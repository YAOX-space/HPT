"""run_exp_A_single_hpt.py — Experiment A: single-HPT network OOD sweep (section 九.A).

Goal: does the single-device SAC extrapolate sanely to the CONTINUOUS local sag depths the feeder
produces (Vp 0.05..0.90), instead of the discrete training residuals 0.2/0.5/0.75?

One HPT at a time at each of buses {7,14,25,30}. Sweep fault location (2..33) × resistance (log
grid) × type {sym3ph,1ph_g} → the HPT's local (Vp,Vn) spans the whole OOD range. For each operating
point record the gated command, surrogate Vdc_min and the FRT criteria, and flag any anomaly
(NaN / wrong reactive sign / cap violation / Vdc collapse / saturation).

Outputs: results/exp_A_summary.csv  + console anomaly report.
"""
import os, sys, csv
os.environ.setdefault('KMP_DUPLICATE_LIB_OK', 'TRUE')
os.environ.setdefault('MKL_THREADING_LAYER', 'SEQUENTIAL')
import numpy as np
from . import config as C
from . import opendss_runner as R
from .hpt_interface import HPT, lv_compensated
from . import metrics as M

R_GRID = [0.3, 0.6, 1.0, 1.8, 3.0, 6.0, 12.0, 30.0]
FAULT_BUSES = list(range(2, 34))
FTYPES = ['sym3ph', '1ph_g']
LOAD_LVL, PV_PEN = 1.0, 0.3


def run():
    rows, anomalies = [], []
    for hb in C.PLACE_A:
        hpt = HPT(hb, use_hysteresis=True)
        for ft in FTYPES:
            for fb in FAULT_BUSES:
                for r in R_GRID:
                    sc = dict(load_lvl=LOAD_LVL, pv_pen=PV_PEN, fault_bus=fb, fault_type=ft, r_fault=r)
                    cmds, info = R.solve_fixed_point(sc, [hpt], fault=True)
                    if cmds is None:
                        continue
                    c = cmds[0]
                    Vp, Vn = info['seq'][str(hb)]
                    dur = C.duration_rule(info['minV'])
                    vdc_min, vdc_max = M.vdc_window(C.vdc_eq(c['iq'], c['se_d'], c['se_q'], max(0.05, Vp)), dur)
                    v_load = lv_compensated(Vp, c['se_d'])
                    crit = M.device_criteria(Vp=Vp, Vn=Vn, iq=c['iq'], se_d=c['se_d'], se_q=c['se_q'],
                                             iq_ref=c['iq_ref'], vdc_min=vdc_min, vdc_max=vdc_max,
                                             v_load=v_load, gate=c['gate'], dur=dur)
                    flags = []
                    if not np.isfinite(c['iq']) or not np.isfinite(c['se_d']):
                        flags.append('NAN')
                    if Vp < 0.9 and c['iq'] < -1e-3:
                        flags.append('WRONG_SIGN')
                    if abs(c['iq']) > c['cap'] + 1e-3:
                        flags.append('CAP_VIOL')
                    if Vp < 0.85 and c['iq'] < 0.02:
                        flags.append('LOW_IQ')
                    if vdc_min < C.VDC_MIN_OK:
                        flags.append('VDC_LOW')
                    row = dict(hpt_bus=hb, fault_bus=fb, fault_type=ft, r_fault=round(r, 3),
                               Vp=round(Vp, 4), Vn=round(Vn, 4), gate=c['gate'],
                               iq=round(c['iq'], 4), iq_ref=round(c['iq_ref'], 4),
                               se_d=round(c['se_d'], 4), se_q=round(c['se_q'], 4),
                               vdc_eq=round(c['Vdc'], 4), vdc_min=round(vdc_min, 4),
                               v_load=round(v_load, 4), clipped=int(c['clipped']),
                               dur=dur, **{k: int(v) for k, v in crit.items()},
                               flags='|'.join(flags))
                    rows.append(row)
                    if flags and set(flags) - {'LOW_IQ', 'VDC_LOW'}:
                        anomalies.append(row)
        print(f'  HPT@{hb}: {sum(1 for x in rows if x["hpt_bus"]==hb)} operating points')

    out = C.RESULTS / 'exp_A_summary.csv'
    with open(out, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    # anomaly report
    Vps = np.array([r['Vp'] for r in rows])
    deep = [r for r in rows if r['Vp'] < 0.15]
    print('\n=== Experiment A: single-HPT OOD sweep ===')
    print(f'total operating points: {len(rows)}  (Vp range {Vps.min():.3f}..{Vps.max():.3f})')
    print(f'deep-OOD points (Vp<0.15): {len(deep)}  '
          f'wrong-sign={sum(1 for r in deep if "WRONG_SIGN" in r["flags"])}  '
          f'NaN={sum(1 for r in deep if "NAN" in r["flags"])}')
    print(f'serious anomalies (sign/NaN/cap): {len(anomalies)}')
    for ft in FTYPES:
        sub = [r for r in rows if r['fault_type'] == ft and r['Vp'] < 0.9]
        if sub:
            print(f'  [{ft}] undervolt pts={len(sub)}  reactive_ok={100*np.mean([r["reactive"] for r in sub]):.0f}%'
                  f'  screen_pass={100*np.mean([r["screen_pass"] for r in sub]):.0f}%'
                  f'  Vdc_min(min)={min(r["vdc_min"] for r in sub):.3f}')
    print(f'saved {out}')
    return rows, anomalies


if __name__ == '__main__':
    run()
