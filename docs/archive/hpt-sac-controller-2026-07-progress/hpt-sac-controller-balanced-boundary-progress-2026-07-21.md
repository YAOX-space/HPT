# HPT SAC Balanced Boundary Progress - 2026-07-21

## Scope

This run follows the Stage-1/Stage-2 research decision: stabilize
switch-level voltage-survival specialist SAC first, then use those specialists
as evidence against a strong conventional dq baseline.  Full FRT certification
remains a later phase.

Balanced cases covered here:

- topology1 LVRT: 0.90 pu / 60 ms
- topology1 HVRT: 1.10 pu / 60 ms
- topology2 LVRT: 0.90 pu / 60 ms
- topology2 HVRT: 1.10 pu / 60 ms

All cases use `fault_start = 0.080 s`, `fault_settle = 0.020 s`, and
`fault_stop_margin = 0.125 s`.

## What Changed

- Generated a mixed pass/fail conventional boundary matrix with a tuned
  conventional scale profile.  The useful boundary is strongest for HVRT:
  topology1 and topology2 both have conventional pass/fail transitions instead
  of all-pass or all-fail behavior.
- Updated the FRT calibration collector/evaluator vocabulary so the proxy and
  switch-level gate both expose:
  - `fault_lv_band_violation_max_pu`
  - `envelope_violation_max_pu`
  - `recovery_violation_max_pu`
- Recalibrated `sac/hpt_proxy_calibration.json` from the pilot FRT
  matrix and verified near-zero rollout mismatch on the pilot support points.
- Retrained trajectory/state-feedback specialists for:
  - topology1 HVRT
  - topology2 LVRT
  - topology2 HVRT
- Rechecked the existing accepted topology1 LVRT actor under the new timestep
  voltage-survival gate because the fresh topology1 LVRT retrain did not
  reproduce the recovery segment.

## Unified Accepted Matrix

Manifest:

`sac/experiments/accepted_specialists_20260721_balanced.csv`

Unified switch-level validation:

`lab/results/hpt_accepted_balanced_matrix_20260721/accepted_specialist_validation.csv`

Result:

- voltage-survival pass: 4 / 4
- beats conventional: 4 / 4
- full FRT pass: 0 / 4

| case | voltage-survival | beats conventional | policy score | baseline score | fault band | GBT envelope | recovery envelope | Vdc min/max |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| topology1 LVRT 0.90 pu | pass | yes | 102.734 | 112.012 | 0 | 0 | 0 | 769.81 / 877.84 V |
| topology1 HVRT 1.10 pu | pass | yes | 107.185 | 115.581 | 0 | 0 | 0 | 762.98 / 903.57 V |
| topology2 LVRT 0.90 pu | pass | yes | 128.458 | 143.302 | 0 | 0 | 0 | 762.39 / 978.34 V |
| topology2 HVRT 1.10 pu | pass | yes | 113.861 | 159.164 | 0 | 0 | 0 | 762.39 / 999.98 V |

`fault band`, `GBT envelope`, and `recovery envelope` are the corresponding
maximum pu violations.  Zero means every sampled timestep in the assessed
window satisfies that voltage-survival sub-gate.

## Important Diagnostic

The fresh topology1 LVRT retrain did not promote:

`lab/results/hpt_t1_l090_bal_retrain_gate96_20260721/summary.json`

It failed only the recovery timestep envelope:

- `fault_lv_band_violation_max_pu = 0`
- `envelope_violation_max_pu = 0`
- `recovery_violation_max_pu = 0.0415`

The existing accepted topology1 LVRT actor was revalidated successfully:

`lab/results/hpt_accepted_t1_l090_recheck_20260721_after_balanced/accepted_specialist_validation.csv`

Interpretation: topology1 LVRT is controllable in the current switch-level
model, but the latest retraining recipe does not reliably reproduce the
successful recovery-phase action profile.  Keep the revalidated accepted actor
as the Stage-1 specialist, and treat the failed retrain as a training-method
diagnostic.

## What This Does Not Prove Yet

This is not full FRT certification.  The current full-FRT failures are caused
by one or more of:

- grid-current limit;
- reactive-current sign or insufficient sustained reactive-current demand;
- recovery criteria outside the voltage-survival sub-gate.

The current claim is narrower and cleaner:

> For four balanced 60-ms boundary cases, specialist SAC controllers survive
> switch-level voltage envelopes at every sampled timestep and score better
> than the configured conventional dq baseline.

## Unbalanced Fault Next Step

The current balanced evaluator replaces `Grid` with a
`Three-Phase Programmable Voltage Source` and configures a common amplitude
table:

`Amplitudes = [1 1 faultPu faultPu 1 1]`

This naturally creates balanced three-phase sag/swell.  MATLAB inspection shows
the source has a `VariationPhaseA` mask parameter, but it does not provide a
clean A/B/C independent amplitude table.  A robust unbalanced-fault interface
therefore needs a source-model migration, not just a scalar parameter change.

Recommended next source migration:

1. Add an evaluator-side fault descriptor that can represent balanced,
   single-phase, two-phase, and phase-selective sag/swell.
2. Build a new programmable grid source subsystem with independent A/B/C
   voltage commands or a validated sequence-component injection method.
3. Preserve the old scalar `faultPu` path for balanced regressions.
4. Add a smoke test proving that measured `Vgrid_abc` positive/negative
   sequence changes as expected for A-G, B-G, C-G, AB, BC, CA, and ABC faults.
5. Only after that, collect an unbalanced boundary matrix and retrain
   unbalanced trajectory/state-feedback specialists.

## Next Research Actions

1. Promote the 4-case balanced manifest as the current Stage-1 voltage-survival
   matrix.
2. Fix topology1 LVRT retraining reproducibility by adding an optional
   `--init-model` warm-start path or a recovery-window weighted imitation loss.
3. Extend the proxy calibration matrix beyond the pilot 0.90/1.10 support
   points before using proxy-only training claims.
4. Start the unbalanced source migration with a dedicated model smoke test
   before running long SAC campaigns.
