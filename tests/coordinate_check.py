"""Интерактивная проверка прямого и обратного преобразования координат.

Запуск из корня проекта:

    python -m tests.coordinate_check

Каждое нажатие Enter создаёт новую случайную точку и выполняет следующий
переход. Сначала проверяются основные переходы, затем дополнительные.
После основных переходов выводится сводка их погрешностей.
"""

from nka_app.common import np, random

from nka_app.coordinates import blh_to_xyz, transform_xyz, xyz_to_blh


# Диапазоны генератора случайных геодезических координат.
# Полюса не используются, потому что непосредственно на полюсе долгота
# геометрически не определена.
MIN_LATITUDE_DEG = -89.0
MAX_LATITUDE_DEG = 89.0
MIN_LONGITUDE_DEG = -180.0
MAX_LONGITUDE_DEG = 180.0
MIN_HEIGHT_M = -1000.0
MAX_HEIGHT_M = 50000.0

# Допустимая пространственная погрешность преобразования туда и обратно: 1 мм.
TOLERANCE_M = 0.001

# Четыре представления координат, используемые программой.
REPRESENTATIONS = (
    ("WGS84", "BLH"),
    ("WGS84", "XYZ"),
    ("PZ90", "BLH"),
    ("PZ90", "XYZ"),
)

# Основные переходы непосредственно вызываются рабочей программой:
# BLH <-> XYZ внутри каждого эллипсоида и XYZ <-> XYZ между эллипсоидами.
MAIN_TRANSITIONS = (
    (("WGS84", "BLH"), ("WGS84", "XYZ")),
    (("WGS84", "XYZ"), ("WGS84", "BLH")),
    (("PZ90", "BLH"), ("PZ90", "XYZ")),
    (("PZ90", "XYZ"), ("PZ90", "BLH")),
    (("WGS84", "XYZ"), ("PZ90", "XYZ")),
    (("PZ90", "XYZ"), ("WGS84", "XYZ")),
)

# Эти переходы возможны, но в основном коде не вызываются одной операцией.
# Они составляются из двух или трёх основных преобразований.
ADDITIONAL_TRANSITIONS = tuple(
    (source, target)
    for source in REPRESENTATIONS
    for target in REPRESENTATIONS
    if source != target and (source, target) not in MAIN_TRANSITIONS
)
TRANSITIONS = MAIN_TRANSITIONS + ADDITIONAL_TRANSITIONS


def representation_name(representation):
    """Понятное название системы и формата координат."""
    datum, mode = representation
    datum_name = "ПЗ-90.02" if datum == "PZ90" else "WGS84"
    return f"{datum_name} {mode}"


def random_blh():
    """Создать случайные B, L, H: углы в градусах, высота в метрах."""
    return (
        random.uniform(MIN_LATITUDE_DEG, MAX_LATITUDE_DEG),
        random.uniform(MIN_LONGITUDE_DEG, MAX_LONGITUDE_DEG),
        random.uniform(MIN_HEIGHT_M, MAX_HEIGHT_M),
    )


def to_xyz(values, representation):
    """Привести BLH или XYZ к внутреннему виду XYZ в исходной системе."""
    datum, mode = representation
    if mode == "BLH":
        return blh_to_xyz(*values, datum)
    return np.asarray(values, dtype=float)


def convert(values, source, target):
    """Перевести координаты между любыми двумя поддерживаемыми представлениями."""
    source_datum, _ = source
    target_datum, target_mode = target

    # Сначала любые исходные координаты приводятся к XYZ.
    xyz = to_xyz(values, source)

    # Затем при необходимости меняется геодезическая система.
    target_xyz = transform_xyz(xyz, source_datum, target_datum)

    # Результат возвращается в выбранном пользователем формате.
    if target_mode == "BLH":
        return tuple(xyz_to_blh(target_xyz, target_datum))
    return tuple(float(value) for value in target_xyz)


def random_source_coordinates(representation):
    """Создать корректную случайную точку сразу в требуемом представлении."""
    datum, mode = representation
    blh = random_blh()
    if mode == "BLH":
        return blh
    return tuple(float(value) for value in blh_to_xyz(*blh, datum))


def longitude_difference(first, second):
    """Разность долгот с учётом совпадения −180° и +180°."""
    return (second - first + 180.0) % 360.0 - 180.0


def round_trip_error(original, restored, source):
    """Вычислить разности компонентов и общую пространственную ошибку."""
    datum, mode = source
    if mode == "BLH":
        component_error = (
            restored[0] - original[0],
            longitude_difference(original[1], restored[1]),
            restored[2] - original[2],
        )
        original_xyz = blh_to_xyz(*original, datum)
        restored_xyz = blh_to_xyz(*restored, datum)
    else:
        component_error = tuple(
            restored_value - original_value
            for original_value, restored_value in zip(original, restored)
        )
        original_xyz = np.asarray(original, dtype=float)
        restored_xyz = np.asarray(restored, dtype=float)

    spatial_error = float(np.linalg.norm(restored_xyz - original_xyz))
    return component_error, spatial_error


def format_coordinates(values, representation):
    """Подготовить координаты к понятному выводу в консоль."""
    _, mode = representation
    if mode == "BLH":
        return f"B = {values[0]:+.12f}°, L = {values[1]:+.12f}°, H = {values[2]:+.6f} м"
    return f"X = {values[0]:+.6f} м, Y = {values[1]:+.6f} м, Z = {values[2]:+.6f} м"


def format_component_error(values, representation):
    """Подготовить разности компонентов к выводу."""
    _, mode = representation
    if mode == "BLH":
        return f"dB = {values[0]:+.12e}°, dL = {values[1]:+.12e}°, dH = {values[2]:+.12e} м"
    return f"dX = {values[0]:+.12e} м, dY = {values[1]:+.12e} м, dZ = {values[2]:+.12e} м"


def run_transition(number, source, target):
    """Выполнить один случайный прямой и обратный перевод и показать ошибку."""
    original = random_source_coordinates(source)
    converted = convert(original, source, target)
    restored = convert(converted, target, source)
    component_error, spatial_error = round_trip_error(original, restored, source)

    print("\n" + "=" * 88)
    print(f"Переход {number + 1}/{len(TRANSITIONS)}: "
          f"{representation_name(source)} -> {representation_name(target)} -> {representation_name(source)}")
    print("-" * 88)
    print(f"Исходные:          {format_coordinates(original, source)}")
    print(f"Прямой перевод:    {format_coordinates(converted, target)}")
    print(f"Обратный перевод:  {format_coordinates(restored, source)}")
    print(f"Разница:           {format_component_error(component_error, source)}")
    print(f"Пространственная погрешность: {spatial_error:.12e} м")
    print(f"Проверка <= {TOLERANCE_M:g} м: " + ("ПРОЙДЕНА" if spatial_error <= TOLERANCE_M else "НЕ ПРОЙДЕНА"))
    return spatial_error


def print_transition_list(title, transitions, first_number):
    """Показать отдельную группу переходов."""
    print(f"\n{title}:")
    for offset, (source, target) in enumerate(transitions):
        print(f"{first_number + offset:2d}. {representation_name(source)} -> {representation_name(target)}")


def print_main_errors(results):
    """Вывести итоговую погрешность каждого основного перехода."""
    print("\n" + "=" * 88)
    print("ИТОГОВЫЕ ПОГРЕШНОСТИ ВСЕХ ОСНОВНЫХ ПЕРЕХОДОВ")
    print("-" * 88)
    for number, (source, target, error) in enumerate(results, start=1):
        status = "ПРОЙДЕНА" if error <= TOLERANCE_M else "НЕ ПРОЙДЕНА"
        print(
            f"{number}. {representation_name(source)} -> {representation_name(target)}: "
            f"{error:.12e} м — {status}"
        )
    maximum = max(error for _, _, error in results)
    print("-" * 88)
    print(f"Максимальная погрешность основных переходов: {maximum:.12e} м")
    print(f"Допустимая погрешность:                     {TOLERANCE_M:.12e} м")
    print("=" * 88)


def main():
    print("ПРОВЕРКА ПРЕОБРАЗОВАНИЯ КООРДИНАТ")
    print("Используются функции непосредственно из nka_app/coordinates.py.")
    print("Проверяется численная обратимость; это не оценка точности параметров эллипсоидов.")
    print_transition_list(
        "ОСНОВНЫЕ ПЕРЕХОДЫ — используются напрямую в программе",
        MAIN_TRANSITIONS,
        1,
    )
    print_transition_list(
        "ДОПОЛНИТЕЛЬНЫЕ ПЕРЕХОДЫ — не вызываются отдельной операцией",
        ADDITIONAL_TRANSITIONS,
        len(MAIN_TRANSITIONS) + 1,
    )

    transition_number = 0
    main_results = []
    try:
        while True:
            command = input("\nEnter — выполнить следующий перевод; q — выход: ").strip().lower()
            if command in {"q", "й", "quit", "exit"}:
                break
            if command:
                print("Введите только Enter для продолжения или q для выхода.")
                continue

            source, target = TRANSITIONS[transition_number]
            error = run_transition(transition_number, source, target)
            if transition_number < len(MAIN_TRANSITIONS):
                main_results.append((source, target, error))
                if len(main_results) == len(MAIN_TRANSITIONS):
                    print_main_errors(main_results)
                    print("\nОсновные переходы завершены. Следующий Enter начнёт дополнительные.")
            transition_number = (transition_number + 1) % len(TRANSITIONS)
            if transition_number == 0:
                main_results.clear()
                print("\nВсе переходы завершены. Следующий Enter начнёт новый цикл.")
    except (EOFError, KeyboardInterrupt):
        pass

    print("\nПроверка завершена.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
