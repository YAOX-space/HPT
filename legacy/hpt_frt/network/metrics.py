"""metrics.py — PHASOR-LAYER SCREENING ONLY (NOT FRT certification).

QUARANTINE (audit item 2): these are STATIC steady-state phasor-snapshot checks. A static snapshot
CANNOT satisfy the time-series frt-v2 contract (no real time vector, no Vdc/i2 trajectory, no 5 ms
response, no recovery-window coverage). Therefore:
  * outputs are named `screen_*` and `screen_pass`, NEVER `frt_pass`;
  * `screen_pass` is a SCREENING flag, not an FRT verdict — it must never be reported as an FRT
    compliance rate or a GB/T pass rate;
  * a tombstone `frt_pass=None` is emitted so any caller that still reads `frt_pass` gets None
    (never True);
  * every result carries `metrics_version` and `evaluation_scope`;
  * non-converged scenarios are a SEPARATE MANDATORY status (`convergence_pct`) and are NOT silently
    dropped from the picture — device screening rates are explicitly "over converged only" and the
    convergence rate is reported alongside so a low convergence cannot be hidden.
Full FRT certification requires the time-domain switching harness via `frt_v2.evaluate` (the
trajectory adapter, audit option (a)), not this module.
"""
from __future__ import annotations
import numpy as np
from . import config as C

METRICS_VERSION = 'frt-v1-phasor-screening'      # explicitly NOT 'frt-v2'
EVALUATION_SCOPE = 'static-phasor-snapshot'       # steady-state, single operating point, no trajectory


def vdc_window(veq, dur):
    """Vdc_min over a held fault of length `dur`: relax 1.0 -> veq with DC_TAU (energy state)."""
    vdc_end = veq + (1.0 - veq) * np.exp(-dur / C.DC_TAU)
    return float(min(1.0, vdc_end)), float(min(C.VDC_CHOP, max(veq, 1.0)))


def device_criteria(*, Vp, Vn, iq, se_d, se_q, iq_ref, vdc_min, vdc_max, v_load, gate, dur,
                    v_post=None, iq_post=None):
    """Phasor-layer SCREEN of the five criterion proxies for one HPT in one scenario.
    Returns `screen_*` flags + `screen_pass` (screening only). `frt_pass=None` is a tombstone:
    a static phasor snapshot can never certify an FRT pass."""
    # 1. connect: LV positive-seq (after series comp) rides through; deep zero-V GB/T allowance
    connect = bool(v_load >= 0.20 or (Vp < 0.05 and dur <= 0.15))
    # 2. reactive: GB/T droop magnitude met AND correct sign
    reactive = bool(abs(iq - iq_ref) <= C.REACTIVE_TOL and not (Vp < 0.9 and iq < -1e-3))
    # 3. limit: command within converter current limit (measured-peak risk deferred to L1)
    limit = bool(abs(iq) <= C.LIMIT_PU + 1e-6)
    # 4. recover: post-fault terminal back to 1±band and reactive withdrawn (N/A -> pass if no post)
    if v_post is None:
        recover = True
    else:
        recover = bool(abs(v_post - 1.0) <= C.RECOVER_BAND + 0.03 and (iq_post is None or iq_post < 0.05))
    # 5. survive: DC bus within [0.75, 1.25]
    survive = bool(vdc_min >= C.VDC_MIN_OK and vdc_max <= C.VDC_MAX_OK)
    return dict(connect=connect, reactive=reactive, limit=limit, recover=recover, survive=survive,
                screen_pass=bool(connect and reactive and limit and recover and survive),
                frt_pass=None,                                 # tombstone — static snapshot never certifies
                metrics_version=METRICS_VERSION, evaluation_scope=EVALUATION_SCOPE)


def system_metrics(per_hpt, info):
    """Aggregate one scenario's per-HPT screen results + coupling info (phasor screening only)."""
    H = per_hpt
    n = len(H)
    def frac(key):
        return 100.0 * np.mean([h[key] for h in H]) if n else 0.0
    return dict(
        n_hpt=n,
        load_strict_pct=100.0 * np.mean([h['v_load'] >= C.LOAD_STRICT for h in H]) if n else 0.0,
        load_tol_pct=100.0 * np.mean([h['v_load'] >= C.LOAD_TOL for h in H]) if n else 0.0,
        screen_compliance_pct=100.0 * np.mean([h['survive'] and h['reactive'] for h in H]) if n else 0.0,
        screen_pass_pct=frac('screen_pass'),
        connect_pct=frac('connect'), reactive_pct=frac('reactive'),
        limit_pct=frac('limit'), recover_pct=frac('recover'), survive_pct=frac('survive'),
        minV=info.get('minV'),
        n_affected=sum(1 for v in info.get('all_mean', {}).values() if 0 < v < 0.9),
        total_qvar_kvar=float(sum(h.get('kvar', 0.0) for h in H)),
        converged=bool(info.get('converged')),
        oscillation=bool(info.get('oscillation')),
        wrong_sign=int(info.get('wrong_sign', 0)),
        metrics_version=METRICS_VERSION, evaluation_scope=EVALUATION_SCOPE,
    )


def aggregate(rows):
    """Mean over many scenarios' system_metrics. Device SCREEN rates are over CONVERGED scenarios
    only; `convergence_pct` is reported as a SEPARATE MANDATORY status so non-converged scenarios are
    never silently dropped (a low convergence_pct invalidates the screen rates above it)."""
    conv = [r for r in rows if r.get('converged')]
    def m(key, src=conv):
        vals = [r[key] for r in src if r.get(key) is not None]
        return float(np.mean(vals)) if vals else 0.0
    return dict(
        n_scenarios=len(rows), n_converged=len(conv), n_nonconverged=len(rows) - len(conv),
        convergence_pct=100.0 * len(conv) / max(1, len(rows)),       # SEPARATE mandatory status
        oscillation_pct=100.0 * np.mean([bool(r.get('oscillation')) for r in rows]) if rows else 0.0,
        wrong_sign_scn_pct=100.0 * np.mean([r.get('wrong_sign', 0) > 0 for r in rows]) if rows else 0.0,
        screen_pass_pct=m('screen_pass_pct'), screen_compliance_pct=m('screen_compliance_pct'),
        connect_pct=m('connect_pct'), reactive_pct=m('reactive_pct'),
        limit_pct=m('limit_pct'), recover_pct=m('recover_pct'), survive_pct=m('survive_pct'),
        load_strict_pct=m('load_strict_pct'), load_tol_pct=m('load_tol_pct'),
        minV_mean=m('minV'),
        frt_pass_pct=None,                                          # tombstone — never an FRT rate
        metrics_version=METRICS_VERSION, evaluation_scope=EVALUATION_SCOPE,
    )
