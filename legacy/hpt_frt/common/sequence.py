"""sequence.py — PURE symmetrical-component (Fortescue) mathematics. NO OpenDSS / no I/O, so unit
tests import it without loading the dss_python backend (which crashed pytest at exit, 0xe0465043).

The OpenDSS bus-voltage access lives in hpt_frt.network.sequence, which imports these pure functions.
"""
from __future__ import annotations
import cmath

A = cmath.exp(1j * 2 * cmath.pi / 3.0)      # 120° operator
A2 = A * A


def symmetrical_components(Va, Vb, Vc):
    """Complex phase phasors -> (V1, V2, V0) complex sequence components (Fortescue)."""
    V1 = (Va + A * Vb + A2 * Vc) / 3.0
    V2 = (Va + A2 * Vb + A * Vc) / 3.0
    V0 = (Va + Vb + Vc) / 3.0
    return V1, V2, V0


def seq_magnitudes(Va, Vb, Vc):
    """(|V1|, |V2|, |V0|) magnitudes (pu)."""
    V1, V2, V0 = symmetrical_components(Va, Vb, Vc)
    return abs(V1), abs(V2), abs(V0)
