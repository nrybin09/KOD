"""Преобразование координат и расчёт углов на спутник.

В модуле используются два способа записи положения наблюдателя:

* BLH — широта B и долгота L в градусах, высота H в метрах;
* XYZ — прямоугольные геоцентрические координаты в метрах.

Название ``PZ90`` в программе означает систему ПЗ-90.02. Переход между
ПЗ-90.02 и WGS-84 выполняется простым сдвигом начала координат согласно
описанию ESA Navipedia:
https://gssc.esa.int/navipedia/index.php/GLONASS_Satellite_Coordinates_Computation
"""

from nka_app.common import ELLIPSOIDS, PZ_TO_WGS, dataclass, math, np


def blh_to_xyz(b: float, l: float, h: float, datum: str = "WGS84") -> np.ndarray:
    """Перевести геодезические координаты BLH в геоцентрические XYZ.

    ``b`` — широта в градусах, ``l`` — долгота в градусах,
    ``h`` — высота над выбранным эллипсоидом в метрах.
    """
    # До расчёта отбрасываем бесконечность, NaN и значения вне диапазона.
    if not all(math.isfinite(v) for v in (b, l, h)):
        raise ValueError("Координаты должны быть конечными числами.")
    if not -90 <= b <= 90 or not -180 <= l <= 180:
        raise ValueError("B: от −90 до 90°, L: от −180 до 180°.")

    a, rf = ELLIPSOIDS[datum]
    if h <= -a + 1:
        raise ValueError("Недопустимая высота наблюдателя.")

    # f — сжатие эллипсоида, e2 — квадрат его первого эксцентриситета.
    f = 1 / rf
    e2 = f * (2 - f)
    lat, lon = np.radians([b, l])

    # Радиус кривизны первого вертикала в точке с широтой lat.
    n = a / np.sqrt(1 - e2 * np.sin(lat) ** 2)

    # Стандартный переход от широты, долготы и высоты к XYZ.
    return np.array([
        (n + h) * np.cos(lat) * np.cos(lon),
        (n + h) * np.cos(lat) * np.sin(lon),
        (n * (1 - e2) + h) * np.sin(lat),
    ])


def xyz_to_blh(xyz, datum: str = "WGS84") -> tuple[float, float, float]:
    """Перевести геоцентрические координаты XYZ в координаты BLH.

    Возвращаются широта и долгота в градусах, высота — в метрах.
    """
    x, y, z = np.asarray(xyz, dtype=float)
    if not np.all(np.isfinite([x, y, z])) or np.linalg.norm([x, y, z]) < 1:
        raise ValueError("XYZ должны задавать точку вне центра Земли.")

    a, rf = ELLIPSOIDS[datum]
    f = 1 / rf
    e2 = f * (2 - f)

    # p — расстояние от точки до земной оси Z.
    p = math.hypot(x, y)
    lon = math.atan2(y, x)

    # На полюсе долгота не определена, поэтому по соглашению берём 0°.
    if p < 1e-8:
        return math.copysign(90.0, z), 0.0, abs(z) - a * (1 - f)

    # Широта уточняется итерациями. Обычно сходимость достигается
    # значительно раньше предельных 20 повторений.
    lat = math.atan2(z, p * (1 - e2))
    for _ in range(20):
        n = a / math.sqrt(1 - e2 * math.sin(lat) ** 2)
        next_lat = math.atan2(z + e2 * n * math.sin(lat), p)
        if abs(next_lat - lat) < 1e-14:
            lat = next_lat
            break
        lat = next_lat

    # После найденной широты определяем высоту над эллипсоидом.
    n = a / math.sqrt(1 - e2 * math.sin(lat) ** 2)
    h = p * math.cos(lat) + z * math.sin(lat) - n * (
        1 - e2 * math.sin(lat) ** 2
    )
    return math.degrees(lat), math.degrees(lon), h


def transform_xyz(xyz, source: str, target: str) -> np.ndarray:
    """Перевести XYZ между ПЗ-90.02 и WGS-84 простым сдвигом."""
    if source not in ELLIPSOIDS or target not in ELLIPSOIDS:
        raise ValueError("Неизвестная система координат.")

    xyz = np.asarray(xyz, dtype=float)
    if source == target:
        return xyz.copy()

    # Из ПЗ-90.02 в WGS-84 прибавляем вектор, в обратную сторону — вычитаем.
    return xyz + PZ_TO_WGS if source == "PZ90" else xyz - PZ_TO_WGS


@dataclass(frozen=True)
class Observer:
    """Положение наблюдателя в XYZ и система этих координат."""

    xyz: tuple[float, float, float]
    datum: str

    @classmethod
    def from_values(cls, values, mode: str, datum: str):
        """Создать наблюдателя из введённых пользователем BLH или XYZ."""
        if datum not in ELLIPSOIDS or mode not in ("XYZ", "BLH"):
            raise ValueError("Неизвестный формат координат.")

        # Внутри программы положение всегда хранится как XYZ.
        xyz = (
            blh_to_xyz(*values, datum)
            if mode == "BLH"
            else np.asarray(values, dtype=float)
        )

        # Обратный перевод здесь служит проверкой корректности введённых XYZ.
        xyz_to_blh(xyz, datum)
        return cls(tuple(float(v) for v in xyz), datum)

    def in_datum(self, datum):
        """Получить XYZ наблюдателя в требуемой системе координат."""
        return transform_xyz(self.xyz, self.datum, datum)


def azimuth_elevation(satellite_xyz, observer: Observer, satellite_datum: str):
    """Рассчитать азимут и угол места спутника в градусах.

    Азимут отсчитывается от севера по часовой стрелке и лежит в диапазоне
    от 0° до 360°. Угол места показывает высоту спутника над горизонтом.
    """
    # Координаты спутника и наблюдателя должны относиться к одной системе.
    origin = observer.in_datum(satellite_datum)
    b, l, _ = xyz_to_blh(origin, satellite_datum)
    b, l = np.radians([b, l])

    # Вектор от наблюдателя к спутнику в геоцентрической системе XYZ.
    dx, dy, dz = np.asarray(satellite_xyz) - origin

    # Перевод в локальную систему наблюдателя: восток, север, вверх (ENU).
    east = -np.sin(l) * dx + np.cos(l) * dy
    north = (
        -np.sin(b) * np.cos(l) * dx
        - np.sin(b) * np.sin(l) * dy
        + np.cos(b) * dz
    )
    up = (
        np.cos(b) * np.cos(l) * dx
        + np.cos(b) * np.sin(l) * dy
        + np.sin(b) * dz
    )

    if math.hypot(math.hypot(east, north), up) < 1e-6:
        raise ValueError("Спутник совпадает с положением наблюдателя.")

    # atan2 правильно определяет четверть и для азимута, и для угла места.
    az = math.degrees(math.atan2(east, north)) % 360
    el = math.degrees(math.atan2(up, math.hypot(east, north)))
    return az, el
