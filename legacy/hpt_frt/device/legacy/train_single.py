"""train_single.py — train ONE model (one job of the parallel sweep). Dispatches to the fixed
train_one (CheckpointSelector + frozen split + sidecars). Spawned as a subprocess by
run_sweep_parallel.py so independent trainings run concurrently on the idle CPU cores.

    python -m hpt_frt.device.train_single --kind expert      --name sym --seed 42
    python -m hpt_frt.device.train_single --kind seed_expert --name asym --seed 7
    python -m hpt_frt.device.train_single --kind ablation    --seed 42
    python -m hpt_frt.device.train_single --kind residual    --seed 42
"""
import os
os.environ.setdefault('KMP_DUPLICATE_LIB_OK', 'TRUE')
os.environ.setdefault('MKL_THREADING_LAYER', 'SEQUENTIAL')
import argparse
from .train_experts import train_one as expert_train_one, EXPERTS
from .train_seeds import train_one as seed_train_one
from .. import train_residual


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--kind', required=True, choices=['expert', 'seed_expert', 'ablation', 'residual'])
    ap.add_argument('--name', default='')
    ap.add_argument('--seed', type=int, default=42)
    ap.add_argument('--steps', type=int, default=300_000)
    a = ap.parse_args()
    if a.kind == 'expert':
        r = expert_train_one(a.name, EXPERTS[a.name], total_steps=a.steps, seed=a.seed)
    elif a.kind == 'seed_expert':
        r = seed_train_one(f'sd_{a.seed}_{a.name}', EXPERTS[a.name], a.seed, total_steps=a.steps)
    elif a.kind == 'ablation':
        r = seed_train_one('ablation_single', lambda s: True, a.seed, total_steps=a.steps)
    else:  # residual
        train_residual.main(total_steps=a.steps, seed=a.seed); r = 'done'
    print(f'JOB DONE kind={a.kind} name={a.name} seed={a.seed} -> {r}', flush=True)


if __name__ == '__main__':
    main()
