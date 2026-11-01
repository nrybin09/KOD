from nka_app.common import MU_GPS, OMEGA_EARTH, np

def wrap_week(tb):
    if tb > 302400:   # если прошло больше половины недели вперёд
        tb -= 604800  # считаем, что это "−X секунд" от предыдущей недели
    if tb < -302400:  # если ушли более чем на полнедели назад
        tb += 604800  # добавляем неделю вперёд
    return tb

def solve_kepler(M, e, iters: int = 50) -> float:
    """
    Решает уравнение Кеплера M = E - e*sin(E) итерационным методом Ньютона.
    Используется для вычисления эксцентрической аномалии E по известной
    средней аномалии M и эксцентриситету e.
    Пошагово:
    1. Задаём начальное приближение E0 = M (достаточно при e < 0.1)
    2. Повторяем N итераций:
           E_{n+1} = E_n + (M - (E_n - e*sin(E_n))) / (1 - e*cos(E_n))
    3. Возвращаем итоговое значение E (в радианах)
    """
    E = M  # начальное приближение
    for _ in range(iters):
        delta = (M - (E - e * np.sin(E))) / (1 - e * np.cos(E))
        E += delta
        # Можно прервать итерации, если изменение уже мало:
        if abs(delta) < 1e-12:
            break
    if abs(E - e*np.sin(E) - M) > 1e-10:
        raise ValueError('Не сошлось уравнение Кеплера. Проверьте параметры орбиты.')
    return E

def ecef_from_eph(eph, t):
    """
    Вычисляет ECEF-координаты GPS-спутника по переданным эфемеридам LNAV в 
    момент времени t (сек GPS-недели).
    Параметры eph:
      eph.sqrtA  : sqrt(A), корень из большой полуоси [м^0.5]
      eph.e      : эксцентриситет
      eph.deltan : поправка к средней угл. скорости [рад/с]
      eph.m0     : средняя аномалия в toe [рад]
      eph.omega  : аргумент перигея ω [рад]
      eph.cus,cuc,crs,crc,cis,cic : гармонические поправки
      eph.i0     : наклон i0 [рад], eph.iDot: di/dt [рад/с]
      eph.OMEGA  : долгота восходящего узла Ω0 в toe [рад]
      eph.omegaDot : dΩ/dt [рад/с]
      eph.toe    : эпоха эфемерид toe [с]

    Возвращает:
      numpy.array([x, y, z]) в ECEF, метры.
    """
    # === 1) Базовые величины ===
    # Большая полуось A = (sqrtA)^2
    A = eph.sqrtA ** 2

    # Номинальная средняя угловая скорость (n0 = sqrt(mu / A^3))
    n0 = np.sqrt(MU_GPS / A**3)

    # Разность времен tb = t - toe, с учетом перехода через границу недели
    tb = wrap_week(t - eph.toe)

    # Исправленная средняя угловая скорость n = n0 + Δn
    n = n0 + eph.deltan

    # Средняя аномалия в момент t: Mk = M0 + n*tb
    Mk = eph.m0 + n * tb

    # === 2) Уравнение Кеплера и истинная аномалия ===
    # Решаем M = E - e*sin(E) → получаем эксцентрическую аномалию Ek
    Ek = solve_kepler(Mk, eph.e)

    # Истинная аномалия ν из Ek (устойчивая формула через tan(E/2))
    vk = 2 * np.arctan2(
        np.sqrt(1 + eph.e) * np.sin(Ek / 2.0),
        np.sqrt(1 - eph.e) * np.cos(Ek / 2.0)
    )

    # === 3) Гармоники второй гармоники и исправления радиуса/широты/наклона ===
    # Аргумент широты без поправок: Φk = νk + ω
    phi_k = vk + eph.omega

    # Поправка аргумента широты u = Φ + δu
    du = eph.cus * np.sin(2 * phi_k) + eph.cuc * np.cos(2 * phi_k)

    # Поправка радиуса r = A(1 - e*cosE) + δr
    dr = eph.crs * np.sin(2 * phi_k) + eph.crc * np.cos(2 * phi_k)

    # Поправка наклона i = i0 + iDot*tb + δi
    di = eph.cis * np.sin(2 * phi_k) + eph.cic * np.cos(2 * phi_k)

    u = phi_k + du
    r = A * (1 - eph.e * np.cos(Ek)) + dr
    i = eph.i0 + eph.iDot * tb + di

    # === 4) Переход из плоскости орбиты к ECEF ===
    # Координаты в орбитальной плоскости
    x_orb = r * np.cos(u)
    y_orb = r * np.sin(u)

    # Исправленная долгота восходящего узла:
   
    Omega_k = (
        eph.OMEGA
        + (eph.omegaDot - OMEGA_EARTH) * tb
        - OMEGA_EARTH * eph.toe
    )

    # Преобразование в ECEF (WGS-84)
    x = x_orb * np.cos(Omega_k) - y_orb * np.cos(i) * np.sin(Omega_k)
    y = x_orb * np.sin(Omega_k) + y_orb * np.cos(i) * np.cos(Omega_k)
    z = y_orb * np.sin(i)

    return np.array([x, y, z])

