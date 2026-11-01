from nka_app.common import GPS_HALF_WEEK, GPS_WEEK, MU_GPS, OMEGA_EARTH, np

def calc_A(alm):

    # A = alm.a ** 2
    A = alm.a
    return A

def calc_n0(A):

    n0 = np.sqrt(MU_GPS / A ** 3)

    return n0

def wrap_week(tk):

    if tk > GPS_HALF_WEEK:
        tk = tk - GPS_WEEK

    if tk < -GPS_HALF_WEEK:
        tk = tk + GPS_WEEK

    return tk
 
def calc_tk(t, alm):

    tk_raw = t - alm.toa
    tk = wrap_week(tk_raw)

    return tk

def calc_n(n0):

    n = n0

    return n

def calc_Mk(alm, n, tk):

    Mk = alm.m0 + n * tk

    return Mk

def solve_kepler(M, e, iters=10):

    E = M

    for _ in range(iters):

        delta = (M - (E - e * np.sin(E))) / (1 - e * np.cos(E))
        E = E + delta

        if abs(delta) < 1e-12:
            break

    return E

def calc_vk(Ek, e):

    part1 = np.sqrt(1 + e) * np.sin(Ek / 2)
    part2 = np.sqrt(1 - e) * np.cos(Ek / 2)

    vk = 2 * np.arctan2(part1, part2)

    return vk

def calc_Phi_k(vk, alm):

    Phi_k = vk + alm.w

    return Phi_k

def calc_du_dr_di():

    du = 0.0
    dr = 0.0
    di = 0.0

    return du, dr, di

def calc_u_k(Phi_k, du):

    u_k = Phi_k + du

    return u_k

def calc_r_k(A, e, Ek, dr):

    part1 = A * (1 - e * np.cos(Ek))
    r_k = part1 + dr

    return r_k

def calc_i_k(alm, di, tk):

    IDOT = 0.0
    i_k = alm.i0 + di + IDOT * tk

    return i_k

def calc_orb_xy(r_k, u_k):

    x_orb = r_k * np.cos(u_k)
    y_orb = r_k * np.sin(u_k)

    return x_orb, y_orb

def calc_Omega_k(alm, tk):

    Omega_k = alm.omega0 + (alm.omegaDot - OMEGA_EARTH) * tk - OMEGA_EARTH * alm.toa

    return Omega_k

def calc_xyz_gps(x_orb, y_orb, Omega_k, i_k):

    x = x_orb * np.cos(Omega_k) - y_orb * np.cos(i_k) * np.sin(Omega_k)
    y = x_orb * np.sin(Omega_k) + y_orb * np.cos(i_k) * np.cos(Omega_k)
    z = y_orb * np.sin(i_k)

    return x, y, z

def calc_E_dot(n, e, Ek):

    part1 = 1 - e * np.cos(Ek)
    E_dot = n / part1

    return E_dot

def calc_v_dot(E_dot, e, Ek):

    part1 = np.sqrt(1 - e ** 2)
    part2 = 1 - e * np.cos(Ek)

    v_dot = E_dot * part1 / part2

    return v_dot

def calc_u_dot(v_dot):

    u_dot = v_dot

    return u_dot

def calc_r_dot(A, e, E_dot, Ek):

    r_dot = A * e * E_dot * np.sin(Ek)

    return r_dot

def calc_Omega_dot_k(alm):

    Omega_dot_k = alm.omegaDot - OMEGA_EARTH

    return Omega_dot_k

def calc_orb_vxy(r_k, r_dot, u_k, u_dot):

    x_dot_orb = r_dot * np.cos(u_k) - r_k * u_dot * np.sin(u_k)
    y_dot_orb = r_dot * np.sin(u_k) + r_k * u_dot * np.cos(u_k)

    return x_dot_orb, y_dot_orb

def calc_vxyz_gps(x_orb, y_orb, x_dot_orb, y_dot_orb, Omega_k, Omega_dot_k, i_k, i_dot):

    vx = (
        -x_orb * Omega_dot_k * np.sin(Omega_k)
        + x_dot_orb * np.cos(Omega_k)
        - y_dot_orb * np.sin(Omega_k) * np.cos(i_k)
        - y_orb * (
            Omega_dot_k * np.cos(Omega_k) * np.cos(i_k)
            - i_dot * np.sin(Omega_k) * np.sin(i_k)
        )
    )

    vy = (
        x_orb * Omega_dot_k * np.cos(Omega_k)
        + x_dot_orb * np.sin(Omega_k)
        + y_dot_orb * np.cos(Omega_k) * np.cos(i_k)
        - y_orb * (
            Omega_dot_k * np.sin(Omega_k) * np.cos(i_k)
            + i_dot * np.cos(Omega_k) * np.sin(i_k)
        )
    )

    vz = (
        y_dot_orb * np.sin(i_k)
        + y_orb * i_dot * np.cos(i_k)
    )

    return vx, vy, vz

def calc_gps_from_alm(alm, t):

    A = calc_A(alm)

    n0 = calc_n0(A)

    tk = calc_tk(t, alm)

    n = calc_n(n0)

    Mk = calc_Mk(alm, n, tk)

    Ek = solve_kepler(Mk, alm.e)

    vk = calc_vk(Ek, alm.e)

    Phi_k = calc_Phi_k(vk, alm)

    du, dr, di = calc_du_dr_di()

    u_k = calc_u_k(Phi_k, du)

    r_k = calc_r_k(A, alm.e, Ek, dr)

    i_k = calc_i_k(alm, di, tk)

    x_orb, y_orb = calc_orb_xy(r_k, u_k)

    Omega_k = calc_Omega_k(alm, tk)

    x, y, z = calc_xyz_gps(x_orb, y_orb, Omega_k, i_k)

    E_dot = calc_E_dot(n, alm.e, Ek)

    v_dot = calc_v_dot(E_dot, alm.e, Ek)

    i_dot = 0.0

    u_dot = calc_u_dot(v_dot)

    r_dot = calc_r_dot(A, alm.e, E_dot, Ek)

    Omega_dot_k = calc_Omega_dot_k(alm)

    x_dot_orb, y_dot_orb = calc_orb_vxy(r_k, r_dot, u_k, u_dot)

    vx, vy, vz = calc_vxyz_gps(
        x_orb, y_orb,
        x_dot_orb, y_dot_orb,
        Omega_k, Omega_dot_k,
        i_k, i_dot
        )

    result = {
        "x": x,
        "y": y,
        "z": z,
        "vx": vx,
        "vy": vy,
        "vz": vz
    }

    return result
