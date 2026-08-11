"""train_ab.py — SAC-variant A/B on the two improvable experts (sym, hvrt_sym).

Variants (same env, same reward, same net 256^3, same gs=2 as production for fairness):
  sac_reset : SAC + periodic full-network resets @100k/200k (primacy-bias fix, Nikishin'22)
  tqc_reset : TQC (truncated quantile critics, sb3-contrib) + same resets

Experts: sym (LVRT sym3ph; prod Simulink 81.7%), hvrt_sym (swell_3ph; absorb-depth weakness).
Saves data/models/ab_{variant}_{expert}_best.zip. Winner selection happens in Simulink, not ODE
(ODE bests are saturated ~100; ODE eval here is only a sanity/selection proxy).
"""
import os
os.environ.setdefault('KMP_DUPLICATE_LIB_OK', 'TRUE')
os.environ.setdefault('MKL_THREADING_LAYER', 'SEQUENTIAL')
import sys, time, json
from collections import defaultdict
from pathlib import Path
import numpy as np
from torch import nn
from stable_baselines3 import SAC
from stable_baselines3.common.vec_env import DummyVecEnv
from stable_baselines3.common.callbacks import BaseCallback
from ..frt_env import load_frt_scenarios
from ..frt_metrics import evaluate_frt, fmt_summary
from ..train_common import select_env, run_metadata, assert_fresh_contract

ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT.parents[2] / 'data' / 'models'; MODELS.mkdir(parents=True, exist_ok=True)

EXPERTS = {
    'sym':      lambda s: s['category'] == 'LVRT' and s['fault_type'] == 'sym3ph',
    'hvrt_sym': lambda s: s['category'] == 'HVRT' and s['fault_type'] == 'swell_3ph',
}
RESET_AT = [100_000, 200_000]


class ResetCallback(BaseCallback):
    """Full network re-init (actor+critic, keep buffer & alpha) at given timesteps."""
    def __init__(self, reset_steps):
        super().__init__()
        self.todo = sorted(reset_steps)

    def _on_step(self) -> bool:
        if self.todo and self.num_timesteps >= self.todo[0]:
            self.todo.pop(0)
            pol = self.model.policy
            for net in (pol.actor, pol.critic):
                for m in net.modules():
                    if isinstance(m, nn.Linear):
                        m.reset_parameters()
            pol.critic_target.load_state_dict(pol.critic.state_dict())
            for opt in (pol.actor.optimizer, pol.critic.optimizer):
                opt.state = defaultdict(dict)
            print(f'  [reset] networks re-initialized at step {self.num_timesteps:,}', flush=True)
        return True


def make_model(variant, vec):
    common = dict(learning_rate=3e-4, buffer_size=100_000, batch_size=512, tau=0.005,
                  gamma=0.99, train_freq=1, gradient_steps=2, ent_coef='auto',
                  device='cpu', verbose=0, seed=42)
    if variant == 'tqc_reset':
        from sb3_contrib import TQC      # optional dep — imported lazily so the module loads without it
        return TQC('MlpPolicy', vec, top_quantiles_to_drop_per_net=2,
                   policy_kwargs=dict(net_arch=[256, 256, 256]), **common)
    return SAC('MlpPolicy', vec, policy_kwargs=dict(net_arch=[256, 256, 256]), **common)


def train_one(variant, name, filt, total_steps=300_000, n_envs=8, eval_freq=25_000, env_cls=None, legacy=False):
    env_cls = env_cls or select_env('frt', legacy=legacy)
    if not legacy:
        assert_fresh_contract(env_cls)
    scen = [s for s in load_frt_scenarios(ROOT.parents[2] / 'lab' / 'frt_scenarios.csv') if filt(s)]
    print(f'\n=== {variant} / expert "{name}": {len(scen)} scenarios ({env_cls.__name__}) ===', flush=True)
    from ..train_common import env_seeds
    vec = DummyVecEnv([(lambda s=s: env_cls(scen, seed=s, train_mode=True))
                       for s in env_seeds(42, n_envs)])       # deterministic per-env seeds (#6)
    model = make_model(variant, vec)
    # sanity: actor keys must match the Simulink exporter
    keys = list(model.policy.actor.state_dict().keys())
    assert any('latent_pi.0.weight' in k for k in keys) and any(k.startswith('mu.') for k in keys), keys
    cb = ResetCallback(RESET_AT)
    best, t0, step = 0.0, time.time(), 0
    while step < total_steps:
        chunk = min(eval_freq, total_steps - step)
        model.learn(total_timesteps=chunk, reset_num_timesteps=False, callback=cb)
        step += chunk
        m = evaluate_frt(model, scen, env_cls, n_eval=min(80, len(scen)))
        if m['partial_proxy_pct'] > best:   # ODE selection proxy (NOT certified FRT)
            best = m['partial_proxy_pct']; model.save(str(MODELS / f'ab_{variant}_{name}_best.zip'))
        print(f"  [{variant}/{name}] step={step:7,} {fmt_summary(m)} best_proxy={best:.0f}% "
              f"{(time.time()-t0)/60:.0f}min", flush=True)
    return best


def main():
    import argparse
    ap = argparse.ArgumentParser(); ap.add_argument('--legacy', action='store_true'); a = ap.parse_args()
    env_cls = select_env('frt', legacy=a.legacy)
    out = (ROOT.parents[2] / 'lab' / 'results') / ('legacy_pre_audit' if a.legacy else '')
    out.mkdir(parents=True, exist_ok=True)
    res = {'_metadata': run_metadata(env_cls, seed=42, scenario_split='2 experts (sym, hvrt_sym); P5', legacy=a.legacy)}
    for variant in ['sac_reset', 'tqc_reset']:
        for nm, fl in EXPERTS.items():
            res[f'{variant}/{nm}'] = train_one(variant, nm, fl, env_cls=env_cls, legacy=a.legacy)
    (out / f"ab_train{'_legacy' if a.legacy else ''}.json").write_text(json.dumps(res, indent=2))
    print('\nA/B DONE:', res, flush=True)


if __name__ == '__main__':
    main()
