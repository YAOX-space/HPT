"""sequence.py — symmetrical-component extraction from OpenDSS + slow-recovery curves.

The HPT controller is trained on positive/negative sequence terminal magnitudes (V2p, V2n). The
feeder is a three-phase circuit; under an asymmetric fault the three phase voltages are unbalanced,
so we compute the Fortescue sequence components from the complex phase voltages.
"""
from __future__ import annotations
import numpy as np
import opendssdirect as dss
from ..common.sequence import symmetrical_components   # PURE Fortescue math (no dss; testable)


def bus_phasors(bus):
    """Return {node: complex pu voltage} for the active-able bus (per-unit, line-to-ground)."""
    dss.Circuit.SetActiveBus(str(bus))
    nodes = dss.Bus.Nodes()
    v = dss.Bus.PuVoltage()                  # [re,im, re,im, ...] aligned with Nodes()
    out = {}
    for k, n in enumerate(nodes):
        out[n] = complex(v[2 * k], v[2 * k + 1])
    return out


def seq_components(bus):
    """Positive/negative/zero sequence magnitudes (pu) at a 3-phase bus.

    Returns (Vp, Vn, V0). For a balanced bus Vn≈V0≈0, Vp≈mean phase magnitude. If fewer than 3
    phases are modelled the missing phases are treated as 0 (a faulted/collapsed phase)."""
    ph = bus_phasors(bus)
    Va, Vb, Vc = ph.get(1, 0j), ph.get(2, 0j), ph.get(3, 0j)
    V1, V2, V0 = symmetrical_components(Va, Vb, Vc)
    return abs(V1), abs(V2), abs(V0)


def mean_vmag(bus):
    """Mean phase voltage magnitude (pu) — fast scalar for sag-depth maps / convergence checks."""
    ph = bus_phasors(bus)
    mags = [abs(x) for x in ph.values() if x != 0j]
    return float(np.mean(mags)) if mags else 0.0


def phase_mags(bus):
    """Three phase magnitudes [|Va|,|Vb|,|Vc|] (pu), 0 for absent phases (for Simulink export)."""
    ph = bus_phasors(bus)
    return [abs(ph.get(1, 0j)), abs(ph.get(2, 0j)), abs(ph.get(3, 0j))]


def network_min_v():
    """Lowest mean-phase bus voltage across the whole feeder (pu) — global sag depth."""
    mn = 9.9
    for b in dss.Circuit.AllBusNames():
        m = mean_vmag(b)
        if 0 < m < mn:
            mn = m
    return mn if mn < 9.0 else 0.0


def recovery_curve(t, t_clear, t_recover, v_fault_p, kind='exp', v_final=1.0):
    """Slow post-fault recovery factor of the positive-sequence terminal voltage.

    Models FIDVR-style gradual restoration: at t_clear the voltage is still depressed (v_fault_p)
    and rises to v_final over t_recover seconds. `kind` ∈ {'linear','exp'}.
    Returns the positive-sequence multiplier to apply to the (cleared) network voltage."""
    if t < t_clear:
        return v_fault_p
    frac = min(1.0, (t - t_clear) / max(1e-6, t_recover))
    if kind == 'linear':
        s = frac
    else:                                    # exponential approach (motor re-acceleration)
        s = 1.0 - np.exp(-3.0 * frac)        # ~95% by frac=1
    return v_fault_p + (v_final - v_fault_p) * s
