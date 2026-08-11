"""Generate standardized FRT scenario tables.

Default behavior preserves the original 32 families x 10 runs = 320 baseline in
``lab/frt_scenarios.csv``. The ``expanded`` profile writes a separate research
matrix to ``lab/frt_scenarios_expanded.csv`` so certified baseline artifacts are
not invalidated accidentally.
"""
from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / 'lab' / 'frt_scenarios.csv'
VLL = 10e3
S_RATED = 400e3
W = 2 * math.pi * 50
PROFILE_BASE = 'base'
PROFILE_EXPANDED = 'expanded'

LVRT_TYPES = ['sym3ph', '1ph_g', '2ph', '2ph_g']
HVRT_TYPES = ['swell_3ph', 'swell_1ph']

# Baseline profile: current certified 320-scenario matrix.
LVRT_RESIDUAL = [0.20, 0.50, 0.75]
HVRT_LEVEL = [1.20, 1.30]
GRID = {'strong': 10.0, 'weak': 3.0}
XR_BASE = [3.0]

# Expanded research profile:
# - LVRT voltage points cover deep, mid, shallow and near-threshold dips.
# - HVRT points cover the 1.1 boundary, intermediate swell levels, and the
#   existing 1.2/1.3 limits.
# - SCR and X/R are swept because weak-grid and fault-impedance studies commonly
#   vary both grid strength and impedance angle.
# - Duration bins stay explicit. Note: the current switching harness caps fault
#   duration at 0.5 s, so the 1.0 s HVRT bin is primarily for ODE/training until
#   the switching harness is deliberately extended.
LVRT_RESIDUAL_EXPANDED = [0.10, 0.20, 0.35, 0.50, 0.70, 0.85]
HVRT_LEVEL_EXPANDED = [1.10, 1.15, 1.20, 1.25, 1.30]
GRID_EXPANDED = {
    'very_weak': 2.0,
    'weak': 3.0,
    'medium': 5.0,
    'strong': 10.0,
    'very_strong': 15.0,
}
XR_EXPANDED = [1.5, 3.0, 6.0]
LVRT_DURATIONS_EXPANDED = [0.16, 0.50]
HVRT_DURATIONS_EXPANDED = [0.50, 1.00]

REACH_09_S = 2.0


def z_grid(scr: float, xr: float = 3.0):
    zmag = VLL**2 / (scr * S_RATED)
    r = zmag / math.sqrt(1 + xr**2)
    x = xr * r
    return round(r, 4), round(x / W, 6)


def profile_config(profile: str):
    if profile == PROFILE_BASE:
        return dict(lvrt_residual=LVRT_RESIDUAL, hvrt_level=HVRT_LEVEL, grid=GRID,
                    xr=XR_BASE, lvrt_durations=[None], hvrt_durations=[None],
                    out=ROOT / 'lab' / 'frt_scenarios.csv', runs=10)
    if profile == PROFILE_EXPANDED:
        return dict(lvrt_residual=LVRT_RESIDUAL_EXPANDED,
                    hvrt_level=HVRT_LEVEL_EXPANDED,
                    grid=GRID_EXPANDED, xr=XR_EXPANDED,
                    lvrt_durations=LVRT_DURATIONS_EXPANDED,
                    hvrt_durations=HVRT_DURATIONS_EXPANDED,
                    out=ROOT / 'lab' / 'frt_scenarios_expanded.csv', runs=2)
    raise ValueError(f'unknown profile {profile!r}')


def jitter_duration(rng, center, category):
    if center is None:
        if category == 'LVRT':
            return float(rng.uniform(0.15, 0.625))
        return None
    span = 0.02 if center <= 0.2 else 0.05
    return float(max(0.05, center + rng.uniform(-span, span)))


def build(runs=10, seed=20260609, profile=PROFILE_BASE):
    cfg = profile_config(profile)
    rng = np.random.default_rng(seed)
    rows, sid, fid = [], 0, 0
    families = []

    for ft in LVRT_TYPES:
        for target in cfg['lvrt_residual']:
            for grid_name, scr in cfg['grid'].items():
                for xr in cfg['xr']:
                    for dur_center in cfg['lvrt_durations']:
                        families.append(('LVRT', ft, target, grid_name, scr, xr, dur_center))

    for ft in HVRT_TYPES:
        for target in cfg['hvrt_level']:
            for grid_name, scr in cfg['grid'].items():
                for xr in cfg['xr']:
                    for dur_center in cfg['hvrt_durations']:
                        families.append(('HVRT', ft, target, grid_name, scr, xr, dur_center))

    for cat, ft, target, grid_name, scr, xr, dur_center in families:
        fid += 1
        rg, lg = z_grid(scr, xr)
        for _ in range(runs):
            sid += 1
            p = float(S_RATED * rng.uniform(0.70, 0.90))
            pf = float(rng.uniform(0.85, 0.95))
            q = float(p * math.tan(math.acos(pf)))
            t_fault = float(rng.uniform(0.012, 0.030))
            if cat == 'LVRT':
                fault_dur = jitter_duration(rng, dur_center, cat)
            else:
                fault_dur = jitter_duration(rng, dur_center, cat)
                if fault_dur is None:
                    fault_dur = 0.5 if target >= 1.30 else 1.0
            t_sim = round(t_fault + fault_dur + 1.5, 4)
            r_trans = float(rng.uniform(0.05, 0.8))
            row = {
                'scenario_id': sid,
                'family_id': fid,
                'category': cat,
                'fault_type': ft,
                'target_V_pu': round(target, 3),
                'grid': grid_name,
                'scr': scr,
                'Rg_ohm': rg,
                'Lg_H': lg,
                'P_load': round(p, 1),
                'Q_load': round(q, 1),
                'power_factor': round(pf, 4),
                't_fault': round(t_fault, 6),
                'fault_dur': round(fault_dur, 4),
                'recover_to_0p9_s': REACH_09_S,
                'T_sim': t_sim,
                'trans_resistance': round(r_trans, 4),
                'random_seed': seed,
            }
            if profile != PROFILE_BASE:
                row['xr_ratio'] = xr
                row['duration_bin_s'] = '' if dur_center is None else dur_center
                row['scenario_profile'] = profile
            rows.append(row)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--profile', choices=[PROFILE_BASE, PROFILE_EXPANDED], default=PROFILE_BASE)
    ap.add_argument('--runs', type=int, default=None,
                    help='runs per family; default is 10 for base and 2 for expanded')
    ap.add_argument('--seed', type=int, default=20260609)
    ap.add_argument('--out', type=Path, default=None)
    args = ap.parse_args()

    cfg = profile_config(args.profile)
    runs = cfg['runs'] if args.runs is None else args.runs
    out = cfg['out'] if args.out is None else args.out
    rows = build(runs=runs, seed=args.seed, profile=args.profile)

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    import collections
    by_cat = collections.Counter(r['category'] for r in rows)
    by_type = collections.Counter(r['fault_type'] for r in rows)
    by_duration = collections.Counter(r.get('duration_bin_s', '') for r in rows)
    print(f'Wrote {len(rows)} FRT scenarios -> {out}')
    print(f'  profile: {args.profile}  runs/family: {runs}')
    print(f'  by category: {dict(by_cat)}')
    print(f'  by type:     {dict(by_type)}')
    print(f'  by duration bin: {dict(by_duration)}')
    print(f'  families: {max(r["family_id"] for r in rows)}')
    print(f'  T_sim range: {min(r["T_sim"] for r in rows):.2f}-{max(r["T_sim"] for r in rows):.2f} s')


if __name__ == '__main__':
    main()
