"""study_gate_noise.py — Round-2 §4: does the "raw gate needs no hysteresis" conclusion survive
MEASUREMENT NOISE + DELAY? Slow-recovery scenarios (where V2p,V2n drift across the gate thresholds)
at dt=5 ms, sweeping Vp/Vn noise and measurement delay, comparing 4 gate variants:
  raw | hysteresis+dwell | raw+slew | hysteresis+slew.
slew = 15 pu/s on iq, 10 pu/s on series (= 0.03/0.02 per 2 ms control step) -> per-5ms-step 0.075/0.05.

Metrics: gate switches, chattering count, max iq jump, max mse jump, survive (Vdc>=0.75), Vdc_min,
recover, oscillation (iq jump>0.1). Output: results/gate_noise_summary.csv.
"""
import os, sys, csv
os.environ.setdefault('KMP_DUPLICATE_LIB_OK', 'TRUE'); os.environ.setdefault('MKL_THREADING_LAYER', 'SEQUENTIAL')
import numpy as np
from . import config as C
from . import opendss_runner as R
from .hpt_interface import HPT

DT = 0.005
SLEW = (0.075, 0.05)                     # 15 pu/s iq, 10 pu/s series at dt=5ms
SCEN = [
    dict(fault_bus=6,  fault_type='sym3ph', r_fault=0.4, load_lvl=1.0, pv_pen=0.3),
    dict(fault_bus=25, fault_type='1ph_g',  r_fault=0.4, load_lvl=1.0, pv_pen=0.3),
    dict(fault_bus=30, fault_type='2ph',    r_fault=0.4, load_lvl=1.0, pv_pen=0.3),
    dict(fault_bus=14, fault_type='2ph_g',  r_fault=0.4, load_lvl=1.0, pv_pen=0.3),
]
NOISE = [(0.0, 0.0), (0.002, 0.002), (0.005, 0.005), (0.01, 0.005)]
DELAYS = [0, 1, 2]                       # 0, 5 ms, 10 ms
VARIANTS = {
    'raw':        dict(use_hysteresis=False),
    'hyst':       dict(use_hysteresis=True),
    'raw_slew':   dict(use_hysteresis=False, slew=SLEW),
    'hyst_slew':  dict(use_hysteresis=True, slew=SLEW),
}


def metrics_from_sim(sim):
    sw = ch = 0; iqjmp = msjmp = 0.0; vdcmin = 1.0; iqmax = 0.0; recov = 1.0
    for tr in sim['trajectories']:
        if tr is None:
            continue
        g = tr['gate']; sw += g['switches']; ch += int(g['chattering'])
        L = tr['log']
        for i in range(1, len(L)):
            iqjmp = max(iqjmp, abs(L[i]['iq'] - L[i-1]['iq']))
            msjmp = max(msjmp, abs(L[i]['se_d'] - L[i-1]['se_d']))
        vdcmin = min(vdcmin, tr['Vdc_min']); iqmax = max(iqmax, tr['iq_max'])
        if tr['v_post'] is not None:
            recov = min(recov, 1.0 - abs(1.0 - tr['v_post']))
    return dict(switches=sw, chatter=ch, iq_jump=round(iqjmp, 4), mse_jump=round(msjmp, 4),
                vdc_min=round(vdcmin, 3), iq_max=round(iqmax, 3),
                survive=int(vdcmin >= 0.75), limit=int(iqmax <= 0.35),
                oscillation=int(iqjmp > 0.10))


def run():
    rows = []
    for (vpn, vnn) in NOISE:
        for dl in DELAYS:
            for vname, vkw in VARIANTS.items():
                agg = {k: 0.0 for k in ('switches', 'chatter', 'iq_jump', 'mse_jump', 'vdc_min',
                                        'iq_max', 'survive', 'limit', 'oscillation')}
                nz = 0
                for sc in SCEN:
                    fleet = [HPT(b, vp_noise=vpn, vn_noise=vnn, meas_delay=dl, noise_seed=7, **vkw)
                             for b in C.PLACE_C]
                    sim = R.simulate({**sc, 'id': 0}, fleet, recovery='slow', t_recover=0.7, dt=DT)
                    m = metrics_from_sim(sim)
                    for k in agg:
                        agg[k] += m[k]
                    nz += 1
                rows.append(dict(vp_noise=vpn, vn_noise=vnn, delay_steps=dl, delay_ms=dl*DT*1000,
                                 variant=vname,
                                 switches=round(agg['switches']/nz, 1), chatter=round(agg['chatter']/nz, 2),
                                 iq_jump=round(agg['iq_jump']/nz, 4), mse_jump=round(agg['mse_jump']/nz, 4),
                                 vdc_min=round(agg['vdc_min']/nz, 3),
                                 survive_pct=round(100*agg['survive']/nz), limit_pct=round(100*agg['limit']/nz),
                                 oscillation_pct=round(100*agg['oscillation']/nz)))
    with open(C.RESULTS / 'gate_noise_summary.csv', 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)

    print('=== Round-2 §4: gate robustness under noise + delay (dt=5ms, slow recovery) ===')
    print(f'{"noise(vp/vn)":>12} {"delay":>6} {"variant":>10} {"switch":>7} {"chat":>5} {"iqjump":>7} {"msejmp":>7} {"surv%":>6}')
    for r in rows:
        print(f'{r["vp_noise"]:.3f}/{r["vn_noise"]:.3f} {r["delay_ms"]:5.0f}ms {r["variant"]:>10} '
              f'{r["switches"]:7.1f} {r["chatter"]:5.2f} {r["iq_jump"]:7.4f} {r["mse_jump"]:7.4f} {r["survive_pct"]:5.0f}')
    # headline: worst-noise raw vs raw_slew chatter + iq jump
    worst = [r for r in rows if r['vp_noise'] == 0.01]
    for v in ['raw', 'hyst', 'raw_slew', 'hyst_slew']:
        sub = [r for r in worst if r['variant'] == v]
        print(f'  [worst-noise vp=0.01] {v:10s}: mean switches={np.mean([r["switches"] for r in sub]):.1f} '
              f'chatter={np.mean([r["chatter"] for r in sub]):.2f} iq_jump={np.mean([r["iq_jump"] for r in sub]):.4f}')
    print('saved gate_noise_summary.csv')


if __name__ == '__main__':
    run()
