"""export_simulink_cases.py — Experiment D scaffold: L1 switching-level spot-check EXPORTER (九.D).

This is the L1 hand-off ONLY: it selects representative network cases and exports the LOCAL voltage
trajectories (three-phase magnitudes Vabc + sequence Vp/Vn over the fault+recovery window) plus the
Mode-5 command the controller issued, to a .mat per case + a scaffold table. It DOES NOT run
Simulink (per the chosen plan): the switching-level run (measured iq peak, 2ω ripple, Vdc_min/max,
the 5 criteria at SPWM/IGBT level) is a separate, later step. Until that runs, L1 columns stay
empty and the report must label network results as 策略级/相量层 (sections 十二.5/.6).

Representative categories (section 九.D.1): super-deep sag (Vp 0.05-0.15), asymmetric propagation,
strong multi-HPT coupling, slow recovery, near-criteria-boundary success & failure.
"""
import os, sys, csv
os.environ.setdefault('KMP_DUPLICATE_LIB_OK', 'TRUE')
os.environ.setdefault('MKL_THREADING_LAYER', 'SEQUENTIAL')
import numpy as np
import scipy.io as sio
from . import config as C
from . import opendss_runner as R
from . import sequence as SQ
from .hpt_interface import HPT

SIM_DIR = C.RESULTS / 'simulink_cases'
SIM_DIR.mkdir(exist_ok=True)

# (label, category, hpt_bus, fault_bus, fault_type, r, recovery)
CASES = [
    ('D1_superdeep_sym',   'super-deep sag',     7,  6,  'sym3ph', 0.3, 'instant'),
    ('D2_superdeep_sym2',  'super-deep sag',     14, 2,  'sym3ph', 0.3, 'instant'),
    ('D3_asym_1ph',        'asymmetric prop.',   25, 25, '1ph_g',  0.4, 'instant'),
    ('D4_asym_2ph',        'asymmetric prop.',   30, 30, '2ph',    0.4, 'instant'),
    ('D5_asym_2phg',       'asymmetric prop.',   14, 14, '2ph_g',  0.4, 'instant'),
    ('D6_coupling_dense',  'strong coupling',    10, 6,  'sym3ph', 0.4, 'instant'),
    ('D7_slow_recovery',   'slow recovery',      7,  6,  'sym3ph', 0.4, 'slow'),
    ('D8_slow_recovery_a', 'slow recovery',      25, 25, '1ph_g',  0.4, 'slow'),
    ('D9_boundary_pass',   'criteria boundary',  30, 12, 'sym3ph', 1.8, 'instant'),
    ('D10_boundary_fail',  'criteria boundary',  7,  3,  'sym3ph', 0.3, 'instant'),
]


def export_case(label, category, hpt_bus, fault_bus, ftype, r, recovery):
    """Time-domain single-HPT run that also records the three phase magnitudes for Simulink."""
    sc = dict(id=label, fault_bus=fault_bus, fault_type=ftype, r_fault=r, load_lvl=1.0, pv_pen=0.3)
    hpt = HPT(hpt_bus, use_hysteresis=True)
    hpt.reset()
    pre = R.build_network(sc, [hpt_bus], [0.0], fault=True)
    minV = pre['minV'] if pre else 0.0
    dur = C.duration_rule(minV)
    v_fault_p = max(0.2, min(0.95, minV))
    t_clear = C.T_PRE + dur
    t_recover = 0.7
    t_end = t_clear + (t_recover + 0.4 if recovery == 'slow' else 0.4)
    grid = np.arange(0, t_end + 1e-9, C.DT_SNAP)
    T, VA, VB, VC, VP, VN, IQ, SED, SEQ, VDC, GATE = ([] for _ in range(11))
    q = 0.0
    for t in grid:
        if t < C.T_PRE:
            fault, src = False, 1.0
        elif t < t_clear:
            fault, src = True, 1.0
        else:
            fault = False
            src = SQ.recovery_curve(t, t_clear, t_recover, v_fault_p) if recovery == 'slow' else 1.0
        net = R.build_network(sc, [hpt_bus], [q], fault=fault, source_pu=src)
        if net is None:
            continue
        va, vb, vc = SQ.phase_mags(hpt_bus)                  # circuit still solved -> query phases
        Vp, Vn = net['seq'][str(hpt_bus)]
        c = hpt.step(Vp, Vn, float(t), in_fault=fault)
        q = hpt.kvar
        T.append(t); VA.append(va); VB.append(vb); VC.append(vc); VP.append(Vp); VN.append(Vn)
        IQ.append(c['iq']); SED.append(c['se_d']); SEQ.append(c['se_q']); VDC.append(c['Vdc'])
        GATE.append(c['gate'])
    mat = dict(label=label, category=category, hpt_bus=hpt_bus, fault_bus=fault_bus,
               fault_type=ftype, r_fault=r, recovery=recovery, dt=C.DT_SNAP, dur=dur, minV=minV,
               t=np.array(T), Vabc=np.array([VA, VB, VC]), Vp=np.array(VP), Vn=np.array(VN),
               iq_cmd=np.array(IQ), se_d_cmd=np.array(SED), se_q_cmd=np.array(SEQ),
               vdc_surrogate=np.array(VDC),
               README=('L2 phasor trajectory for Simulink switching-level injection. Inject Vabc(t) '
                       'as the HPT terminal voltage; the closed-loop HLC (Mode 5, mi==12) regenerates '
                       'iq/se. Compare measured iq peak, 2w ripple, Vdc_min/max, 5 criteria vs the '
                       'phasor-layer iq_cmd/vdc_surrogate here.'))
    sio.savemat(str(SIM_DIR / f'{label}.mat'), mat)
    return dict(label=label, category=category, hpt_bus=hpt_bus, fault_bus=fault_bus,
                fault_type=ftype, r_fault=r, recovery=recovery, minV=round(minV, 3), dur=dur,
                Vp_min=round(float(min(VP)), 3), Vn_max=round(float(max(VN)), 3),
                iq_cmd_max=round(float(np.max(np.abs(IQ))), 3),
                vdc_surrogate_min=round(float(min(VDC)), 3),
                # L1 columns to be filled by the Simulink run (PENDING):
                iq_peak_measured='', ripple_2w='', Vdc_min_sw='', Vdc_max_sw='',
                connect_sw='', reactive_sw='', limit_sw='', recover_sw='', survive_sw='',
                frt_pass_sw='', L1_status='PENDING_SWITCHING_RUN')


def run():
    rows = [export_case(*c) for c in CASES]
    table = SIM_DIR / 'simulink_spotcheck_table.csv'
    with open(table, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    print('=== Experiment D: Simulink spot-check EXPORT (L1 hand-off, switching run PENDING) ===')
    print(f'exported {len(rows)} cases -> {SIM_DIR}')
    for r in rows:
        print(f'  {r["label"]:20s} [{r["category"]:16s}] Vp_min={r["Vp_min"]:.3f} '
              f'Vn_max={r["Vn_max"]:.3f} iq_cmd_max={r["iq_cmd_max"]:.3f} '
              f'vdc_surr_min={r["vdc_surrogate_min"]:.3f}')
    print(f'\nscaffold table: {table}  (L1 *_sw columns empty -> switching-level run is PENDING)')
    print('NOTE: network results remain 策略级/相量层 until these Simulink runs are executed.')


if __name__ == '__main__':
    run()
