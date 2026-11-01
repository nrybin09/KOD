from nka_app.common import AGL_REFERENCE_INCLINATION_DEG, I_CP, dataclass, datetime


@dataclass
class AlmGln:
    ta : float           # время узлового момента альманаха, [сек]
    Na : int             # календарный номер суток внутри четырехлетнего интервала соответствующий узловому моменту альманаха
    delta_ia : float     # коррекция наклонения, [рад]
    delta_Ta : float     # поправка к драконическому периоду, [сек]
    delta_Ta_dot : float # поправка к драконическому периоду, [сек/виток]
    eps_a : float        # эксцентриситет
    w_a : float          # аргумент перигея, [рад]
    lambda_a : float     # долгота восходящего узла, [рад]

def _integer(value, name, record_number):
    """Прочитать целое поле без молчаливого отбрасывания дробной части."""
    value = float(value)
    if not value.is_integer():
        raise ValueError(f"Запись {record_number}: поле {name} должно быть целым.")
    return int(value)


def _day_in_four_year_interval(day, month, year, record_number):
    """Получить прежний параметр Na из календарной даты новой AGL-записи."""
    try:
        moment = datetime(year, month, day)
    except ValueError as exc:
        raise ValueError(f"Запись {record_number}: недопустимая календарная дата AGL.") from exc
    start_year = year - (year - 1996) % 4
    return (moment - datetime(start_year, 1, 1)).days + 1


def readAlmGln(filename: str) -> list[AlmGln]:
    """Прочитать альманах ГЛОНАСС ИАЦ с расширением ``*.ralml1of``.

    Содержимое соответствует трёхстрочной структуре AGL. Поля ``AlmGln``
    не меняются. Календарная дата преобразуется в прежний ``Na``,
    а dI из AGL — в поправку к I_CP, которую ожидает расчётный модуль.
    """
    with open(filename, "r", encoding="utf-8-sig") as stream:
        lines = [line.strip() for line in stream if line.strip()]

    if not lines or len(lines) % 3:
        raise ValueError("Неполная запись альманаха ГЛОНАСС: каждая запись должна содержать три строки.")

    almArray = []
    for index in range(0, len(lines), 3):
        record_number = index // 3 + 1
        date_values = lines[index].split()
        main_values = lines[index + 1].split()
        orbit_values = lines[index + 2].split()
        if len(date_values) < 4 or len(main_values) != 10 or len(orbit_values) != 6:
            raise ValueError(
                f"Запись {record_number}: ожидаются строки минимум с 4, затем с 10 и 6 полями."
            )
        try:
            list(map(float, date_values[:4]))
            main = list(map(float, main_values))
            orbit = list(map(float, orbit_values))
        except ValueError as exc:
            raise ValueError(f"Запись {record_number}: найдено нечисловое поле альманаха.") from exc

        day = _integer(main[3], "day", record_number)
        month = _integer(main[4], "month", record_number)
        year = _integer(main[5], "year", record_number)
        na = _day_in_four_year_interval(day, month, year, record_number)

        # В AGL dI задан относительно 63°, а расчётный модуль хранит поправку
        # относительно I_CP. Обе величины здесь выражены в полуциклах.
        delta_i_for_math = orbit[1] + (AGL_REFERENCE_INCLINATION_DEG - I_CP) / 180.0
        almArray.append(AlmGln(
            ta=main[6],
            Na=na,
            delta_ia=delta_i_for_math,
            delta_Ta=orbit[4],
            delta_Ta_dot=orbit[5],
            eps_a=orbit[3],
            w_a=orbit[2],
            lambda_a=orbit[0],
        ))

    return almArray
