from nka_app.common import dataclass, np


@dataclass
class AlmGps:
    svid : int
    toa : int
    wna : int
    a : float
    e : float
    w : float
    m0 : float
    omega0 : float
    omegaDot : float
    i0 : float
    af0 : float
    af1 : float
    svHealth : int

def _integer(value, name, record_number):
    """Прочитать целое поле без молчаливого отбрасывания дробной части."""
    value = float(value)
    if not value.is_integer():
        raise ValueError(f"Запись {record_number}: поле {name} должно быть целым.")
    return int(value)


def readAlmGps(filename: str) -> list[AlmGps]:
    """Прочитать GPS-альманах ИАЦ с расширением ``*.ralml1ca``.

    Содержимое соответствует трёхстрочной структуре AGP. Имена полей
    ``AlmGps`` оставлены прежними. Формат хранит углы в
    полуциклах и ``sqrt(A)``, поэтому здесь они сразу переводятся в радианы и
    большую полуось в метрах — именно эти единицы использует расчётный модуль.
    """
    with open(filename, "r", encoding="utf-8-sig") as stream:
        lines = [line.strip() for line in stream if line.strip()]

    if not lines or len(lines) % 3:
        raise ValueError("Неполная запись GPS-альманаха: каждая запись должна содержать три строки.")

    almArray = []
    for index in range(0, len(lines), 3):
        record_number = index // 3 + 1
        date_values = lines[index].split()
        main_values = lines[index + 1].split()
        orbit_values = lines[index + 2].split()
        if len(date_values) < 4 or len(main_values) != 11 or len(orbit_values) != 6:
            raise ValueError(
                f"Запись {record_number}: ожидаются строки минимум с 4, затем с 11 и 6 полями."
            )
        try:
            # Первые четыре поля проверяются, хотя дата при расчёте берётся из WN/toa.
            list(map(float, date_values[:4]))
            main = list(map(float, main_values))
            orbit = list(map(float, orbit_values))
        except ValueError as exc:
            raise ValueError(f"Запись {record_number}: найдено нечисловое поле альманаха.") from exc

        sqrt_a = orbit[4]
        almArray.append(AlmGps(
            svid=_integer(main[0], "svid", record_number),
            toa=_integer(main[3], "toa", record_number),
            wna=_integer(main[2], "wna", record_number),
            a=sqrt_a ** 2,
            e=orbit[3],
            w=orbit[5] * np.pi,
            m0=orbit[2] * np.pi,
            omega0=orbit[0] * np.pi,
            omegaDot=main[10] * np.pi,
            i0=orbit[1] * np.pi,
            af0=main[8],
            af1=main[9],
            svHealth=_integer(main[1], "svHealth", record_number),
        ))

    return almArray
