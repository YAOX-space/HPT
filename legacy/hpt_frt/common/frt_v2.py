"""frt_v2.py — versioned FRT criteria (metrics_version = 'frt-v2'), the SINGLE definition shared by
Python (ODE / network) and mirrored by MATLAB. Fixes audit C1–C3, H3–H4, M5 and the 2026-06-22
regressions:

  * REAL time vector t (never linspace on a variable-step solver)                                [C1]
  * connect = PCC voltage on the required side of the GB/T voltage-time envelope over the whole
    assessment window. The LVRT lower boundary is fixed at 0.20 pu through 625 ms and then rises
    linearly to 0.90 pu at 2 s. `solver_tol` is only a numerical comparison guard.                 [C2]
  * limit = max(peak phase current, sqrt(id^2+iq^2)) normalised by the PEAK base I_sys_peak.       [C3]
  * recover = post-clear ramp envelope + final steady |V+-1|<=band; requires sufficient post window.[§1.4]
  * survive = Vdc in [0.75,1.25] over the FULL domain AND negative-seq current I2 <= 3 pu.          [H4,M5]
  * HVRT connect = 1.30 pu through 0.5 s, 1.25 pu through 1 s, 1.20 pu through 10 s, then 1.10 pu. [H3]
  * response (5 ms) computed SEPARATELY, never inside frt_pass.                                     [§1]

STATUS model: every criterion has a status in {PASS, FAIL, NOT_EVALUATED}. A mandatory criterion
whose required measurement is missing (iq / current / Vdc / I2) or whose window is insufficient
(no/too-short recovery) is NOT_EVALUATED — it does NOT pass. `frt_pass` is:
  None   if any mandatory criterion is NOT_EVALUATED  (cannot certify),
  False  if any mandatory criterion FAILs,
  True   only if all five PASS.
Structural input errors (length mismatch, non-finite, non-monotonic time, empty fault window) raise
ValueError — they are caller bugs, not "passes".
"""
from __future__ import annotations
import numpy as np
from . import pu as PU

METRICS_VERSION = 'frt-v2'

# status constants
PASS = 'PASS'
FAIL = 'FAIL'
NOT_EVALUATED = 'NOT_EVALUATED'
MANDATORY = ('connect', 'reactive', 'limit', 'recover', 'survive')
VALID_CATEGORIES = ('LVRT', 'HVRT')

# GB/T envelope timing (s, real time after fault onset)
LVRT_HOLD = 0.625          # residual held >= 625 ms
LVRT_REACH = 2.0           # linear recovery to 0.9 pu by 2 s
LVRT_FLOOR = 0.20          # fixed GB/T lower boundary during the hold
RECOVER_BAND = 0.07        # final steady |V+-1| <= 7 %  [任务书]
RECOVER_MIN_COVER = 0.10   # min post-clear duration (s) needed to assess recovery (else NOT_EVALUATED)
REACTIVE_TOL = 0.12        # under-support tolerance (system-pu); see reactive_criterion (MIN-SUPPORT)
# Reactive criterion is MINIMUM-SUPPORT (project-defined, NOT a literal GB/T numeric clause):
#   LVRT: iq >= iq_ref - REACTIVE_TOL  (inject AT LEAST the droop demand; over-injection is allowed
#         and is bounded by the LIMIT criterion via the total current constraint, not here).
#   HVRT: iq <= iq_ref + REACTIVE_TOL  (absorb at least the demand; iq_ref<0).
# Assessment starts REACTIVE_DELAY after onset (response window) and requires the demand to be met for
# at least REACTIVE_DWELL of the demanded samples (sustained, not instantaneous, not whole-window mean).
# Wrong sign (sourcing when absorbing is required, or vice versa) is an IMMEDIATE FAIL.
REACTIVE_DELAY = 0.06      # s after fault onset before support must be present (response settling)
REACTIVE_DWELL = 0.80      # fraction of demanded samples that must meet min-support
REACTIVE_SIGN_EPS = 1e-3   # dead-band for the wrong-sign test
I2_MAX_PU = 3.0            # negative-seq current limit (FRT_SPEC criterion 5)
VDC_LO, VDC_HI = 0.75, 1.25
DEFAULT_SOLVER_TOL = 1e-3  # float-comparison guard ONLY (NOT a physical margin)


def lvrt_lower_env(t_rel, residual):
    """GB/T LVRT lower boundary at real time ``t_rel`` after onset.

    ``residual`` is retained for source compatibility but does not define the
    standard curve.  The floor is fixed at 0.20 pu for 625 ms and then rises
    linearly to 0.90 pu at 2 s.
    """
    del residual
    if t_rel < 0:
        return 0.9
    if t_rel <= LVRT_HOLD:
        return LVRT_FLOOR
    if t_rel <= LVRT_REACH:
        return LVRT_FLOOR + (0.9 - LVRT_FLOOR) * (t_rel - LVRT_HOLD) / (LVRT_REACH - LVRT_HOLD)
    return 0.9


def hvrt_upper_env(t_rel):
    """GB/T HVRT upper boundary: 1.30, 1.25, 1.20, then 1.10 pu."""
    if t_rel < 0:
        return 1.1
    if t_rel <= 0.5:
        return 1.30
    if t_rel <= 1.0:
        return 1.25
    if t_rel <= 10.0:
        return 1.20
    return 1.10


def envelope_value(category, t_rel, residual):
    """UNIFIED versioned voltage-time boundary (the single interface the ODE env trips/rewards on).
    Returns (boundary_pu, side): side='lower' for LVRT (V+ must be >= boundary), 'upper' for HVRT
    (V+ must be <= boundary). t_rel is REAL seconds after fault onset."""
    _validate_category(category)
    if category == 'LVRT':
        return lvrt_lower_env(t_rel, residual), 'lower'
    return hvrt_upper_env(t_rel), 'upper'


def _validate_category(category):
    if category not in VALID_CATEGORIES:
        raise ValueError(f'category must be one of {VALID_CATEGORIES}, got {category!r}')


def within_envelope(category, t_rel, residual, v_plus, solver_tol=DEFAULT_SOLVER_TOL):
    """True iff terminal V+ is on the correct side of the versioned envelope. `solver_tol` is ONLY a
    float-comparison guard (default 1e-3), kept distinct from the physical boundary — never widen the
    boundary with it."""
    b, side = envelope_value(category, t_rel, residual)
    return (v_plus >= b - solver_tol) if side == 'lower' else (v_plus <= b + solver_tol)


def iq_ref_droop(V1):
    """GB/T reactive-droop reference (SYSTEM-pu), capped at PE full (0.3). Inductive(+) under-volt."""
    if V1 < 0.9:
        return min(PU.IQ_PE_LIMIT_PU, 1.5 * (0.9 - V1))
    if V1 > 1.1:
        return max(-PU.IQ_PE_LIMIT_PU, -1.5 * (V1 - 1.1))
    return 0.0


def reactive_criterion(t, V1, iq, category, in_fault, t_fault, *, tol=REACTIVE_TOL,
                       delay=REACTIVE_DELAY, dwell=REACTIVE_DWELL):
    """MINIMUM-SUPPORT reactive assessment (project-defined). Returns
    (status, worst_under_support, t_worst, reason, detail). status in {PASS, FAIL, NOT_EVALUATED}.

    - wrong sign (sourcing under-voltage / absorbing over-voltage) -> immediate FAIL;
    - assessment window = fault window starting `delay` after onset (response settling);
    - at demanded samples (|iq_ref|>tol) the device must meet min-support:
        LVRT: iq >= iq_ref - tol ;  HVRT: iq <= iq_ref + tol ;
    - PASS requires the met-fraction over demanded samples >= `dwell`;
    - reports max under-support (worst shortfall) and the sustained met-fraction.
    Over-injection is NOT penalised here — it is bounded by the LIMIT criterion (total current)."""
    _validate_category(category)
    ref = np.array([iq_ref_droop(v) for v in V1])
    fault = in_fault
    if not fault.any():
        return NOT_EVALUATED, np.nan, t_fault, 'no fault-window samples', {}
    assess = fault & (t >= t_fault + delay)        # response-settling window (also used for min-support)
    # SUSTAINED wrong sign within the ASSESSMENT window -> immediate FAIL. Assessed after the response
    # delay (NOT the raw onset): as iq slews from its pre-event ~0 state through zero it can momentarily
    # sit on the wrong side of 0 for a single sample while V+ is just crossing 1.1 — that transient must
    # not trip the criterion (it failed every swell case). A real wrong-sign policy holds the wrong sign
    # well past the settling delay and is still caught here.
    wrong = np.any((V1[assess] < 0.9) & (iq[assess] < -REACTIVE_SIGN_EPS)) or \
            np.any((V1[assess] > 1.1) & (iq[assess] > REACTIVE_SIGN_EPS))
    if wrong:
        return FAIL, np.nan, t_fault, 'wrong sign (sourcing under-volt / absorbing over-volt)', \
               {'wrong_sign': True}
    demanded = assess & (np.abs(ref) > tol)
    if not demanded.any():
        # support window has no real demand (shallow sag cleared within the response delay) -> NOT_EVALUATED
        return NOT_EVALUATED, np.nan, t_fault, 'no sustained reactive demand after response delay', \
               {'n_demanded': 0}
    iq_d, ref_d, t_d = iq[demanded], ref[demanded], t[demanded]
    if category == 'LVRT':
        shortfall = np.maximum(0.0, (ref_d - tol) - iq_d)      # how far BELOW min-support
    else:
        shortfall = np.maximum(0.0, iq_d - (ref_d + tol))      # how far ABOVE max-absorb (HVRT)
    met = shortfall <= 1e-9
    met_frac = float(np.mean(met))
    j = int(np.argmax(shortfall)); worst = float(shortfall.max())
    good = met_frac >= dwell
    reason = 'ok' if good else f'min-support held only {met_frac:.0%} (<{dwell:.0%}); under-support {worst:.3f}'
    return (PASS if good else FAIL), worst, float(t_d[j]), reason, \
        {'met_fraction': met_frac, 'max_under_support': worst, 'n_demanded': int(demanded.sum())}


def _crit(status, worst, t_worst, reason):
    return dict(status=status, passed=(status == PASS), worst=float(worst),
                t_worst=float(t_worst), reason=reason)


def _validate(t, V1, named):
    """Structural validation -> raise ValueError on caller bugs. `named` = {name: array|None}."""
    t = np.asarray(t, float); V1 = np.asarray(V1, float)
    if t.ndim != 1 or t.size < 2:
        raise ValueError('t must be 1-D with >=2 samples')
    if V1.shape != t.shape:
        raise ValueError(f'V1 length {V1.shape} != t length {t.shape}')
    if not np.all(np.isfinite(t)) or not np.all(np.isfinite(V1)):
        raise ValueError('t/V1 contain non-finite values')
    if not np.all(np.diff(t) > 0):
        raise ValueError('t must be strictly increasing (monotonic)')
    arrs = {}
    for name, a in named.items():
        if a is None:
            arrs[name] = None
            continue
        a = np.asarray(a, float)
        if a.shape != t.shape:
            raise ValueError(f'{name} length {a.shape} != t length {t.shape}')
        if not np.all(np.isfinite(a)):
            raise ValueError(f'{name} contains non-finite values')
        arrs[name] = a
    return t, V1, arrs


def evaluate(t, V1, category, residual, t_fault, dur, *, V2=None, Vdc=None,
             iq=None, i_peak=None, idq_mag=None, i2=None, solver_tol=DEFAULT_SOLVER_TOL):
    """Evaluate frt-v2 criteria from REAL time-series. See module docstring for the status model.
    Returns {criterion: {status,passed,worst,t_worst,reason}, ..., frt_pass: True|False|None}."""
    _validate_category(category)
    if dur <= 0:
        raise ValueError('dur must be > 0')
    t, V1, A = _validate(t, V1, dict(V2=V2, Vdc=Vdc, iq=iq, i_peak=i_peak, idq_mag=idq_mag, i2=i2))
    Vdc, iq, i_peak, idq_mag, i2 = A['Vdc'], A['iq'], A['i_peak'], A['idq_mag'], A['i2']
    in_fault = (t >= t_fault) & (t <= t_fault + dur)
    if not in_fault.any():
        raise ValueError('empty fault window (t_fault/dur outside t range)')
    post = t > t_fault + dur
    out = {}

    # ── connect: V+ vs the time-varying GB/T envelope (LVRT lower / HVRT upper) over fault+recovery ──
    if category == 'LVRT':
        env = np.array([lvrt_lower_env(ti - t_fault, residual) for ti in t])
        margin = V1 - env                                     # >=0 inside; physical boundary, no slack
    else:
        env = np.array([hvrt_upper_env(ti - t_fault) for ti in t])
        margin = env - V1
    win = in_fault | post
    k = int(np.argmin(np.where(win, margin, np.inf)))
    ok = margin[win].min() >= -solver_tol                     # solver_tol = float guard only
    out['connect'] = _crit(PASS if ok else FAIL, margin[k], t[k],
                           'ok' if ok else 'V+ left GB/T envelope')

    # ── reactive: MINIMUM-SUPPORT (signed) with response delay + sustained dwell + wrong-sign FAIL ──
    if iq is None:
        out['reactive'] = _crit(NOT_EVALUATED, np.nan, t_fault, 'iq not provided')
    else:
        st, worst, tw, reason, detail = reactive_criterion(t, V1, iq, category, in_fault, t_fault)
        c = _crit(st, worst, tw, reason)
        c['detail'] = detail
        out['reactive'] = c

    # ── limit: max(peak phase current, sqrt(id^2+iq^2)) <= converter limit (PEAK base) ──
    lim = PU.I_CONV_MAX_PU
    cur = None
    if i_peak is not None:
        cur = i_peak
    if idq_mag is not None:
        cur = idq_mag if cur is None else np.maximum(cur, idq_mag)
    if cur is None:
        out['limit'] = _crit(NOT_EVALUATED, np.nan, t_fault, 'current (i_peak/idq_mag) not provided')
    else:
        k = int(np.argmax(cur)); good = cur.max() <= lim + solver_tol
        out['limit'] = _crit(PASS if good else FAIL, cur.max(), t[k],
                             'ok' if good else f'I>{lim} pu')

    # ── recover: post-clear V+ within recovery envelope + final steady |V+-1|<=band ──
    cover = (t[-1] - (t_fault + dur)) if post.any() else 0.0
    if not post.any() or cover < RECOVER_MIN_COVER:
        out['recover'] = _crit(NOT_EVALUATED, np.nan, t[-1],
                               f'insufficient recovery window ({cover:.3f}s < {RECOVER_MIN_COVER}s)')
    else:
        tp, Vp = t[post], V1[post]
        env_p = (np.array([lvrt_lower_env(ti - t_fault, residual) for ti in tp]) if category == 'LVRT'
                 else np.array([hvrt_upper_env(ti - t_fault) for ti in tp]))
        final_mask = tp >= tp[-1] - 0.12
        final_dev = np.abs(Vp[final_mask] - 1.0).max()
        env_ok = (np.all(Vp >= env_p - solver_tol) if category == 'LVRT'
                  else np.all(Vp <= env_p + solver_tol))
        good = bool(env_ok and final_dev <= RECOVER_BAND)
        out['recover'] = _crit(PASS if good else FAIL, final_dev, tp[-1],
                               'ok' if good else ('|V+-1|>band' if final_dev > RECOVER_BAND else 'left recovery env'))

    # ── survive: Vdc in [0.75,1.25] over FULL domain AND I2 current <= 3 pu (both mandatory) ──
    if Vdc is None or i2 is None:
        miss = ' & '.join([n for n, a in (('Vdc', Vdc), ('I2', i2)) if a is None])
        out['survive'] = _crit(NOT_EVALUATED, np.nan, t_fault, f'{miss} not provided')
    else:
        vmin, vmax = Vdc.min(), Vdc.max()
        vdc_ok = vmin >= VDC_LO and vmax <= VDC_HI
        i2max = i2.max(); i2_ok = i2max <= I2_MAX_PU
        if not vdc_ok:
            worst, tw, reason = ((VDC_LO - vmin, t[int(np.argmin(Vdc))], 'Vdc<0.75')
                                 if (VDC_LO - vmin) >= (vmax - VDC_HI)
                                 else (vmax - VDC_HI, t[int(np.argmax(Vdc))], 'Vdc>1.25'))
        elif not i2_ok:
            worst, tw, reason = i2max - I2_MAX_PU, t[int(np.argmax(i2))], f'I2>{I2_MAX_PU}pu'
        else:
            worst, tw, reason = 0.0, t[int(np.argmin(Vdc))], 'ok'
        out['survive'] = _crit(PASS if (vdc_ok and i2_ok) else FAIL, worst, tw, reason)

    # ── frt_pass precedence: any FAIL -> False FIRST; else any NOT_EVALUATED -> None; else True ──
    # (a FAIL is a definite non-pass and must not be masked to None by a separately-missing criterion)
    statuses = [out[c]['status'] for c in MANDATORY]
    out['frt_pass'] = (False if FAIL in statuses
                       else (None if NOT_EVALUATED in statuses else True))
    out['metrics_version'] = METRICS_VERSION
    return out


# ── 5 ms voltage-regulation response — SEPARATE control-response metric (NEVER inside frt_pass) ──
# MATLAB frt-v2 validator plan (P1): the rewritten validate_mode_full.m must call an equivalent of
# response_metrics on the measured reactive current iq (target = the explicit droop reference at the
# fault residual, NOT a window median) using the REAL solver time `tout`, and store the fields
#   response_status, rise_time_ms, settling_time_ms, meets_5ms
# in each result struct ALONGSIDE (not inside) the five-criteria frt_pass. Same contract as the
# Python device path (_response_of in device/frt_metrics.py).
RESP_BAND = 0.02            # tolerance band (pu) around the settled value
RESP_DWELL = 0.002         # must remain inside the band this long to be "settled" (s)
RESP_RISE_LO, RESP_RISE_HI = 0.10, 0.90    # rise time = 10% -> 90% of the step
RESP_MIN_SAMPLES = 3       # min samples in the post-onset assessment window (else insufficient res.)


def response_metrics(t, signal, t_event, *, band=RESP_BAND, dwell=RESP_DWELL,
                     settle_window=0.10, pre_window=0.02, target=None):
    """Proper control-response measurement of `signal` to a step at `t_event`.

    baseline   = mean over the pre-event window [t_event-pre_window, t_event);
    settled    = `target` if given, else the median over the last `settle_window` seconds;
    rise_time  = time from t_event for signal to cross 10%->90% of the (settled-baseline) step;
    settling_time = first time t_s>=t_event after which |signal-settled|<=band for the whole
                    remaining record AND for at least `dwell` (else 'not settled');
    overshoot  = max excursion beyond `settled` in the step direction, as a fraction of |step|.
    Returns a dict; NEVER folded into frt_pass. status in {settled, not_settled, insufficient_resolution}.
    """
    t = np.asarray(t, float); s = np.asarray(signal, float)
    if t.shape != s.shape or t.size < 2 or not np.all(np.diff(t) > 0):
        raise ValueError('response_metrics: t/signal must be equal-length with strictly increasing t')
    i0 = int(np.searchsorted(t, t_event))
    pre = (t >= t_event - pre_window) & (t < t_event)
    baseline = float(s[pre].mean()) if pre.any() else float(s[max(0, i0 - 1)])
    postwin = t >= t[-1] - settle_window
    settled = float(target) if target is not None else (float(np.median(s[postwin])) if postwin.any()
                                                        else float(s[-1]))
    post = t >= t_event
    nan = float('nan')
    if post.sum() < RESP_MIN_SAMPLES:
        return dict(status='insufficient_resolution', rise_time_ms=nan, settling_time_ms=nan,
                    settled=False, overshoot=nan, baseline=baseline, settled_value=settled,
                    metrics_version=METRICS_VERSION)
    step = settled - baseline
    sign = 1.0 if step >= 0 else -1.0
    # rise time (10% -> 90%); undefined for a negligible step
    rise_ms = nan
    if abs(step) > max(1e-6, band):
        lo, hi = baseline + RESP_RISE_LO * step, baseline + RESP_RISE_HI * step
        t_lo = t_hi = None
        for i in range(i0, len(s)):
            if t_lo is None and sign * (s[i] - lo) >= 0:
                t_lo = t[i]
            if t_hi is None and sign * (s[i] - hi) >= 0:
                t_hi = t[i]; break
        if t_lo is not None and t_hi is not None:
            rise_ms = float((t_hi - t_lo) * 1e3)
    # settling time: last exit from the band; require dwell to the end
    inband = np.abs(s - settled) <= band
    settle_ms, settled_ok = nan, False
    after = np.where(post)[0]
    if after.size:
        # find the last index where it is OUT of band; settling = the next sample
        out_idx = after[~inband[after]]
        if out_idx.size == 0:
            settle_ms, settled_ok = float((t[after[0]] - t_event) * 1e3), True   # already in band at onset
        else:
            last_out = int(out_idx.max())
            if last_out < len(s) - 1:
                ts = t[last_out + 1]
                # dwell check: stays in band from ts to the end, and that span >= dwell
                if (t[-1] - ts) >= dwell and np.all(inband[last_out + 1:]):
                    settle_ms, settled_ok = float((ts - t_event) * 1e3), True
    # overshoot beyond settled in the step direction
    excursion = sign * (s[post] - settled)
    overshoot = float(max(0.0, excursion.max()) / abs(step)) if abs(step) > 1e-6 else 0.0
    return dict(status='settled' if settled_ok else 'not_settled',
                rise_time_ms=rise_ms, settling_time_ms=settle_ms, settled=bool(settled_ok),
                overshoot=overshoot, baseline=baseline, settled_value=settled,
                meets_5ms=bool(settled_ok and settle_ms <= 5.0), metrics_version=METRICS_VERSION)
