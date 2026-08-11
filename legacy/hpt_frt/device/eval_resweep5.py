"""eval_resweep5.py — audit round-5 B: re-evaluate the 5-seed FINAL models on the FROZEN held-out
family split and write a versioned summary (mean / sample-std ddof=1 / median / min / max), with the
reactive NOT_EVALUATED detail surfaced (HVRT's 100% must not hide reactive=NOT_EVALUATED). Single-SAC
and residual (seed 42 only) are reported SEPARATELY — never inside the 5-seed mean.

    python -m hpt_frt.device.eval_resweep5
writes lab/results/p3_resweep5_summary_v2.json (does NOT overwrite raw logs)."""
from __future__ import annotations
import json, time
from pathlib import Path
import numpy as np
from .model_io import load_sac
from .frt_env import load_frt_scenarios
from .frt_env_v2 import HPTFRTEnvV2
from .frt_metrics import evaluate_frt, evaluate_scenario
from .train_common import split_scenarios, FROZEN_SPLIT_SEED, env_contract
from ..common import frt_v2 as FV2

ROOT = Path(__file__).resolve().parents[3]   # repo root (src/hpt_frt/device/.. -> repo)
MODELS = ROOT / 'data' / 'models'
SCEN = ROOT / 'lab' / 'frt_scenarios.csv'
SEEDS = [42, 7, 123, 2024, 31]
EXPERTS = {'sym': lambda s: s['category'] == 'LVRT' and s['fault_type'] == 'sym3ph',
           'asym': lambda s: s['category'] == 'LVRT' and s['fault_type'] in ('1ph_g', '2ph', '2ph_g'),
           'hvrt_sym': lambda s: s['category'] == 'HVRT' and s['fault_type'] == 'swell_3ph',
           'hvrt_asym': lambda s: s['category'] == 'HVRT' and s['fault_type'] == 'swell_1ph'}


def _model_path(expert, seed):
    return MODELS / (f'sac_{expert}_final.zip' if seed == 42 else f'sd_{seed}_{expert}_final.zip')


def _reactive_detail(model, val):
    """Per-scenario reactive demand breakdown so a 100% proxy with reactive=NOT_EVALUATED is visible."""
    n_dem = n_ne = 0
    for sc in val:
        c = evaluate_scenario(model, HPTFRTEnvV2, sc)
        if c['kind'] != 'evaluated':
            continue
        st = c['res']['reactive']['status']
        if st == FV2.NOT_EVALUATED:
            n_ne += 1
        else:
            n_dem += 1
    return n_dem, n_ne


def eval_one(expert, seed, val):
    p = _model_path(expert, seed)
    if not p.exists():
        return None
    m = load_sac(p)
    res = evaluate_frt(m, val, HPTFRTEnvV2, n_eval=None)
    n_dem, n_ne = _reactive_detail(m, val)
    return dict(seed=seed, model=p.name, partial_proxy_pct=res['partial_proxy_pct'],
                proxy_saturated=res['proxy_saturated'],
                proxy_criteria_evaluated_mean=res['proxy_criteria_evaluated_mean'],
                connect=res['connect'], reactive=res['reactive'], recover=res['recover'],
                connect_not_eval_pct=res['connect_not_eval_pct'],
                reactive_not_eval_pct=res['reactive_not_eval_pct'],
                recover_not_eval_pct=res['recover_not_eval_pct'],
                n_complete=res['n_complete'], n_incomplete=res['n_incomplete'],
                n_reactive_demanded=n_dem, n_reactive_not_evaluated=n_ne,
                frt_pass_pct=res['frt_pass_pct'])


def agg(vals):
    a = np.array([v for v in vals if v is not None], float)
    if a.size == 0:
        return None
    return dict(mean=round(float(a.mean()), 2),
                sample_std=round(float(a.std(ddof=1)), 2) if a.size > 1 else 0.0,
                median=round(float(np.median(a)), 2), min=float(a.min()), max=float(a.max()), n=int(a.size))


def main():
    allscn = load_frt_scenarios(SCEN)
    contract, obs_dim, act_dim = env_contract(HPTFRTEnvV2)
    summary = dict(metrics_version='frt-v2', generated_at=time.strftime('%Y-%m-%dT%H:%M:%S'),
                   env_contract=contract, observation_dim=obs_dim, action_dim=act_dim,
                   frozen_split_seed=FROZEN_SPLIT_SEED, seeds=SEEDS,
                   note=('partial_proxy_pct is an ODE SELECTION PROXY, NOT an FRT pass rate; '
                         'limit/survive are NOT_EVALUATED in the ODE so saturated proxies are flagged. '
                         'FROZEN split: the spread across seeds isolates the policy-seed effect; the '
                         'absolute level is conditional on the single held-out family set.'),
                   experts={}, single_sac_seed42_only={}, residual_seed42_only={})

    for expert, filt in EXPERTS.items():
        scen = [s for s in allscn if filt(s)]
        _, val = split_scenarios(scen, val_frac=0.2, seed=FROZEN_SPLIT_SEED)
        per_seed = [eval_one(expert, s, val) for s in SEEDS]
        per_seed = [x for x in per_seed if x is not None]
        proxies = [x['partial_proxy_pct'] for x in per_seed]
        summary['experts'][expert] = dict(
            n_val=len(val), val_family_ids=sorted({s.get('family_id') for s in val}),
            per_seed=per_seed, proxy_stats=agg(proxies),
            all_proxy_saturated=all(x['proxy_saturated'] for x in per_seed),
            reactive_demanded_per_seed=[x['n_reactive_demanded'] for x in per_seed])
        st = summary['experts'][expert]['proxy_stats']
        print(f'{expert:10s} proxy {proxies}  mean={st["mean"]}±{st["sample_std"]} '
              f'median={st["median"]} [{st["min"]},{st["max"]}]  saturated={summary["experts"][expert]["all_proxy_saturated"]}')

    # single-SAC (ablation) + residual: seed 42 only -> reported SEPARATELY (not in any 5-seed mean)
    _, val_all = split_scenarios(allscn, val_frac=0.2, seed=FROZEN_SPLIT_SEED)
    for key, fn in (('single_sac_seed42_only', 'ablation_single_final.zip'),
                    ('residual_seed42_only', 'sac_residual_ema_final.zip')):
        p = MODELS / fn
        if p.exists():
            m = load_sac(p); res = evaluate_frt(m, val_all, HPTFRTEnvV2, n_eval=None)
            summary[key] = dict(model=fn, seed=42, partial_proxy_pct=res['partial_proxy_pct'],
                                proxy_saturated=res['proxy_saturated'], n_val=len(val_all),
                                note='seed 42 only — NOT part of the 5-seed expert statistics')
            print(f'{key}: proxy={res["partial_proxy_pct"]} saturated={res["proxy_saturated"]}')

    out = ROOT / 'lab' / 'results' / 'p3_resweep5_summary_v2.json'
    out.write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(f'\nwrote {out}')


if __name__ == '__main__':
    main()
