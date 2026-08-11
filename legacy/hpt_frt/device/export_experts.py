"""Export the 4 specialist SAC actors' weights to sac_{name}_weights.mat for Simulink closed-loop.

frt-v2 (audit fix #2): routes through `export_sac_actor.export_actor`, which reads n_obs/n_act FROM
THE MODEL (no hard-coded 21), enforces the 20/3 frt-v2 contract, builds the obs_test at the model's
true width, and uses the numpy2-robust loader. A stale frt-v1 (21/4) expert is rejected (use the
explicit legacy path only for legacy reproduction).
"""
import os
os.environ.setdefault('KMP_DUPLICATE_LIB_OK', 'TRUE')
os.environ.setdefault('MKL_THREADING_LAYER', 'SEQUENTIAL')
from pathlib import Path
from .export_sac_actor import export_actor

ROOT = Path(__file__).resolve().parent
MODELS = ROOT.parents[2] / 'data' / 'models'
LAB = ROOT.parents[2] / 'lab'
EXPERTS = ['sym', 'asym', 'hvrt_sym', 'hvrt_asym']


def main(legacy=False):
    for name in EXPERTS:
        export_actor(MODELS / f'sac_{name}_best.zip', LAB / f'sac_{name}_weights.mat', legacy=legacy)
    print('done — exported', len(EXPERTS), 'expert weight files (frt-v2 20/3)')


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(); ap.add_argument('--legacy', action='store_true'); a = ap.parse_args()
    main(legacy=a.legacy)
