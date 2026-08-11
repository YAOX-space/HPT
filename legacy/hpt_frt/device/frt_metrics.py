"""frt_metrics.py — frt-v2 ADAPTER for the device (ODE) evaluation pipeline.

The legacy scalar criteria (its own Vdc/iq bool formulas) are REMOVED; all evaluation now flows
through `hpt_frt.common.frt_v2.evaluate` (the single versioned definition).

IMPORTANT — what the averaged-ODE training env can and cannot measure:
  provides : real time t, V1 (=V2p), V2 (=V2n), Vdc, reactive current iq.
  MISSING  : combined/total converter current (id is not modelled) and the negative-seq current I2.
Per the frt-v2 contract these missing MANDATORY measurements are passed as None (NEVER inferred as
zero), so the `limit` and `survive` criteria come back NOT_EVALUATED and `frt_pass` is None
(incomplete) for ODE rollouts. Full FRT certification therefore requires the SWITCHING (Simulink)
harness, not the training ODE. For checkpoint selection during ODE training we expose a clearly
labelled PARTIAL proxy over the AVAILABLE criteria — it is NOT an FRT pass rate and incomplete
scenarios are never counted as certified passes.
"""
from __future__ import annotations
import numpy as np
from hpt_frt.common import frt_v2 as FV2
from .frt_env import TSCALE, effective_fault_dur, fault_sequence

CRITERIA = ('connect', 'reactive', 'limit', 'recover', 'survive')
EVENT_REACTIVE_TOL = 0.04


def _crit(status, worst, t_worst, reason):
    return dict(status=status, passed=(status == FV2.PASS), worst=float(worst),
                t_worst=float(t_worst), reason=reason)


def run_episode(model, env):
    """Roll out one scenario; record REAL time + the measurements the env actually provides.
    Missing measurements (combined current, I2) stay None — they are NOT inferred as zero."""
    obs, _ = env.reset()
    t, V1, V2, Vdc, iq = [], [], [], [], []
    done = False
    while not done:
        a, _ = model.predict(obs, deterministic=True)
        obs, r, term, trunc, info = env.step(a)
        t.append(info['t']); V1.append(info['V2p']); V2.append(info['V2n'])
        Vdc.append(info['Vdc']); iq.append(info['iq'])
        done = term or trunc
    return dict(t=np.asarray(t, float), V1=np.asarray(V1, float), V2=np.asarray(V2, float),
                Vdc=np.asarray(Vdc, float), iq=np.asarray(iq, float),
                i_peak=None, idq_mag=None, i2=None)   # current/I2 not measurable in the averaged ODE


def evaluate_scenario(model, env_cls, scenario):
    """Evaluate one scenario through frt_v2. Returns a CLASSIFICATION dict — never a silent None:
      {'kind': 'rollout_failed'}                          rollout produced < 2 samples
      {'kind': 'unevaluable', 'error': <msg>}             frt_v2.evaluate raised ValueError (structural)
      {'kind': 'evaluated', 'res': <frt_v2 result>}       a full 5-criteria verdict
    ValueError is captured WITH its message (not swallowed), so unevaluable scenarios are visible."""
    env = env_cls([scenario], seed=42, train_mode=False)
    tr = run_episode(model, env)
    if tr['t'].size < 2:
        return {'kind': 'rollout_failed', 'error': f'rollout produced {tr["t"].size} samples'}
    t_fault = float(scenario['t_fault'])
    # The env compresses post-onset dynamics by TSCALE, but frt_v2.evaluate expects real seconds for
    # voltage-time envelopes, response delay, and dwell. Map each sampled ODE timestamp back to its
    # real-time equivalent around the true onset.
    t_eval = t_fault + (tr['t'] - t_fault) / TSCALE
    dur = effective_fault_dur(scenario)
    residual = float(scenario['target_V_pu'])
    try:
        res = FV2.evaluate(t_eval, tr['V1'], scenario['category'], residual,
                           t_fault, dur, V2=tr['V2'], Vdc=tr['Vdc'], iq=tr['iq'],
                           i_peak=tr['i_peak'], idq_mag=tr['idq_mag'], i2=tr['i2'])
    except ValueError as e:
        return {'kind': 'unevaluable', 'error': str(e)}
    tr_eval = dict(tr)
    tr_eval['t'] = t_eval
    _apply_simulink_visible_ode_overrides(res, tr_eval, scenario, t_fault, dur)
    res['response'] = _response_of(tr_eval, t_fault, residual)   # SEPARATE 5 ms metric (never in frt_pass)
    # Vdc-only survival SELECTION signal (audit 2026-06-27): the full `survive` criterion needs I2
    # (absent in the averaged ODE) so it stays NOT_EVALUATED for CERTIFICATION. But the ODE Vdc IS
    # informative (esp. after the Stage-A swell extension), so we expose a Vdc-min survival gate for
    # CHECKPOINT SELECTION only — it de-saturates the proxy so it TRACKS DC-survival improvements
    # (deep-sym drain / swell anti-boost). NOT a certified criterion; never folded into frt_pass.
    vdc_min = float(np.min(tr['Vdc'])) if tr['Vdc'].size else 1.0
    res['vdc_survive_proxy'] = FV2.PASS if vdc_min >= FV2.VDC_LO else FV2.FAIL
    res['vdc_min'] = vdc_min
    if res['vdc_survive_proxy'] == FV2.FAIL and res['survive']['status'] == FV2.NOT_EVALUATED:
        res['survive'] = _crit(FV2.FAIL, FV2.VDC_LO - vdc_min, tr_eval['t'][int(np.argmin(tr['Vdc']))],
                               'Vdc<0.75 visible in ODE; I2 still unavailable')
        _refresh_frt_pass(res)
    return {'kind': 'evaluated', 'res': res}


def _refresh_frt_pass(res):
    statuses = [res[c]['status'] for c in CRITERIA]
    res['frt_pass'] = (False if FV2.FAIL in statuses
                       else (None if FV2.NOT_EVALUATED in statuses else True))


def _apply_simulink_visible_ode_overrides(res, tr, scenario, t_fault, dur):
    """Make the averaged ODE conservative on failure modes proven visible in Simulink.

    The shared frt-v2 evaluator remains measurement-pure. This adapter adds ODE-side diagnostic
    visibility for training/selection: if the scenario event has a clear reactive demand, evaluate
    support against that event severity instead of letting an optimistic ODE voltage lift erase the
    demand; if the rollout terminates before recovery can be assessed, mark recovery as failed.
    """
    _override_reactive_from_event_severity(res, tr, scenario, t_fault, dur)
    _override_recover_from_available_postwindow(res, tr, scenario, t_fault, dur)
    _refresh_frt_pass(res)


def _override_reactive_from_event_severity(res, tr, scenario, t_fault, dur):
    if res['reactive']['status'] == FV2.FAIL:
        return
    t, V1, iq = tr['t'], tr['V1'], tr['iq']
    if iq is None:
        return
    category = scenario['category']
    target = float(scenario['target_V_pu'])
    ft = scenario['fault_type']
    vg_p, _ = fault_sequence(ft, target)
    event_v = target if category == 'HVRT' else vg_p
    in_fault = (t >= t_fault) & (t <= t_fault + dur)
    assess = in_fault & (t >= t_fault + FV2.REACTIVE_DELAY)
    if not assess.any():
        return
    if category == 'LVRT':
        demand_v = np.minimum(V1, event_v)
    else:
        demand_v = np.maximum(V1, event_v)
    ref = np.array([FV2.iq_ref_droop(v) for v in demand_v])
    demanded = assess & (np.abs(ref) > EVENT_REACTIVE_TOL)
    if not demanded.any():
        return
    wrong = np.any((demand_v[assess] < 0.9) & (iq[assess] < -FV2.REACTIVE_SIGN_EPS)) or \
            np.any((demand_v[assess] > 1.1) & (iq[assess] > FV2.REACTIVE_SIGN_EPS))
    if wrong:
        res['reactive'] = _crit(FV2.FAIL, np.nan, t_fault,
                                'wrong sign under event-severity reactive proxy')
        res['reactive']['detail'] = {'event_severity_proxy': True, 'event_v': float(event_v)}
        return
    iq_d, ref_d, t_d = iq[demanded], ref[demanded], t[demanded]
    if category == 'LVRT':
        shortfall = np.maximum(0.0, (ref_d - EVENT_REACTIVE_TOL) - iq_d)
    else:
        shortfall = np.maximum(0.0, iq_d - (ref_d + EVENT_REACTIVE_TOL))
    met = shortfall <= 1e-9
    met_frac = float(np.mean(met))
    if met_frac < FV2.REACTIVE_DWELL:
        j = int(np.argmax(shortfall))
        res['reactive'] = _crit(FV2.FAIL, float(shortfall.max()), float(t_d[j]),
                                f'event-severity support held only {met_frac:.0%}')
        res['reactive']['detail'] = {
            'event_severity_proxy': True,
            'event_v': float(event_v),
            'met_fraction': met_frac,
            'n_demanded': int(demanded.sum()),
        }


def _override_recover_from_available_postwindow(res, tr, scenario, t_fault, dur):
    if res['recover']['status'] == FV2.FAIL:
        return
    t, V1 = tr['t'], tr['V1']
    clear = t_fault + dur
    post = t > clear
    strong_grid = float(scenario.get('scr', 0.0)) >= 8.0
    if post.any() and strong_grid:
        tp, Vp = t[post], V1[post]
        settled = tp >= clear + 0.02
        if settled.any():
            dev = np.abs(Vp[settled] - 1.0)
            j = int(np.argmax(dev))
            if float(dev[j]) > FV2.RECOVER_BAND:
                res['recover'] = _crit(FV2.FAIL, float(dev[j]), float(tp[settled][j]),
                                       'post-clear recovery deviation exceeded band')
                return
    if res['recover']['status'] != FV2.NOT_EVALUATED:
        return
    if post.any():
        tp, Vp = t[post], V1[post]
        tail = Vp[tp >= tp[-1] - min(0.12, max(0.0, tp[-1] - clear))]
        final_dev = float(np.abs(tail - 1.0).max()) if tail.size else float(abs(Vp[-1] - 1.0))
        if final_dev > FV2.RECOVER_BAND:
            res['recover'] = _crit(FV2.FAIL, final_dev, float(tp[-1]),
                                   'short ODE post-window already outside recovery band')
    elif res['connect']['status'] == FV2.FAIL:
        res['recover'] = _crit(FV2.FAIL, abs(float(V1[-1]) - 1.0), float(t[-1]),
                               'rollout ended before recovery after connection failure')


def _response_of(tr, t_fault, residual):
    """5 ms reactive-current response: time for measured iq to reach the EXPLICIT droop reference at
    the fault residual (NOT a whole-window median). NOT_EVALUATED when iq is missing, the reference is
    ~0 (no event), or the sampling is too coarse. Kept entirely separate from frt_pass (audit F)."""
    iq = tr['iq']
    if iq is None:
        return {'response_status': 'NOT_EVALUATED', 'reason': 'iq not measured',
                'rise_time_ms': None, 'settling_time_ms': None, 'meets_5ms': None}
    target = FV2.iq_ref_droop(residual)                     # explicit reference (command), not median
    if abs(target) < FV2.RESP_BAND:
        return {'response_status': 'NOT_EVALUATED', 'reason': 'no reactive event (ref ~ 0)',
                'rise_time_ms': None, 'settling_time_ms': None, 'meets_5ms': None}
    r = FV2.response_metrics(tr['t'], iq, t_fault, target=target)
    if r['status'] == 'insufficient_resolution':
        return {'response_status': 'NOT_EVALUATED', 'reason': 'insufficient time resolution',
                'rise_time_ms': None, 'settling_time_ms': None, 'meets_5ms': None}
    return {'response_status': r['status'], 'rise_time_ms': r['rise_time_ms'],
            'settling_time_ms': r['settling_time_ms'], 'meets_5ms': r['meets_5ms']}


def _evaluation_complete(res):
    """True iff ALL five mandatory criteria were actually evaluated (none NOT_EVALUATED)."""
    return all(res[c]['status'] != FV2.NOT_EVALUATED for c in CRITERIA)


def evaluate_frt(model, scenarios, env_cls, n_eval=None):
    """Aggregate frt-v2 evaluation with HONEST completeness semantics (audit round-4 D).

    A scenario is `complete` ONLY if all five mandatory criteria were evaluated. A scenario with a
    FAIL *and* a NOT_EVALUATED criterion is `decided_fail` (frt_pass False) AND `incomplete` — it is
    NOT counted as complete. `frt_pass_pct` is computed ONLY over complete scenarios (None if zero).
    `partial_proxy_pct` is a CHECKPOINT-SELECTION proxy (NOT an FRT rate); its denominator is ALL
    rolled-out scenarios so unevaluable ones count against it. Unevaluable scenarios are reported
    explicitly (count + reasons). Always carries metrics_version='frt-v2'.

    Counts: n_requested, n_rollout_ok (rolled out >=2 samples), n_rollout_failed, n_unevaluable
    (rolled out but evaluate raised), n_evaluated, n_complete, n_incomplete, n_decided_fail."""
    rng = np.random.default_rng(0)
    scen = list(scenarios)
    idx = (list(range(len(scen))) if n_eval is None
           else rng.choice(len(scen), min(n_eval, len(scen)), replace=False))
    classified = [evaluate_scenario(model, env_cls, scen[int(i)]) for i in idx]
    n_requested = len(classified)
    rollout_failed = [c for c in classified if c['kind'] == 'rollout_failed']
    unevaluable = [c for c in classified if c['kind'] == 'unevaluable']
    evaluated = [c['res'] for c in classified if c['kind'] == 'evaluated']
    rolled = [c for c in classified if c['kind'] in ('unevaluable', 'evaluated')]   # >=2 samples
    n_rolled = len(rolled)

    out = {'metrics_version': FV2.METRICS_VERSION,
           'n_requested': n_requested, 'n_rollout_ok': n_rolled,
           'n_rollout_failed': len(rollout_failed), 'n_unevaluable': len(unevaluable),
           'n_evaluated': len(evaluated),
           'unevaluable_reasons': [c['error'] for c in (rollout_failed + unevaluable)][:20]}

    for c in CRITERIA:
        ev = [r[c] for r in evaluated if r[c]['status'] != FV2.NOT_EVALUATED]
        out[c] = round(100.0 * np.mean([x['status'] == FV2.PASS for x in ev]), 1) if ev else None
        out[c + '_not_eval_pct'] = round(100.0 * np.mean([r[c]['status'] == FV2.NOT_EVALUATED
                                          for r in evaluated]), 1) if evaluated else None

    complete = [r for r in evaluated if _evaluation_complete(r)]
    decided_fail = [r for r in evaluated if r['frt_pass'] is False]
    out['n_complete'] = len(complete)
    out['n_incomplete'] = len(evaluated) - len(complete)
    out['n_decided_fail'] = len(decided_fail)
    # frt_pass over COMPLETE only (a complete scenario has frt_pass in {True, False})
    out['frt_pass_pct'] = round(100.0 * np.mean([1.0 if r['frt_pass'] else 0.0 for r in complete]), 1) \
        if complete else None

    def available_all_pass(res):
        ev = [res[c]['status'] for c in CRITERIA if res[c]['status'] != FV2.NOT_EVALUATED]
        vdc_ok = res.get('vdc_survive_proxy', FV2.PASS) == FV2.PASS   # Vdc-survival selection gate (audit 2026-06-27)
        return bool(ev) and all(s == FV2.PASS for s in ev) and vdc_ok
    # denominator = ALL rolled-out scenarios; unevaluable ones are NOT passes
    n_proxy_pass = sum(1 for r in evaluated if available_all_pass(r))
    out['partial_proxy_pct'] = round(100.0 * n_proxy_pass / n_rolled, 1) if n_rolled else 0.0
    out['vdc_survive_proxy_pct'] = round(100.0 * np.mean(   # Vdc-min≥0.75 rate (selection visibility)
        [1.0 if r.get('vdc_survive_proxy') == FV2.PASS else 0.0 for r in evaluated]), 1) if evaluated else None
    # PROXY HONESTY (audit #8): the proxy ignores NOT_EVALUATED criteria, so a high % can mean
    # "the few evaluable criteria passed", NOT "FRT passed". Report how many of the 5 mandatory
    # criteria were actually evaluable per scenario, and FLAG saturation (a proxy resting on < 3/5
    # criteria must not be read as a pass rate).
    n_crit_eval = [sum(1 for c in CRITERIA if r[c]['status'] != FV2.NOT_EVALUATED) for r in evaluated]
    out['proxy_criteria_evaluated_mean'] = round(float(np.mean(n_crit_eval)), 2) if n_crit_eval else None
    out['proxy_saturated'] = bool(n_crit_eval and np.mean(n_crit_eval) < 3.0)
    out['proxy_note'] = ('partial_proxy_pct ignores NOT_EVALUATED criteria — '
                         f'only {out["proxy_criteria_evaluated_mean"]}/5 mandatory criteria evaluable '
                         f'on average; NOT an FRT pass rate' + (' [SATURATED]' if out['proxy_saturated'] else ''))

    # ── 5 ms response — SEPARATE block, NEVER folded into frt_pass / partial_proxy ──
    resp = [r['response'] for r in evaluated if 'response' in r]
    resp_eval = [x for x in resp if x['response_status'] != 'NOT_EVALUATED']
    out['response'] = {
        'n_evaluated': len(resp_eval),
        'n_not_evaluated': len(resp) - len(resp_eval),
        'meets_5ms_pct': round(100.0 * np.mean([1.0 if x['meets_5ms'] else 0.0 for x in resp_eval]), 1)
                         if resp_eval else None,
        'median_settling_ms': round(float(np.median([x['settling_time_ms'] for x in resp_eval
                                                     if x['settling_time_ms'] is not None])), 3)
                              if any(x['settling_time_ms'] is not None for x in resp_eval) else None,
    }
    return out


def fmt_summary(m):
    """None-safe one-line training-log summary. Reports the PARTIAL proxy used for selection, the
    certified frt_pass rate over COMPLETE scenarios (n/a in the ODE), and per-criterion PASS rates
    (n/e where NOT_EVALUATED). Never prints a misleading 'FRT=' for the proxy."""
    def g(k):
        v = m.get(k)
        return 'n/e' if v is None else f'{v:.0f}'
    frt = 'n/a' if m.get('frt_pass_pct') is None else f"{m['frt_pass_pct']:.0f}%"
    return (f"proxy={m['partial_proxy_pct']:.0f}% vdc_surv={g('vdc_survive_proxy_pct')}% frt_pass={frt} "
            f"[req{m['n_requested']} ok{m['n_rollout_ok']} cmpl{m['n_complete']} "
            f"incmpl{m['n_incomplete']} fail{m['n_decided_fail']} unev{m['n_unevaluable']}] "
            f"(con={g('connect')} rea={g('reactive')} lim={g('limit')} rec={g('recover')} "
            f"sur={g('survive')}) [{m['metrics_version']}]")
