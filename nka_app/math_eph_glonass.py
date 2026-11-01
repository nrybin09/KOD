from nka_app.common import (
    EARTH_RADIUS_GLONASS,
    J2_GLONASS,
    MU_GLONASS,
    OMEGA_EARTH,
    np,
)

def _grav_j2_acc(x, y, z):
    """
    Вычисляет ускорение (ax, ay, az) спутника в геоцентрической системе
     с учётом второй гармоники J2 (сплюснутости Земли).
    """
    # Расстояние до центра Земли и вспомогательные параметры
    r2 = x*x + y*y + z*z      # квадрат расстояния
    r  = np.sqrt(r2)          # модуль радиус-вектора
    zx = z*z / r2             # отношение (z/r)^2
    # Коэффициент с поправкой на J2
    k = 1.5 * J2_GLONASS * (EARTH_RADIUS_GLONASS**2) / r2
    # Основной множитель
    mu_r3 = MU_GLONASS / (r2 * r)
    # Поправки для каждой координаты
    c = 1 - k * (5*zx - 1)
    ax = -mu_r3 * x * c
    ay = -mu_r3 * y * c
    az = -mu_r3 * z * (1 - k * (5*zx - 3))

    return ax, ay, az

def _rotating_frame_acc(x, y, z, vx, vy, vz):
    ax = (OMEGA_EARTH**2) * x + 2.0 * OMEGA_EARTH * vy
    ay = (OMEGA_EARTH**2) * y - 2.0 * OMEGA_EARTH * vx
    az = 0.0
    return ax, ay, az

def _glo_rhs(state, add_ax=0.0, add_ay=0.0, add_az=0.0):
    """
    state = [x, y, z, vx, vy, vz]
        x, y, z  — координаты спутника (м)
        vx, vy, vz — скорости (м/с)
    add_ax, add_ay, add_az — дополнительные ускорения
        (лунно–солнечные возмущения, постоянные на ±15 мин)
    Возвращает вектор:
        [dx/dt, dy/dt, dz/dt, d²x/dt², d²y/dt², d²z/dt²]
    """
    # Распаковываем состояние
    x, y, z, vx, vy, vz = state

    #  1) Гравитация с учётом сплюснутости Земли (J2) 
    ax_g, ay_g, az_g = _grav_j2_acc(x, y, z)

    #  2) Центробежное + кориолисово ускорения во вращающейся системе 
    ax_r, ay_r, az_r = _rotating_frame_acc(x, y, z, vx, vy, vz)

    #  3) Добавляем возмущения от Луны и Солнца 
    ax = ax_g + ax_r + add_ax
    ay = ay_g + ay_r + add_ay
    az = az_g + az_r + add_az

    return np.array([vx, vy, vz, ax, ay, az])

def _rk4_step(state, dt, ax_add, ay_add, az_add):
    """
    Параметры:
      state  – вектор состояния [x, y, z, vx, vy, vz]
      dt     – шаг интегрирования (сек)
      ax_add, ay_add, az_add – дополнительные ускорения (лунно–солнечные)
    Возвращает:
      новое состояние после шага dt
    """
    # k1: производные при начальном состоянии
    k1 = _glo_rhs(state, ax_add, ay_add, az_add)
    # k2: производные в середине шага (с учётом k1)
    k2 = _glo_rhs(state + 0.5 * dt * k1, ax_add, ay_add, az_add)
    # k3: ещё одно приближение середины шага (с учётом k2)
    k3 = _glo_rhs(state + 0.5 * dt * k2, ax_add, ay_add, az_add)
    # k4: производные в конце шага (с учётом k3)
    k4 = _glo_rhs(state + dt * k3, ax_add, ay_add, az_add)
    # Итоговое новое состояние (взвешенное среднее 1–2–2–1)
    state_next = state + (dt / 6.0) * (k1 + 2*k2 + 2*k3 + k4)
    
    return state_next

def glo_ecef_from_icd(ephR, t, step_s=1.0):
    """
    Вычисляет координаты спутника ГЛОНАСС (ECEF)
    Параметры:
        ephR   — объект с эфемеридами спутника (x, y, z, dx, dy, dz, ddx, ddy, ddz, tb)
        t      — момент времени, на который требуется определить координаты, [с]
        step_s — шаг интегрирования, [с] 
    Возвращает:
        numpy.array([x, y, z]) — координаты спутника в метрах 
    """
    #  1) Начальные условия из эфемерид 
    x0  = ephR.x  * 1000.0    # координата X в метрах
    y0  = ephR.y  * 1000.0    # координата Y в метрах
    z0  = ephR.z  * 1000.0    # координата Z в метрах
    vx0 = ephR.dx * 1000.0    # скорость по X в м/с
    vy0 = ephR.dy * 1000.0    # скорость по Y в м/с
    vz0 = ephR.dz * 1000.0    # скорость по Z в м/с
 
    #  2) Лунно–солнечные ускорения 
    ax_add = ephR.ddx * 1000.0
    ay_add = ephR.ddy * 1000.0
    az_add = ephR.ddz * 1000.0

    #  3) Расчёт временного интервала от tb 
    tb = ephR.tb                # эпоха, для которой заданы параметры эфемерид
    dt_total = float(t - tb)    # общее смещение по времени, [с]

    # Если момент совпадает с tb — возвращаем исходные координаты без интегрирования
    if dt_total == 0.0:
        return np.array([x0, y0, z0])

    #  4) Разбиваем интервал на шаги интегрирования 
    # Определяем количество шагов интегратора, чтобы равномерно пройти весь интервал
    nsteps = int(np.ceil(abs(dt_total) / step_s))  # количество шагов
    dt = dt_total / nsteps                         # реальный шаг по времени

    #  5) Формируем начальный вектор состояния 
    state = np.array([x0, y0, z0, vx0, vy0, vz0], dtype=float)

    #  6) Интегрирование уравнений движения 
    for _ in range(nsteps):
        state = _rk4_step(state, dt, ax_add, ay_add, az_add)

    #  7) Возвращаем координаты после интегрирования 
    # Берём только первые три компоненты (x, y, z),
    # скорости и ускорения для построения орбиты не нужны.
    return state[:3]


