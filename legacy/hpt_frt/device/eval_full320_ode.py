"""eval_full320_ode.py — full-320 ODE-LAYER frt-v2 PROXY for the deployed residual champion (mi=14:
MPC prior + residual, via HPTFRTResidualEnvV2). The ODE env can evaluate connect/reactive/recover but
NOT limit/survive (no switching-level current/DC) — so partial_proxy_pct is a CHECKPOINT/SELECTION
PROXY, explicitly NOT a certified frt-v2 pass rate. A faithful pass rate needs the switching layer with
per-scenario sag re-calibration (the CSV trans_resistance does not reproduce target_V_pu in Simulink).

    python -m hpt_frt.device.eval_full320_ode
writes lab/results/p3_full320_ode_proxy.json (does NOT overwrite anything)."""
from __future__ import annotations
import argparse
import json, time
from collections import defaultdict
from pathlib import Path
from .model_io import load_sac
from .frt_env import load_frt_scenarios
from .residual_env import HPTFRTResidualEnvV2
from .frt_metrics import evaluate_frt

ROOT = Path(__file__).resolve().parents[3]
MODELS = ROOT / 'data' / 'models'
SCEN = ROOT / 'lab' / 'frt_scenarios.csv'


def _slice(model, scen, env_cls):
    r = evaluate_frt(model, scen, env_cls, n_eval=None)
    return dict(n=len(scen), partial_proxy_pct=r['partial_proxy_pct'], proxy_saturated=r['proxy_saturated'],
                connect=r['connect'], reactive=r['reactive'], recover=r['recover'],
                connect_ne_pct=r['connect_not_eval_pct'], reactive_ne_pct=r['reactive_not_eval_pct'],
                recover_ne_pct=r['recover_not_eval_pct'],
                proxy_criteria_evaluated_mean=r['proxy_criteria_evaluated_mean'])


def main(scen_path=SCEN, out_path=None):
    scen_path = Path(scen_path)
    out_path = Path(out_path) if out_path is not None else ROOT / 'lab' / 'results' / 'p3_full320_ode_proxy.json'
    allscn = load_frt_scenarios(scen_path)
    selection_json = ROOT / 'lab' / 'results' / 'residual_export_selection.json'
    if selection_json.exists():
        pick = json.loads(selection_json.read_text(encoding='utf-8')).get('selected_model')
        res_zip = MODELS / pick
    else:
        train_json = ROOT / 'lab' / 'results' / 'residual_train.json'
        if train_json.exists():
            j = json.loads(train_json.read_text(encoding='utf-8'))
            raw_best = j.get('best_raw', j.get('best', -1))
            ema_best = j.get('best_ema', -1)
            res_zip = MODELS / ('sac_residual_ema_best.zip' if ema_best >= raw_best else 'sac_residual_best.zip')
        else:
            res_zip = MODELS / 'sac_residual_ema_final.zip'
            if not res_zip.exists():
                res_zip = MODELS / 'sac_residual_ema_best.zip'
    model = load_sac(res_zip)

    out = dict(metrics_version='frt-v2', layer='ODE', generated_at=time.strftime('%Y-%m-%dT%H:%M:%S'),
               deployed_model=res_zip.name, deployment_mode='mi=14 residual (MPC prior + residual)',
               scenario_file=str(scen_path), n_scenarios=len(allscn),
               DISCLAIMER=('ODE-LAYER PROXY. partial_proxy_pct counts only EVALUABLE criteria '
                           '(connect/reactive/recover); limit + survive are NOT_EVALUATED in the ODE '
                           '(no switching current / DC bus). This is NOT a certified frt-v2 pass rate. '
                           'A faithful pass rate requires the switching layer; the CSV scenario fault '
                           'params do not reproduce target_V_pu in Simulink (needs per-scenario '
                           're-calibration) — see the 12-case switching gate for validated transfer.'),
               overall={}, by_category={}, by_fault_type={})

    def f(x):  # criterion pass% is None when ALL its scenarios are NOT_EVALUATED (0/0)
        return ' NE ' if x is None else f'{x:3.0f}'

    out['overall'] = _slice(model, allscn, HPTFRTResidualEnvV2)
    v = out['overall']
    print(f"OVERALL  n={v['n']:3d}  proxy={v['partial_proxy_pct']:.1f}%  "
          f"con={f(v['connect'])} rea={f(v['reactive'])} rec={f(v['recover'])} (reactive NE {v['reactive_ne_pct']:.0f}%)")

    cats = defaultdict(list); fts = defaultdict(list)
    for s in allscn:
        cats[s['category']].append(s); fts[s['fault_type']].append(s)
    for k, scen in sorted(cats.items()):
        out['by_category'][k] = _slice(model, scen, HPTFRTResidualEnvV2); v = out['by_category'][k]
        print(f"  cat {k:5s} n={v['n']:3d} proxy={v['partial_proxy_pct']:5.1f}%  con={f(v['connect'])} rea={f(v['reactive'])} rec={f(v['recover'])}  reaNE={v['reactive_ne_pct']:3.0f}%")
    for k, scen in sorted(fts.items()):
        out['by_fault_type'][k] = _slice(model, scen, HPTFRTResidualEnvV2); v = out['by_fault_type'][k]
        print(f"  ft  {k:9s} n={v['n']:3d} proxy={v['partial_proxy_pct']:5.1f}%  con={f(v['connect'])} rea={f(v['reactive'])} rec={f(v['recover'])}  reaNE={v['reactive_ne_pct']:3.0f}%")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2), encoding='utf-8')
    print(f'\nwrote {out_path}')


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--scenarios', type=Path, default=SCEN)
    ap.add_argument('--out', type=Path, default=None)
    a = ap.parse_args()
    main(a.scenarios, a.out)
