from nka_app.common import (
    EARTH_RADIUS_GLONASS,
    DAYS_1460,
    DAYS_1461,
    MU_GLONASS,
    I_CP,
    J2_GLONASS,
    OMEGA_EARTH,
    SEC_IN_DAY,
    T_CP,
    np,
)

def nearest_int(x):

    k = np.floor(x + 0.5)

    return int(k)

def calc_delta_N_A(N, N_A, N4):

    days = DAYS_1460 if N4 == 27 else DAYS_1461

    a = N - N_A
    b = nearest_int((N - N_A) / days)
    delta_N_A = a - b * days

    return delta_N_A

def calc_delta_t_pr(alm, task):

    delta_N_A = calc_delta_N_A(task["N"], alm.Na, task["N4"])

    part1 = delta_N_A * SEC_IN_DAY
    part2 = task["time_glo"] - alm.ta
    delta_t_pr = part1 + part2

    return delta_t_pr

def calc_W(delta_t_pr, alm):
    denominator = T_CP
    W = int(np.floor(delta_t_pr / denominator))
    return W

def calc_i(alm):

    part1 = I_CP / 180
    part2 = part1 + alm.delta_ia
    i = part2 * np.pi

    return i

def calc_Tdr_n(W, alm):
    T_dr = T_CP
    n = (2 * np.pi) / T_dr
    return T_dr, n

def calc_a(T_dr, i, alm):

    T_osc = T_dr
    eps = alm.eps_a
    omega = alm.w_a

    a_prev = 0

    while True:

        part1 = (T_osc / (2 * np.pi)) ** 2
        a = (part1 * MU_GLONASS) ** (1 / 3)

        p = a * (1 - eps ** 2)

        partA = (EARTH_RADIUS_GLONASS / p) ** 2
        partB = 2 - 2.5 * (np.sin(i) ** 2)
        partC = ((1 - eps ** 2) ** (3 / 2)) / ((1 + eps * np.cos(np.pi * omega)) ** 2)
        partD = ((1 + eps * np.cos(np.pi * omega)) ** 3) / (1 - eps ** 2)

        correction = 1 - 1.5 * J2_GLONASS * partA * (partB * partC + partD)

        T_osc_new = T_dr / correction

        if abs(a - a_prev) <= 0.01:
            break

        a_prev = a
        T_osc = T_osc_new

    return a, p, T_osc_new

def calc_lambda_omega(delta_t_pr, i, n, p, alm):

    part1_lambda = alm.lambda_a * np.pi
    part2_lambda = OMEGA_EARTH
    part3_lambda = (
        1.5
        * J2_GLONASS
        * n
        * (EARTH_RADIUS_GLONASS / p) ** 2
        * np.cos(i)
    )
    lambda_current = part1_lambda - (part2_lambda + part3_lambda) * delta_t_pr

    part1_omega = alm.w_a * np.pi
    part2_omega = 0.75 * J2_GLONASS * n * (EARTH_RADIUS_GLONASS / p) ** 2
    part3_omega = 1 - 5 * (np.cos(i) ** 2)
    omega_current = part1_omega - part2_omega * part3_omega * delta_t_pr

    return lambda_current, omega_current

def calc_L1(omega_current, alm):

    part1 = np.sqrt((1 - alm.eps_a) / (1 + alm.eps_a))
    part2 = np.tan(omega_current / 2)
    E0 = -2 * np.arctan(part1 * part2)

    part3 = alm.eps_a * np.sin(E0)
    L1 = omega_current + E0 - part3

    return L1, E0

def calc_L(L1, delta_t_pr, W, n, alm):
    part_total = delta_t_pr - T_CP * W
    L = L1 + n * part_total
    return L

def calc_short_period_base(a, eps, omega):

    ratio = EARTH_RADIUS_GLONASS / a
    B = 1.5 * J2_GLONASS * (ratio ** 2)

    h = eps * np.sin(omega)
    l = eps * np.cos(omega)

    return B, h, l

def calc_short_period_terms(Lk, B, h, l, i, a):

    sin_i = np.sin(i)
    cos_i = np.cos(i)

    sin2_i = sin_i ** 2
    cos2_i = cos_i ** 2

    sinL = np.sin(Lk)
    cosL = np.cos(Lk)

    sin2L = np.sin(2 * Lk)
    cos2L = np.cos(2 * Lk)

    sin3L = np.sin(3 * Lk)
    cos3L = np.cos(3 * Lk)

    sin4L = np.sin(4 * Lk)
    cos4L = np.cos(4 * Lk)

    partA = 1 - 1.5 * sin2_i

    # δa_k / a
    term_a_1 = 2 * B * partA * (l * cosL + h * sinL)
    term_a_2 = B * sin2_i * (0.5 * h * sinL - 0.5 * l * cosL + cos2L + 3.5 * l * cos3L + 3.5 * h * sin3L)
    delta_a_over_a = term_a_1 + term_a_2
    delta_a = a * delta_a_over_a

    # δh_k
    term_h_1 = B * partA * ( sinL + 1.5 * l * sin2L - 1.5 * h * cos2L)
    term_h_2 = -0.25 * B * sin2_i * (sinL - (7 / 3) * sin3L + 5 * l * sin2L - 8.5 * l * sin4L + 8.5 * h * cos4L + h * cos2L )
    term_h_3 = -0.5 * B * cos2_i * l * sin2L
    delta_h = term_h_1 + term_h_2 + term_h_3

    # δl_k
    term_l_1 = B * partA * (cosL+ 1.5 * l * cos2L+ 1.5 * h * sin2L )
    term_l_2 = -0.25 * B * sin2_i * (-cosL- (7 / 3) * cos3L- 5 * h * sin2L- 8.5 * l * cos4L- 8.5 * h * sin4L+ l * cos2L )
    term_l_3 = 0.5 * B * cos2_i * h * sin2L
    delta_l = term_l_1 + term_l_2 + term_l_3

    # δλ_k
    delta_lambda = -B * cos_i * (3.5 * l * sinL- 2.5 * h * cosL- 0.5 * sin2L- (7 / 6) * l * sin3L+ (7 / 6) * h * cos3L )

    # δi_k
    delta_i = 0.5 * B * sin_i * cos_i * (-l * cosL+ h * sinL+ cos2L+ (7 / 3) * l * cos3L+ (7 / 3) * h * sin3L)

    # δL_k
    term_L_1 = 2 * B * partA * ((7/4) * l * sinL- (7/4) * h * cosL)
    term_L_2 = 3 * B * sin2_i * (-(7 / 24) * h * cosL- (7 / 24) * l * sinL- (49 / 72) * h * cos3L+ (49 / 72) * l * sin3L+ 0.25 * sin2L )
    term_L_3 = B * cos2_i * (3.5 * l * sinL- 2.5 * h * cosL- 0.5 * sin2L- (7 / 6) * l * sin3L+ (7 / 6) * h * cos3L)
    delta_L = term_L_1 + term_L_2 + term_L_3

    return delta_a, delta_a_over_a, delta_h, delta_l, delta_i, delta_lambda, delta_L

def apply_short_period_correction(a,  i, lam,  L, delta_a1, delta_a2, delta_h1, delta_h2, delta_l1, delta_l2, delta_i1, delta_i2, delta_lambda1, delta_lambda2, delta_L1, delta_L2, h, l):

    a_corr = a + delta_a2 - delta_a1

    h_corr = h + delta_h2 - delta_h1
    l_corr = l + delta_l2 - delta_l1

    eps_corr = np.sqrt(h_corr ** 2 + l_corr ** 2)

    i_corr = i + delta_i2 - delta_i1
    lambda_corr = lam + delta_lambda2 - delta_lambda1
    omega_corr = np.arctan2(h_corr, l_corr)
    L_corr = L + delta_L2 - delta_L1

    return a_corr, eps_corr, i_corr, lambda_corr, omega_corr, L_corr, h_corr, l_corr

def calc_E(L, omega, eps):

    E_prev = L - omega

    while True:

        E = L - omega + eps * np.sin(E_prev)

        if abs(E - E_prev) <= 1e-9:
            break

        E_prev = E

    return E

def calc_nu_u(E, eps, omega):

    part1 = np.sqrt((1 + eps) / (1 - eps))
    part2 = np.tan(E / 2)

    nu = 2 * np.arctan(part1 * part2)

    u = nu + omega

    return nu, u

def calc_xyz(a, eps, nu, u, lam, i):

    part1 = 1 - eps ** 2
    p = a * part1

    part2 = 1 + eps * np.cos(nu)
    r = p / part2

    x = r * (np.cos(lam) * np.cos(u) - np.sin(lam) * np.sin(u) * np.cos(i))
    y = r * (np.sin(lam) * np.cos(u) + np.cos(lam) * np.sin(u) * np.cos(i))
    z = r * np.sin(u) * np.sin(i)

    return x, y, z, r, p

def calc_vxyz(p, eps, nu, u, lam, i, x, y):

    part1 = np.sqrt(MU_GLONASS / p)

    V_r = part1 * eps * np.sin(nu)
    V_u = part1 * (1 + eps * np.cos(nu))

    vx = (V_r * (np.cos(lam) * np.cos(u) - np.sin(lam) * np.sin(u) * np.cos(i))- V_u * (np.cos(lam) * np.sin(u) + np.sin(lam) * np.cos(u) * np.cos(i))+ OMEGA_EARTH * y)

    vy = (V_r * (np.sin(lam) * np.cos(u) + np.cos(lam) * np.sin(u) * np.cos(i))- V_u * (np.sin(lam) * np.sin(u) - np.cos(lam) * np.cos(u) * np.cos(i))- OMEGA_EARTH * x)

    vz = (V_r * np.sin(u) * np.sin(i)+ V_u * np.cos(u) * np.sin(i))

    return vx, vy, vz, V_r, V_u

def calc_gln_from_alm(alm, task):

    delta_t_pr = calc_delta_t_pr(alm, task)
    W = calc_W(delta_t_pr, alm)
    i = calc_i(alm)

    T_dr, n = calc_Tdr_n(W, alm)
    a, p, T_osc = calc_a(T_dr, i, alm)

    lambda_current, omega_current = calc_lambda_omega(delta_t_pr, i, n, p, alm)

    L1, E0 = calc_L1(omega_current, alm)
    L = calc_L(L1, delta_t_pr, W, n, alm)

    B, h, l = calc_short_period_base(a, alm.eps_a, omega_current)

    delta_a1, delta_a1_over_a, delta_h1, delta_l1, delta_i1, delta_lambda1, delta_L1 = calc_short_period_terms(L1, B, h, l, i, a)
    delta_a2, delta_a2_over_a, delta_h2, delta_l2, delta_i2, delta_lambda2, delta_L2 = calc_short_period_terms(L, B, h, l, i, a)

    a_corr, eps_corr, i_corr, lambda_corr, omega_corr, L_corr, h_corr, l_corr = apply_short_period_correction(
        a, i, lambda_current, L,
        delta_a1, delta_a2,
        delta_h1, delta_h2,
        delta_l1, delta_l2,
        delta_i1, delta_i2,
        delta_lambda1, delta_lambda2,
        delta_L1, delta_L2,
        h, l
    )

    E = calc_E(L_corr, omega_corr, eps_corr)
    nu, u = calc_nu_u(E, eps_corr, omega_corr)

    x, y, z, r, p_corr = calc_xyz(a_corr, eps_corr, nu, u, lambda_corr, i_corr)
    vx, vy, vz, V_r, V_u = calc_vxyz(p_corr, eps_corr, nu, u, lambda_corr, i_corr, x, y)

    result = {
        "x": x,
        "y": y,
        "z": z,
        "vx": vx,
        "vy": vy,
        "vz": vz,
        "r": r,
        "p": p_corr,
        "a": a_corr,
        "eps": eps_corr,
        "i": i_corr,
        "lambda": lambda_corr,
        "omega": omega_corr,
        "L": L_corr,
        "E": E,
        "nu": nu,
        "u": u,
        "V_r": V_r,
        "V_u": V_u
    }

    return result
