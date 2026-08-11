"""scenarios.py — system-level fault-scenario generator (section 五). Reproducible (config.SEED).

Matrix: fault bus 2..33 × type {sym3ph,2ph,1ph_g,2ph_g} × resistance (log-uniform 0.3..30 Ω,
controls depth) × load {0.7,1.0} × PV penetration {0,0.3,0.6}. Fault duration is COUPLED to the
realised global sag depth (GB/T: deeper faults are cleared faster) — assigned after the power flow,
not at sample time, so it reflects the true propagated depth.

~400 scenarios for the full study + a 48-scenario debug subset (stratified over fault type/depth).
"""
from __future__ import annotations
import numpy as np
from . import config as C

FAULT_TYPES = ['sym3ph', '1ph_g', '2ph', '2ph_g']
TYPE_P      = [0.30, 0.34, 0.18, 0.18]          # SLG most common, then 3ph, then LL/LLG
LOAD_LVLS   = [0.7, 1.0]
PV_PENS     = [0.0, 0.3, 0.6]


def gen_scenarios(n=400, seed=C.SEED):
    rng = np.random.default_rng(seed)
    out = []
    for i in range(n):
        out.append(dict(
            id=int(i),
            fault_bus=int(rng.integers(2, 34)),
            fault_type=str(rng.choice(FAULT_TYPES, p=TYPE_P)),
            r_fault=float(np.exp(rng.uniform(np.log(0.3), np.log(30.0)))),
            load_lvl=float(rng.choice(LOAD_LVLS)),
            pv_pen=float(rng.choice(PV_PENS)),
        ))
    return out


def debug_subset(seed=C.SEED + 1, n=48):
    """Stratified 48-scenario quick-debug subset: every fault type × a spread of resistances ×
    a spread of buses, balanced load/PV."""
    rng = np.random.default_rng(seed)
    buses = [3, 6, 9, 14, 18, 22, 25, 30, 33]
    rs = [0.3, 1.0, 3.0, 10.0, 30.0]
    out, i = [], 0
    for ft in FAULT_TYPES:
        for k in range(12):
            out.append(dict(
                id=int(i),
                fault_bus=int(rng.choice(buses)),
                fault_type=ft,
                r_fault=float(rng.choice(rs)),
                load_lvl=float(rng.choice(LOAD_LVLS)),
                pv_pen=float(rng.choice(PV_PENS)),
            ))
            i += 1
    return out[:n]


if __name__ == '__main__':
    s = gen_scenarios()
    import collections
    print(f'{len(s)} scenarios; types:', dict(collections.Counter(x['fault_type'] for x in s)))
    print(f'debug subset: {len(debug_subset())}')
