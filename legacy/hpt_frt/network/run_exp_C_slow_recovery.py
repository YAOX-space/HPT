"""run_exp_C_slow_recovery.py — Experiment C: slow-recovery / FIDVR stress test (section 九.C).

Goal: after the fault clears, the network voltage does NOT snap back — it recovers slowly over
0.5-1.0 s (FIDVR-like, modelled here as the substation source pu ramping back up). Does the SAC:
  * withdraw reactive current smoothly (no abrupt jump / overshoot)?
  * keep Vdc ≥ 0.75 and current ≤ 0.35 throughout the recovery transient?
  * avoid multi-HPT recovery oscillation?
  * (Mode 5) avoid GATE CHATTERING as (V2p,V2n) drift across the gate thresholds during recovery?

We run the dense 10-HPT fleet (strongest coupling) on deep faults × recovery shape {linear,exp} ×
gate variant {raw, hysteresis} — the raw-vs-hysteresis pair quantifies the chattering and its
mitigation (sections 八.10 / 十二.8).

Outputs: exp_C_summary.csv, failures_C.csv, per_hpt_timeseries/C_*.csv.
"""
import os, sys, csv, json
os.environ.setdefault('KMP_DUPLICATE_LIB_OK', 'TRUE')
os.environ.setdefault('MKL_THREADING_LAYER', 'SEQUENTIAL')
import numpy as np
from . import config as C
from . import opendss_runner as R
from .hpt_interface import HPT

DEEP = [
    dict(id=1, fault_bus=2,  fault_type='sym3ph', r_fault=0.3),
    dict(id=2, fault_bus=6,  fault_type='sym3ph', r_fault=0.4),
    dict(id=3, fault_bus=10, fault_type='1ph_g',  r_fault=0.3),
    dict(id=4, fault_bus=25, fault_type='1ph_g',  r_fault=0.4),
    dict(id=5, fault_bus=30, fault_type='2ph',    r_fault=0.4),
    dict(id=6, fault_bus=14, fault_type='2ph_g',  r_fault=0.4),
    dict(id=7, fault_bus=6,  fault_type='2ph',    r_fault=0.3),
    dict(id=8, fault_bus=18, fault_type='sym3ph', r_fault=0.5),
]
for d in DEEP:
    d.update(load_lvl=1.0, pv_pen=0.3)


def recovery_smoothness(tr, t_clear):
    """Max |Δiq| per step during the recovery window (smooth withdrawal => small)."""
    log = [r for r in tr['log'] if r['t'] >= t_clear]
    if len(log) < 2:
        return 0.0, 0.0
    diq = [abs(log[i + 1]['iq'] - log[i]['iq']) for i in range(len(log) - 1)]
    return float(max(diq)), float(log[-1]['iq'])


def run():
    rows, failures, saved = [], [], 0
    for kind in ['linear', 'exp']:
        for gate_variant, use_hyst in [('raw', False), ('hyst', True)]:
            for sc in DEEP:
                hpts = [HPT(b, use_hysteresis=use_hyst) for b in C.PLACE_C]
                sim = R.simulate(sc, hpts, recovery='slow', t_recover=0.7, kind=kind)
                worst_vdc, max_iq, max_diq, n_chatter, tot_switch = 1.0, 0.0, 0.0, 0, 0
                end_iqs = []
                for tr in sim['trajectories']:
                    if tr is None:
                        continue
                    worst_vdc = min(worst_vdc, tr['Vdc_min'])
                    max_iq = max(max_iq, tr['iq_max'])
                    diq, iq_end = recovery_smoothness(tr, sim['t_clear'])
                    max_diq = max(max_diq, diq)
                    end_iqs.append(abs(iq_end))
                    g = tr['gate']
                    n_chatter += int(g['chattering'])
                    tot_switch += g['switches']
                # recovery oscillation: any HPT's iq non-monotone bump during recovery (Δiq large)
                osc = max_diq > 0.10
                smooth_exit = max_diq <= 0.10 and max(end_iqs) < 0.05
                vdc_ok = worst_vdc >= C.VDC_MIN_OK
                limit_ok = max_iq <= C.LIMIT_PU + 1e-6
                row = dict(scn=sc['id'], fault_bus=sc['fault_bus'], fault_type=sc['fault_type'],
                           r_fault=sc['r_fault'], recovery=kind, gate=gate_variant,
                           minV=round(sim['minV'], 3), dur=sim['dur'],
                           worst_vdc=round(worst_vdc, 3), max_iq=round(max_iq, 3),
                           max_diq=round(max_diq, 4), end_iq=round(max(end_iqs), 4),
                           chatter_hpts=n_chatter, total_switches=tot_switch,
                           vdc_ok=int(vdc_ok), limit_ok=int(limit_ok),
                           smooth_exit=int(smooth_exit), recov_osc=int(osc),
                           nonconv=sim['nonconv'])
                rows.append(row)
                if not (vdc_ok and limit_ok and smooth_exit) or n_chatter > 0:
                    failures.append(row)
                # save representative time series (exp recovery, both gate variants, 3 scenarios)
                if kind == 'exp' and sc['id'] in (1, 3, 5):
                    _save_ts(f'C_{gate_variant}_{sc["id"]}_{sc["fault_type"]}', sim)
                    saved += 1

    _csv(C.RESULTS / 'exp_C_summary.csv', rows)
    _csv(C.RESULTS / 'failures_C.csv', failures)
    (C.RESULTS / 'exp_C_summary.json').write_text(json.dumps(rows, indent=1))

    # ── gate chattering: raw vs hysteresis ────────────────────────────────────────
    print('\n=== Experiment C: slow-recovery / FIDVR ===')
    for gv in ['raw', 'hyst']:
        sub = [r for r in rows if r['gate'] == gv]
        print(f'  gate={gv:4s}: switches/scn(mean)={np.mean([r["total_switches"] for r in sub]):.1f}  '
              f'chatter-HPTs/scn(mean)={np.mean([r["chatter_hpts"] for r in sub]):.2f}  '
              f'worst_vdc(min)={min(r["worst_vdc"] for r in sub):.3f}  '
              f'max_iq={max(r["max_iq"] for r in sub):.3f}  '
              f'smooth_exit={100*np.mean([r["smooth_exit"] for r in sub]):.0f}%  '
              f'recov_osc={100*np.mean([r["recov_osc"] for r in sub]):.0f}%')
    print(f'Vdc≥0.75 all={100*np.mean([r["vdc_ok"] for r in rows]):.0f}%  '
          f'limit(iq≤0.35) all={100*np.mean([r["limit_ok"] for r in rows]):.0f}%')
    print(f'saved exp_C_summary.csv ({len(rows)} runs), failures_C.csv ({len(failures)}), '
          f'{saved} time-series')
    return rows


def _save_ts(name, sim):
    for tr in sim['trajectories']:
        if tr is None:
            continue
        with open(C.TS_DIR / f'{name}_hpt{tr["bus"]}.csv', 'w', newline='') as f:
            w = csv.writer(f)
            w.writerow(['t', 'Vp', 'Vn', 'iq', 'iq_ref', 'se_d', 'Vdc', 'v_load', 'gate', 'in_fault'])
            for r in tr['log']:
                w.writerow([round(r['t'], 4), round(r['Vp'], 4), round(r['Vn'], 4), round(r['iq'], 4),
                            round(r['iq_ref'], 4), round(r['se_d'], 4), round(r['Vdc'], 4),
                            round(r['v_load'], 4), r['gate'], r['in_fault']])


def _csv(path, rows):
    if not rows:
        path.write_text(''); return
    with open(path, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)


if __name__ == '__main__':
    run()
