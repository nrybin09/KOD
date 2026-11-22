"""Обмен BINR с NV08C и преобразование ответов в текущие форматы файлов.

Модуль не изменяет существующие парсеры: принятые сообщения 40h/49h
записываются в те же ``*.ralm*`` и ``*.reph*`` файлы, которые приложение
уже умеет загружать.
"""

from nka_app.common import (
    GPS_WEEK, PROJECT_ROOT, Path, dataclass, datetime, math, struct, timedelta,
    timezone,
)


DLE = 0x10
ETX = 0x03
CRC_MARK = 0xFF
GPS_SYSTEM = 1
GLONASS_SYSTEM = 2
GPS_EPOCH = datetime(1980, 1, 6, tzinfo=timezone.utc)


@dataclass(frozen=True)
class BINRFrame:
    message_id: int
    payload: bytes
    checksum_present: bool = False
    checksum_valid: bool | None = None


@dataclass(frozen=True)
class NV08CRecord:
    """Одна принятая запись альманаха или эфемерид."""

    kind: str
    system: int
    prn: int
    fields: dict


def crc16_binr(data: bytes) -> int:
    """CRC-16/CCITT из приложения A протокола NV08C, начальное значение 0."""

    crc = 0
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else crc << 1
            crc &= 0xFFFF
    return crc


def build_binr_message(message_id: int, payload: bytes = b"", checksum: bool = False) -> bytes:
    """Сформировать BINR-сообщение с экранированием байта DLE."""

    if message_id in (DLE, ETX, CRC_MARK) or not 0 <= message_id <= 0xFF:
        raise ValueError("Недопустимый идентификатор сообщения BINR.")
    payload = bytes(payload)
    stuffed = payload.replace(bytes((DLE,)), bytes((DLE, DLE)))
    message = bytearray((DLE, message_id))
    message.extend(stuffed)
    if checksum:
        value = crc16_binr(bytes((message_id,)) + stuffed)
        message.extend((DLE, CRC_MARK))
        message.extend(struct.pack("<H", value))
    message.extend((DLE, ETX))
    return bytes(message)


class BINRStreamParser:
    """Потоковый разбор BINR: поддерживает фрагменты и несколько пакетов подряд."""

    def __init__(self):
        self._buffer = bytearray()

    def feed(self, chunk: bytes) -> list[BINRFrame]:
        self._buffer.extend(chunk)
        frames = []
        while True:
            start = self._buffer.find(bytes((DLE,)))
            if start < 0:
                self._buffer.clear()
                break
            if start:
                del self._buffer[:start]
            if len(self._buffer) < 2:
                break
            message_id = self._buffer[1]
            if message_id in (DLE, ETX, CRC_MARK):
                del self._buffer[0]
                continue

            payload = bytearray()
            crc_bytes = bytearray((message_id,))
            index = 2
            malformed = False
            while True:
                if index >= len(self._buffer):
                    return frames
                value = self._buffer[index]
                if value != DLE:
                    payload.append(value)
                    crc_bytes.append(value)
                    index += 1
                    continue
                if index + 1 >= len(self._buffer):
                    return frames
                code = self._buffer[index + 1]
                if code == DLE:
                    payload.append(DLE)
                    crc_bytes.extend((DLE, DLE))
                    index += 2
                    continue
                if code == ETX:
                    frames.append(BINRFrame(message_id, bytes(payload)))
                    del self._buffer[:index + 2]
                    break
                if code == CRC_MARK:
                    if index + 6 > len(self._buffer):
                        return frames
                    if self._buffer[index + 4:index + 6] != bytes((DLE, ETX)):
                        malformed = True
                        break
                    received = struct.unpack_from("<H", self._buffer, index + 2)[0]
                    calculated = crc16_binr(bytes(crc_bytes))
                    frames.append(BINRFrame(message_id, bytes(payload), True, received == calculated))
                    del self._buffer[:index + 6]
                    break
                malformed = True
                break
            if malformed:
                del self._buffer[0]
        return frames


def request_almanac(system: int, prn: int) -> bytes:
    if system not in (GPS_SYSTEM, GLONASS_SYSTEM):
        raise ValueError("Неизвестная спутниковая система.")
    limit = 32 if system == GPS_SYSTEM else 24
    if not 1 <= prn <= limit:
        raise ValueError("Недопустимый номер НКА.")
    return build_binr_message(0x20, bytes((system, prn)))


def request_all_ephemerides(enabled: bool = True) -> bytes:
    return build_binr_message(0x19, bytes((0xFF, int(enabled))))


def request_ephemeris(system: int, prn: int) -> bytes:
    """Запросить эфемериды одного НКА только выбранной системы."""

    if system not in (GPS_SYSTEM, GLONASS_SYSTEM):
        raise ValueError("Неизвестная спутниковая система.")
    limit = 32 if system == GPS_SYSTEM else 24
    if not 1 <= prn <= limit:
        raise ValueError("Недопустимый номер НКА.")
    return build_binr_message(0x19, bytes((system, prn)))


def _u8(data, offset):
    return struct.unpack_from("<B", data, offset)[0]


def _i8(data, offset):
    return struct.unpack_from("<b", data, offset)[0]


def _u16(data, offset):
    return struct.unpack_from("<H", data, offset)[0]


def _f32(data, offset):
    return struct.unpack_from("<f", data, offset)[0]


def _f64(data, offset):
    return struct.unpack_from("<d", data, offset)[0]


def _f80(data: bytes, offset: int) -> float:
    """Прочитать little-endian IEEE 754 extended (10 байт), используемый в 40h."""

    raw = data[offset:offset + 10]
    if len(raw) != 10:
        raise ValueError("Неполное значение FP80.")
    significand = int.from_bytes(raw[:8], "little")
    sign_exponent = int.from_bytes(raw[8:], "little")
    sign = -1.0 if sign_exponent & 0x8000 else 1.0
    exponent = sign_exponent & 0x7FFF
    if exponent == 0 and significand == 0:
        return math.copysign(0.0, sign)
    if exponent == 0x7FFF:
        return math.copysign(math.inf, sign) if significand == 1 << 63 else math.nan
    power = exponent - 16383 if exponent else 1 - 16383
    return sign * math.ldexp(significand / float(1 << 63), power)


def decode_almanac(payload: bytes) -> NV08CRecord | None:
    """Разобрать данные ответного сообщения 40h."""

    if len(payload) == 2:
        return None
    if not payload:
        raise ValueError("Пустое сообщение 40h.")
    system = _u8(payload, 0)
    if system == GPS_SYSTEM:
        if len(payload) != 60:
            raise ValueError(f"Сообщение 40h GPS должно содержать 60 байт, получено {len(payload)}.")
        fields = {
            "health": _u8(payload, 2),
            "broadcast_prn": _u8(payload, 3),
            "e": _f32(payload, 4),
            "i0": _f32(payload, 8),
            "omega_dot": _f32(payload, 12),
            "sqrt_a": _f64(payload, 16),
            "omega0": _f32(payload, 24),
            "omega": _f32(payload, 28),
            "m0": _f32(payload, 32),
            "af0": _f32(payload, 36),
            "af1": _f32(payload, 40),
            "af0_high": _f32(payload, 44),
            "toa": _f80(payload, 48),
            "week": _u16(payload, 58),
        }
        prn = _u8(payload, 1)
    elif system == GLONASS_SYSTEM:
        if len(payload) != 42:
            raise ValueError(f"Сообщение 40h ГЛОНАСС должно содержать 42 байта, получено {len(payload)}.")
        encoded_slot = _u8(payload, 3)
        fields = {
            "health": _u8(payload, 2),
            "freq_no": encoded_slot - 32 if encoded_slot >= 25 else encoded_slot,
            "tau": _f32(payload, 4),
            "lambda_a": _f32(payload, 8),
            "inclination": _f32(payload, 12),
            "e": _f32(payload, 16),
            "omega": _f32(payload, 20),
            "ta": _f32(payload, 24),
            "period": _f64(payload, 28),
            "period_dot": _f32(payload, 36),
            "na": _u16(payload, 40),
        }
        prn = _u8(payload, 1)
    else:
        raise ValueError(f"Неизвестная спутниковая система в сообщении 40h: {system}.")
    return NV08CRecord("alm", system, prn, fields)


def decode_ephemeris(payload: bytes) -> NV08CRecord | None:
    """Разобрать данные ответного сообщения 49h."""

    if len(payload) == 2:
        return None
    if not payload:
        raise ValueError("Пустое сообщение 49h.")
    system = _u8(payload, 0)
    if system == GPS_SYSTEM:
        if len(payload) != 130:
            raise ValueError(f"Сообщение 49h GPS должно содержать 130 байт, получено {len(payload)}.")
        fields = {
            "crs": _f32(payload, 2), "delta_n": _f32(payload, 6),
            "m0": _f64(payload, 10), "cuc": _f32(payload, 18),
            "e": _f64(payload, 22), "cus": _f32(payload, 30),
            "sqrt_a": _f64(payload, 34), "toe": _f64(payload, 42),
            "cic": _f32(payload, 50), "omega0": _f64(payload, 54),
            "cis": _f32(payload, 62), "i0": _f64(payload, 66),
            "crc": _f32(payload, 74), "omega": _f64(payload, 78),
            "omega_dot": _f64(payload, 86), "idot": _f64(payload, 94),
            "tgd": _f32(payload, 102), "toc": _f64(payload, 106),
            "af2": _f32(payload, 114), "af1": _f32(payload, 118),
            "af0": _f32(payload, 122), "ura": _u16(payload, 126),
            "iode": _u16(payload, 128),
        }
        prn = _u8(payload, 1)
    elif system == GLONASS_SYSTEM:
        if len(payload) != 93:
            raise ValueError(f"Сообщение 49h ГЛОНАСС должно содержать 93 байта, получено {len(payload)}.")
        fields = {
            "freq_no": _i8(payload, 2),
            "x": _f64(payload, 3), "y": _f64(payload, 11), "z": _f64(payload, 19),
            "vx": _f64(payload, 27), "vy": _f64(payload, 35), "vz": _f64(payload, 43),
            "ax": _f64(payload, 51), "ay": _f64(payload, 59), "az": _f64(payload, 67),
            "tb": _f64(payload, 75), "gamma": _f32(payload, 83),
            "tau": _f32(payload, 87), "age": _u16(payload, 91),
        }
        prn = _u8(payload, 1)
    else:
        raise ValueError(f"Неизвестная спутниковая система в сообщении 49h: {system}.")
    return NV08CRecord("eph", system, prn, fields)


def decode_navigation_frame(frame: BINRFrame) -> NV08CRecord | None:
    if frame.checksum_present and not frame.checksum_valid:
        raise ValueError("Контрольная сумма принятого BINR-пакета не совпала.")
    if frame.message_id == 0x40:
        return decode_almanac(frame.payload)
    if frame.message_id == 0x49:
        return decode_ephemeris(frame.payload)
    return None


def _gps_week(now: datetime) -> int:
    return int((now - GPS_EPOCH).total_seconds() // GPS_WEEK)


def _expand_almanac_week(value: int, now: datetime) -> int:
    base = 1024 + int(value)
    return base + 1024 * round((_gps_week(now) - base) / 1024)


def _gps_moment(milliseconds: float, week: int, now: datetime) -> datetime:
    candidates = [
        GPS_EPOCH + timedelta(weeks=week + shift, milliseconds=milliseconds)
        for shift in (-1, 0, 1)
    ]
    return min(candidates, key=lambda value: abs((value - now).total_seconds()))


def _glonass_moment(milliseconds: float, now: datetime) -> datetime:
    # В сообщении tb используется шкала ГЛОНАСС (UTC(SU)+3 ч), а эпоха RINEX
    # записывается в UTC. Выбираем ближайшие к текущему времени сутки.
    utc_seconds = milliseconds / 1000.0 - 3 * 3600
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    candidates = [midnight + timedelta(days=shift, seconds=utc_seconds) for shift in (-1, 0, 1)]
    return min(candidates, key=lambda value: abs((value - now).total_seconds()))


def _d(value: float) -> str:
    return f"{float(value):19.12E}".replace("E", "D")


def _epoch_prefix(system: str, prn: int, moment: datetime) -> str:
    return (f"{system}{prn:02d} {moment.year:04d} {moment.month:02d} {moment.day:02d} "
            f"{moment.hour:02d} {moment.minute:02d} {moment.second:02d}")


def _rinex_header(signal: str, now: datetime) -> str:
    if signal == "L1CA":
        first = "     3.02           N: GNSS NAV DATA    G: GPS              RINEX VERSION / TYPE"
    else:
        first = "     3.02           N: GNSS NAV DATA    R: GLONASS          RINEX VERSION / TYPE"
    stamp = now.strftime("%Y%m%d %H%M%S UTC")
    return f"{first}\nNV08C                                      {stamp} PGM / RUN BY / DATE\n" \
           "                                                            END OF HEADER\n"


def _gps_ephemeris_text(records: list[NV08CRecord], now: datetime) -> str:
    week = _gps_week(now)
    lines = [_rinex_header("L1CA", now)]
    for record in records:
        f = record.fields
        moment = _gps_moment(f["toc"], week, now)
        toe = f["toe"] / 1000.0
        toc = f["toc"] / 1000.0
        values = (
            (f["af0"] / 1000.0, f["af1"], f["af2"] * 1000.0),
            (f["iode"], f["crs"], f["delta_n"] * 1000.0, f["m0"]),
            (f["cuc"], f["e"], f["cus"], f["sqrt_a"]),
            (toe, f["cic"], f["omega0"], f["cis"]),
            (f["i0"], f["crc"], f["omega"], f["omega_dot"] * 1000.0),
            (f["idot"] * 1000.0, 0.0, week, 0.0),
            (f["ura"], 0.0, f["tgd"] / 1000.0, f["iode"]),
            (toc, 0.0),
        )
        lines.append(_epoch_prefix("G", record.prn, moment) + "".join(_d(v) for v in values[0]) + "\n")
        lines.extend("    " + "".join(_d(v) for v in row) + "\n" for row in values[1:])
    return "".join(lines)


def _glonass_ephemeris_text(records: list[NV08CRecord], now: datetime) -> str:
    lines = [_rinex_header("L1OF", now)]
    for record in records:
        f = record.fields
        moment = _glonass_moment(f["tb"], now)
        first = (-f["tau"] / 1000.0, f["gamma"], f["tb"] / 1000.0)
        rows = (
            (f["x"] / 1000.0, f["vx"], f["ax"] * 1000.0, 0.0),
            (f["y"] / 1000.0, f["vy"], f["ay"] * 1000.0, f["freq_no"]),
            (f["z"] / 1000.0, f["vz"], f["az"] * 1000.0, f["age"]),
        )
        lines.append(_epoch_prefix("R", record.prn, moment) + "".join(_d(v) for v in first) + "\n")
        lines.extend("    " + "".join(_d(v) for v in row) + "\n" for row in rows)
    return "".join(lines)


def _gps_almanac_text(records: list[NV08CRecord], now: datetime) -> str:
    lines = []
    receive_seconds = now.hour * 3600 + now.minute * 60 + now.second
    for record in records:
        f = record.fields
        week = _expand_almanac_week(f["week"], now)
        toa = f["toa"] / 1000.0
        moment = GPS_EPOCH + timedelta(weeks=week, seconds=toa)
        day_seconds = moment.hour * 3600 + moment.minute * 60 + moment.second
        main = (
            record.prn, f["health"], week, toa, moment.day, moment.month, moment.year,
            day_seconds, f["af0"] / 1000.0, f["af1"], f["omega_dot"] * 1000.0 / math.pi,
        )
        orbit = (
            f["omega0"] / math.pi, f["i0"] / math.pi, f["m0"] / math.pi,
            f["e"], f["sqrt_a"], f["omega"] / math.pi,
        )
        lines.append(f"{now.day:02d} {now.month:02d} {now.year:04d} {receive_seconds}\n")
        lines.append(" ".join(f"{v:.15g}" for v in main) + "\n")
        lines.append(" ".join(f"{v:.15g}" for v in orbit) + "\n")
    return "".join(lines)


def _glonass_almanac_text(records: list[NV08CRecord], now: datetime) -> str:
    lines = []
    receive_seconds = now.hour * 3600 + now.minute * 60 + now.second
    cycle_start_year = now.year - (now.year - 1996) % 4
    for record in records:
        f = record.fields
        day = datetime(cycle_start_year, 1, 1, tzinfo=timezone.utc) + timedelta(days=f["na"] - 1)
        ta = f["ta"] / 1000.0
        main = (
            record.prn, f["freq_no"], f["health"], day.day, day.month, day.year,
            ta, 0.0, 0.0, f["tau"] / 1000.0,
        )
        delta_i_from_63 = f["inclination"] / math.pi - 63.0 / 180.0
        orbit = (
            f["lambda_a"] / math.pi, delta_i_from_63, f["omega"] / math.pi,
            f["e"], f["period"] / 1000.0 - 40544.0, f["period_dot"] / 1000.0,
        )
        lines.append(f"{now.day:02d} {now.month:02d} {now.year:04d} {receive_seconds}\n")
        lines.append(" ".join(f"{v:.15g}" for v in main) + "\n")
        lines.append(" ".join(f"{v:.15g}" for v in orbit) + "\n")
    return "".join(lines)


def nv08c_extension(kind: str, signal: str) -> str:
    mapping = {
        ("eph", "L1CA"): "rephl1ca", ("eph", "L1OF"): "rephl1of",
        ("alm", "L1CA"): "ralml1ca", ("alm", "L1OF"): "ralml1of",
    }
    try:
        return mapping[(kind, signal)]
    except KeyError as exc:
        raise ValueError("Неизвестный тип данных NV08C или сигнал.") from exc


def nv08c_output_directory(kind: str, signal: str) -> Path:
    system = "GPS" if signal == "L1CA" else "GLONASS"
    return PROJECT_ROOT / "data" / "NV08C" / kind / system


def _unique_output_path(kind: str, signal: str, now: datetime) -> Path:
    folder = nv08c_output_directory(kind, signal)
    extension = nv08c_extension(kind, signal)
    stem = "NV08C_" + now.strftime("%Y%m%d_%H%M%S")
    candidate = folder / f"{stem}.{extension}"
    index = 1
    while candidate.exists():
        candidate = folder / f"{stem}_{index:02d}.{extension}"
        index += 1
    return candidate


def write_nv08c_file(records, kind: str, signal: str, path=None, now=None) -> Path:
    """Записать принятые записи в формат существующего парсера."""

    now = now or datetime.now(timezone.utc)
    records = sorted(
        (record for record in records
         if record.kind == kind and record.system == (GPS_SYSTEM if signal == "L1CA" else GLONASS_SYSTEM)),
        key=lambda record: record.prn,
    )
    if not records:
        raise ValueError("Нет полученных данных NV08C для записи.")
    extension = nv08c_extension(kind, signal)
    destination = Path(path) if path is not None else _unique_output_path(kind, signal, now)
    if destination.suffix.lower() != "." + extension:
        raise ValueError(f"Ожидается расширение .{extension}.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if kind == "eph" and signal == "L1CA":
        text = _gps_ephemeris_text(records, now)
    elif kind == "eph":
        text = _glonass_ephemeris_text(records, now)
    elif signal == "L1CA":
        text = _gps_almanac_text(records, now)
    else:
        text = _glonass_almanac_text(records, now)
    destination.write_text(text, encoding="utf-8")
    return destination
