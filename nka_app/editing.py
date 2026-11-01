"""Редактирование копии параметров без изменения PARS, MATH и исходного файла."""

from nka_app.common import (
    AGL_REFERENCE_INCLINATION_DEG, INTEGER_FIELDS, I_CP, TIME_FIELDS, copy,
    datetime, math, replace, timedelta, timezone,
)


def edit_parameter(dataset, record, key, text):
    if key not in record.parameters or key in {"prn", "svid"}:
        raise ValueError("Это поле не является редактируемым параметром орбиты.")
    try:
        value = float(text.strip().replace(",", ".").replace("D", "E").replace("d", "e"))
    except ValueError:
        raise ValueError("Введите число; допускаются десятичная запятая и экспонента.") from None
    if not math.isfinite(value):
        raise ValueError("NaN и бесконечность недопустимы.")
    if key in INTEGER_FIELDS:
        if not value.is_integer():
            raise ValueError(f"{key} должен быть целым числом.")
        value = int(value)
    if key in {"e", "eps_a"} and not 0 <= value < (0.2 if key == "eps_a" else 1):
        raise ValueError("Недопустимый эксцентриситет.")
    if key in {"a", "sqrtA"} and not 0 <= value <= (1e9 if key == "a" else 1e5):
        raise ValueError("Недопустимая большая полуось.")
    if key in {"toa", "toe"} and not 0 <= value < 604800:
        raise ValueError("Время GPS-недели должно быть в диапазоне [0, 604800).")
    if key == "ta" and not 0 <= value < 86400:
        raise ValueError("Время суток должно быть в диапазоне [0, 86400).")
    if key == "Na" and not 1 <= value <= 1461:
        raise ValueError("Na должен быть от 1 до 1461.")
    if key in {"wna", "gpsWeekNo"} and not 0 <= value <= 10000:
        raise ValueError("Недопустимый номер GPS-недели.")
    if abs(value) > 1e12:
        raise ValueError("Слишком большое значение параметра.")
    data = copy(record.data)
    parameters = {**record.parameters, key: value}
    if dataset.source == "Rinex alm" and dataset.signal == "L1CA":
        if key == "sqrtA":
            data.a = value ** 2
        elif key in {"w", "m0", "omega0", "omegaDot", "i0"}:
            setattr(data, key, value * math.pi)
        elif hasattr(data, key):
            setattr(data, key, value)
    elif dataset.source == "Rinex alm" and dataset.signal == "L1OF":
        if key == "delta_ia":
            data.delta_ia = value + (AGL_REFERENCE_INCLINATION_DEG - I_CP) / 180.0
        elif hasattr(data, key):
            setattr(data, key, value)
    elif hasattr(data, key):
        setattr(data, key, value)
    epoch = record.epoch
    if key in TIME_FIELDS:
        if dataset.signal == "L1CA":
            if dataset.source == "Rinex eph":
                epoch = (datetime(1980, 1, 6, tzinfo=timezone.utc)
                         + timedelta(weeks=data.gpsWeekNo, seconds=data.toe)).timestamp()
            else:
                epoch = data.wna * 604800 + data.toa
        elif dataset.source == "Rinex alm":
            epoch = (data.Na - 1) * 86400 + data.ta
    error = ""
    if getattr(data, "a", 1) <= 0 or getattr(data, "sqrtA", 1) <= 0:
        error = "В файле отсутствует орбита: большая полуось равна нулю."
    if dataset.signal == "L1OF" and dataset.source == "Rinex eph" and math.hypot(data.x, data.y, data.z) < 1:
        error = "Отсутствует орбита: нулевой радиус-вектор."
    updated = replace(record, data=data, parameters=parameters, epoch=epoch, error=error)
    records = dict(dataset.records)
    records[record.prn] = [updated if r is record else r for r in records[record.prn]]
    records[record.prn].sort(key=lambda r: r.epoch)
    change = {"prn": record.prn, "epoch": record.epoch, "field": key,
              "before": record.parameters[key], "after": value}
    return replace(dataset, records=records, edits=[*dataset.edits, change])
