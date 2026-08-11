# HPT Direct SAC Progress - 2026-07-17

## Interruption Handling

The full fault-specialist run was interrupted while evaluating
`topology2 / fault / sag_0p75`.

Interrupted run directory:

- `lab/results/hpt_case_specialists_20260717_011726`

The residual Python and MATLAB processes were stopped.  The run produced 11
diagnostic fault-specialist records before interruption.  It should not be
treated as a completed campaign.

## Engineering Cleanup

Added an explicit package map and workflow for `sac`:

- `sac/README.md`
- `sac/experiments/README.md`
- `sac/run_hpt_sac_pipeline.py`

The scripts were not moved yet because current tests, wrappers, and commands
import modules directly from `sac`.  Any future folder migration should
leave compatibility wrappers.

## Current Technical Status

Completed:

- Full switch-level FRT calibration matrix exists for topology1/topology2,
  LVRT depths `0.20/0.50/0.75/0.85/0.90 pu`, and HVRT depths
  `1.10/1.20/1.25/1.30 pu`.
- The FRT proxy is calibrated for independent d-axis regulation and independent
  energy-bridge sweeps.
- FRT teacher traces were generated for 18 topology/fault cases.
- Fault specialist training now uses FRT teacher traces instead of steady traces.
- Grid-side current logging was added to the switch-level models:
  topology1 logs `Igrid_abc` from `MeasMV`, and topology2 logs `Igrid_abc`
  from `MeasPrimary`.
- The comparison and single-case FRT evaluators now derive dq current from
  grid-side voltage/current, using support convention where positive `iq` means
  LVRT reactive support.  Fault reports now include reactive-current support,
  response, shortfall, and grid-current limit metrics.

Partial result from the interrupted run:

- Topology1 LVRT specialists generally improved the switch-level score and Vdc
  survival but still failed full FRT criteria.
- Topology1 HVRT specialists did not consistently improve score.
- Topology2 sag `0.20/0.50 pu` improved some metrics but still failed.

Not completed:

- No fault specialist actor was promoted from the interrupted full run.
- Full GB/T pass/fail certification is no longer blocked by missing grid-side
  current logging, but the implemented dq metric can now explicitly fail cases
  for `reactive_shortfall`, `reactive_wrong_sign`, response delay, or
  `grid_current_limit`.
- Topology2 joint regulating+energy proxy behavior still has a large Vdc gap and
  needs a joint-interaction model before proxy-only training can be trusted.

## Proxy Calibration Update

The resumed full fault-specialist run was stopped at the user's request and the
work shifted back to proxy calibration.

Stopped run:

- `lab/results/hpt_case_specialists_20260717_011726`
- completed `13 / 18` fault specialist records before stop
- no specialist actor was promoted

Proxy changes:

- Added `fault_reg_response_table` from all FRT `reg_sweep` rows, including
  nonzero `reg_q` cases.
- Added `fault_joint_response_table` from FRT `joint_sweep` rows, representing
  the coupled `(reg_d, energy_d, energy_q)` response.
- Updated the proxy environment to use calibrated multi-axis lookup tables for
  fault LV/Vdc targets.
- Updated the FRT proxy-gap measurement so it evaluates the same joint lookup
  model that the environment uses.

Latest matrix-calibrated in-sample gap:

- topology2 `joint_sweep` Vdc MAE improved from about `0.40-0.45 pu` to `0`.
- topology2 `reg_q_sweep` Vdc MAE improved from about `0.26-0.33 pu` to `0`.
- topology1 `joint_sweep` and `reg_q_sweep` are also matched in-sample.

Important limitation:

This is a calibration-matrix in-sample match, not yet a generalization proof.
The next proxy step should create a small holdout or newly sampled topology2
joint-action matrix to verify interpolation between the calibrated points.

Quick leave-one-depth diagnostic:

- Held-out standard depths show that interpolation is still uneven.
- topology2 LVRT `0.50 pu` held out: joint-sweep Vdc MAE about `0.335 pu`.
- topology2 HVRT `1.10 pu` held out: joint-sweep Vdc MAE about `0.230 pu`.
- topology2 LVRT `0.85 pu` and HVRT `1.25 pu` interpolate much better.

Operational implication:

- For the next SAC runs, keep the FRT proxy curriculum on the calibrated
  discrete GB/T depths first.
- Do not claim continuous fault-depth generalization until additional topology2
  joint-action samples or a better learned uncertainty-aware proxy are added.

## Reward Alignment Check

Added:

- `sac/measure_hpt_reward_alignment.py`

Latest outputs:

- `lab/results/hpt_v2_reward_alignment/reward_alignment_full_all_20260717_005608_detail.csv`
- `lab/results/hpt_v2_reward_alignment/reward_alignment_full_all_20260717_005608_summary.csv`
- `lab/results/hpt_v2_reward_alignment/reward_alignment_full_all_20260717_005608_REPORT.md`

Result:

- `20` topology/category/mode groups were checked.
- `13 / 20` groups show useful monotonic alignment.
- `7 / 20` groups are weak under the current criteria.

Important weak groups:

- topology1 HVRT `energy_sweep`: Spearman about `0.169`; proxy reward ranking
  is not reliable here.
- topology1/topology2 `joint_sweep`: Spearman is often acceptable, but top-3
  overlap is `0`; the proxy gets the broad trend but not the best action.
- topology2 HVRT `joint_sweep`: Spearman about `0.716`, proxy top-1 is only
  rank `15 / 36` in switch-level score.

Interpretation:

- The proxy is useful for coarse filtering and directionally ranking many LVRT
  groups.
- It is not yet trustworthy as a standalone SAC training environment for final
  action selection.
- Next training should use proxy candidates only with switch-level promotion
  gates, or switch to offline/DAgger training from Simulink-labeled actions for
  the weak groups.

## Next Engineering Step

Use `run_hpt_sac_pipeline.py` for repeatable launches:

```powershell
py -3.8 -m sac.run_hpt_sac_pipeline --list
py -3.8 -m sac.run_hpt_sac_pipeline --stage fault-specialists-smoke
```

Before another full 8-hour campaign, the next code work should be:

1. Add grid-side current/reactive-current logging to the switch-level evaluator.
2. Validate the new joint lookup proxy on held-out or newly sampled topology2
   joint regulating/energy actions.
3. Resume specialist training only after a short smoke case proves the new
   scoring and proxy gap are consistent.

## Literature-Driven Method Update

Added:

- `docs/specs/algorithms/hpt-sac-controller/hpt-sac-offline-rl-literature-and-method.md`
- `sac/train_hpt_reward_correction.py`

Reference conclusion:

- Offline RL papers in `references/week6` point to a conservative data-first
  route when rollouts are expensive and the proxy is biased.
- SAC robustness papers in `references/week5` are relevant, but they do not
  remove the need to align the reward source with switch-level Simulink.
- The current practical fix is therefore reward correction from switch-level
  labels before more proxy SAC.

Reward-correction run:

- Output directory:
  `lab/results/hpt_v2_reward_correction/reward_correction_20260717_025529`
- Selected model: `extra_trees`
- Training rows: `656`
- Held-out action rows: `172`
- Feature count: `35`

Held-out action evaluation:

| Metric | Baseline proxy | Corrected proxy |
| --- | ---: | ---: |
| Weak groups | `3 / 20` | `0 / 20` |
| Mean Spearman | `0.852` | `0.992` |
| Mean top-k overlap fraction | `0.833` | `0.967` |
| Mean proxy-top1 switch percentile | `0.088` | `0.021` |

Full matrix sanity check:

| Metric | Baseline proxy | Corrected proxy |
| --- | ---: | ---: |
| Weak groups | `7 / 20` | `1 / 20` |
| Mean Spearman | `0.782` | `0.975` |
| Mean top-k overlap fraction | `0.467` | `0.850` |
| Mean proxy-top1 switch percentile | `0.155` | `0.025` |

Interpretation:

- The correction model substantially repairs action ranking on the current
  switch-level FRT matrix.
- It should now be used for candidate/teacher ranking and specialist training
  inputs.
- It is not a final proof of controller success.  Any actor trained with this
  corrected signal still needs switch-level validation.

## Conventional-Control Baseline Start

Added:

- `simulink/evaluators/eval_hpt_v2_control_comparison.m`
- `sac/summarize_hpt_control_comparison.py`

Purpose:

- Move toward the real research target: compare SAC against a traditional
  dq/voltage-loop style controller on the same switch-level HPT plants.
- Keep the plant, PWM, converter limits, topology, and fault definitions
  identical across no-control, conventional, and SAC modes.

Implemented control modes:

- `no_control`: `hpt_sac_enable = 0`, energy bridge disabled.
- `conventional_dq`: current HPTSACController `policy_mode = 0` conventional-like
  voltage/DC-link feedback branch. This is a runnable baseline v0, not yet the
  final paper-grade PLL+dq+PI controller.
- `sac_actor_raw_guard0`: SAC actor with execution guard disabled.

Important repair:

- `simulink/hpt_sac_actor_weights.mat` was found incomplete; it only
  contained five actor variables and missed `mu_*`, `act_*`, `n_obs`, and
  `n_act`.
- The broken file was backed up locally and the complete
  `hpt_sac_actor_weights_step4_pass_20260715.mat` file was restored as the
  steady actor weight file so MATLAB Function compilation can succeed.

Smoke result:

- Input:
  `lab/results/hpt_v2_control_comparison/control_comparison_topology1_fault_sag_0p90_20260717_033421.csv`
- Summary:
  `lab/results/hpt_v2_control_comparison/control_comparison_topology1_fault_sag_0p90_20260717_033421_REPORT.md`

| Mode | Score | Pass | LV recovery | Vdc min |
| --- | ---: | --- | ---: | ---: |
| no_control | `101.583` | false | `204.405 V` | `709.352 V` |
| conventional_dq | `109.791` | false | `191.047 V` | `722.911 V` |
| sac_actor_raw_guard0 | `164.422` | false | `201.956 V` | `121.095 V` |

Interpretation:

- Current SAC does not beat the conventional baseline in this smoke case.
- Current conventional baseline v0 also does not beat no-control, so it needs
  tuning or replacement by a stronger PLL+dq+PI baseline before the final paper
  comparison.
- The comparison infrastructure is now in place; the next work is controller
  baseline tuning and then SAC training against that baseline.

## Strong Conventional Baseline Update

Correction:

- The old `no_control` label was misleading. In the current Simulink wiring,
  `hpt_sac_enable = 0` selects the existing physical
  `VoltageRegulator`/`EnergyController` path, not all-converters-off.
- The comparison mode is now named `legacy_conventional`; `no_control` remains
  only as a backward-compatible alias.

Updated modes:

- `legacy_conventional`: original model-workspace PLL/dq/PI controller path.
- `conventional_dq`: stronger topology-aware traditional baseline.
  - topology1: tuned physical `VoltageRegulator`/`EnergyController`.
  - topology2: calibrated rule/dq current-loop fallback, because the physical
    topology2 `EnergyController` DC-link outer loop currently collapses the DC
    link around the parallel-coupled energy port.
- `rule_fallback`: explicit access to the rule/dq fallback branch for diagnosis.
- `sac_actor_raw_guard0`: SAC actor with execution guard disabled.

Instrumentation repair:

- `action_max_abs` now uses the actual selected bridge commands
  `Mref6_cmd` and `Menergy_cmd`, instead of the unselected internal
  `HPTSAC_action` signal.
- For legacy/conventional physical-controller modes, reported action means are
  derived from selected modulation commands and `Energy_dbg`, so the CSV no
  longer reports unused HPTSAC action values as if they were applied.

Topology1 `sag_0p90` smoke:

- Result CSV:
  `lab/results/hpt_v2_control_comparison/control_comparison_topology1_fault_sag_0p90_20260717_040637.csv`

| Mode | Score | Pass | LV fault | LV recovery | Vdc min |
| --- | ---: | --- | ---: | ---: | ---: |
| legacy_conventional | `101.583` | false | `201.678 V` | `204.405 V` | `709.352 V` |
| conventional_dq | `101.005` | false | `202.283 V` | `206.689 V` | `754.297 V` |
| rule_fallback | `109.791` | false | `182.629 V` | `191.047 V` | `722.911 V` |
| sac_actor_raw_guard0 | `164.422` | false | `184.194 V` | `201.956 V` | `121.095 V` |

Topology2 `sag_0p90` smoke:

- Result CSV:
  `lab/results/hpt_v2_control_comparison/control_comparison_topology2_fault_sag_0p90_20260717_040454.csv`

| Mode | Score | Pass | LV fault | LV recovery | Vdc min |
| --- | ---: | --- | ---: | ---: | ---: |
| legacy_conventional | `174.977` | false | `201.839 V` | `196.762 V` | `0.084 V` |
| conventional_dq | `113.448` | false | `181.702 V` | `203.965 V` | `735.011 V` |
| rule_fallback | `113.448` | false | `181.702 V` | `203.965 V` | `735.011 V` |
| sac_actor_raw_guard0 | `137.399` | false | `213.672 V` | `250.645 V` | `729.396 V` |

Interpretation:

- The strong baseline now beats SAC raw in both topology1 and topology2
  `sag_0p90` switch-level smoke cases.
- topology1 improved by tuning the real physical conventional path.
- topology2 exposed a structural issue in the physical `EnergyController`: the
  DC-link loop drives the wrong effective direction under sag. A sign/polarity
  sweep showed simple bridge polarity flips do not fix it; the stable
  traditional baseline therefore uses the existing rule/dq fallback branch.
- Fault `pass=false` is no longer hidden behind missing current measurement:
  topology1 `sag_0p90` conventional smoke is shallow enough to report
  `not_evaluated_no_sustained_reactive_demand_after_delay`, while topology2
  `sag_0p90` conventional smoke reports `reactive_shortfall` and
  `grid_current_limit`.
- A deeper topology1 `sag_0p75` conventional smoke confirms that the new
  reactive-current evaluator can pass independently: `grid_iq_mean_pu=0.226`,
  `grid_iq_ref_mean_pu=0.283`, `gbt_reactive_status=pass`; that case still
  fails because of recovery and DC-link survival.

## Proxy Grid-Current Reward Update

Implemented after adding `Igrid_abc` to the switch-level models:

- `collect_hpt_v2_frt_calibration_matrix.m` now records grid-side positive
  sequence voltage, dq current, reactive-current reference, reactive shortfall,
  and grid-current peak metrics into both aggregate rows and 2-ms trace rows.
- `calibrate_hpt_frt_proxy_from_matrix.py` carries those grid-current metrics
  into the FRT proxy calibration JSON tables.
- `hpt_voltage_sac_env.py` keeps the 24-D actor interface unchanged, but the
  proxy reward/info now includes `grid_iq`, `grid_iq_ref`, reactive shortfall,
  wrong-sign reactive response, and grid-current limit penalties.
- `measure_hpt_frt_proxy_gap.py` and `measure_hpt_reward_alignment.py` now
  evaluate proxy-vs-Simulink alignment on grid-current metrics, not only
  LV/Vdc.
- `build_hpt_frt_teacher_traces.py` and `train_hpt_case_specialists.py` now
  penalize teacher/candidate actions that fail reactive-current support or
  exceed grid-current limits.

Validation:

- Python SAC modules compile successfully.
- A proxy smoke rollout still returns a 24-D observation and now reports the
  new grid-current info fields.
- MATLAB `checkcode` on the FRT matrix collector shows only style/deprecation
  warnings, not syntax errors.

Remaining required step:

- Re-run at least a pilot FRT calibration matrix with the updated Simulink
  models, then regenerate `sac/hpt_proxy_calibration.json`.  Until
  that JSON is refreshed, the proxy falls back to a simple physics estimate for
  grid-current reward terms.

## Proxy/Simulink Alignment Repair

Completed a fresh pilot matrix with the new grid-current instrumentation:

- `frt_calibration_matrix_pilot_topology1_20260717_050602.csv`
- `frt_calibration_matrix_pilot_topology2_20260717_050831.csv`
- merged pilot matrix:
  `frt_calibration_matrix_pilot_both_20260717_merged.csv`

Fixes made after comparing proxy against Simulink:

- Static lookup/reward alignment was expanded from LV/Vdc mean only to the full
  evaluator metric set: LV fault/recovery/peak/min, Vdc mean/min/max, action
  bound, grid `iq`, `iq_ref`, reactive shortfall, wrong-sign reactive response,
  and grid-current peak.
- FRT calibration JSON export now keeps these metrics in baseline, reg, energy,
  and joint tables.
- Proxy reward alignment now uses the same aggregate score terms as the
  switch-level evaluator.
- `HPTVoltageSACEnv` now has explicit `calibration_mode`, so the proxy can
  reproduce `baseline`, `reg_sweep`, `energy_sweep`, or `joint_sweep` rows
  instead of mixing enable modes.
- The default direct-SAC environment no longer applies execution-layer action
  projection.  Projection is now optional through `action_projection_enable`.
- Out-of-support interpolation no longer silently clamps actions to table
  boundaries; a tolerance was added only for float32 roundoff.
- Added `sac/verify_hpt_proxy_rollout_alignment.py` to verify the
  actual SAC environment rollout against Simulink matrix rows.

Pilot alignment results:

- Static proxy gap: all reported LV/Vdc/grid-current metrics match the merged
  pilot Simulink matrix with zero CSV-level error.
- Reward alignment: every multi-row group has Spearman `1.0`, top-k overlap
  `1.0`, and proxy reward equals switch-level reward exactly on the pilot
  matrix.
- SAC environment rollout alignment on all 52 pilot rows:
  - LV mean MAE `6.63e-10 pu`, max `4.56e-09 pu`
  - Vdc mean MAE `4.10e-10 pu`, max `7.12e-09 pu`
  - grid `iq` MAE `7.88e-10 pu`, max `6.67e-09 pu`
  - grid `iq_ref` MAE `3.00e-10 pu`, max `2.92e-09 pu`
  - grid current peak MAE `4.26e-10 pu`, max `2.86e-09 pu`

Interpretation:

- On the calibrated pilot cases, the proxy now faithfully reproduces the
  switch-level input/output/reward relationship, including FRT reactive-current
  terms.
- This is still an in-sample pilot result.  A full matrix or a holdout matrix is
  required before restarting long SAC training and claiming generalization
  across all GB/T depths and unseen joint actions.

## Full/Expanded Proxy Alignment

Completed the full switch-level FRT calibration matrix with grid-current
metrics:

- `frt_calibration_matrix_full_topology1_20260717_054605.csv`
- `frt_calibration_matrix_full_topology2_20260717_060226.csv`
- merged full matrix:
  `frt_calibration_matrix_full_both_20260717_merged_grid_full.csv`

Initial full static alignment exposed one proxy bug:

- `energy_sweep` was using an additive d-axis plus q-axis approximation.
- Simulink showed coupled `m_energy_d/m_energy_q` behavior, especially in
  topology2.
- Fixed both `measure_hpt_frt_proxy_gap.py` and `hpt_voltage_sac_env.py` to
  use a two-axis energy response table first, with the old additive estimate
  only as fallback.

Initial full environment-rollout alignment exposed two environment bugs:

- Deep LVRT rows were terminating before the fault assessment window, yielding
  missing LV/grid-current reward feedback.
- Vdc was clipped to `[0.05, 1.30] pu`, hiding real Simulink DC-link collapse or
  overvoltage errors.
- In switch-calibrated fault scenarios, the environment now runs to
  `stop_time`, allows Vdc over `[0.0, 2.0] pu`, caches calibrated metric lookup,
  and skips expensive teacher-table lookup when `teacher_prior_weight == 0`.

Full in-sample results after fixes:

- Static proxy gap on all 828 full rows: zero CSV-level error for LV, Vdc,
  energy current, grid `iq`, reactive shortfall, and grid-current peak.
- Reward alignment on all 20 topology/category/mode groups: Spearman `1.0`,
  Kendall `1.0`, top-3 overlap `1.0`, proxy top-1 switch rank `1`.
- Environment rollout alignment on all 828 full rows:
  - LV mean MAE `2.51e-09 pu`, max `2.72e-08 pu`
  - Vdc mean MAE `5.11e-09 pu`, max `1.27e-07 pu`
  - grid `iq` MAE `2.18e-09 pu`, max `8.10e-08 pu`
  - grid `iq_ref` MAE `8.64e-10 pu`, max `1.97e-08 pu`
  - grid current peak MAE `1.73e-09 pu`, max `4.05e-08 pu`

Then added a true holdout matrix with unseen depths/actions:

- `sag_0p65`, `swell_1p15`
- intermediate regulating/energy/joint actions such as `reg_q=0.20`,
  `energy_d=0.10/0.30`, `energy_q=0.10`, and joint `reg_d=0.30/0.50`
- `frt_calibration_matrix_holdout_all_20260717_062807.csv`

The full-only proxy did not generalize reliably to this holdout, especially
topology2 Vdc and grid `iq`.  The fix was to expand the calibration surface:

- Expanded matrix:
  `frt_calibration_matrix_expanded_full_holdout_20260717.csv`
- Expanded default calibration:
  `sac/hpt_proxy_calibration.json`

Expanded calibration validation:

- Static proxy gap on all 880 rows: zero CSV-level error for all reward-driving
  fields.
- Reward alignment on all 20 groups: Spearman `1.0`, Kendall `1.0`, top-3
  overlap `1.0`, proxy top-1 switch rank `1`.
- Environment rollout alignment on all 880 rows:
  - LV mean MAE `2.50e-09 pu`, max `2.72e-08 pu`
  - Vdc mean MAE `5.13e-09 pu`, max `1.27e-07 pu`
  - grid `iq` MAE `2.18e-09 pu`, max `8.10e-08 pu`
  - grid `iq_ref` MAE `8.64e-10 pu`, max `1.97e-08 pu`
  - grid current peak MAE `1.74e-09 pu`, max `4.05e-08 pu`

Interpretation:

- The proxy is now trustworthy on the expanded calibrated FRT surface and can
  correctly expose LV error, DC-link error, reactive-current error,
  wrong-direction support, current-limit stress, and reward terms to SAC.
- The holdout failure showed that sparse interpolation alone is not enough for
  topology2.  Future SAC training should either constrain exploration to the
  calibrated action/depth envelope or keep adding Simulink samples where the
  actor proposes high-value off-surface actions.

## Conventional Boundary Matrix

Added a dedicated traditional-control boundary sweep so SAC has a meaningful
baseline to beat rather than comparing against an all-pass or all-fail setup.

Implementation:

- `simulink/sweeps/sweep_hpt_v2_conventional_boundary.m`
  - LVRT / undervoltage depths: `0.995, 0.990, 0.980, 0.950, 0.920,
    0.900, 0.880, 0.850, 0.800, 0.750, 0.700, 0.650, 0.600,
    0.500, 0.350, 0.200 pu`
  - HVRT / overvoltage depths: `1.005, 1.010, 1.020, 1.050, 1.080,
    1.100, 1.120, 1.150, 1.180, 1.200, 1.250, 1.300 pu`
  - Durations: `40 ms`, `80 ms`, `120 ms`, `200 ms`
- `simulink/evaluators/eval_hpt_v2_control_comparison.m`
  - supports custom fault matrices and per-row duration
  - reports two pass levels:
    - `voltage_survival_pass`: fault-window LV RMS, recovery-window LV RMS,
      Vdc, and action magnitude stay inside survival limits
    - `full_frt_pass`: full GB/T-style FRT gate including recovery,
      grid-current limit, and reactive-current response
- `sac/summarize_hpt_conventional_boundary.py`
  - summarizes boundary by topology, LVRT/HVRT, and duration

Result files:

- Raw switch-level matrix:
  `lab/results/hpt_v2_control_comparison/control_comparison_all_fault_all_conventional_boundary_20260717_074421.csv`
- Survival boundary report:
  `lab/results/hpt_v2_control_comparison/control_comparison_all_fault_all_conventional_boundary_20260717_074421_voltage_survival_BOUNDARY_REPORT.md`
- Full-FRT boundary report:
  `lab/results/hpt_v2_control_comparison/control_comparison_all_fault_all_conventional_boundary_20260717_074421_full_frt_BOUNDARY_REPORT.md`

Measured conventional survival boundary:

- topology1 LVRT:
  - `40 ms`: pass to `0.80 pu`, fail at `0.75 pu`
  - `80 ms`: pass to `0.75 pu`, fail at `0.70 pu`
  - `120 ms`: pass to `0.75 pu`, fail at `0.70 pu`
  - `200 ms`: pass to `0.80 pu`, fail at `0.75 pu`
- topology1 HVRT:
  - `40 ms`: pass to `1.18 pu`, fail at `1.20 pu`
  - `80 ms`: pass to `1.15 pu`, fail at `1.18 pu`
  - `120 ms`: pass to `1.15 pu`, fail at `1.18 pu`
  - `200 ms`: pass to `1.12 pu`, fail at `1.15 pu`
- topology2 LVRT:
  - `40 ms`: pass to `0.98 pu`, fail at `0.95 pu`
  - `80 ms`: pass to `0.95 pu`, fail at `0.92 pu`
  - `120 ms`: fail from `0.995 pu`
  - `200 ms`: fail from `0.995 pu`
- topology2 HVRT:
  - `40 ms`: pass to `1.10 pu`, fail at `1.12 pu`
  - `80 ms`: pass to `1.10 pu`, fail at `1.12 pu`
  - `120 ms`: pass to `1.10 pu`, fail at `1.12 pu`
  - `200 ms`: pass to `1.10 pu`, fail at `1.12 pu`

The refined matrix achieved mixed pass/fail behavior in `14 / 16`
topology/category/duration groups.  The only all-fail groups are topology2
LVRT at `120 ms` and `200 ms`, which fail from even `0.995 pu` because Vdc
collapses in this conventional schedule.

Full-FRT result:

- `full_frt_pass = 0` for all 16 topology/category/duration groups.
- Main blockers are recovery error, grid-current limit, and reactive-current
  direction/response.  Therefore this traditional baseline is useful for a
  two-stage SAC goal:
  1. beat the measured `voltage_survival_pass` boundary;
  2. then optimize the stricter `full_frt_pass` terms that conventional control
     currently cannot satisfy.

## Full-Action Literature Plan And Boundary Dataset

Added a new literature-driven plan and reference bundle for the direct
full-action SAC route:

- `references/week7_full_action_sac/`
- `references/week7_full_action_sac/README.md`
- `references/week7_full_action_sac/literature_notes_zh.md`
- `docs/specs/algorithms/hpt-sac-controller/hpt-sac-controller-full-action-sac-literature-plan-2026-07-17.md`

Main conclusion:

- The final actor should still directly output
  `[m_reg_d, m_reg_q, m_energy_d, m_energy_q]`.
- Plain proxy SAC is not the right next step because actor drift and
  out-of-support actions remain the dominant failure mode.
- The next training route should use behavior-constrained or offline RL ideas:
  BC warm start, TD3+BC/IQL/AWAC-style data use, support penalties, and
  switch-level promotion gates.

Implemented:

- `sac/build_hpt_boundary_full_action_dataset.py`
  - merges the conventional boundary sweep and expanded switch-level FRT matrix
    into a shared full-action dataset contract;
  - exports CSV, NPZ, manifest, report, and experiment metadata;
  - includes 4-D actions, LV/Vdc/grid-current metrics, survival score,
    `voltage_survival_pass`, and `full_frt_pass`.
- `sac/run_hpt_sac_pipeline.py`
  - added `boundary-full-action-dataset`;
  - added `boundary-bc-reproduction-smoke`;
  - added `boundary-sac-regularized-smoke`.
- `sac/train_hpt_fault_specialists_vs_baseline.py`
  - added SAC hyperparameter controls: learning rate, batch size, buffer size,
    learning starts, and entropy coefficient;
  - added proxy penalty controls for calibrated support, survival, reactive
    current, and grid-current limit;
  - added periodic behavior-anchor BC updates during SAC training.

Dataset smoke:

- Output:
  `data/hpt_boundary_full_action/smoke_boundary_full_action/`
- Rows: `621`
  - conventional boundary rows: `30`
  - switch-matrix candidate rows: `591`
- Role counts:
  - `conventional_last_pass`: `14`
  - `conventional_first_fail`: `14`
  - `conventional_all_fail_start`: `2`
  - switch candidates from baseline/reg/energy/joint sweeps: `591`

BC-only reproduction smoke:

- Command stage: `boundary-bc-reproduction-smoke`
- Output:
  `lab/results/hpt_boundary_bc_reproduction_smoke/`
- Case group: topology1 LVRT, `80 ms`, near conventional boundary
  (`0.75 pu` pass, `0.70 pu` fail).
- Result:
  - conventional survival pass: `1 / 2`
  - BC actor proxy survival pass: `1 / 2`
  - beat conventional: `0 / 2`
- Interpretation:
  - BC warm start preserves the conventional pass/fail boundary.
  - It does not beat conventional, which is expected because this is only a
    reproduction gate.

Behavior-anchored SAC smoke:

- Command stage: `boundary-sac-regularized-smoke`
- Output:
  `lab/results/hpt_boundary_sac_regularized_smoke/`
- Settings:
  - `1000` SAC steps;
  - `80` BC warm-start epochs;
  - `teacher_prior_weight=30`;
  - `learning_rate=1e-4`;
  - `ent_coef=auto_0.1`;
  - behavior anchor: `20` BC epochs every `100` SAC steps.
- Result:
  - conventional survival pass: `1 / 2`
  - behavior-anchored SAC proxy survival pass: `0 / 2`
  - beat conventional: `0 / 2`
- Failure mode:
  - actor still drifts to near-saturated regulating commands;
  - `proxy_ood_action` appears in both boundary cases;
  - Vdc collapses in the proxy evaluation;
  - final behavior-anchor action MSE is large, showing that intermittent BC is
    not strong enough once SAC has pushed the actor into a bad region.

Operational conclusion:

- Do not launch long behavior-anchored SAC runs with the current SB3 setup.
- The next implementation should either:
  1. train a true offline baseline first, especially TD3+BC/IQL, on the new
     boundary full-action dataset; or
  2. implement a real custom SAC actor loss with behavior regularization inside
     every actor update, not only periodic BC repair.

## Offline Full-Action Baselines

Implemented a stronger offline/behavior-constrained route:

- `sac/train_hpt_offline_full_action_baselines.py`
  - loads the boundary full-action dataset;
  - trains `td3_bc_style`, `awac_style`, and `bc_conventional` contextual
    actors;
  - maps fault/topology context directly to
    `[m_reg_d, m_reg_q, m_energy_d, m_energy_q]`;
  - evaluates the constant action through the calibrated HPT proxy gate;
  - exports case results, model checkpoints, reports, metadata, and
    active-sampling candidates.
- `sac/run_hpt_sac_pipeline.py`
  - added `offline-full-action-smoke`;
  - added `offline-full-action-boundary`;
  - added `offline-full-action-group-boundary`.

Important implementation note:

- The current boundary dataset is a scenario/action/result table, not a
  per-step transition replay buffer.  Therefore the implemented methods are
  honestly named TD3+BC-style and AWAC/IQL-style contextual offline baselines,
  not literal transition-based TD3 or IQL.  A literal implementation still
  requires per-step `(s, a, r, s')` traces.

Smoke result:

- Output: `lab/results/hpt_offline_full_action_smoke/`
- Group: topology1 LVRT, `80 ms`
- Result:
  - `td3_bc_style`: pass `1 / 2`, beat `0 / 2`, improved score `1 / 2`;
  - `awac_style`: pass `1 / 2`, beat `0 / 2`, improved score `1 / 2`;
  - `bc_conventional`: pass `1 / 2`, beat `0 / 2`.
- Diagnosis:
  - the original candidate selection tried to imitate failing switch-matrix
    candidates on a case where conventional already passed;
  - fixed by using a candidate as teacher only when it improves score or turns a
    conventional fail into a pass.

Pooled boundary result:

- Output: `lab/results/hpt_offline_full_action_boundary/`
- Cases: `30`
- Result:
  - pooled `td3_bc_style`: pass `4 / 30`, beat `0 / 30`;
  - pooled `awac_style`: pass `13 / 30`, beat `5 / 30`;
  - pooled `bc_conventional`: pass `14 / 30`, beat `0 / 30`.
- Diagnosis:
  - pooled AWAC learns useful topology1/HVRT actions but loses one conventional
    pass case, mainly due to topology2 DC-link behavior contaminating the
    shared action surface.

Group-specialist boundary result:

- Output: `lab/results/hpt_offline_full_action_group_boundary/`
- Group specialists trained by `(topology, category, duration)`.
- Viable proxy-gate specialists:
  - `topology1_hvrt_40ms/awac_style`: baseline pass `1 / 2`, policy pass
    `2 / 2`, beat `1 / 2`;
  - `topology1_hvrt_80ms/awac_style`: baseline pass `1 / 2`, policy pass
    `2 / 2`, beat `2 / 2`;
  - `topology1_hvrt_120ms/awac_style`: baseline pass `1 / 2`, policy pass
    `1 / 2`, beat `1 / 2`;
  - `topology1_hvrt_200ms/awac_style`: baseline pass `1 / 2`, policy pass
    `1 / 2`, beat `1 / 2`.
- Example beat cases:
  - `hvrt_040ms_1p200pu`: conventional fail, AWAC proxy pass;
  - `hvrt_080ms_1p180pu`: conventional fail, AWAC proxy pass;
  - `hvrt_080ms_1p150pu`: conventional pass, AWAC lower score;
  - `hvrt_120ms_1p150pu`: conventional pass, AWAC lower score;
  - `hvrt_200ms_1p120pu`: conventional pass, AWAC lower score.

Current conclusion:

- Per-group AWAC-style offline control is the first route that shows a real
  proxy-gate advantage over conventional DQ.
- The success is currently local: topology1/HVRT only.
- topology1/LVRT improves score but does not convert fail to pass.
- topology2 is still dominated by DC-link failures; active-sampling candidates
  were exported for those cases.
- None of these actors is a final claim yet.  The next gate is switch-level
  validation of the viable topology1/HVRT AWAC specialists.

## Offline Full-Action Switch-Level Gate

Implemented:

- `sac/validate_hpt_offline_actions_switchlevel.py`
  - promotes proxy-beating offline full-action rows into switch-level Simulink;
  - injects the candidate action as fixed
    `[m_reg_d, m_reg_q, m_energy_d, m_energy_q]`;
  - runs the same case against `conventional_dq` and `fixed_action`;
  - writes candidate CSVs, MATLAB logs, summary JSON, and a report.
- `simulink/evaluators/eval_hpt_v2_control_comparison.m`
  - added `fixed_action` mode;
  - passes `hpt_compare_fixed_action` into the model workspace so the existing
    controller fixed-policy path can be used without changing plant topology.
- `sac/run_hpt_sac_pipeline.py`
  - added `offline-full-action-switch-validate`.

Bug fix:

- MATLAB CSV pass fields can be `0/1`, while the first report parser only
  treated literal `true` as pass.  The switch-validation script now parses
  `0/1/true/false` consistently and can recompute an existing run with
  `--recompute-run-dir`.

Validated run:

- Output:
  `lab/results/hpt_offline_full_action_switch_validation_v2/`
- Source proxy candidates:
  `lab/results/hpt_offline_full_action_group_boundary/case_results.csv`
- Selected candidates: topology1/HVRT AWAC rows that beat conventional in the
  proxy gate.

Switch-level result after corrected counting:

| Metric | Result |
| --- | ---: |
| MATLAB completed | `5 / 5` |
| Conventional voltage-survival pass | `3 / 5` |
| Fixed-action AWAC voltage-survival pass | `1 / 5` |
| Fixed-action AWAC beats conventional | `1 / 5` |

Confirmed switch-level beat:

- `topology1_hvrt_200ms/awac_style`, `hvrt_200ms_1p120pu`
  - conventional pass: `1`
  - AWAC fixed-action pass: `1`
  - conventional score: `153.521`
  - AWAC fixed-action score: `148.973`
  - requested action:
    `[0.086, -0.007, 0.075, 0.027]`

Failures:

- The other four proxy-beating candidates did not survive switch-level
  validation.
- Common failure reason: `lv_recovery_mean_bounds`.
- The regulating command transfer looks consistent, but the energy branch does
  not match the proxy semantics:
  requested `m_energy_d` is small positive, while the reported switch-level
  `energy_d_mean` is large negative, around `-0.40` to `-0.51`.

Interpretation:

- This is the first real switch-level evidence that a behavior-constrained
  full-action policy can beat the traditional baseline on one HPT FRT case.
- It is not robust enough to claim controller success.  The proxy-gate
  topology1/HVRT advantage transfers only partially to switch-level Simulink.
- The next technical blocker is action-semantics alignment, especially the
  energy-bridge command/current sign and the recovery-window voltage response.

