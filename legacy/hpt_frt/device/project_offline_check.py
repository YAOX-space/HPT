"""project_offline_check.py — OFFLINE static check that the deployment-side reactive projection would
intercept the 24 reactive wrong-sign FAILs of SAC mi=14. POST-PROCESSING ONLY:
  - reads lab/results/error_analysis_mi14_failures.csv (existing);
  - does NOT run Simulink, does NOT re-run full-320, does NOT mutate any result;
  - does NOT claim the switching pass rate is fixed.

The per-step iq trajectories are not saved, so this is a PREDICATE-EQUIVALENCE check, not a replay: the
frt-v2 wrong-sign criterion fires on samples where the measured V+ is in a constrained region and iq is
on the wrong side of zero; project_action's trigger is the contrapositive of that same predicate (same
V+, same threshold), so by construction it corrects every wrong-sign sample. Here we verify, per failing
scenario's fault region, that a representative wrong-sign iq (and a full sweep) is projected to the
correct side.

    python -m hpt_frt.device.project_offline_check
writes lab/results/projection_offline_reactive_check.csv + projection_offline_reactive_summary.json
"""
from __future__ import annotations
import csv
import json
from pathlib import Path
import numpy as np
from .safety_projection import project_action, is_wrong_sign, DEFAULTS

ROOT = Path(__file__).resolve().parents[3]
RES = ROOT / 'lab' / 'results'
FAILCSV = RES / 'error_analysis_mi14_failures.csv'


def _region_V1(category, Vg_p):
    """The V+ at which the wrong-sign criterion fired for this scenario's region.
    under-voltage scenarios already have Vg_p < 0.9; the over-voltage (swell_1ph) FAILs trip when the
    MEASURED V+ fluctuates just above 1.1, so test at the boundary-crossing condition."""
    if Vg_p < DEFAULTS['lvrt_lo']:
        return Vg_p, 'undervolt'
    if Vg_p > DEFAULTS['hvrt_hi']:
        return Vg_p, 'overvolt'
    # nominal at/near 1.1 (swell_1ph Vg_p=1.10): the trip is at measured V+>1.1
    return DEFAULTS['hvrt_hi'] + 5e-3, 'overvolt(boundary-crossing)'


def main():
    rows = [r for r in csv.DictReader(FAILCSV.open(encoding='utf-8'))
            if 'reactive' in r['failed_criteria']]
    out = []
    n_intercept = 0
    sweep = np.linspace(-DEFAULTS['iq_cap'], DEFAULTS['iq_cap'], 55)
    for r in rows:
        Vg_p = float(r['Vg_p'])
        V1, region = _region_V1(r['category'], Vg_p)
        wrong_iq = -0.05 if 'under' in region else 0.05      # representative wrong-sign command
        proj, meta = project_action([wrong_iq, 0.0, 0.0], V1_pu=V1)
        before = is_wrong_sign(wrong_iq, V1)
        after = is_wrong_sign(proj[0], V1)
        # invariant over the whole sweep: NO wrong-sign survives projection at this V1
        sweep_ok = all(not is_wrong_sign(project_action([q, 0, 0], V1_pu=V1)[0][0], V1) for q in sweep)
        intercepted = before and (not after) and sweep_ok
        n_intercept += intercepted
        out.append(dict(sid=r['sid'], fault_type=r['fault_type'], category=r['category'], scr=r['scr'],
                        Vg_p=Vg_p, region=region, V1_tested=round(V1, 4),
                        example_wrong_iq=wrong_iq, projected_iq=round(float(proj[0]), 4),
                        wrong_sign_before=before, wrong_sign_after=after,
                        sweep_invariant_ok=sweep_ok, would_be_intercepted=intercepted,
                        projection_reason=meta['reason']))

    csvp = RES / 'projection_offline_reactive_check.csv'
    with csvp.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
        w.writeheader()
        w.writerows(out)

    summary = dict(
        analysis='OFFLINE static predicate-equivalence check — post-processing only',
        disclaimer=('NO Simulink, NO full-320 re-run, NO result mutation. This checks that the '
                    'projection would INTERCEPT the wrong-sign condition; it does NOT claim the '
                    'switching pass rate is fixed (that needs a switching spotcheck of the projected '
                    'controller). NOT_EVALUATED is never counted as PASS; no-fail/effective is not a '
                    'strict grid-code pass rate.'),
        certified_full320_unchanged=dict(residual_SAC_mi14=dict(strict_pass_pct=53.1,
                                         no_fail_effective_pct=89.4, fail_pct=10.6,
                                         true=170, false=34, none=116)),
        n_reactive_fail_scenarios=len(out),
        n_would_be_intercepted=int(n_intercept),
        intercept_rate=f'{n_intercept}/{len(out)}',
        by_region=_count(out, 'region'),
        by_fault_type=_count(out, 'fault_type'),
        survive_cluster_note=('the 10 survive/DC-bus-undershoot FAILs (scr3 + swell_3ph + Vg_p=1.30) are '
                              'NOT addressed by this reactive projection — plan only, see the doc.'))
    jsonp = RES / 'projection_offline_reactive_summary.json'
    jsonp.write_text(json.dumps(summary, indent=1), encoding='utf-8')

    print(f'reactive-FAIL scenarios checked: {len(out)}')
    print(f'would-be intercepted by projection: {n_intercept}/{len(out)}')
    print(f'  by region: {summary["by_region"]}')
    print(f'  by fault_type: {summary["by_fault_type"]}')
    print(f'wrote {csvp}')
    print(f'wrote {jsonp}')


def _count(rows, key):
    c = {}
    for r in rows:
        c[str(r[key])] = c.get(str(r[key]), 0) + 1
    return c


if __name__ == '__main__':
    main()
