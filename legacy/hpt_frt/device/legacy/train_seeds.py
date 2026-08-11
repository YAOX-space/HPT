"""train_seeds.py — overnight robustness batch:
(a) seed robustness: 4 experts x seeds {7, 123} (production seed=42 already exists) -> ODE best per run
(b) single-SAC ablation: ONE SAC on ALL 320 scenarios (faithful ODE), seed 42 -> is the 4-expert split needed?
Saves seed-tagged zips (sd_{seed}_{name}_best.zip / ablation_single_best.zip) — production untouched.
"""
import os
os.environ.setdefault('KMP_DUPLICATE_LIB_OK', 'TRUE')
os.environ.setdefault('MKL_THREADING_LAYER', 'SEQUENTIAL')
import sys, time, json
from pathlib import Path
import numpy as np
from stable_baselines3 import SAC
from stable_baselines3.common.vec_env import DummyVecEnv
from ..frt_env import load_frt_scenarios
from ..frt_metrics import evaluate_frt, fmt_summary
from ..train_common import select_env, run_metadata, assert_fresh_contract

ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT.parents[2] / 'data' / 'models'
SCEN = Path(os.environ.get('HPT_SCENARIO_CSV', ROOT.parents[2] / 'lab' / 'frt_scenarios.csv'))

EXPERTS = {
    'sym':       lambda s: s['category'] == 'LVRT' and s['fault_type'] == 'sym3ph',
    'asym':      lambda s: s['category'] == 'LVRT' and s['fault_type'] in ('1ph_g', '2ph', '2ph_g'),
    'hvrt_sym':  lambda s: s['category'] == 'HVRT' and s['fault_type'] == 'swell_3ph',
    'hvrt_asym': lambda s: s['category'] == 'HVRT' and s['fault_type'] == 'swell_1ph',
}


def train_one(tag, filt, seed, total_steps=300_000, n_envs=8, eval_freq=25_000, env_cls=None,
              legacy=False, run_id=None, split_seed=None):
    import os
    env_cls = env_cls or select_env('frt', legacy=legacy)
    if not legacy:
        assert_fresh_contract(env_cls)
    from ..train_common import (env_seeds, pick_device, split_scenarios, make_run_context,
                               CheckpointSelector, new_run_id, FROZEN_SPLIT_SEED)
    run_id = run_id or os.environ.get('HPT_RUN_ID') or new_run_id()
    split_seed = FROZEN_SPLIT_SEED if split_seed is None else split_seed   # FROZEN across policy seeds
    run_started = time.time()
    scen = [s for s in load_frt_scenarios(SCEN) if filt(s)]
    train_scn, val_scn = split_scenarios(scen, val_frac=0.2, seed=split_seed)   # FROZEN held-out split
    rc = make_run_context(run_id=run_id, policy_seed=seed, env_cls=env_cls,
                          scenario_split=f'per-expert FROZEN held-out family split (val_frac=0.2, split_seed={split_seed})',
                          train_scn=train_scn, val_scn=val_scn, n_envs=n_envs, total_steps=total_steps,
                          source_log=os.environ.get('HPT_RUN_LOG'))
    print(f'\n=== {tag} (seed {seed}): {len(train_scn)} train / {len(val_scn)} val ({env_cls.__name__}) '
          f'run={run_id} ===', flush=True)
    vec = DummyVecEnv([(lambda s=s: env_cls(train_scn, seed=s, train_mode=True))
                       for s in env_seeds(seed, n_envs)])     # deterministic per-env seeds
    sac = SAC('MlpPolicy', vec, learning_rate=3e-4, buffer_size=100_000, batch_size=512,
              tau=0.005, gamma=0.99, train_freq=1, gradient_steps=2, ent_coef='auto',
              policy_kwargs=dict(net_arch=[256, 256, 256]), device=pick_device(), verbose=0, seed=seed)
    sel = CheckpointSelector(MODELS / f'{tag}_best.zip', rc, run_started)   # fail-fast on stale
    t0, step, last_m = time.time(), 0, None
    while step < total_steps:
        chunk = min(eval_freq, total_steps - step)
        sac.learn(total_timesteps=chunk, reset_num_timesteps=False); step += chunk
        m = evaluate_frt(sac, val_scn, env_cls, n_eval=min(80, len(val_scn)))   # HELD-OUT val (#7)
        sel.consider(sac, m['partial_proxy_pct'], step, m)     # first eval ALWAYS saved (incl proxy=0)
        last_m = m
        print(f"  [{tag}] step={step:7,} {fmt_summary(m)} best_proxy={sel.best:.0f}%@{sel.best_step} "
              f"{(time.time()-t0)/60:.0f}min", flush=True)
    sel.save_final(sac, MODELS / f'{tag}_final.zip', step, last_m)   # final + sidecar (always)
    return sel.best


def main():
    import argparse, os
    from ..train_common import PRODUCTION_SEEDS, new_run_id
    ap = argparse.ArgumentParser(); ap.add_argument('--legacy', action='store_true')
    # >=5 seeds for the robustness study (audit fix #6). seed 42 is trained by train_experts; here we
    # cover the rest of PRODUCTION_SEEDS by default so {42}+these reach >=5 distinct seeds.
    ap.add_argument('--seeds', type=int, nargs='+', default=[s for s in PRODUCTION_SEEDS if s != 42])
    a = ap.parse_args()
    run_id = os.environ.get('HPT_RUN_ID') or new_run_id()
    env_cls = select_env('frt', legacy=a.legacy)
    out = (ROOT.parents[2] / 'lab' / 'results') / ('legacy_pre_audit' if a.legacy else '')
    out.mkdir(parents=True, exist_ok=True)
    fn = out / f"seeds_train{'_legacy' if a.legacy else ''}.json"
    all_seeds = sorted(set([42] + list(a.seeds)))
    res = {'_metadata': run_metadata(env_cls, seed=f'multi{all_seeds}',
                                     scenario_split='per-expert held-out family split + single-all-320 ablation',
                                     legacy=a.legacy, seeds=all_seeds, n_seeds=len(all_seeds), run_id=run_id)}
    # (a) seed robustness across the non-42 seeds (42 already done by train_experts)
    for seed in a.seeds:
        for nm, fl in EXPERTS.items():
            res[f'sd{seed}/{nm}'] = train_one(f'sd_{seed}_{nm}', fl, seed, env_cls=env_cls,
                                              legacy=a.legacy, run_id=run_id)
            fn.write_text(json.dumps(res, indent=2))
    # (b) single-SAC ablation on all 320
    res['ablation_single'] = train_one('ablation_single', lambda s: True, 42, env_cls=env_cls,
                                       legacy=a.legacy, run_id=run_id)
    fn.write_text(json.dumps(res, indent=2))
    print('\nSEEDS+ABLATION DONE:', res, flush=True)


if __name__ == '__main__':
    main()
