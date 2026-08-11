# HPT SAC Stage-2 Evidence Audit - 2026-07-22

## Purpose

This audit checks the current repository evidence against the active Stage-2
research sequence:

1. produce mixed pass/fail boundary evidence;
2. recalibrate the proxy for timestep voltage-survival metrics;
3. train and validate balanced trajectory/state-feedback specialist SAC for
   topology1/topology2 LVRT/HVRT where feasible;
4. prepare the unbalanced-fault extension path with documented blockers and
   next actions.

The audit intentionally separates switch-level voltage-survival evidence from
full FRT certification.  No current accepted specialist is full-FRT certified.

## Verdict

| Requirement | Status | Evidence strength | Notes |
| --- | --- | --- | --- |
| Mixed pass/fail boundary evidence | Partly complete | Switch-level CSV/report evidence exists | Balanced boundary is mixed mainly for HVRT; unbalanced A/AB matrix is mixed for LVRT. |
| Proxy recalibrated for timestep voltage-survival metrics | Partly complete | Balanced pilot alignment exists; unbalanced pilot is diagnostic | Static pilot-support rollout alignment is strong, but energy-sweep reward ranking remains weak. |
| Balanced topology1/topology2 LVRT/HVRT specialists | Complete for voltage survival | Accepted switch-level matrix rechecked on 2026-07-22 | Four balanced 60-ms specialists pass voltage survival and beat conventional. The previous topology1 HVRT actor was stale, but it has been replaced by a current-interface retrain. |
| Unbalanced extension path | Prepared, not complete | Source smoke plus first topology1 accepted rows | Per-phase source is now supported; topology2 unbalanced remains blocked by energy/DC-link dynamics. |
| Full FRT certification | Not complete | Current accepted rows mark `full_frt_pass=false` | Grid-current and reactive-current criteria remain the next phase. |

## Mixed Boundary Evidence

### Balanced Boundary

Primary evidence:

- `lab/results/hpt_v2_control_comparison/control_comparison_all_fault_all_balanced_boundary_scale055_timestep_20260721_20260721_033458_voltage_survival_BOUNDARY_REPORT.md`

Result:

- 16 grouped balanced voltage-survival boundary slices.
- 7 / 16 groups are mixed pass/fail.
- Useful mixed regions are mostly HVRT:
  - topology1 HVRT at 40/80/120/200 ms;
  - topology2 HVRT at 40/80/120 ms.
- topology1 LVRT and topology2 LVRT are all-fail for the conventional baseline
  over this broad balanced matrix.

60-ms focused evidence:

- `lab/results/hpt_v2_control_comparison/control_comparison_all_fault_all_balanced_boundary_scale055_60ms_timestep_20260721_20260721_040555_voltage_survival_BOUNDARY_REPORT.md`

Result:

- 2 / 4 groups are mixed.
- topology1 HVRT is mixed: pass at 1.20 pu, fail at 1.25 pu.
- topology2 HVRT is mixed: pass at 1.12 pu, fail at 1.10 pu in the recorded
  conventional sweep, indicating nonmonotonic recovery/DC-link behavior that
  should be treated as a boundary diagnostic rather than a clean monotonic
  grid-code claim.

Core accepted-point check:

- `lab/results/hpt_v2_control_comparison/control_comparison_stage2_balanced_core_60ms_090_110_20260721_voltage_survival_BOUNDARY_REPORT.md`

Result:

- 0 / 4 mixed groups because it only checks the four accepted nominal
  0.90/1.10-pu cases.
- This file is useful as a core-point sanity check, not as boundary evidence.

### Unbalanced Boundary

Primary evidence:

- `lab/results/hpt_v2_control_comparison/control_comparison_all_fault_all_unbalanced_boundary_a_ab_scale055_20260721_20260721_055206_voltage_survival_BOUNDARY_REPORT.md`

Result:

- 4 grouped unbalanced A/AB slices.
- 2 / 4 groups are mixed.
- topology1 LVRT is mixed.
- topology2 LVRT is mixed but still dominated by timestep fault-band and
  voltage-envelope failures.
- Both HVRT groups are all-pass over the current unbalanced pilot range, so
  they are not yet useful beat-conventional boundary cases.

Limitation:

- This boundary is voltage-survival only.  Full-FRT pass count is 0.

## Proxy Recalibration Evidence

Balanced proxy calibration:

- Calibration JSON:
  `sac/hpt_proxy_calibration.json`
- Pilot matrix:
  `lab/results/hpt_v2_frt_calibration_matrix/frt_calibration_matrix_pilot_all_20260721_034530.csv`
- Alignment summary:
  `lab/results/hpt_proxy_alignment_pilot_20260721_034530/proxy_rollout_pilot_all_20260721_034530_summary.json`

Recorded pilot-support errors:

- LV mean MAE: about `6.7e-11 pu`;
- Vdc mean MAE: about `3.3e-11 pu`;
- envelope violation MAE: about `1.8e-10 pu`;
- fault-band violation MAE: about `6.9e-10 pu`;
- recovery violation MAE: about `5.5e-10 pu`.

Interpretation:

- The balanced proxy can reproduce its current pilot calibration table and the
  newly added timestep voltage-survival fields on support.
- This is not enough to prove robust off-support SAC training quality.

Unbalanced proxy pilot:

- Calibration JSON:
  `sac/hpt_proxy_calibration_unbalanced_pilot.json`
- Matrix:
  `lab/results/hpt_v2_frt_calibration_matrix/frt_calibration_matrix_pilot_all_20260721_061731.csv`
- Reward alignment report:
  `lab/results/hpt_v2_reward_alignment/reward_alignment_pilot_all_20260721_061731_REPORT.md`

Reward-ranking results:

- topology1 LVRT `reg_sweep`: Spearman about `0.956`;
- topology1 LVRT `joint_sweep`: Spearman about `0.848`;
- topology2 LVRT `reg_sweep`: Spearman about `0.956`;
- topology2 LVRT `joint_sweep`: Spearman about `0.947`;
- topology1 LVRT `energy_sweep`: Spearman about `0.120`;
- topology2 LVRT `energy_sweep`: Spearman about `0.359`.

Decision:

- Regulating and joint-action ranking is useful for coarse search.
- Energy-only proxy behavior is still too weak for final SAC training claims.
- Switch-level validation remains mandatory for promotion.

## Balanced Specialist Matrix

Authoritative balanced accepted matrix:

- `sac/experiments/accepted_specialists_20260721_balanced.csv`
- Latest recheck:
  `lab/results/hpt_accepted_balanced_matrix_20260722_current4_recheck/REPORT.md`

Current accepted rows:

| Case | Topology | Fault | Policy score | Baseline score | Voltage survival | Full FRT |
| --- | --- | --- | ---: | ---: | --- | --- |
| `topology1_lvrt090_60ms_gridobs_clock` | topology1 | LVRT 0.90 pu / 60 ms | 104.012 | 122.356 | pass | false |
| `topology1_hvrt110_60ms_current_iface_const249` | topology1 | HVRT 1.10 pu / 60 ms | 105.383 | 116.834 | pass | false |
| `topology2_lvrt090_60ms_phase_nonoise_retrain` | topology2 | LVRT 0.90 pu / 60 ms | 113.665 | 264.260 | pass | false |
| `topology2_hvrt110_60ms_balanced_retrain` | topology2 | HVRT 1.10 pu / 60 ms | 114.076 | 188.705 | pass | false |

All four accepted rows have:

- `voltage_survival_pass=true`;
- `beats_conventional=true`;
- `fault_lv_band_violation_max_pu=0`;
- `envelope_violation_max_pu=0`;
- DC-link values inside the current survival bounds.

The topology1 LVRT row reports a small nonzero
`recovery_violation_max_pu=0.0008097` but the current evaluator returns
`voltage_survival_pass=true` and no voltage failure reason.  This should be
treated as accepted under the current gate but noted when tightening future
envelope tolerances.

Replaced stale balanced row:

- `topology1_hvrt110_60ms_balanced_retrain` was moved out of the accepted
  matrix after the phase-aware/per-case validation recheck failed with
  `timestep_fault_lv_band;timestep_recovery_envelope`.
- It is replaced by `topology1_hvrt110_60ms_current_iface_const249`, trained
  under the current observation interface from the passing constant trajectory
  `[0.249, 0, -0.005, 0]`.
- Archive:
  `sac/experiments/stale_specialists_after_phaseaware_recheck_20260722.csv`.

Latest topology2 LVRT upgrade:

- Evidence:
  `lab/results/hpt_t2_lvrt090_fr052_rr016_re008_phase_nonoise_actor_20260722/summary.json`
- Actor:
  `data/models/hpt_t2_lvrt090_fr052_rr016_re008_phase_nonoise_actor_20260722_bc0.zip`
- The run passed switch-level voltage survival with zero fault/recovery
  envelope violation and replaced the older topology2 LVRT accepted row.

## Unbalanced Extension Path

Source/observation support:

- topology1 smoke:
  `lab/results/hpt_unbalanced_source_smoke_topology1_20260721_164456/REPORT.md`
- topology2 smoke:
  `lab/results/hpt_unbalanced_source_smoke_topology2_20260721_164301/REPORT.md`

Result:

- Both topologies passed 14 / 14 source cases.
- Per-phase sag/swell source and observation diagnostics are usable.

Unbalanced accepted matrix:

- `sac/experiments/accepted_specialists_20260721_unbalanced.csv`

Current unbalanced voltage-survival accepted rows:

| Case | Topology | Fault | Policy score | Baseline score | Voltage survival | Full FRT |
| --- | --- | --- | ---: | ---: | --- | --- |
| `topology1_a_lvrt090_60ms_unbalanced` | topology1 | A-phase LVRT 0.90 pu / 60 ms | 103.650 | 117.680 | pass | false |
| `topology1_ab_lvrt090_60ms_unbalanced` | topology1 | AB LVRT 0.90 pu / 60 ms | 104.331 | 116.292 | pass | false |

Blockers:

- topology2 A/AB unbalanced LVRT has not produced a promotable actor.
- The key unresolved issue is topology2 energy/DC-link dynamics and
  fault/recovery phase robustness.
- Unbalanced HVRT specialists are not yet promoted.
- Full-FRT current criteria are not yet passing.

Scenario manifest:

- `sac/experiments/stage1_stage2_scenarios_20260721.csv`

This manifest has been updated so unbalanced rows no longer claim
`pending_source_model`; the source is supported, while topology2 training
remains blocked by controller dynamics.

## Next Actions

1. Expand topology2 LVRT from the narrow no-noise actor into a robust
   phase/window-conditioned or two-head reg/energy actor.
2. Rebuild a larger proxy calibration matrix that includes topology2
   energy-only and joint-energy cases near the accepted LVRT/HVRT trajectories.
3. For unbalanced work, continue from topology2 A-phase LVRT 0.90 pu and
   topology2 AB LVRT 0.90 pu, using switch-level trajectory teachers first.
4. Keep full-FRT certification separate until grid-side reactive-current
   support and current-limit metrics pass in switch-level validation.
