"""Адаптер парсеров и спутниковых расчётов.

Числовые поля эфемерид читает исходный rinex_get_nav_*; адаптер добавляет
дату/время и строит записи без потери повторных PRN в разных эпохах.
"""

from nka_app.common import (
    GLO_FIELDS, GPS_FIELDS, SIGNALS, SOURCES, Path, copy, datetime, math, np,
    timedelta, timezone,
)

from nka_app.models import Dataset, NavRecord, Sample
from nka_app.coordinates import azimuth_elevation
from nka_app.parse_alm_gps import readAlmGps
from nka_app.parse_alm_glonass import readAlmGln
from nka_app.parse_eph_gps import GPSRec, rinex_get_nav_gps
from nka_app.parse_eph_glonass import GloRec, rinex_get_nav_glonass
from nka_app.math_alm_gps import calc_gps_from_alm
from nka_app.math_alm_glonass import calc_gln_from_alm
from nka_app.math_eph_gps import ecef_from_eph
from nka_app.math_eph_glonass import glo_ecef_from_icd

def format_extension(source, signal):
    """Расширение входного файла для выбранных источника и сигнала."""
    if source not in SOURCES or signal not in SIGNALS:
        raise ValueError("Неизвестный источник или сигнал.")
    prefix = "r" if source.startswith("Rinex") else "n"
    return prefix + source.split()[1] + signal.lower()


def file_filter(source, signal):
    extension = format_extension(source, signal)
    return f"{source} / {signal} (*.{extension})"


def _nonempty(path):
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        # Новые RINEX-файлы могут содержать русскую строку заголовка в Windows-1251.
        text = raw.decode("cp1251")
    return [line for line in text.splitlines() if line.strip()]


def _rinex_epochs(path, signal):
    lines = _nonempty(path)
    if not lines or "RINEX VERSION / TYPE" not in lines[0]:
        raise ValueError("Не найден заголовок RINEX. Проверьте источник и сигнал.")
    version = float(lines[0][:9])
    if not 2 <= version < 4:
        raise ValueError("Существующие парсеры подключены для отдельных файлов RINEX 2/3.")
    if version < 3:
        is_glo = "GLONASS" in lines[0].upper() or lines[0][20:21] == "G"
        if is_glo != (signal == "L1OF"):
            raise ValueError("Система в заголовке не соответствует выбранному сигналу.")
    header_end = next((i for i, ln in enumerate(lines) if "END OF HEADER" in ln), None)
    if header_end is None:
        raise ValueError("Отсутствует END OF HEADER.")
    body = lines[header_end + 1:]
    size = 8 if signal == "L1CA" else 4
    if not body or len(body) % size:
        raise ValueError("Неполный блок эфемерид или смешанный файл. Нужен отдельный GPS/ГЛОНАСС файл.")
    result = []
    for i in range(0, len(body), size):
        line = body[i]
        v3 = line[0].isalpha()
        if v3 and line[0] != ("G" if signal == "L1CA" else "R"):
            raise ValueError("Смешанные RINEX не поддерживаются исходными парсерами. Выберите отдельный файл.")
        prefix = line[4:23] if v3 else line[3:22]
        fields = prefix.split()
        if len(fields) != 6:
            raise ValueError(f"Не удалось прочитать дату записи {i // size + 1}.")
        year, month, day, hour, minute = map(int, fields[:5])
        if year < 100:
            year += 2000 if year < 80 else 1900
        result.append(datetime(year, month, day, hour, minute, tzinfo=timezone.utc)
                      + timedelta(seconds=float(fields[5])))
    return result


def load_dataset(filename, source, signal):
    if source not in SOURCES or signal not in SIGNALS:
        raise ValueError("Неизвестный источник или сигнал.")
    if source.startswith("NV08C"):
        raise NotImplementedError("NV08C добавлен в список. Парсер и расчёт для этого формата пока не реализованы.")
    path = Path(filename)
    expected_extension = "." + format_extension(source, signal)
    if path.suffix.lower() != expected_extension:
        raise ValueError(f"Для {source} / {signal} требуется файл формата *{expected_extension}.")
    records = {}

    def add(prn, epoch, data, parameters, file_epoch=None):
        prn = int(prn)
        if not 1 <= prn <= 99:
            raise ValueError(f"Недопустимый номер НКА: {prn}.")
        if not math.isfinite(epoch) or not all(math.isfinite(float(v)) for v in parameters.values()):
            raise ValueError(f"НКА {prn}: параметры содержат NaN или бесконечность.")
        error = ""
        if hasattr(data, "e") and not 0 <= data.e < 1:
            error = "Эксцентриситет должен быть в [0, 1)."
        if hasattr(data, "eps_a") and not 0 <= data.eps_a < 0.2:
            error = "Неподдерживаемый эксцентриситет альманаха ГЛОНАСС."
        if (hasattr(data, "a") and data.a <= 0) or (hasattr(data, "sqrtA") and data.sqrtA <= 0):
            error = "В файле отсутствует орбита: большая полуось равна нулю."
        if isinstance(data, GloRec) and np.linalg.norm([data.x, data.y, data.z]) < 1:
            error = "В файле отсутствует орбита: нулевой радиус-вектор."
        records.setdefault(prn, []).append(NavRecord(prn, epoch, data, parameters, error, file_epoch))

    notes = []
    if source == "Rinex eph":
        dates = _rinex_epochs(path, signal)
        gps = signal == "L1CA"
        columns = (rinex_get_nav_gps if gps else rinex_get_nav_glonass)(str(path))
        if not columns or len(columns[0]) != len(dates):
            raise ValueError("Число записей исходного парсера не совпадает с числом эпох.")
        fields = GPS_FIELDS if gps else GLO_FIELDS
        for index, date in enumerate(dates):
            data = GPSRec() if gps else GloRec()
            parameters = {key: col[index] for key, col in zip(fields, columns)}
            for key, value in parameters.items():
                setattr(data, key, value)
            if gps:
                epoch = (datetime(1980, 1, 6, tzinfo=timezone.utc)
                         + timedelta(weeks=int(data.gpsWeekNo), seconds=data.toe)).timestamp()
            else:
                # RINEX tb в исходном парсере — время сообщения, а XYZ относятся
                # к календарной эпохе строки. Сохраняем оба значения раздельно.
                epoch = date.timestamp()
            add(data.prn, epoch, data, parameters, date.timestamp())
        time_system = "GPS" if gps else "UTC"
        calendar = True
    else:
        lines = _nonempty(path)
        group_size = 3
        if not lines or len(lines) % group_size:
            raise ValueError("Неполная запись альманаха. Проверьте выбранный сигнал.")
        expected_columns = (4, 11, 6) if signal == "L1CA" else (4, 10, 6)
        if any(
            len(line.split()) < expected_columns[0] if i % group_size == 0
            else len(line.split()) != expected_columns[i % group_size]
            for i, line in enumerate(lines)
        ):
            raise ValueError(f"Альманах не соответствует структуре формата *{expected_extension}.")
        if signal == "L1CA":
            for index, data in enumerate(readAlmGps(str(path))):
                if not 0 <= data.toa < 604800 or data.wna < 0:
                    raise ValueError("Недопустимые GPS-неделя или toa.")
                header = list(map(float, lines[index * 3].split()[:4]))
                metadata = list(map(float, lines[index * 3 + 1].split()))
                orbit = list(map(float, lines[index * 3 + 2].split()))
                # В таблицу передаются все исходные числа и именно в порядке файла.
                # Преобразованные радианы и A=sqrtA² хранятся только в data для расчёта.
                parameters = {
                    "alm_day": header[0], "alm_month": header[1],
                    "alm_year": header[2], "receive_time": header[3],
                    "svid": metadata[0], "svHealth": metadata[1],
                    "wna": metadata[2], "toa": metadata[3],
                    "day": metadata[4], "month": metadata[5], "year": metadata[6],
                    "day_time": metadata[7], "af0": metadata[8], "af1": metadata[9],
                    "omegaDot": metadata[10], "omega0": orbit[0], "i0": orbit[1],
                    "m0": orbit[2], "e": orbit[3], "sqrtA": orbit[4], "w": orbit[5],
                }
                add(data.svid, data.wna * 604800 + data.toa, data, parameters)
            notes.append("Номер GPS-недели показан как в файле; неоднозначность rollover не устраняется автоматически.")
        else:
            for index, data in enumerate(readAlmGln(str(path))):
                metadata = list(map(float, lines[index * 3 + 1].split()))
                if not 1 <= data.Na <= 1461 or not 0 <= data.ta < 86400:
                    raise ValueError("Недопустимые Na или ta альманаха ГЛОНАСС.")
                header = list(map(float, lines[index * 3].split()[:4]))
                orbit = list(map(float, lines[index * 3 + 2].split()))
                parameters = {
                    "alm_day": header[0], "alm_month": header[1],
                    "alm_year": header[2], "receive_time": header[3],
                    "svid": metadata[0], "freqNo": metadata[1], "health": metadata[2],
                    "day": metadata[3], "month": metadata[4], "year": metadata[5],
                    "ta": metadata[6], "glo_utc": metadata[7],
                    "gps_glo": metadata[8], "clock": metadata[9],
                    "lambda_a": orbit[0], "delta_ia": orbit[1], "w_a": orbit[2],
                    "eps_a": orbit[3], "delta_Ta": orbit[4], "delta_Ta_dot": orbit[5],
                }
                add(metadata[0], (data.Na - 1) * 86400 + data.ta, data, parameters)
            notes.append("В альманахе нет N4: задайте четырёхлетний интервал вручную; дата показана номером суток.")
        time_system = "GPS" if signal == "L1CA" else "ГЛОНАСС"
        calendar = False
    if not records:
        raise ValueError("В файле нет записей спутников выбранной системы.")
    for values in records.values():
        values.sort(key=lambda r: r.epoch)
    if signal == "L1OF":
        notes.append("PZ90 трактуется как ПЗ-90.02. Формулы расчёта сохранены.")
    dataset = Dataset(path, source, signal, records, time_system, calendar, notes)
    unavailable = sorted(set(dataset.satellites) - set(dataset.available_satellites))
    if unavailable:
        notes.append("Без орбитальных данных, только просмотр: НКА " + ", ".join(map(str, unavailable)) + ".")
    return dataset


def state_vector(dataset, record, epoch, n4=1):
    if record.error:
        raise ValueError(f"НКА {record.prn}: {record.error}")
    data = record.data
    if dataset.source == "Rinex alm":
        if dataset.signal == "L1CA":
            result = calc_gps_from_alm(data, data.toa + epoch - record.epoch)
        else:
            cycle_days = 1460 if n4 == 27 else 1461
            day, seconds = divmod(epoch, 86400)
            task = {"N": int(day) % cycle_days + 1, "N4": n4, "time_glo": seconds}
            result = calc_gln_from_alm(data, task)
        position = np.array([result[k] for k in ("x", "y", "z")])
        velocity = np.array([result[k] for k in ("vx", "vy", "vz")])
    else:
        if dataset.signal == "L1CA":
            relative_t = data.toe + epoch - record.epoch
            calculate = lambda t: ecef_from_eph(data, t)
        else:
            local = copy(data)
            local.tb = 0.0
            relative_t = epoch - record.epoch
            # Исходная функция предоставляет шаг интегрирования аргументом.
            # 30 с — только внутренний шаг RK4; не шаг эксперимента.
            calculate = lambda t: glo_ecef_from_icd(local, t, step_s=30.0)
        position = calculate(relative_t)
        # Центральная разность в одной и той же записи, без смены эфемериды.
        velocity = (calculate(relative_t + 0.5) - calculate(relative_t - 0.5)) / 1.0
    if not np.all(np.isfinite(np.r_[position, velocity])):
        raise ValueError(f"НКА {record.prn}: расчёт дал неконечные значения.")
    return position, velocity


def calculate_sample(dataset, observer, prn, epoch, dt, n4=1):
    record = dataset.nearest(prn, epoch)
    xyz, velocity = state_vector(dataset, record, epoch, n4)
    az, el = azimuth_elevation(xyz, observer, dataset.datum)
    return Sample(float(dt), az, el, *map(float, xyz), *map(float, velocity), float(np.linalg.norm(xyz)))
