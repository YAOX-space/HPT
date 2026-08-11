# HPT SAC New-Matrix Proxy Calibration And Retraining Progress - 2026-07-19

## Completed

1. Re-ran the switch-level FRT calibration matrix with timestep envelope fields.
   - Matrix:
     `lab/results/hpt_v2_frt_calibration_matrix/frt_calibration_matrix_full_all_20260719_162219.csv`
   - Trace:
     `lab/results/hpt_v2_frt_calibration_matrix/frt_calibration_traces_full_all_20260719_162219.csv`
   - Aggregate rows: `828`
   - Trace samples: `91908`

2. Rebuilt proxy calibration from the new matrix.
   - Output:
     `sac/hpt_proxy_calibration.json`
   - Topologies: `topology1`, `topology2`
   - Fault depths:
     `0.2, 0.5, 0.75, 0.85, 0.9, 1.1, 1.2, 1.25, 1.3`

3. Re-ran proxy-vs-switch alignment.
   - Static proxy gap:
     `lab/results/hpt_v2_frt_proxy_gap/frt_proxy_gap_full_all_20260719_162219_summary.csv`
   - Actual proxy rollout alignment:
     `lab/results/hpt_v2_proxy_rollout_alignment/proxy_rollout_full_all_20260719_162219_detail.csv`
   - Reward alignment:
     `lab/results/hpt_v2_reward_alignment/reward_alignment_full_all_20260719_162219_REPORT.md`

4. Generated a new conventional boundary with timestep envelope fields.
   - CSV:
     `lab/results/hpt_v2_control_comparison/control_comparison_all_fault_all_conventional_boundary_20260719_163315.csv`
   - Strict envelope/full-FRT result:
     - topology1: `0 / 9`
     - topology2: `0 / 9`

5. Built the new full-action dataset.
   - Dataset:
     `data/hpt_boundary_full_action/hpt_boundary_full_action_20260719_163350/dataset.csv`
   - Rows: `556`
   - Schema: `hpt-boundary-full-action-dataset-v2`
   - Requires timestep envelope metrics: `true`

6. Re-ran training smoke tests.
   - Offline trajectory/split-head smoke:
     `lab/results/hpt_offline_full_action_smoke_20260719_envelope_v2`
   - Online split-head SAC short smoke:
     `lab/results/hpt_sac_splithead_proxy_smoke_20260719_envelope_v2_short`
   - Online split-head SAC with table teacher + projection:
     `lab/results/hpt_sac_splithead_proxy_smoke_20260719_envelope_v2_table_projected`
   - Pure BC table-teacher check:
     `lab/results/hpt_sac_splithead_proxy_bc_only_20260719_envelope_v2_table`

## Key Results

Proxy alignment is now strong on the new calibration matrix:

- LV mean rollout MAE: about `1.45e-4 pu`
- Vdc mean rollout MAE: about `3.95e-7 pu`
- envelope violation MAE: about `9.6e-6 pu`
- recovery violation MAE: about `2.8e-9 pu`

Reward ranking is also aligned on the fixed-action matrix:

- `20 / 20` groups have Spearman rank correlation `1.0`
- weak groups: `0`

However, the retrained specialist controllers are not yet successful:

- Offline trajectory smoke: `0 / 1` proxy pass, `0 / 1` beat conventional.
- Online split-head SAC short smoke: `0 / 1` proxy pass, `0 / 1` beat conventional.
- Table-teacher projected SAC: `0 / 1` proxy pass, `0 / 1` beat conventional.
- Pure BC table-teacher: actor matched the table teacher, but still failed the
  trajectory rollout.

## Main Finding

The proxy is no longer the main blocker for this tested case.  The important
new failure is teacher semantics:

- The fixed-action matrix can mark a candidate action as good for a case.
- But using that same action as a per-timestep trajectory command can fail.
- For `topology1 / LVRT / sag_0p90 / 60 ms`, the table teacher produces mostly
  `m_reg_d ~= 0.36 ... 0.60`.
- Pure BC reproduces this teacher with `teacher_gap = 0`, but trajectory rollout
  still fails:
  - DC link lower bound fails.
  - timestep voltage envelope fails.
  - recovery envelope fails.

Therefore, fixed-action teacher rows are not sufficient as trajectory-teacher
labels.  The next training target must be generated from actual per-step
switch-level trajectories or from a closed-loop trajectory optimization pass,
not by replaying one fixed action at every SAC decision step.

## Next Research Step

1. Build a trajectory teacher generator:
   - Use the new matrix only as candidate action evidence.
   - For each topology/fault case, synthesize several time schedules:
     - fault-only injection
     - ramp-in/ramp-out
     - recovery clamp
     - Vdc-protective taper
   - Evaluate those schedules in switch-level `trajectory_action` mode.

2. Promote only trajectory rows, not fixed rows, into the SAC dataset:
   - input: obs/time context at every 2 ms step
   - target: actual trajectory action at that step
   - labels: timestep envelope violation, recovery violation, Vdc, grid current

3. Re-train split-head specialists:
   - first BC/TD3+BC/AWAC from successful trajectory rows
   - then short SAC fine-tuning inside calibrated proxy

4. Validate only with switch-level trajectory/action actor rollout.

## Addendum: Duration Fix and Trajectory Teacher Smoke

Updated: `2026-07-19T17:57:51+08:00`

### Duration-field fix

The calibration path had one important field mismatch:

- switch-level matrix rows had `fault_start`, `fault_clear`, and `stop_time`;
- proxy calibration expected `fault_duration_s`;
- therefore duration-aware lookup could silently see matrix rows as `0.0 s`.

Fixed in:

- `sac/calibrate_hpt_frt_proxy_from_matrix.py`
  - derives `fault_duration_s = fault_clear - fault_start` when the explicit
    field is absent;
  - stores `fault_duration_s` in all fault response tables;
  - records `frt_matrix.fault_durations_s`.
- `sac/hpt_voltage_sac_env.py`
  - filters fault response/conventional/joint/energy tables by active
    `category` and `fault_duration_s` before interpolation.
- `simulink/collectors/collect_hpt_v2_frt_calibration_matrix.m`
  - new matrix exports now write `fault_start_s`, `fault_clear_s`,
    `fault_duration_s`, and `stop_time_s` explicitly.

After recalibration from
`lab/results/hpt_v2_frt_calibration_matrix/frt_calibration_matrix_full_all_20260719_162219.csv`,
all topology1/topology2 fault tables report duration `[0.06]`.

### Alignment after fix

Proxy rollout alignment remained strong:

- rows: `828`
- LV mean MAE: `1.4508e-4 pu`
- Vdc mean MAE: `3.95e-7 pu`
- grid current peak MAE: `4.09e-5 pu`
- envelope violation MAE: `9.60e-6 pu`
- recovery violation MAE: `2.81e-9 pu`

Reward ranking alignment also remained strong:

- `20 / 20` groups have Spearman `1.000`
- weak groups: `0`
- pass-like groups: still `0`, because strict timestep-envelope criteria are
  not yet satisfied by the fixed-action calibration matrix.

### Trajectory smoke results

A topology1 `0.90 pu`, `60 ms` LVRT smoke showed why fixed-action teachers are
not enough.

1. Ramp-down trajectory sweep:
   - run:
     `lab/results/hpt_traj_teacher_sweep_topology1_sag090_60ms_20260719_smoke`
   - best ramp-down candidates failed recovery badly:
     recovery mean around `165-171 V`.

2. Hold-after-clear trajectory sweep:
   - run:
     `lab/results/hpt_traj_teacher_sweep_topology1_sag090_60ms_20260719_hold_smoke`
   - holding support fixes much of the recovery dip, but still fails the
     per-step fault envelope.
   - best score in this small set: `m_reg_d = 0.36`, score `130.30`.
   - fault mean: `188.35 V`, recovery mean: `215.55 V`.
   - envelope violation max: `0.1956 pu`; recovery violation max:
     `0.0185 pu`.

3. Step trajectory check:
   - run:
     `lab/results/hpt_traj_teacher_topology1_sag090_step_rd036_20260719`
   - immediate step at fault start improves over slow ramp but still fails:
     envelope violation max `0.1636 pu`.

4. Constant trajectory check:
   - run:
     `lab/results/hpt_traj_teacher_topology1_sag090_constant_rd036_20260719`
   - exactly matches fixed-action behavior, confirming the trajectory-action
     interface is correctly wired.
   - still fails the strict per-step envelope:
     envelope violation max `0.0370 pu`, recovery violation max `0.00308 pu`.

### Interpretation

The current blocker is not a broken trajectory interface.  The interface works.
The blocker is that strict per-step envelope evaluation begins immediately at
`fault_start`.  A controller that reacts only after the voltage event cannot
remove the first-cycle/early transient violation unless the pass definition
allows an explicit fault-response settling window or the model has a predictive
pre-actuation signal.

Before training SAC again, the next decision is therefore:

- either keep the strict envelope and accept that only pre-biased/constant
  support can pass early samples;
- or add a documented fault-response assessment delay, analogous to the
  existing `0.035 s` recovery settling delay, and then regenerate matrix,
  proxy calibration, trajectory teacher data, and SAC datasets.

### Fault-response window support

Implemented a configurable fault-response assessment window without changing
the default strict standard:

- `sac/frt_envelope.py`
  - added `fault_settle_s`, default `0.0`.
- `sac/hpt_voltage_sac_env.py`
  - proxy step reward/envelope check now accepts `config.fault_settle_s`.
- `simulink/evaluators/eval_hpt_v2_control_comparison.m`
  - added `hpt_compare_fault_settle_s`, default `0.0`.
- `simulink/collectors/collect_hpt_v2_frt_calibration_matrix.m`
  - added `hpt_calib_fault_settle_s`, default `0.0`.
- `sac/validate_hpt_trajectory_switchlevel.py`
  and `sac/run_hpt_dynamic_trajectory_sweep.py`
  - added `--fault-settle-s`.

This lets us run strict `0 ms` certification and response-window research from
the same code path.

### 20-ms response-window checks

Small topology1/sag0.90/60-ms trajectory checks:

- constant `m_reg_d=0.36`, `fault_settle_s=20 ms`:
  - still fails envelope/recovery;
  - fault envelope violation max `0.0370 pu`;
  - recovery violation max `0.00308 pu`.
- two-stage `0 -> 0.60 -> 0.36`, `fault_settle_s=20 ms`:
  - much closer;
  - fault mean `202.38 V`;
  - recovery mean `215.57 V`;
  - Vdc min `723.33 V`;
  - fault envelope violation max `0.00362 pu`;
  - recovery violation max `0.0187 pu`.
- two-stage `0 -> 0.65 -> 0.30`, `fault_settle_s=20 ms`:
  - recovery improves but fault envelope worsens because support is reduced
    before clear;
  - Vdc min `691.10 V`.
- pre-biased feasibility check `0.30 -> 0.65 -> 0.30`,
  `fault_settle_s=20 ms`:
  - fault envelope violation reaches `0.0`;
  - but Vdc collapses to `461.02 V` and recovery still violates.

Interpretation: a usable trajectory teacher probably needs joint action,
especially energy-branch/DC-link management.  Regulating-bridge-only schedules
can trade fault support against recovery overshoot, but they do not solve the
full survival gate cleanly.

