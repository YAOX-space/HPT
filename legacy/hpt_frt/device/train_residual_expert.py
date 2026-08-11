"""train_residual_expert.py — trains the NEW 4-expert + residual SAC (pure-learning hybrid),
candidate MAIN METHOD. Internal HLC dispatch mi==17 (new; mi==16 is the deployment-projected mode-14).
ONE global residual policy on the online-gated frozen-expert prior (experts from train_experts.py are
FROZEN; only the residual learns).

Why this mode: Mode 5 (4 experts) is LVRT-strong / HVRT-weak; Mode 6 (residual on MPC prior) is
strong but NON-pure (analytic MPC). This stacks the residual on the EXPERT prior instead of MPC, so
it stays PURE LEARNING while gaining the residual's cross-domain correction + reactive-sign cleanup.
See docs/RESIDUAL_EXPERT_PLAN_2026-06-25.md. Canonical naming pending CONTROL_MODES.md update.

Same stability suite as train_residual (LR anneal 3e-4->3e-5 + actor EMA). Saves
data/models/sac_resexpert_best.zip (raw) / sac_resexpert_ema_best.zip.

⚠️ Proxy is NOT a certified pass rate (limit/survive NOT_EVALUATED in the ODE; the ODE is also blind
to the swell_3ph switching DC undershoot). Simulink frt-v2 full-320 (mi==16) is the authority.
"""
import os
os.environ.setdefault('KMP_DUPLICATE_LIB_OK', 'TRUE')
os.environ.setdefault('MKL_THREADING_LAYER', 'SEQUENTIAL')
import time, json, copy
from pathlib import Path
from stable_baselines3 import SAC
from stable_baselines3.common.vec_env import DummyVecEnv
from .frt_env import load_frt_scenarios
from .frt_metrics import evaluate_frt, fmt_summary
from .train_common import select_env, run_metadata, assert_fresh_contract
from .train_residual import EMACallback          # reuse the actor-EMA callback
from .residual_expert_env import load_frozen_experts

ROOT = Path(__file__).resolve().parent
MODELS = ROOT.parents[2] / 'data' / 'models'


def main(total_steps=300_000, n_envs=8, eval_freq=25_000, seed=42, run_id=None, split_seed=None):
    env_cls = select_env('residual_expert')
    assert_fresh_contract(env_cls)                 # must be 20-D/3-D frt-v2
    from .train_common import (env_seeds, pick_device, split_scenarios, make_run_context,
                               CheckpointSelector, new_run_id, FROZEN_SPLIT_SEED)
    run_id = run_id or os.environ.get('HPT_RUN_ID') or new_run_id()
    split_seed = FROZEN_SPLIT_SEED if split_seed is None else split_seed
    run_started = time.time()
    out = ROOT.parents[2] / 'lab' / 'results'; out.mkdir(parents=True, exist_ok=True)
    scen = load_frt_scenarios(ROOT.parents[2] / 'lab' / 'frt_scenarios.csv')
    train_scn, val_scn = split_scenarios(scen, val_frac=0.2, seed=split_seed)   # FROZEN held-out split
    experts = load_frozen_experts(device='cpu')    # load ONCE; shared across all vec-envs (sequential)
    rc = make_run_context(run_id=run_id, policy_seed=seed, env_cls=env_cls,
                          scenario_split=f'all-320 residual-expert FROZEN held-out split '
                                         f'(val_frac=0.2, split_seed={split_seed})',
                          train_scn=train_scn, val_scn=val_scn, n_envs=n_envs, total_steps=total_steps,
                          source_log=os.environ.get('HPT_RUN_LOG'))
    md = run_metadata(env_cls, seed=seed, run_id=run_id,
                      scenario_split=f'held-out family split: {len(train_scn)} train / {len(val_scn)} val (#7)')
    print(f'=== residual-expert SAC: {len(train_scn)} train / {len(val_scn)} val '
          f'({env_cls.__name__}) run={run_id} ===', flush=True)
    vec = DummyVecEnv([(lambda s=s: env_cls(train_scn, seed=s, experts=experts))
                       for s in env_seeds(seed, n_envs)])
    lr = lambda p: 3e-5 + (3e-4 - 3e-5) * p        # linear anneal (p: 1->0)
    sac = SAC('MlpPolicy', vec, learning_rate=lr, buffer_size=100_000, batch_size=512,
              tau=0.005, gamma=0.99, train_freq=1, gradient_steps=2, ent_coef='auto',
              policy_kwargs=dict(net_arch=[256, 256, 256]), device=pick_device(), verbose=0, seed=seed)
    ema = EMACallback()
    sel_raw = CheckpointSelector(MODELS / 'sac_resexpert_best.zip', rc, run_started)
    sel_ema = CheckpointSelector(MODELS / 'sac_resexpert_ema_best.zip', rc, run_started)
    t0, step, last_m, last_me = time.time(), 0, None, None
    while step < total_steps:
        chunk = min(eval_freq, total_steps - step)
        sac.learn(total_timesteps=chunk, reset_num_timesteps=False, callback=ema); step += chunk
        m = evaluate_frt(sac, val_scn, env_cls, n_eval=min(80, len(val_scn)))
        sel_raw.consider(sac, m['partial_proxy_pct'], step, m); last_m = m
        if ema.ema is not None:
            bak = ema.load_into(sac)
            me = evaluate_frt(sac, val_scn, env_cls, n_eval=min(80, len(val_scn)))
            sel_ema.consider(sac, me['partial_proxy_pct'], step, me); last_me = me
            sac.policy.actor.load_state_dict(bak)
        ema_p = (last_me['partial_proxy_pct'] if last_me else float('nan'))
        print(f"  [resexp] step={step:7,} {fmt_summary(m)} EMA_proxy={ema_p:.0f}% "
              f"best_proxy={sel_raw.best:.0f}/{sel_ema.best:.0f}% {(time.time()-t0)/60:.0f}min", flush=True)
    sel_raw.save_final(sac, MODELS / 'sac_resexpert_final.zip', step, last_m)
    if last_me is not None:
        bak = ema.load_into(sac); sel_ema.save_final(sac, MODELS / 'sac_resexpert_ema_final.zip', step, last_me)
        sac.policy.actor.load_state_dict(bak)
    (out / 'residual_expert_train.json').write_text(
        json.dumps({**md, 'best_raw': sel_raw.best, 'best_raw_step': sel_raw.best_step,
                    'best_ema': sel_ema.best, 'best_ema_step': sel_ema.best_step}, indent=2))
    print(f'RESIDUAL-EXPERT DONE raw={sel_raw.best}@{sel_raw.best_step} '
          f'ema={sel_ema.best}@{sel_ema.best_step}', flush=True)


if __name__ == '__main__':
    import argparse
    from .train_common import new_run_id
    ap = argparse.ArgumentParser(); ap.add_argument('--seed', type=int, default=42); a = ap.parse_args()
    main(seed=a.seed, run_id=os.environ.get('HPT_RUN_ID') or new_run_id())
