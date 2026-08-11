"""train_frt_sac.py — train SAC on the standard-FRT env.

frt-v2 (audit round-4 C): defaults to the frt-v2 V2 env (20-D de-privileged obs / 3-D action /
versioned envelope). `--legacy` uses the audited 21-D/4-D env and writes into the legacy namespace.
Every result JSON carries the run-metadata contract block. This entrypoint does NOT warm-start from a
21-D/4-D checkpoint. Running it to completion is the P3 retrain (NOT done here).
"""
import argparse, time, json, os
from pathlib import Path
import numpy as np
from stable_baselines3 import SAC
from stable_baselines3.common.vec_env import DummyVecEnv
from ..frt_env import load_frt_scenarios
from ..frt_metrics import evaluate_frt, fmt_summary
from ..train_common import select_env, run_metadata, assert_fresh_contract

ROOT   = Path(__file__).resolve().parents[1]
SCEN   = Path(os.environ.get('HPT_SCENARIO_CSV', ROOT.parents[2] / 'lab' / 'frt_scenarios.csv'))
OUT    = ROOT.parents[2] / 'lab' / 'results'; OUT.mkdir(exist_ok=True)
MODELS = ROOT.parents[2] / 'data' / 'models'; MODELS.mkdir(parents=True, exist_ok=True)


def train(total_steps=400_000, n_envs=8, eval_freq=25_000, legacy=False, seed=42):
    env_cls = select_env('frt', legacy=legacy)
    if not legacy:
        assert_fresh_contract(env_cls)
    out_dir = (OUT / 'legacy_pre_audit') if legacy else OUT
    out_dir.mkdir(parents=True, exist_ok=True)
    tag = 'legacy_' if legacy else ''
    scen = load_frt_scenarios(SCEN)
    md = run_metadata(env_cls, seed=seed, scenario_split='all-320 (no split yet; P5)', legacy=legacy)
    print('run metadata:', md)
    from ..train_common import env_seeds, pick_device
    vec = DummyVecEnv([(lambda s=s: env_cls(load_frt_scenarios(SCEN), seed=s, train_mode=True))
                       for s in env_seeds(seed, n_envs)])     # deterministic per-env seeds (#6)
    dev = pick_device()
    sac = SAC('MlpPolicy', vec, learning_rate=3e-4, buffer_size=100_000, batch_size=512,
              tau=0.005, gamma=0.99, train_freq=1, gradient_steps=2, ent_coef='auto',
              policy_kwargs=dict(net_arch=[256, 256, 256]), device=dev, verbose=0, seed=seed)
    best, t0, step = 0.0, time.time(), 0
    while step < total_steps:
        chunk = min(eval_freq, total_steps - step)
        sac.learn(total_timesteps=chunk, reset_num_timesteps=False); step += chunk
        m = evaluate_frt(sac, scen, env_cls, n_eval=80)
        if m['partial_proxy_pct'] > best:   # ODE selection proxy (NOT certified FRT)
            best = m['partial_proxy_pct']; sac.save(str(MODELS / f'sac_frt_{tag}best.zip'))
        print(f"  step={step:7,}  {fmt_summary(m)}  best_proxy={best:.0f}%  {(time.time()-t0)/60:.0f}min")
    sac.save(str(MODELS / f'sac_frt_{tag}final.zip'))
    final = evaluate_frt(sac, scen, env_cls)
    final = {**md, **final}
    (out_dir / f'frt_train_{tag}result.json').write_text(json.dumps(final, indent=2), encoding='utf-8')
    print('FINAL:', final)
    return final


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--legacy', action='store_true', help='use the audited legacy 21-D/4-D env')
    ap.add_argument('--steps', type=int, default=400_000)
    ap.add_argument('--seed', type=int, default=42)
    a = ap.parse_args()
    train(total_steps=a.steps, legacy=a.legacy, seed=a.seed)


if __name__ == '__main__':
    main()
