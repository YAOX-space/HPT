"""safety_projection.py — PROPOSED deployment-side safety projection for the frt-v2 3-D action
`[iq, mse_d, mse_q]`. Post-processing of the SAC output ONLY: it does not change the network, the
training, or any result file.

⚠️ WIRING STATUS (2026-06-25): Part 1 below is IMPLEMENTED + unit-tested (tests/test_safety_projection.py)
but is **NOT yet wired into the live deployment path**. The only caller is the OFFLINE check
`device/project_offline_check.py`. The deployed network controller (`network/sac_wrapper._project_safety`)
applies a DIFFERENT, narrower projection (Vdc-surrogate series-boost shrink, iq untouched) — it does NOT
apply this wrong-sign reactive correction. So passing tests here do NOT certify deployed behavior.
Wiring this into sac_wrapper + re-running frt-v2 full-320 is the proposed remedy for the 34 FAILs
(see docs/FRT_V2_SAFETY_PROJECTION_PLAN_2026-06-24.md), pending a switching spotcheck — a deliberate
experiment, not a no-op cleanup.

Part 1 (IMPLEMENTED) — reactive sign-consistent dead-band.
  The frt-v2 `reactive_criterion` FAILs immediately on a WRONG SIGN:
    under-voltage (V+ < 0.9): iq < 0  (absorbing while the grid is sagging)  -> FAIL
    over-voltage  (V+ > 1.1): iq > 0  (sourcing while the grid is swelling)  -> FAIL
  The residual SAC's 24 reactive FAILs are exactly this, at near-boundary V+ (≈0.875 / 0.833 / 1.10)
  where the demanded reactive is tiny and the small SAC output crosses to the wrong side of zero.
  This projection forces iq onto the correct side of zero in the constrained region — its trigger is
  the CONTRAPOSITIVE of the criterion's wrong-sign predicate, so any sample that would trip wrong-sign
  is corrected. It never increases |iq| and never touches mse_d / mse_q, so current-limit and series
  commands are preserved.

Part 2 (PLAN ONLY — see docs/FRT_V2_SAFETY_PROJECTION_PLAN_2026-06-24.md) — HVRT DC-bus survival for the
scr3 + swell_3ph + Vg_p=1.30 cluster is NOT implemented here; it needs a switching spotcheck to validate.

Thresholds mirror common/frt_v2.py (V+ 0.9 / 1.1, REACTIVE_SIGN_EPS=1e-3) and residual_env.IQ_CAP=0.27.
"""
from __future__ import annotations
import numpy as np

# defaults mirror the frt-v2 criterion + residual env (single source: common/frt_v2.py, residual_env.py)
DEFAULTS = dict(
    lvrt_lo=0.9,       # V+ below this => under-voltage => iq must be >= 0 (capacitive)
    hvrt_hi=1.1,       # V+ above this => over-voltage  => iq must be <= 0 (inductive/absorb)
    sign_eps=1e-3,     # = REACTIVE_SIGN_EPS; wrong-sign dead-band
    iq_cap=0.27,       # = residual_env.IQ_CAP; max |iq| (current/action bound)
)


def required_iq_sign(V1_pu, lvrt_lo=0.9, hvrt_hi=1.1):
    """+1 if iq must be non-negative (under-voltage), -1 if non-positive (over-voltage), 0 if neutral."""
    if V1_pu < lvrt_lo:
        return +1
    if V1_pu > hvrt_hi:
        return -1
    return 0


def project_action(action, V1_pu, category=None, iq_ref=None, current_limit=None, params=None):
    """Project the 3-D action `[iq, mse_d, mse_q]` onto the sign-consistent + current-limited safe set.

    Parameters
    ----------
    action : array-like, length 3  -- [iq, mse_d, mse_q] (the SAC / deployed command).
    V1_pu  : float                 -- measured positive-sequence terminal voltage (pu) at this step.
    category : str, optional       -- 'LVRT'/'HVRT' (informational; the sign rule is driven by V1_pu).
    iq_ref : float, optional       -- droop reference; if given and same sign as required, used as the
                                      projection floor instead of 0 (never over-injects).
    current_limit : float, optional-- |iq| cap; defaults to params['iq_cap'].
    params : dict, optional        -- overrides for DEFAULTS.

    Returns
    -------
    (projected : np.ndarray(3,), meta : dict)
      meta = {triggered, reason, iq_in, iq_out, V1_pu, required_sign, region, cap}
    """
    cfg = dict(DEFAULTS)
    if params:
        cfg.update(params)
    a = np.asarray(action, dtype=np.float64).reshape(-1)
    if a.size != 3:
        raise ValueError(f'action must be length-3 [iq, mse_d, mse_q], got {a.size}')
    iq, mse_d, mse_q = float(a[0]), float(a[1]), float(a[2])
    iq_in = iq
    cap = float(current_limit) if current_limit is not None else float(cfg['iq_cap'])
    sign = required_iq_sign(V1_pu, cfg['lvrt_lo'], cfg['hvrt_hi'])
    region = {1: 'undervolt', -1: 'overvolt', 0: 'neutral'}[sign]
    reasons = []

    # --- Part 1: sign-consistent dead-band (the wrong-sign fix) ---
    if sign > 0 and iq < -cfg['sign_eps']:            # under-voltage but absorbing -> wrong sign
        floor = 0.0
        if iq_ref is not None and iq_ref > 0:         # optional: snap to the correct-direction demand
            floor = min(float(iq_ref), cap)
        iq = floor
        reasons.append(f'undervolt_wrong_sign(iq<0)->{iq:+.3f}')
    elif sign < 0 and iq > cfg['sign_eps']:           # over-voltage but sourcing -> wrong sign
        ceil = 0.0
        if iq_ref is not None and iq_ref < 0:
            ceil = max(float(iq_ref), -cap)
        iq = ceil
        reasons.append(f'overvolt_wrong_sign(iq>0)->{iq:+.3f}')

    # --- current/action bound (projection never grows |iq|, but guard anyway) ---
    if abs(iq) > cap:
        iq = float(np.clip(iq, -cap, cap))
        reasons.append('iq_clipped_to_cap')

    projected = np.array([iq, mse_d, mse_q], dtype=np.float64)
    meta = dict(triggered=bool(reasons), reason=(' + '.join(reasons) if reasons else 'none'),
                iq_in=iq_in, iq_out=iq, V1_pu=float(V1_pu), required_sign=sign, region=region, cap=cap)
    return projected, meta


def is_wrong_sign(iq, V1_pu, lvrt_lo=0.9, hvrt_hi=1.1, sign_eps=1e-3):
    """The frt-v2 criterion's wrong-sign predicate (for offline checking)."""
    if V1_pu < lvrt_lo and iq < -sign_eps:
        return True
    if V1_pu > hvrt_hi and iq > sign_eps:
        return True
    return False
