"""retrain_expert.py — retrain ONE expert in place for error-analysis-driven improvement.

Fixes two workflow traps found in the 2026-06-27 audit:
  * AUTO-MIGRATES the stale best/final (+ sidecars) to data/models/legacy_pre_resweep/ so the
    CheckpointSelector stale-guard (assert_no_stale_target) does not abort the run.
  * default total_steps = 100k (the per-expert scenario subsets are small; 300k was overkill and
    made the run ~3x slower for no benefit).

Selection now also tracks the Vdc-survival proxy (frt_metrics, audit 2026-06-27) so the saved `best`
reflects DC-survival improvement (anti-boost) rather than freezing on a saturated connect+reactive
proxy. Certification is still the switching frt_v2_full320 (the authority).

    python -m hpt_frt.device.retrain_expert hvrt_sym --steps 100000 --seed 42
"""
import os
os.environ.setdefault('KMP_DUPLICATE_LIB_OK', 'TRUE')
os.environ.setdefault('MKL_THREADING_LAYER', 'SEQUENTIAL')
import shutil
from .train_experts import train_one, EXPERTS, MODELS


def migrate_stale(name):
    """Move sac_<name>_{best,final}.{zip,json} to legacy_pre_resweep/ (clears the stale guard)."""
    leg = MODELS / 'legacy_pre_resweep'
    leg.mkdir(parents=True, exist_ok=True)
    moved = []
    for suf in ('_best.zip', '_best.json', '_final.zip', '_final.json'):
        p = MODELS / f'sac_{name}{suf}'
        if p.exists():
            shutil.move(str(p), str(leg / p.name))
            moved.append(p.name)
    print(f'migrated stale -> legacy_pre_resweep/: {moved or "(none)"}', flush=True)


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('name', choices=list(EXPERTS))
    ap.add_argument('--steps', type=int, default=100_000)
    ap.add_argument('--seed', type=int, default=42)
    a = ap.parse_args()
    migrate_stale(a.name)
    best = train_one(a.name, EXPERTS[a.name], total_steps=a.steps, seed=a.seed)
    print(f'RETRAIN {a.name} DONE: best_proxy={best}', flush=True)


if __name__ == '__main__':
    main()
