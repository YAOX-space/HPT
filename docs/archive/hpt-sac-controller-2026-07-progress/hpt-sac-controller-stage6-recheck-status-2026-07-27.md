# Stage-6 Recheck Status

Date: 2026-07-27

## Purpose

This document freezes the current evidence before further SAC repair.  It
addresses the recent audit findings:

1. the paper-facing representative matrix should be 12 specialists, not 8;
2. many current actors are BC/DAgger or trajectory specialists rather than
   clearly SAC-improved policies;
3. fixed-center-case evidence is not the same as fault-family evidence;
4. SAC fine-tune contribution must be measured rather than assumed.

## Artifacts

- Target matrix:
  `sac/experiments/stage6_fault_family_experiment_matrix_20260727.csv`
- Executed manifest:
  `sac/experiments/stage6_recheck_manifest_current10_20260727.csv`
- Switch-level result:
  `lab/results/hpt_stage6_recheck_current10_20260727/accepted_specialist_validation.csv`
- Run report:
  `lab/results/hpt_stage6_recheck_current10_20260727/REPORT.md`
- Topology1 HVRT fallback probe:
  `lab/results/hpt_stage6_probe_t1_hvrt_unbalanced_fallback_20260727/accepted_specialist_validation.csv`

## Recheck Command

```powershell
py -3.8 -m sac.validate_hpt_accepted_specialists `
  --manifest sac/experiments/stage6_recheck_manifest_current10_20260727.csv `
  --run-id hpt_stage6_recheck_current10_20260727 `
  --timeout-s 1200
```

## Main Result

The current executable center-case matrix has:

- 10 / 10 switch-level voltage-survival pass;
- 8 / 10 beat-conventional pass;
- 0 / 10 full-FRT pass.

The result is therefore publication-useful for bounded switch-level
voltage-survival claims, but it must not be described as full FRT
certification.

An additional fallback probe used the topology1 balanced-HVRT actor on the two
missing topology1 unbalanced HVRT center cases.  That probe produced:

- 2 / 2 switch-level voltage-survival pass;
- 0 / 2 beat-conventional pass;
- 0 / 2 full-FRT pass.

Combining the current 10-case recheck and this fallback probe, all 12 center
fault types now have a voltage-survival controller path, but only 8 / 12 beat
conventional and the two topology1 HVRT unbalanced rows are not independent
fault-specific specialists.

## Case-Level Status

| Case | Center status | Beat conventional | Full FRT | Current interpretation |
| --- | ---: | ---: | ---: | --- |
| topology1 balanced LVRT | pass | yes | no | keep; candidate for fault-family LVRT pilot |
| topology1 balanced HVRT | pass | yes | no | keep; SAC contribution still unclear |
| topology1 A-LVRT | pass | no | no | repair score/recovery behavior before claiming superiority |
| topology1 AB-LVRT | pass | no | no | repair score/recovery behavior before claiming superiority |
| topology1 A-HVRT | fallback pass | no | no | balanced HVRT actor survives but is not an independent specialist |
| topology1 AB-HVRT | fallback pass | no | no | balanced HVRT actor survives but is not an independent specialist |
| topology2 balanced LVRT | pass | yes | no | keep |
| topology2 balanced HVRT | pass | yes | no | keep; protected-SAC-improved actor is current best |
| topology2 A-LVRT | pass | yes | no | keep; current strong unbalanced LVRT case |
| topology2 AB-LVRT | pass | yes | no | keep; warm-SAC voltage-survival case |
| topology2 A-HVRT | pass | yes | no | keep; include in 12-case representative matrix |
| topology2 AB-HVRT | pass | yes | no | keep; include in 12-case representative matrix |

## What This Fixes

- The claim no longer depends on the stale "8 specialists" framing.
- The current 12-case target is explicit: 10 cases have rechecked
  case-specific evidence and 2 topology1 HVRT unbalanced cases have fallback
  voltage-survival evidence.
- The next experiments can be prioritized by actual weaknesses:
  topology1 A/AB-HVRT missing, topology1 A/AB-LVRT not beating conventional,
  and family-level holdout evidence not yet available.

## What Is Still Not Fixed

- Full FRT still fails for every checked case, mostly due to grid-current,
  recovery, or not-yet-complete reactive-current support evaluation.
- The 10 passing center cases are not yet fault-family specialists.
- BC/DAgger versus protected-SAC contribution is not yet measured across all
  representative cases.
- Independent topology1 A/AB-HVRT center actors do not yet exist.

## Next Repair Queue

1. Train score-improving topology1 A-HVRT 1.10 pu / 60 ms center specialist.
2. Train score-improving topology1 AB-HVRT 1.10 pu / 60 ms center specialist.
3. Recheck `stage6_recheck_manifest_current12_with_t1_hvrt_fallback_20260727.csv`
   only as a center-voltage-survival consolidation, while clearly marking the
   two fallback rows.
4. Run protected-SAC fine-tune contribution tests on the 12 center cases and
   label each as `sac_improved`, `no_sac_gain`, or `sac_degraded`.
5. Start fault-family pilots:
   topology1 balanced LVRT, topology1 A-HVRT, topology2 A-HVRT, and topology2
   AB-HVRT.
