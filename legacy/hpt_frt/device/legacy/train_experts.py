"""
train_experts.py — trains the experts for the MAIN METHOD: canonical Mode 5
(online-gated multi-expert SAC). Four specialist SAC policies on disjoint fault sub-categories,
for a hierarchical "classify → specialist" controller; at DEPLOYMENT the gate is the ONLINE
sequence-component classifier on measured (V2p, V2n) (NOT true labels) in the Simulink HLC,
internal dispatch mi==12 (= canonical Mode 5; internal integer kept unchanged for reproducibility):

  sym       : LVRT, fault_type == sym3ph            (symmetric undervoltage)
  asym      : LVRT, fault_type in {1ph_g,2ph,2ph_g} (asymmetric, negative-seq / 2ω)
  hvrt_sym  : HVRT, fault_type == swell_3ph         (symmetric overvoltage → absorb reactive)
  hvrt_asym : HVRT, fault_type == swell_1ph         (asymmetric overvoltage)

Each specialist trains on the SAME faithful ODE env (frt_env.py), only the scenario subset
differs.  Saves data/models/sac_{name}_best.zip; export_experts.py emits the .mat weights that
build_hpt_frt_full.m's HLC loads via coder.load.

Canonical naming per CONTROL_MODES.md. NOTE the residual-SAC (train_residual.py, internal mi==14)
is canonical Mode 6, an EXTENSION (NOT the main method, NOT pure SAC) — it is not the headline.

待验证 (pending re-validation, see CONTROL_MODES.md §5):
  * de-privileged retrain: the deployment gate is online sequence-component, but TRAINING here
    currently fills the fault one-hot from the SCENARIO LABEL (privileged-info residual);
  * 3-D action retrain: frt_env.py action is nominally 4-D but effective 3-D — action dim 0
    (i_sh_d) is a vestigial dim (only enters the limit penalty, discarded at deployment).
"""
import os
os.environ.setdefault('KMP_DUPLICATE_LIB_OK', 'TRUE')        # avoid libiomp double-load hard crash
os.environ.setdefault('MKL_THREADING_LAYER', 'SEQUENTIAL')   # numpy/MKL single-thread (torch stays MT)
import sys, time, json
from pathlib import Path
import numpy as np
from stable_baselines3 import SAC
from stable_baselines3.common.vec_env import DummyVecEnv
from ..frt_env import load_frt_scenarios
from ..frt_metrics import evaluate_frt
from ..train_common import select_env, run_metadata, assert_fresh_contract

ROOT   = Path(__file__).resolve().parents[1]
SCEN   = Path(os.environ.get('HPT_SCENARIO_CSV', ROOT.parents[2] / 'lab' / 'frt_scenarios.csv'))
MODELS = ROOT.parents[2] / 'data' / 'models'; MODELS.mkdir(parents=True, exist_ok=True)

EXPERTS = {
    'sym':       lambda s: s['category']=='LVRT' and s['fault_type']=='sym3ph',
    'asym':      lambda s: s['category']=='LVRT' and s['fault_type'] in ('1ph_g','2ph','2ph_g'),
    'hvrt_sym':  lambda s: s['category']=='HVRT' and s['fault_type']=='swell_3ph',
    'hvrt_asym': lambda s: s['category']=='HVRT' and s['fault_type']=='swell_1ph',
}

def train_one(name, filt, total_steps=300_000, n_envs=8, eval_freq=25_000, env_cls=None, legacy=False,
              seed=42, run_id=None, split_seed=None):
    import math, os
    env_cls = env_cls or select_env('frt', legacy=legacy)
    if not legacy:
        assert_fresh_contract(env_cls)
    from ..train_common import (env_seeds, pick_device, split_scenarios, make_run_context,
                               CheckpointSelector, new_run_id, FROZEN_SPLIT_SEED)
    from ..frt_metrics import fmt_summary
    run_id = run_id or os.environ.get('HPT_RUN_ID') or new_run_id()
    split_seed = FROZEN_SPLIT_SEED if split_seed is None else split_seed   # FROZEN across policy seeds
    run_started = time.time()
    allscn = load_frt_scenarios(SCEN)
    scen = [s for s in allscn if filt(s)]
    train_scn, val_scn = split_scenarios(scen, val_frac=0.2, seed=split_seed)   # FROZEN held-out split
    rc = make_run_context(run_id=run_id, policy_seed=seed, env_cls=env_cls,
                          scenario_split=f'per-expert FROZEN held-out family split (val_frac=0.2, split_seed={split_seed})',
                          train_scn=train_scn, val_scn=val_scn, n_envs=n_envs, total_steps=total_steps,
                          source_log=os.environ.get('HPT_RUN_LOG'))
    print(f'\n=== expert "{name}": {len(train_scn)} train / {len(val_scn)} val ({env_cls.__name__}) '
          f'run={run_id} ===', flush=True)
    vec = DummyVecEnv([(lambda s=s: env_cls(train_scn, seed=s, train_mode=True))
                       for s in env_seeds(seed, n_envs)])     # deterministic per-env seeds
    sac = SAC('MlpPolicy', vec, learning_rate=3e-4, buffer_size=100_000, batch_size=512,
              tau=0.005, gamma=0.99, train_freq=1, gradient_steps=2, ent_coef='auto',
              policy_kwargs=dict(net_arch=[256,256,256]), device=pick_device(), verbose=0, seed=seed)
    sel = CheckpointSelector(MODELS / f'sac_{name}_best.zip', rc, run_started)   # fail-fast on stale
    t0, step, last_m = time.time(), 0, None
    while step < total_steps:
        chunk = min(eval_freq, total_steps-step)
        sac.learn(total_timesteps=chunk, reset_num_timesteps=False); step += chunk
        m = evaluate_frt(sac, val_scn, env_cls, n_eval=min(80, len(val_scn)))   # HELD-OUT val (#7)
        sel.consider(sac, m['partial_proxy_pct'], step, m)     # first eval ALWAYS saved (incl proxy=0)
        last_m = m
        print(f"  [{name}] step={step:7,} {fmt_summary(m)} best_proxy={sel.best:.0f}%@{sel.best_step} "
              f"{(time.time()-t0)/60:.0f}min", flush=True)
    sel.save_final(sac, MODELS / f'sac_{name}_final.zip', step, last_m)   # final + sidecar (always)
    return sel.best

def main():
    import argparse, os
    from ..train_common import new_run_id
    ap = argparse.ArgumentParser(); ap.add_argument('--legacy', action='store_true')
    ap.add_argument('--seed', type=int, default=42); a = ap.parse_args()
    run_id = os.environ.get('HPT_RUN_ID') or new_run_id()
    env_cls = select_env('frt', legacy=a.legacy)
    out = (ROOT.parents[2] / 'lab' / 'results') / ('legacy_pre_audit' if a.legacy else '')
    out.mkdir(parents=True, exist_ok=True)
    md = run_metadata(env_cls, seed=a.seed,
                      scenario_split='per-expert held-out family split (val_frac=0.2)',
                      legacy=a.legacy, run_id=run_id)
    res = {'_metadata': md}
    for nm, fl in EXPERTS.items():
        res[nm] = train_one(nm, fl, total_steps=300_000, env_cls=env_cls, legacy=a.legacy, seed=a.seed,
                            run_id=run_id)
    (out / f"experts_train{'_legacy' if a.legacy else ''}.json").write_text(json.dumps(res, indent=2))
    print('\nALL EXPERTS DONE:', res, flush=True)


if __name__ == '__main__':
    main()
