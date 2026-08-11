"""error_analysis_mi14.py — POST-PROCESSING error analysis of the residual SAC (mi=14) FAILs in the
frt-v2 switching full-320. Reads ONLY existing switching results (no training / no Simulink / no
mutation of result values) and automatically replays each switching FAIL in the matching ODE policy
to classify ODE-visible vs ODE-blind failure modes:
    lab/results/p3_full320_sw_mi14.mat  (SAC)   lab/results/p3_full320_sw_mi7.mat  (dq baseline)
Per FAIL scenario it extracts the failed criteria + reason + worst/t_worst, whether a NOT_EVALUATED
criterion co-exists, and whether the matching dq scenario also failed. Writes CSV + summary JSON + 4
breakdown figures.

NOTE: NE is never counted as PASS; no-fail/effective is NOT a strict grid-code pass rate.
NOTE: ODE visibility is a diagnostic routing label, NOT certification. For switching `survive` FAILs,
the ODE uses `vdc_survive_proxy` because full ODE `survive` is intentionally NOT_EVALUATED without I2.

    python -m hpt_frt.device.error_analysis_mi14
"""
from __future__ import annotations
import json
import csv
import time
from collections import Counter, defaultdict
from pathlib import Path
import scipy.io as sio
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from .frt_env import load_frt_scenarios
from .frt_metrics import evaluate_scenario
from .model_io import load_sac
from .residual_env import HPTFRTResidualEnvV2
from hpt_frt.common import frt_v2 as FV2

ROOT = Path(__file__).resolve().parents[3]
RES = ROOT / 'lab' / 'results'
FIG = RES / 'figures'
MODELS = ROOT / 'data' / 'models'
SCEN = ROOT / 'lab' / 'frt_scenarios.csv'
CRITERIA = ['connect', 'reactive', 'limit', 'recover', 'survive']
TRACE_COLS = ['sid', 't', 'V2p', 'V2n', 'Vdc', 'iq', 'iq_cmd', 'iq_ref', 'mse_d', 'mse_q',
              'Vdc_eq', 'Vg_p', 'Vg_n', 'tripped']


def load(mi):
    R = sio.loadmat(RES / f'p3_full320_sw_mi{mi}.mat', simplify_cells=True)['R']
    R = [R] if isinstance(R, dict) else list(R)
    out = {}
    for r in R:
        p = r['prov']
        ft = p['fault_type']
        out[int(r['sid'])] = dict(sid=int(r['sid']), frt=str(r['frt']), ft=ft,
                                  cat='HVRT' if str(ft).startswith('swell') else 'LVRT',
                                  scr=int(p['scr']), Vg_p=float(p['Vg_p']),
                                  target_V_pu=float(p['target_V_pu']), crit=r['crit'])
    return out


def certified_counts(rows):
    vals = [str(v['frt']) for v in rows.values()]
    n = len(vals)
    n_true = vals.count('True')
    n_false = vals.count('False')
    n_none = vals.count('None')
    det = n_true + n_false
    return dict(strict_pass_pct=round(100.0 * n_true / n, 1) if n else None,
                no_fail_effective_pct=round(100.0 * (n_true + n_none) / n, 1) if n else None,
                fail_pct=round(100.0 * n_false / n, 1) if n else None,
                pass_determinable_pct=round(100.0 * n_true / det, 1) if det else None,
                true=n_true, false=n_false, none=n_none)


def fail_record(rec, dq):
    """Build the per-FAIL row: failed criteria, reasons, worst/t, NE present, dq-also-fail."""
    cr = rec['crit']
    failed = [k for k in CRITERIA if str(cr[k]['status']) == 'FAIL']
    ne = [k for k in CRITERIA if str(cr[k]['status']) == 'NOT_EVALUATED']
    reasons = {k: str(cr[k]['reason']) for k in failed}
    worst = {k: (None if not _finite(cr[k]['worst']) else float(cr[k]['worst'])) for k in failed}
    t_worst = {k: float(cr[k]['t_worst']) for k in failed}
    dq_rec = dq.get(rec['sid'])
    return dict(
        sid=rec['sid'], fault_type=rec['ft'], category=rec['cat'], scr=rec['scr'],
        target_V_pu=rec['target_V_pu'], Vg_p=rec['Vg_p'],
        failed_criteria='+'.join(failed), n_failed=len(failed),
        connect=_st(cr, 'connect'), reactive=_st(cr, 'reactive'), limit=_st(cr, 'limit'),
        recover=_st(cr, 'recover'), survive=_st(cr, 'survive'),
        primary_reason=' | '.join(f'{k}:{reasons[k][:70]}' for k in failed),
        worst=' | '.join(f'{k}={worst[k]}' for k in failed if worst[k] is not None),
        t_worst=' | '.join(f'{k}@{t_worst[k]:.3f}' for k in failed),
        has_not_evaluated=bool(ne), not_evaluated='+'.join(ne),
        dq_frt=(dq_rec['frt'] if dq_rec else 'NA'),
        dq_also_fail=(dq_rec is not None and dq_rec['frt'] == 'False'))


def _finite(x):
    try:
        return x == x and abs(float(x)) != float('inf')
    except Exception:
        return False


def _st(cr, k):
    return str(cr[k]['status'])


def residual_model_path():
    """Return the mi=14 residual checkpoint selected for deployment by frozen-val proxy."""
    selection_json = RES / 'residual_export_selection.json'
    if selection_json.exists():
        pick = json.loads(selection_json.read_text(encoding='utf-8')).get('selected_model')
        if pick and (MODELS / pick).exists():
            return MODELS / pick
    train_json = RES / 'residual_train.json'
    if train_json.exists():
        j = json.loads(train_json.read_text(encoding='utf-8'))
        raw_best = j.get('best_raw', j.get('best', -1))
        ema_best = j.get('best_ema', -1)
        pick = 'sac_residual_ema_best.zip' if ema_best >= raw_best else 'sac_residual_best.zip'
        p = MODELS / pick
        if p.exists():
            return p
    final = MODELS / 'sac_residual_ema_final.zip'
    return final if final.exists() else MODELS / 'sac_residual_ema_best.zip'


def classify_ode_visibility(fails):
    """Replay each switching FAIL in the ODE and decide whether the ODE sees the same failed criterion.

    Visibility rule:
      * ordinary criteria: ODE criterion status is FAIL;
      * switching survive: ODE `vdc_survive_proxy` is FAIL, since full ODE survive needs I2 and stays NE.
    Returns (per_sid, summary). Unknown means the ODE rollout/evaluator itself could not produce a
    diagnostic result, not that the failure is blind.
    """
    scenarios = load_frt_scenarios(SCEN)
    by_sid = {int(s['scenario_id']): s for s in scenarios}
    model_path = residual_model_path()
    model = load_sac(model_path)
    out = {}
    counts = Counter()
    by_criterion = defaultdict(Counter)
    for r in fails:
        sid = int(r['sid'])
        failed = [k for k in r['failed_criteria'].split('+') if k]
        scenario = by_sid.get(sid)
        if scenario is None:
            label = dict(ode_visibility='UNKNOWN', ode_visible=False, ode_blind=False,
                         ode_matched_criteria='', ode_failed_criteria='',
                         ode_reason='scenario_id missing from lab/frt_scenarios.csv')
            out[sid] = label; counts['UNKNOWN'] += 1
            continue
        cls = evaluate_scenario(model, HPTFRTResidualEnvV2, scenario)
        if cls['kind'] != 'evaluated':
            label = dict(ode_visibility='UNKNOWN', ode_visible=False, ode_blind=False,
                         ode_matched_criteria='', ode_failed_criteria='',
                         ode_reason=f"{cls['kind']}: {cls.get('error', '')}")
            out[sid] = label; counts['UNKNOWN'] += 1
            continue
        res = cls['res']
        ode_failed = [k for k in CRITERIA if res[k]['status'] == FV2.FAIL]
        matched = []
        for k in failed:
            if k == 'survive':
                if res.get('vdc_survive_proxy') == FV2.FAIL:
                    matched.append(k)
            elif res[k]['status'] == FV2.FAIL:
                matched.append(k)
        visible = bool(matched)
        status = 'VISIBLE' if visible else 'BLIND'
        label = dict(ode_visibility=status, ode_visible=visible, ode_blind=not visible,
                     ode_matched_criteria='+'.join(matched),
                     ode_failed_criteria='+'.join(ode_failed),
                     ode_vdc_survive_proxy=str(res.get('vdc_survive_proxy', 'NA')),
                     ode_vdc_min=res.get('vdc_min', ''),
                     ode_reason='matched switching failed criterion' if visible
                                else 'ODE did not reproduce switching failed criterion')
        out[sid] = label
        counts[status] += 1
        for k in failed:
            by_criterion[k][status] += 1
    summary = dict(enabled=True, model=model_path.name,
                   rule='VISIBLE iff ODE reproduces a switching-failed criterion; survive uses vdc_survive_proxy',
                   counts=dict(counts),
                   by_switching_failed_criterion={k: dict(v) for k, v in by_criterion.items()})
    return out, summary


def export_ode_replay_traces(fails, path):
    """Write per-step ODE replay traces for the switching FAIL set."""
    scenarios = load_frt_scenarios(SCEN)
    by_sid = {int(s['scenario_id']): s for s in scenarios}
    model = load_sac(residual_model_path())
    with path.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=TRACE_COLS)
        w.writeheader()
        for r in fails:
            sid = int(r['sid'])
            scenario = by_sid.get(sid)
            if scenario is None:
                continue
            env = HPTFRTResidualEnvV2([scenario], seed=42, train_mode=False)
            obs, _ = env.reset()
            done = False
            while not done:
                action, _ = model.predict(obs, deterministic=True)
                obs, _reward, term, trunc, info = env.step(action)
                row = {'sid': sid}
                for k in TRACE_COLS[1:]:
                    row[k] = info.get(k, '')
                w.writerow(row)
                done = term or trunc


def main():
    sac, dq = load(14), load(7)
    fails = [fail_record(sac[s], dq) for s in sorted(sac) if sac[s]['frt'] == 'False']
    assert len(fails) == sum(1 for s in sac if sac[s]['frt'] == 'False')
    ode_labels, ode_summary = classify_ode_visibility(fails)
    for r in fails:
        r.update(ode_labels[int(r['sid'])])

    # ---- CSV (per-scenario) ----
    FIG.mkdir(parents=True, exist_ok=True)
    csv_path = RES / 'error_analysis_mi14_failures.csv'
    cols = ['sid', 'fault_type', 'category', 'scr', 'target_V_pu', 'Vg_p', 'failed_criteria',
            'n_failed', 'connect', 'reactive', 'limit', 'recover', 'survive', 'primary_reason',
            'worst', 't_worst', 'has_not_evaluated', 'not_evaluated', 'dq_frt', 'dq_also_fail',
            'ode_visibility', 'ode_visible', 'ode_blind', 'ode_matched_criteria',
            'ode_failed_criteria', 'ode_vdc_survive_proxy', 'ode_vdc_min', 'ode_reason']
    with csv_path.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in fails:
            w.writerow(r)

    # ---- aggregate stats ----
    by_crit = Counter()             # each failed criterion occurrence (a scenario may fail 2)
    for r in fails:
        for k in r['failed_criteria'].split('+'):
            by_crit[k] += 1
    multi = [r['sid'] for r in fails if r['n_failed'] >= 2]
    fail_plus_ne = [r['sid'] for r in fails if r['has_not_evaluated']]
    by_ft = Counter(r['fault_type'] for r in fails)
    by_scr = Counter(r['scr'] for r in fails)
    by_cat = Counter(r['category'] for r in fails)
    by_depth = Counter(round(r['Vg_p'], 3) for r in fails)
    dq_also = [r['sid'] for r in fails if r['dq_also_fail']]
    sac_only = [r['sid'] for r in fails if not r['dq_also_fail']]
    # criterion x (cat,scr) cross-tab
    cross = defaultdict(Counter)
    for r in fails:
        for k in r['failed_criteria'].split('+'):
            cross[k][f"{r['category']}/scr{r['scr']}"] += 1

    summary = dict(
        analysis='post-processing of existing MAT/JSON only — NO training / Simulink / re-run',
        metrics_version='frt-v2', layer='switching',
        generated_at=time.strftime('%Y-%m-%dT%H:%M:%S'),
        certified_full320=dict(
            residual_SAC_mi14=certified_counts(sac),
            dq_mi7=certified_counts(dq)),
        note=('strict_pass=all 5 criteria evaluated AND PASS; NOT_EVALUATED never counted as PASS; '
              'no-fail/effective is NOT a strict grid-code pass rate.'),
        n_sac_fail=len(fails),
        fail_by_criterion=dict(by_crit),
        multi_criterion_fail=dict(count=len(multi), sids=multi),
        fail_plus_not_evaluated=dict(count=len(fail_plus_ne), sids=fail_plus_ne),
        fail_by_fault_type=dict(by_ft), fail_by_scr={str(k): v for k, v in by_scr.items()},
        fail_by_category=dict(by_cat), fail_by_Vg_p={str(k): v for k, v in sorted(by_depth.items())},
        criterion_by_cat_scr={k: dict(v) for k, v in cross.items()},
        ode_visibility=ode_summary,
        dq_also_fail=dict(count=len(dq_also), sids=dq_also),
        sac_only_fail=dict(count=len(sac_only), sids=sac_only))
    json_path = RES / 'error_analysis_mi14_summary.json'
    json_path.write_text(json.dumps(summary, indent=1), encoding='utf-8')
    trace_path = RES / 'error_analysis_mi14_ode_replay_traces.csv'
    export_ode_replay_traces(fails, trace_path)

    # ---- figures ----
    _bar(by_crit, 'SAC mi=14 FAILs by criterion (occurrences; a scenario may fail >1)',
         'failed criterion', FIG / 'error_fail_by_criterion.png',
         order=CRITERIA)
    _bar(by_ft, 'SAC mi=14 FAILs by fault_type', 'fault_type', FIG / 'error_fail_by_fault_type.png')
    _bar({f'scr {k}': v for k, v in sorted(by_scr.items())}, 'SAC mi=14 FAILs by SCR (3=weak / 10=strong)',
         'grid SCR', FIG / 'error_fail_by_scr.png')
    _bar(by_cat, 'SAC mi=14 FAILs by ride-through type', 'category', FIG / 'error_fail_by_lvrt_hvrt.png')

    # console summary
    print(f'SAC mi=14 FAILs: {len(fails)}/320')
    print(f'  by criterion: {dict(by_crit)}')
    print(f'  multi-criterion: {len(multi)} {multi}')
    print(f'  FAIL+NE mixed: {len(fail_plus_ne)} {fail_plus_ne}')
    print(f'  by fault_type: {dict(by_ft)}')
    print(f'  by scr: {dict(by_scr)}  by cat: {dict(by_cat)}')
    print(f'  ODE visibility: {ode_summary["counts"]}')
    print(f'  dq-also-fail: {len(dq_also)}  SAC-only: {len(sac_only)} {sac_only}')
    print(f'wrote {csv_path}\nwrote {json_path}\nwrote {trace_path}\nwrote 4 figures in {FIG}')


def _bar(counter, title, xlabel, path, order=None):
    keys = order if order else list(counter.keys())
    keys = [k for k in keys if k in counter] if order else keys
    vals = [counter[k] for k in keys]
    fig, ax = plt.subplots(figsize=(8, 5))
    bars = ax.bar([str(k) for k in keys], vals, color='tab:red', alpha=0.8)
    ax.bar_label(bars)
    ax.set_title(title + '\n(ODE selection proxy NOT involved — switching-level certified frt-v2 FAILs)',
                 fontsize=10)
    ax.set_xlabel(xlabel); ax.set_ylabel('# FAIL scenarios')
    ax.grid(True, axis='y', alpha=0.3)
    fig.tight_layout(); fig.savefig(path, dpi=140); plt.close(fig)


if __name__ == '__main__':
    main()
