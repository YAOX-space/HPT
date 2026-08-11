# HPT SAC Trajectory And Envelope Update - 2026-07-19

## Purpose

This update changes the version-2 HPT SAC workflow from fixed-point action
screening toward trajectory-specialist control.  The active gate is now stricter:
future fault candidates must respect the FRT voltage envelope at every sampled
control step, not only by fault-window averages.

## Completed Code Changes

1. Shared FRT envelope definition
   - Added `sac/frt_envelope.py`.
   - The Python proxy and MATLAB switch-level evaluators now use matching
     LVRT/HVRT envelope concepts:
     - LVRT lower-bound envelope.
     - HVRT upper-bound envelope.
     - recovery-band check after the configured settling delay.
   - The proxy reward now penalizes both instantaneous envelope violation and
     recovery-envelope violation.

2. Every-control-step pass fields
   - `HPTVoltageSACEnv.step()` now reports:
     - `envelope_violation_pu`
     - `envelope_violation_max_pu`
     - `envelope_violation_duration_s`
     - `recovery_violation_pu`
     - `recovery_violation_max_pu`
     - `recovery_violation_duration_s`
     - `timestep_envelope_pass`
   - The voltage-survival gate now fails on either:
     - `timestep_voltage_envelope`
     - `timestep_recovery_envelope`

3. Switch-level matrix/evaluator fields
   - Updated `simulink/collectors/collect_hpt_v2_frt_calibration_matrix.m`.
   - Updated `simulink/evaluators/eval_hpt_v2_control_comparison.m`.
   - New aggregate CSVs should contain timestep envelope metrics.
   - New trace CSVs should also contain sampled envelope bounds and violations.

4. Proxy-vs-switch alignment
   - `calibrate_hpt_frt_proxy_from_matrix.py` now carries the new envelope
     metrics into calibration tables.
   - `measure_hpt_frt_proxy_gap.py`, `measure_hpt_reward_alignment.py`, and
     `verify_hpt_proxy_rollout_alignment.py` now compare envelope/recovery
     violations as first-class outputs.

5. Split controller heads
   - Online specialist SAC now supports `--controller-heads split` by default.
   - The custom SB3 policy uses one output head for
     `[m_reg_d, m_reg_q]` and another for `[m_energy_d, m_energy_q]`.
   - Offline full-action actors also support `--controller-heads split`.

6. Trajectory specialist mode
   - Offline full-action training now has `--specialist-mode trajectory` by
     default.
   - The training context includes time features:
     - `t_s`
     - `t_norm`
     - `in_fault_window`
     - `in_recovery_window`
     - `time_to_clear_norm`
   - Instead of learning one fixed action per case, the actor is queried at each
     2 ms control step and learns a smooth action schedule.

7. Old-data protection
   - `build_hpt_boundary_full_action_dataset.py` now uses schema
     `hpt-boundary-full-action-dataset-v2`.
   - By default it rejects rows missing timestep envelope metrics.
   - Known stale matrix stems are skipped unless explicitly overridden.
   - This prevents pre-envelope or corrupt calibration rows from being treated
     as valid full-action evidence.

## What This Does Not Yet Prove

This commit-level update does not certify a new SAC controller.  It proves that
the code path can now express the correct experiment:

- split reg/energy action heads;
- trajectory-level action scheduling;
- per-step envelope reward and pass/fail;
- stricter dataset ingestion;
- proxy/switch comparison of the same safety quantities.

The previous accepted switch-level specialist matrix is now legacy evidence
under the new gate.  It must be rerun because those old rows were not produced
with timestep envelope fields.

## Required Next Run

Run the refresh in this order:

```powershell
matlab -batch "cd('E:/research_space/Hybrid-power-transformer/simulink'); hpt_calib_mode='full'; hpt_calib_topology='all'; run(fullfile(pwd,'collectors','collect_hpt_v2_frt_calibration_matrix.m'));"
py -3.8 -m sac.calibration.calibrate_hpt_frt_proxy_from_matrix
py -3.8 -m sac.calibration.measure_hpt_frt_proxy_gap
py -3.8 -m sac.calibration.verify_hpt_proxy_rollout_alignment
py -3.8 -m sac.calibration.measure_hpt_reward_alignment
py -3.8 -m sac.datasets.build_hpt_boundary_full_action_dataset
py -3.8 -m sac.offline.train_hpt_offline_full_action_baselines --group-specialists --group-by-fault --specialist-mode trajectory --controller-heads split
py -3.8 -m sac.offline.train_hpt_fault_specialists_vs_baseline --controller-heads split --granularity case --selection near_boundary
```

Only after these runs should a candidate be promoted to switch-level validation.



