# Stage-6 Four-Issue Audit

Date: 2026-07-28

## Question

Are the four recent audit issues complete?

1. The representative matrix should contain 12 specialists, not 8.
2. Many of the 8 earlier entries were BC or DAgger policies, not clearly
   SAC-improved policies.
3. The next target should be fault-family specialists, not only one fixed
   center case per fault.
4. SAC fine-tune has not shown a clear improvement yet.

## Short Answer

No. The issues have been clarified and partially repaired, but they are not all
closed.

Scope update: the user no longer requires teacher replay / BC / BC+DAgger
ablation as a completion gate.  The paper-critical gate is now narrower and
cleaner: the final SAC actor must beat the conventional dq baseline under the
same switch-level voltage-survival validator.  Provenance should still be
recorded honestly, but ablation is optional supporting evidence rather than a
required repair item.

## Evidence Used

- Stage-6 target matrix:
  `sac/experiments/stage6_fault_family_experiment_matrix_20260727.csv`
- Current 10-case switch-level recheck:
  `lab/results/hpt_stage6_recheck_current10_20260727/accepted_specialist_validation.csv`
- Topology1 HVRT fallback probe:
  `lab/results/hpt_stage6_probe_t1_hvrt_unbalanced_fallback_20260727/accepted_specialist_validation.csv`
- Current status memo:
  `docs/specs/algorithms/hpt-sac-controller/hpt-sac-controller-stage6-recheck-status-2026-07-27.md`

## Current Status By Issue

| Issue | Status | Evidence | Remaining gap |
| --- | --- | --- | --- |
| 12 specialists, not 8 | Partially fixed | The Stage-6 matrix has 12 representative topology/fault rows. Current evidence gives 10 case-specific switch-level voltage-survival passes plus 2 topology1 HVRT fallback voltage-survival passes. | The two topology1 A/AB-HVRT rows are fallback uses of the balanced-HVRT actor, not independent fault-specific specialists. A unified 12-row recheck with explicit fallback labels is still needed. |
| BC/DAgger/SAC provenance | Re-scoped | The Stage-6 plan and status now state that earlier actors are mixed BC, DAgger, trajectory, and protected-SAC artifacts. | Do not require a teacher/BC/DAgger ablation for completion.  Instead, keep provenance labels and require the final promoted SAC actor to beat conventional. |
| Fault-family specialists | Not complete | A 12-row Stage-6 matrix and runbook exist. | No trained family specialist has yet passed a held-out family matrix. Current evidence is still mostly fixed center cases. |
| SAC beats conventional | Not complete | Some topology2 cases have beat-conventional switch-level evidence; topology1 A/AB-HVRT repair attempts have not produced a better independent actor. | Complete the remaining 12-case gaps by training/fine-tuning SAC actors that pass voltage survival and beat conventional. |

## Current Switch-Level Counts

- Current 10 case-specific rows:
  - 10 / 10 voltage-survival pass.
  - 8 / 10 beat conventional.
  - 0 / 10 full FRT pass.
- Topology1 A/AB-HVRT fallback rows:
  - 2 / 2 voltage-survival pass.
  - 0 / 2 beat conventional.
  - 0 / 2 full FRT pass.

Combined interpretation: all 12 representative center fault types currently
have a voltage-survival controller path, but only 10 are case-specific and only
8 beat conventional. This is not yet a clean 12-specialist SAC result.

## Next Actions

1. Re-run topology1 A-HVRT CEM after the positive-HVRT bounds fix, without
   forcing a return-to-zero action, so sustained positive-d candidates can be
   evaluated.
2. Repeat the same repair for topology1 AB-HVRT if A-HVRT produces a useful
   candidate.
3. Run a 12-row consolidation recheck that marks fallback rows explicitly.
4. Promote only rows that pass a family holdout matrix to
   `fault-family specialist`; keep center-case rows labeled as center-case
   specialists.

## 2026-07-28 Update: Topology1 A-HVRT Repair Evidence

The user-scoped goal was tightened to final SAC-vs-conventional superiority;
teacher/BC/DAgger ablation is no longer required as a completion gate.

New switch-level results:

- CEM sustained positive-d search:
  `lab/results/hpt_stage6_t1_a_hvrt110_cem_sustained_20260728/REPORT.md`
  - 8 switch-level candidates.
  - 0 voltage-survival passes.
  - Diagnosis: proxy-selected candidates under-supported the fault window.
- Positive-d fault/recovery sweep without pre-bias:
  `lab/results/hpt_stage6_t1_a_hvrt110_score_sweep_posd_20260728/REPORT.md`
  - 9 / 9 voltage-survival passes.
  - 0 / 9 beat conventional.
- Pre-biased positive-d sweep:
  `lab/results/hpt_stage6_t1_a_hvrt110_score_sweep_prebias_20260728/REPORT.md`
  - 8 / 8 voltage-survival passes.
  - 1 / 8 beat conventional.
  - Best trajectory: `pre_reg_d=0.24`, `fault_reg_d=0.30`,
    `recovery_reg_d=0.30`, `energy_d=-0.005`.
  - Best trajectory score: `105.140`, conventional score: `105.229`.
  - All voltage-survival envelope violations were zero.
- Actor distillation from the best trajectory:
  `lab/results/hpt_stage6_t1_a_hvrt110_prebias_actor_20260728/summary.json`
  - Final actor passed voltage survival.
  - Final actor did not beat conventional: policy score `105.261` versus
    conventional score `105.229`.
- Protected SAC fine-tune:
  `lab/results/hpt_stage6_t1_a_hvrt110_prebias_sacft_20260728/summary.json`
  and
  `lab/results/hpt_stage6_t1_a_hvrt110_prebias_sacft_relaxed_20260728/summary.json`
  - Strong-anchor SAC kept voltage survival but produced no score improvement.
  - Relaxed-anchor SAC produced reward traces but broke voltage survival.

Interpretation: topology1 A-HVRT now has a switch-level trajectory that beats
conventional, but not yet a final SAC actor that beats conventional.  The next
repair should focus on trajectory-to-actor fidelity or direct state-feedback
policy optimization around this pre-biased positive-d behavior.

## 2026-07-28 Update: Topology1 AB-HVRT Trajectory Evidence

- Pre-biased positive-d sweep:
  `lab/results/hpt_stage6_t1_ab_hvrt110_score_sweep_prebias_20260728/REPORT.md`
  - 8 / 8 voltage-survival passes.
  - 1 / 8 beat conventional.
  - Best trajectory: `pre_reg_d=0.24`, `fault_reg_d=0.24`,
    `recovery_reg_d=0.30`, `energy_d=-0.005`.
  - Best trajectory score: `104.911`, conventional score: `104.983`.
  - All voltage-survival envelope violations were zero.

Interpretation: both missing topology1 unbalanced HVRT center cases now have
switch-level trajectories that beat conventional.  The remaining research gap
is converting these trajectories into final state-feedback SAC actors that
preserve the trajectory score advantage in switch-level validation.

## 2026-07-28 Update: Topology1 AB-HVRT Actor Fidelity Diagnostics

Follow-up experiments focused on the topology1 AB-HVRT 1.10 pu / 60 ms row.

- The first AB-HVRT actor distilled from the pre-biased trajectory passed
  voltage survival but did not beat conventional:
  `lab/results/hpt_stage6_t1_ab_hvrt110_prebias_actor_20260728/summary.json`
  - trajectory score `104.911`, conventional score `104.983`;
  - actor score `105.328`;
  - all sampled voltage-survival violations remained zero.
- A tau-0 recheck of that actor also passed voltage survival but did not beat
  conventional:
  `lab/results/hpt_stage6_t1_ab_hvrt110_prebias_actor_tau0_recheck_20260728/`.
- A local score-margin sweep found a better switch-level trajectory:
  `lab/results/hpt_stage6_t1_ab_hvrt110_score_sweep_margin_20260728/`
  - best completed trajectory: `pre_reg_d=0.20`, `fault_reg_d=0.21`,
    `recovery_reg_d=0.30`, `energy_d=-0.005`;
  - trajectory score `104.714`, conventional score `104.983`;
  - all sampled voltage-survival violations were zero.
- Direct actor distillation from the margin trajectory still failed to beat
  conventional:
  `lab/results/hpt_stage6_t1_ab_hvrt110_margin_actor_20260728/summary.json`
  - actor score `105.664`;
  - trace alignment showed `m_reg_d` MAE `0.0266` and LV RMS MAE `4.65 V`,
    indicating poor trajectory-to-state-feedback fidelity.
- A phase-aware diagnostic actor improved fidelity but remained just short of
  the beat-conventional gate:
  `lab/results/hpt_stage6_t1_ab_hvrt110_margin_actor_phaseaware_20260728/summary.json`
  - actor score `104.996`, conventional score `104.983`;
  - trace alignment improved to `m_reg_d` MAE `0.00906` and LV RMS MAE
    `1.47 V`;
  - this is diagnostic only because scheduled phase features have oracle-risk
    unless replaced by online fault/recovery detector features.
- A phase-aware tau-0 recheck worsened the result:
  `lab/results/hpt_stage6_t1_ab_hvrt110_phaseaware_tau0_recheck_20260728/`.

Interpretation: the AB-HVRT gap is now localized.  Simulink has a
beat-conventional trajectory with adequate score margin, but the final
deployable actor still loses the margin because the current observation/action
interface does not robustly encode the required prefault/fault/recovery
control phase.  Phase-aware observations almost close the gap, so the next
repair should replace oracle scheduled phase flags with online phase/detector
features and then repeat actor distillation plus SAC fine-tune with recorded
reward traces.

## 2026-07-28 Update: Online Detector Repair and AB-HVRT SAC Promotion

The oracle-risk phase-aware diagnostic was replaced by an online
fault/recovery detector in `simulink/add_hpt_sac_controller.m`.
The detector repair adds an HVRT falling-edge clear condition with a minimum
fault-age gate, avoiding the earlier failure mode where topology1 AB-HVRT was
misclassified as `fault_active` throughout recovery or prematurely classified
as `recovery_active` before fault clearing.

Detector validation:

- Trace artifact:
  `lab/results/hpt_v2_trajectory_traces/trajectory_trace_topology1_stage6_t1_ab_hvrt_detector_fix8_trace_20260728_033005.csv`.
- Fault window: `obs_17 = 1.0`, `obs_18 = 0.0`.
- Recovery window: `obs_17 = 0.0`, `obs_18 = 1.0`.
- Interface smoke:
  `py -3.8 -m sac.smoke_matlab_engine --runner batch --test interface --timeout-s 900`
  passed for topology1 and topology2.

State-feedback actor after detector repair:

- Run:
  `lab/results/hpt_stage6_t1_ab_hvrt110_margin_actor_detectorfix_20260728/summary.json`.
- Source trajectory remained switch-level valid and beat conventional:
  trajectory score `104.714`, conventional score `109.170`.
- Distilled state-feedback actor passed switch-level voltage survival and beat
  conventional:
  actor score `104.879`, conventional score `109.170`.
- Trace alignment improved to `m_reg_d` MAE `0.00833`, LV RMS MAE `1.41 V`,
  Vdc MAE `1.05 V`.

Protected SAC fine-tune:

- Run:
  `lab/results/hpt_stage6_t1_ab_hvrt110_detectorfix_sacft_20260728/summary.json`.
- The completion gate was SAC-vs-conventional, not SAC-vs-BC.
- All 4 protected SAC chunks passed switch-level voltage survival and beat
  conventional.
- Best SAC-updated actor: chunk 01,
  `data/models/hpt_stage6_t1_ab_hvrt110_detectorfix_sacft_20260728_chunk01.zip`.
- Best switch-level score: `104.717` versus conventional `109.170`, giving a
  score improvement of `4.454`.
- Voltage-survival metrics for the best SAC chunk:
  `envelope_violation_max_pu = 0`,
  `recovery_violation_max_pu = 0`,
  `fault_lv_band_violation_max_pu = 0`,
  `vdc_min = 768.75 V`,
  `vdc_max = 878.66 V`.
- Full FRT remains false because grid-current/reactive-current items are not
  yet satisfied/evaluated; this result is voltage-survival only.
- Reward trace artifacts:
  `lab/results/hpt_stage6_t1_ab_hvrt110_detectorfix_sacft_20260728/sac_training_reward_trace_combined.csv`
  and
  `lab/results/hpt_stage6_t1_ab_hvrt110_detectorfix_sacft_20260728/sac_reward_and_switch_score_convergence.png`.

Interpretation: topology1 AB-HVRT now has a non-oracle, online-detector,
state-feedback SAC-updated actor that passes switch-level voltage survival and
beats the conventional dq baseline. This closes one of the two missing
topology1 unbalanced HVRT representative rows. The remaining similar row is
topology1 A-HVRT, which should be rerun through the same online-detector plus
protected-SAC pipeline.

## 2026-07-28 Update: A-HVRT SAC Promotion with the Same Detector Repair

The same non-oracle online-detector pipeline was then applied to topology1
A-phase HVRT 1.10 pu / 60 ms.

State-feedback actor after detector repair:

- Run:
  `lab/results/hpt_stage6_t1_a_hvrt110_prebias_actor_detectorfix_20260728/summary.json`.
- Source trajectory remained switch-level valid and beat conventional:
  trajectory score `105.140`, conventional score `107.784`.
- Distilled state-feedback actor passed switch-level voltage survival and beat
  conventional:
  actor score `104.737`, conventional score `107.784`.
- Trace alignment was acceptable for this representative row:
  `m_reg_d` MAE `0.01043`, LV RMS MAE `1.21 V`, Vdc MAE `1.14 V`.

Protected SAC fine-tune:

- Run:
  `lab/results/hpt_stage6_t1_a_hvrt110_detectorfix_sacft_20260728/summary.json`.
- All 4 protected SAC chunks passed switch-level voltage survival and beat
  conventional.
- Best SAC-updated actor: chunk 03,
  `data/models/hpt_stage6_t1_a_hvrt110_detectorfix_sacft_20260728_chunk03.zip`.
- Best switch-level score: `104.654` versus conventional `107.784`, giving a
  score improvement of `3.130`.
- Voltage-survival metrics for the best SAC chunk:
  `envelope_violation_max_pu = 0`,
  `recovery_violation_max_pu = 0`,
  `fault_lv_band_violation_max_pu = 0`,
  `vdc_min = 766.74 V`,
  `vdc_max = 876.91 V`.
- Full FRT remains false because grid-current/reactive-current items are not
  yet satisfied/evaluated; this result is voltage-survival only.
- Reward trace artifacts:
  `lab/results/hpt_stage6_t1_a_hvrt110_detectorfix_sacft_20260728/sac_training_reward_trace_combined.csv`
  and
  `lab/results/hpt_stage6_t1_a_hvrt110_detectorfix_sacft_20260728/sac_reward_and_switch_score_convergence.png`.

Interpretation: both missing topology1 unbalanced HVRT representative rows
(A-phase and AB-phase, 1.10 pu / 60 ms) now have non-oracle online-detector
SAC-updated actors that pass switch-level voltage survival and beat the
traditional dq baseline. They should next be incorporated into a consolidated
12-row recheck manifest so the overall Stage-6 table no longer relies on
fallback actors for topology1 unbalanced HVRT.
