# HPT SAC Stage-4 Paper Evidence Plan

Date: 2026-07-26

## Objective

The Stage-4 objective is to close the remaining evidence gap for the claim:

> Specialist SAC controllers improve switch-level HPT voltage-survival over a strong conventional dq baseline.

This stage does not claim full FRT certification.  Grid current limit, reactive current support, and full GB/T recovery certification remain later work.

## Current Evidence Baseline

The frozen Stage-3 recheck is:

- Run: `lab/results/hpt_promoted_recheck_20260726_round1`
- Cases: 11 promoted specialist cases
- SAC switch-level voltage-survival: 11/11
- Conventional switch-level voltage-survival: 2/11
- SAC beats conventional score: 9/11
- Traditional fail / SAC pass: 9/11
- Traditional pass / SAC fail: 0/11

The two weak rows are:

- `topology1/a_lvrt090_60ms`: SAC survives but conventional has lower score.
- `topology1/ab_lvrt090_60ms`: SAC survives but conventional has lower score.

## Success Criteria

Stage-4 succeeds when the paper can report all of the following with fresh artifacts:

1. A frozen promoted specialist matrix with one validator and one score definition.
2. A boundary matrix showing where conventional passes/fails and where SAC passes/fails.
3. At least one nontrivial region where conventional fails but SAC passes at switch level.
4. A clear weak-case table showing survival-only rows and why they are not claimed as beat-conventional.
5. An ablation table separating teacher, BC/DAgger, and SAC fine-tune contributions for representative cases.
6. A conventional baseline tuning protocol showing the dq controller is not an intentionally weak baseline.
7. A proxy-alignment limitation table, especially for topology1 unbalanced recovery and topology2 energy branch behavior.
8. A reproducibility manifest with actor paths, command lines, run ids, and Git status snapshots.

## Experiment Block A: Freeze And Rebuild Boundary Manifests

Generate a Stage-4 full 630-case manifest from the current promoted recheck actor set:

- LVRT depths: 0.75, 0.80, 0.85, 0.90, 0.95 pu
- HVRT depths: 1.05, 1.10, 1.15, 1.20 pu
- Durations: 40, 60, 80, 120, 200 ms
- Topologies: topology1, topology2
- Phase modes: balanced, A, B, C, AB, BC, CA

Also generate reduced manifests for staged execution:

- reduced-smoke: balanced, A, AB; 0.90 LVRT, 1.10 HVRT; 60 ms
- reduced-boundary: balanced, A, AB; LVRT 0.85/0.90/0.95, HVRT 1.05/1.10/1.15; 40/60/80/120 ms
- weak-focus: topology1 A/AB LVRT 0.85/0.90/0.95 at 60/80/120 ms

## Experiment Block B: Boundary Evidence

Run conventional and SAC on the same switch-level validator:

```powershell
py -3 -m sac.campaigns.run_hpt_voltage_survival_boundary_matrix `
  --manifest sac/experiments/stage4_boundary_manifest_20260726.csv `
  --run-id hpt_stage4_boundary_<tag> `
  --controller-mode current-sac `
  --phase-modes balanced,a,ab `
  --depths <subset> `
  --durations-ms <subset> `
  --timeout-s 2400
```

Promotion rule:

- `survival`: SAC passes all voltage-survival gates.
- `beat-conventional`: SAC passes and has lower score than conventional.
- `boundary-breakthrough`: conventional fails while SAC passes.
- `weak`: both pass but SAC score is higher.
- `diagnostic`: SAC fails or the run is invalid.

## Experiment Block C: Weak-Case Improvement

The weak cases are topology1 unbalanced LVRT.  Do not replace the validated actor with direct BC unless the switch-level validator passes.

Allowed methods:

- protected SAC from the current best actor;
- score-aware behavior anchor using the accepted actor trace;
- smaller learning rate and lower exploration;
- rollback after every failed switch-level candidate.

Avoid:

- blind CEM trajectory replacement;
- proxy-only promotion;
- BC models promoted without switch-level validation.

## Experiment Block D: Ablation

For representative cases, recheck the following under the same validator:

- conventional dq;
- trajectory teacher or hand-designed seed;
- BC;
- BC+DAgger;
- protected SAC fine-tune.

Minimum representative cases:

- topology2 balanced LVRT 0.90 / 60 ms;
- topology2 A-HVRT 1.05 / 60 ms;
- topology1 AB-LVRT 0.90 / 60 ms.

## Experiment Block E: Baseline Tuning

Document the conventional dq tuning budget:

- sag/swell scale;
- recovery damping;
- dq PI gains where exposed;
- chopper threshold and resistance scale;
- topology-specific settings.

The final conventional baseline must be the best validated baseline from the tuning sweep, not the first working configuration.

## Experiment Block F: Proxy Alignment

Proxy alignment must be reported at four levels:

- metric alignment: LV fault/recovery/envelope/DC-link values;
- ranking alignment: candidate ordering versus Simulink score;
- support alignment: whether SAC actions stay inside calibrated support;
- failure alignment: whether proxy and Simulink agree on gate failure reasons.

Known limitation to track:

- topology1 unbalanced recovery score;
- topology2 joint regulating/energy branch DC-link response;
- actor trace BC overshoot and DC-link collapse.

## Execution Order

1. Regenerate Stage-4 manifest from the promoted recheck actors.
2. Run a dry-run/smoke on the reduced-smoke subset.
3. Run reduced-boundary matrix.
4. Summarize boundary breakthrough and weak rows.
5. Improve weak topology1 unbalanced LVRT only if the reduced-boundary result confirms it remains the limiting case.
6. Run ablation and baseline tuning tables.
7. Update paper evidence tables and manuscript claims.

