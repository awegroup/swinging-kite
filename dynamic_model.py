import casadi as ca
import numpy as np
import matplotlib.pyplot as plt
from system_properties import *


def derive_tether_model_kcu_williams(n_tether_elements, vwx=0):
    # Only drag of the lower adjacent tether element is lumped to the point mass.
    vw = ca.vertcat(vwx, 0, 0)

    # States
    n_elements = n_tether_elements + 1  # n_tether_elements excludes bridle element
    n_free_pm = n_elements-1  # Upper point mass is constrained - others are free
    r = ca.SX.sym('r', n_elements, 3)
    r_wing = r[n_elements-1, :]
    r_kcu = r[n_elements-2, :]
    v = ca.SX.sym('v', n_elements, 3)

    l = ca.SX.sym('l')  # Without bridle
    dl = ca.SX.sym('dl')
    x = ca.vertcat(ca.vec(r.T), ca.vec(v.T), l, dl)

    # Controls
    ddl = ca.SX.sym('ddl')
    a_wing = ca.SX.sym('a_wing', 3)
    u = ca.vertcat(ddl, a_wing)

    l_s = l / n_tether_elements
    dl_s = dl / n_tether_elements
    ddl_s = ddl / n_tether_elements

    m_s = np.pi*d_t**2/4 * l_s * rho_t

    # Determine drag on each tether element
    d_s = []
    for i in range(n_tether_elements):
        vf = v[i, :]

        va = vf - vw.T  # Only depending on end of element.
        d_s.append(-.5*rho*d_t*l_s*cd_t*ca.norm_2(va)*va)
    d_s = ca.vcat(d_s)

    v_kcu = v[n_tether_elements-1, :]
    va = v_kcu - vw.T
    d_kcu = -.5*rho*ca.norm_2(va)*va*cd_kcu*frontal_area_kcu

    e_k = 0
    e_p = 0
    f = []  # Non-conservative forces
    tether_lengths = []
    tether_length_consistency_conditions = []

    for i in range(n_elements):
        last_element = i == n_elements - 1
        kcu_element = i == n_elements - 2

        zi = r[i, 2]
        vi = v[i, :]
        vai = vi - vw.T

        if last_element:
            point_mass = m_kite
        elif kcu_element:
            point_mass = m_s/2 + m_kcu
        else:
            point_mass = m_s

        e_k = e_k + .5 * point_mass * ca.dot(vi, vi)
        # if last_element:
        #     print("Resultant force on last mass point is imposed, i.e. gravity and tether forces etc. on last mass "
        #           "point are not included explicitly.")
        # else:
        e_p = e_p + point_mass * zi * g

        if kcu_element:
            fi = d_s[i, :] / 2 + d_kcu
            f.append(fi)
        elif not last_element:
            fi = d_s[i, :]
            f.append(fi)

        if i == 0:
            ri0 = ca.SX.zeros((1, 3))
        else:
            ri0 = r[i-1, :]
        rif = r[i, :]
        dri = rif - ri0
        tether_lengths.append(ca.norm_2(dri))

        if last_element:
            tether_length_consistency_conditions.append(.5 * (ca.dot(dri, dri) - l_bridle**2))
        else:
            tether_length_consistency_conditions.append(.5 * (ca.dot(dri, dri) - l_s**2))

        if last_element:
            ez_last_elem = dri/ca.norm_2(dri)
            ey_last_elem = ca.cross(ez_last_elem, vai)/ca.norm_2(ca.cross(ez_last_elem, vai))
            ex_last_elem = ca.cross(ey_last_elem, ez_last_elem)
            dcm_last_elem = ca.horzcat(ex_last_elem.T, ey_last_elem.T, ez_last_elem.T)

            ez_tau = rif/ca.norm_2(rif)
            ey_tau = ca.cross(ez_tau, vai)/ca.norm_2(ca.cross(ez_tau, vai))
            ex_tau = ca.cross(ey_tau, ez_tau)
            dcm_tau = ca.horzcat(ex_tau.T, ey_tau.T, ez_tau.T)

    f = ca.vcat(f)
    tether_lengths = ca.vcat(tether_lengths)
    tether_length_consistency_conditions = ca.vcat(tether_length_consistency_conditions)

    r = ca.vec(r.T)
    v = ca.vec(v.T)
    f = ca.vec(f.T)

    a00 = ca.jacobian(ca.jacobian(e_k, v[:n_free_pm*3]), v[:n_free_pm*3])
    a10 = ca.jacobian(tether_length_consistency_conditions, r[:n_free_pm*3])
    a0 = ca.horzcat(a00, a10.T)
    a1 = ca.horzcat(a10, ca.SX.zeros((n_elements, n_elements)))
    a = ca.vertcat(a0, a1)

    c0 = f - ca.jacobian(e_p, r[:n_free_pm*3]).T
    gx = ca.jacobian(tether_length_consistency_conditions, r)
    c1 = -ca.jacobian(gx@v, r)@v + ca.vertcat((dl_s**2 + l_s*ddl_s) * ca.SX.ones(n_tether_elements, 1), 0)
    c = ca.vertcat(c0, c1)

    c[n_free_pm*3+n_elements-1] = c[n_free_pm*3+n_elements-1] - (r_wing-r_kcu)@a_wing

    tether_speed_consistency_conditions = gx@v - ca.vertcat(l_s*dl_s * ca.SX.ones(n_tether_elements, 1), 0)

    res = {
        'x': x,
        'u': u,
        'a': a,
        'c': c,
        'a10': a10,
        'g': tether_length_consistency_conditions,
        'dg': tether_speed_consistency_conditions,
        'n_free_pm': n_free_pm,
        'n_elements': n_elements,
        'n_tether_elements': n_tether_elements,
        'tether_lengths': tether_lengths,
        'rotation_matrices': {
            'tangential_plane': dcm_tau,
            'last_element': dcm_last_elem,
        },
        'f_mat': ca.Function('f_mat', [x, u], [a, c])
    }
    return res


def dae_sim(tf, n_intervals, dyn):
    # Returns nu at end of intervals
    a = ca.vec(ca.SX.sym('a', dyn['n_free_pm'], 3).T)
    nu = ca.SX.sym('nu', dyn['n_elements'])
    z = ca.vertcat(a, nu)

    f_z = dyn['a'] @ z - dyn['c']
    f_x = ca.vertcat(dyn['x'][dyn['n_elements']*3:dyn['n_elements']*6], a, dyn['u'][1:4], dyn['x'][dyn['n_elements']*6+1], dyn['u'][0])

    # Create an integrator
    dae = {'x': dyn['x'], 'z': z, 'p': dyn['u'], 'ode': f_x, 'alg': f_z}

    # options = {
    #     "tf": tf,
    #     "number_of_finite_elements": 1,
    #     "interpolation_order": 3,
    #     "collocation_scheme": 'radau',
    # }
    # intg = ca.integrator('intg', 'collocation', dae, options)
    intg = ca.integrator('intg', 'idas', dae, {'tf': tf})

    n_states = dyn['x'].shape[0]
    n_controls = dyn['u'].shape[0]
    x0 = ca.MX.sym('x0', n_states)
    u = ca.MX.sym('u', n_intervals, n_controls)

    x_sol = [x0.T]
    nu_sol = []
    for i in range(n_intervals):
        sol = intg(x0=x_sol[-1], p=u[i, :])
        x_sol.append(sol["xf"].T)
        nu_sol.append(sol["zf"][dyn['n_free_pm']*3:].T)

    x_sol = ca.vcat(x_sol)
    nu_sol = ca.vcat(nu_sol)

    return ca.Function('sim', [x0, u], [x_sol, nu_sol])
