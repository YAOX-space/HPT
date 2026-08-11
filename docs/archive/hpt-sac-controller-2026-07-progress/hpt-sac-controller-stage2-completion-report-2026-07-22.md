# HPT SAC Stage-2 Completion Report - 2026-07-22

## Scope

This report closes the current Stage-2 voltage-survival research sequence:

1. establish mixed pass/fail boundary evidence for a meaningful conventional
   baseline;
2. recalibrate the proxy for timestep voltage-survival metrics;
3. train and validate balanced trajectory/state-feedback specialist SAC for
   topology1/topology2 LVRT/HVRT;
4. train and validate the first unbalanced A/AB LVRT specialist set for
   topology1/topology2.

This is not a full-FRT certification report.  Current accepted specialists are
switch-level voltage-survival controllers only.

## Authoritative Unified Recheck

The current Stage-2 accepted matrix is the 8-row manifest:

- `sac/experiments/accepted_specialists_20260722_stage2_voltage_survival.csv`

Latest unified switch-level recheck:

- Summary:
  `lab/results/hpt_stage2_voltage_survival_matrix_20260722_8row_warmsac_recheck/summary.json`
- Report:
  `lab/results/hpt_stage2_voltage_survival_matrix_20260722_8row_warmsac_recheck/REPORT.md`
- Validation CSV:
  `lab/results/hpt_stage2_voltage_survival_matrix_20260722_8row_warmsac_recheck/accepted_specialist_validation.csv`

Result:

- cases: `8`;
- voltage-survival pass: `8 / 8`;
- beats conventional: `6 / 8`;
- full FRT pass: `0 / 8`.

Interpretation:

- balanced topology1/topology2 LVRT/HVRT: `4 / 4` voltage-survival and
  `4 / 4` beat conventional;
- unbalanced topology1/topology2 A/AB LVRT: `4 / 4` voltage-survival;
- unbalanced topology2 A/AB LVRT: `2 / 2` beat conventional;
- unbalanced topology2 A/AB LVRT are now warm-start SAC fine-tuned actors,
  promoted only after switch-level recheck;
- unbalanced topology1 A/AB LVRT: voltage-survival only, not
  beat-conventional under the current score definition;
- full FRT remains intentionally out of Stage-2 scope and is not claimed.

## Requirement Audit

| Requirement | Status | Authoritative evidence | Conclusion |
| --- | --- | --- | --- |
| Mixed pass/fail boundary evidence | Complete for Stage-2 | Balanced and unbalanced boundary reports | Conventional baseline has useful pass/fail boundaries, especially balanced HVRT and unbalanced LVRT. |
| Proxy recalibrated for timestep voltage-survival metrics | Complete for balanced support; diagnostic for unbalanced | `hpt_proxy_calibration.json` plus rollout-alignment summary | Balanced proxy reproduces timestep voltage-survival fields on calibration support; unbalanced energy-only ranking remains weak. |
| Balanced topology1/topology2 LVRT/HVRT specialist SAC | Complete for switch-level voltage survival | `hpt_stage2_voltage_survival_matrix_20260722_8row_warmsac_recheck` | Four 60-ms balanced specialists pass voltage survival and beat conventional. |
| Unbalanced topology1/topology2 A/AB LVRT specialist SAC | Complete for switch-level voltage survival | `hpt_stage2_voltage_survival_matrix_20260722_8row_warmsac_recheck` | Four 60-ms unbalanced specialists pass voltage survival; topology2 A/AB also beat conventional and use warm-start SAC fine-tuned actors. |
| Full FRT certification | Out of Stage-2 scope / not complete | accepted matrix full-FRT columns | 0 / 8 accepted rows pass full FRT; current/reactive-current/recovery criteria remain future work. |

## Mixed Boundary Evidence

Balanced conventional boundary:

- Report:
  `lab/results/hpt_v2_control_comparison/control_comparison_all_fault_all_balanced_boundary_scale055_timestep_20260721_20260721_033458_voltage_survival_BOUNDARY_REPORT.md`
- Result:
  `7 / 16` grouped balanced slices are mixed pass/fail.
- Useful regions:
  topology1 HVRT 40/80/120/200 ms and topology2 HVRT 40/80/120 ms.
- Limitation:
  broad balanced LVRT remains conventional all-fail in this sweep, so LVRT
  specialist claims must use accepted-point SAC-vs-conventional validation
  rather than a clean conventional boundary curve.

Unbalanced conventional boundary:

- Report:
  `lab/results/hpt_v2_control_comparison/control_comparison_all_fault_all_unbalanced_boundary_a_ab_scale055_20260721_20260721_055206_voltage_survival_BOUNDARY_REPORT.md`
- Result:
  `2 / 4` grouped A/AB slices are mixed pass/fail.
- Useful regions:
  topology1 LVRT and topology2 LVRT.
- Limitation:
  this is voltage-survival only; full-FRT pass count is zero.

## Proxy Recalibration Evidence

Balanced proxy:

- Calibration:
  `sac/hpt_proxy_calibration.json`
- Pilot matrix:
  `lab/results/hpt_v2_frt_calibration_matrix/frt_calibration_matrix_pilot_all_20260721_034530.csv`
- Rollout alignment:
  `lab/results/hpt_proxy_alignment_pilot_20260721_034530/proxy_rollout_pilot_all_20260721_034530_summary.json`

The balanced proxy reproduces the calibration-support timestep metrics:

- LV mean MAE: `6.71e-11 pu`;
- Vdc mean MAE: `3.29e-11 pu`;
- envelope violation MAE: `1.76e-10 pu`;
- fault-band violation MAE: `6.86e-10 pu`;
- recovery violation MAE: `5.47e-10 pu`.

Interpretation:

- The proxy is valid as a support-table surrogate for timestep
  voltage-survival fields.
- It is not evidence that off-support SAC policies will transfer without
  switch-level validation.

Unbalanced proxy pilot:

- Calibration:
  `sac/hpt_proxy_calibration_unbalanced_pilot.json`
- Reward-alignment report:
  `lab/results/hpt_v2_reward_alignment/reward_alignment_pilot_all_20260721_061731_REPORT.md`

Useful ranking groups:

- topology1 LVRT `reg_sweep`: Spearman `0.956`;
- topology1 LVRT `joint_sweep`: Spearman `0.848`;
- topology2 LVRT `reg_sweep`: Spearman `0.956`;
- topology2 LVRT `joint_sweep`: Spearman `0.947`.

Weak groups:

- topology1 LVRT `energy_sweep`: Spearman `0.120`;
- topology2 LVRT `energy_sweep`: Spearman `0.359`.

Decision:

- Use the unbalanced proxy pilot only for coarse ranking and diagnostics.
- Do not promote unbalanced SAC from proxy-only evidence.

## Balanced Specialist Matrix

Accepted manifest:

- `sac/experiments/accepted_specialists_20260721_balanced.csv`

Latest switch-level validation:

- Summary:
  `lab/results/hpt_accepted_balanced_matrix_20260722_current4_recheck/summary.json`
- Report:
  `lab/results/hpt_accepted_balanced_matrix_20260722_current4_recheck/REPORT.md`
- Unified 8-row recheck:
  `lab/results/hpt_stage2_voltage_survival_matrix_20260722_8row_warmsac_recheck/REPORT.md`

Result:

- cases: `4`;
- voltage-survival pass: `4 / 4`;
- beats conventional: `4 / 4`;
- full FRT pass: `0 / 4`.

| Case | Topology | Fault | Actor | SAC score | Conventional score | Vdc min/max |
| --- | --- | --- | --- | ---: | ---: | --- |
| `topology1_lvrt090_60ms_gridobs_clock` | topology1 | LVRT 0.90 pu / 60 ms | `data/models/hpt_t1_l090_pre24_b60_down35_clk_dg3_dagger2.zip` | 104.012 | 122.356 | 766.30 / 876.57 V |
| `topology1_hvrt110_60ms_current_iface_const249` | topology1 | HVRT 1.10 pu / 60 ms | `data/models/hpt_t1_hvrt110_const249_current_iface_actor_20260722_bc0.zip` | 105.383 | 116.834 | 765.00 / 878.06 V |
| `topology2_lvrt090_60ms_phase_nonoise_retrain` | topology2 | LVRT 0.90 pu / 60 ms | `data/models/hpt_t2_lvrt090_fr052_rr016_re008_phase_nonoise_actor_20260722_bc0.zip` | 113.665 | 264.260 | 761.40 / 978.45 V |
| `topology2_hvrt110_60ms_balanced_retrain` | topology2 | HVRT 1.10 pu / 60 ms | `data/models/hpt_t2_h110_bal_retrain_gate_20260721_bc0.zip` | 114.076 | 188.705 | 762.39 / 999.98 V |

Notes:

- `topology1_hvrt110_60ms_current_iface_const249` replaces the stale
  `topology1_hvrt110_60ms_balanced_retrain` actor, which stopped producing the
  required regulating action after the observation/grid-normalization
  interface changed.
- The replacement was trained from the passing constant trajectory
  `[0.249, 0, -0.005, 0]` under the current interface.
- `topology2_lvrt090_60ms_phase_nonoise_retrain` requires the phase-override
  observation contract and raw actor filtering (`actor_filter_tau=0`).

## Unbalanced Specialist Matrix

Source/observation smoke:

- topology1:
  `lab/results/hpt_unbalanced_source_smoke_topology1_20260721_164456/REPORT.md`
- topology2:
  `lab/results/hpt_unbalanced_source_smoke_topology2_20260721_164301/REPORT.md`

Result:

- topology1 source smoke: `14 / 14`;
- topology2 source smoke: `14 / 14`.

Scenario manifest:

- `sac/experiments/stage1_stage2_scenarios_20260721.csv`

Accepted unbalanced manifest:

- `sac/experiments/accepted_specialists_20260721_unbalanced.csv`

Latest switch-level validation:

- Phase-vector recheck:
  `lab/results/hpt_accepted_unbalanced_matrix_20260722_current4_phasefix_recheck/REPORT.md`
- Unified 8-row recheck:
  `lab/results/hpt_stage2_voltage_survival_matrix_20260722_8row_warmsac_recheck/REPORT.md`

Result:

- cases: `4`;
- voltage-survival pass: `4 / 4`;
- beats conventional: `2 / 4`;
- full FRT pass: `0 / 4`.

| Case | Topology | Fault | Actor | SAC score | Conventional score | Status |
| --- | --- | --- | --- | ---: | ---: | --- |
| `topology1_a_lvrt090_60ms_unbalanced` | topology1 | A-phase LVRT 0.90 pu / 60 ms | `data/models/hpt_unbalanced_t1_a_lvrt090_trajteacher_smoke_20260721_bc0.zip` | 106.028 | 102.465 | voltage-survival only |
| `topology1_ab_lvrt090_60ms_unbalanced` | topology1 | AB LVRT 0.90 pu / 60 ms | `data/models/hpt_unbalanced_t1_ab_lvrt090_trajteacher_tau0_bcstrong_20260721_bc0.zip` | 106.015 | 102.888 | voltage-survival only |
| `topology2_a_lvrt090_60ms_unbalanced` | topology2 | A-phase LVRT 0.90 pu / 60 ms | `data/models/hpt_t2_a_lvrt090_warm_sac_reganchor_20260722.zip` | 126.578 | 159.385 | warm-start SAC fine-tune, voltage-survival and beats conventional |
| `topology2_ab_lvrt090_60ms_unbalanced` | topology2 | AB LVRT 0.90 pu / 60 ms | `data/models/hpt_t2_ab_lvrt090_warm_sac_reganchor_20260722.zip` | 132.148 | 163.332 | warm-start SAC fine-tune, voltage-survival and beats conventional |

Known limitations:

- topology1 unbalanced A/AB rows are useful survival evidence but are not
  beat-conventional evidence under the current score definition;
- topology2 unbalanced rows are the strongest current SAC-over-conventional
  evidence and the first accepted warm-start SAC fine-tuned unbalanced actors;
- topology2 energy/DC-link response remains sensitive to recovery timing and
  energy-branch command semantics, so future SAC fine-tuning should focus
  there first;
- full-FRT current criteria are not part of this Stage-2 claim and should not
  be mixed into the voltage-survival claim.

## Current Stage-2 Claim

The supported claim is:

> A set of topology- and fault-specialist SAC actors can pass switch-level HPT
> voltage-survival tests for eight Stage-2 60-ms cases: four balanced
> topology1/topology2 LVRT/HVRT cases and four unbalanced topology1/topology2
> A/AB LVRT cases. Six of the eight also outperform the tuned conventional
> baseline under the current voltage-survival score.

The unsupported claims are:

- one unified SAC handles all topology/fault/unbalanced cases;
- proxy-only training is sufficient for final promotion;
- the accepted actors satisfy full grid-code FRT certification;
- topology1 unbalanced specialists beat conventional;
- full FRT certification is complete.

## Next Actions

1. Use the unified 8-row recheck as the Stage-2 voltage-survival baseline.
2. Use the topology2 A/AB warm-start SAC fine-tune settings as the conservative
   template for the next SAC experiments: very small learning rate, strong
   behavior anchoring to the accepted actor, and switch-level validation before
   promotion.
3. The failed unanchored/weak-anchor A-phase runs show that direct proxy SAC can
   destroy the regulating action; future tuning should protect the regulating
   bridge while searching energy/recovery improvements.
4. Keep switch-level validation as the promotion gate; proxy-only gains remain
   diagnostic.
5. Add full-FRT current/reactive-current objectives only after the
   voltage-survival matrix remains reproducible under this unified validator.
6. For future claims, always cite the run-level report and the manifest row
   together; do not cite stale accepted manifests without re-running
   `validate_hpt_accepted_specialists.py`.
