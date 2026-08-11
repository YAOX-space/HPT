"""run_exp_B_multi_hpt.py — Experiment B: multi-HPT independent-SAC coupling (section 九.B).

Goal: do multiple HPTs, each independently running the SAME device-level Mode-5 SAC with ONLY its
own local measurements (no coordinator), fight each other through the network — oscillation,
reactive sign-reversal, non-convergent power flow, or device failure?

Scheme B = 4 HPTs {7,14,25,30}; Scheme C = 10 dense HPTs. For every scenario (default 400 +
48-debug) we solve the network<->fleet fixed point, evaluate the 5 FRT criteria per HPT, and the
system-level metrics (convergence, wrong-sign, oscillation, load ride-through, total Q, minV).
Representative scenarios also get a time-domain run (per_hpt_timeseries/).

Outputs: exp_B_summary.csv, per_scenario_detail.csv (+per_hpt_timeseries/*.csv), failures_B.csv.
Usage: python run_exp_B_multi_hpt.py [full|debug]
"""
import os, sys, csv, json
os.environ.setdefault('KMP_DUPLICATE_LIB_OK', 'TRUE')
os.environ.setdefault('MKL_THREADING_LAYER', 'SEQUENTIAL')
from . import config as C
from . import opendss_runner as R
from .hpt_interface import HPT, lv_compensated
from .sac_wrapper import iq_ref_gbt
from . import scenarios as SCN
from . import metrics as M

SCHEMES = {'B4': C.PLACE_B, 'C10': C.PLACE_C}


def eval_scenario(sc, hpts):
    """Network<->fleet fixed point + per-HPT FRT criteria + system metrics for one scenario."""
    cmds, info = R.solve_fixed_point(sc, hpts, fault=True)
    if cmds is None or info.get('nonconverged'):
        return None, dict(converged=False, nonconverged=True, oscillation=False, wrong_sign=0,
                          minV=None, all_mean={}), info
    dur = C.duration_rule(info['minV'])
    # post-fault cleared snapshot (shared) for the recover criterion
    post = R.build_network(sc, [h.bus for h in hpts], [0.0] * len(hpts), fault=False)
    per = []
    for h, c in zip(hpts, cmds):
        Vp, Vn = info['seq'][str(h.bus)]
        vdc_min, vdc_max = M.vdc_window(C.vdc_eq(c['iq'], c['se_d'], c['se_q'], max(0.05, Vp)), dur)
        v_load = lv_compensated(Vp, c['se_d'])
        v_post = post['seq'][str(h.bus)][0] if post else None
        iq_post = abs(iq_ref_gbt(v_post)) if v_post is not None else None
        crit = M.device_criteria(Vp=Vp, Vn=Vn, iq=c['iq'], se_d=c['se_d'], se_q=c['se_q'],
                                 iq_ref=c['iq_ref'], vdc_min=vdc_min, vdc_max=vdc_max,
                                 v_load=v_load, gate=c['gate'], dur=dur, v_post=v_post, iq_post=iq_post)
        rec = dict(hpt_bus=h.bus, Vp=Vp, Vn=Vn, gate=c['gate'], iq=c['iq'], iq_ref=c['iq_ref'],
                   se_d=c['se_d'], se_q=c['se_q'], vdc_min=vdc_min, vdc_max=vdc_max, v_load=v_load,
                   kvar=h.kvar, **crit)
        per.append(rec)
    sysm = M.system_metrics(per, info)
    return per, sysm, info


def run(mode='full'):
    scen = SCN.gen_scenarios() if mode == 'full' else SCN.debug_subset()
    detail_rows, failures, summary = [], [], {}
    for scheme, buses in SCHEMES.items():
        hpts = [HPT(b, use_hysteresis=True) for b in buses]
        sys_rows = []
        for sc in scen:
            per, sysm, info = eval_scenario(sc, hpts)
            sys_rows.append(sysm)
            base = dict(scheme=scheme, scn_id=sc['id'], fault_bus=sc['fault_bus'],
                        fault_type=sc['fault_type'], r_fault=round(sc['r_fault'], 3),
                        load_lvl=sc['load_lvl'], pv_pen=sc['pv_pen'])
            if per is None:
                failures.append({**base, 'failure': 'NONCONVERGED'})
                continue
            for h in per:
                row = {**base, **{k: (round(v, 4) if isinstance(v, float) else v) for k, v in h.items()}}
                detail_rows.append(row)
                if not h['screen_pass'] or (h['Vp'] < 0.9 and h['iq'] < -1e-3):
                    failures.append({**base, **{k: h[k] for k in
                        ('hpt_bus', 'Vp', 'Vn', 'gate', 'iq', 'iq_ref', 'se_d', 'vdc_min',
                         'connect', 'reactive', 'limit', 'recover', 'survive', 'screen_pass')},
                        'failure': ('VDC' if not h['survive'] else 'REACTIVE' if not h['reactive']
                                    else 'CONNECT' if not h['connect'] else 'RECOVER' if not h['recover']
                                    else 'LIMIT')})
            if sysm['oscillation'] or sysm['wrong_sign'] > 0:
                failures.append({**base, 'failure': 'OSC' if sysm['oscillation'] else 'WRONG_SIGN',
                                 'wrong_sign': sysm['wrong_sign']})
        agg = M.aggregate(sys_rows)
        summary[scheme] = agg
        print(f'[{scheme}] conv={agg["convergence_pct"]:.1f}% osc={agg["oscillation_pct"]:.1f}% '
              f'wrong-sign(scn)={agg["wrong_sign_scn_pct"]:.1f}% | FRT={agg["screen_pass_pct"]:.1f}% '
              f'react={agg["reactive_pct"]:.1f}% survive={agg["survive_pct"]:.1f}% '
              f'load≥0.9={agg["load_strict_pct"]:.1f}% load≥0.7={agg["load_tol_pct"]:.1f}% '
              f'minV={agg["minV_mean"]:.3f}')

    # ── representative time-series (deep sym, strong asym, dense coupling) ─────────
    reps = [dict(id=9001, fault_bus=6, fault_type='sym3ph', r_fault=0.3, load_lvl=1.0, pv_pen=0.3),
            dict(id=9002, fault_bus=25, fault_type='1ph_g', r_fault=0.5, load_lvl=1.0, pv_pen=0.6),
            dict(id=9003, fault_bus=30, fault_type='2ph', r_fault=0.5, load_lvl=0.7, pv_pen=0.3)]
    for sc in reps:
        hpts = [HPT(b, use_hysteresis=True) for b in C.PLACE_C]
        sim = R.simulate(sc, hpts, recovery='instant')
        _save_timeseries(f'B_{sc["id"]}_{sc["fault_type"]}_bus{sc["fault_bus"]}', sim)

    _write_csv(C.RESULTS / 'per_scenario_detail.csv', detail_rows)
    _write_csv(C.RESULTS / 'failures_B.csv', failures)
    (C.RESULTS / 'exp_B_summary.csv').write_text(_summary_csv(summary))
    (C.RESULTS / 'exp_B_summary.json').write_text(json.dumps(summary, indent=1))
    print(f'\nsaved per_scenario_detail.csv ({len(detail_rows)} rows), failures_B.csv '
          f'({len(failures)}), exp_B_summary.csv')
    return summary


def _save_timeseries(name, sim):
    for tr in sim['trajectories']:
        if tr is None:
            continue
        path = C.TS_DIR / f'{name}_hpt{tr["bus"]}.csv'
        with open(path, 'w', newline='') as f:
            w = csv.writer(f)
            w.writerow(['t', 'Vp', 'Vn', 'iq', 'iq_ref', 'se_d', 'se_q', 'Vdc', 'v_load', 'gate', 'in_fault'])
            for r in tr['log']:
                w.writerow([round(r['t'], 4), round(r['Vp'], 4), round(r['Vn'], 4), round(r['iq'], 4),
                            round(r['iq_ref'], 4), round(r['se_d'], 4), round(r['se_q'], 4),
                            round(r['Vdc'], 4), round(r['v_load'], 4), r['gate'], r['in_fault']])


def _write_csv(path, rows):
    if not rows:
        path.write_text(''); return
    keys = list({k for r in rows for k in r.keys()})
    order = ['scheme', 'scn_id', 'fault_bus', 'fault_type', 'r_fault', 'load_lvl', 'pv_pen',
             'hpt_bus', 'failure']
    keys = [k for k in order if k in keys] + [k for k in keys if k not in order]
    with open(path, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=keys); w.writeheader()
        for r in rows:
            w.writerow(r)


def _summary_csv(summary):
    keys = list(next(iter(summary.values())).keys())
    lines = ['scheme,' + ','.join(keys)]
    for s, agg in summary.items():
        lines.append(s + ',' + ','.join(f'{agg[k]:.3f}' if isinstance(agg[k], float) else str(agg[k])
                                         for k in keys))
    return '\n'.join(lines) + '\n'


if __name__ == '__main__':
    run('debug' if len(sys.argv) > 1 and sys.argv[1] == 'debug' else 'full')
