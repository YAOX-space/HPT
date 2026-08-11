"""train_residual.py — trains canonical Mode 6 (MPC-assisted residual SAC): Residual-SAC on the
MPC prior, ONE policy for ALL 320 scenarios. Internal HLC dispatch mi==14 (integer unchanged for
reproducibility).

Mode 6 is an EXTENSION (performance variant), NOT the main method and NOT "pure SAC": its action
is the analytic MPC prior + a learned bounded residual. The MAIN METHOD is canonical Mode 5
(online-gated multi-expert SAC, train_experts.py, internal mi==12). Canonical naming per
CONTROL_MODES.md.

Stability suite (lit-grounded): linear LR annealing 3e-4→3e-5 + actor-weight EMA (deploy the
averaged actor; evaluated alongside the raw actor, best of both checkpointed).
Saves: data/models/sac_residual_best.zip (raw) / sac_residual_ema_best.zip (EMA snapshot).
"""
import os
os.environ.setdefault('KMP_DUPLICATE_LIB_OK', 'TRUE')
os.environ.setdefault('MKL_THREADING_LAYER', 'SEQUENTIAL')
import sys, time, json, copy
from pathlib import Path
import numpy as np
from stable_baselines3 import SAC
from stable_baselines3.common.vec_env import DummyVecEnv
from stable_baselines3.common.callbacks import BaseCallback
from .frt_env import load_frt_scenarios
from .frt_metrics import evaluate_frt, fmt_summary
from .train_common import select_env, run_metadata, assert_fresh_contract

ROOT = Path(__file__).resolve().parent
MODELS = ROOT.parents[2] / 'data' / 'models'


class EMACallback(BaseCallback):
    """Exponential moving average of actor weights (updated every 250 env steps, beta=0.99)."""
    def __init__(self, every=250, beta=0.99):
        super().__init__(); self.every = every; self.beta = beta; self.ema = None; self.k = 0

    def _on_step(self):
        self.k += 1
        if self.k % self.every == 0:
            sd = self.model.policy.actor.state_dict()
            if self.ema is None:
                self.ema = copy.deepcopy(sd)
            else:
                for key in self.ema:
                    if self.ema[key].dtype.is_floating_point:
                        self.ema[key].mul_(self.beta).add_(sd[key], alpha=1 - self.beta)
        return True

    def load_into(self, model):
        """Swap EMA weights into the actor (returns backup for restoring)."""
        bak = copy.deepcopy(model.policy.actor.state_dict())
        model.policy.actor.load_state_dict(self.ema)
        return bak


def main(total_steps=300_000, n_envs=8, eval_freq=25_000, legacy=False, seed=42, run_id=None, split_seed=None):
    import os
    env_cls = select_env('residual', legacy=legacy)
    if not legacy:
        assert_fresh_contract(env_cls)
    from .train_common import (env_seeds, pick_device, split_scenarios, make_run_context,
                               CheckpointSelector, new_run_id, FROZEN_SPLIT_SEED)
    run_id = run_id or os.environ.get('HPT_RUN_ID') or new_run_id()
    split_seed = FROZEN_SPLIT_SEED if split_seed is None else split_seed   # FROZEN across policy seeds
    run_started = time.time()
    out = (ROOT.parents[2] / 'lab' / 'results') / ('legacy_pre_audit' if legacy else '')
    out.mkdir(parents=True, exist_ok=True)
    scen_path = Path(os.environ.get('HPT_SCENARIO_CSV', ROOT.parents[2] / 'lab' / 'frt_scenarios.csv'))
    scen_label = scen_path.stem
    scen = load_frt_scenarios(scen_path)
    train_scn, val_scn = split_scenarios(scen, val_frac=0.2, seed=split_seed)   # FROZEN held-out split
    rc = make_run_context(run_id=run_id, policy_seed=seed, env_cls=env_cls,
                          scenario_split=(f'{scen_label} residual FROZEN held-out split '
                                          f'(val_frac=0.2, split_seed={split_seed})'),
                          train_scn=train_scn, val_scn=val_scn, n_envs=n_envs, total_steps=total_steps,
                          source_log=os.environ.get('HPT_RUN_LOG'))
    md = run_metadata(env_cls, seed=seed, legacy=legacy, run_id=run_id,
                      scenario_split=(f'{scen_label} held-out family split: '
                                      f'{len(train_scn)} train / {len(val_scn)} val (#7)'),
                      scenario_file=str(scen_path))
    print(f'=== residual-SAC: {len(train_scn)} train / {len(val_scn)} val ({env_cls.__name__}) run={run_id} ===', flush=True)
    vec = DummyVecEnv([(lambda s=s: env_cls(train_scn, seed=s))
                       for s in env_seeds(seed, n_envs)])     # deterministic per-env seeds (#6)
    lr = lambda p: 3e-5 + (3e-4 - 3e-5) * p          # linear anneal (p: 1→0)
    sac = SAC('MlpPolicy', vec, learning_rate=lr, buffer_size=100_000, batch_size=512,
              tau=0.005, gamma=0.99, train_freq=1, gradient_steps=2, ent_coef='auto',
              policy_kwargs=dict(net_arch=[256, 256, 256]), device=pick_device(), verbose=0, seed=seed)
    ema = EMACallback()
    sel_raw = CheckpointSelector(MODELS / 'sac_residual_best.zip', rc, run_started)
    sel_ema = CheckpointSelector(MODELS / 'sac_residual_ema_best.zip', rc, run_started)
    t0, step, last_m, last_me = time.time(), 0, None, None
    while step < total_steps:
        chunk = min(eval_freq, total_steps - step)
        sac.learn(total_timesteps=chunk, reset_num_timesteps=False, callback=ema)
        step += chunk
        m = evaluate_frt(sac, val_scn, env_cls, n_eval=min(80, len(val_scn)))
        sel_raw.consider(sac, m['partial_proxy_pct'], step, m)      # raw: first eval always saved
        last_m = m
        if ema.ema is not None:
            bak = ema.load_into(sac)
            me = evaluate_frt(sac, val_scn, env_cls, n_eval=min(80, len(val_scn)))
            sel_ema.consider(sac, me['partial_proxy_pct'], step, me)
            last_me = me
            sac.policy.actor.load_state_dict(bak)
        ema_p = (last_me['partial_proxy_pct'] if last_me else float('nan'))
        print(f"  [res] step={step:7,} {fmt_summary(m)} EMA_proxy={ema_p:.0f}% "
              f"best_proxy={sel_raw.best:.0f}/{sel_ema.best:.0f}% {(time.time()-t0)/60:.0f}min", flush=True)
    sel_raw.save_final(sac, MODELS / 'sac_residual_final.zip', step, last_m)
    if last_me is not None:
        bak = ema.load_into(sac); sel_ema.save_final(sac, MODELS / 'sac_residual_ema_final.zip', step, last_me)
        sac.policy.actor.load_state_dict(bak)
    (out / f"residual_train{'_legacy' if legacy else ''}.json").write_text(
        json.dumps({**md, 'best_raw': sel_raw.best, 'best_raw_step': sel_raw.best_step,
                    'best_ema': sel_ema.best, 'best_ema_step': sel_ema.best_step}, indent=2))
    print(f'RESIDUAL DONE raw={sel_raw.best}@{sel_raw.best_step} ema={sel_ema.best}@{sel_ema.best_step}', flush=True)


if __name__ == '__main__':
    import argparse, os
    from .train_common import new_run_id
    ap = argparse.ArgumentParser(); ap.add_argument('--legacy', action='store_true')
    ap.add_argument('--seed', type=int, default=42); a = ap.parse_args()
    main(legacy=a.legacy, seed=a.seed, run_id=os.environ.get('HPT_RUN_ID') or new_run_id())
