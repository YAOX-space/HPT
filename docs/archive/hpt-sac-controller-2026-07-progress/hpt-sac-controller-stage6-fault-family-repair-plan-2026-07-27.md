# Stage-6 Fault-Family SAC Repair Experiment Plan

Date: 2026-07-27

## Motivation

The current voltage-survival evidence has four weaknesses that must be fixed
before the paper can honestly claim an SAC-based HPT controller:

1. The representative specialist matrix should contain 12 cases, not 8:
   two topologies times balanced LVRT, balanced HVRT, A-phase LVRT,
   AB-phase LVRT, A-phase HVRT, and AB-phase HVRT.
2. The current eight Stage-2 accepted policies are mostly trajectory/BC/DAgger
   actors. Only a subset has clear protected-SAC fine-tune contribution.
3. A specialist should cover a fault family, not just one fixed point such as
   0.90 pu / 60 ms.
4. Protected SAC fine-tune currently shows only a small positive improvement on
   one representative topology2 A-HVRT case. The contribution must be measured
   across multiple cases, not assumed.

This plan repairs those weaknesses without changing the current claim boundary:
switch-level load-side voltage survival first; full grid-code FRT remains a
later phase.

## Fixed Definitions

### Representative 12-case matrix

For each topology, the paper-facing representative matrix shall contain:

| Fault class | Center case |
| --- | --- |
| Balanced LVRT | ABC at 0.90 pu, 60 ms |
| Balanced HVRT | ABC at 1.10 pu, 60 ms |
| A-phase LVRT | A at 0.90 pu, B/C nominal, 60 ms |
| AB-phase LVRT | A/B at 0.90 pu, C nominal, 60 ms |
| A-phase HVRT | A at 1.10 pu, B/C nominal, 60 ms |
| AB-phase HVRT | A/B at 1.10 pu, C nominal, 60 ms |

### Fault-family specialist

A fault-family specialist is accepted only when it is evaluated on more than
the center case. For Stage 6, use this staged family grid:

| Family | Train / tune grid | Holdout grid |
| --- | --- | --- |
| LVRT | depth 0.85/0.90/0.95 pu, duration 40/60/80/120 ms | depth 0.875/0.925 pu, duration 100/160 ms |
| HVRT | depth 1.05/1.10/1.15 pu, duration 40/60/80/120 ms | depth 1.075/1.125 pu, duration 100/160 ms |

Balanced uses ABC. A-phase uses A only. AB-phase uses A/B. B/C/BC/CA remain
rotation-generalization checks after A and AB pass.

### Promotion labels

- `representative_pass`: passes the center case under the current
  switch-level voltage-survival gate.
- `family_pass`: passes the Stage-6 family train grid and holdout grid under
  the current switch-level voltage-survival gate.
- `sac_improved`: protected SAC fine-tune improves over BC/DAgger by at least
  one of:
  - higher holdout pass count without new failures;
  - mean switch-level score improvement >= 1.0;
  - mean switch-level score improvement >= 1% of the BC/DAgger score.
- `no_sac_gain`: protected SAC was attempted and kept feasible, but did not
  meet the improvement threshold.
- `sac_degraded`: protected SAC made the actor fail or worsened the score.

Do not label a policy as SAC-improved merely because its architecture is
SAC-compatible.

## Validation Gate

Every promoted policy must be evaluated in the switch-level Simulink model, not
by proxy alone. The validator must report at minimum:

- `voltage_survival_pass`;
- `envelope_violation_max_pu`;
- `fault_lv_band_violation_max_pu`;
- `recovery_violation_max_pu`;
- `vdc_min`, `vdc_max`;
- `action_max_abs`, `cmd_action_max_abs`;
- `control_score`;
- `full_frt_pass` and full-FRT failure reason, even though full FRT is not the
  Stage-6 promotion target.

For fixed center cases, use strict voltage-survival: no timestep envelope
violation, no fault-window band violation, DC link inside the configured
survival range, and action within limit.

For family cases, report both strict pass rate and worst-case violation. A
family result is publication-strong only if the holdout pass rate is high and
the failure taxonomy is understood.

## Experiment Stages

### Stage 6A: Freeze and audit the 12-case representative matrix

Hypothesis: the current evidence can be reorganized into a cleaner 12-case
matrix, but topology1 A-HVRT and topology1 AB-HVRT are missing and must be
trained or marked as gaps.

Actions:

1. Re-run the current validator on the existing Stage-2 eight cases.
2. Re-run topology2 A-HVRT and topology2 AB-HVRT 1.10 pu / 60 ms using the best
   Stage-4/5 promoted actors.
3. Train or search topology1 A-HVRT and topology1 AB-HVRT 1.10 pu / 60 ms
   using trajectory search -> BC -> DAgger -> switch-level recheck.
4. Write `accepted_specialists_20260727_stage6_12case_voltage_survival.csv`.

Expected outcome:

- 12 rows, all with model path, validator config, score, pass/fail reason, and
  training source.
- If topology1 A/AB-HVRT cannot pass, keep the rows as explicit `gap` entries
  rather than hiding them.

### Stage 6B: Protected-SAC contribution attempt on all 12 center cases

Hypothesis: protected SAC fine-tune can provide local improvement in a subset
of cases, but may not be the main source of performance.

Actions:

1. For each of the 12 center cases, warm-start from the best feasible
   BC/DAgger/trajectory actor.
2. Run short protected SAC chunks with low learning rate, strong behavior
   anchor, support penalty, and switch-level recheck after every chunk.
3. Promote only if the candidate passes and meets the `sac_improved` threshold.
4. Record negative results as `no_sac_gain` or `sac_degraded`.

Expected outcome:

- A paired table: BC/DAgger score versus protected-SAC score for all 12 center
  cases.
- A clear statement of how many cases are genuinely SAC-improved.

### Stage 6C: Fault-family pilot specialists

Hypothesis: a family-level state-feedback policy is needed to avoid
fixed-case overfitting.

Priority families:

1. topology1 balanced LVRT;
2. topology1 A-HVRT;
3. topology2 A-HVRT;
4. topology2 AB-HVRT.

Actions:

1. Build family train and holdout grids using the depth/duration sets above.
2. Generate or search teacher trajectories for the family grid.
3. Train one state-feedback actor per family using aggregated traces,
   BC/DAgger, and optional protected SAC fine-tune.
4. Validate on train and holdout grids.

Expected outcome:

- A table with train pass rate, holdout pass rate, worst-case violation, and
  mean score relative to conventional.
- If a family fails, record whether the failure is LV envelope, recovery
  overboost, DC link, action limit, or current/full-FRT related.

### Stage 6D: Full 12-family expansion

After the pilot families establish a stable recipe, expand the same method to
all 12 topology/fault families.

Acceptance for paper:

- At least the 12 center cases must pass.
- Family-level claims require holdout evidence. Without holdout pass-rate
  evidence, wording must remain "case-specialized" rather than
  "fault-family specialist."

### Stage 6E: Paper figures and trace evidence

Generate paper-ready plots only from accepted center/family policies:

- conventional versus accepted specialist LV RMS overlay;
- Vdc overlay;
- actor actions;
- pass/fail envelope markers;
- fault-window shading.

Do not use the current `simulink_fault_control_plots` gallery as final
accepted-specialist evidence because it uses the current active actor path and
shows DC-link failures in several cases.

## Self-Feedback Loop

After every batch:

1. Summarize pass counts and beat-conventional counts.
2. Rank failures by reason and worst violation.
3. Decide one next intervention:
   - tune trajectory teacher;
   - increase BC/DAgger trace coverage;
   - tighten protected SAC behavior anchor;
   - recalibrate proxy only if switch-level/proxy ranking disagreement blocks
     training.
4. Update the research log and matrix CSV before running the next batch.

## Stop Rules

- Stop protected SAC for a case if two consecutive chunks fail switch-level
  voltage survival after anchor tightening.
- Stop proxy-only training claims if holdout ranking correlation is poor.
- Do not overwrite accepted actors. Export candidates to new model names and
  promote only through manifests.
- Keep failed switch-level runs as diagnostic evidence.

## Immediate Next Commands

Interface dry run:

```powershell
py -3.8 -m sac.smoke_matlab_engine --dry-run
```

Stage-6 fixed-matrix planning artifact:

```powershell
py -3.8 -c "import pandas as pd; df=pd.read_csv('sac/experiments/stage6_fault_family_experiment_matrix_20260727.csv'); print(df.groupby(['stage','status']).size())"
```

The next execution step is Stage 6A: recheck the existing eight, integrate the
topology2 A/AB-HVRT rows from Stage-5, and start topology1 A/AB-HVRT training.
