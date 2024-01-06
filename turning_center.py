import numpy as np
from scipy.optimize import least_squares
from utils import add_panel_labels, rotation_matrix_earth2sphere, plot_vector_2d, rotation_matrix_earth2body, get_pitch_nose_down_angle_v3, calc_spherical_coords


def circle_residuals(c, x, y):
    return np.sqrt((x-c[0])**2 + (y-c[1])**2) - c[2]


r_limit = .25
center_estimate = [(0, 0.7, .1), (0, 0.4, .1)]
mark_points = [20, 40, 57, 76, 111, 146, 163, 177, 192]


def find_turn_specs(az, el):
    for j in range(2):
        res = least_squares(circle_residuals, center_estimate[j], args=(az, el), verbose=0)
        xc, yc, r = res.x
        if r < r_limit:
            return (xc, yc, r)
    return (np.nan, np.nan, np.nan)


def find_turns_for_rolling_window(flight_data):
    window = 9
    n_nans = (window-1)//2

    res = np.empty((flight_data.shape[0], 3))
    res[:] = np.nan
    for i in range(n_nans, flight_data.shape[0]-n_nans):
        if np.abs(flight_data.iloc[i].kite_azimuth) < .1:
            continue
        az = np.array(flight_data[i-n_nans:i+n_nans+1].kite_azimuth)
        el = np.array(flight_data[i-n_nans:i+n_nans+1].kite_elevation)
        res[i, :] = find_turn_specs(az, el)
    flight_data['azimuth_turn_center'] = res[:, 0]
    flight_data['elevation_turn_center'] = res[:, 1]
    flight_data['flag_turn'] = res[:, 2] < r_limit


def rigid_body_rotation_errors(omega, r_kite, v_kite, a_kite):
    v_om = np.cross(omega, r_kite)
    a_om = np.cross(omega, v_om)

    v_err = v_kite - v_om
    a_err = a_kite - a_om
    return np.hstack((v_err, a_err))


def determine_rigid_body_rotation(flight_data):
    omega_great_circle = np.empty((flight_data.shape[0], 3))
    omega_radial = np.empty((flight_data.shape[0], 3))
    omega_analytic = np.empty((flight_data.shape[0], 3))
    omega_turn = np.empty((flight_data.shape[0], 3))
    omega_optimized = np.empty((flight_data.shape[0], 3))
    omega_magnitude = np.empty(flight_data.shape[0])

    v_kite_om = np.empty((flight_data.shape[0], 3))
    a_kite_om = np.empty((flight_data.shape[0], 3))
    v_kite_om_opt = np.empty((flight_data.shape[0], 3))
    a_kite_om_opt = np.empty((flight_data.shape[0], 3))

    for i, (idx, row) in enumerate(flight_data.iterrows()):
        # Project measured acceleration on sphere surface
        a_kite = np.array(list(row[['ax', 'ay', 'az']]))
        if i == flight_data.shape[0] - 1:
            a_kite = np.array(list(flight_data.loc[idx-1, ['ax', 'ay', 'az']]))
        v_kite = np.array(list(row[['vx', 'vy', 'vz']]))
        r_kite = np.array(list(row[['rx', 'ry', 'rz']]))

        r_wt = rotation_matrix_earth2sphere(row['kite_azimuth'], row['kite_elevation'], row['kite_course']).T
        ex_t = r_wt[:, 0]
        ey_t = r_wt[:, 1]
        v_kite_tau = row['vt']*ex_t
        om_gc = np.cross(r_kite, v_kite_tau) / np.linalg.norm(r_kite) ** 2
        a_kite_normal = row['an']*ey_t
        om_r = np.cross(v_kite_tau, a_kite_normal) / np.linalg.norm(v_kite_tau) ** 2

        if not np.isnan(row['elevation_turn_center']):  # Turning kite
            elt, azt = row['elevation_turn_center'], row['azimuth_turn_center']
            e_omega = np.array([np.cos(elt)*np.cos(azt), np.cos(elt)*np.sin(azt), np.sin(elt)])
            r_parallel = np.dot(r_kite, e_omega)*e_omega
            r_turn = r_kite - r_parallel

            e_v = np.cross(e_omega, r_kite)
            e_v = e_v/np.linalg.norm(e_v)
            v_kite_rot = np.dot(v_kite, e_v)*e_v

            om_turn = np.cross(r_turn, v_kite_rot)/np.linalg.norm(r_turn)**2
            omega_magnitude[i] = np.linalg.norm(om_turn)

            om_opt = least_squares(rigid_body_rotation_errors, om_turn, args=(r_kite, v_kite, a_kite), verbose=0).x
        else:
            om_turn = [np.nan]*3
            omega_magnitude[i] = np.linalg.norm(om_gc)

            om_opt = least_squares(rigid_body_rotation_errors, om_gc, args=(r_kite, v_kite, a_kite), verbose=0).x

        omega_great_circle[i, :] = om_gc
        omega_radial[i, :] = om_r
        omega_analytic[i, :] = om_gc + om_r
        omega_turn[i, :] = om_turn
        omega_optimized[i, :] = om_opt

        v_om_opt = np.cross(om_opt, r_kite)
        v_kite_om_opt[i] = v_om_opt
        a_om_opt = np.cross(om_opt, v_om_opt)
        a_kite_om_opt[i] = a_om_opt

        v_om = np.cross(om_gc + om_r, r_kite)
        v_kite_om[i] = v_om
        a_om = np.cross(om_gc + om_r, v_om)
        a_kite_om[i] = a_om

    flight_data['omx'] = omega_analytic[:, 0]
    flight_data['omy'] = omega_analytic[:, 1]
    flight_data['omz'] = omega_analytic[:, 2]
    flight_data['omx_opt'] = omega_optimized[:, 0]
    flight_data['omy_opt'] = omega_optimized[:, 1]
    flight_data['omz_opt'] = omega_optimized[:, 2]
    flight_data['omx_gc'] = omega_great_circle[:, 0]
    flight_data['omy_gc'] = omega_great_circle[:, 1]
    flight_data['omz_gc'] = omega_great_circle[:, 2]
    flight_data['omx_turn'] = omega_turn[:, 0]
    flight_data['omy_turn'] = omega_turn[:, 1]
    flight_data['omz_turn'] = omega_turn[:, 2]
    flight_data['om'] = omega_magnitude

    flight_data['vx_om'] = v_kite_om[:, 0]
    flight_data['vy_om'] = v_kite_om[:, 1]
    flight_data['vz_om'] = v_kite_om[:, 2]
    flight_data['ax_om'] = a_kite_om[:, 0]
    flight_data['ay_om'] = a_kite_om[:, 1]
    flight_data['az_om'] = a_kite_om[:, 2]

    flight_data['vx_om_opt'] = v_kite_om_opt[:, 0]
    flight_data['vy_om_opt'] = v_kite_om_opt[:, 1]
    flight_data['vz_om_opt'] = v_kite_om_opt[:, 2]
    flight_data['ax_om_opt'] = a_kite_om_opt[:, 0]
    flight_data['ay_om_opt'] = a_kite_om_opt[:, 1]
    flight_data['az_om_opt'] = a_kite_om_opt[:, 2]


def plot_apparent_wind_velocity(ax, row, vwx, scale_vector=1, **kwargs):
    v_kite = np.array(list(row[['vx', 'vy', 'vz']]))
    v_app = v_kite - np.array([vwx, 0, 0])
    r_sw = rotation_matrix_earth2sphere(row['kite_azimuth'], row['kite_elevation'], 0)

    vec_sphere = r_sw.dot(v_app)
    vec_proj = np.array([vec_sphere[1], -vec_sphere[0]])
    plot_vector_2d([row['kite_azimuth']*180./np.pi, row['kite_elevation']*180./np.pi], vec_proj, ax, scale_vector,
                   **kwargs)


def plot_heading(ax, row, sensor=0, scale_vector=1, **kwargs):
    r_sb = rotation_matrix_earth2body(row[f'roll{sensor}_tau'], row[f'pitch{sensor}_tau'], row[f'yaw{sensor}_tau']).T
    ex_s = r_sb.dot(np.array([1, 0, 0]))
    vec_proj = np.array([ex_s[1], -ex_s[0]])
    plot_vector_2d([row['kite_azimuth'] * 180. / np.pi, row['kite_elevation'] * 180. / np.pi], vec_proj, ax,
                   scale_vector, **kwargs)


def plot_estimated_turn_center(flight_data, animate=False, vwx=10):
    import matplotlib.pyplot as plt
    ax = plt.figure(figsize=[5.8, 3]).gca()
    plt.subplots_adjust(top=1.0, bottom=0.16, left=0.1, right=.99)
    if animate:
        for i in range(flight_data.shape[0]):
            ax.cla()
            ax.set_xlim([-20, 20])
            ax.set_ylim([24, 46])
            ax.set_xlabel('Azimuth [$^\circ$]')
            ax.set_ylabel('Elevation [$^\circ$]')
            ax.set_aspect('equal')

            ax.plot(flight_data.iloc[:i]['kite_azimuth']*180./np.pi, flight_data.iloc[:i]['kite_elevation']*180./np.pi)
            ax.plot(flight_data.iloc[:i]['azimuth_turn_center']*180./np.pi, flight_data.iloc[:i]['elevation_turn_center']*180./np.pi, linewidth=.5, color='grey')
            ax.plot(flight_data.iloc[i]['azimuth_turn_center']*180./np.pi, flight_data.iloc[i]['elevation_turn_center']*180./np.pi, 's')
            plt.pause(0.001)
    else:
        ax.set_xlim([-23, 23])
        ax.set_ylim([24, 47])
        ax.set_xlabel('Azimuth [$^\circ$]')
        ax.set_ylabel('Elevation [$^\circ$]')
        ax.set_aspect('equal')

        az, el = flight_data['kite_azimuth']*180./np.pi, flight_data['kite_elevation']*180./np.pi
        ax.plot(np.where(~flight_data['flag_turn'], az, np.nan), np.where(~flight_data['flag_turn'], el, np.nan), color='C0', label='Straight')
        ax.plot(np.where(flight_data['flag_turn'], az, np.nan), np.where(flight_data['flag_turn'], el, np.nan), '--', color='C0', label='Turn')

        ax.plot(flight_data['azimuth_turn_center']*180./np.pi, flight_data['elevation_turn_center']*180./np.pi, linewidth=.8, color='tomato', label='Turn centre')

        for j, im in enumerate(mark_points):
            row = flight_data.iloc[im]

            if j == 0:
                lbl_va = r'$v_{a,\tau}$'
                lbl_heading = 'Heading'
            else:
                lbl_va = None
                lbl_heading = None
            plot_apparent_wind_velocity(ax, row, vwx, .3, color='g', linestyle=':', label=lbl_va)
            plot_heading(ax, row, 1, 5, linewidth=1, color='grey', label=lbl_heading)

            az_tc, el_tc = row['azimuth_turn_center']*180./np.pi, row['elevation_turn_center']*180./np.pi
            # if np.isnan(az_tc):
            marker = 's'
            # else:
            #     marker = 'o'
            ax.plot(az_tc, el_tc, marker, mfc="white", alpha=1, ms=6, mec='C{}'.format(j))

            az, el = row['kite_azimuth']*180./np.pi, row['kite_elevation']*180./np.pi
            ax.plot(az, el, marker, mfc="white", alpha=1, ms=12, mec='C{}'.format(j))
            ax.plot(az, el, marker='${}$'.format(j+1), alpha=1, ms=7, mec='C{}'.format(j))
        legend = ax.legend(ncol=3)
        ax.grid()


def visualize_estimated_rotation_vector(flight_data, animate=False):
    import matplotlib.pyplot as plt

    def calc_sphere_coords(x, y, z):
        r = (x**2 + y**2 + z**2)**.5
        el = np.arcsin(z/r)*180./np.pi
        az = np.arctan2(y, x)*180./np.pi
        return az, el, r

    om_opt_sphere = calc_sphere_coords(flight_data.omx_opt, flight_data.omy_opt, flight_data.omz_opt)

    # Plot only the magnitude for the paper
    fig, ax = plt.subplots(3, 1, figsize=[5.8, 4.8], sharex=True)
    plt.subplots_adjust(top=0.985, bottom=0.105, left=0.185, right=0.985, hspace=0.125)
    ax[0].plot(flight_data.time, flight_data.om, color='C3', label=r'$\omega_{\rm straight/turn}$', linewidth=1)
    ax[0].plot(flight_data.time, om_opt_sphere[2], '--', color='C0', label=r'$\omega_{\rm opt}$')
    ax[0].set_xlim([flight_data['time'].iloc[0], flight_data['time'].iloc[-1]])
    ax[0].set_ylim([0, None])
    ax[0].set_ylabel('Rotational\nspeed [rad s$^{-1}$]')
    ax[0].legend(ncol=2)

    ax[1].plot(flight_data.time, (flight_data.vx**2+flight_data.vy**2+flight_data.vz**2)**.5, color='C1', label='Reconstructed')
    ax[1].plot(flight_data.time, (flight_data.kite_0_vx**2+flight_data.kite_0_vy**2+flight_data.kite_0_vz**2)**.5, ':', color='C2', label='Flight data')
    ax[1].plot(flight_data.time, (flight_data.vx_om**2+flight_data.vy_om**2+flight_data.vz_om**2)**.5, color='C3', linewidth=1)  #, label=r'$\omega_{\rm rb-gc/turn}$')
    ax[1].plot(flight_data.time, (flight_data.vx_om_opt**2+flight_data.vy_om_opt**2+flight_data.vz_om_opt**2)**.5, '--', color='C0')  #, label=r'$\omega_{\rm rb-opt}$')
    ax[1].plot(flight_data.time, flight_data.vt, color='C4', label='Tangential')
    ax[1].set_ylabel('Wing speed\n[m s$^{-1}$]')
    ax[1].legend(ncol=2)

    ax[2].plot(flight_data.time, (flight_data.ax**2+flight_data.ay**2+flight_data.az**2)**.5, color='C1', label='Reconstructed')
    ax[2].plot(flight_data.time, (flight_data.kite_1_ax**2+flight_data.kite_1_ay**2+flight_data.kite_1_az**2)**.5, ':', color='C2', label='Flight data')
    ax[2].plot(flight_data.time, (flight_data.ax_om**2+flight_data.ay_om**2+flight_data.az_om**2)**.5, color='C3', linewidth=1)
    ax[2].plot(flight_data.time, (flight_data.ax_om_opt**2+flight_data.ay_om_opt**2+flight_data.az_om_opt**2)**.5, '--', color='C0')
    ax[2].plot(flight_data.time, flight_data.an, color='C4', label='Normal')
    ax[2].plot(flight_data.time, flight_data.an.abs(), ':', color='C4', label='Normal')
    ax[2].set_ylabel('Wing\nacceleration [m s$^{-2}$]')

    add_panel_labels(ax, offset_x=.22)
    ax[2].set_xlabel('Time [s]')
    for a in ax:
        a.grid()
        y1 = a.get_ylim()[1]
        a.set_ylim([0, y1])
        a.fill_between(flight_data.time, 0, y1, where=flight_data['flag_turn'], facecolor='lightgrey', alpha=0.5)


def compare_rotational_velocities(flight_data):
    import matplotlib.pyplot as plt

    # Plot only the magnitude for the paper
    fig, ax = plt.subplots(3, 1, figsize=[5.8, 4.8], sharex=True)
    plt.subplots_adjust(top=0.985, bottom=0.105, left=0.185, right=0.985, hspace=0.125)
    ax[0].plot(flight_data.time, flight_data.omx, label='analytic')
    ax[0].plot(flight_data.time, flight_data.omx_opt, label='opt')
    ax[0].plot(flight_data.time, flight_data.omx_gc, label='great circle')
    ax[0].plot(flight_data.time, flight_data.omx_turn, label='turn')
    ax[0].set_xlim([flight_data['time'].iloc[0], flight_data['time'].iloc[-1]])
    ax[0].set_ylabel('x-component rotational\nvelocity [rad s$^{-1}$]')
    ax[0].legend()

    ax[1].plot(flight_data.time, flight_data.omy)
    ax[1].plot(flight_data.time, flight_data.omy_opt)
    ax[1].plot(flight_data.time, flight_data.omy_gc)
    ax[1].plot(flight_data.time, flight_data.omy_turn)
    ax[1].set_ylabel('y-component rotational\nvelocity [rad s$^{-1}$]')

    ax[2].plot(flight_data.time, flight_data.omz)
    ax[2].plot(flight_data.time, flight_data.omz_opt)
    ax[2].plot(flight_data.time, flight_data.omz_gc)
    ax[2].plot(flight_data.time, flight_data.omz_turn)
    ax[2].set_ylabel('z-component rotational\nvelocity [rad s$^{-1}$]')

    add_panel_labels(ax, offset_x=.22)
    ax[2].set_xlabel('Time [s]')
    for a in ax:
        a.grid()
        a.fill_between(flight_data.time, a.get_ylim()[0], a.get_ylim()[1], where=flight_data['flag_turn'], facecolor='lightgrey', alpha=0.5)


if __name__ == "__main__":
    from utils import read_and_transform_flight_data
    from matplotlib.pyplot import show
    flight_data = read_and_transform_flight_data(make_kinematics_consistent=True)
    print("Min. and max. height: {:.2f} and {:.2f}".format(flight_data['rz'].min(), flight_data['rz'].max()))
    print("Start and height radial position: {:.2f} and {:.2f}".format(flight_data.iloc[0]['kite_distance'], flight_data.iloc[-1]['kite_distance']))
    determine_rigid_body_rotation(flight_data)
    plot_estimated_turn_center(flight_data)  # Plots figure 4
    visualize_estimated_rotation_vector(flight_data)  # Plots figure 6
    compare_rotational_velocities(flight_data)
    show()
