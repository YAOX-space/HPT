# HPT Research Log

## 2026-07-21 - Autonomy skill bootstrap

- Branch: `research/hpt-autonomy-skill`
- Scope: repository audit, project skill creation, autonomy policies, MATLAB
  Engine smoke runner, and dry-run baseline.
- Findings:
  - Git root is `E:/research_space/Hybrid-power-transformer`.
  - `old iterative workspace` is a subworkspace inside a dirty research branch.
  - Active Python entry points are concentrated under `sac`.
  - MATLAB/Simulink smoke scripts already exist under `simulink/tests`.
  - The existing SAC contract is 24-D observation / 4-D action.
- Decision: create only additive files and commit with explicit pathspecs.
- Validation:
  - Skill structure validation passed.
  - `py -3 -m sac.smoke_matlab_engine --dry-run` passed.
  - `py -3 -m pytest tests/test_hpt_v2_smoke_runner.py -q` passed.
  - MATLAB Engine mode failed because the active Python environments do not
    have the `matlab` module installed.
  - `py -3 -m sac.smoke_matlab_engine --runner batch --test interface`
    passed in about 93 s, confirming the topology1/topology2 24-D observation
    and 4-D action Simulink interface regression.
- Follow-up:
  - Install/configure MATLAB Engine for the project Python environment.
  - Investigate non-blocking MATLAB model-name shadowing warnings for
    `hpt_v2_1to1_switchlevel` and `hpt_v2_topology2_paper`.

## 2026-07-21 - Skill wording alignment

- Scope: align the project skill and autonomy documents with the current
  voltage-survival first research plan.
- Changes:
  - Clarified that the active research scope is Stage-1 switch-level
    voltage-survival specialists and Stage-2 beat-conventional boundary
    evidence before full FRT certification.
  - Replaced the absolute failed-run deletion rule with an evidence-preserving
    archive/stale policy.
  - Replaced mandatory wrappers with migration notes plus wrappers only when
    compatibility is required.
  - Clarified that short explanatory questions do not require the full
    long-running session audit.

## 2026-07-21 - Timestep voltage-survival gate recheck

- Scope: move Stage-1 voltage-survival evidence away from mean-voltage gates
  and toward sampled trajectory gates before continuing SAC training.
- Code changes:
  - `simulink/evaluators/eval_hpt_v2_control_comparison.m` now
    computes fault-window `fault_lv_min`, `fault_lv_max`, and
    `fault_lv_band_violation_*` metrics.
  - `assess_fault_voltage_survival()` no longer uses `lv_mean` or
    `lv_recovery_mean` as hard pass conditions.  It requires sampled
    fault-window LV band, GBT voltage envelope, recovery envelope, DC link, and
    action limits.
  - `sac/frt_envelope.py` and
    `sac/hpt_voltage_sac_env.py` now expose and penalize
    `fault_band_violation_*`, aligning the proxy reward vocabulary with the
    switch-level evaluator.
  - Added `sac/experiments/stage1_stage2_scenarios_20260721.csv`
    as the Stage-1/Stage-2 balanced/unbalanced scenario manifest.  Balanced
    cases are supported by the current Simulink source; unbalanced cases are
    explicitly marked `pending_source_model` because the current evaluator uses
    a three-phase programmable source with common amplitude.
- Validation:
  - `py -3 -m py_compile sac\frt_envelope.py
    sac\hpt_voltage_sac_env.py` passed.
  - `PYTHONPATH=src py -3 -m pytest tests\test_env_envelope_unification.py
    -q` passed: 14/14.
  - `py -3 -m sac.smoke_matlab_engine --runner batch --test
    interface` passed in about 94 s.
  - Accepted specialist recheck:
    `lab/results/hpt_accepted_recheck_20260721_timestep_gate/`.
    Result: 4/4 accepted switch-level specialists still pass
    voltage-survival and beat `conventional_dq`; 0/4 pass full FRT.
  - Direct CSV spot check showed the accepted policies have
    `fault_lv_band_violation_max_pu = 0`,
    `envelope_violation_max_pu = 0`, and
    `recovery_violation_max_pu = 0` in the switch-level evaluator.
- Traditional boundary smoke:
  - `control_comparison_all_fault_all_conventional_boundary_timestep_smoke_20260721_020357.csv`
    evaluated topology1/topology2 at 0.90, 0.75, 1.10, and 1.25 pu.
  - `control_comparison_all_fault_all_conventional_boundary_timestep_shallow_smoke_20260721_020600.csv`
    evaluated topology1/topology2 at 0.95 and 1.05 pu.
  - `control_comparison_topology1_fault_all_conventional_default_shallow_gate_smoke_20260721_020724.csv`
    checked `model_default` on topology1 at 0.95 and 1.05 pu.
  - Finding: the current conventional baseline does not produce a mixed
    pass/fail voltage-survival boundary under the new sampled recovery gate;
    it fails even shallow cases because recovery overshoots the +/-7% band.
- Decision:
  - Do not launch another SAC training campaign until the traditional baseline
    is retuned or a separate weaker/stronger baseline set is defined.  The
    current Stage-1 accepted SAC result is valid as voltage-survival evidence,
    but Stage-2 "beat conventional at the boundary" needs a conventional
    baseline with both pass and fail cases.

## 2026-07-21 - Conventional baseline scaling probe

- Scope: make the `conventional_dq` baseline tunable enough to locate a
  meaningful Stage-2 voltage-survival boundary.
- Code changes:
  - Added `hpt_conventional_reg_scale` and
    `hpt_conventional_energy_scale` to `add_hpt_sac_controller.m`.
  - Added default `1.0` values in both topology builders, preserving previous
    behavior unless a sweep explicitly overrides the scales.
- Validation:
  - `py -3 -m sac.smoke_matlab_engine --runner batch --test
    interface` passed after the interface change.
- Probes:
  - Topology1, shallow 0.95/1.05 pu, scale 0.40:
    LVRT failed the GBT lower envelope; HVRT passed voltage-survival.
  - Topology1, shallow 0.95/1.05 pu, scale 0.55:
    LVRT failed the GBT lower envelope; HVRT passed voltage-survival.
  - Topology1, shallow 0.95/1.05 pu, scale 0.70:
    fault-window envelope passed, but recovery envelope failed from overshoot.
  - Topology1, six-point boundary, scale 0.55:
    HVRT produced a mixed voltage-survival boundary: 1.05/1.10 pu pass,
    1.25 pu fail.  LVRT remained all fail for 0.95/0.90/0.75 pu.
  - Topology2, six-point boundary, scale 0.55:
    all tested LVRT/HVRT voltage-survival cases failed.
  - Topology2, shallow 0.95/1.05 pu, scale 0.40:
    LVRT still failed the GBT lower envelope; HVRT failed recovery/DC-link.
- Decision:
  - The new scale knobs are useful for topology1 HVRT boundary mapping.
  - Topology1 LVRT and topology2 need a phase/state-dependent conventional
    baseline or separate sag/swell scaling; a single constant scale cannot
    satisfy both fault support and recovery envelope.

## 2026-07-21 - Conventional baseline phase/recovery probe

- Scope: strengthen the traditional `conventional_dq` baseline before using it
  as the Stage-2 comparison target for specialist SAC.
- Code changes:
  - Added sag/swell-specific conventional scale multipliers:
    `hpt_conventional_reg_scale_sag`,
    `hpt_conventional_reg_scale_swell`,
    `hpt_conventional_energy_scale_sag`, and
    `hpt_conventional_energy_scale_swell`.
  - Added conventional recovery damping controls:
    `hpt_conventional_recovery_reg_gain`,
    `hpt_conventional_recovery_reg_max`, and
    `hpt_conventional_recovery_hold_s`.
  - Defaults preserve the previous conventional-dq behavior unless a sweep
    explicitly overrides the new variables.
- Validation:
  - `py -3 -m sac.smoke_matlab_engine --runner batch --test
    interface --timeout-s 900` passed after the interface migration.
- Probes:
  - `control_comparison_topology1_fault_all_conventional_phase_scale_recovery_topology1_probe_20260721_023307.csv`:
    no voltage-survival pass; failures remain dominated by recovery envelope.
  - `control_comparison_topology1_fault_all_conventional_recovery_sign_probe_topology1_20260721_023532.csv`:
    opposite recovery-action sign worsened recovery voltage.
  - `control_comparison_topology1_fault_all_conventional_aggressive_sag_recovery_topology1_probe_20260721_024319.csv`:
    stronger sag support removed the shallow fault-window violation but made
    recovery overshoot larger.
  - `control_comparison_topology2_fault_all_conventional_phase_scale_recovery_topology2_probe_20260721_024527.csv`:
    no voltage-survival pass; topology2 still fails on sampled fault and/or
    recovery envelope.
- Decision:
  - Keep topology1 HVRT scale-0.55 as the current usable conventional boundary
    evidence.
  - Do not claim topology1 LVRT or topology2 conventional boundary success yet.
    Their current value is diagnostic: they expose the rule baseline's
    fault-support versus recovery-overshoot tradeoff.
- Next action:
  - Recalibrate the proxy around sampled fault/recovery envelope metrics, then
    train trajectory/state-feedback specialist SAC against the updated
    switch-level gate, using topology1 HVRT as the first beat-conventional
    target and topology1 LVRT/topology2 as open improvement targets.

## 2026-07-21 - Balanced boundary proxy refresh and trajectory specialist matrix

- Scope: execute the balanced Stage-1/Stage-2 plan after the timestep
  voltage-survival gate migration.
- Conventional boundary:
  - Ran a 224-case balanced conventional boundary matrix with scale 0.55:
    `control_comparison_all_fault_all_balanced_boundary_scale055_timestep_20260721_20260721_033458.csv`.
  - Summary found 7 mixed pass/fail groups.  Topology1 HVRT and topology2 HVRT
    now have useful conventional pass/fail boundaries; topology1 LVRT and
    topology2 LVRT remain diagnostic all-fail groups for the conventional dq
    baseline.
- Proxy/calibration:
  - Added fault-window LV band metrics to
    `collect_hpt_v2_frt_calibration_matrix.m`.
  - Fixed the MATLAB subfunction scope bug by passing `faultSettleS`
    explicitly into `run_fixed_case`.
  - Collected pilot matrix:
    `frt_calibration_matrix_pilot_all_20260721_034530.csv`.
  - Rebuilt `sac/hpt_proxy_calibration.json`.
  - Verified rollout alignment on pilot support:
    `lab/results/hpt_proxy_alignment_pilot_20260721_034530/`.
- Specialist training:
  - topology1 HVRT retrain promoted:
    `hpt_t1_h110_bal_retrain_gate_20260721`;
    voltage-survival pass, beats conventional.
  - topology2 LVRT retrain promoted:
    `hpt_t2_l090_bal_retrain_gate_20260721`;
    voltage-survival pass, beats conventional.
  - topology2 HVRT retrain promoted:
    `hpt_t2_h110_bal_retrain_gate_20260721`;
    voltage-survival pass, beats conventional.
  - topology1 LVRT fresh retrain was diagnostic:
    `hpt_t1_l090_bal_retrain_gate96_20260721`;
    it passed fault band and GBT envelope but failed recovery envelope with
    `recovery_violation_max_pu ~= 0.0415`.
  - The previously accepted topology1 LVRT actor was revalidated successfully
    under the current timestep gate:
    `hpt_accepted_t1_l090_recheck_20260721_after_balanced`.
- Unified accepted matrix:
  - Added `sac/experiments/accepted_specialists_20260721_balanced.csv`.
  - Revalidated all four balanced specialists:
    `lab/results/hpt_accepted_balanced_matrix_20260721/`.
  - Result: 4/4 voltage-survival pass, 4/4 beat conventional, 0/4 full FRT
    pass.
- Paper-safe claim:
  - Four balanced 60-ms specialist SAC controllers survive sampled
    switch-level voltage envelopes and beat the configured conventional dq
    baseline.
  - This is still voltage-survival evidence, not full FRT certification.
- Unbalanced follow-up:
  - The current evaluator creates balanced sag/swell through a common
    programmable-source amplitude table.
  - A/B/C independent sag/swell requires a source-subsystem migration plus
    sequence/phase smoke tests before collecting unbalanced matrices.

## 2026-07-21 - Unbalanced source migration, proxy refresh, and first pipeline smoke

- Scope:
  - Start the unbalanced-FRT branch requested for A/B/C, AB/BC/CA, and balanced
    ABC fault descriptors.
- Simulink source interface:
  - Added the additive fault descriptor
    `{case_name, fault_pu, duration_s, [puA puB puC]}` to
    `eval_hpt_v2_control_comparison.m`.
  - Added matching unbalanced support to
    `collect_hpt_v2_frt_calibration_matrix.m` and
    `collect_hpt_v2_trajectory_trace.m`.
  - Existing balanced descriptors remain supported.
- Source smoke tests:
  - topology1 passed 14/14 source cases:
    `lab/results/hpt_unbalanced_source_smoke_topology1_20260721_054313/REPORT.md`.
  - topology2 passed 14/14 source cases:
    `lab/results/hpt_unbalanced_source_smoke_topology2_20260721_054730/REPORT.md`.
  - The smoke tests verified A/B/C phase RMS direction, balanced ABC sequence
    tolerance, and nonzero negative sequence for unbalanced A/AB/BC/CA cases.
- Conventional boundary:
  - Ran A/AB-only conventional boundary matrix with scale 0.55:
    `control_comparison_all_fault_all_unbalanced_boundary_a_ab_scale055_20260721_20260721_055206.csv`.
  - Summary:
    `control_comparison_all_fault_all_unbalanced_boundary_a_ab_scale055_20260721_20260721_055206_voltage_survival_BOUNDARY_REPORT.md`.
  - Mixed groups: 2/4.  LVRT is mixed for both topologies; HVRT 1.02-1.15 pu
    is all-pass under the present matrix and needs a stricter follow-up if it
    is to be used as a beat-conventional boundary.
- Proxy/calibration:
  - Fixed `HPTSACController` grid negative-sequence observation.  `obs_03`
    was previously hardcoded to zero; it now uses a quarter-cycle delayed
    grid sequence estimator.
  - Regenerated minimal unbalanced pilot matrix:
    `frt_calibration_matrix_pilot_all_20260721_061731.csv`.
  - Regenerated independent unbalanced calibration JSON:
    `sac/hpt_proxy_calibration_unbalanced_pilot.json`.
  - Reward alignment:
    `lab/results/hpt_v2_reward_alignment/reward_alignment_pilot_all_20260721_061731_REPORT.md`.
    Reg and joint sweep ranking is useful (`rho ~= 0.85-0.96`); energy-only
    ranking remains weak (`rho ~= 0.12` for topology1 and `0.36` for
    topology2).
- First unbalanced trajectory pipeline smoke:
  - Ran topology1 A-phase LVRT 0.90 pu / 60 ms rule-teacher BC smoke:
    `lab/results/hpt_unbalanced_topology1_a_lvrt090_pipeline_smoke_20260721/`.
  - The actor training/export/evaluation pipeline completed.
  - Switch-level result was diagnostic, not promoted:
    - conventional score `117.681`, actor score `105.973`;
    - actor did not beat baseline by the current gate because both failed
      voltage survival;
    - actor fault band and GBT envelope passed, but recovery envelope failed
      (`recovery_violation_max_pu ~= 0.0335`);
    - full FRT failed on recovery and grid-current criteria.
- Decision:
  - The unbalanced source and grid observation interfaces are now usable.
  - Do not claim unbalanced SAC success yet.
  - Next research should focus on recovery-window trajectory shaping and
    energy-head calibration before launching the full A/AB topology matrix.

## 2026-07-21 - Topology1 A-phase LVRT trajectory specialist recovery fix

- Scope:
  - Continue the unbalanced trajectory/state-feedback SAC branch for
    topology1 A-phase LVRT 0.90 pu / 60 ms.
- Interface fix:
  - Added `--fault-phase-pu` support to
    `sac/search_hpt_frt_trajectory_cem.py`.
  - The CEM proxy scenario now derives `fault_phase_key` and approximate
    negative-sequence magnitude from the A/B/C fault vector, and switch-level
    validation now uses the same four-field fault descriptor as the evaluator.
- Trajectory search:
  - Ran
    `hpt_unbalanced_t1_a_lvrt090_cem_recovery_probe_20260721`.
  - No 0-ms-settle CEM candidate passed voltage-survival.
  - Diagnosis: fault-window envelope violation was dominated by the initial
    controller response delay.  With a 20-ms response/settle window, candidate
    c002 passed switch-level voltage-survival.
- Teacher evidence:
  - Passing teacher trajectory:
    `lab/results/hpt_unbalanced_t1_a_lvrt090_cem_recovery_probe_20260721/switch_candidate_001_it-1_c002/hpt_sac_trajectory.mat`.
  - Recheck:
    `hpt_unbalanced_t1_a_lvrt090_c002_settle20_recheck_20260721`.
  - Result: `trajectory_voltage_pass=true`, trajectory score `115.196`
    versus conventional score `117.680`.
- Actor evidence:
  - Trained trajectory-teacher BC actor:
    `hpt_unbalanced_t1_a_lvrt090_trajteacher_smoke_20260721`.
  - With the default 1-ms actor command filter, the actor still failed only
    the recovery envelope (`policy_recovery_violation_max_pu ~= 0.00307`).
  - Direct switch-level recheck with `hpt_compare_actor_filter_tau=0` passed
    voltage-survival:
    `control_comparison_topology1_fault_all_hpt_unbalanced_t1_a_lvrt090_bc0_actor_tau0_recheck_20260721_20260721_124509.csv`.
  - Tau-0 actor metrics: voltage-survival pass, fault-band violation `0`,
    envelope violation `0`, recovery violation `0`, control score `103.650`
    versus conventional `117.680`.
- Decision:
  - Treat topology1 A-phase LVRT as the first unbalanced voltage-survival
    specialist success, conditional on explicit zero actor-output filtering.
  - Do not claim full FRT: grid-current and reactive-current criteria still
    fail or remain not evaluated.
  - Next action: repeat the trajectory-teacher workflow for topology1 AB LVRT,
    then carry the same recovery/actor-filter lessons into topology2.

## 2026-07-21 - Topology1 AB LVRT unbalanced specialist promotion

- Scope:
  - Extend the unbalanced minimum matrix from A-phase LVRT to AB LVRT for
    topology1.
- Trajectory search:
  - Ran
    `hpt_unbalanced_t1_ab_lvrt090_cem_recovery_probe_20260721`.
  - CEM found one switch-level voltage-survival trajectory teacher:
    candidate c002 with `reg_boost=0.48`, `reg_recovery=0.30`, and
    `recovery_taper_ms=45`.
  - Teacher result: voltage-survival pass, score `113.947` versus
    conventional score `116.292`.
- Actor training:
  - Initial 60-epoch BC with `actor_filter_tau=0` did not pass voltage
    survival; it still had small fault/recovery envelope violations.
  - Strengthened BC imitation with:
    `switch_trace_repeat=64`, `fault_window_repeat_mult=6`,
    `recovery_window_repeat_mult=8`, `bc_obs_noise_std=0.002`,
    `bc_obs_noise_repeat=2`, `action_weights=8,1,0.5,0.5`,
    and `teacher_prior_weight=80`.
  - Promoted run:
    `hpt_unbalanced_t1_ab_lvrt090_trajteacher_tau0_bcstrong_20260721`.
  - Result: voltage-survival pass, beats conventional, fault-band violation
    `0`, envelope violation `0`, recovery violation `0`, score `104.331`
    versus conventional `116.292`.
- Accepted matrix:
  - Added
    `sac/experiments/accepted_specialists_20260721_unbalanced.csv`.
  - Current unbalanced accepted rows:
    topology1 A-phase LVRT 0.90 pu / 60 ms and topology1 AB LVRT
    0.90 pu / 60 ms.
- Decision:
  - For unbalanced trajectory specialists, use explicit `actor_filter_tau=0`
    unless a later controller/filter design is validated in switch-level.
  - Strong BC settings are required for AB because boundary-action imitation
    errors at fault/recovery transitions are enough to violate the timestep
    envelope.
  - Next action: move to topology2 A/AB LVRT, with extra attention to energy
    branch calibration and DC-link response.

## 2026-07-21 - Topology2 A-phase LVRT diagnostics

- Scope:
  - Start topology2 unbalanced LVRT after topology1 A/AB success.
- CEM result:
  - Ran
    `hpt_unbalanced_t2_a_lvrt090_cem_recovery_probe_20260721`.
  - No CEM-selected low-reg candidate passed; all were strongly undervoltage
    (`LV_mean ~= 160-166 V`).
  - Diagnosis: the existing topology2 LVRT CEM anchor/proxy ranking favored
    too-small `m_reg_d` for unbalanced A-phase LVRT.
- Polarity/amplitude probes:
  - `m_reg_d=-0.20` worsened undervoltage (`LV_mean ~= 158.7 V`).
  - `m_reg_d=0.48` improved but remained undervoltage (`LV_mean ~= 182.7 V`).
  - `m_reg_d=0.80` fixed the fault-window envelope but failed recovery
    overvoltage.
  - Added high-boost topology2 LVRT anchors to
    `search_hpt_frt_trajectory_cem.py` for future CEM runs.
- Passing teacher trajectories:
  - Generated and validated
    `lab/results/hpt_manual_trajectories/t2_a_lvrt090_boost080_rec038.mat`.
    It passed voltage-survival with fault/recovery violations all zero.
  - Generated and validated
    `lab/results/hpt_manual_trajectories/t2_a_lvrt090_boost080_rec045.mat`.
    It also passed voltage-survival and raised the recovery mean.
- Actor attempts:
  - `hpt_unbalanced_t2_a_lvrt090_trajteacher_tau0_bcstrong_20260721`
    failed after strong BC: fault envelope and recovery envelope were both
    violated.
  - `hpt_unbalanced_t2_a_lvrt090_trajteacher_tau0_dagger1_20260721`
    improved after one DAgger iteration: fault envelope violation became zero,
    score improved to `125.423` versus conventional `133.749`, but recovery
    violation remained `0.0131 pu`; not promoted.
  - `hpt_unbalanced_t2_a_lvrt090_rec045_tau0_dagger1_20260721`
    over-supported recovery and became worse; not promoted.
- Decision:
  - Do not add topology2 A-phase LVRT to the accepted matrix yet.
  - The current topology2 bottleneck is actor reproduction of high-boost /
    recovery-transition trajectories, not lack of a feasible teacher.
  - Next action should focus on smoother topology2 teachers or explicit
    recovery/head shaping before training topology2 AB.

## 2026-07-21 - Topology2 A-phase LVRT smoother teacher / actor test

- Scope:
  - Continue topology2 A-phase LVRT 0.90 pu / 60 ms after finding that fixed
    high-boost actions can pass the fault window but actor reproduction fails
    around recovery.
- Interface addition:
  - Added a reproducible `fault_recovery` preset to
    `sac/build_hpt_action_trajectory.py`.
  - The preset encodes:
    base action before the event, high fault support action, and lower recovery
    action with a configurable fault-clear-to-recovery ramp.  This replaces
    one-off manual MAT generation for topology2 recovery-shaping probes.
- Experiment hygiene:
  - A parallel validation probe showed that two MATLAB evaluator calls writing
    the same `hpt_v2_control_comparison` pattern can race when the Python
    wrapper uses latest-file discovery.  Treat the parallel pair as diagnostic
    only.
  - Re-ran the selected teacher sequentially:
    `hpt_unbalanced_t2_a_lvrt090_faultrec080_038_130_teacher_seq_20260721`.
- Teacher evidence:
  - Source trajectory:
    `lab/results/hpt_manual_trajectories/t2_a_lvrt090_faultrec080_038_130.mat`.
  - Switch-level teacher result: voltage-survival pass, fault-band violation
    `0`, envelope violation `0`, recovery violation `0`, recovery mean
    `203.768 V`, Vdc range `718.783-920.518 V`.
- Actor evidence:
  - Ran
    `hpt_unbalanced_t2_a_lvrt090_faultrec038130_tau0_dagger1_20260721`
    with stronger BC/DAgger settings:
    `actor_filter_tau=0`, `epochs=160`, `switch_trace_repeat=80`,
    `fault_window_repeat_mult=8`, `recovery_window_repeat_mult=10`,
    `action_weights=12,1,0.5,0.5`, and `teacher_prior_weight=120`.
  - BC0 failed both voltage and recovery timestep envelopes.
  - DAgger1 improved fault-window behavior but still failed recovery:
    score `130.573` versus conventional `133.749`, fault-band violation `0`,
    envelope violation `0`, recovery violation `0.0768 pu`.
  - Trace alignment still showed large regulating-axis closed-loop mismatch
    (`m_reg_d_mae ~= 0.0889`, max error `0.8`), despite very small supervised
    training loss.
- Decision:
  - Do not promote topology2 A-phase LVRT yet.
  - The current bottleneck is no longer finding a passing trajectory teacher;
    it is actor closed-loop state/phase disambiguation during the recovery
    transition.
  - Next action should add a recovery-status/time-context observation or a
    dedicated recovery head/gate for topology2 before more topology2 AB/HVRT
    specialist training.

## 2026-07-21 - Grid-sequence observation normalization diagnostic

- Scope:
  - Debug why topology2 A-phase LVRT actors kept high regulating injection
    into the evaluator recovery window.
- Finding:
  - The trajectory trace showed evaluator `window_zone=recovery`, but
    HPTSACController observation still reported `fault_active=1`,
    `recovery_active=0`.
  - The same trace showed controller grid positive sequence near `0.6-0.7 pu`
    after fault clearing because `g_vpos` was normalized to ideal 10-kV phase
    RMS instead of the local measured pre-fault sequence baseline.
  - The unbalanced source smoke tests had only checked phase ordering and
    negative-sequence presence; they did not enforce absolute commanded
    per-phase pu recovery.
- Interface fix:
  - Added startup blanking for measured-fault detection in
    `add_hpt_sac_controller.m`.
  - Added local startup normalization of grid positive/negative sequence
    observation using the measured pre-fault sequence baseline.
  - Relaxed controller internal fault/recovery state thresholds to match the
    normalized local grid observation.
- Smoke:
  - `py -3 -m sac.smoke_matlab_engine --runner batch --test
    interface --timeout-s 900` passed after the controller-code migration.
  - A topology2 teacher trace
    `trajectory_trace_topology2_gridnorm_t2_teacher_probe_20260721_20260721_143845.csv`
    confirmed pre-fault `fault_active=0` and recovery-window
    `recovery_active=1` appears after source recovery.
- Consequence:
  - Existing unbalanced accepted rows were generated under the old observation
    semantics and must not be quoted as final evidence without rerun.
  - Added
    `sac/experiments/stale_specialists_after_gridnorm_20260721.csv`
    for the old topology1 A/AB unbalanced specialists.
- Follow-up experiment:
  - Reran topology2 A-phase LVRT with the normalized grid observation:
    `hpt_unbalanced_t2_a_lvrt090_gridnorm038130_tau0_dagger1_20260721`.
  - The previous teacher trajectory became a near miss under the stricter
    regenerated model (`recovery_violation_max_pu ~= 0.0029`).
  - Actor still failed voltage-survival:
    - BC0: fault-band pass, but voltage envelope and recovery envelope failed.
    - DAgger1: fault-band, voltage envelope, and recovery envelope failed.
- Decision:
  - Stop treating topology2 failure as mainly a BC-strength issue.
  - Next research should first rebuild the unbalanced source/observation
    smoke gate to include absolute pre/fault/recovery sequence levels, then
    regenerate topology1/topology2 unbalanced trajectory teachers and only
    then train specialists.

## 2026-07-21 - Unbalanced source/observation smoke gate rebuild

- Scope:
  - Implement the next gate before restarting unbalanced trajectory specialist
    training.
  - Goal: verify that the controlled A/B/C source command, source recovery,
    and controller observation channels are usable across pre-fault,
    fault-window, and recovery-window intervals.
- Interface changes:
  - Added `Vgrid_cmd_abc` logging for the controlled phase-voltage source used
    by unbalanced faults.
  - Added `source_*` pre/fault/recovery window fields to
    `eval_hpt_v2_control_comparison.m` so source-command correctness is not
    confused with plant-side `grid_*` dynamics.
  - Added `grid_*` and `obs_*` pre/fault/recovery window fields for diagnostics
    and proxy calibration.
  - Added `hpt_sac_gridnorm_startup_s` to the HPTSACController interface while
    preserving the 24-observation / 4-action contract.
- Debug findings:
  - The first strict topology2 smoke failed because it was using plant-side
    `Vpri_abc` as if it were the source command.
  - After adding `Vgrid_cmd_abc`, the source-command metrics still failed until
    the evaluator used the command signal's own `StructureWithTime` time vector.
  - The controller pre-fault state initially showed stale recovery/fault state;
    startup blanking now clears both `fault_active` and `recovery_active` before
    the configured startup-normalization interval ends.
- Validation:
  - MATLAB interface smoke passed after the controller port migration:
    `py -3 -m sac.smoke_matlab_engine --runner batch --test interface --timeout-s 900`.
  - Topology2 unbalanced source/observation smoke passed:
    `lab/results/hpt_unbalanced_source_smoke_topology2_20260721_164301/REPORT.md`.
  - Topology1 unbalanced source/observation smoke passed:
    `lab/results/hpt_unbalanced_source_smoke_topology1_20260721_164456/REPORT.md`.
- Decision:
  - The source/observation gate is now usable for regenerating the unbalanced
    conventional boundary matrix.
  - Do not cite pre-gridnorm unbalanced accepted specialists without rerun.
  - Next action: regenerate mixed pass/fail unbalanced conventional boundary
    evidence, then recalibrate the proxy with the new `source_*`, `grid_*`, and
    timestep-envelope fields before training new trajectory/state-feedback
    specialists.

## 2026-07-21 - Unbalanced conventional boundary regeneration attempt

- Scope:
  - Run the first post-gridnorm unbalanced conventional boundary matrix after
    the source/observation smoke gate passed.
- Command:
  - `matlab -batch "cd('E:/research_space/Hybrid-power-transformer/simulink'); hpt_unbalanced_boundary_run_label='unbalanced_conventional_boundary_gridnorm_20260721'; run(fullfile(pwd,'sweeps','sweep_hpt_v2_unbalanced_conventional_boundary.m'));"`
- Result:
  - Output CSV:
    `lab/results/hpt_v2_control_comparison/control_comparison_all_fault_all_unbalanced_conventional_boundary_gridnorm_20260721_20260721_165018.csv`.
  - Matrix size: 32 switch-level `conventional_dq` cases
    (`topology1/topology2` x A/AB x LVRT/HVRT depths).
  - Voltage-survival pass count: `0 / 32`.
  - Full-FRT pass count: `0 / 32`.
- Main diagnosis:
  - This is not a usable mixed pass/fail boundary yet.
  - Topology1 failed mainly recovery/fault-band voltage because the
    `conventional_dq` rule path did not respond when mild unbalanced source
    faults did not trip the grid-side `fault_active` flag.
  - Topology2 failed mainly DC-link survival/recovery in this conventional
    configuration.
- Traditional baseline fixes attempted:
  - Added an LV-voltage-error fallback branch to `HPTSACController` policy
    mode `0`, so `conventional_dq` can respond when LV voltage is out of band
    even if grid-side `fault_active` is low.
  - Added nonzero tuned-v1 recovery/LV-error gains:
    topology1 `gain=4`, `max=0.65`; topology2 `gain=4`, `max=0.80`.
  - Topology1 two-case pilot with default sweep scale improved recovery from
    about `174 V` to about `182-183 V`, but still failed voltage survival.
  - Strong pilot (`gain=8`, `max=0.80`, scale `1.0`) improved recovery to
    about `185 V`, but still failed.
  - Extreme pilot (`gain=20`, `max=0.80`) still failed; therefore simple gain
    increase is not enough.
- Decision:
  - Do not use the 0/32 conventional matrix as the SAC comparison baseline.
  - Next action should be a focused traditional-baseline tuning sweep over
    injection phase/RegPolarity/recovery law, not SAC retraining.
  - Only after the conventional matrix has mixed pass/fail rows should proxy
    recalibration and specialist SAC retraining resume.

## 2026-07-21 - Stage-2 balanced/unbalanced boundary and proxy update

- Scope:
  - Continue the staged voltage-survival workflow requested by the user:
    mixed pass/fail boundary first, proxy recalibration second, and only then
    trajectory/state-feedback specialist training.
- Balanced status:
  - Confirmed current balanced accepted matrix:
    `sac/experiments/accepted_specialists_20260721_balanced.csv`.
  - It contains four switch-level voltage-survival specialists:
    topology1 LVRT 0.90 pu / 60 ms, topology1 HVRT 1.10 pu / 60 ms,
    topology2 LVRT 0.90 pu / 60 ms, and topology2 HVRT 1.10 pu / 60 ms.
  - All four rows report zero timestep fault-band, envelope, and recovery
    violations, DC-link survival, and lower score than the corresponding
    traditional baseline.
  - This remains voltage-survival evidence only, not full FRT certification.
- Conventional boundary debugging:
  - Added `tune_hpt_v2_unbalanced_conventional_phase.m` as a diagnostic sweep
    over `hpt_sac_reg_polarity` and `hpt_inj_phase_offset`.
  - Added `hpt_unbalanced_boundary_modes` and
    `hpt_unbalanced_boundary_model_params` to
    `sweep_hpt_v2_unbalanced_conventional_boundary.m`.
  - `conventional_dq` topology1 A-phase shallow unbalanced pilot remained
    all-fail even after phase/polarity and chopper pilots; best cases were
    still limited by timestep voltage/recovery envelope or DC-link overvoltage.
  - `legacy_conventional` gave a usable topology1 unbalanced voltage-survival
    boundary:
    `control_comparison_topology1_fault_all_unbalanced_current_topology1_a_legacy_pilot_20260721_20260721_190957.csv`.
    A-phase LVRT 0.98/0.95 failed, while A-phase HVRT 1.02/1.05 passed the
    voltage-survival gate.
- New unbalanced boundary matrix:
  - Generated
    `lab/results/hpt_v2_control_comparison/control_comparison_all_fault_all_unbalanced_legacy_mixed_boundary_20260721_20260721_191851.csv`.
  - Voltage-survival pass count:
    topology1 `12 / 16`, topology2 `0 / 16`.
  - Full-FRT pass count remains `0 / 32`, mainly because grid-current/reactive
    current criteria are not yet satisfied.
  - Use this matrix only as a voltage-survival boundary, not as a full FRT
    baseline.
- Unbalanced proxy pilot:
  - Generated an unbalanced fixed-action calibration pilot:
    `lab/results/hpt_v2_frt_calibration_matrix/frt_calibration_matrix_pilot_all_20260721_193807.csv`
    with A/AB LVRT 0.90 and A/AB HVRT 1.10 for topology1/topology2.
  - Wrote separate calibration file:
    `sac/hpt_proxy_calibration_unbalanced_pilot.json`.
  - Rollout alignment is not yet final-quality:
    LV mean MAE about `0.0106 pu`, Vdc mean MAE about `0.0122 pu`, maximum Vdc
    error about `0.443 pu`, and recovery-violation max error about `0.085 pu`.
  - Reward alignment has two weak groups:
    topology1 HVRT `energy_sweep` and topology1 HVRT `reg_sweep`.
- Decision:
  - Balanced voltage-survival evidence is usable for the current staged claim.
  - Do not train unbalanced SAC directly from the unbalanced proxy yet.
  - Next unbalanced step should either improve proxy calibration for topology1
    HVRT and topology2 DC-link dynamics, or generate switch-level trajectory
    teachers and train from traces while treating proxy ranking as diagnostic.

## 2026-07-21 - Stage-2 evidence index refresh

- Scope:
  - Consolidate the current Stage-2 evidence after grid-sequence normalization,
    timestep-envelope gating, and the `old iterative workspace` directory cleanup.
  - Avoid future confusion between voltage-survival evidence and full FRT
    certification.
- Updated artifacts:
  - Rewrote
    `docs/specs/algorithms/hpt-sac-controller/hpt-sac-controller-stage1-stage2-progress-2026-07-21.md`
    as the current Stage-2 evidence index.
  - Updated `sac/experiments/README.md` with the current balanced
    accepted matrix, unbalanced mixed boundary, unbalanced source smoke reports,
    unbalanced proxy pilot, and the split between voltage-survival promotion and
    full FRT certification.
- Verification:
  - Recomputed the key counts directly from current CSV artifacts:
    - balanced accepted rows: `4`;
    - balanced switch-level voltage-survival pass: `4 / 4`;
    - balanced beat-conventional rows: `4 / 4`;
    - balanced full-FRT pass: `0 / 4`;
    - balanced maximum fault-band/envelope/recovery violation: all `0`;
    - unbalanced boundary rows: `32`;
    - topology1 unbalanced voltage-survival pass: `12 / 16`;
    - topology2 unbalanced voltage-survival pass: `0 / 16`;
    - unbalanced full-FRT pass: `0 / 32`;
    - unbalanced proxy pilot rows: `104`.
- Decision:
  - The current paper-safe Stage-2 claim is the balanced 4-case
    switch-level voltage-survival specialist matrix.
  - The unbalanced source/observation interface is usable, but the unbalanced
    SAC specialists are not yet promotable under the post-gridnorm gate.
  - The unbalanced proxy pilot is diagnostic only; next research should improve
    topology1 HVRT weak-group alignment and topology2 energy/DC-link dynamics
    before unbalanced SAC training is treated as evidence.

## 2026-07-21 - Topology2 energy-branch pilot and trajectory-input fix

- Scope:
  - Start the next unbalanced/proxy blocker: topology2 energy branch and
    DC-link command-response calibration.
- Command:
  - `matlab -batch "cd('E:/research_space/Hybrid-power-transformer/simulink'); hpt_energy_calib_run_label='stage2_t2_energy_pilot_20260721'; hpt_energy_calib_faults={'lvrt090_reg014_down004',0.90,0.14,0.14,-0.04;'hvrt110_reg000_rec024',1.10,0.00,0.00,0.24}; hpt_energy_calib_d_values=[-0.30 0.00 0.30]; hpt_energy_calib_q_values=0.0; hpt_energy_calib_id_values=20.0; hpt_energy_calib_chop_values=780.0; hpt_energy_calib_rchop_scales=0.65; run(fullfile(pwd,'calibration','calibrate_hpt_v2_topology2_energy_branch.m'));"`.
- Initial finding:
  - All three requested `m_energy_d` values produced identical LV/Vdc rows.
  - CSV `cmd_m_energy_d_mean` was `0` for `cmd_m_energy_d=-0.3/0/+0.3`.
  - Diagnosis: the calibration script saved `hpt_sac_trajectory.mat` but did
    not inject `hpt_traj_t` and `hpt_traj_action` into the model workspace via
    `SimulationInput`.  Therefore the built model kept its default zero
    trajectory action.
- Fix:
  - Updated
    `simulink/calibration/calibrate_hpt_v2_topology2_energy_branch.m`
    to set `hpt_traj_t` and `hpt_traj_action` with `in.setVariable(...,
    'Workspace', M)` before simulation.
- Re-run:
  - `stage2_t2_energy_pilot_after_trajinput_fix_20260721`.
  - Output CSV:
    `lab/results/hpt_v2_topology2_energy_branch_calibration/topology2_energy_branch_stage2_t2_energy_pilot_after_trajinput_fix_20260721_20260721_205941.csv`.
- Result after fix:
  - `cmd_m_energy_d_mean` now tracks the request:
    about `-0.2999`, `0`, and `+0.2999`.
  - LVRT 0.90 pilot remains failed for all energy commands.  In this anchor,
    fault LV is only about `146-147 V`, so regulating boost is insufficient;
    energy-d cannot rescue the case by itself.
  - HVRT 1.10 pilot remains failed by recovery envelope.  More positive
    `m_energy_d` raises recovery voltage and worsens recovery violation; negative
    `m_energy_d` is less harmful but still fails the recovery envelope.
  - DC link remains inside the survival range for this small sweep
    (`vdc_min` about `761-770 V`, `vdc_max` below `1000 V`).
- Decision:
  - The energy calibration path is now functional enough to expose command
    direction.
  - The next topology2 experiment should sweep regulating boost and energy
    together; an energy-only d-axis sweep around a weak regulating anchor is not
    sufficient for LVRT voltage survival.
  - Proxy updates should keep command and measured response separate, and should
    not learn from the pre-fix energy pilot where trajectory commands were not
    actually injected.

## 2026-07-21 - Topology2 joint regulating/energy LVRT pilot

- Scope:
  - Follow the repaired energy calibration path with a strong topology2 LVRT
    regulating anchor to check whether energy commands can stabilize DC link or
    recovery when `m_reg_d` provides enough voltage boost.
- Command:
  - `matlab -batch "cd('E:/research_space/Hybrid-power-transformer/simulink'); hpt_energy_calib_run_label='stage2_t2_energy_joint_lvrt_pilot_20260721'; hpt_energy_calib_faults={'lvrt090_reg080_rec038',0.90,0.00,0.80,0.38}; hpt_energy_calib_d_values=[-0.30 0.00 0.30]; hpt_energy_calib_q_values=0.0; hpt_energy_calib_id_values=20.0; hpt_energy_calib_chop_values=780.0; hpt_energy_calib_rchop_scales=0.65; run(fullfile(pwd,'calibration','calibrate_hpt_v2_topology2_energy_branch.m'));"`.
- Result:
  - Output CSV:
    `lab/results/hpt_v2_topology2_energy_branch_calibration/topology2_energy_branch_stage2_t2_energy_joint_lvrt_pilot_20260721_20260721_210334.csv`.
  - All three rows failed voltage survival.
  - The strong regulating anchor lifted fault LV to about `225 V`, but this is
    too high for the timestep envelope and recovery stayed high
    (`228-232 V`).
  - DC link collapsed below the survival lower bound, with `vdc_min` about
    `556-561 V`.
  - Negative `m_energy_d` was the least harmful of the three tested d-axis
    commands, but it did not prevent the DC-link failure or recovery violation.
- Decision:
  - topology2 LVRT control cannot be reduced to energy-branch sign selection.
  - The next useful search space is constrained joint trajectory search over
    `m_reg_d` and energy d/q with explicit DC-link and timestep-recovery
    penalties.
  - For proxy calibration, include both under-boosted and over-boosted
    regulating anchors so the proxy learns the LV/DC tradeoff instead of only
    local energy response.

## 2026-07-21 - Topology2 LVRT constrained joint sweep finds pass region

- Scope:
  - Continue topology2 LVRT joint calibration after the broad matrix showed
    under-boost, over-boost, and DC-link-collapse boundaries.
- Broad retry matrix:
  - Command:
    `stage2_t2_lvrt_joint_reg_energy_grid_retry_20260721`.
  - Output CSV:
    `lab/results/hpt_v2_topology2_energy_branch_calibration/topology2_energy_branch_stage2_t2_lvrt_joint_reg_energy_grid_retry_20260721_20260721_211204.csv`.
  - Result:
    - `reg_fault=0.50`, `reg_recovery=0.08` was closest but failed recovery
      envelope only (`recovery_violation_max_pu ~= 0.0104` at
      `m_energy_d=+0.30`).
    - `reg_fault=0.60/0.70` failed by timestep voltage envelope.
    - `reg_fault=0.80` failed by DC-link collapse.
- Fine sweep:
  - Command:
    `stage2_t2_lvrt_reg_recovery_fine_ed030_20260721`.
  - Output CSV:
    `lab/results/hpt_v2_topology2_energy_branch_calibration/topology2_energy_branch_stage2_t2_lvrt_reg_recovery_fine_ed030_20260721_20260721_211456.csv`.
  - Search space:
    `reg_fault = 0.48/0.50/0.52/0.54`,
    `reg_recovery = 0.08/0.12/0.16`, fixed `m_energy_d=+0.30`.
  - Passing switch-level voltage-survival rows:
    - `reg_fault=0.48`, `reg_recovery=0.16`, `m_energy_d=+0.30`:
      `LV_fault=217.05 V`, `LV_recovery=202.07 V`,
      `Vdc=761.40-970.48 V`, envelope/recovery violations `0`.
    - `reg_fault=0.50`, `reg_recovery=0.16`, `m_energy_d=+0.30`:
      `LV_fault=218.80 V`, `LV_recovery=202.74 V`,
      `Vdc=761.40-970.48 V`, envelope/recovery violations `0`.
    - `reg_fault=0.52`, `reg_recovery=0.16`, `m_energy_d=+0.30`:
      `LV_fault=219.87 V`, `LV_recovery=202.51 V`,
      `Vdc=759.15-970.48 V`, envelope/recovery violations `0`.
- Warnings:
  - MATLAB emitted repeated warnings that the on-disk and loaded topology2
    model were both modified during the fine sweep.  The sweep still completed
    and saved valid CSV/MAT results, but the calibration workflow should be
    hardened before larger unattended matrices.
  - A batch MATLAB process remained after completion and was killed manually to
    clear model-file locks.
- Decision:
  - topology2 LVRT now has a switch-level voltage-survival trajectory seed
    region.  Use `reg_fault ~= 0.50`, `reg_recovery ~= 0.16`,
    `m_energy_d ~= +0.30`, and `actor_filter_tau=0` as the next trajectory
    teacher starting point.
  - This is still a calibrated trajectory/action seed, not a trained SAC actor.
  - Next action: convert the best passing row into a trajectory MAT, collect
    switch-level traces, and train a topology2 LVRT trajectory/state-feedback
    specialist against the current timestep gate.

## 2026-07-21 - Topology2 LVRT trajectory seed validated by standard evaluator

- Scope:
  - Convert the topology2 LVRT pass-region seed into a reusable trajectory MAT
    and validate it through the standard trajectory switch-level evaluator.
- Trajectory:
  - Generated manual piecewise trajectory:
    `lab/results/hpt_manual_trajectories/t2_lvrt090_reg050_rec016_ed030_piecewise_20260721/hpt_sac_trajectory.mat`.
  - Schedule:
    - pre-fault action `[0, 0, 0, 0]`;
    - fault-window action `[0.50, 0, 0.30, 0]`;
    - recovery action `[0.16, 0, 0.30, 0]`.
  - A first attempt with `build_hpt_action_trajectory --preset fault_recovery`
    was rejected because the preset ramped `m_reg_d` from about `0.40` down to
    `0.16`, which did not match the calibration seed.
- Standard validation:
  - Command:
    `py -3 -m sac.validate_hpt_trajectory_switchlevel --run-id hpt_t2_lvrt090_reg050_rec016_ed030_piecewise_validate_20260721 --topology topology2 --fault-pu 0.90 --duration-s 0.060 --fault-start 0.080 --fault-stop-margin 0.125 --fault-settle-s 0.020 --trajectory-file lab/results/hpt_manual_trajectories/t2_lvrt090_reg050_rec016_ed030_piecewise_20260721/hpt_sac_trajectory.mat --chopper-threshold 780 --rchop-scale 0.65 --timeout-s 900`.
  - Output control CSV:
    `lab/results/hpt_v2_control_comparison/control_comparison_topology2_fault_all_traj_topology2_constant_lvrt_060ms_0p900pu_20260721_211931.csv`.
- Result:
  - `trajectory_voltage_pass = true`.
  - `trajectory_beats_baseline = true`.
  - `trajectory_score = 128.799`, baseline score `264.260`.
  - `trajectory_lv_mean = 216.953 V`.
  - `trajectory_lv_recovery_mean = 201.074 V`.
  - `trajectory_vdc_min = 760.765 V`, `trajectory_vdc_max = 978.342 V`.
  - `trajectory_envelope_violation_max_pu = 0`.
  - `trajectory_recovery_violation_max_pu = 0`.
  - The fixed-action comparator failed, confirming that the time-varying
    trajectory schedule is necessary.
- Decision:
  - topology2 LVRT now has a validated switch-level trajectory teacher seed.
  - The next work item is behavior-cloning/DAgger actor training from this
    trajectory, with explicit checks that the actor reproduces the
    fault-to-recovery transition instead of collapsing back into a fixed action.

## 2026-07-21 - Topology2 LVRT trajectory actor campaign exposes state-feedback gap

- Scope:
  - Train a topology2 LVRT 0.90 pu / 60 ms state-feedback actor from the
    validated piecewise trajectory seed and validate it in the switch-level
    model.
- Engineering fixes:
  - Updated `sac/run_hpt_trajectory_specialist_campaign.py` so
    trace collection tolerates a MATLAB nonzero return only when the expected
    trace CSV is actually produced.
  - Added one automatic retry for initial trajectory validation when MATLAB
    returns a transient `matlab_failed` summary.
- Main campaign:
  - Run directory:
    `lab/results/hpt_t2_lvrt090_reg050_rec016_ed030_actor_bc_20260721_r3`.
  - Teacher trajectory:
    `[0,0,0,0]` before the fault,
    `[0.50,0,0.30,0]` during the fault, and
    `[0.16,0,0.30,0]` during recovery.
  - Teacher validation passed again:
    `trajectory_voltage_pass=true`, `trajectory_score=128.799`,
    zero timestep envelope and recovery violations.
- Actor results:
  - `bc0` did not promote:
    `policy_voltage_pass=false`,
    reason `timestep_fault_lv_band;timestep_voltage_envelope`,
    fault LV min/max `173.12/204.94 V`,
    `Vdc=760.29-967.01 V`.
  - `dagger1` did not promote:
    `policy_voltage_pass=false`,
    reason `timestep_fault_lv_band;dc_link_bounds`,
    fault LV min/max `192.04/250.30 V`,
    `Vdc=598.35-1072.70 V`.
  - The campaign selected `bc0` by score, but
    `promoted_voltage_survival=false` and
    `promoted_beats_baseline=false`.
- Trace-alignment diagnosis:
  - Teacher fault-window action was exactly
    `m_reg_d=0.50`, `m_energy_d=0.30`.
  - Final actor trace had large deviations:
    `m_reg_d_mae=0.159`, `m_reg_d_max_abs_error=0.543`,
    `m_energy_d_mae=0.072`,
    LV RMS MAE `18.12 V`, and Vdc MAE `29.69 V`.
  - The actor starts producing nonzero action during prefault/startup
    transients and does not reproduce the sharp transition from the fault
    action to the recovery action.
- Manual mode comparison:
  - CSV:
    `lab/results/hpt_v2_control_comparison/control_comparison_topology2_fault_all_manual_mode_compare_hpt_t2_lvrt090_reg050_rec016_ed030_actor_bc_20260721_r3_bc0_20260721_215429.csv`.
  - `sac_actor_raw_guard0` also failed; startup/fault gating did not make this
    actor promotable.
  - `sac_actor_always_raw` remained the better of the two actor modes, but it
    still failed by timestep LV voltage criteria.
- Decision:
  - The validated topology2 LVRT trajectory seed is still useful evidence and
    a teacher source.
  - The current BC/DAgger actor is not promotable.  Do not add it to the
    accepted matrix.
  - The next actor-training revision should explicitly handle startup/fault/
    recovery phase separation, either by filtering startup samples, adding a
    stronger clock/window feature contract, or training separate phase heads
    before returning to unified state-feedback SAC.

## 2026-07-21 - Topology2 actor phase-observation blocker confirmed

- Scope:
  - Determine whether the failed topology2 LVRT BC/DAgger actor was primarily
    a training-loss issue or an observation/phase-identification issue.
- Evidence:
  - Teacher trace:
    `lab/results/hpt_v2_trajectory_traces/trajectory_trace_topology2_trajectory_teacher_20260721_213814.csv`.
  - Final actor trace:
    `lab/results/hpt_v2_trajectory_traces/trajectory_trace_topology2_final_actor_trace_20260721_214929.csv`.
- Findings:
  - The teacher applies exactly zero action before the fault, `m_reg_d=0.50`
    during the fault, and `m_reg_d=0.16` in recovery.
  - The actor produces nonzero commands before the scheduled fault:
    prefault `m_reg_d` mean about `0.186`, with peaks above `0.54`.
  - During the fault, the actor under-reproduces the teacher boost:
    fault `m_reg_d` mean about `0.323` instead of `0.50`.
  - During recovery, the actor does not consistently settle to the recovery
    action:
    recovery `m_reg_d` mean about `0.272` instead of `0.16`.
  - The actor closed-loop recovery observations still show high
    fault-active flags and low recovery-active flags for much of the recovery
    window.  The actor therefore cannot reliably infer the phase switch from
    the current observation contract.
- Manual mode check:
  - Compared the same BC0 actor under `sac_actor_raw_guard0` and
    `sac_actor_always_raw`.
  - Output CSV:
    `lab/results/hpt_v2_control_comparison/control_comparison_topology2_fault_all_manual_mode_compare_hpt_t2_lvrt090_reg050_rec016_ed030_actor_bc_20260721_r3_bc0_20260721_215429.csv`.
  - Both modes failed voltage survival.  Startup/fault gating alone does not
    make this actor promotable.
- Decision:
  - Stop blind BC/SAC hyperparameter sweeps for this topology2 seed.
  - Next useful work is an interface/observation revision for phase separation:
    robust startup blanking, explicit fault/recovery phase features, or
    separate phase-conditioned controller heads.

## 2026-07-21 - Diagnostic phase override improves topology2 action imitation but not promotion

- Scope:
  - Add an opt-in scheduled phase-observation contract and test whether the
    topology2 LVRT 0.90 pu / 60 ms trajectory actor failure was primarily a
    phase-identification problem.
- Interface changes:
  - Added default-off Simulink workspace variables:
    `hpt_sac_phase_override_enable`,
    `hpt_sac_phase_fault_start_s`,
    `hpt_sac_phase_fault_clear_s`, and
    `hpt_sac_phase_recovery_end_s`.
  - Added `--phase-override` to:
    `sac.validate_hpt_trajectory_switchlevel` and
    `sac.run_hpt_trajectory_specialist_campaign`.
  - Added `fault_recovery` to the trajectory-specialist campaign preset list
    to match the existing trajectory generator.
  - The observation/action dimensions remain `24/4`; default behavior is
    unchanged.
- Validation:
  - Phase-override teacher validation passed:
    `lab/results/hpt_t2_lvrt090_phase_override_validation_20260721/summary.json`.
  - The known trajectory still had zero timestep envelope and recovery
    violations, and still beat conventional:
    trajectory score `128.799`, baseline score `264.260`.
- Actor smoke 1:
  - Run:
    `lab/results/hpt_t2_lvrt090_phase_override_actor_smoke_20260721/summary.json`.
  - Action imitation improved sharply versus the prior non-phase run:
    `m_reg_d_mae=0.00435`, `m_energy_d_mae=0.00490`.
  - The actor still failed voltage survival by timestep envelope:
    `envelope_violation_max_pu=0.03376`,
    `recovery_violation_max_pu=0`.
- Actor smoke 2:
  - A higher-margin seed `[0.52,0,0.30,0]` during fault and
    `[0.18,0,0.30,0]` during recovery passed as a teacher, but the actor
    failed by both envelope and recovery envelope:
    `envelope_violation_max_pu=0.02069`,
    `recovery_violation_max_pu=0.02159`.
  - Run:
    `lab/results/hpt_t2_lvrt090_reg052_rec018_ed030_phase_margin_actor_smoke_20260721/summary.json`.
- Actor smoke 3:
  - A conservative-recovery seed `[0.52,0,0.30,0]` during fault and
    `[0.16,0,0.30,0]` during recovery passed as a teacher, but the actor
    failed by recovery envelope and DC-link bounds:
    `recovery_violation_max_pu=0.03928`, `Vdc_min=528.42 V`.
  - Run:
    `lab/results/hpt_t2_lvrt090_reg052_rec016_ed030_phase_margin_actor_smoke_20260721/summary.json`.
- Decision:
  - Phase override is useful: it resolves the major action-imitation gap and
    confirms that the previous actor failure was not merely an optimizer issue.
  - No new topology2 actor is promotable yet.
  - Next work should focus on topology2 closed-loop robustness around the
    energy/DC-link branch: reduce recovery over-injection, add recovery/DC-link
    state-feedback labels, or train separate phase-conditioned heads before
    returning to final direct SAC.

## 2026-07-21 - Topology2 recovery-energy sweep narrows the actor blocker

- Scope:
  - Continue topology2 LVRT 0.90 pu / 60 ms phase-aware actor work by changing
    the recovery energy command and testing whether DC-link collapse and
    recovery overvoltage can be removed without losing fault-window voltage
    survival.
- Energy/DC-link DAgger test:
  - Run:
    `lab/results/hpt_t2_lvrt090_reg052_rec016_ed030_phase_energy_dagger_20260721/summary.json`.
  - Used the passing `[0.52,0,0.30,0]` fault /
    `[0.16,0,0.30,0]` recovery teacher with phase override, then enabled
    two-zone energy relabeling on actor-visited DAgger states.
  - `bc0` improved DC-link survival versus the prior smoke
    (`Vdc_min=653.62 V` instead of about `528 V`) but still failed by
    timestep and recovery envelopes:
    `envelope_violation_max_pu=0.00539`,
    `recovery_violation_max_pu=0.03901`.
  - `dagger1` got worse:
    `Vdc_min=504.04 V`, `fault_lv_band_violation_max_pu=0.00265`.
  - Decision: 2-ms actor-visited trace relabeling does not see enough of the
    20-us switch-level DC-link transient; it is not sufficient as the only
    DAgger signal.
- Recovery-energy trajectory test:
  - A reduced recovery-energy teacher with `[0.52,0,0.30,0]` during fault and
    `[0.16,0,0.10,0]` during recovery passed as a trajectory:
    `lab/results/hpt_t2_lvrt090_reg052_rec016_ed010_phase_margin_validate_20260721/summary.json`.
  - Its BC actor did not promote but fixed the DC-link failure:
    `lab/results/hpt_t2_lvrt090_reg052_rec016_ed010_phase_actor_smoke_20260721/summary.json`.
  - Result:
    `Vdc_min=762.39 V`, `envelope_violation_max_pu=0.00837`,
    `recovery_violation_max_pu=0.01508`.
- Conservative-recovery bound:
  - Teacher `[0.50,0,0.30,0]` fault /
    `[0.12,0,0.10,0]` recovery failed by recovery undervoltage:
    `recovery_violation_max_pu=0.02055`.
  - Teacher `[0.50,0,0.30,0]` fault /
    `[0.14,0,0.10,0]` recovery passed:
    `lab/results/hpt_t2_lvrt090_reg050_rec014_ed010_phase_margin_validate_20260721/summary.json`.
  - Its BC actor did not promote:
    `envelope_violation_max_pu=0.03959`, recovery violation `0`.
    Run:
    `lab/results/hpt_t2_lvrt090_reg050_rec014_ed010_phase_actor_smoke_20260721/summary.json`.
- Decision:
  - Lowering recovery `m_energy_d` from `0.30` to `0.10` is the right direction
    for DC-link survival.
  - The remaining topology2 LVRT actor problem is a narrow closed-loop
    fault/recovery voltage boundary, not phase ambiguity.
  - Do not promote any of these actors.
  - Next useful experiment should use finer trajectory search or phase-specific
    heads around the narrow region: fault `m_reg_d` roughly `0.50-0.52`,
    recovery `m_reg_d` roughly `0.14-0.16`, recovery `m_energy_d` roughly
    `0.10`, and evaluator-level correction samples that include 20-us
    envelope/DC-link extrema.

## 2026-07-21 - Topology2 LVRT fine trajectory grid confirms teacher feasibility but not actor promotion

- Scope:
  - Replace broad/blind topology2 LVRT retraining with a small reproducible
    switch-level teacher grid around the narrowed phase-aware fault/recovery
    region.
- Code:
  - Added `sac.campaigns.sweep_hpt_t2_lvrt_phase_grid`.
  - The runner builds `fault_recovery` trajectory MAT files, validates each
    one with `sac.validate_hpt_trajectory_switchlevel`, and writes
    ranked CSV/JSON summaries under `lab/results/<campaign_id>/`.
- Teacher grid:
  - Run:
    `lab/results/hpt_t2_lvrt090_phase_grid_smoke_20260721/summary.json`.
  - Six topology2 LVRT 0.90 pu / 60 ms phase-aware trajectories passed
    switch-level voltage survival and beat the conventional baseline.
  - Best ranked teacher:
    `fr052_rr016_fe030_re008`, fault action `[0.52,0,0.30,0]`, recovery
    action `[0.16,0,0.08,0]`.
  - Best teacher metrics:
    trajectory score `128.086`, baseline score `264.260`,
    `Vdc_min=758.31 V`, `Vdc_max=978.34 V`, zero timestep/recovery envelope
    violations.
- Actor attempt:
  - Run:
    `lab/results/hpt_t2_lvrt090_fr052_rr016_re008_phase_actor_20260721/summary.json`.
  - The BC actor fitted the teacher closely:
    `m_reg_d_mae=0.00597`, `m_energy_d_mae=0.00407`.
  - It still failed switch-level voltage survival:
    `policy_envelope_violation_max_pu=0.02644`,
    `policy_voltage_reason=timestep_voltage_envelope`.
  - DC link was no longer the limiter:
    `policy_vdc_min=762.39 V`, `policy_vdc_max=979.45 V`.
- Decision:
  - Do not promote this actor.
  - Feasible trajectory generation is now proven for this narrow topology2
    LVRT region.  The remaining blocker is actor realization: small action
    and state-feedback deviations produce 20-us voltage envelope excursions.
  - Next work should add phase/window-conditioned actor heads or
    evaluator-level correction samples around the fault/recovery boundary,
    instead of searching only more fixed trajectory seeds.

## 2026-07-21 - Topology2 LVRT trajectory-label DAgger shifts, but does not remove, the failure

- Scope:
  - Test whether a minimal actor-realization repair can promote the best
    topology2 LVRT phase-grid teacher without changing the actor architecture.
- Run:
  - `lab/results/hpt_t2_lvrt090_fr052_rr016_re008_phase_trajdagger1_20260722/summary.json`.
  - Same teacher as the fine-grid best case:
    fault action `[0.52,0,0.30,0]`, recovery action `[0.16,0,0.08,0]`.
  - Used one DAgger iteration with `--dagger-label-source trajectory` and
    no additional Vdc feedback.
- Results:
  - BC0 reproduced the previous failure exactly:
    `policy_envelope_violation_max_pu=0.02644`,
    `policy_recovery_violation_max_pu=0`,
    `policy_vdc_min=762.39 V`.
  - DAgger1 did not promote:
    `policy_voltage_reason=dc_link_bounds;timestep_recovery_envelope`.
  - DAgger1 removed the fault envelope violation but created recovery/DC-link
    failure:
    `policy_envelope_violation_max_pu=0`,
    `policy_recovery_violation_max_pu=0.03771`,
    `policy_vdc_min=613.03 V`.
- Decision:
  - Do not promote the DAgger actor.
  - The evidence now separates two subproblems:
    BC0 has a fault-window 20-us envelope excursion, while DAgger1 overcorrects
    into recovery and weakens the DC link.
  - Simple 2-ms actor-visited relabeling is not enough.  The next change should
  explicitly separate fault/recovery behavior in the policy or training
  target, such as phase/window-conditioned actor heads, recovery-specific
  correction samples, or a two-head reg/energy actor with separate recovery
  weighting.

## 2026-07-22 - Topology2 LVRT no-noise high-weight actor promoted

- Scope:
  - Convert the best topology2 LVRT phase-grid trajectory into a
    switch-level voltage-survival actor after the first BC and DAgger attempts
    failed around the fault/recovery boundary.
- Diagnostics:
  - Added `sac.summaries.analyze_hpt_trace_alignment` to compare
    teacher and actor traces by time/window zone.
  - The failing BC actor had small mean action error but a large boundary
    excursion near fault clearing: about `38.55 V` maximum LV trace error.
  - A delayed-recovery teacher passed as a trajectory, but its actor worsened
    recovery/DC-link behavior and was not promoted.
- Successful run:
  - `lab/results/hpt_t2_lvrt090_fr052_rr016_re008_phase_nonoise_actor_20260722/summary.json`.
  - Teacher:
    fault `[0.52,0,0.30,0]`, recovery `[0.16,0,0.08,0]`.
  - Training:
    no observation-noise augmentation, high action weights `32,1,12,1`,
    teacher-prior weight `300`, and direct switch-trace behavior cloning.
- Switch-level result:
  - `policy_voltage_pass=true`;
  - `policy_beats_baseline=true`;
  - `policy_score=113.665`, baseline score `264.260`;
  - `fault_lv_band_violation_max_pu=0`;
  - `envelope_violation_max_pu=0`;
  - `recovery_violation_max_pu=0`;
  - `Vdc_min=761.40 V`, `Vdc_max=978.45 V`.
- Limitation:
  - `policy_full_frt_pass=false` because grid-current and sustained
    reactive-current criteria are still not satisfied/evaluated for full FRT.
- Decision:
  - Promoted this actor as the current topology2 LVRT balanced
    voltage-survival specialist.
  - Updated
    `sac/experiments/accepted_specialists_20260721_balanced.csv`
    to replace the older topology2 LVRT row with
    `data/models/hpt_t2_lvrt090_fr052_rr016_re008_phase_nonoise_actor_20260722_bc0.zip`.
  - This is evidence for a narrow switch-level voltage-survival specialist,
    not for a full-FRT certified controller.

## 2026-07-22 - Stage-2 evidence audit and unbalanced manifest correction

- Scope:
  - Audit the active Stage-2 research goal against current repository evidence
    instead of relying on memory of previous runs.
- New audit:
  - Added
    `docs/specs/algorithms/hpt-sac-controller/hpt-sac-controller-stage2-evidence-audit-2026-07-22.md`.
  - The audit maps the current evidence to four requested deliverables:
    mixed pass/fail boundary evidence, proxy recalibration for timestep
    voltage-survival metrics, balanced topology1/topology2 LVRT/HVRT
    specialists, and unbalanced-fault extension preparation.
- Findings:
  - Balanced voltage-survival specialist matrix is complete for the four
    60-ms accepted cases, and all four rows beat conventional.
  - Mixed boundary evidence exists, but it is strongest in balanced HVRT and
    unbalanced LVRT; balanced LVRT remains conventional all-fail in the broad
    boundary sweep.
  - Balanced proxy support reproduces the pilot matrix timestep metrics, but
    unbalanced energy-sweep reward alignment remains weak.
  - Unbalanced source/observation support is no longer pending: topology1 and
    topology2 both passed 14/14 source smoke cases.
  - topology1 unbalanced A-phase and AB LVRT specialists are accepted at the
    voltage-survival level; topology2 unbalanced remains blocked by
    energy/DC-link and phase-transition dynamics.
- Manifest correction:
  - Updated
    `sac/experiments/stage1_stage2_scenarios_20260721.csv` so the
    unbalanced scenarios now show `supported` instead of
    `pending_source_model`, with notes distinguishing accepted topology1 rows
    from still-blocked topology2 rows.
- Decision:
  - Keep the active claim at switch-level voltage survival.
  - Do not mark the research goal complete until the remaining proxy and
    unbalanced-extension evidence is either finalized or explicitly scoped as
    the documented Stage-2 stopping point.

## 2026-07-22 - Balanced accepted matrix per-case recheck corrected the current claim

- Scope:
  - Re-run the balanced accepted-specialist matrix after discovering that the
    new explicit `actor_filter_tau` manifest column had been applied uniformly
    even though the accepted actors were validated under different command
    filtering conditions.
- Manifest correction:
  - `topology1_lvrt090_60ms_gridobs_clock`: `actor_filter_tau=0.001`.
  - `topology2_lvrt090_60ms_phase_nonoise_retrain`: `actor_filter_tau=0.0`
    and `phase_override=true`.
  - `topology2_hvrt110_60ms_balanced_retrain`: `actor_filter_tau=0.001`.
  - `topology1_hvrt110_60ms_balanced_retrain` remains stale and archived in
    `sac/experiments/stale_specialists_after_phaseaware_recheck_20260722.csv`.
- Switch-level recheck:
  - Run:
    `lab/results/hpt_accepted_balanced_matrix_20260722_percase_tau_recheck/summary.json`.
  - Result:
    `case_count=3`, `voltage_survival_pass_count=3`,
    `beats_conventional_count=3`, `full_frt_pass_count=0`.
  - Detailed report:
    `lab/results/hpt_accepted_balanced_matrix_20260722_percase_tau_recheck/REPORT.md`.
- Current accepted balanced rows:
  - topology1 LVRT 0.90 pu / 60 ms:
    score `104.012` vs conventional `122.356`, Vdc `766.30/876.57 V`.
  - topology2 LVRT 0.90 pu / 60 ms:
    score `113.665` vs conventional `264.260`, Vdc `761.40/978.45 V`.
  - topology2 HVRT 1.10 pu / 60 ms:
    score `114.076` vs conventional `188.705`, Vdc `762.39/999.98 V`.
- Decision:
  - The current reproducible balanced voltage-survival claim is 3 accepted
    specialists, not 4.
  - topology1 HVRT 1.10 pu / 60 ms must be retrained or re-searched under the
    current phase-aware/per-case validation interface before it can return to
    the accepted matrix.
  - No accepted row is full-FRT certified; grid-current and reactive-current
    gates remain future work.

## 2026-07-22 - Topology1 HVRT recovered under the current observation interface

- Scope:
  - Restore the missing balanced topology1 HVRT 1.10 pu / 60 ms specialist
    after the old `topology1_hvrt110_60ms_balanced_retrain` actor became stale
    under the current grid-normalized observation interface.
- Diagnosis:
  - The old actor no longer produced the original regulating action: current
    rechecks showed `cmd_m_reg_d_mean` near `0.004` instead of the old passing
    value near `0.249`.
  - Therefore the failure was actor/observation-interface incompatibility, not
    a physical impossibility of the case.
- Trajectory sanity check:
  - Run:
    `lab/results/hpt_t1_hvrt110_const_old_actor_mean_current_iface_20260722/summary.json`.
  - Constant action `[0.249, 0, -0.005, 0]` passed switch-level voltage
    survival and beat conventional:
    score `105.512` vs baseline `116.834`, Vdc `770.26/878.19 V`.
- Current-interface actor retrain:
  - Run:
    `lab/results/hpt_t1_hvrt110_const249_current_iface_actor_20260722/summary.json`.
  - Model:
    `data/models/hpt_t1_hvrt110_const249_current_iface_actor_20260722_bc0.zip`.
  - Result:
    `policy_voltage_pass=true`, `policy_beats_baseline=true`,
    score `105.383` vs baseline `116.834`,
    fault LV `204.46/220.64 V`,
    zero fault/envelope/recovery violations, Vdc `765.00/878.06 V`.
- Accepted matrix recheck:
  - Run:
    `lab/results/hpt_accepted_balanced_matrix_20260722_current4_recheck/summary.json`.
  - Result:
    `case_count=4`, `voltage_survival_pass_count=4`,
    `beats_conventional_count=4`, `full_frt_pass_count=0`.
  - Report:
    `lab/results/hpt_accepted_balanced_matrix_20260722_current4_recheck/REPORT.md`.
- Decision:
  - The current reproducible balanced voltage-survival matrix is restored to
    four accepted specialists.
  - This supersedes the immediately preceding 3-row claim.
  - The full-FRT claim remains false for all four rows because grid-current
    and/or reactive-current recovery criteria remain unsatisfied or not fully
    evaluated.

## 2026-07-22 - Stage-2 voltage-survival completion report added

- Scope:
  - Consolidate the current Stage-2 evidence into a single citable report after
    the balanced 4-row matrix was restored.
- Added:
  - `docs/specs/algorithms/hpt-sac-controller/hpt-sac-controller-stage2-completion-report-2026-07-22.md`.
- Report covers:
  - mixed pass/fail boundary evidence;
  - balanced proxy recalibration for timestep voltage-survival metrics;
  - the four accepted balanced switch-level SAC specialists;
  - unbalanced source/observation readiness;
  - topology2 unbalanced and full-FRT blockers.
- Decision:
  - Treat Stage-2 voltage-survival as complete at the balanced-specialist
    level.
  - Continue future work from topology2 unbalanced trajectory teachers and
    full-FRT current/reactive-current criteria, not from broader proxy-only SAC
    claims.

## 2026-07-22 - Topology2 A-phase unbalanced trajectory seed promoted to state-feedback actor

- Scope:
  - Convert the passing topology2 A-phase LVRT 0.90 pu / 60 ms trajectory seed
    into a real state-feedback actor and validate it in the switch-level model.
- Seed recheck:
  - Run:
    `lab/results/hpt_unbalanced_t2_a_lvrt090_seed_recheck_20260722/summary.json`.
  - Result:
    trajectory voltage-survival pass `true`, trajectory beats conventional
    `true`, score `135.323` vs baseline `159.385`, zero timestep envelope and
    recovery violations, Vdc `719.74/920.52 V`.
- Training attempt:
  - Heavy BC setting
    `hpt_unbalanced_t2_a_lvrt090_seed_statefeedback_strong_20260722` timed out
    during BC training after 1800 s.  It is diagnostic evidence that the
    high-repeat/high-epoch setting is too slow for interactive iteration.
  - Lightweight state-feedback setting
    `hpt_unbalanced_t2_a_lvrt090_seed_statefeedback_light_20260722` completed
    with one trajectory-label DAgger iteration.
- Switch-level actor result:
  - Model:
    `data/models/hpt_unbalanced_t2_a_lvrt090_seed_statefeedback_light_20260722_dagger1.zip`.
  - Result:
    `policy_voltage_pass=true`, `policy_beats_baseline=true`,
    `policy_full_frt_pass=false`, score `126.950` vs baseline `159.385`,
    fault LV `224.79/229.95 V`, recovery LV mean `200.01 V`,
    zero fault/envelope/recovery violations, Vdc `728.09/849.28 V`.
  - Full FRT remains false because `gbt_recover` and `grid_current_limit` are
    still not satisfied.
- Manifest update:
  - Added `topology2_a_lvrt090_60ms_unbalanced` to
    `sac/experiments/accepted_specialists_20260721_unbalanced.csv`.
- Decision:
  - The unbalanced voltage-survival matrix now has three accepted specialists:
    topology1 A-phase LVRT, topology1 AB LVRT, and topology2 A-phase LVRT.
  - Next unbalanced target is topology2 AB LVRT 0.90 pu / 60 ms using the same
    trajectory-to-state-feedback pattern, with short BC settings first.

## 2026-07-22 - Topology2 AB unbalanced state-feedback actor promoted with phase-aware observation

- Scope:
  - Extend the topology2 unbalanced work from A-phase LVRT to AB LVRT
    0.90 pu / 60 ms.
- Seed transfer:
  - Run:
    `lab/results/hpt_unbalanced_t2_ab_lvrt090_seed_from_a_recheck_20260722/summary.json`.
  - Result:
    the topology2 A-phase trajectory seed also passed the AB LVRT trajectory
    gate and beat conventional: score `131.606` vs baseline `163.332`, zero
    timestep envelope/recovery violations, Vdc `698.80/920.22 V`.
- Actor attempts:
  - Non-phase-overridden run
    `hpt_unbalanced_t2_ab_lvrt090_seed_statefeedback_light_20260722` did not
    promote: best actor score `125.510` but `policy_voltage_pass=false` due to
    `timestep_recovery_envelope`.
  - Phase-aware run
    `hpt_unbalanced_t2_ab_lvrt090_phase_statefeedback_light_20260722` promoted
    the `bc0` actor; the DAgger1 actor over-corrected recovery and was not
    selected.
- Switch-level promoted actor:
  - Model:
    `data/models/hpt_unbalanced_t2_ab_lvrt090_phase_statefeedback_light_20260722_bc0.zip`.
  - Result:
    `policy_voltage_pass=true`, `policy_beats_baseline=true`,
    `policy_full_frt_pass=false`, score `132.248` vs baseline `163.332`,
    fault LV `219.66/225.23 V`, recovery LV mean `203.72 V`,
    zero fault/envelope/recovery violations, Vdc `689.21/900.28 V`.
  - Full FRT remains false because `gbt_recover` and `grid_current_limit` are
    still not satisfied.
- Manifest update:
  - Added explicit `phase_override` support to
    `sac/experiments/accepted_specialists_20260721_unbalanced.csv`.
  - Added `topology2_ab_lvrt090_60ms_unbalanced`.
- Decision:
  - The current unbalanced voltage-survival matrix now has four accepted
    specialists: topology1 A, topology1 AB, topology2 A, and topology2 AB.
  - The trajectory-to-state-feedback route works for the requested unbalanced
    LVRT cases, but AB requires phase-aware features and should not use the
    DAgger1 actor from this run.

## 2026-07-22 - Unbalanced accepted matrix rechecked after per-phase validator fix

- Scope:
  - Recheck the unbalanced accepted-specialist manifest after adding topology2
    A and AB rows.
- Validator fix:
  - `sac/validate_hpt_accepted_specialists.py` previously ignored
    `fault_phase_pu` and therefore ran unbalanced rows as balanced faults.
  - Added parsing for `fault_phase_key` / `fault_phase_pu` and pass-through of
    the fourth `hpt_compare_faults` argument, for example
    `[0.9 1.0 1.0]` and `[0.9 0.9 1.0]`.
- Recheck:
  - Run:
    `lab/results/hpt_accepted_unbalanced_matrix_20260722_current4_phasefix_recheck/summary.json`.
  - Result:
    `case_count=4`, `voltage_survival_pass_count=4`,
    `beats_conventional_count=2`, `full_frt_pass_count=0`.
- Current row status:
  - topology1 A LVRT and topology1 AB LVRT: voltage-survival pass, but do not
    beat conventional under the current score definition.
  - topology2 A LVRT and topology2 AB LVRT: voltage-survival pass and beat
    conventional.
  - all four are still not full-FRT certified because grid-current/recovery
    criteria remain outside the current voltage-survival scope.
- Decision:
  - Use the unbalanced manifest as a voltage-survival matrix, not as a 4/4
    beat-conventional claim.
  - For the next research loop, topology2 unbalanced is now the strongest
    SAC-over-conventional evidence; topology1 unbalanced needs either score
    improvement or a narrower voltage-survival-only claim.

## 2026-07-22 - Stage-2 8-row voltage-survival matrix unified recheck

- Scope:
  - Consolidate the current balanced and unbalanced accepted specialists into
    one Stage-2 voltage-survival manifest and recheck them with a single
    validator invocation.
- Manifest:
  - `sac/experiments/accepted_specialists_20260722_stage2_voltage_survival.csv`.
- Switch-level recheck:
  - Run:
    `lab/results/hpt_stage2_voltage_survival_matrix_20260722_8row_recheck/summary.json`.
  - Result:
    `case_count=8`, `voltage_survival_pass_count=8`,
    `beats_conventional_count=6`, `full_frt_pass_count=0`.
- Current accepted-matrix interpretation:
  - Balanced topology1/topology2 LVRT/HVRT: four voltage-survival specialists,
    all beat conventional.
  - Unbalanced topology1/topology2 A/AB LVRT: four voltage-survival
    specialists; topology2 A/AB beat conventional, topology1 A/AB are
    survival-only rows under the current score definition.
  - Full FRT remains out of the current Stage-2 claim and still fails in the
    existing evaluator because grid-current/recovery criteria are not yet
    satisfied.
- Documentation:
  - Updated
    `docs/specs/algorithms/hpt-sac-controller/hpt-sac-controller-stage2-completion-report-2026-07-22.md`.
  - Updated `sac/experiments/README.md`.
- Decision:
  - Use the unified 8-row recheck as the authoritative Stage-2 baseline.
  - Next research path is warm-start SAC fine-tuning on topology2 A-phase and
    AB unbalanced LVRT, with switch-level validation as the promotion gate.

## 2026-07-22 - Topology2 unbalanced warm-start SAC fine-tuning accepted

- Scope:
  - Move the strongest topology2 unbalanced A/AB LVRT evidence from trajectory
    imitation/state-feedback actors toward true SAC fine-tuning while keeping
    the Stage-2 voltage-survival scope.
- Script changes:
  - Extended `sac/offline/train_hpt_voltage_sac.py` with exact
    topology2 A/AB unbalanced LVRT 0.90 pu / 60 ms curricula.
  - Added reward-weight CLI controls so grid-current/reactive full-FRT terms
    can be held at zero during Stage-2 voltage-survival fine-tuning.
  - Added conservative behavior anchoring against the accepted init actor.
- Negative result:
  - Weak-anchor A-phase run:
    `data/models/hpt_t2_a_lvrt090_warm_sac_anchor_20260722.zip`.
  - Switch-level result:
    `lab/results/hpt_candidate_t2_a_lvrt090_warm_sac_anchor_20260722_switchcheck/summary.json`.
  - It failed voltage-survival because regulating action drifted too low:
    fault LV `171.49/178.68 V`, violations in fault band, envelope, and
    recovery.  Do not promote this candidate.
- Accepted warm-start SAC candidates:
  - topology2 A-phase LVRT:
    `data/models/hpt_t2_a_lvrt090_warm_sac_reganchor_20260722.zip`.
    Switch-level score `126.578` vs conventional `159.385`, voltage-survival
    pass, full FRT false on `gbt_recover;grid_current_limit`.
  - topology2 AB LVRT:
    `data/models/hpt_t2_ab_lvrt090_warm_sac_reganchor_20260722.zip`.
    Switch-level score `132.148` vs conventional `163.332`, voltage-survival
    pass, full FRT false on `gbt_recover;grid_current_limit`.
- Manifest updates:
  - Updated
    `sac/experiments/accepted_specialists_20260721_unbalanced.csv`.
  - Updated
    `sac/experiments/accepted_specialists_20260722_stage2_voltage_survival.csv`.
- Unified recheck:
  - Run:
    `lab/results/hpt_stage2_voltage_survival_matrix_20260722_8row_warmsac_recheck/summary.json`.
  - Result:
    `case_count=8`, `voltage_survival_pass_count=8`,
    `beats_conventional_count=6`, `full_frt_pass_count=0`.
- Decision:
  - The Stage-2 matrix is still voltage-survival only, but topology2 A/AB
    unbalanced rows are now accepted warm-start SAC fine-tuned actors.
  - Future SAC improvements must use strong regulating-bridge anchoring or a
    split-head/regularized update; direct proxy SAC can destroy LV support even
    when DC link remains safe.

## 2026-07-25 - 630-case voltage-survival boundary matrix completed

- Scope:
  - Build the confirmed voltage-survival boundary experiment before returning
    to full-FRT criteria.
  - Matrix:
    `2` topologies x `9` fault depths x `5` durations x `7` phase modes =
    `630` switch-level scenarios.
  - Depths:
    LVRT `0.75/0.80/0.85/0.90/0.95 pu`; HVRT
    `1.05/1.10/1.15/1.20 pu`.
  - Durations:
    `40/60/80/120/200 ms`.
  - Phase modes:
    balanced ABC, A, B, C, AB, BC, CA.
- Added task-owned workflow files:
  - Plan:
    `docs/specs/algorithms/hpt-sac-controller/hpt-sac-controller-voltage-survival-boundary-plan-2026-07-25.md`.
  - Manifest generator:
    `sac/campaigns/generate_hpt_voltage_survival_boundary_manifest.py`.
  - Grouped switch-level runner:
    `sac/campaigns/run_hpt_voltage_survival_boundary_matrix.py`.
  - Manifest:
    `sac/experiments/voltage_survival_boundary_manifest_20260725.csv`.
- Interface checks:
  - MATLAB Engine import failed (`No module named 'matlab'`), so the campaign
    used the accepted `matlab -batch` fallback.
  - Dry-run passed:
    smoke `12` cases / `10` groups, full `630` cases / `18` groups.
- Smoke switch-level run:
  - Run:
    `lab/results/hpt_voltage_survival_boundary_smoke_20260725/summary.json`.
  - Result:
    `12` cases, conventional voltage-survival `4/12`, nearest-SAC
    voltage-survival `10/12`, SAC beats conventional `6/12`,
    traditional fail / SAC pass `6/12`, traditional pass / SAC fail `0/12`.
- Full switch-level run:
  - Run:
    `lab/results/hpt_voltage_survival_boundary_full_20260725/summary.json`.
  - Result:
    `630` cases, raw rows `1260`, conventional voltage-survival `270/630`,
    nearest-SAC voltage-survival `392/630`, SAC beats conventional `180/630`,
    traditional fail / SAC pass `122/630`, traditional pass / SAC fail `0/630`.
  - Analysis:
    `lab/results/hpt_voltage_survival_boundary_full_20260725/BOUNDARY_ANALYSIS.md`.
- Key interpretation:
  - The current nearest-specialist SAC boundary is strictly better than the
    traditional baseline under the voltage-survival gate in this matrix:
    no row has traditional pass and SAC fail.
  - topology1 unbalanced rows all survive for both traditional and SAC; the
    remaining topology1 unbalanced objective is score improvement, not pass/fail
    survival.
  - topology1 balanced LVRT and topology2 HVRT/unbalanced HVRT expose the main
    remaining SAC failure regions.
  - topology2 LVRT has strong traditional-fail/SAC-pass regions, but also
    boundary failures at deeper/longer scenarios.
- Decision:
  - Treat this as Stage-2 voltage-survival boundary evidence, not full FRT
    certification.
  - Next training targets should be chosen from
    `sac_fail_boundary_targets.csv`, with priority:
    topology2 unbalanced HVRT specialist, topology1 balanced LVRT deeper/longer
    specialist, then topology2 LVRT duration/depth extension.

## 2026-07-25 - Exact specialist boundary push: topology2 A-HVRT and topology1 balanced LVRT

- Scope:
  - Train exact switch-level voltage-survival specialists for the next boundary
    targets:
    topology2 unbalanced A-HVRT 1.05/1.10 pu at 60 ms, topology1 balanced
    LVRT 0.85/0.90 pu at 80/120 ms, and topology1 unbalanced A-phase score
    optimization.
- topology2 unbalanced HVRT:
  - Fixed strong-positive probe:
    `lab/results/hpt_probe_t2_a_hvrt105_strongpos_validate_20260725/summary.json`.
    Action `[0.50, 0, 0.30, 0]` passed A-phase HVRT 1.05 pu / 60 ms and
    beat conventional: score `126.275` vs `145.478`.
  - Trained trajectory-imitation/DAgger actor:
    `data/models/hpt_exact_t2_a_hvrt105_60ms_strongpos_actor_daggertraj_20260725_dagger1.zip`.
    Switch-level policy score `125.626` vs conventional `145.478`, no
    voltage-survival violations.
  - Recheck:
    `lab/results/hpt_exact_t2_a_hvrt105110_dagger_recheck_20260725/summary.json`.
    Result: `2/2` voltage-survival pass and `2/2` beat conventional for
    A-HVRT 1.05 and 1.10 pu / 60 ms. Full FRT remains false on
    `gbt_recover;grid_current_limit`.
- topology1 balanced LVRT:
  - The earlier 0.90 pu / 80 ms DAgger actor extended to 0.85 pu at 80/120 ms,
    but failed 0.90 pu / 120 ms by a small timestep voltage-envelope violation.
  - Built a 0.90 pu / 120 ms fault/recovery trajectory that holds the high
    support through the longer fault, then lowers recovery support:
    `lab/results/hpt_exact_t1_lvrt090_120ms_fault_recovery_018_validate2_20260725/summary.json`.
  - Trained a no-noise, strong-BC actor:
    `data/models/hpt_exact_t1_lvrt090_120ms_fault_recovery_018_actor_bcstrong_20260725_bc0.zip`.
    Switch-level score `156.723` vs conventional `169.927`; fault/recovery
    envelope and DC-link survival gates passed.
- Reduced boundary confirmation:
  - Manifest:
    `sac/experiments/reduced_boundary_exact_push_20260725.csv`.
  - Run:
    `lab/results/hpt_reduced_boundary_exact_push_20260725/summary.json`.
  - Result:
    `6` cases, conventional voltage-survival `0/6`, exact SAC
    voltage-survival `6/6`, SAC beats conventional `6/6`,
    traditional-fail/SAC-pass `6/6`.
- topology1 unbalanced score optimization:
  - Rechecked why the accepted A/AB unbalanced actors do not beat conventional:
    their recovery support is too high.  Example A-phase accepted actor score
    `106.028` vs conventional `102.465`, with recovery mean `215.24 V` vs
    conventional `204.04 V`.
  - Zero/fixed conventional-like action probes failed voltage-survival; CEM
    found passable A-phase trajectories but none beat conventional.  Best CEM
    switch-level trajectory score was `108.263` vs conventional `102.465`.
  - Decision: topology1 unbalanced score beating is not solved by simple fixed
    action or shallow CEM; next attempt should use a conventional-trace teacher
    or score-aware trajectory search constrained to reduce recovery overboost.

## 2026-07-25 - topology1 unbalanced A-LVRT recovery-overboost attack

- Scope:
  - Focus on topology1 A-phase LVRT 0.90 pu / 60 ms.
  - Avoid simple fixed action; try conventional-trace teacher extraction and
    score-aware fault/recovery trajectory search.
- Tooling added:
  - Extended
    `simulink/collectors/collect_hpt_v2_trajectory_trace.m` to log
    command, measured, and teacher action channels:
    `cmd_action_*`, `meas_action_*`, `teacher_action_*`, `mref_*`, and
    `menergy_*`.
  - Added
    `sac/datasets/build_hpt_trajectory_from_trace.py` to convert
    Simulink traces into executable trajectory MAT/CSV files.
  - Added
    `sac/campaigns/run_hpt_fault_recovery_trajectory_score_sweep.py`
    for explicit pre/fault/recovery trajectory sweeps.
  - Added unbalanced `--fault-phase-pu` support to
    `sac/campaigns/run_hpt_dynamic_trajectory_sweep.py`.
- Conventional-trace result:
  - Tuned conventional trace:
    `lab/results/hpt_v2_trajectory_traces/trajectory_trace_topology1_conv_teacher_tuned_t1_a_lvrt090_60ms_20260725_20260725_160959.csv`.
  - The measured conventional response looked reasonable
    (`fault_mregd ~= 0.092`, `recovery_mregd ~= 0.013`,
    `fault_lv ~= 203.2 V`, `recovery_lv ~= 205.4 V`), but replaying those
    measured/teacher coordinates directly failed voltage regulation
    (`score 154.49`, `LV_mean 159.45 V`).
  - Interpretation: conventional internal response coordinates are not the
    same as executable `HPTSACController` action commands.
- Score-aware trajectory search:
  - Best micro pre/fault/recovery trajectory:
    `lab/results/hpt_t1_a_lvrt090_60ms_micro_pre_frd_scoresweep_20260725`.
  - Best token:
    `prd0p2_frd0p39_rrd0p3_fed0p0_red0p0_fq0p0_rq0p0`.
  - Result: voltage-survival pass, no fault/recovery/timestep envelope
    violation, `Vdc 765.9-877.4 V`.
  - Score `102.702` vs conventional `102.465`: close, but still not beat.
  - Recovery overboost improved materially: previous accepted actor recovery
    mean was about `215.24 V`; the best score-aware trajectory gives about
    `206.97 V`.
  - Remaining score bottleneck is grid current / current-related penalty:
    trajectory grid-current peak is about `1.545 pu` vs conventional
    `1.514 pu`.
- Actor training result:
  - Trained trajectory-imitation/DAgger actor:
    `data/models/hpt_t1_a_lvrt090_60ms_pre02_frd039_rrd03_actor_20260725_dagger1.zip`.
  - First BC actor: voltage-survival pass, score `103.265`, recovery mean
    `210.61 V`, not beat.
  - DAgger actor: voltage-survival pass, score `104.994`, recovery mean
    `199.00 V`, still not beat because action/current penalties grew.
- Key decision:
  - The recovery-overboost mechanism is now understood and partially fixed.
  - topology1 unbalanced A-LVRT is still not a SAC-beats-conventional result.
  - Next attack should optimize trajectory/current tradeoff directly, not only
    mimic a low-overboost trace.  Useful options are:
    enable/calibrate topology1 q-channel if it is intended to participate, add
    a score-aware DAgger label that penalizes grid-current peak, and fine-tune
    state-feedback actor with explicit current/action smoothness terms.

## 2026-07-25 - topology1 unbalanced A-LVRT current/trajectory tradeoff continuation

- Scope:
  - Continue the topology1 A-phase LVRT 0.90 pu / 60 ms score attack after the
    recovery-overboost fix.
  - Objective: beat conventional dq under the switch-level voltage-survival
    score without returning to a fixed-action policy.
- Current-tradeoff sweep:
  - Run:
    `lab/results/hpt_t1_a_lvrt090_60ms_current_tradeoff_scoresweep_20260725`.
  - Tested lower `fault_reg_d` around `0.370-0.380` and recovery
    `0.260-0.300`.
  - Best: `pre=0.20`, `fault_reg_d=0.37`, `recovery_reg_d=0.30`,
    score `102.643` vs conventional `102.465`, voltage-survival pass.
  - Lower recovery commands suppressed overboost but pushed recovery LV too
    low, so score increased.
- Energy-branch local sweep:
  - Run:
    `lab/results/hpt_t1_a_lvrt090_60ms_energy_tradeoff_scoresweep_20260725`.
  - Best:
    `pre=0.20`, `fault_reg_d=0.37`, `recovery_reg_d=0.30`,
    `fault_energy_d=-0.04`, `recovery_energy_d=0.04`.
  - Result: voltage-survival pass, score `102.542` vs conventional `102.465`.
    This is the closest result so far but still not a beat.
  - Metrics: `LV_mean 201.88 V`, `LV_recovery_mean 206.85 V`,
    `grid_current_peak 1.530 pu`, `Vdc 765.9-878.8 V`, no timestep envelope
    violations.
  - Deeper energy commands (`fault_energy_d=-0.08` and lower) worsened score;
    the useful energy effect is small and saturates near `-0.04`.
- Reg/energy and pre-bias refinement:
  - Runs:
    `lab/results/hpt_t1_a_lvrt090_60ms_reg_energy_combo_scoresweep_20260725`
    and
    `lab/results/hpt_t1_a_lvrt090_60ms_pre_energy_scoresweep_20260725`.
  - Increasing `fault_reg_d` to `0.375-0.385` raised LV mean but also raised
    current penalty; no beat.
  - `pre_reg_d=0.20` remained best; lower pre-bias reduced LV mean and higher
    pre-bias increased current/score.
- Ramp test:
  - Run:
    `lab/results/hpt_t1_a_lvrt090_60ms_ramp5_best_scoresweep_20260725`.
  - A slower 5-ms ramp lowered current slightly (`1.52945 pu`) but also lowered
    LV mean, score `102.557`; no beat.
- Conventional trace replay:
  - Built a replay trajectory from tuned conventional `cmd_action`:
    `lab/results/hpt_t1_a_lvrt090_60ms_conv_cmd_replay_20260725`.
  - Replay failed (`LV_mean 160.61 V`, score `152.56`), confirming that the
    logged conventional command/response channels are not directly executable
    SAC action semantics.
- Interpretation:
  - Recovery overboost is now reduced from about `215 V` to about `206-207 V`.
  - The remaining gap is not voltage envelope survival; all best candidates
    pass voltage-survival and timestep envelopes.
  - The remaining gap is the current/action tradeoff: trajectory LV/recovery
    terms beat conventional, but grid-current peak remains about
    `1.530 pu` versus conventional `1.514 pu`.
  - Under the present topology1 action surface, scalar trajectory search appears
    locally saturated just above the conventional score.
- Next decision:
  - Do not keep blind-sweeping the same four scalar action channels for this
    case.
  - To make topology1 unbalanced beat conventional, the next work should add or
    validate an effective degree of freedom for current shaping: either enable
    and calibrate the topology1 q/control channel if physically intended, or
    train a true state-feedback actor with an explicit grid-current peak term
    and score-aware DAgger labels sampled from switch-level traces.

## 2026-07-25 - topology1 q-channel diagnostic

- Scope:
  - Diagnostic only: temporarily override `hpt_sac_reg_q_gain=1.0` in
    `hpt_compare_model_params` without changing the topology1 builder or SLX.
  - Purpose: determine whether topology1 q action has a useful physical effect
    for the A-phase LVRT 0.90 pu / 60 ms score bottleneck.
- Result:
  - Default topology1 builder still sets `hpt_sac_reg_q_gain=0.0`, while
    topology2 sets `hpt_sac_reg_q_gain=1.0`.  This explains why previous
    topology1 q sweeps had no effect.
  - Diagnostic `m_reg_q=-0.10` worsened score to `104.956`:
    `LV_mean 198.67 V`, `LV_recovery_mean 203.26 V`,
    `grid_current_peak 1.551 pu`.
  - Diagnostic `m_reg_q=+0.10` also did not beat conventional:
    score `102.776`, `LV_mean 205.66 V`,
    `LV_recovery_mean 213.90 V`, `grid_current_peak 1.523 pu`.
- Interpretation:
  - q-channel has physical effect when enabled, but raw q action is not an
    immediate solution.  Positive q reduces current somewhat but reintroduces
    recovery overboost; negative q worsens current and voltage.
  - Any use of topology1 q must be a formal model/control design change with
    calibration and renewed boundary validation, not a silent tuning change.

## 2026-07-25 - paper reviewer evidence package

- Scope:
  - Convert reviewer-critique action items into paper-facing evidence tables
    using existing switch-level validation outputs.
  - Avoid promoting proxy-only or stale accepted CSV results as final evidence.
- Completed:
  - Added `sac/summaries/build_hpt_paper_evidence_package.py`.
  - Generated `paper/evidence/per_case_metrics.csv`,
    `paper/evidence/paired_case_comparison.csv`,
    `paper/evidence/score_sensitivity.csv`,
    `paper/evidence/reproducibility_manifest.csv`, and
    `paper/evidence/REPORT.md`.
  - Added `paper/evidence/ablation_ladder_protocol.md` to define the
    teacher / BC / BC+DAgger / BC+DAgger+SAC fine-tune comparison needed to
    distinguish imitation benefit from SAC policy-improvement benefit.
  - Ran MATLAB command-line interface smoke because Python MATLAB Engine is not
    installed; `test_hpt_v2_sac_interface.m` passed for topology1 and topology2.
  - Updated `paper/reviewer_critique_action_plan.md` and the manuscript
    reproducibility section with the new evidence package paths.
- Evidence interpretation:
  - Current package covers 8 Stage-2 paired cases plus 6 reduced-boundary paired
    cases.
  - The package separates feasibility improvement from quality improvement and
    records current/DC-link diagnostics.
  - The reproducibility manifest is partial: actor/control CSV hashes are
    available, but training dataset hashes, teacher trajectory hashes, exact
    training commands, MATLAB version, and solver settings remain unresolved
    for historical runs.
- Not completed:
  - Fresh switch-level ablation ladder runs.
  - Conventional baseline tuning appendix.
  - Hold-out proxy alignment categories.
  - Robustness matrix for inception angle, noise, solver tolerance, load, SCR,
    and X/R perturbations.

## 2026-07-25 - reviewer evidence fresh-run addendum

- Scope:
  - Execute and document the four missing reviewer-evidence blocks:
    ablation, conventional baseline tuning, proxy holdout alignment, and
    reduced robustness.
  - Keep claims bounded to switch-level voltage-survival evidence.
- New tooling:
  - Added `sac/campaigns/run_hpt_reviewer_evidence_campaign.py`.
  - Added detailed report
    `paper/evidence/reviewer_evidence_experiment_report_2026-07-25.md`.
  - Appended the result summary to `paper/evidence/REPORT.md`.
  - Updated `paper/reviewer_critique_action_plan.md`.
- Ablation:
  - Run id: `hpt_reviewer_evidence_20260725_ablation_v2`.
  - topology2 A-phase HVRT 1.05 pu / 60 ms: teacher replay, BC, and
    BC+DAgger all passed voltage-survival and beat conventional.
  - topology1 balanced LVRT 0.90 pu / 80 ms: teacher replay passed and beat
    conventional, but promoted BC and BC+DAgger actors failed.
  - Missing: independent BC+DAgger+SAC fine-tune row.
- Baseline tuning:
  - Run id: `hpt_reviewer_evidence_20260725_baseline`.
  - Conventional dq scale sweeps at 0.45, 0.55, and 0.70 produced 0/12
    voltage-survival pass each; shallow sanity sweep also produced 0/12.
  - Interpretation: this is useful negative evidence, but not a strong
    conventional tuning protocol.
- Proxy alignment:
  - Run id: `hpt_reviewer_evidence_20260725_proxy_v2`.
  - Local support-domain matrix aligned near exactly; broader matrix showed
    non-trivial LV/Vdc/recovery mismatch.
  - Interpretation: proxy remains suitable for screening/warm-start, not final
    evidence.
- Robustness:
  - Run id: `hpt_reviewer_evidence_20260725_robustness`.
  - fault_start +/-5 ms and Rchop +10% passed 2/2 voltage-survival checks;
    actor tau = 2 ms passed 1/2.
  - Full FRT pass remained zero.

## 2026-07-25 - topology2 ablation SAC fine-tune negative row

- Scope:
  - Add the missing fourth ablation row for the stable topology2 A-phase HVRT
    1.05 pu / 60 ms representative case.
  - Warm-start from the switch-level-passing BC+DAgger checkpoint and run a
    short proxy SAC fine-tune with behavior anchoring.
- Code change:
  - Added `topology2_a_hvrt105_60ms` curriculum to
    `sac/offline/train_hpt_voltage_sac.py`.
- Training run:
  - Run id:
    `hpt_reviewer_evidence_20260725_ablation_v2_topology2_a_hvrt105_60ms_sacft`.
  - Init model:
    `data/models/hpt_reviewer_evidence_20260725_ablation_v2_topology2_a_hvrt105_60ms_dagger_dagger1.zip`.
  - Steps: 4000, learning rate: 5e-5, behavior anchor enabled.
  - Proxy diagnostics were poor: critic loss exploded, mean return was
    extremely negative, and behavior-anchor action MSE remained large.
- Switch-level validation:
  - CSV:
    `lab/results/hpt_v2_control_comparison/control_comparison_topology2_fault_all_hpt_reviewer_evidence_20260725_ablation_v2_topology2_a_hvrt105_60ms_sacft_actor_20260725_225107.csv`.
  - Parsed summary:
    `lab/results/hpt_reviewer_evidence_20260725_ablation_v2_topology2_a_hvrt105_60ms_sacft/switch_eval_summary.json`.
  - Result: failed voltage-survival.
  - Score: SAC fine-tune `294.7297` versus conventional `145.4778`.
  - LV mean/recovery: `78.98/80.85 V`.
  - Vdc max: `1066.92 V`.
  - Action max: `1.131`, violating the action limit.
- Interpretation:
  - This is a completed negative ablation row.
  - Current proxy SAC fine-tune degrades the already switch-level-valid
    BC+DAgger actor.
  - Next SAC work should redesign the fine-tune objective/support constraint
    before claiming SAC policy-improvement beyond imitation.

## 2026-07-25 - protected SAC fine-tune chunk gate

- Goal:
  - Repair the failed topology2 A-HVRT SAC fine-tune by using short proxy SAC
    chunks, stronger behavior anchoring, and immediate switch-level validation
    after each chunk.
- Implementation:
  - Added `sac/campaigns/run_hpt_protected_sac_finetune.py`.
  - The runner starts from the switch-level-passing BC+DAgger checkpoint,
    exports each candidate to the dynamic Simulink actor, validates the
    candidate in switch-level simulation, stops on hard voltage-survival
    failure, and restores the previous dynamic actor file at exit.
- Results:
  - `hpt_protected_sacft_t2_a_hvrt105_20260725`:
    - Chunk 1 preserved voltage survival but did not improve over BC+DAgger.
    - Chunk 2 failed the recovery-envelope gate.
  - `hpt_protected_sacft_t2_a_hvrt105_20260725_tinyanchor`:
    - Ran 8/8 chunks without voltage-survival failure.
    - Best score was `125.84597092026` versus BC+DAgger baseline
      `125.845970922945`; the delta is `2.68e-9`, below the `1e-3`
      meaningful-improvement threshold.
    - Later chunks gradually worsened to score `126.4266`.
- Interpretation:
  - Switch-level chunk gating prevents the catastrophic drift seen in naive
    SAC fine-tune.
  - The current proxy SAC objective still does not provide a useful
    improvement gradient near the validated BC+DAgger policy.
  - Do not claim SAC fine-tune contribution yet; treat this as diagnostic
    evidence for redesigning the fine-tune objective and support constraint.

## 2026-07-26 - topology2 A-HVRT trust-region SAC fine-tune positive row

- Goal:
  - Convert the topology2 A-phase HVRT 1.05 pu / 60 ms representative case
    from "BC/DAgger only" evidence into a genuine SAC policy-improvement row.
  - Keep switch-level validation as the promotion gate and avoid accepting
    proxy-only improvements.
- Code change:
  - Updated `sac/campaigns/run_hpt_protected_sac_finetune.py`.
  - Added `--advance-policy` with default `improve`, so a candidate becomes the
    next warm start only if it passes switch-level validation and improves the
    score by more than the `1e-3` threshold.
  - Added per-chunk seed variation and explicit score-delta fields.
- Conservative seed search:
  - Run id:
    `hpt_trustregion_sacft_t2_a_hvrt105_20260726_seedsearch`.
  - Config: 20 proxy steps per chunk, very strong behavior anchor, 10 chunks.
  - Result: 10/10 voltage-survival pass, but no meaningful improvement over
    BC+DAgger.  Best score remained `125.845970922945`.
  - Interpretation: the policy was safe but effectively frozen.
- Medium-anchor trust-region run:
  - Run id:
    `hpt_trustregion_sacft_t2_a_hvrt105_20260726_mediumanchor`.
  - Config: 35 proxy steps per chunk, medium behavior anchor, rollback on
    non-improvement, and continued search after non-promoted candidates.
  - Best candidate: chunk 3,
    `data/models/hpt_trustregion_sacft_t2_a_hvrt105_20260726_mediumanchor_chunk03.zip`.
  - Switch-level result:
    - voltage-survival pass;
    - score `125.808359717994` versus BC+DAgger baseline
      `125.845970922945`;
    - improvement `0.037611204951`;
    - fault-band, timestep-envelope, and recovery violations all zero;
    - DC link range `761.43-831.28 V`;
    - action max `0.95`;
    - full FRT still false on `gbt_recover;grid_current_limit`.
- Interpretation:
  - This is the first positive switch-level evidence that protected SAC
    fine-tuning can improve over a BC+DAgger warm-start actor in the current
    flattened HPT2.0 pipeline.
  - The claim remains narrow: one topology2 A-HVRT voltage-survival case, not
    unified SAC and not full FRT certification.
  - Next steps: repeat on topology2 A-HVRT 1.10 pu / 60 ms and topology2 AB
    HVRT, then test whether the same trust-region settings transfer to LVRT
    cases without breaking DC-link behavior.

## 2026-07-26 - protected SAC promotion matrix round 1

- Goal:
  - Extend the trust-region protected SAC fine-tune mechanism from the single
    topology2 A-HVRT case to the Stage-2 voltage-survival specialist set and
    the new topology2 unbalanced HVRT targets.
  - Keep switch-level validation as the promotion gate.  Proxy-only
    improvements are not accepted.
- Code changes:
  - Added `swell_2ph` negative-sequence support in
    `sac/hpt_voltage_sac_env.py`.
  - Parameterized
    `sac/campaigns/run_hpt_protected_sac_finetune.py` so the
    curriculum, topology, fault case, phase vector, chopper settings, actor
    filter, and phase override are supplied from the command line instead of
    being hard-coded to topology2 A-HVRT 1.05 pu.
  - Added the manifest
    `sac/experiments/trustregion_promotion_targets_20260726.csv`.
  - Added the batch runner
    `sac/campaigns/run_hpt_trustregion_promotion_matrix.py`.
- Verification:
  - Compile check passed for the modified environment, trainer, protected
    runner, and batch runner.
  - Smoke run:
    `hpt_trustregion_promotion_20260726_smoke`, one case, one chunk,
    completed without chain failure.
- Round-1 command:
  - `py -3 -m sac.campaigns.run_hpt_trustregion_promotion_matrix --run-id hpt_trustregion_promotion_20260726_round1 --max-chunks 4 --chunk-steps 80 --train-timeout-s 900 --matlab-timeout-s 1200 --continue-after-fail`
- Round-1 results:
  - Run directory:
    `lab/results/hpt_trustregion_promotion_20260726_round1`.
  - Completed `11/11` targets, with `0` process failures.
  - Improved `3` existing switch-level voltage-survival specialists:
    - topology2 balanced HVRT 1.10 pu / 60 ms:
      score `114.075781714011 -> 114.067011689805`;
      checkpoint
      `data/models/hpt_trustregion_promotion_20260726_round1_04_topology2_hvrt110_60ms_balanced_retrain_chunk01.zip`.
    - topology1 A-phase LVRT 0.90 pu / 60 ms:
      score `106.027966140736 -> 105.126612795124`;
      checkpoint
      `data/models/hpt_trustregion_promotion_20260726_round1_05_topology1_a_lvrt090_60ms_unbalanced_chunk03.zip`.
    - topology2 A-phase LVRT 0.90 pu / 60 ms:
      score `126.577723426817 -> 126.261797445833`;
      checkpoint
      `data/models/hpt_trustregion_promotion_20260726_round1_07_topology2_a_lvrt090_60ms_unbalanced_chunk01.zip`.
  - Newly probed topology2 AB-HVRT 1.05 pu / 60 ms:
    - chunk 1 produced a switch-level voltage-survival pass with score
      `125.283136901034`;
    - checkpoint
      `data/models/hpt_trustregion_promotion_20260726_round1_11_topology2_ab_hvrt105_60ms_new_chunk01.zip`;
    - chunks 2-4 failed the timestep recovery envelope, so the safe region is
      narrow and should not yet be treated as a robust promoted specialist.
- Interpretation:
  - The protected SAC fine-tune mechanism transfers beyond the original
    topology2 A-HVRT case, but gains are case-dependent.
  - topology1 AB-LVRT, topology2 AB-LVRT, topology2 A-HVRT 1.05, and
    topology2 A-HVRT 1.10 did not improve in this short round.
  - Current evidence is still voltage-survival only.  It is not full FRT
    certification because grid current limit, reactive current support, and
    GBT recovery gates remain outside the promotion criterion.
- Next action:
  - Build an updated accepted/promoted manifest from the three improved
    checkpoints plus the cautious topology2 AB-HVRT candidate.
  - Run a reduced boundary recheck comparing old Stage-2 specialists,
    protected-SAC promoted specialists, and conventional control on the same
    validator.
  - For non-improved AB cases, use score-aware trajectory search before further
    SAC fine-tune, because blind local SAC did not reduce the score.

## 2026-07-26 - promoted specialist recheck and expansion plan

- Goal:
  - Stabilize the protected SAC round-1 results by running all promoted
    checkpoint choices through one shared switch-level voltage-survival
    validator.
  - Identify which rows are robust promoted rows and which rows need targeted
    quality improvement before boundary expansion.
- Planning artifact:
  - `docs/specs/algorithms/hpt-sac-controller/hpt-sac-controller-stabilize-and-expand-plan-2026-07-26.md`.
- Manifest artifacts:
  - `sac/experiments/protected_sac_promoted_specialists_20260726_round1.csv`.
  - `sac/experiments/protected_sac_promoted_recheck_manifest_20260726.csv`.
- Recheck command:
  - `py -3 -m sac.campaigns.run_hpt_voltage_survival_boundary_matrix --manifest sac/experiments/protected_sac_promoted_recheck_manifest_20260726.csv --run-id hpt_promoted_recheck_20260726_round1 --controller-mode current-sac --timeout-s 2400`
- Recheck result:
  - Run directory:
    `lab/results/hpt_promoted_recheck_20260726_round1`.
  - Cases: `11`.
  - Conventional voltage-survival pass: `2/11`.
  - Promoted SAC voltage-survival pass: `11/11`.
  - SAC beats conventional: `9/11`.
  - Traditional fail / SAC pass: `9/11`.
  - Traditional pass / SAC fail: `0/11`.
- Interpretation:
  - The current promoted SAC set is stable under a fresh shared validator pass.
  - The two weak rows are topology1 A-phase LVRT 0.90 pu / 60 ms and topology1
    AB LVRT 0.90 pu / 60 ms.  Both survive, but conventional has a lower score.
  - The next expansion should focus on reducing topology1 unbalanced recovery
    overboost / quality score, and on stabilizing the new topology2 AB-HVRT
    1.05 pu candidate.

## 2026-07-26 - targeted expansion round 2

- Goal:
  - Improve the weak topology1 unbalanced LVRT rows and test whether the new
    topology2 AB-HVRT 1.05 pu candidate can be made more stable.
- Command:
  - `py -3 -m sac.campaigns.run_hpt_trustregion_promotion_matrix --run-id hpt_trustregion_targeted_expand_20260726_round2 --case-id topology1_a_lvrt090_60ms_unbalanced --case-id topology1_ab_lvrt090_60ms_unbalanced --case-id topology2_ab_hvrt105_60ms_new --max-chunks 6 --chunk-steps 100 --train-timeout-s 900 --matlab-timeout-s 1200 --continue-after-fail`
- Results:
  - Run directory:
    `lab/results/hpt_trustregion_targeted_expand_20260726_round2`.
  - Completed `3/3`, process failures `0`.
  - topology1 A-LVRT:
    - best score `105.552368294878`, improved over the original Stage-2 actor
      but not over the round-1 best score `105.126612795124`.
    - Reason: this run started from the original target manifest, not the
      round-1 promoted checkpoint.
  - topology1 AB-LVRT:
    - best score `104.487873543975`, improved over `106.015360281519`.
    - Still does not beat the conventional score `102.888321369442`.
  - topology2 AB-HVRT 1.05:
    - chunk 1 voltage-survival pass, score `125.445236503455`.
    - chunks 2-6 failed `timestep_recovery_envelope`.
    - This repeats the round-1 finding: the AB-HVRT safe region is narrow and
      needs lower exploration / stronger recovery anchoring.
- Next action:
  - Run a round-3 refined expansion starting from the best available
    checkpoints:
    - topology1 A-LVRT from the round-1 best checkpoint;
    - topology1 AB-LVRT from the round-2 best checkpoint;
    - topology2 AB-HVRT from the round-1 pass candidate.
  - Use smaller learning rate, shorter chunks, and stronger behavior anchors.

## 2026-07-26 - refined expansion round 3

- Goal:
  - Start from the current best checkpoint for each weak target and test a
    lower-learning-rate, stronger-anchor trust-region SAC refinement.
- Manifest:
  - `sac/experiments/trustregion_refined_targets_20260726_round3.csv`.
- Command:
  - `py -3 -m sac.campaigns.run_hpt_trustregion_promotion_matrix --manifest sac/experiments/trustregion_refined_targets_20260726_round3.csv --run-id hpt_trustregion_refined_expand_20260726_round3 --max-chunks 8 --chunk-steps 60 --learning-rate 5e-6 --teacher-prior-weight 80 --behavior-anchor-epochs 14 --behavior-anchor-interval-steps 30 --behavior-anchor-episodes 4 --behavior-anchor-noise-std 0.0025 --behavior-anchor-lr 5e-6 --behavior-anchor-action-weights 10,6,24,24 --train-timeout-s 900 --matlab-timeout-s 1200 --continue-after-fail`
- Results:
  - Run directory:
    `lab/results/hpt_trustregion_refined_expand_20260726_round3`.
  - Completed `3/3`, process failures `0`, new improved promotions `0`.
  - topology1 A-LVRT:
    - no improvement beyond round-1 best `105.126612795124`.
  - topology1 AB-LVRT:
    - no improvement beyond round-2 best `104.487873543975`.
    - Some lower-score candidates appeared, but failed
      `timestep_voltage_envelope`, so they were correctly rejected.
  - topology2 AB-HVRT:
    - all 8 refined chunks were voltage-survival passes.
    - none improved beyond the round-1 candidate score `125.283136901034`.
- Interpretation:
  - Stronger anchor improves AB-HVRT stability but suppresses useful
    exploration.
  - topology1 AB-LVRT needs an envelope-aware trajectory teacher or constrained
    trajectory search; naive score minimization finds lower-score but
    non-surviving candidates.
  - Current best promoted manifest remains:
    - round-1 promoted set for all unchanged/improved rows;
    - round-2 topology1 AB-LVRT checkpoint only as a quality improvement
      candidate, still not beat-conventional.

## 2026-07-26 - Stage-3 evidence freeze and topology1 AB-LVRT trajectory probe

- Goal:
  - Freeze the current promoted voltage-survival matrix into paper-facing
    evidence artifacts.
  - Probe whether a proxy-guided piecewise-linear trajectory teacher can reduce
    the weak topology1 AB-LVRT 0.90 pu / 60 ms score below the current
    specialist and conventional baseline.
- Evidence artifact:
  - Added `sac/summaries/summarize_stage3_voltage_survival.py`.
  - Generated:
    - `paper/evidence/stage3_voltage_survival_summary.csv`;
    - `paper/evidence/stage3_voltage_survival_summary.md`.
  - Counts from `hpt_promoted_recheck_20260726_round1`:
    - `11/11` SAC switch-level voltage-survival pass;
    - `9/11` SAC beats conventional;
    - `9/11` traditional fail / SAC pass;
    - weak rows: topology1 A-LVRT and topology1 AB-LVRT, both survival-only
      because conventional still has lower score.
- Trajectory CEM probes:
  - Anchor-priority run:
    `hpt_cem_t1_ab_lvrt090_20260726_stage3_seed`.
    - Switch-level candidates: `4`.
    - Voltage-survival passes: `3`.
    - Best passing score: `109.204563825383`, worse than the current
      specialist score `104.487873543975` and conventional score
      `102.888321369442`.
    - Best proxy candidate failed switch-level DC-link bounds with
      `Vdc_min = 481.418 V`, exposing a proxy/DC-link ranking mismatch for
      this case.
  - Proxy-ranked run:
    `hpt_cem_t1_ab_lvrt090_20260726_stage3_proxyrank`.
    - Switch-level candidates: `6`.
    - Voltage-survival passes: `5`.
    - Best passing score again `109.204563825383`.
  - No-anchor run:
    `hpt_cem_t1_ab_lvrt090_20260726_stage3_noanchors`.
    - Switch-level candidates: `5`.
    - Voltage-survival passes: `0`.
- Interpretation:
  - The current CEM trajectory parameterization is useful diagnostically but
    does not produce a better topology1 AB-LVRT teacher.
  - Blind piecewise-linear trajectory search should not be the next main path.
    The next research step should export state-action traces from the accepted
    actor itself and perform score-aware DAgger / protected SAC fine-tune around
    that validated support region.

## 2026-07-26 - topology1 AB-LVRT actor-trace interface and BC diagnostics

- Goal:
  - Move beyond blind CEM by exporting state-action traces from the current
    topology1 AB-LVRT specialist and testing whether local trace imitation can
    preserve or improve the switch-level policy.
- Interface changes:
  - Updated `simulink/evaluators/eval_hpt_v2_sac_single_case.m` with
    optional `hpt_eval_fault_phase_pu=[puA puB puC]` support.
  - Reused the controlled per-phase voltage source pattern from
    `eval_hpt_v2_control_comparison.m`.
  - First attempt used non-replacing line connections and produced near-zero LV
    voltage; fixed by adding `connect_replace()` for the controlled phase
    source branch connection.
  - Updated `sac/pretrain_hpt_actor_bc.py` with
    `--switch-trace-target-columns {action,actor_action}` so trace imitation
    can explicitly target raw actor outputs instead of post-execution action
    columns.
- Trace export:
  - Exported current topology1 AB-LVRT best actor
    `data/models/hpt_trustregion_targeted_expand_20260726_round2_02_topology1_ab_lvrt090_60ms_unbalanced_chunk04.zip`
    to both Simulink actor weight files.
  - Ran single-case trace with `hpt_eval_fault_phase_pu=[0.9 0.9 1.0]`.
  - Valid trace:
    `lab/results/hpt_v2_sac_single_case_actor_traces/single_actor_trace_topology1_fault_sag_0p90_20260726_113647.csv`.
  - Trace windows: prefault `18`, fault `30`, recovery `60`, tail `3`.
- BC diagnostic 1:
  - Run id: `hpt_t1_ab_lvrt090_actortrace_bc_20260726`.
  - Target columns: default `action_*`.
  - Recheck:
    `hpt_t1_ab_lvrt090_actortrace_bc_recheck_20260726_fix`.
  - Result: failed voltage-survival, score `148.582`; reasons
    `timestep_fault_lv_band;timestep_voltage_envelope;timestep_recovery_envelope`.
  - Diagnosis: the executed/action column had recovery `m_reg_d` averaging
    negative, so BC learned insufficient/incorrect lift.
- BC diagnostic 2:
  - Run id: `hpt_t1_ab_lvrt090_actortrace_actorcols_bc_20260726`.
  - Target columns: `actor_action_*`.
  - Recheck:
    `hpt_t1_ab_lvrt090_actortrace_actorcols_bc_recheck_20260726`.
  - Result: failed voltage-survival, score `140.884`; reasons
    `dc_link_bounds;timestep_recovery_envelope`.
  - Diagnosis: raw-actor-column BC preserved the positive lift direction but
    overshot the regulating action (`m_reg_d_fault_mean ~= 0.687`) and drove
    `Vdc_min` down to `356.978 V`.
- Decision:
  - The unbalanced actor-trace export interface is now usable.
  - Direct BC/distillation from the trace is not safe enough to promote.
  - For topology1 AB-LVRT, continue from the existing switch-validated actor and
    use smaller trust-region SAC updates or score-aware anchors; do not replace
    it with a re-BC actor unless it passes switch-level recheck.

## 2026-07-26 - Stage-4 paper evidence plan and boundary smoke

- Goal:
  - Start the remaining paper-evidence work needed to honestly claim that
    specialist SAC improves switch-level voltage-survival over a strong
    conventional dq baseline.
  - Rebuild the voltage-survival boundary manifest from the current promoted
    recheck actors rather than older Stage-2 actor mappings.
- Planning artifact:
  - `docs/specs/algorithms/hpt-sac-controller/hpt-sac-controller-stage4-paper-evidence-plan-2026-07-26.md`.
- Manifest artifacts:
  - Full 630-case promoted manifest:
    `sac/experiments/stage4_boundary_manifest_20260726.csv`.
  - Smoke subset:
    `sac/experiments/stage4_boundary_smoke_manifest_20260726.csv`.
  - Reduced boundary subset:
    `sac/experiments/stage4_reduced_boundary_manifest_20260726.csv`.
  - Weak topology1 unbalanced LVRT subset:
    `sac/experiments/stage4_weak_focus_manifest_20260726.csv`.
- Dry-run:
  - `py -3 -m sac.campaigns.run_hpt_voltage_survival_boundary_matrix --manifest sac/experiments/stage4_boundary_smoke_manifest_20260726.csv --run-id hpt_stage4_boundary_smoke_20260726_dryrun --controller-mode current-sac --dry-run`
  - Result: 12 selected cases, 11 grouped switch-level jobs.
- Switch-level smoke command:
  - `py -3 -m sac.campaigns.run_hpt_voltage_survival_boundary_matrix --manifest sac/experiments/stage4_boundary_smoke_manifest_20260726.csv --run-id hpt_stage4_boundary_smoke_20260726 --controller-mode current-sac --timeout-s 2400`
- Smoke result:
  - Run directory:
    `lab/results/hpt_stage4_boundary_smoke_20260726`.
  - Cases: `12`.
  - Conventional voltage-survival pass: `4/12`.
  - SAC voltage-survival pass: `11/12`.
  - SAC beats conventional: `7/12`.
  - Traditional fail / SAC pass: `7/12`.
  - Traditional pass / SAC fail: `0/12`.
- Paper-facing evidence:
  - `paper/evidence/stage4_boundary_smoke_20260726.md`.
- Interpretation:
  - The promoted Stage-4 manifest and runner are executable.
  - topology1 A/AB LVRT and A/AB HVRT at 60 ms remain survival-only quality
    gaps because conventional passes with lower score.
  - topology2 AB-HVRT 1.10 / 60 ms is a real Stage-4 failure:
    `timestep_fault_lv_band;dc_link_bounds;timestep_recovery_envelope`.
  - Do not launch the larger 144-case reduced boundary as a paper claim until
    the topology2 AB-HVRT 1.10 failure is fixed or explicitly treated as a
    diagnostic boundary gap.
- Next action:
  - Target topology2 AB-HVRT 1.10 / 60 ms with recovery-aware protected SAC and
    stronger energy-branch anchoring.
  - In parallel, plan a topology1 unbalanced quality optimization round, but do
    not claim beat-conventional for those rows until fresh switch-level scores
    improve below conventional.

## 2026-07-26 - Stage-4 topology2 AB-HVRT 1.10 repair

- Goal:
  - Repair the only SAC voltage-survival failure exposed by the Stage-4 smoke:
    topology2 AB-HVRT 1.10 pu / 60 ms.
- Target manifest:
  - `sac/experiments/stage4_t2_ab_hvrt110_target_20260726.csv`.
- Command:
  - `py -3 -m sac.campaigns.run_hpt_trustregion_promotion_matrix --manifest sac/experiments/stage4_t2_ab_hvrt110_target_20260726.csv --run-id hpt_stage4_t2_ab_hvrt110_repair_20260726 --max-chunks 3 --chunk-steps 60 --learning-rate 5e-6 --teacher-prior-weight 90 --behavior-anchor-epochs 16 --behavior-anchor-interval-steps 30 --behavior-anchor-episodes 5 --behavior-anchor-noise-std 0.002 --behavior-anchor-lr 5e-6 --behavior-anchor-action-weights 8,6,30,30 --advance-policy pass --train-timeout-s 900 --matlab-timeout-s 1200 --continue-after-fail`
- Result:
  - Run directory:
    `lab/results/hpt_stage4_t2_ab_hvrt110_repair_20260726`.
  - Best model:
    `data/models/hpt_stage4_t2_ab_hvrt110_repair_20260726_01_topology2_ab_hvrt110_60ms_stage4_chunk03.zip`.
  - Best score: `128.060512246615`.
  - Previous smoke fallback SAC score: `135.190765145462`.
  - Conventional score: `145.970008470231`.
  - Conventional pass: `false`.
  - Repaired SAC pass: `true`.
  - Full FRT pass: `false`, reasons `gbt_recover;grid_current_limit`.
  - Voltage-survival metrics for the best chunk:
    - `sac_envelope_violation_max_pu = 0.0`;
    - `sac_recovery_violation_max_pu = 0.0`;
    - `sac_fault_lv_band_violation_max_pu = 0.0`;
    - `sac_vdc_min = 762.521345935865 V`;
    - `sac_vdc_max = 827.935171470461 V`.
- Manifest updates:
  - Added the repaired actor to
    `sac/experiments/stage4_promoted_specialists_20260726.csv`.
  - Regenerated:
    - `sac/experiments/stage4_boundary_manifest_20260726_r2.csv`;
    - `sac/experiments/stage4_boundary_smoke_manifest_20260726_r2.csv`;
    - `sac/experiments/stage4_reduced_boundary_manifest_20260726_r2.csv`;
    - `sac/experiments/stage4_weak_focus_manifest_20260726_r2.csv`.
  - The r2 full manifest has 630 rows and 12 exact actor rows.
- Interpretation:
  - The Stage-4 smoke failure was caused by missing exact AB-HVRT 1.10
    specialization, not by a global inability of SAC to control topology2 HVRT.
  - The repaired actor creates a stronger starting point for the reduced
    boundary matrix.
- Next action:
  - Run the r2 smoke matrix to confirm the integrated manifest now gives
    12/12 SAC voltage-survival.
  - If confirmed, proceed to the 144-case r2 reduced boundary matrix.

## 2026-07-26 - Stage-4 r2 smoke recheck

- Goal:
  - Confirm that the repaired topology2 AB-HVRT 1.10 actor is correctly
    integrated into the Stage-4 boundary manifest.
- Command:
  - `py -3 -m sac.campaigns.run_hpt_voltage_survival_boundary_matrix --manifest sac/experiments/stage4_boundary_smoke_manifest_20260726_r2.csv --run-id hpt_stage4_boundary_smoke_20260726_r2 --controller-mode current-sac --timeout-s 2400`
- Result:
  - Run directory:
    `lab/results/hpt_stage4_boundary_smoke_20260726_r2`.
  - Cases: `12`.
  - Conventional voltage-survival pass: `4/12`.
  - SAC voltage-survival pass: `12/12`.
  - SAC beats conventional: `8/12`.
  - Traditional fail / SAC pass: `8/12`.
  - Traditional pass / SAC fail: `0/12`.
- Remaining non-beat rows:
  - topology1 A-HVRT 1.10 / 60 ms:
    conventional `105.228856415172`, SAC `106.3472201202`.
  - topology1 A-LVRT 0.90 / 60 ms:
    conventional `102.46532840039`, SAC `105.126612795124`.
  - topology1 AB-HVRT 1.10 / 60 ms:
    conventional `104.983263612647`, SAC `106.038313653575`.
  - topology1 AB-LVRT 0.90 / 60 ms:
    conventional `102.888321369442`, SAC `106.015360281519`.
- Interpretation:
  - The Stage-4 r2 promoted set passes all smoke voltage-survival cases.
  - The only smoke-level weakness is now topology1 unbalanced quality score,
    not voltage-survival feasibility.
- Next action:
  - Start the 144-case r2 reduced boundary matrix, or run a shorter topology1
    unbalanced weak-focus matrix first if runtime is constrained.

## 2026-07-26 - Stage-4 r2 reduced boundary matrix

- Goal:
  - Run the first broader Stage-4 voltage-survival boundary matrix using the
    r2 promoted actor set, including the repaired topology2 AB-HVRT 1.10 actor.
- Command:
  - `py -3 -m sac.campaigns.run_hpt_voltage_survival_boundary_matrix --manifest sac/experiments/stage4_reduced_boundary_manifest_20260726_r2.csv --run-id hpt_stage4_reduced_boundary_20260726_r2 --controller-mode current-sac --timeout-s 2400`
- Result:
  - Run directory:
    `lab/results/hpt_stage4_reduced_boundary_20260726_r2`.
  - Cases: `144`.
  - Conventional voltage-survival pass: `48/144`.
  - SAC voltage-survival pass: `90/144`.
  - SAC beats conventional: `49/144`.
  - Traditional fail / SAC pass: `45/144`.
  - Traditional pass / SAC fail: `3/144`.
- Evidence artifacts:
  - `paper/evidence/stage4_reduced_boundary_summary_20260726_r2.md`.
  - `paper/evidence/stage4_reduced_boundary_summary_20260726_r2.csv`.
  - `paper/evidence/stage4_reduced_boundary_breakthrough_rows_20260726_r2.csv`.
  - `paper/evidence/stage4_reduced_boundary_sac_failures_20260726_r2.csv`.
- Group-level interpretation:
  - topology1 balanced HVRT: SAC `12/12`, conventional `0/12`, SAC beats
    `12/12`.
  - topology1 unbalanced HVRT: SAC `24/24`, conventional `24/24`; SAC beats
    only `4/24`, so this is survival-only for most rows.
  - topology1 A-phase LVRT: conventional `12/12`, SAC `9/12`; this is the only
    reduced-matrix region with traditional pass / SAC fail.
  - topology2 LVRT: SAC passes `23/36`, conventional `0/36`, breakthrough
    rows `23`.
  - topology2 HVRT: SAC passes `8/36`, conventional `0/36`, breakthrough rows
    `8`; wider HVRT depth/duration remains hard.
- Traditional pass / SAC fail rows:
  - topology1 A-LVRT 0.95 pu / 60 ms:
    `timestep_voltage_envelope`, envelope violation `0.0107885313202438 pu`.
  - topology1 A-LVRT 0.95 pu / 80 ms:
    `timestep_voltage_envelope`, envelope violation `0.0223721840328601 pu`.
  - topology1 A-LVRT 0.95 pu / 120 ms:
    `timestep_voltage_envelope`, envelope violation `0.0223721840328601 pu`.
- Interpretation:
  - The reduced matrix gives the first broad switch-level evidence that
    specialist SAC expands the voltage-survival boundary over conventional dq.
  - It also identifies two honest limitations:
    1. topology1 A-phase shallow LVRT needs a repair actor to avoid small
       timestep voltage-envelope overboost/violation;
    2. topology2 HVRT needs more dedicated specialists for wider depth/duration.
- Next action:
  - Train a topology1 A-LVRT 0.95 specialist for 60/80/120 ms using the current
    topology1 A-LVRT actor as warm start and a score/envelope-aware anchor.
  - Then expand topology2 HVRT specialists beyond the 60 ms center cases.

## 2026-07-26 - topology1 A-LVRT 0.95 repair attempt

- Goal:
  - Repair the three reduced-boundary rows where conventional passes but SAC
    fails: topology1 A-phase LVRT 0.95 pu at 60, 80, and 120 ms.
- Target manifest:
  - `sac/experiments/stage4_t1_a_lvrt095_repair_targets_20260726.csv`.
- Command:
  - `py -3 -m sac.campaigns.run_hpt_trustregion_promotion_matrix --manifest sac/experiments/stage4_t1_a_lvrt095_repair_targets_20260726.csv --run-id hpt_stage4_t1_a_lvrt095_repair_20260726 --max-chunks 4 --chunk-steps 60 --learning-rate 4e-6 --teacher-prior-weight 100 --behavior-anchor-epochs 18 --behavior-anchor-interval-steps 30 --behavior-anchor-episodes 5 --behavior-anchor-noise-std 0.0015 --behavior-anchor-lr 4e-6 --behavior-anchor-action-weights 30,20,8,8 --advance-policy pass --train-timeout-s 900 --matlab-timeout-s 1200 --continue-after-fail`
- Result:
  - Run directory:
    `lab/results/hpt_stage4_t1_a_lvrt095_repair_20260726`.
  - Completed repair targets: `3/3`.
  - Improved targets: `0/3`.
  - For all three targets, the best model remained the original
    `data/models/hpt_trustregion_promotion_20260726_round1_05_topology1_a_lvrt090_60ms_unbalanced_chunk03.zip`.
  - All generated chunks still failed `timestep_voltage_envelope`.
- Interpretation:
  - The shallow A-phase LVRT 0.95 issue is not fixed by small protected SAC
    updates around the deeper-sag 0.90 actor.
  - The likely failure mode is over-injection: the deeper LVRT actor is too
    aggressive for a shallow 0.95 pu sag, causing timestep voltage-envelope
    violation while DC link and recovery remain acceptable.
- Next action:
  - Build a shallow-LVRT action teacher or rule-protected actor for topology1
    A-LVRT 0.95, explicitly reducing regulating injection as sag depth becomes
    shallow.
  - Re-run the 3-row repair matrix only after this new teacher/action
    protection is implemented.

## 2026-07-27 - topology1 A-LVRT 0.95 shallow action sweep

- Goal:
  - Determine whether the three Stage-4 traditional-pass / SAC-fail rows can be
    made physically feasible with a shallow-LVRT action region before training a
    new actor.
- Run directory:
  - `lab/results/hpt_stage4_t1_a_lvrt095_action_sweep_20260727`.
- Raw summary:
  - `lab/results/hpt_stage4_t1_a_lvrt095_action_sweep_20260727/action_sweep_summary.csv`.
- Evidence:
  - `paper/evidence/stage4_t1_a_lvrt095_action_sweep_20260727.md`.
- Result:
  - For topology1 A-phase LVRT 0.95 pu / 60 ms, constant
    `m_reg_d = 0.33`, `0.34`, `0.36`, and `0.38` pass the switch-level
    voltage-survival validator.
  - For 80 ms, constant `m_reg_d = 0.33`, `0.34`, and `0.36` pass.
  - For 120 ms, constant `m_reg_d = 0.33`, `0.34`, and `0.36` pass.
  - `m_reg_d = 0.32` is just below the feasibility threshold and still fails
    the timestep voltage envelope by about `0.0017 pu`.
- Interpretation:
  - The three shallow A-LVRT 0.95 rows are controllable at switch level.
  - The previous repair failed because it fine-tuned around the deeper 0.90 pu
    actor, while the shallow sag needs a different regulating-action region.
  - The sweep closes the voltage-survival feasibility gap, but it is not yet a
    SAC actor and the feasible fixed actions still do not beat conventional dq
    on score.
- Next action:
  - Train a topology1 A-LVRT 0.95 trajectory/state-feedback specialist using
    this shallow action region as teacher/support.
  - Recheck the three repaired rows and then rerun the reduced boundary matrix.

## 2026-07-27 - topology1 A-LVRT 0.95 trajectory actor repair

- Goal:
  - Convert the shallow A-LVRT 0.95 fixed-action region into a real exported
    actor and test whether it repairs the Stage-4 reduced-boundary SAC failure
    holes.
- Command:
  - `py -3 -m sac.run_hpt_trajectory_specialist_campaign --run-id hpt_stage4_t1_a_lvrt095_80ms_traj_actor_20260727 --topology topology1 --fault-pu 0.95 --fault-phase-pu 0.95 1.0 1.0 --duration-s 0.08 --case-name a_lvrt_080ms_0p950pu --action 0.36 0 0 0 --safe-target 0.36 0 0 0 --start-action 0 0 0 0 --base-action 0 0 0 0 --preset constant --dagger-iters 2 --dagger-label-source safe_target --window-zones all --epochs 80 --batch-size 512 --lr 1e-4 --teacher-prior-weight 60 --bc-obs-noise-std 0.006 --bc-obs-noise-repeat 4 --action-weights 12,4,2,2 --switch-trace-repeat 64 --matlab-timeout-s 1200 --train-timeout-s 900`
- Run directory:
  - `lab/results/hpt_stage4_t1_a_lvrt095_80ms_traj_actor_20260727`.
- Result:
  - BC0, DAgger1, and DAgger2 all pass switch-level voltage survival at 80 ms.
  - Best selected actor: BC0,
    `data/models/hpt_stage4_t1_a_lvrt095_80ms_traj_actor_20260727_bc0.zip`.
  - BC0 score: `143.052`, conventional score: `142.592`.
  - The actor does not beat conventional on score and does not pass full FRT
    because grid-current/reactive-current criteria are still failing.
- Cross-check:
  - Temporarily swapped the selected actor into
    `simulink/hpt_sac_actor_weights_dynamic.mat`, then restored the
    previous dynamic actor after evaluation.
  - CSV:
    `lab/results/hpt_v2_control_comparison/control_comparison_topology1_fault_all_hpt_stage4_t1_a_lvrt095_80ms_actor_crosscheck_60_120_20260727_20260727_022613.csv`.
  - At 60 ms: new actor voltage-survival pass, score `102.951`;
    conventional voltage-survival pass, score `102.004`.
  - At 120 ms: new actor voltage-survival pass, score `144.279`;
    conventional voltage-survival pass, score `142.853`.
- Interpretation:
  - The topology1 A-LVRT 0.95 reduced-boundary SAC failure holes can now be
    repaired by a real actor, not only by a fixed-action trajectory.
  - This repair improves feasibility but not score dominance; it should be
    promoted as a voltage-survival repair specialist only.
- Next action:
  - Add this actor to a Stage-4 repair/promoted manifest and rerun the reduced
    boundary matrix or the three-row repair matrix with current-SAC selection.
  - Continue topology2 HVRT expansion, where conventional still fails and SAC
    has the clearest opportunity to expand the voltage-survival boundary.

## 2026-07-27 - topology1 A-LVRT 0.95 actor repair recheck

- Goal:
  - Recheck the new topology1 A-LVRT 0.95 actor through the boundary-matrix
    runner using reduced-matrix style parameters, including
    `fault_settle_s = 0.020`.
- Manifest:
  - `sac/experiments/stage4_t1_a_lvrt095_actor_repair_recheck_20260727.csv`.
- Command:
  - `py -3 -m sac.campaigns.run_hpt_voltage_survival_boundary_matrix --manifest sac/experiments/stage4_t1_a_lvrt095_actor_repair_recheck_20260727.csv --run-id hpt_stage4_t1_a_lvrt095_actor_repair_recheck_20260727 --controller-mode current-sac --timeout-s 1800`
- Run directory:
  - `lab/results/hpt_stage4_t1_a_lvrt095_actor_repair_recheck_20260727`.
- Result:
  - Cases: `3`.
  - Conventional voltage-survival pass: `3/3`.
  - SAC voltage-survival pass: `3/3`.
  - SAC beats conventional: `0/3`.
  - Traditional pass / SAC fail: `0/3`.
  - SAC envelope violation: `0.0 pu` for all three rows.
  - SAC recovery violation: `0.0 pu` for all three rows.
- Interpretation:
  - The new actor closes the previous reduced-matrix SAC failure holes for
    topology1 A-LVRT 0.95 at 60/80/120 ms.
  - It remains a survival repair, not a beat-conventional result.
- Next action:
  - Promote this actor into the Stage-4 manifest for future reduced/full matrix
    runs.
  - Resume topology2 HVRT expansion and topology1 unbalanced score
    optimization as separate beat-conventional targets.

## 2026-07-27 - Stage-4 r3 reduced boundary matrix

- Goal:
  - Rerun the 144-case reduced voltage-survival boundary matrix with the new
    topology1 A-LVRT 0.95 repair actor included.
- Updated manifests:
  - `sac/experiments/stage4_promoted_specialists_20260727.csv`.
  - `sac/experiments/stage4_reduced_boundary_manifest_20260727_r3.csv`.
- Command:
  - `py -3 -m sac.campaigns.run_hpt_voltage_survival_boundary_matrix --manifest sac/experiments/stage4_reduced_boundary_manifest_20260727_r3.csv --run-id hpt_stage4_reduced_boundary_20260727_r3 --controller-mode current-sac --timeout-s 2400`
- Run directory:
  - `lab/results/hpt_stage4_reduced_boundary_20260727_r3`.
- Result:
  - Cases: `144`.
  - Conventional voltage-survival pass: `48/144`.
  - SAC voltage-survival pass: `93/144`.
  - SAC beats conventional: `49/144`.
  - Traditional fail / SAC pass: `45/144`.
  - Traditional pass / SAC fail: `0/144`.
- Evidence:
  - `paper/evidence/stage4_reduced_boundary_summary_20260727_r3.md`.
  - `paper/evidence/stage4_reduced_boundary_summary_20260727_r3.csv`.
  - `paper/evidence/stage4_reduced_boundary_breakthrough_rows_20260727_r3.csv`.
  - `paper/evidence/stage4_reduced_boundary_sac_failures_20260727_r3.csv`.
- Interpretation:
  - The new shallow A-LVRT repair actor increased SAC voltage-survival pass
    count from `90` to `93` and eliminated all conventional-pass/SAC-fail rows.
  - The beat-conventional count did not improve; topology1 A-LVRT 0.95 remains
    a survival-only repair.
  - The next beat-conventional targets remain topology2 HVRT expansion and
    topology1 unbalanced score optimization.

## 2026-07-27 - Stage-5 target manifest setup

- Goal:
  - Start the next evidence cycle after Stage-4 r3 by preparing explicit
    target manifests for topology2 HVRT expansion, topology1 unbalanced score
    optimization, and reviewer-grade evidence.
- Created manifests:
  - `sac/experiments/stage5_topology2_hvrt_expansion_targets_20260727.csv`.
  - `sac/experiments/stage5_topology1_unbalanced_scoreopt_targets_20260727.csv`.
- Evidence/plan:
  - `paper/evidence/stage5_voltage_survival_extension_plan_20260727.md`.
- Target counts:
  - topology2 HVRT expansion targets: `18`.
  - topology1 unbalanced score-optimization targets: `44`.
- Interpretation:
  - topology2 HVRT remains the highest-value survival-boundary target because
    conventional dq fails broadly in this region.
  - topology1 unbalanced is now a score-quality target because SAC already
    survives but often does not beat conventional.
- Next action:
  - Run the first topology2 HVRT expansion batch for A-phase and AB-phase
    `1.10 pu`, `80/120 ms`.

## 2026-07-27 - Stage-5 topology2 HVRT 1.10 pu A/AB expansion

- Goal:
  - Expand topology2 HVRT switch-level voltage-survival coverage at `1.10 pu`
    for A-phase and AB-phase faults with `80/120 ms` duration.
- Commands:
  - `py -3 -m sac.campaigns.run_hpt_trustregion_promotion_matrix --manifest sac/experiments/stage5_topology2_hvrt_expansion_targets_20260727.csv --run-id hpt_stage5_t2_hvrt110_phase_80_120_20260727 --case-id topology2_a_hvrt1p100_80ms_stage5 --case-id topology2_a_hvrt1p100_120ms_stage5 --case-id topology2_ab_hvrt1p100_80ms_stage5 --case-id topology2_ab_hvrt1p100_120ms_stage5 --max-chunks 4 --chunk-steps 80 --learning-rate 6e-6 --teacher-prior-weight 80 --behavior-anchor-epochs 16 --behavior-anchor-interval-steps 40 --behavior-anchor-episodes 4 --behavior-anchor-noise-std 0.0025 --behavior-anchor-lr 6e-6 --behavior-anchor-action-weights 10,5,24,24 --advance-policy pass --train-timeout-s 900 --matlab-timeout-s 1200 --continue-after-fail`
  - `py -3 -m sac.campaigns.run_hpt_trustregion_promotion_matrix --manifest sac/experiments/stage5_topology2_ab_hvrt110_retry_targets_20260727.csv --run-id hpt_stage5_t2_ab_hvrt110_retry_80_120_20260727 --max-chunks 4 --chunk-steps 80 --learning-rate 6e-6 --teacher-prior-weight 80 --behavior-anchor-epochs 16 --behavior-anchor-interval-steps 40 --behavior-anchor-episodes 4 --behavior-anchor-noise-std 0.0025 --behavior-anchor-lr 6e-6 --behavior-anchor-action-weights 10,5,24,24 --advance-policy pass --train-timeout-s 900 --matlab-timeout-s 1200 --continue-after-fail`
- Run directories:
  - `lab/results/hpt_stage5_t2_hvrt110_phase_80_120_20260727`.
  - `lab/results/hpt_stage5_t2_ab_hvrt110_retry_80_120_20260727`.
- Result:
  - topology2 A-HVRT `1.10 pu / 80 ms`: conventional fails, SAC passes,
    best score `127.659`, prior actor score `139.179`.
  - topology2 A-HVRT `1.10 pu / 120 ms`: conventional fails, SAC passes,
    best score `127.069`, prior actor score `135.203`.
  - topology2 AB-HVRT `1.10 pu / 80 ms`: conventional fails, SAC passes,
    best score `127.803`, prior actor score `133.821`.
  - topology2 AB-HVRT `1.10 pu / 120 ms`: conventional fails, SAC passes,
    best score `127.196`, prior actor score `130.813`.
- Evidence:
  - `paper/evidence/stage5_topology2_hvrt110_phase_expansion_20260727.md`.
  - `sac/experiments/stage5_t2_hvrt110_phase_recheck_20260727.csv`.
- Interpretation:
  - Four new topology2 HVRT 1.10 pu A/AB 80/120 ms voltage-survival candidates
    were found in switch-level Simulink validation.
  - These are still voltage-survival candidates, not full FRT certified actors;
    grid-current/reactive-current failures remain outside the current claim.
- Next action:
  - Run the four-row exact current-SAC recheck before adding the actors to
    broader Stage-5 boundary matrices.

## 2026-07-27 - Stage-5 topology2 HVRT 1.10 pu exact recheck

- Goal:
  - Verify the four promoted topology2 HVRT 1.10 pu A/AB actors with the same
    boundary-matrix runner and current voltage-survival validator.
- Manifest:
  - `sac/experiments/stage5_t2_hvrt110_phase_recheck_20260727.csv`.
- Command:
  - `py -3 -m sac.campaigns.run_hpt_voltage_survival_boundary_matrix --manifest sac/experiments/stage5_t2_hvrt110_phase_recheck_20260727.csv --run-id hpt_stage5_t2_hvrt110_phase_recheck_20260727 --controller-mode current-sac --timeout-s 1800`
- Run directory:
  - `lab/results/hpt_stage5_t2_hvrt110_phase_recheck_20260727`.
- Result:
  - Cases: `4`.
  - Conventional voltage-survival pass: `0/4`.
  - SAC voltage-survival pass: `4/4`.
  - SAC beats conventional: `4/4`.
  - Traditional fail / SAC pass: `4/4`.
  - Traditional pass / SAC fail: `0/4`.
  - SAC envelope violation max: `0.0 pu` for all four rows.
  - SAC recovery violation max: `0.0 pu` for all four rows.
- Interpretation:
  - The Stage-5 topology2 HVRT A/AB 1.10 pu 80/120 ms expansion is now
    reproducible as switch-level voltage-survival evidence.
  - This remains a voltage-survival claim; full FRT grid-current and reactive
    current constraints still need a later certification phase.
- Next action:
  - Add these exact actors to the promoted-specialist manifest for future
    boundary matrices.
  - Continue topology2 HVRT expansion to `1.15 pu` and topology1 unbalanced
    score optimization as separate workstreams.

## 2026-07-27 - Stage-5 promoted specialist manifest update

- Goal:
  - Make the four rechecked topology2 HVRT 1.10 pu actors available to future
    Stage-5 boundary matrices.
- Updated manifest:
  - `sac/experiments/stage4_promoted_specialists_20260727.csv`.
- Added actors:
  - `promoted_topology2_a_hvrt110_80ms_stage5`.
  - `promoted_topology2_a_hvrt110_120ms_stage5`.
  - `promoted_topology2_ab_hvrt110_80ms_stage5`.
  - `promoted_topology2_ab_hvrt110_120ms_stage5`.
- Validation basis:
  - `lab/results/hpt_stage5_t2_hvrt110_phase_recheck_20260727/summary.json`.
- Next action:
  - Continue Stage-5 topology2 HVRT expansion to `1.15 pu` and maintain the
    same exact-recheck-before-promotion rule.

## 2026-07-27 - Stage-5 topology2 HVRT 1.15 pu target manifest

- Goal:
  - Prepare the next topology2 HVRT expansion batch after the `1.10 pu`
    A/AB exact recheck succeeded.
- Created manifest:
  - `sac/experiments/stage5_topology2_hvrt115_targets_20260727.csv`.
- Target cases:
  - balanced HVRT `1.15 pu`, `80/120 ms`.
  - A-phase HVRT `1.15 pu`, `80/120 ms`.
  - AB-phase HVRT `1.15 pu`, `80/120 ms`.
- Notes:
  - A-phase rows are warm-started from the exact rechecked `1.10 pu` A-phase
    actors.
  - AB-phase rows are warm-started from the exact rechecked `1.10 pu` AB-phase
    actors and use the validated `topology2_ab_hvrt105_60ms` curriculum.
- Next action:
  - Run protected SAC promotion on this six-case matrix.

## 2026-07-27 - Stage-5 topology2 HVRT 1.15 pu first batch

- Goal:
  - Extend topology2 HVRT voltage-survival from `1.10 pu` to `1.15 pu` for
    balanced, A-phase, and AB-phase faults at `80/120 ms`.
- Command:
  - `py -3 -m sac.campaigns.run_hpt_trustregion_promotion_matrix --manifest sac/experiments/stage5_topology2_hvrt115_targets_20260727.csv --run-id hpt_stage5_t2_hvrt115_80_120_20260727 --max-chunks 4 --chunk-steps 80 --learning-rate 6e-6 --teacher-prior-weight 90 --behavior-anchor-epochs 18 --behavior-anchor-interval-steps 40 --behavior-anchor-episodes 4 --behavior-anchor-noise-std 0.0025 --behavior-anchor-lr 6e-6 --behavior-anchor-action-weights 10,5,26,26 --advance-policy pass --train-timeout-s 900 --matlab-timeout-s 1200 --continue-after-fail`
- Run directory:
  - `lab/results/hpt_stage5_t2_hvrt115_80_120_20260727`.
- Result:
  - Balanced `1.15 pu / 80 ms` and `120 ms` did not train because the manifest
    used invalid curriculum `topology2_hvrt110_60ms_balanced`.
  - A-phase `1.15 pu / 80 ms`: conventional fails, SAC passes, best score
    `130.477`, prior actor score `137.698`.
  - A-phase `1.15 pu / 120 ms`: conventional fails, SAC passes, best score
    `129.813`, prior actor score `134.565`.
  - AB-phase `1.15 pu / 80 ms`: conventional fails, SAC still fails recovery
    envelope; no promoted actor.
  - AB-phase `1.15 pu / 120 ms`: conventional fails, SAC passes, best score
    `129.858`, prior actor score `134.163`.
- Evidence:
  - `paper/evidence/stage5_topology2_hvrt115_first_batch_20260727.md`.
  - `sac/experiments/stage5_t2_hvrt115_success_recheck_20260727.csv`.
- Interpretation:
  - Three new `1.15 pu` candidates were found, but they require exact recheck.
  - AB `1.15 pu / 80 ms` is now the main topology2 HVRT recovery-overvoltage
    failure point.
- Next action:
  - Run exact recheck for the three successful `1.15 pu` actors.
  - Retry balanced rows with corrected curriculum.
  - Design a recovery-focused retry for AB `1.15 pu / 80 ms`.

## 2026-07-27 - Stage-5 topology2 HVRT 1.15 pu exact recheck

- Goal:
  - Verify the three successful topology2 HVRT `1.15 pu` candidates with the
    boundary-matrix runner before promotion.
- Manifest:
  - `sac/experiments/stage5_t2_hvrt115_success_recheck_20260727.csv`.
- Command:
  - `py -3 -m sac.campaigns.run_hpt_voltage_survival_boundary_matrix --manifest sac/experiments/stage5_t2_hvrt115_success_recheck_20260727.csv --run-id hpt_stage5_t2_hvrt115_success_recheck_20260727 --controller-mode current-sac --timeout-s 1800`
- Run directory:
  - `lab/results/hpt_stage5_t2_hvrt115_success_recheck_20260727`.
- Result:
  - Cases: `3`.
  - Conventional voltage-survival pass: `0/3`.
  - SAC voltage-survival pass: `3/3`.
  - SAC beats conventional: `3/3`.
  - Traditional fail / SAC pass: `3/3`.
  - Traditional pass / SAC fail: `0/3`.
  - SAC envelope and recovery violations are `0.0 pu` for all three rows.
- Updated manifest:
  - `sac/experiments/stage4_promoted_specialists_20260727.csv`.
- Promoted actors:
  - `promoted_topology2_a_hvrt115_80ms_stage5`.
  - `promoted_topology2_a_hvrt115_120ms_stage5`.
  - `promoted_topology2_ab_hvrt115_120ms_stage5`.
- Next action:
  - Retry balanced `1.15 pu` with corrected curriculum
    `topology2_hvrt110_60ms`.
  - Attack topology2 AB-HVRT `1.15 pu / 80 ms` with a recovery-focused
    strategy.

## 2026-07-27 - Stage-5 topology2 HVRT 1.15 pu retry result

- Goal:
  - Retry balanced `1.15 pu` after fixing the curriculum name and retry AB
    `1.15 pu / 80 ms` using the successful AB `1.15 pu / 120 ms` actor as
    warm start.
- Command:
  - `py -3 -m sac.campaigns.run_hpt_trustregion_promotion_matrix --manifest sac/experiments/stage5_topology2_hvrt115_retry_targets_20260727.csv --run-id hpt_stage5_t2_hvrt115_retry_20260727 --max-chunks 4 --chunk-steps 80 --learning-rate 4e-6 --teacher-prior-weight 110 --behavior-anchor-epochs 24 --behavior-anchor-interval-steps 40 --behavior-anchor-episodes 5 --behavior-anchor-noise-std 0.0015 --behavior-anchor-lr 4e-6 --behavior-anchor-action-weights 12,6,30,30 --advance-policy pass --train-timeout-s 900 --matlab-timeout-s 1200 --continue-after-fail`
- Run directory:
  - `lab/results/hpt_stage5_t2_hvrt115_retry_20260727`.
- Result:
  - Balanced `1.15 pu / 80 ms`: no promoted actor; all chunks fail
    `dc_link_bounds`, with `Vdc_max` about `1103 V`.
  - Balanced `1.15 pu / 120 ms`: no promoted actor; all chunks fail
    `dc_link_bounds`, with `Vdc_max` about `1103 V`.
  - AB `1.15 pu / 80 ms`: no promoted actor; best retry still fails
    `timestep_recovery_envelope` with recovery violation about `0.01109 pu`.
- Interpretation:
  - The corrected curriculum worked, so these are real control failures, not
    manifest failures.
  - Balanced HVRT `1.15 pu` requires DC-link/energy-branch shaping.
  - AB HVRT `1.15 pu / 80 ms` requires recovery damping, not DC-link repair.
- Next action:
  - Do not keep blind SAC fine-tuning on these rows.
  - Add targeted retry designs: balanced HVRT energy/DC-link shaping and AB
    80 ms recovery-window damping.

## 2026-07-27 - Stage-5 topology2 HVRT 1.15 pu retry manifest

- Goal:
  - Repair the two manifest-level balanced failures and retry the AB-HVRT
    `1.15 pu / 80 ms` recovery failure.
- Created manifest:
  - `sac/experiments/stage5_topology2_hvrt115_retry_targets_20260727.csv`.
- Retry design:
  - Balanced rows use corrected curriculum `topology2_hvrt110_60ms`.
  - AB `1.15 pu / 80 ms` is warm-started from the successful AB `1.15 pu /
    120 ms` actor, because the failure mode is recovery overvoltage rather
    than fault-period envelope violation.
- Next action:
  - Run the retry with stronger behavior anchoring and lower learning rate.

## 2026-07-27 - Stage-5 topology2 HVRT 1.15 pu targeted gap repair

- Goal:
  - Repair the unresolved topology2 HVRT `1.15 pu` voltage-survival gaps after
    the blind protected-SAC retry failed.
- Diagnostic:
  - Created `sac/experiments/stage5_t2_hvrt115_balanced_chopper_sweep_20260727.csv`.
  - Partial chopper sweep showed that lowering the chopper threshold to
    `760 V` removes the previous `~1103 V` DC-link overvoltage, but the old
    actor then fails LV/recovery voltage survival.  The failure therefore
    requires matched regulating action, not a chopper-only change.
- Targeted trajectory smoke tests:
  - Balanced HVRT `1.15 pu / 80 ms`: constant action
    `[0.60, 0.00, 0.00, 0.00]`, chopper `760 V`, `Rchop` scale `0.55`,
    switch-level voltage-survival pass, score `131.977` versus conventional
    `269.359`.
  - Balanced HVRT `1.15 pu / 120 ms`: same action/chopper settings,
    switch-level voltage-survival pass, score `132.210` versus conventional
    `271.334`.
  - AB HVRT `1.15 pu / 80 ms`: constant action
    `[0.45, 0.00, 0.26, 0.00]`, chopper `780 V`, `Rchop` scale `0.65`,
    switch-level voltage-survival pass, score `131.036` versus conventional
    `232.840`.
- Actor conversion:
  - Converted the three trajectories into state-feedback SAC-format actors
    using BC/DAgger trajectory-specialist campaigns.
  - Promoted final DAgger actors:
    - `hpt_stage5_t2_bal_hvrt115_80ms_const060_actor_retry_20260727_dagger1`.
    - `hpt_stage5_t2_bal_hvrt115_120ms_const060_actor_20260727_dagger1`.
    - `hpt_stage5_t2_ab_hvrt115_80ms_reg045_energy026_actor_20260727_dagger1`.
- Exact recheck:
  - Balanced manifest:
    `sac/experiments/stage5_t2_hvrt115_balanced_const060_recheck_20260727.csv`.
  - AB manifest:
    `sac/experiments/stage5_t2_ab_hvrt115_80ms_reg045_energy026_recheck_20260727.csv`.
  - Recheck outcome:
    - Conventional voltage-survival pass: `0/3`.
    - SAC voltage-survival pass: `3/3`.
    - SAC beats conventional: `3/3`.
    - SAC envelope and recovery violations: `0.0 pu` for all three rows.
    - Balanced `80 ms`: SAC score `131.686` versus conventional `269.359`.
    - Balanced `120 ms`: SAC score `132.057` versus conventional `271.334`.
    - AB `80 ms`: SAC score `129.976` versus conventional `232.840`.
- Updated manifests and evidence:
  - Updated `sac/experiments/stage4_promoted_specialists_20260727.csv`.
  - Added `paper/evidence/stage5_topology2_hvrt115_gap_repair_20260727.md`.
- Interpretation:
  - These results close the remaining topology2 HVRT `1.15 pu`
    voltage-survival gaps.  They are still not full-FRT certified:
    balanced rows fail `grid_current_limit`, and AB `80 ms` fails
    `gbt_recover;grid_current_limit`.
- Next action:
  - Push voltage-survival expansion to topology2 HVRT `1.20 pu`, `80/120 ms`,
    and continue topology1 unbalanced score optimization before resuming full
    FRT metrics.

## 2026-07-27 - Stage-5 topology2 HVRT 1.20 pu expansion

- Goal:
  - Extend topology2 HVRT voltage-survival from `1.15 pu` to `1.20 pu` for
    balanced, A-phase, and AB-phase faults at `80/120 ms`.
- Manifest:
  - `sac/experiments/stage5_topology2_hvrt120_targets_20260727.csv`.
- Command:
  - `py -3 -m sac.campaigns.run_hpt_trustregion_promotion_matrix --manifest sac/experiments/stage5_topology2_hvrt120_targets_20260727.csv --run-id hpt_stage5_t2_hvrt120_80_120_20260727 --max-chunks 4 --chunk-steps 80 --learning-rate 4e-6 --teacher-prior-weight 120 --behavior-anchor-epochs 24 --behavior-anchor-interval-steps 40 --behavior-anchor-episodes 5 --behavior-anchor-noise-std 0.0015 --behavior-anchor-lr 4e-6 --behavior-anchor-action-weights 12,6,30,30 --advance-policy pass --train-timeout-s 900 --matlab-timeout-s 1200 --continue-after-fail`.
- Run directory:
  - `lab/results/hpt_stage5_t2_hvrt120_80_120_20260727`.
- Training outcome:
  - Balanced HVRT `1.20 pu / 80 ms`: voltage-survival candidate found,
    best passing score `138.748`, chunk 4.
  - Balanced HVRT `1.20 pu / 120 ms`: no voltage-survival candidate; all
    chunks failed `timestep_fault_lv_band` with about `0.00926 pu`
    fault-band violation.
  - A HVRT `1.20 pu / 80 ms`: voltage-survival candidate found,
    best passing score `132.233`, chunk 1.
  - A HVRT `1.20 pu / 120 ms`: voltage-survival candidate found,
    best passing score `131.574`, chunk 1.
  - AB HVRT `1.20 pu / 80 ms`: voltage-survival candidate found,
    best passing score `132.167`, chunk 1.
  - AB HVRT `1.20 pu / 120 ms`: voltage-survival candidate found,
    best passing score `132.060`, chunk 2.
- Exact recheck:
  - Manifest:
    `sac/experiments/stage5_t2_hvrt120_success_recheck_20260727.csv`.
  - Command:
    `py -3 -m sac.campaigns.run_hpt_voltage_survival_boundary_matrix --manifest sac/experiments/stage5_t2_hvrt120_success_recheck_20260727.csv --run-id hpt_stage5_t2_hvrt120_success_recheck_20260727 --controller-mode current-sac --timeout-s 2400`.
  - Run directory:
    `lab/results/hpt_stage5_t2_hvrt120_success_recheck_20260727`.
  - Result:
    - Cases: `5`.
    - Conventional voltage-survival pass: `0/5`.
    - SAC voltage-survival pass: `5/5`.
    - SAC beats conventional: `5/5`.
    - Traditional fail / SAC pass: `5/5`.
    - Traditional pass / SAC fail: `0/5`.
    - SAC envelope violation max: `0.0 pu` for all five rows.
    - SAC recovery violation max: `0.0 pu` for four rows and
      `0.00016 pu` for A-HVRT `80 ms`; all five rows pass.
- Updated manifests and evidence:
  - Added
    `sac/experiments/stage5_t2_hvrt120_success_recheck_20260727.csv`.
  - Updated `sac/experiments/stage4_promoted_specialists_20260727.csv`
    with the five exact-rechecked `1.20 pu` actors.
  - Added `paper/evidence/stage5_topology2_hvrt120_expansion_20260727.md`.
- Interpretation:
  - Topology2 HVRT voltage-survival coverage now reaches `1.20 pu` for
    balanced `80 ms`, A `80/120 ms`, and AB `80/120 ms`.
  - Balanced `1.20 pu / 120 ms` remains the next topology2 HVRT voltage
    boundary target.
  - Later fine-tune chunks sometimes reduce raw score while violating recovery;
    candidate selection must remain gate-first rather than raw-score-first.
- Next action:
  - Repair balanced HVRT `1.20 pu / 120 ms` with fault-band-aware trajectory
    shaping or lower regulating action.
  - Rerun a compact boundary matrix that includes all Stage-5 `1.15` and
    `1.20` promoted actors.
  - Resume topology1 unbalanced score optimization after the topology2 HVRT
    boundary is compactly rechecked.

## 2026-07-27 - Stage-5 topology2 balanced HVRT 1.20 pu / 120 ms repair

- Goal:
  - Close the only remaining topology2 HVRT `1.20 pu` voltage-survival gap:
    balanced `120 ms`.
- Diagnostic:
  - The previous trust-region candidate over-boosted the fault-window LV band
    by about `0.009 pu`.
  - A lower regulating d-axis command was tested to reduce over-boost while
    preserving recovery.
- Smoke command:
  - `py -3 -m sac.validate_hpt_trajectory_switchlevel --run-id hpt_stage5_t2_bal_hvrt120_120ms_reg055_smoke_20260727 --topology topology2 --fault-pu 1.20 --duration-s 0.12 --fault-start 0.035 --fault-stop-margin 0.125 --fault-settle-s 0.020 --chopper-threshold 760 --rchop-scale 0.55 --preset constant --action 0.55 0 0 0 --timeout-s 1200`.
- Smoke result:
  - Conventional voltage-survival pass: `false`.
  - Constant trajectory voltage-survival pass: `true`.
  - Trajectory score: `137.641` versus conventional `272.305`.
  - LV fault/recovery means: `224.410 / 203.022 V`.
  - DC link min/max: `739.08 / 802.29 V`.
  - Envelope and recovery violations: `0.0 pu`.
- Actor conversion command:
  - `py -3 -m sac.run_hpt_trajectory_specialist_campaign --run-id hpt_stage5_t2_bal_hvrt120_120ms_reg055_actor_20260727 --topology topology2 --fault-pu 1.20 --duration-s 0.12 --fault-start 0.035 --fault-stop-margin 0.125 --fault-settle-s 0.020 --case-name balanced_hvrt1p200_120ms --case-contains hvrt_120ms_1.200pu --chopper-threshold 760 --rchop-scale 0.55 --actor-filter-tau 0.001 --preset constant --action 0.55 0 0 0 --safe-target 0.55 0 0 0 --dagger-iters 1 --dagger-label-source trajectory --switch-trace-repeat 96 --epochs 100 --batch-size 512 --lr 2e-4 --action-weights 12,4,1,1 --bc-obs-noise-std 0.008 --bc-obs-noise-repeat 3 --collect-final-actor-trace --matlab-timeout-s 1200 --train-timeout-s 700`.
- Actor conversion result:
  - BC0 actor and DAgger1 actor both passed switch-level voltage-survival and
    beat the conventional baseline.
  - BC0 was selected because it had the lower score:
    `137.770` versus DAgger1 `138.208`.
  - BC0 LV fault min/max: `215.77 / 237.63 V`.
  - BC0 LV recovery mean: `204.38 V`.
  - BC0 DC link min/max: `737.13 / 800.37 V`.
  - BC0 full-FRT reason remains `grid_current_limit`; this is not claimed as
    full-FRT certification.
- Exact recheck:
  - Manifest:
    `sac/experiments/stage5_t2_bal_hvrt120_120ms_reg055_recheck_20260727.csv`.
  - Command:
    `py -3 -m sac.campaigns.run_hpt_voltage_survival_boundary_matrix --manifest sac/experiments/stage5_t2_bal_hvrt120_120ms_reg055_recheck_20260727.csv --run-id hpt_stage5_t2_bal_hvrt120_120ms_reg055_recheck_20260727 --controller-mode current-sac --timeout-s 1800`.
  - Run directory:
    `lab/results/hpt_stage5_t2_bal_hvrt120_120ms_reg055_recheck_20260727`.
  - Result:
    - Cases: `1`.
    - Conventional voltage-survival pass: `0/1`.
    - SAC voltage-survival pass: `1/1`.
    - SAC beats conventional: `1/1`.
    - Traditional fail / SAC pass: `1/1`.
    - SAC score: `137.770` versus conventional `272.305`.
    - SAC envelope and recovery violations: `0.0 pu`.
    - SAC DC link min/max: `737.13 / 800.37 V`.
- Updated manifests and evidence:
  - Added
    `sac/experiments/stage5_t2_bal_hvrt120_120ms_reg055_recheck_20260727.csv`.
  - Updated `sac/experiments/stage4_promoted_specialists_20260727.csv`
    with the repaired balanced `1.20 pu / 120 ms` actor.
  - Updated `paper/evidence/stage5_topology2_hvrt120_expansion_20260727.md`.
- Interpretation:
  - Topology2 HVRT `1.20 pu` voltage-survival now covers balanced, A-phase,
    and AB-phase cases at `80/120 ms`, all exact-rechecked and all beating the
    traditional dq baseline under the voltage-survival validator.
- Next action:
  - Rerun a compact Stage-5 boundary matrix that includes all new `1.15 pu` and
    `1.20 pu` promotions.
  - Continue topology1 unbalanced score optimization; that line is now the main
    remaining voltage-survival improvement target before full-FRT work resumes.

## 2026-07-27 - Stage-5 topology2 HVRT 1.15/1.20 compact recheck

- Goal:
  - Recheck all Stage-5 topology2 HVRT `1.15/1.20 pu`, `80/120 ms`
    specialists in one validator run.
- Manifest:
  - `sac/experiments/stage5_t2_hvrt115_120_compact_recheck_20260727.csv`.
  - Generated from `sac/experiments/stage4_promoted_specialists_20260727.csv`
    by selecting topology2 HVRT rows with fault magnitude `1.150` or `1.200`.
- Command:
  - `py -3 -m sac.campaigns.run_hpt_voltage_survival_boundary_matrix --manifest sac/experiments/stage5_t2_hvrt115_120_compact_recheck_20260727.csv --run-id hpt_stage5_t2_hvrt115_120_compact_recheck_20260727 --controller-mode current-sac --timeout-s 3600`.
- Run directory:
  - `lab/results/hpt_stage5_t2_hvrt115_120_compact_recheck_20260727`.
- Result:
  - Cases: `12`.
  - Conventional voltage-survival pass: `0/12`.
  - SAC voltage-survival pass: `12/12`.
  - SAC beats conventional: `12/12`.
  - Traditional fail / SAC pass: `12/12`.
  - Traditional pass / SAC fail: `0/12`.
  - Maximum SAC envelope violation: `0.0 pu`.
  - Maximum SAC recovery violation: `0.000160 pu`.
- Score range:
  - A-phase rows: SAC beats conventional by about `101.6-103.0` score units.
  - AB-phase rows: SAC beats conventional by about `102.3-105.9` score units.
  - Balanced rows: SAC beats conventional by about `132.8-139.3` score units.
- Evidence:
  - Added
    `paper/evidence/stage5_topology2_hvrt115_120_compact_recheck_20260727.md`.
- Interpretation:
  - Stage-5 topology2 HVRT voltage-survival evidence is now compactly
    reproducible for `1.15/1.20 pu`, `80/120 ms`, balanced, A-phase, and
    AB-phase cases.
  - This remains a voltage-survival claim only; full-FRT current-related
    failures, especially `grid_current_limit`, remain for later work.
- Next action:
  - Shift the active voltage-survival improvement target back to topology1
    unbalanced score optimization, where survival exists but beating the
    conventional dq baseline is still the hard part.

## 2026-07-27 - Stage-5 remaining-evidence refresh and topology1 score diagnostic

- Goal:
  - Fill the remaining reviewer-grade evidence gap for the bounded
    switch-level voltage-survival claim, while checking whether topology1
    unbalanced score optimization can beat the tested conventional baseline.
- Interface fixes:
  - Updated
    `sac/campaigns/run_hpt_protected_sac_finetune.py` so
    score-optimization curricula such as `scoreopt_topology1_lvrt_a` are
    mapped to trainable offline curriculum labels.
  - Updated
    `sac/campaigns/run_hpt_reviewer_evidence_campaign.py` so
    robustness defaults to the latest
    `sac/experiments/stage4_promoted_specialists_20260727.csv`.
  - Fixed proxy holdout summary extraction in the reviewer-evidence runner;
    verifier outputs are named `proxy_rollout_*_summary.json`, not
    `summary.json`.
- Topology1 A-LVRT 0.85 pu / 80 ms score diagnostics:
  - Protected proxy-SAC run:
    `hpt_stage5_t1_unbalanced_scoreopt_top8_r2_20260727`.
    The first case completed four chunks; all chunks preserved
    voltage-survival but worsened the score versus the current actor.  The run
    was stopped after this diagnostic because the direction was not productive.
  - Coarse trajectory sweep:
    `hpt_stage5_t1_a_lvrt085_80ms_score_sweep_20260727`.
    16/16 completed, 4/16 voltage-survival pass, 0/16 beat conventional.
  - Refined trajectory sweep:
    `hpt_stage5_t1_a_lvrt085_80ms_score_sweep_refined_20260727`.
    15/15 completed, 10/15 voltage-survival pass, 0/15 beat conventional.
    Best valid score was `148.131` at `fault_reg_d=0.55`,
    `recovery_reg_d=0.28`, versus conventional `146.777`.
    Lower raw-score candidates at `fault_reg_d=0.60` were rejected by
    `dc_link_bounds`, even though their envelope metrics were otherwise near
    zero.
- Fresh reviewer-evidence campaign:
  - Command:
    `py -3 -m sac.campaigns.run_hpt_reviewer_evidence_campaign --run-id hpt_reviewer_evidence_stage5_20260727 --stage all --ablation-epochs 120 --max-ablation-cases 2 --max-baseline-param-sets 3 --max-proxy-matrices 2 --max-robustness-cases 4 --max-robustness-variants 4 --matlab-timeout-s 2400 --ablation-timeout-s 3000 --proxy-timeout-s 1200 --robustness-timeout-s 3000`.
  - Run directory:
    `lab/results/hpt_reviewer_evidence_stage5_20260727`.
  - Result:
    `15` subprocesses, `0` nonzero return codes.
- Ablation result:
  - topology2 A-HVRT `1.05 pu / 60 ms`: teacher replay, BC, and BC+DAgger
    all passed voltage-survival and beat conventional.  Scores were
    `126.275`, `126.052`, and `125.846`, versus conventional `145.478`.
  - topology1 balanced LVRT `0.90 pu / 80 ms`: teacher replay passed and beat
    conventional (`160.680` versus `169.173`), but BC failed
    `timestep_fault_lv_band;timestep_voltage_envelope`, and BC+DAgger failed
    `timestep_recovery_envelope`.
- Baseline tuning result:
  - Conventional dq scale sweep over scales `0.45`, `0.55`, `0.70` produced
    `0/12` voltage-survival pass and `0/12` full-FRT pass for each scale.
  - Dominant strict-gate failures were timestep voltage envelope, fault LV
    band, recovery envelope, and DC-link bounds.
- Proxy holdout result:
  - Local 52-row support matrix replayed near exactly.
  - Broader 104-row matrix retained non-trivial mismatch:
    LV mean MAE `0.0307 pu`, Vdc mean MAE `0.0262 pu`, grid iq mean MAE
    `0.0442 pu`, fault-band max MAE `0.0198 pu`, recovery max MAE
    `0.00589 pu`.
  - Proxy remains suitable for screening/warm-start/local search, not final
    claims.
- Robustness result:
  - Using four current promoted specialists:
    fault-start +5 ms passed/beat `3/4`, fault-start -5 ms passed/beat `2/4`,
    Rchop +10% passed/beat `3/4`, actor tau 2 ms passed/beat `2/4`.
  - Full-FRT pass remained `0/4` for all variants.
- Evidence:
  - Added
    `paper/evidence/stage5_reviewer_evidence_refresh_20260727.md`.
  - Updated `paper/evidence/REPORT.md` with a Stage-5 evidence-refresh index.
- Interpretation:
  - The remaining 20% is now mostly an evidence-boundary problem, not a
    missing-run problem for voltage-survival: topology2 HVRT evidence is
    strong, topology1 score optimization has an honest hard boundary, and the
    reviewer evidence gaps have fresh data.
  - The paper claim should remain bounded to switch-level voltage survival.
    Full FRT certification and globally robust/unified SAC are still future
    phases.
- Next action:
  - For topology1 hard LVRT/unbalanced cases, move beyond simple d-axis
    fault/recovery trajectories and add recovery-aware q-axis/DC-link shaping.
  - For publication, use this evidence package to revise the manuscript claim
    language and tables, while clearly separating L1 voltage survival from
    current/reactive/full-FRT criteria.

## 2026-07-27 - Voltage-survival manuscript completion pass

- Scope:
  - Revised `paper/hpt_sac_voltage_survival_manuscript.md` using the
    `research-paper-writing` skill guidelines and the HPT evidence boundary.
  - This was a manuscript/evidence-integration pass only; no new Simulink or
    SAC experiments were run.
- Manuscript changes:
  - Updated the abstract and contribution list to include the Stage-5
    topology2 HVRT expansion evidence while preserving the bounded L1
    load-side voltage-survival claim.
  - Added a Stage-5 topology2 HVRT results subsection:
    1.10 pu A/AB 80/120 ms exact recheck `4/4` pass and beat, and
    1.15/1.20 pu balanced/A/AB 80/120 ms compact recheck `12/12` pass and
    beat.
  - Added reviewer-evidence subsection covering ablation, conventional
    baseline scale sweep, proxy holdout alignment, and reduced robustness.
  - Updated reproducibility paths to point to the Stage-5 evidence notes and
    result directories.
  - Updated the conclusion to distinguish switch-level voltage survival from
    current-safe survival, reactive-support FRT, and full grid-code FRT
    certification.
- Evidence boundary:
  - The manuscript now supports only switch-level-promoted,
    case-specialized voltage-survival claims.
  - It still does not claim unified SAC, full GB/T FRT certification, globally
    reliable proxy training, or superiority over every possible conventional
    tuning.

## 2026-07-27 - Voltage-survival manuscript figure package

- Scope:
  - Generated a reproducible paper figure package under `paper/figures`.
  - This was a visualization and manuscript-integration pass only; no new
    Simulink or SAC experiments were run.
- Added files:
  - `paper/figures/FIGURE_PLAN.md`.
  - `paper/figures/make_voltage_survival_figures.py`.
  - Ten PNG/PDF figure pairs:
    topology/control interface, training-promotion pipeline, state-feedback
    actor interface, voltage-survival gate, switch-level boundary summary,
    representative metric-derived trajectory comparison, SAC convergence,
    teacher/BC/DAgger ablation, proxy alignment, and topology1 unbalanced
    tradeoff.
- Manuscript integration:
  - Added a `6.8` figure-summary subsection to
    `paper/hpt_sac_voltage_survival_manuscript.md` with links and captions.
- Evidence boundary:
  - Quantitative figures read current evidence CSV/JSON where available.
  - The representative waveform figure is metric-derived from switch-level
    summary rows and is explicitly labeled as not being a raw time-series
    export.
  - The package continues to support only switch-level voltage-survival claims,
    not full FRT certification.
- Figure revision:
  - Revised Fig. 7 from a potentially misleading monotonic "SAC convergence"
    curve into a training-diagnostics figure: BC/DAgger imitation loss on the
    left and protected SAC switch-level promotion trace on the right.
  - The caption now states that protected SAC starts from BC+DAgger and chunk
    scores need not be monotonic.

## 2026-07-27 - Topology2 Simulink fault control trace gallery

- Scope:
  - Generated raw Simulink-exported control-step trace figures for one topology
    only, as requested. The selected topology is `topology2`.
  - Fault set: balanced, A, B, C, AB, BC, and CA phase modes for LVRT
    `0.90 pu / 60 ms` and HVRT `1.10 pu / 60 ms`.
- Command:
  - `py -3.8 paper/figures/simulink_fault_control_plots/run_topology2_fault_plot_gallery.py`
- Output:
  - `paper/figures/simulink_fault_control_plots/INDEX.md`
  - 14 trace CSV files, 14 PNG files, 14 PDF files, and 14 MATLAB logs.
- Evidence boundary:
  - These are actual Simulink switch-level traces exported at the 2-ms control
    stride by `eval_hpt_v2_sac_single_case.m`.
  - The gallery uses the current active dynamic SAC actor path. It is not a
    conventional-vs-SAC overlay and not guaranteed to be the per-case accepted
    specialist for every scenario.
  - Some plots are therefore diagnostic failure/survival traces rather than
    final paper-pass evidence.

## 2026-07-27 - Figure QA for Simulink trace gallery and SAC training diagnostics

- Scope:
  - Reviewed all 14 topology2 fault-control trace figures through a contact
    sheet and CSV-derived summary metrics.
  - Reworked `fig07_sac_training_convergence` because the previous version did
    not visibly separate SAC training from switch-level promotion checks.
- Findings:
  - The topology2 gallery is useful as a Simulink diagnostic set, but it is not
    a final accepted-specialist evidence set: many traces show late DC-link
    collapse or DC-link overvoltage, and energy-branch actor actions remain near
    zero.
  - LVRT cases have lower evaluator window-ok rates than HVRT cases; the
    gallery should not be used to claim all representative faults pass.
  - The original Fig. 7 mainly showed BC/DAgger imitation loss and protected SAC
    promotion score, so it looked unlike a SAC training curve.
- Changes:
  - Updated `paper/figures/make_voltage_survival_figures.py` to redraw Fig. 7 as
    four diagnostics: imitation warm start, proxy-side SAC return,
    behavior-anchor loss, and switch-level promotion score.
  - Regenerated `paper/figures/fig07_sac_training_convergence.{png,pdf}`.
  - Updated the Fig. 7 caption in
    `paper/hpt_sac_voltage_survival_manuscript.md`.
- Next action:
  - For paper-ready fault control plots, generate conventional-vs-accepted-SAC
    overlays using per-case accepted specialists rather than the current active
    dynamic actor trace.

## 2026-07-27 - Stage-6 fault-family repair plan and recheck smoke

- Scope:
  - Organized the next SAC repair campaign around the four current weaknesses:
    12 representative specialists rather than 8, clear BC/DAgger/SAC
    provenance, fault-family rather than fixed-point claims, and measured SAC
    fine-tune contribution.
  - Added `docs/specs/algorithms/hpt-sac-controller/hpt-sac-controller-stage6-fault-family-repair-plan-2026-07-27.md`.
  - Added `sac/experiments/stage6_fault_family_experiment_matrix_20260727.csv`
    with 12 representative topology/fault rows.
  - Added `sac/experiments/stage6_recheck_manifest_current10_20260727.csv`
    with the 10 currently executable center-case actors.
  - Added `sac/experiments/stage6_fault_family_runbook_20260727.md`
    with canonical commands for recheck and missing topology1 A/AB-HVRT gap
    training.
- Validation:
  - CSV matrix shape: 12 rows; current status split is 10
    `needs_stage6_recheck` and 2 `missing_actor`.
  - All 10 recheck-manifest actor paths exist.
  - MATLAB interface dry run passed:
    `py -3.8 -m sac.smoke_matlab_engine --dry-run`.
  - Stage-6A switch-level smoke command:
    `py -3.8 -m sac.validate_hpt_accepted_specialists --manifest sac/experiments/stage6_recheck_manifest_current10_20260727.csv --run-id hpt_stage6_recheck_current10_smoke_20260727 --max-cases 1 --timeout-s 1200`.
  - Smoke result: 1/1 voltage-survival pass, 1/1 beat conventional, 0/1 full
    FRT pass.  The case was `t1_balanced_lvrt`, with policy score 104.012
    versus conventional score 122.356 and full-FRT failure reason
    `gbt_recover;grid_current_limit;not_evaluated_no_sustained_reactive_demand_after_delay`.
- Evidence boundary:
  - The smoke supports the current voltage-survival claim only; it does not
    upgrade the result to full FRT.
- Next action:
  - Run the full 10-case Stage-6A recheck.
  - Train the two missing topology1 A-HVRT and topology1 AB-HVRT center cases,
    then assemble the 12-case Stage-6 representative manifest.

## 2026-07-27 - Stage-6A current-10 switch-level recheck

- Scope:
  - Executed the current 10-case representative recheck manifest:
    `sac/experiments/stage6_recheck_manifest_current10_20260727.csv`.
  - The two intentionally excluded rows are the missing topology1 A-HVRT and
    topology1 AB-HVRT center specialists.
- Command:
  - `py -3.8 -m sac.validate_hpt_accepted_specialists --manifest sac/experiments/stage6_recheck_manifest_current10_20260727.csv --run-id hpt_stage6_recheck_current10_20260727 --timeout-s 1200`.
- Result:
  - 10 / 10 switch-level voltage-survival pass.
  - 8 / 10 beat conventional.
  - 0 / 10 full FRT pass.
  - Result CSV:
    `lab/results/hpt_stage6_recheck_current10_20260727/accepted_specialist_validation.csv`.
  - Report:
    `lab/results/hpt_stage6_recheck_current10_20260727/REPORT.md`.
- Important case findings:
  - topology1 A-LVRT and topology1 AB-LVRT pass voltage survival but do not
    beat conventional under the current score.
  - topology2 A-HVRT and topology2 AB-HVRT now have center-case switch-level
    voltage-survival and beat-conventional evidence for the 12-case matrix.
  - Full-FRT remains false for all checked cases, with grid-current/recovery or
    reactive-current evaluation reasons; keep the paper claim bounded to
    voltage survival.
- Next action:
  - Train/search topology1 A-HVRT and topology1 AB-HVRT 1.10 pu / 60 ms
    center specialists, then re-run a full 12-case Stage-6 representative
    manifest.

## 2026-07-27 - Stage-6A topology1 HVRT unbalanced fallback and CEM repair

- Scope:
  - Probed the two missing topology1 HVRT unbalanced representative cases with
    the existing topology1 balanced-HVRT actor.
  - Fixed a trajectory-interface inconsistency discovered while preparing the
    missing-case training path.
  - Ran a first topology1 A-HVRT CEM trajectory search and a follow-up
    hand-designed positive-d trajectory validation.
- Interface fixes:
  - `sac/validate_hpt_trajectory_switchlevel.py` now accepts the
    `fault_recovery` trajectory preset.
  - `sac/pretrain_hpt_actor_bc.py` now accepts
    `fault_recovery` as `--switch-trace-target-profile`.
  - `sac/search_hpt_frt_trajectory_cem.py` now allows positive
    HVRT `reg_boost` candidates and includes positive-d HVRT anchors, because
    the previous HVRT bounds excluded the known topology1 balanced-HVRT
    operating region.
- Fallback probe:
  - Manifest:
    `sac/experiments/stage6_probe_t1_hvrt_unbalanced_fallback_manifest_20260727.csv`.
  - Command:
    `py -3.8 -m sac.validate_hpt_accepted_specialists --manifest sac/experiments/stage6_probe_t1_hvrt_unbalanced_fallback_manifest_20260727.csv --run-id hpt_stage6_probe_t1_hvrt_unbalanced_fallback_20260727 --timeout-s 1200`.
  - Result: 2 / 2 voltage-survival pass, 0 / 2 beat conventional, 0 / 2 full
    FRT pass.
  - Interpretation: the 12 center fault types now have voltage-survival
    coverage, but topology1 A/AB-HVRT still need independent
    score-improving specialists.
- Failed/diagnostic training attempts:
  - `hpt_stage6_t1_a_hvrt110_60ms_20260727` failed before Simulink because
    the `fault_recovery` preset lacked explicit timing parameters.
  - `hpt_stage6_t1_a_hvrt110_60ms_20260727_r2` reached switch-level
    trajectory validation but used the wrong negative-d teacher sign; the
    trajectory failed voltage survival and was worse than conventional.  The
    run then exposed the `fault_recovery` BC-interface mismatch, which is now
    fixed.
- CEM search:
  - Command:
    `py -3.8 -m sac.search_hpt_frt_trajectory_cem --run-id hpt_stage6_t1_a_hvrt110_cem_20260727 --topology topology1 --fault-pu 1.10 --fault-phase-pu 1.10 1.00 1.00 --duration-s 0.060 --fault-start 0.035 --fault-settle-s 0.020 --case-name topology1_a_hvrt110_60ms_stage6 --iterations 3 --population 48 --switch-top-k 6 --return-to-zero --timeout-s 1200`.
  - Result: 6 switch-level candidates, 0 voltage-survival passes.
  - Main finding: the previous CEM bounds biased HVRT toward recovery-only
    positive-d or negative-d regions and did not adequately cover sustained
    positive-d HVRT control.
- Positive-d trajectory validation:
  - Command:
    `py -3.8 -m sac.validate_hpt_trajectory_switchlevel --run-id hpt_stage6_t1_a_hvrt110_pos249_window_val_20260727 --topology topology1 --preset two_stage_window --fault-pu 1.10 --fault-phase-pu 1.10 1.00 1.00 --duration-s 0.060 --fault-start 0.035 --fault-stop-margin 0.125 --fault-settle-s 0.020 --case-name topology1_a_hvrt110_60ms_stage6_pos249_window --base-action 0.00 0.00 0.00 0.00 --start-action 0.249 0.00 -0.005 0.00 --action 0.249 0.00 -0.005 0.00 --ramp-start 0.030 --step-time 0.035 --ramp-end 0.040 --down-start 0.095 --down-end 0.105 --chopper-threshold 850.0 --rchop-scale 1.0 --timeout-s 1200`.
  - Result: fixed constant positive-d action passed voltage survival but did
    not beat conventional; the fast-return trajectory failed recovery envelope.
- Updated artifacts:
  - `sac/experiments/stage6_recheck_manifest_current12_with_t1_hvrt_fallback_20260727.csv`.
  - `docs/specs/algorithms/hpt-sac-controller/hpt-sac-controller-stage6-recheck-status-2026-07-27.md`.
  - `sac/experiments/stage6_fault_family_runbook_20260727.md`.
- Next action:
  - Re-run topology1 A-HVRT CEM after the positive-HVRT bounds fix, without
    forcing return-to-zero, so sustained positive-d candidates similar to the
    balanced HVRT actor can be evaluated.
  - If no candidate beats conventional, keep topology1 A/AB-HVRT as
    voltage-survival-only fallback rows and move the SAC contribution study to
    topology2 HVRT where stronger beat-conventional evidence already exists.

## 2026-07-28 - Stage-6 four-issue audit

- Scope:
  - Audited whether the four Stage-6 repair issues are complete:
    12 representative specialists, BC/DAgger/SAC provenance, fault-family
    specialists, and SAC fine-tune contribution.
- Evidence checked:
  - `lab/results/hpt_stage6_recheck_current10_20260727/accepted_specialist_validation.csv`.
  - `lab/results/hpt_stage6_probe_t1_hvrt_unbalanced_fallback_20260727/accepted_specialist_validation.csv`.
  - `docs/specs/algorithms/hpt-sac-controller/hpt-sac-controller-stage6-recheck-status-2026-07-27.md`.
- Result:
  - The four issues are not fully complete.
  - Current case-specific evidence is 10 / 10 switch-level voltage-survival
    passes, 8 / 10 beat-conventional passes, and 0 / 10 full-FRT passes.
  - The two missing topology1 A/AB-HVRT rows have fallback voltage-survival
    coverage using the topology1 balanced-HVRT actor, but they are not
    independent fault-specific specialists and do not beat conventional.
  - Fault-family evidence and per-case SAC contribution ablation remain open.
- Artifact:
  - Added
    `docs/specs/algorithms/hpt-sac-controller/hpt-sac-controller-stage6-four-issue-audit-2026-07-28.md`.
- Next action:
  - Continue with topology1 A/AB-HVRT independent repair, then run
    12-row consolidation and per-case provenance/ablation.

## 2026-07-28 - Topology1 A-HVRT score repair and SAC fine-tune diagnostics

- Scope:
  - Re-scoped the user-facing completion gate to final SAC-vs-conventional
    switch-level superiority. Teacher replay / BC / BC+DAgger ablation is no
    longer a required gate for this user-scoped target.
  - Focused on the missing topology1 A-HVRT 1.10 pu / 60 ms case.
- Code changes:
  - `sac/offline/train_hpt_voltage_sac.py` now writes
    `sac_training_reward_trace.csv` for SAC training, including partial
    chunks shorter than one full episode. This supports convergence figures
    from raw training reward logs.
- Experiments:
  - CEM sustained positive-d search:
    `hpt_stage6_t1_a_hvrt110_cem_sustained_20260728`.
    Result: 8 switch-level candidates, 0 voltage-survival passes. The proxy
    selected under-supported fault-window actions.
  - Positive-d fault/recovery sweep:
    `hpt_stage6_t1_a_hvrt110_score_sweep_posd_20260728`.
    Result: 9 / 9 voltage-survival passes, 0 / 9 beat conventional.
  - Pre-biased positive-d sweep:
    `hpt_stage6_t1_a_hvrt110_score_sweep_prebias_20260728`.
    Result: 8 / 8 voltage-survival passes, 1 / 8 beat conventional. Best
    trajectory used `pre_reg_d=0.24`, `fault_reg_d=0.30`,
    `recovery_reg_d=0.30`, `energy_d=-0.005`, scoring 105.140 versus
    conventional 105.229 with zero envelope violations.
  - Actor distillation:
    `hpt_stage6_t1_a_hvrt110_prebias_actor_20260728`.
    Result: final actor passed voltage survival but did not beat conventional:
    105.261 versus 105.229.
  - Protected SAC fine-tune:
    `hpt_stage6_t1_a_hvrt110_prebias_sacft_20260728` and
    `hpt_stage6_t1_a_hvrt110_prebias_sacft_relaxed_20260728`.
    Result: strong-anchor SAC produced no score movement; relaxed-anchor SAC
    produced reward traces but broke voltage survival.
- Interpretation:
  - Topology1 A-HVRT now has a switch-level trajectory that beats conventional,
    but not yet a final SAC actor that beats conventional.
  - The remaining gap is trajectory-to-actor fidelity/direct state-feedback
    optimization, not discovery of a feasible switch-level trajectory.
- Next action:
  - Try AB-HVRT with the same pre-biased positive-d sweep pattern.
  - For A-HVRT, improve actor fidelity around the pre-biased trajectory before
    further SAC fine-tune.

## 2026-07-28 - Topology1 AB-HVRT trajectory margin and actor-fidelity diagnostics

- Scope:
  - Continued the Stage-6 repair around the missing topology1 AB-HVRT
    1.10 pu / 60 ms representative case.
  - Preserved the user-scoped completion gate: final SAC/state-feedback actor
    must pass switch-level voltage survival and beat `conventional_dq`.
  - Added SAC reward-trace logging to
    `sac/offline/train_hpt_voltage_sac.py`; future SAC fine-tune
    runs now write `sac_training_reward_trace.csv`, including partial chunks
    shorter than a full episode.
- Trajectory results:
  - Pre-biased positive-d sweep:
    `hpt_stage6_t1_ab_hvrt110_score_sweep_prebias_20260728`.
    Result: 8 / 8 voltage-survival passes, 1 / 8 beat-conventional.
    Best trajectory scored `104.911` versus conventional `104.983`.
  - Local margin sweep:
    `hpt_stage6_t1_ab_hvrt110_score_sweep_margin_20260728`.
    The run was intentionally stopped after the first two fault-d groups once
    the best direction was clear.  Best completed trajectory used
    `pre_reg_d=0.20`, `fault_reg_d=0.21`, `recovery_reg_d=0.30`,
    `energy_d=-0.005`, scoring `104.714` versus conventional `104.983` with
    zero sampled voltage-survival violations.
- Actor results:
  - Direct actor from the pre-biased trajectory:
    `hpt_stage6_t1_ab_hvrt110_prebias_actor_20260728`.
    Voltage-survival pass, but no beat: `105.328` versus `104.983`.
  - Tau-0 recheck of that actor:
    `hpt_stage6_t1_ab_hvrt110_prebias_actor_tau0_recheck_20260728`.
    Voltage-survival pass, but no beat: `105.363` versus `104.983`.
  - Direct actor from the margin trajectory:
    `hpt_stage6_t1_ab_hvrt110_margin_actor_20260728`.
    Voltage-survival pass, but no beat: `105.664` versus `104.983`.
    Trace alignment showed poor `m_reg_d` fidelity
    (`m_reg_d_mae ~= 0.0266`, `lv_rms_mae ~= 4.65 V`).
  - Phase-aware diagnostic actor:
    `hpt_stage6_t1_ab_hvrt110_margin_actor_phaseaware_20260728`.
    Voltage-survival pass, near-beat but still below the gate:
    `104.996` versus `104.983`.  Trace alignment improved markedly
    (`m_reg_d_mae ~= 0.00906`, `lv_rms_mae ~= 1.47 V`).
  - Phase-aware tau-0 recheck:
    `hpt_stage6_t1_ab_hvrt110_phaseaware_tau0_recheck_20260728`.
    Voltage-survival pass, but worse score: `106.110` versus `104.983`.
- Interpretation:
  - The missing topology1 AB-HVRT row now has switch-level
    beat-conventional trajectory evidence, but not a final accepted actor.
  - The actor bottleneck is trajectory-to-state-feedback fidelity around the
    prefault/fault/recovery phase, not discovery of a feasible trajectory.
  - Scheduled phase features nearly close the gap, but are diagnostic only
    unless replaced by online fault/recovery detector features or a validated
    recurrent/history-based actor interface.
- Next action:
  - Add an online phase-feature repair that does not rely on known future fault
    times, then re-run AB-HVRT and A-HVRT actor distillation and protected SAC
    fine-tune using the new reward-trace logging.

## 2026-07-28 - Online detector repair and topology1 AB-HVRT SAC promotion

- Scope:
  - Continued Stage-6 topology1 AB-HVRT 1.10 pu / 60 ms repair.
  - Preserved the user-facing completion gate: SAC-updated state-feedback
    actor must pass switch-level voltage survival and beat `conventional_dq`.
- Code changes:
  - Updated `simulink/add_hpt_sac_controller.m` online
    fault/recovery detector.
  - Added an HVRT falling-edge clear condition with a minimum fault-age gate so
    unbalanced HVRT recovery is not mistaken for a continuing fault and fault
    clearing is not detected too early.
- Detector validation:
  - Trace:
    `lab/results/hpt_v2_trajectory_traces/trajectory_trace_topology1_stage6_t1_ab_hvrt_detector_fix8_trace_20260728_033005.csv`.
  - Fault window flags were correct: `obs_17 = 1`, `obs_18 = 0`.
  - Recovery window flags were correct: `obs_17 = 0`, `obs_18 = 1`.
  - Interface smoke passed:
    `py -3.8 -m sac.smoke_matlab_engine --runner batch --test interface --timeout-s 900`.
- Actor distillation:
  - Run:
    `hpt_stage6_t1_ab_hvrt110_margin_actor_detectorfix_20260728`.
  - Distilled state-feedback actor passed voltage survival and beat
    conventional: policy score `104.879` versus conventional score `109.170`.
  - Trace alignment improved to `m_reg_d` MAE `0.00833`, LV RMS MAE `1.41 V`,
    Vdc MAE `1.05 V`.
- Protected SAC fine-tune:
  - Run:
    `hpt_stage6_t1_ab_hvrt110_detectorfix_sacft_20260728`.
  - All 4 SAC-updated chunks passed switch-level voltage survival and beat
    conventional.
  - Best SAC chunk: chunk 01, score `104.717` versus conventional `109.170`.
  - Best model:
    `data/models/hpt_stage6_t1_ab_hvrt110_detectorfix_sacft_20260728_chunk01.zip`.
  - Best voltage-survival gate details: envelope violation `0`, recovery
    violation `0`, fault LV band violation `0`, `vdc_min = 768.75 V`,
    `vdc_max = 878.66 V`.
  - Full FRT remains false due grid-current/reactive-current items; this is
    still a voltage-survival result.
- Reward/convergence artifacts:
  - Each SAC chunk wrote `sac_training_reward_trace.csv`.
  - Combined reward CSV:
    `lab/results/hpt_stage6_t1_ab_hvrt110_detectorfix_sacft_20260728/sac_training_reward_trace_combined.csv`.
  - Convergence figure:
    `lab/results/hpt_stage6_t1_ab_hvrt110_detectorfix_sacft_20260728/sac_reward_and_switch_score_convergence.png`.
- Interpretation:
  - Topology1 AB-HVRT now has a non-oracle online-detector SAC-updated actor
    that passes switch-level voltage survival and beats conventional.
  - The remaining missing topology1 unbalanced HVRT representative row is
    A-HVRT; it should be rerun through the same detector-repaired
    actor-distillation and protected-SAC pipeline.

## 2026-07-28 - Topology1 A-HVRT detector-fixed SAC promotion

- Scope:
  - Applied the detector-repaired actor-distillation and protected-SAC
    pipeline to topology1 A-phase HVRT 1.10 pu / 60 ms.
  - User-facing completion gate remained SAC-updated actor versus
    `conventional_dq`, not BC/DAgger ablation.
- Actor distillation:
  - Run:
    `hpt_stage6_t1_a_hvrt110_prebias_actor_detectorfix_20260728`.
  - Source trajectory stayed switch-level valid and beat conventional:
    `105.140` versus `107.784`.
  - Distilled state-feedback actor passed switch-level voltage survival and
    beat conventional:
    `104.737` versus `107.784`.
  - Trace alignment: `m_reg_d` MAE `0.01043`, LV RMS MAE `1.21 V`, Vdc MAE
    `1.14 V`.
- Protected SAC fine-tune:
  - Run:
    `hpt_stage6_t1_a_hvrt110_detectorfix_sacft_20260728`.
  - All 4 SAC chunks passed switch-level voltage survival and beat
    conventional.
  - Best SAC chunk: chunk 03,
    `data/models/hpt_stage6_t1_a_hvrt110_detectorfix_sacft_20260728_chunk03.zip`.
  - Best score:
    `104.654` versus conventional `107.784`, improvement `3.130`.
  - Voltage-survival details: envelope violation `0`, recovery violation `0`,
    fault LV band violation `0`, `vdc_min = 766.74 V`,
    `vdc_max = 876.91 V`.
  - Full FRT remains false because grid-current/reactive-current requirements
    are not yet satisfied/evaluated.
- Reward/convergence artifacts:
  - Combined reward CSV:
    `lab/results/hpt_stage6_t1_a_hvrt110_detectorfix_sacft_20260728/sac_training_reward_trace_combined.csv`.
  - Convergence figure:
    `lab/results/hpt_stage6_t1_a_hvrt110_detectorfix_sacft_20260728/sac_reward_and_switch_score_convergence.png`.
  - Promotion manifest:
    `sac/experiments/stage6_t1_a_hvrt110_detectorfix_sacft_20260728.csv`.
- Interpretation:
  - The two previously missing topology1 unbalanced HVRT representative rows
    now have non-oracle online-detector SAC-updated actors that pass
    switch-level voltage survival and beat conventional.
  - Next action: build a consolidated 12-row manifest/recheck replacing the
    fallback topology1 A/AB-HVRT rows with the new detector-fixed SAC actors.

## 2026-07-28 - Consolidated 12-row detector-fixed SAC recheck

- Scope:
  - Rechecked the current 12 representative specialists with one switch-level
    validator and one manifest:
    `sac/experiments/stage6_recheck_manifest_current12_detectorfix_sac_20260728.csv`.
  - The recheck includes the newly promoted topology1 A-HVRT and AB-HVRT
    detector-fixed protected-SAC actors.
- Result:
  - Output directory:
    `lab/results/hpt_stage6_recheck_current12_detectorfix_sac_20260728`.
  - 8 / 12 rows passed the voltage-survival gate.
  - 8 / 12 rows both passed voltage survival and beat the conventional score
    under the unified validator.
  - The repaired topology1 A-HVRT and AB-HVRT rows reproduced successfully:
    A-HVRT `104.654` versus `107.784`; AB-HVRT `104.717` versus `109.170`.
- Remaining failures:
  - `t1_ab_lvrt`: recovery-envelope violation `0.0272 pu`, score
    `109.032` versus conventional `106.626`.
  - `t2_balanced_hvrt`: recovery-envelope violation `0.0148 pu`.
  - `t2_a_lvrt`: recovery-envelope violation `0.1872 pu`.
  - `t2_ab_lvrt`: recovery-envelope violation `0.0437 pu`.
- Interpretation:
  - The remaining failures are recovery-window timestep-envelope failures, not
    DC-link collapse or fault-window LV band failures.
  - Next action is recovery-aware trajectory repair and protected SAC
    fine-tune for the four failed representative rows.  SAC training runs must
    keep writing reward traces for convergence plots.

## 2026-07-28 - Topology1 AB-LVRT recovery repair and micro SAC

- Scope:
  - Repaired the failed `t1_ab_lvrt` representative row from the consolidated
    12-row recheck.
  - Failure mode before repair: recovery-envelope violation `0.0272 pu` and
    score `109.032` versus conventional `106.626`.
- Recovery-aware repair:
  - A CEM trajectory search was started but stopped after switch-level evidence
    showed that its return-to-zero trajectories worsened recovery overshoot.
  - A constant `[m_reg_d, m_reg_q, m_energy_d, m_energy_q] = [0.36, 0, 0, 0]`
    trajectory gave a stronger switch-level result: voltage-survival pass and
    score `104.459` versus conventional `106.626`.
- State-feedback actor:
  - Campaign:
    `hpt_stage6_repair_t1_ab_lvrt090_const036_actor_20260728`.
  - Best actor: DAgger1,
    `data/models/hpt_stage6_repair_t1_ab_lvrt090_const036_actor_20260728_dagger1.zip`.
  - Switch-level result: voltage-survival pass, score `104.868` versus
    conventional `106.626`, with envelope, recovery, and fault LV band
    violations all equal to zero.
- Protected SAC fine-tune:
  - Aggressive 300-step chunks failed by reintroducing recovery-envelope
    violation.
  - Micro protected SAC succeeded:
    `hpt_stage6_repair_t1_ab_lvrt090_const036_sacft_micro_20260728`.
  - All 6 SAC-updated chunks passed switch-level voltage survival and beat
    conventional with score `104.868` versus `106.626`.
  - Best SAC-updated model:
    `data/models/hpt_stage6_repair_t1_ab_lvrt090_const036_sacft_micro_20260728_chunk01.zip`.
  - SAC reward traces were written for each chunk under
    `lab/results/hpt_stage6_repair_t1_ab_lvrt090_const036_sacft_micro_20260728_chunk*_train/sac_training_reward_trace.csv`.
- Interpretation:
  - Counting this repaired row, the representative matrix has 9 / 12 rows with
    switch-level voltage-survival and beat-conventional evidence.
  - The remaining representative failures are `t2_balanced_hvrt`,
    `t2_a_lvrt`, and `t2_ab_lvrt`, all dominated by timestep recovery-envelope
    violations.

## 2026-07-28 - Topology2 recovery repair and 12-row SAC/conventional recheck

- Scope:
  - Continued the stage-6 representative matrix repair with the user-facing
    gate set to switch-level voltage-survival and beat-conventional evidence.
  - Full FRT certification remained out of scope for this pass; grid-current
    and reactive-current failures were preserved in the result table.
- Reward trace plumbing:
  - Added the reward trace summarizer:
    `sac/summaries/summarize_sac_reward_traces.py`.
  - Integrated it into protected SAC campaigns and offline SAC training so
    SAC runs now write:
    `sac_training_reward_trace_combined.csv`,
    `sac_reward_trace_summary.json`, and
    `sac_reward_and_switch_score_convergence.png`.
- Topology2 balanced HVRT repair:
  - Probe showed that using `hpt_chopper_threshold = 760 V` removed the
    recovery-envelope violation.
  - Protected SAC micro run:
    `hpt_stage6_t2_balanced_hvrt110_chop760_sacft_micro_20260728`.
  - Best SAC-updated model:
    `data/models/hpt_stage6_t2_balanced_hvrt110_chop760_sacft_micro_20260728_chunk01.zip`.
  - Switch-level result: voltage-survival pass, score `113.162` versus
    conventional `174.870`, with envelope, recovery, and fault-band violations
    all equal to zero.
- Topology2 A-LVRT repair:
  - Old warm-SAC reg-anchor actor was verified as pass/beat under the current
    validator.
  - A fresh protected SAC micro run was then executed:
    `hpt_stage6_t2_a_lvrt090_reganchor_sacft_micro_20260728`.
  - Best SAC-updated model:
    `data/models/hpt_stage6_t2_a_lvrt090_reganchor_sacft_micro_20260728_chunk02.zip`.
  - Switch-level result: voltage-survival pass, score `126.423` versus
    conventional `156.538`; max recovery-envelope violation was
    `0.000886 pu` and accepted by the validator.
- Topology2 AB-LVRT repair:
  - A fault/recovery trajectory with fault action `[0.80, 0, 0, 0]` and
    recovery action `[0.35, 0, 0, 0]` passed switch-level voltage-survival:
    score `133.747` versus conventional `160.931`.
  - State-feedback actor campaign:
    `hpt_stage6_t2_ab_lvrt090_faultrec080035_actor_20260728`.
  - DAgger1 actor passed and beat conventional with score `129.830`.
  - Protected SAC micro run:
    `hpt_stage6_t2_ab_lvrt090_faultrec080035_sacft_micro_20260728`.
  - Best SAC-updated model:
    `data/models/hpt_stage6_t2_ab_lvrt090_faultrec080035_sacft_micro_20260728_chunk04.zip`.
  - Switch-level result: voltage-survival pass, score `129.049` versus
    conventional `160.931`; SAC fine-tune improved the switch-level score over
    the DAgger1 starting actor by about `0.781`.
- Consolidated recheck:
  - Manifest:
    `sac/experiments/stage6_recheck_manifest_current12_repaired_sac_20260728.csv`.
  - Run:
    `hpt_stage6_recheck_current12_repaired_sac_20260728`.
  - Result CSV:
    `lab/results/hpt_stage6_recheck_current12_repaired_sac_20260728/accepted_specialist_validation.csv`.
  - Summary:
    12 / 12 voltage-survival pass,
    12 / 12 beat conventional,
    0 / 12 full FRT pass.
- Interpretation:
  - The requested representative voltage-survival matrix is now repaired:
    all 12 topology/fault-family specialists beat the conventional dq baseline
    under the same switch-level validator.
  - This is not a full FRT result.  Remaining certification work is explicitly
    the grid-current limit and reactive-current support layer, which was not
    targeted in this pass.

## 2026-07-28 - Stage 7 topology2 LVRT family-controller pilot

- Scope:
  - Started the move from single-case voltage-survival specialists toward a family-level controller.
  - Target family for this pass: `topology2_LVRT_family`, covering balanced, one-phase, and two-phase LVRT around 0.85/0.90/0.95 pu and 40/60/80/120 ms in the proxy curriculum.
  - Full FRT certification remains out of scope; the switch-level gate here is voltage-survival plus beat-conventional.
- Code/interface changes:
  - Added `topology2_lvrt_family_v1` and `topology2_lvrt_family_holdout_v1` curricula to `sac/offline/train_hpt_voltage_sac.py`.
  - Synchronized the same curricula into `sac/pretrain_hpt_actor_bc.py` so BC/DAgger-style warm starts can use the family scenario set.
  - Added plan document `docs/specs/algorithms/hpt-sac-controller/hpt-sac-controller-family-sac-generalization-plan-2026-07-28.md`.
- Seed generalization baseline:
  - Manifest: `sac/experiments/stage7_t2_lvrt_family_seed_manifest_20260728.csv`.
  - Run: `hpt_stage7_t2_lvrt_family_seed_recheck_20260728`.
  - Result: 5 / 9 voltage-survival pass and 5 / 9 beat conventional, 0 / 9 full FRT.
  - Interpretation: the single `topology2 AB-LVRT` seed has useful unbalanced transfer, but fails balanced LVRT by fault-band and recovery overboost.
- Raw family SAC pilot:
  - Trained from the AB-LVRT seed using `topology2_lvrt_family_v1` for 30k proxy steps:
    `hpt_stage7_t2_lvrt_family_sac_pilot_20260728_r2`.
  - Proxy training showed severe instability: critic loss stayed around `1e27`, actor loss grew to about `1e6`, and proxy Vdc minimum fell to about `0.424 pu`.
  - Switch-level spot gate was stopped after the first case because balanced 0.90/60 ms collapsed to `LV_mean ~= 76.6 V` and exceeded the action limit (`max|a| ~= 1.131`).
  - Interpretation: raw full-action SAC fine-tune is not a safe family-training mechanism yet.
- Execution-guard family BC warm start:
  - Run: `hpt_stage7_t2_lvrt_family_bc_guard_20260728`.
  - Switch-level recheck: `hpt_stage7_t2_lvrt_family_bc_guard_recheck_20260728`.
  - Result: 3 / 9 voltage-survival pass and 3 / 9 beat conventional.
  - Interpretation: execution-guard BC is stable but too conservative / not tuned enough for this family.
- Selector-teacher upper bound:
  - Manifest: `sac/experiments/stage7_t2_lvrt_family_selector_teacher_manifest_20260728.csv`.
  - Rule: balanced rows use the topology2 balanced LVRT seed, one-phase rows use the topology2 A-LVRT seed, and two-phase rows use the topology2 AB-LVRT seed.
  - Run: `hpt_stage7_t2_lvrt_family_selector_teacher_recheck_20260728`.
  - Result: 7 / 9 voltage-survival pass and 7 / 9 beat conventional, 0 / 9 full FRT.
  - Remaining failures are both balanced holdouts: 0.875 pu / 100 ms fails DC-link bounds; 0.925 pu / 100 ms fails DC-link plus small timestep fault/recovery envelope violations.
- Research decision:
  - Do not continue raw proxy SAC as the main path.
  - Next best path is to use the selector teacher to generate family trajectory/DAgger data, then train a single state-feedback actor to imitate the selector, followed by residual/protected SAC fine-tune with a much stronger support constraint.

## 2026-07-28 - Literature check for family SAC, DAgger, residual RL, and safe RL

- Scope:
  - Collected literature for the Stage-7 failure mode where direct full-action
    proxy SAC damaged switch-level voltage-survival, while a selector teacher
    made from validated single-case specialists was more reliable.
- Local reference folder:
  - `references/week8_family_sac/`
  - `references/week8_family_sac/README.md`
- Added strategy note:
  - `docs/specs/algorithms/hpt-sac-controller/hpt-sac-controller-family-sac-literature-strategy-2026-07-28.md`
- Main conclusion:
  - The next research path should not be raw family SAC on the proxy.
  - The literature supports a safer sequence:
    validated specialists -> selector-teacher trajectory data -> on-policy
    DAgger relabeling -> distilled split-head family actor -> bounded residual
    SAC fine-tune -> switch-level promotion.
- Reason:
  - Imitation/DAgger papers address distribution shift in trajectory control.
  - Multiple-expert DAgger and policy distillation match the current specialist
    matrix.
  - Residual RL and safe RL papers support keeping the feasible base policy and
    training only a constrained residual correction.

## 2026-07-28 - Direction correction: SAC remains the main research line

- User clarification:
  - DAgger should not become the main method.  The project goal remains a SAC
    controller.  BC/DAgger can be diagnostics, initialization, or ablations,
    but the paper claim must be SAC-centered.
- Added SAC-main literature set:
  - `references/week8_sac_main/`
  - `references/week8_sac_main/README.md`
- Added SAC-main debug plan:
  - `docs/specs/algorithms/hpt-sac-controller/hpt-sac-controller-sac-main-debug-plan-2026-07-28.md`
- Main diagnosis:
  - The Stage-7 raw family SAC failure is a SAC stability / constraint /
    proxy-exploitation problem: large negative returns, low Vdc, large
    behavior-anchor mismatch, and switch-level action-limit collapse.
- New research direction:
  - Keep SAC as the update mechanism.
  - Systematically test conservative/behavior-regularized SAC, constrained
    SAC with cost critics, uncertainty/model-bias penalties, REDQ-style critic
    ensembles, and switch-level promotion after each candidate chunk.
  - Treat support data as a SAC regularizer, not as the main controller method.

## 2026-07-28 - Chinese SAC-main literature synthesis and execution plan

- Added Chinese literature synthesis:
  - `references/week8_sac_main/literature_synthesis_zh.md`
- Added execution plan:
  - `docs/specs/algorithms/hpt-sac-controller/hpt-sac-main-research-execution-plan-2026-07-28.md`
- Plan summary:
  - Stage 0: freeze SAC as the main claim and mark BC/DAgger as initialization
    or ablation only.
  - Stage 1: instrument SAC failure with actor/critic/alpha/Q/action-support
    diagnostics.
  - Stage 2: separate reward from constraint costs.
  - Stage 3: implement BRAC-SAC / CQL-SAC action-support protection.
  - Stage 4: implement constrained SAC with envelope/Vdc/action cost critics.
  - Stage 5: add proxy-bias/uncertainty penalties.
  - Stage 6: expand only after switch-level spot promotion passes.

## 2026-07-28 - Stage 8 SAC-main implementation and topology2 proxy diagnosis

- Scope:
  - Implemented SAC-centered diagnostics and support regularization after the
    user clarified that DAgger/BC must not be the main research line.
  - Target pilot: `topology2_lvrt_family_v1`.
- Code changes:
  - Added `SupportRegularizedSAC` in
    `sac/offline/train_hpt_voltage_sac.py`.
  - The new actor loss is standard SAC actor loss plus optional BRAC-style
    support penalties inside each SAC update, not post-hoc BC repair.
  - Added multi-expert support anchors from switch-level manifests using
    `--sac-support-anchor-manifest`.
  - Added nearest-replay support regularization with
    `--sac-support-nearest-replay`.
  - Added SAC diagnostics for actor base loss, support loss, replay-support
    loss, and critic loss.
  - Added reward controls for `vdc_soft_reward_weight` and
    `vdc_bounds_reward_weight`.
- Validation:
  - `py -3 -m py_compile sac/offline/train_hpt_voltage_sac.py sac/hpt_voltage_sac_env.py`
  - `PYTHONPATH=src py -3 -m pytest tests/test_env_envelope_unification.py -q`
  - Result: 14 tests passed.
- Diagnostic runs:
  - Uncapped plain SAC kept critic loss near `1e27`, dominated by raw support
    distance.
  - Reward-capped support SAC reduced critic loss to about `1e6`.
  - Manifest multi-expert BRAC-SAC improved proxy return relative to the
    single-actor support baseline.
  - Reducing proxy-OOD reward weight and increasing Vdc reward weight improved
    the best proxy return to about `-1.92e4` after a 12k continuation run.
- Key finding:
  - The remaining Vdc-min failure is not only a SAC optimization issue.
  - In a direct proxy trace for topology2 balanced LVRT 0.90 pu / 60 ms, the
    switch-level validated selector-teacher actor also shows severe proxy Vdc
    collapse and discontinuous Vdc jumps.
  - Therefore the current topology2 dynamic Vdc proxy is a false-negative /
    misalignment source for energy-branch training.
- Artifacts:
  - `lab/results/hpt_stage8_sac_main_diagnostics_20260728/REPORT.md`
  - `lab/results/hpt_stage8_sac_main_diagnostics_20260728/sac_main_diagnostic_summary_20260728.csv`
  - `lab/results/hpt_stage8_sac_manifest_replaybrac_vdc1200_ood40_12k_20260728/per_scenario_proxy_eval.csv`
  - `lab/results/hpt_stage8_sac_manifest_replaybrac_vdc1200_ood40_12k_20260728/trace_compare_bal090_60ms_proxy.csv`
- Next action:
  - Do not keep blindly optimizing proxy Vdc.
  - Repair topology2 dynamic Vdc proxy with switch-level traces, or use the
    proxy only for LV/action-support pretraining and perform SAC promotion with
    switch-level spot gates.

## 2026-07-28 - Current12 specialist proxy-manifest alignment smoke

- Scope:
  - Added a lightweight proxy governance script for the accepted 12-specialist
    manifest:
    `sac/calibration/evaluate_hpt_manifest_proxy_alignment.py`.
  - The script rolls each accepted actor through the shared
    `HPTVoltageSACEnv` proxy and optionally joins the Stage-6 switch-level
    validation CSV.
- Validation:
  - `py -3 -m py_compile sac/calibration/evaluate_hpt_manifest_proxy_alignment.py`
  - Smoke run:
    `PYTHONPATH=src py -3 -m sac.calibration.evaluate_hpt_manifest_proxy_alignment --max-cases 3 --run-id hpt_proxy_manifest_alignment_smoke_20260728`
  - Current-12 run:
    `PYTHONPATH=src py -3 -m sac.calibration.evaluate_hpt_manifest_proxy_alignment --run-id hpt_proxy_manifest_alignment_current12_20260728`
- Result:
  - Switch-level voltage-survival pass: `12 / 12`.
  - Proxy voltage-survival pass: `2 / 12`.
  - Proxy/switch pass agreement: `2 / 12`.
  - The only proxy-pass cases were `t2_a_hvrt` and `t2_ab_hvrt`.
  - Most proxy false negatives were caused by proxy envelope/fault-band/recovery
    violations; topology2 LVRT/HVRT also exposed Vdc-low false negatives.
- Artifacts:
  - `lab/results/hpt_proxy_manifest_alignment_current12_20260728/REPORT.md`
  - `lab/results/hpt_proxy_manifest_alignment_current12_20260728/proxy_manifest_alignment.csv`
- Research decision:
  - The 12 specialists share one parameterized proxy interface, but they do not
    yet have equally trustworthy proxy counterparts.
  - Do not use the current proxy as the final SAC optimization authority for all
    12 specialists.
  - Next repair should separate proxy alignment layers: scenario timing/phase,
    actor command support, LV envelope dynamics, and topology2 Vdc/energy
    dynamics.

## 2026-07-28 - Topology2 LVRT family SAC-anchor pilot switch-level recheck

- Scope:
  - Started from one fault family as requested: `topology2` / `LVRT`.
  - Trained a SAC-main candidate with BRAC-style support regularization inside
    the SAC actor update, using the switch-level selector manifest as the
    support set.
- Training command family:
  - `PYTHONPATH=src py -3 -m sac.offline.train_hpt_voltage_sac`
  - `--curriculum topology2_lvrt_family_v1`
  - `--steps 12000`
  - `--sac-support-anchor-manifest sac/experiments/stage7_t2_lvrt_family_selector_teacher_manifest_20260728.csv`
  - `--sac-support-nearest-replay`
- Training artifact:
  - `data/models/hpt_stage8_t2_lvrt_family_sac_anchor_pilot_20260728.zip`
  - `lab/results/hpt_stage8_t2_lvrt_family_sac_anchor_pilot_20260728/`
- Proxy-side result:
  - Reward trace rows: `112`.
  - Diagnostics rows: `2976`.
  - Proxy mean return: about `-2795.69`.
  - Proxy min Vdc pu: about `0.878`.
- Switch-level recheck:
  - Manifest:
    `sac/experiments/stage8_t2_lvrt_family_sac_anchor_pilot_manifest_20260728.csv`
  - Result directory:
    `lab/results/hpt_stage8_t2_lvrt_family_sac_anchor_pilot_recheck_20260728/`
  - Voltage-survival pass: `0 / 9`.
  - Beat conventional: `0 / 9`.
  - Full FRT pass: `0 / 9`.
- Comparison against existing topology2 LVRT family evidence:
  - Selector-teacher upper bound: `7 / 9` voltage-survival and `7 / 9` beat
    conventional.
  - BC guard: `3 / 9` voltage-survival and `3 / 9` beat conventional.
  - This SAC-anchor pilot: `0 / 9`.
- Diagnosis:
  - The candidate improved proxy metrics but failed switch-level promotion.
  - The dominant switch-level failures were `dc_link_bounds`,
    `timestep_recovery_envelope`, and sometimes `timestep_fault_lv_band` /
    `timestep_voltage_envelope`.
  - This is evidence that proxy-side Vdc/recovery optimization is still not
    aligned enough for topology2 LVRT family SAC.
- Next action:
  - Do not expand this actor.
  - Retry the same fault family with a feasible seed initialization, lower
    actor learning rate, stronger energy-branch support, lower exploration, and
    switch-level chunk promotion before full 9-case validation.

## 2026-07-28 - Start formal topology1 balanced LVRT fault-family workflow

- Scope:
  - Started the first formal 12-family workflow using
    `topology1 / LVRT / balanced` as the template family.
  - This family is centered on `0.90 pu / 60 ms` and is separated from
    single-phase and two-phase unbalanced LVRT families.
- New manifests:
  - Full 19-case family matrix:
    `sac/experiments/family_t1_lvrt_balanced_matrix_20260728.csv`
  - 3-case switch-level smoke matrix:
    `sac/experiments/family_t1_lvrt_balanced_smoke_20260728.csv`
- Matrix definition:
  - Train: `0.85 / 0.90 / 0.95 pu x 40 / 60 / 80 ms` = 9 cases.
  - Validation: `0.875 / 0.925 pu x 100 / 120 ms` = 4 cases.
  - Holdout: `0.825 / 0.875 / 0.925 pu x 120 / 160 ms` = 6 cases.
- Smoke run:
  - Command:
    `PYTHONPATH=src py -3 -m sac.validate_hpt_accepted_specialists --manifest sac/experiments/family_t1_lvrt_balanced_smoke_20260728.csv --run-id hpt_family_t1_lvrt_balanced_seed_smoke_20260728 --timeout-s 900`
  - Result directory:
    `lab/results/hpt_family_t1_lvrt_balanced_seed_smoke_20260728/`
  - Voltage-survival pass: `2 / 3`.
  - Beat conventional: `2 / 3`.
  - Full FRT pass: `0 / 3`.
- Key finding:
  - The center case `0.90 pu / 60 ms` passes voltage survival and beats
    conventional.
  - The mild validation case `0.925 pu / 100 ms` also passes and beats
    conventional.
  - The harder train-edge case `0.85 pu / 80 ms` fails due to
    `timestep_recovery_envelope`, with recovery violation about `0.00186 pu`.
- Research decision:
  - The first SAC target for this family should be recovery-envelope reduction
    around `0.85 pu / 80 ms`, while preserving center-case and validation-case
    pass status.
  - Next run the full 19-case seed matrix to measure the baseline family
    boundary before collecting family proxy/SAC data.

## 2026-07-28 - Topology1 balanced LVRT family seed full baseline

- Scope:
  - Completed the full 19-case switch-level seed baseline for the first formal
    fault family: `topology1 / LVRT / balanced`, centered at
    `0.90 pu / 60 ms`.
- Command:
  - `PYTHONPATH=src py -3 -m sac.validate_hpt_accepted_specialists --manifest sac/experiments/family_t1_lvrt_balanced_matrix_20260728.csv --run-id hpt_family_t1_lvrt_balanced_seed_full_20260728 --timeout-s 900`
- Result directory:
  - `lab/results/hpt_family_t1_lvrt_balanced_seed_full_20260728/`
- Summary:
  - Overall voltage-survival pass: `13 / 19`.
  - Overall beat-conventional: `13 / 19`.
  - Full FRT pass: `0 / 19`.
  - Train split: `5 / 9` voltage-survival pass.
  - Validation split: `4 / 4` voltage-survival pass.
  - Holdout split: `4 / 6` voltage-survival pass.
- Failed voltage-survival cases:
  - `0.85 pu / 80 ms`: failed `timestep_recovery_envelope`, with
    recovery violation about `0.001862 pu`.
  - `0.95 pu / 40 ms`, `0.95 pu / 60 ms`, `0.95 pu / 80 ms`: failed
    `timestep_voltage_envelope`, with envelope violation about `0.017644 pu`.
  - `0.825 pu / 160 ms`: failed `timestep_fault_lv_band`, with fault-band
    violation about `0.002424 pu`.
  - `0.925 pu / 160 ms`: failed `timestep_voltage_envelope`, with envelope
    violation about `0.020829 pu`.
- Interpretation:
  - The seed actor is a useful family prior, not merely a single center-case
    policy.
  - It generalizes over the validation matrix and part of the holdout matrix,
    but it overcompensates shallow LVRT cases and has long-duration edge
    failures.
- Evidence report:
  - `lab/results/hpt_family_t1_lvrt_balanced_seed_full_20260728/FAMILY_FULL_BASELINE_REPORT.md`
- Next action:
  - Train a topology1 balanced LVRT family SAC with the seed actor as a
    warm-start.
  - Prioritize reducing recovery overboost around `0.85 pu / 80 ms` and
    shallow-fault overcompensation around `0.95 pu / 40-80 ms`, while preserving
    the `4 / 4` validation pass result.

## 2026-07-29 - Topology1 balanced LVRT family SAC pilot and boundary probe

- Scope:
  - Added `topology1_lvrt_balanced_family_v1` and
    `topology1_lvrt_balanced_family_holdout_v1` curricula to
    `sac/offline/train_hpt_voltage_sac.py`.
  - Built a pass-only support manifest from the 13 seed-pass family rows:
    `sac/experiments/family_t1_lvrt_balanced_pass_support_20260728.csv`.
- Validation:
  - `py -3 -m py_compile sac/offline/train_hpt_voltage_sac.py`
    passed.
  - `py -3 -m sac.offline.train_hpt_voltage_sac --help` listed the
    new topology1 balanced LVRT family curricula.
- SAC pilot 1:
  - Run id: `hpt_t1_lvrt_bal_family_sac_pilot_rq08_20260728`.
  - Init actor: `data/models/hpt_t1_l090_pre24_b60_down35_clk_dg3_dagger2.zip`.
  - Steps: `4000`, learning rate `3e-5`, support weight `15`.
  - Initial run without `--reg-q-limit 0.8` failed before training because the
    seed actor uses a wider `m_reg_q` action space than the default current
    training config.  The rerun used `--reg-q-limit 0.8`.
  - Proxy mean return was about `-156116.59`, with large support violations.
  - Switch-level smoke:
    `lab/results/hpt_t1_lvrt_bal_family_sac_pilot_smoke_20260728/`.
  - Voltage-survival pass: `0 / 3`; beat conventional: `0 / 3`.
  - Decision: reject.  The actor left the switch-supported region and destroyed
    center-case feasibility.
- SAC pilot 2:
  - Run id: `hpt_t1_lvrt_bal_family_sac_guarded_pilot_20260728`.
  - Steps: `800`, learning rate `3e-6`, support weight `120`, behavior-anchor
    epochs every 200 SAC steps.
  - Switch-level smoke:
    `lab/results/hpt_t1_lvrt_bal_family_sac_guarded_pilot_smoke_20260728/`.
  - Voltage-survival pass: `1 / 3`; beat conventional: `1 / 3`.
  - The center `0.90 pu / 60 ms` case was preserved, but `0.85 pu / 80 ms`
    recovery violation and `0.95 pu / 60 ms` envelope violation were slightly
    worse than the seed actor.
  - Decision: reject as a promoted actor.  It is safer than pilot 1 but still
    does not improve the family boundary.
- Trajectory probes:
  - Broad probe:
    `hpt_t1_lvrt_bal_0850_080ms_recovery_probe_20260728`, `12` candidates,
    `0 / 12` voltage-survival pass.  This probe was not conclusive because
    `--max-cases 12` sampled only the low `fault_reg_d=0.39` region.
  - Seed-local probe:
    `hpt_t1_lvrt_bal_0850_080ms_seedlocal_probe_20260729`, `9` candidates.
  - Seed-local result: `6 / 9` voltage-survival pass and `6 / 9`
    beat-conventional.
  - Best passing direction:
    `fault_reg_d=0.43`, `recovery_reg_d=0.19`,
    `fault_energy_d=-0.01`, `recovery_energy_d=0.0`,
    with recovery violation about `0.000246 pu`.
  - Another passing direction with zero recovery violation:
    `fault_reg_d=0.42`, `recovery_reg_d=0.20`,
    `fault_energy_d=-0.01`, `recovery_energy_d=0.0`.
- Interpretation:
  - The `0.85 pu / 80 ms` boundary is physically controllable in switch-level
    validation.
  - Current proxy SAC fails because it changes the actor globally rather than
    learning a local recovery-stage adjustment.
  - The next SAC attempt should build a boundary teacher dataset from the
    seed-pass rows plus the seed-local passing trajectory candidates, then use
    this data as support for chunked SAC fine-tuning with switch-level
    promotion after each chunk.
- Evidence report:
  - `lab/results/hpt_family_t1_lvrt_balanced_seed_full_20260728/FAMILY_SAC_PILOT_AND_TRAJECTORY_PROBE_REPORT.md`

## 2026-07-29 - Topology1 balanced LVRT family support-dataset SAC pilot

- Scope:
  - Continued the first formal fault-family SAC experiment for
    `topology1 / LVRT / balanced`, centered at `0.90 pu / 60 ms`.
  - Added direct `.npz` support-anchor loading to
    `sac/offline/train_hpt_voltage_sac.py` through
    `--sac-support-anchor-dataset`.
  - Added `sac/datasets/build_hpt_family_support_dataset.py`.
- Support dataset:
  - Output:
    `lab/results/hpt_t1_lvrt_bal_family_support_dataset_20260729/support_anchors.npz`.
  - Sources:
    `sac/experiments/family_t1_lvrt_balanced_pass_support_20260728.csv`
    and
    `lab/results/hpt_t1_lvrt_bal_0850_080ms_seedlocal_probe_20260729/sweep_results.csv`.
  - Anchor count: `2817` total, including `1959` seed actor anchors and `858`
    trajectory anchors from `6` switch-level passing recovery trajectories.
- Training:
  - Run id: `hpt_t1_lvrt_bal_family_sac_supportdataset_pilot_20260729`.
  - Init actor:
    `data/models/hpt_t1_l090_pre24_b60_down35_clk_dg3_dagger2.zip`.
  - Model:
    `data/models/hpt_t1_lvrt_bal_family_sac_supportdataset_pilot_20260729.zip`.
  - SAC settings: `1200` steps, learning rate `1e-6`, support weight `220`,
    nearest-replay support regularization, no post-chunk behavior-anchor BC.
  - Reward trace:
    `lab/results/hpt_t1_lvrt_bal_family_sac_supportdataset_pilot_20260729/sac_training_reward_trace.csv`.
- Switch-level smoke:
  - Run directory:
    `lab/results/hpt_t1_lvrt_bal_family_sac_supportdataset_pilot_smoke_20260729/`.
  - Voltage-survival pass: `2 / 3`.
  - Beat conventional: `2 / 3`.
  - The target boundary case `0.85 pu / 80 ms` passed, improving over both the
    seed actor and the previous guarded SAC pilot.
- Full 19-case family gate:
  - Run directory:
    `lab/results/hpt_t1_lvrt_bal_family_sac_supportdataset_full_20260729/`.
  - Voltage-survival pass: `11 / 19`.
  - Beat conventional: `11 / 19`.
  - Full FRT pass: `0 / 19`.
  - Comparison against seed baseline:
    `lab/results/hpt_t1_lvrt_bal_family_sac_supportdataset_full_20260729/seed_vs_supportdataset_sac_summary.json`.
- Interpretation:
  - The new trajectory-support mechanism is useful locally: it repaired
    `train_0850_080ms`, reducing recovery violation from about `0.001862 pu`
    to about `0.000954 pu` and passing the voltage-survival gate.
  - It is not yet a promoted family specialist because the full matrix regressed
    from the seed actor's `13 / 19` to `11 / 19`.
  - Regressions appeared in shallow LVRT cases around `0.925 pu`, indicating
    global support regularization lets the deep-fault recovery correction bleed
    into shallow-fault overboost regions.
- Next action:
  - Keep the support-dataset path and reward traces.
  - Do not promote
    `data/models/hpt_t1_lvrt_bal_family_sac_supportdataset_pilot_20260729.zip`.
  - Add depth-aware/state-conditional support or split the family support into
    deep, center, and shallow LVRT regions before another full matrix attempt.

## 2026-07-29 - Topology1 balanced LVRT shallow probes and depth-aware support attempt

- Scope:
  - Followed up the `11 / 19` support-dataset SAC regression by probing shallow
    LVRT anti-overboost behavior for `topology1 / balanced LVRT / 0.95 pu /
    60 ms`.
- Shallow trajectory probes:
  - `hpt_t1_lvrt_bal_0950_060ms_shallow_probe_20260729`
  - `hpt_t1_lvrt_bal_0950_060ms_shallow_seedlocal_probe_20260729`
  - `hpt_t1_lvrt_bal_0950_060ms_shallow_preact_probe_20260729`
  - `hpt_t1_lvrt_bal_0950_060ms_shallow_fine_probe_20260729`
- Probe result:
  - No strict voltage-survival passing trajectory was found for `0.95 pu /
    60 ms`.
  - Best near-pass reduced envelope violation from the seed actor's about
    `0.01764 pu` to about `0.01015 pu`, but still failed
    `timestep_voltage_envelope`.
  - Adding `pre_reg_d` was important; without it, the fault-onset minimum
    voltage was too low.
- Depth-aware support dataset:
  - Generated:
    `sac/experiments/family_t1_lvrt_balanced_depthaware_pass_support_20260729.csv`.
  - Generated:
    `lab/results/hpt_t1_lvrt_bal_family_depthaware_support_dataset_20260729/support_anchors.npz`.
  - Anchor count: `4733` total, including `3875` seed actor anchors and `858`
    deep strict trajectory anchors.
- Training:
  - Run id: `hpt_t1_lvrt_bal_family_sac_depthaware_pilot_20260729`.
  - Model:
    `data/models/hpt_t1_lvrt_bal_family_sac_depthaware_pilot_20260729.zip`.
  - Settings: `900` SAC steps, learning rate `5e-7`, support weight `260`,
    nearest-replay support, no post-chunk BC.
- Switch-level smoke:
  - Run directory:
    `lab/results/hpt_t1_lvrt_bal_family_sac_depthaware_pilot_smoke_20260729/`.
  - Voltage-survival pass: `1 / 3`.
  - It preserved `0.90 pu / 60 ms` but failed `0.85 pu / 80 ms` and
    `0.95 pu / 60 ms`.
- Interpretation:
  - Simple dataset reweighting is not enough.
  - The single actor still receives incompatible local objectives: deep LVRT
    needs a recovery-stage correction while shallow LVRT needs anti-overboost
    behavior.
  - Do not promote the depth-aware actor.
- Evidence report:
  - `lab/results/hpt_t1_lvrt_bal_family_sac_depthaware_pilot_smoke_20260729/DEPTHAWARE_SUPPORT_SAC_REPORT.md`
- Next action:
  - Implement explicit state-conditional control or a depth selector:
    use the deep correction only when `grid_pu <= 0.875`, preserve the seed or
    shallow-local behavior for `grid_pu >= 0.925`, and validate on the same
    19-case switch-level family matrix.

## 2026-07-29 - Topology1 balanced LVRT depth-selector family gate

- Scope:
  - Tested a diagnostic case-level selector for the first formal family:
    `topology1 / balanced LVRT`, centered at `0.90 pu / 60 ms`.
  - Manifest:
    `sac/experiments/family_t1_lvrt_balanced_depth_selector_full_20260729.csv`.
  - Rule:
    use the support-dataset SAC actor for `fault_pu <= 0.875` and
    `duration_s >= 0.080`; otherwise use the seed actor.
- Switch-level full-family gate:
  - Run directory:
    `lab/results/hpt_t1_lvrt_bal_family_depth_selector_full_20260729/`.
  - Voltage-survival pass: `14 / 19`.
  - Beat conventional: `14 / 19`.
  - Full FRT pass: `0 / 19`.
- Comparison:
  - Seed actor baseline: `13 / 19` voltage-survival pass.
  - Single support-dataset SAC actor: `11 / 19` voltage-survival pass.
  - Depth selector recovered `train_0850_080ms` without losing seed-passing
    cases.
- Remaining failures:
  - Shallow LVRT: `0.95 pu / 40, 60, 80 ms` still fails timestep voltage
    envelope by about `0.017644 pu`.
  - Deep-long LVRT: `0.825 pu / 160 ms` still fails fault LV band by about
    `0.012150 pu`.
  - Long shallow LVRT: `0.925 pu / 160 ms` still fails envelope by about
    `0.020829 pu`.
- Interpretation:
  - The result supports state-conditional control: deep recovery correction is
    useful locally but should not be forced globally.
  - This is not yet a final single SAC family specialist because the current
    evidence uses a case-level actor selector.
- Evidence report:
  - `lab/results/hpt_t1_lvrt_bal_family_depth_selector_full_20260729/FAMILY_DEPTH_SELECTOR_COMPARISON_REPORT.md`
- Next action:
  - Convert the selector idea into a runtime state-conditional controller or a
    feature-conditioned family actor, with separate treatment of deep-long
    LVRT under-support and shallow-LVRT overboost.

## 2026-07-29 - Topology1 balanced LVRT runtime selector validation

- Scope:
  - Converted the previous manifest-level depth selector into an online
    Simulink controller mode.
  - Added evaluator mode `sac_actor_depth_selector_raw` and controller
    `actor_select_mode = 4.0`.
  - Extended `validate_hpt_accepted_specialists.py` with optional
    `comparison_mode`, `base_model_path`, and `dynamic_model_path` manifest
    fields.
- Runtime selector logic:
  - Base actor:
    `data/models/hpt_t1_l090_pre24_b60_down35_clk_dg3_dagger2.zip`.
  - Dynamic/deep actor:
    `data/models/hpt_t1_lvrt_bal_family_sac_supportdataset_pilot_20260729.zip`.
  - Dynamic actor is selected online for topology1 deep LVRT when `g_vpos` or
    remembered `v_fault_min` is below `0.885` during fault/recovery.
- Smoke:
  - Manifest:
    `sac/experiments/family_t1_lvrt_balanced_runtime_selector_smoke_20260729.csv`.
  - Run directory:
    `lab/results/hpt_t1_lvrt_bal_family_runtime_selector_smoke_20260729/`.
  - Voltage-survival pass: `2 / 3`.
  - The smoke reproduced the expected pattern: `0.85 pu / 80 ms` and
    `0.90 pu / 60 ms` passed; `0.95 pu / 60 ms` still failed shallow
    envelope overboost.
- Full 19-case family gate:
  - Manifest:
    `sac/experiments/family_t1_lvrt_balanced_runtime_selector_full_20260729.csv`.
  - Run directory:
    `lab/results/hpt_t1_lvrt_bal_family_runtime_selector_full_20260729/`.
  - Voltage-survival pass: `14 / 19`.
  - Beat conventional: `14 / 19`.
  - Full FRT pass: `0 / 19`.
- Comparison:
  - Seed actor: `13 / 19`.
  - Single support-dataset SAC actor: `11 / 19`.
  - Manifest-level selector: `14 / 19`.
  - Runtime selector: `14 / 19`.
  - Runtime selector recovered `train_0850_080ms` without regressing
    seed-passing cases.
- Interpretation:
  - This is stronger than the previous case-level selector because the actor
    choice now occurs inside the Simulink controller at runtime.
  - It is still a two-actor selector, not a final single-network family SAC
    specialist.
- Evidence report:
  - `lab/results/hpt_t1_lvrt_bal_family_runtime_selector_full_20260729/FAMILY_RUNTIME_SELECTOR_REPORT.md`
- Next action:
  - Train or fit a single feature-conditioned family actor that internalizes
    the selector behavior and adds shallow-LVRT overboost suppression.

## 2026-07-29 - Topology1 balanced LVRT runtime-selector trace distillation smoke

- Scope:
  - Continued the first formal fault-family track:
    `topology1 / balanced LVRT`, centered at `0.90 pu / 60 ms`.
  - Added a reusable trace orchestration entry point:
    `sac/datasets/collect_hpt_family_actor_traces.py`.
  - The script exports base/dynamic actors, runs
    `simulink/collectors/collect_hpt_v2_trajectory_trace.m` for
    selected manifest rows, and aggregates the resulting per-step CSV traces.
- Trace collection:
  - Run id:
    `hpt_t1_lvrt_bal_rtselector_trace_smoke_20260729`.
  - Aggregate trace:
    `lab/results/hpt_trace_aggregates/hpt_t1_lvrt_bal_rtselector_trace_smoke_20260729/aggregate_trace.csv`.
  - Cases:
    `0.85 pu / 80 ms`, `0.90 pu / 60 ms`, and `0.925 pu / 120 ms`.
  - Samples: `439` per-2-ms switch-level rows, with `obs_01..obs_24` and
    `actor_action_01..actor_action_04` verified.
- Single-network distillation attempts:
  - Standard BC distillation:
    `data/models/hpt_t1_lvrt_bal_family_rtselector_distill_smoke_20260729.zip`.
    Switch-level smoke result: `1 / 4` voltage-survival pass.
  - Stricter BC distillation:
    `data/models/hpt_t1_lvrt_bal_family_rtselector_distill_strict_smoke_20260729.zip`.
    Switch-level smoke result: `1 / 4` voltage-survival pass.
- Comparison:
  - The runtime selector passes the same smoke pass-candidate points, while
    both single-network BC distillations fail the deep/center cases through
    recovery-stage voltage violations.
  - Stricter supervised fitting reduced action MSE to about `1e-8` on `m_reg_d`
    but did not improve switch-level survival, confirming that low open-loop
    imitation loss is insufficient for this family.
- Evidence:
  - `lab/results/hpt_t1_lvrt_bal_family_rtselector_distill_strict_smoke_20260729/DISTILLATION_SMOKE_COMPARISON.md`.
- Interpretation:
  - The result is a useful negative control.  Static trace imitation alone
    cannot replace the runtime selector because small closed-loop action errors
    shift the recovery trajectory outside the timestep envelope.
  - The next attempt should use closed-loop DAgger or trajectory-aware SAC
    fine-tuning with switch-level promotion, instead of adding more static BC
    epochs on the same trace.
- Aborted follow-up:
  - A noise-augmented BC run
    `hpt_t1_lvrt_bal_rtselector_distill_noisy_smoke_20260729` was started with
    `bc_obs_noise_repeat = 8`, but the expanded dataset made the quick smoke
    too slow for this iteration.  The process was stopped before producing a
    checkpoint and is not counted as evidence.

## 2026-07-29 - Topology1 balanced LVRT DAgger relabel negative control

- Scope:
  - Continued the first formal fault family:
    `topology1 / balanced LVRT`, centered at `0.90 pu / 60 ms`.
  - Collected closed-loop switch-level visited states from the failed strict
    single-network distillation actor.
  - Relabeled those visited states with the current runtime-selector teacher
    so the dataset contains the selector action at states actually induced by
    the failed actor.
- New tooling:
  - Added `sac/datasets/relabel_hpt_trace_with_runtime_selector.py`.
  - The relabeler reads `obs_01..obs_24`, loads the base and deep SAC actors,
    applies the same `g_vpos` / remembered `v_fault_min` selector threshold
    used by the Simulink runtime selector, and writes relabeled
    `actor_action_01..actor_action_04` targets while preserving the original
    actions.
- Data:
  - Failed-actor visited trace:
    `lab/results/hpt_trace_aggregates/hpt_t1_lvrt_bal_strictdistill_visited_trace_20260729/aggregate_trace.csv`.
  - Relabeled trace:
    `lab/results/hpt_trace_relabels/hpt_t1_lvrt_bal_strictdistill_visited_relabel_20260729/runtime_selector_relabel_trace.csv`.
  - Combined trace:
    `lab/results/hpt_trace_aggregates/hpt_t1_lvrt_bal_rtselector_plus_dagger_relabel_20260729/aggregate_trace.csv`.
  - Relabel split: `508` deep-actor rows and `64` base-actor rows.
- DAgger relabel BC actor:
  - Model:
    `data/models/hpt_t1_lvrt_bal_family_dagger_relabel_bc_smoke_20260729.zip`.
  - Training run:
    `hpt_t1_lvrt_bal_dagger_relabel_bc_smoke_20260729`.
  - Final BC loss was about `0.0124`; the discontinuous base/deep selector
    labels were much harder to fit than the static runtime-selector trace.
- Switch-level smoke:
  - Manifest:
    `sac/experiments/family_t1_lvrt_balanced_dagger_relabel_smoke_20260729.csv`.
  - Run directory:
    `lab/results/hpt_t1_lvrt_bal_family_dagger_relabel_smoke_20260729/`.
  - Voltage-survival pass: `0 / 4`.
  - Beat conventional: `0 / 4`.
  - Full FRT pass: `0 / 4`.
- Failure mode:
  - `0.85 pu / 80 ms` and `0.90 pu / 60 ms` failed recovery envelope.
  - `0.95 pu / 60 ms` and `0.925 pu / 120 ms` failed voltage envelope and
    recovery envelope.
- Interpretation:
  - Simple DAgger-style relabeling does not solve the single-network family
    problem for this case.
  - The likely cause is that the hard runtime selector creates discontinuous
    action labels near the branch boundary; a smooth MLP actor interpolates
    between base and deep behavior and creates unsafe recovery trajectories.
  - This actor is diagnostic only and must not be promoted.
- Next action:
  - Keep the runtime selector as the current strongest family controller, then
    either add an explicit multi-branch/selector architecture or target the
    remaining failure subregions directly: shallow `0.95 pu` overboost,
    deep-long `0.825 pu / 160 ms` under-support, and long-shallow
    `0.925 pu / 160 ms` envelope violation.

## 2026-07-29 - Topology1 balanced LVRT shallow trajectory probe

- Scope:
  - Focused on the runtime-selector failure subregion for the first formal
    family: `topology1 / balanced LVRT`, shallow `0.95 pu` sag.
  - The runtime selector fails `0.95 pu / 40, 60, 80 ms` by timestep voltage
    envelope only, while fault LV band, recovery envelope, and DC-link
    survival are otherwise close.
- First low-action sweep:
  - Run id: `hpt_t1_lvrt_bal_shallow095_traj_probe_20260729`.
  - Matrix: `fault m_reg_d = {0, 0.04, 0.08, 0.12}`,
    `recovery m_reg_d = {0, 0.02, 0.04}` at `0.95 pu / 60 ms`.
  - Result: `0 / 12` voltage-survival pass.
  - Interpretation: the action range was under-supporting the LV voltage and
    produced large fault/recovery violations, so the shallow failure is not
    solved by simply reducing the action toward zero.
- Near-actor sweep:
  - Run id: `hpt_t1_lvrt_bal_shallow095_traj_probe2_20260729`.
  - Matrix: `fault m_reg_d = {0.28, 0.30, 0.32, 0.34}`,
    `recovery m_reg_d = {0.16, 0.20, 0.24}` at `0.95 pu / 60 ms`.
  - Result: `0 / 12` voltage-survival pass, but the best candidate
    `fault=0.34`, `recovery=0.24` reduced the maximum envelope violation to
    about `0.0162 pu` with fault band and recovery passing.
- Final narrow probe:
  - Run id: `hpt_t1_lvrt_bal_shallow095_traj_probe3_20260729`.
  - Matrix: `fault m_reg_d = {0.36, 0.38}`,
    `recovery m_reg_d = {0.26, 0.28, 0.30}` at `0.95 pu / 60 ms`.
  - Result: `2 / 6` voltage-survival pass and beat conventional.
  - Best candidate:
    `fault m_reg_d = 0.38`, `recovery m_reg_d = 0.28`.
  - Metrics for the best candidate:
    LV fault mean about `207.11 V`, LV recovery mean about `206.42 V`,
    `fault_lv_band_violation_max_pu = 0`,
    `envelope_violation_max_pu = 0`,
    `recovery_violation_max_pu = 0`.
- Duration spot checks using `fault=0.38`, `recovery=0.28`:
  - `0.95 pu / 40 ms`:
    run id `hpt_t1_lvrt_bal_shallow095_040ms_besttraj_20260729`;
    result still fails by a small timestep envelope violation of about
    `0.0030 pu`.
  - `0.95 pu / 80 ms`:
    run id `hpt_t1_lvrt_bal_shallow095_080ms_besttraj_20260729`;
    result passes voltage-survival and beats conventional.
- Interpretation:
  - The shallow `0.95 pu` subregion is not infeasible at switch level.
  - A simple fault/recovery trajectory can repair `60 ms` and `80 ms`; the
    `40 ms` case needs a slightly different short-fault timing or clearing
    action.
  - This is trajectory evidence, not yet a trained SAC family actor.  The next
    controller step should turn this trajectory into a state-feedback shallow
    branch or include these rows in a family SAC support dataset with an
    explicit shallow-depth feature.
- Next action:
  - Add a shallow-support branch or support dataset for `0.95 pu` LVRT,
    re-run the 19-case family gate, and check whether the family improves
    beyond the current runtime selector baseline of `14 / 19`.

## 2026-07-29 - Topology1 balanced LVRT support-SAC family negative controls

- Scope:
  - Continued the first formal fault family:
    `topology1 / balanced LVRT`, centered at `0.90 pu / 60 ms`.
  - Goal was to turn the switch-level passing deep/shallow trajectory evidence
    into one state-feedback SAC actor for the family, rather than relying on a
    hand-written runtime selector.
- Support dataset tooling:
  - Updated
    `sac/datasets/build_hpt_family_support_dataset.py` so multiple
    trajectory sweep CSVs can be mixed in one support dataset and per-sweep
    `summary.json` metadata is used to infer fault depth/duration.
  - Added support for `--seed-episodes-per-row 0`, enabling trajectory-only
    support datasets without center-seed actor samples.
- First support-SAC attempt:
  - Dataset:
    `lab/results/hpt_t1_lvrt_bal_family_shallowdeep_support_dataset_20260729/support_anchors.npz`.
  - Samples: `4493` total, including `1959` seed-actor anchors and `2534`
    switch-level passing trajectory anchors.
  - Actor:
    `data/models/hpt_t1_lvrt_bal_family_sac_shallowdeep_support_pilot_20260729.zip`.
  - Training:
    `1000` SAC steps from
    `data/models/hpt_t1_l090_pre24_b60_down35_clk_dg3_dagger2.zip`, with
    BRAC-style in-update support penalty.
  - Switch-level smoke:
    `lab/results/hpt_t1_lvrt_bal_family_shallowdeep_sac_smoke_20260729/`.
  - Result: `1 / 5` voltage-survival pass and `1 / 5` beat conventional.
  - Passed only the center guard point `0.90 pu / 60 ms`.
  - Failure modes:
    - `0.85 pu / 80 ms`: small recovery envelope violation
      (`recovery_violation_max_pu = 0.002196`).
    - `0.95 pu / 40/60/80 ms`: timestep voltage envelope violation
      (`envelope_violation_max_pu = 0.02159`).
- Second support-SAC attempt:
  - Dataset:
    `lab/results/hpt_t1_lvrt_bal_family_trajectoryonly_support_dataset_20260729/support_anchors.npz`.
  - Samples: `10136` total, all from switch-level passing trajectories:
    deep `0.85 pu / 80 ms` and shallow `0.95 pu / 60, 80 ms`.
  - Actor:
    `data/models/hpt_t1_lvrt_bal_family_sac_trajectoryonly_support_pilot_20260729.zip`.
  - Training:
    `600` SAC steps from the first support-SAC actor, learning rate `1e-7`,
    support penalty `1000`, and heavier `m_reg_d` support weight.
  - Switch-level smoke:
    `lab/results/hpt_t1_lvrt_bal_family_trajectoryonly_sac_smoke_20260729/`.
  - Result: `1 / 5` voltage-survival pass and `1 / 5` beat conventional.
  - The same center point passed, while deep/shallow boundary cases remained
    just outside the timestep envelope.
  - The shallow envelope violation improved only from `0.02159 pu` to
    `0.01946 pu`; the deep recovery violation improved only from `0.002196 pu`
    to `0.001650 pu`.
- Interpretation:
  - This is a useful negative result.  The current single smooth SAC actor is
    averaging between deep-fault and shallow-fault trajectory requirements:
    for `0.95 pu / 60 ms`, the switch-passing trajectory needs approximately
    `m_reg_d = 0.38` during the fault and `0.28` during recovery, while the
    support-SAC actor produced about `0.36` during the fault.
  - Increasing support weight and removing center-seed anchors did not fix the
    family generalization gap, so blind SAC fine-tuning is not the next best
    path for this family.
- Next action:
  - Move to an explicit family controller architecture:
    either a learned selector/gating head plus branch actors, or a split
    trajectory/state-feedback actor with a depth/duration-aware head.  Keep the
    existing runtime selector as the strongest current switch-level baseline
    for this family (`14 / 19` voltage-survival pass), and treat both
    support-SAC actors above as diagnostic negative controls rather than
    accepted specialists.

## 2026-07-29 - 12-specialist fault/gate standard audit

- Created:
  `docs/specs/algorithms/hpt-sac-controller/hpt-sac-controller-12-specialist-fault-standard-2026-07-29.md`.
- Scope:
  - This was a documentation/audit step only; no Simulink model, actor, proxy,
    or validator behavior was changed.
- Findings:
  - The historical Stage-2 "8 specialist" statement is no longer the complete
    current matrix.
  - The current representative center matrix has 12 cases:
    `2 topologies x 2 ride-through classes x 3 phase classes`
    (`balanced`, `A-phase`, `AB-phase`).
  - Latest authoritative recheck:
    `lab/results/hpt_stage6_recheck_current12_repaired_sac_20260728/`.
  - Latest manifest:
    `sac/experiments/stage6_recheck_manifest_current12_repaired_sac_20260728.csv`.
  - The latest recheck reports `12 / 12` switch-level
    `voltage_survival_pass`, `12 / 12` beat conventional by the current
    `control_score`, and `0 / 12` `full_frt_pass`.
- Validator audit:
  - `voltage_survival_pass` currently requires the fault LV band, timestep
    LVRT/HVRT envelope, recovery envelope, DC-link survival, and action limit.
  - `full_frt_pass` additionally requires grid-current and reactive-current
    criteria, so it remains outside the current voltage-survival claim.

## 2026-07-30 - Conventional dq closed-loop controller implementation smoke

- Scope:
  - Upgraded the shared `HPTSACController` conventional branch in
    `simulink/add_hpt_sac_controller.m` from fixed fault-action
    rules to a state-feedback dq action generator:
    LV voltage PI -> `[m_reg_d, m_reg_q]`, DC-link PI -> `m_energy_d`,
    and energy q-current damping -> `m_energy_q`.
  - Kept the public 24-D observation / 4-D action contract unchanged.
  - Enabled topology1 regulating q-axis gain in
    `simulink/topoloty1/build_hpt_v2_1to1_switchlevel.m`.
  - Added explicit conventional-dq profile parameters for both topology1 and
    topology2 in
    `simulink/evaluators/eval_hpt_v2_control_comparison.m`.
- Interface gate:
  - Python MATLAB Engine import was unavailable:
    `matlab_engine_import_failed: No module named 'matlab'`.
  - Fallback command passed:
    `matlab -batch "cd('E:/research_space/Hybrid-power-transformer/simulink'); run(fullfile(pwd,'tests','test_hpt_v2_sac_interface.m'));"`.
  - Result: `HPT SAC 24/4 interface regression passed for topology1 and topology2`.
- Switch-level smoke:
  - Command:
    `matlab -batch "cd('E:/research_space/Hybrid-power-transformer/simulink'); hpt_compare_topology='all'; hpt_compare_scenario_type='fault'; hpt_compare_modes=string({'conventional_dq'}); hpt_compare_faults={'sag_0p90',0.90,0.060; 'swell_1p10',1.10,0.060}; hpt_compare_run_label='dq_closed_loop_smoke_tuned_20260730'; run(fullfile(pwd,'evaluators','eval_hpt_v2_control_comparison.m'));"`.
  - CSV:
    `lab/results/hpt_v2_control_comparison/control_comparison_all_fault_all_dq_closed_loop_smoke_tuned_20260730_20260730_003603.csv`.
  - Result: all four cases simulated successfully but none passed full FRT.
    Topology1 no longer collapses DC link under `sag_0p90`; however,
    timestep envelope/recovery violations remain.  Topology2 still needs
    DC-link/recovery tuning and HVRT reactive-current sign repair.
- Interpretation:
  - The dq closed-loop structure is now connected and runnable for both
    topologies.
  - It is not yet a final strong conventional baseline.  The next engineering
    step is to tune/regress the dq profile against the voltage-survival
    boundary before using it in beat-conventional claims.

## 2026-07-30 - Conventional dq center-case tuning campaign

- Created:
  `sac/campaigns/tune_hpt_conventional_dq_profile.py`.
- Campaigns:
  - Smoke:
    `lab/results/hpt_conventional_dq_tuning_smoke_20260730/`.
  - Center matrix:
    `lab/results/hpt_conventional_dq_tuning_center_20260730/`.
  - Refined matrix:
    `lab/results/hpt_conventional_dq_tuning_refine_20260730/`.
- Matrix:
  - Switch-level `conventional_dq` mode.
  - Topologies: topology1 and topology2.
  - Faults: balanced `sag_0p90 / 60 ms` and `swell_1p10 / 60 ms`.
  - Metrics: current voltage-survival gate, full-FRT flag, envelope
    violation, recovery violation, DC-link extrema, and action magnitude.
- Result:
  - No tuned conventional dq candidate passed the two-case voltage-survival
    gate (`0 / 2` for every candidate).
  - Topology1 can be tuned close to the voltage envelope:
    `t1_refine_reg080_k8` reached
    `envelope_violation_max_pu = 0.009684` and
    `recovery_violation_max_pu = 0.005080`, but it pulled the DC link down to
    `535.921 V`, so it is not an acceptable baseline.
  - The safer topology1 candidates kept DC link within the survival range but
    still had envelope/recovery violations.  Example:
    `t1_strong_voltage` kept `Vdc = 787.761..922.672 V`, but still had
    `envelope_violation_max_pu = 0.019073` and
    `recovery_violation_max_pu = 0.013212`.
  - Topology2 q-axis polarity is important.  The q-flip candidates reduced
    voltage violations substantially, but the DC link still exceeded the
    survival range (`Vdc_max` around `1286..1292 V` in the refined sweep).
  - Flipping the energy-bridge sign was not a fix; the center sweep
    `t2_energy_sign_flip` drove `Vdc_min` down to about `117 V`.
- Interpretation:
  - Parameter tuning alone is not enough to make the current conventional dq
    branch a strong baseline.
  - The next conventional-baseline step should be structural:
    DC-aware regulating-action saturation, recovery gain scheduling and
    anti-windup, topology2 q-axis sign correction with separate DC-link
    stabilization, and a clearer energy-branch/chopper power-balance loop.
  - Failed tuned candidates were not promoted into the default evaluator.

## 2026-07-30 - topology2 balanced LVRT split-head SAC voltage-survival pass

- Scope:
  - Continued the single-family target:
    `topology2` balanced LVRT `0.90 pu / 60 ms`.
  - Goal was to turn a switch-level passing pre-ramp trajectory into a
    deployable 4-D split-head actor with separate regulating and energy heads.
- Interface/code changes:
  - `sac/offline/train_hpt_voltage_sac.py` now supports
    `--behavior-anchor-dataset`, allowing BC/DAgger anchor repair from an
    explicit `.npz` dataset instead of sampling only from `--init-model`.
  - The trainer records the behavior-anchor dataset path and sample count in
    the run summary.
- Data:
  - Built command-action behavior anchors from
    `lab/results/hpt_v2_trajectory_traces/trajectory_trace_topology2_trajectory_teacher_20260730_224546.csv`.
  - Important semantic fix: targets use `action_01..action_04` command
    columns, not measured `teacher_action_*` response columns.
  - Initial anchor:
    `lab/results/hpt_t2_bal_lvrt090_preramp_teacher_actor_20260730/preramp_behavior_anchor.npz`
    with `631` weighted samples.
  - DAgger anchor:
    `lab/results/hpt_t2_bal_lvrt090_preramp_split_bcrepair_20260730/preramp_dagger_behavior_anchor.npz`
    with `1719` weighted samples.  It combines teacher observations and actor
    rollout observations relabeled by the same-time teacher command.
- Diagnostics:
  - Pure split-head conversion and first BC repair still failed the timestep
    voltage envelope.
  - Trace comparison showed the actor's own rollout observations caused the
    fault-period regulating command to undershoot the teacher by about
    `0.03` in `m_reg_d` and `0.012` in `m_reg_q`; this was a DAgger-style
    covariate-shift problem.
- Successful actor:
  - DAgger repair model:
    `data/models/hpt_t2_bal_lvrt090_preramp_split_daggerrepair_20260730.zip`.
  - Safe SAC fine-tune model:
    `data/models/hpt_t2_bal_lvrt090_preramp_split_safe_sacft_20260730.zip`.
  - SAC fine-tune used `1000` proxy steps, learning rate `1e-7`,
    support-regularization weight `5000`, and periodic behavior anchors.
  - Reward trace:
    `lab/results/hpt_t2_bal_lvrt090_preramp_split_safe_sacft_20260730/sac_training_reward_trace.csv`.
- Switch-level validation:
  - CSV:
    `lab/results/hpt_v2_control_comparison/control_comparison_topology2_fault_all_hpt_t2_bal_lvrt090_preramp_split_safe_sacft_commonact_modeldefault_20260730_20260730_230938.csv`.
  - Strong conventional dq:
    `voltage_survival_pass = 0`, reason `grid_current_limit`,
    `control_score = 110.7676220676`,
    `grid_current_peak_pu = 1.5043653289`.
  - Safe SAC fine-tune actor:
    `voltage_survival_pass = 1`,
    `control_score = 107.5762663193`,
    `grid_current_peak_pu = 1.3919829878`,
    `envelope_violation_max_pu = 0`,
    `recovery_violation_max_pu = 0`,
    `fault_lv_band_violation_max_pu = 0`,
    `vdc_min = 721.335 V`, `vdc_max = 950.090 V`.
- Interpretation:
  - This is a valid switch-level voltage-survival result for one topology2
    balanced LVRT center case and it beats the tuned conventional dq baseline
    under the current voltage-survival/current-gated evaluator.
  - It is not full FRT certification: `full_frt_pass = 0` because the
    reactive-current criterion still reports `reactive_wrong_sign`.
- Next action:
  - Preserve this actor as the current single-family split-head SAC baseline.
  - Do not expand to more families until the same DAgger-anchor plus protected
    SAC fine-tune flow is wrapped as a reproducible campaign command.
  - Later full-FRT work must repair reactive-current support separately.

## 2026-07-30 - Paper figures for topology2 balanced LVRT control traces

- Scope:
  - Generated paper-ready Simulink switch-level trace figures for the same
    `topology2` balanced LVRT `0.90 pu / 60 ms` case.
- Controllers compared:
  - SAC initial: pre-fine-tune split-head DAgger actor
    `data/models/hpt_t2_bal_lvrt090_preramp_split_daggerrepair_20260730.zip`.
  - SAC after fine-tune:
    `data/models/hpt_t2_bal_lvrt090_preramp_split_safe_sacft_20260730.zip`.
  - Strong dq closed-loop: `policy_mode = 0` with the same topology2
    common-actuation and conventional-dq parameters used in the switch-level
    gate comparison.
- Trace CSVs:
  - `lab/results/hpt_v2_trajectory_traces/trajectory_trace_topology2_paper_t2_bal_lvrt090_sac_initial_dagger_20260730_20260730_234739.csv`.
  - `lab/results/hpt_v2_trajectory_traces/trajectory_trace_topology2_paper_t2_bal_lvrt090_sac_after_finetune_20260730_20260730_234928.csv`.
  - `lab/results/hpt_v2_trajectory_traces/trajectory_trace_topology2_paper_t2_bal_lvrt090_strong_dq_20260730_20260730_235101.csv`.
- Figures:
  - `paper/figures/simulink_control_traces/fig_t2_bal_lvrt090_m_actions_sac_init_sac_trained_dq.png`.
  - `paper/figures/simulink_control_traces/fig_t2_bal_lvrt090_m_actions_sac_init_sac_trained_dq.pdf`.
  - `paper/figures/simulink_control_traces/fig_t2_bal_lvrt090_voltage_sac_init_sac_trained_dq.png`.
  - `paper/figures/simulink_control_traces/fig_t2_bal_lvrt090_voltage_sac_init_sac_trained_dq.pdf`.
  - Manifest:
    `paper/figures/simulink_control_traces/fig_t2_bal_lvrt090_trace_manifest.json`.
- Notes:
  - The SAC initial and post-fine-tune voltage traces nearly overlap, which is
    expected because protected SAC fine-tuning was intentionally low-step and
    heavily behavior-anchored.
  - The dq closed-loop command is visibly more aggressive in `m_reg_d` and
    `m_reg_q`; this matches the switch-level comparison where dq had good
    voltage envelope behavior but failed the grid-current gate.

## 2026-07-31 - Topology2 balanced LVRT boundary expansion with dq-seeded SAC

- Scope:
  - Replaced the hand-searched pre-ramp trajectory teacher with switch-level
    strong-dq traces as the behavior source.
  - Targeted `topology2` balanced LVRT only, with a depth-duration boundary
    matrix: `0.85 / 0.875 / 0.90 pu` by `80 / 100 / 120 ms`.
  - Used stable prefault timing: fault start `0.080 s`; behavior-anchor samples
    before `0.020 s` were dropped to avoid startup transient contamination.
- Code changes:
  - Added single-case CLI support to
    `sac/offline/train_hpt_voltage_sac.py`, so a SAC run can train
    directly on one explicit topology/fault/depth/duration family.
  - Added campaign runner:
    `sac/campaigns/run_hpt_t2_balanced_lvrt_dq_seeded_boundary.py`.
  - Added result summarizer:
    `sac/campaigns/summarize_hpt_boundary_run.py`.
- Full run:
  - Command:
    `py -3 -m sac.campaigns.run_hpt_t2_balanced_lvrt_dq_seeded_boundary --depths 0.85,0.875,0.90 --durations-ms 80,100,120 --bc-epochs 140 --sac-steps 600 --fault-start-s 0.080 --anchor-min-time-s 0.020 --run-id hpt_t2_bal_lvrt_dqseed_boundary_3x3_f080_20260731`.
  - Run directory:
    `lab/results/hpt_t2_bal_lvrt_dqseed_boundary_3x3_f080_20260731`.
  - Compact summary:
    `lab/results/hpt_t2_bal_lvrt_dqseed_boundary_3x3_f080_20260731/boundary_summary.md`.
- Aggregate switch-level voltage-survival results:
  - Strong dq baseline: `0 / 9` pass; all failed the current gate.
  - Dq-seeded actor before SAC: `4 / 9` pass and `7 / 9` lower score than
    strong dq.
  - Dq-seeded actor after current-aware protected SAC: `2 / 9` pass,
    `5 / 9` lower score than strong dq, and score improved over the seed in
    `3 / 9` cases.
- Clean boundary evidence:
  - At `0.90 pu` and `80 / 100 ms`, current-aware protected SAC preserves
    voltage-survival and slightly improves the dq-seeded score.
  - At `0.90 pu / 120 ms`, the dq-seeded actor passes but the current SAC
    fine-tune loses the DC-link gate.
  - At deeper `0.85-0.875 pu` sag, the limiting failure mode is the
    energy/DC-link branch, not LV voltage envelope tracking.
- Interpretation:
  - The new route is cleaner than the hand-searched pre-ramp route: it starts
    from a real switch-level strong-dq trajectory, not a manually shaped
    action.
  - However, protected SAC fine-tuning is still not robust enough for the full
    boundary.  It can improve score near `0.90 pu`, but it can also degrade
    DC-link survival at deeper sag.
- Next action:
  - Keep `dq_seeded_actor_before_sac` as the reliable baseline for this family.
  - Redesign the SAC fine-tune reward/support constraint so the energy head is
    explicitly DC-link-safe before expanding this route to other families.

## 2026-07-31 - Energy-safe SAC repair and profile promotion evidence

- Scope:
  - Continue the topology2 balanced LVRT boundary work after discovering that
    naive current-aware SAC could destroy DC-link survival.
  - Goal: make SAC contribute a switch-level improvement rather than only
    preserving the dq-seeded actor.
- Code changes:
  - `sac/hpt_voltage_sac_env.py` now includes calibrated
    `vdc_min/vdc_max` in the Vdc bounds reward term.  Previously the explicit
    Vdc bounds reward used only the proxy state `self.vdc`, while
    switch-level failure was driven by calibrated or measured extrema.
  - `sac/offline/train_hpt_voltage_sac.py` gained
    `--sac-energy-head-only`.  With split heads, the actor update can now
    freeze the shared trunk and regulating head while updating only
    `mu.energy_head`, protecting a dq-seeded voltage trajectory from SAC
    recovery-action drift.
  - `sac/campaigns/run_hpt_t2_balanced_lvrt_dq_seeded_boundary.py`
    was retuned to an energy-safe profile: stronger support anchoring,
    stronger Vdc/envelope/survival reward, and lower grid-current greed.
  - Added
    `sac/campaigns/summarize_hpt_sac_profile_promotion.py` to compare
    multiple SAC fine-tune profiles against the dq-seeded actor using only
    switch-level validation rows.
- Key diagnostics:
  - The previous failing case `0.90 pu / 120 ms` was repaired:
    `lab/results/hpt_t2_bal_lvrt_dqseed_energy_safe_090_120_20260731`.
    Strong dq failed current; dq seed passed with score `110.932`; energy-safe
    SAC passed with score `110.124`.
  - A 2x2 neighbor matrix with the full-head energy-safe profile:
    `lab/results/hpt_t2_bal_lvrt_dqseed_energy_safe_2x2_20260731`.
    Result: strong dq `0/4` pass, dq-seeded actor `3/4` pass, full-head SAC
    `3/4` pass.  Full-head SAC repaired `0.875 pu / 120 ms` from DC-link fail
    to pass, but still destroyed `0.875 pu / 100 ms`.
  - Energy-head-only SAC diagnostic:
    `lab/results/hpt_t2_bal_lvrt_dqseed_energy_head_only_0875_100_120_20260731`.
    Result: it preserved the `0.875 pu / 100 ms` seed pass but did not repair
    `0.875 pu / 120 ms`.
- Promotion evidence:
  - Profile-promotion report:
    `lab/results/hpt_t2_bal_lvrt_sac_profile_promotion_20260731/sac_profile_promotion_summary.md`.
  - On the 2x2 topology2 balanced LVRT matrix:
    - strong dq: `0/4` voltage-survival pass;
    - dq-seeded actor: `3/4` voltage-survival pass;
    - best switch-level SAC profile: `4/4` voltage-survival pass;
    - strict SAC improvements over dq seed: `2/4`;
    - best SAC profile loses seed pass: `0/4`.
- Interpretation:
  - This is the first clean evidence in this branch that SAC fine-tuning can
    materially improve the experiment rather than merely follow a BC/DAgger
    seed.
  - The improvement is still scoped: topology2, balanced LVRT, and the tested
    `0.875/0.90 pu` by `100/120 ms` neighborhood.
  - The robust controller logic should be profile-aware: full-head SAC can
    expand the boundary when the seed fails; energy-head-only SAC is safer for
    seed-pass cases where regulating-head drift would harm DC-link survival.
- Next action:
  - Promote this as the current topology2 balanced LVRT SAC-improvement
    evidence.
  - Generalize the profile-promotion gate to larger boundary matrices only
    after adding automated profile selection and avoiding proxy-only promotion.

## 2026-07-31 - No-profile-selection family SAC attempt for topology2 balanced LVRT

- Scope:
  - Re-ran the topology2 balanced LVRT work under the updated constraint:
    no automatic profile selection, one fixed family-level actor for the
    `0.875/0.90 pu x 100/120 ms` neighborhood.
  - Changed the training direction from single-case score optimization to
    family-level fine-tune with gate-aware reward terms.
- Code changes:
  - `sac/hpt_voltage_sac_env.py` now has explicit gate-margin reward
    terms for LV envelope, DC-link bounds, and grid-current margin.
  - `sac/offline/train_hpt_voltage_sac.py` gained family-case CLI
    arguments and `--behavior-anchor-energy-head-only`.
  - `sac/pretrain_hpt_actor_bc.py` can now fit only
    `mu.energy_head`, preserving a validated regulating head while fitting
    DC-link support targets.
  - `sac/campaigns/run_hpt_t2_balanced_lvrt_family_gate_sac.py`
    now builds one family anchor from multiple dq traces and can inject
    calibration-derived energy targets.
- Switch-level findings without profile selection:
  - Best fixed candidate in this run:
    `energy_head_bc_seed_q04_tau001`, summarized in
    `lab/results/hpt_t2_bal_lvrt_family_gate_sac_roundup_20260731/candidate_summary.csv`.
    It achieved `1/4` voltage-survival pass, with all four cases passing LV
    envelope, recovery envelope, and grid-current limit; remaining failures
    are DC-link survival.
  - Strong conventional dq remains `0/4` under the same validator because it
    violates the grid-current gate despite passing LV and DC-link checks.
  - Naive energy-head-only SAC fine-tune from the `q=0.4` seed did not improve
    switch-level performance: it fell to `0/4` and reduced DC-link margins,
    even though proxy-side rewards were available.
  - Fixed energy support sweeps showed the tradeoff:
    `m_energy_q=0.4` keeps current under the gate but lacks DC-link margin;
    `m_energy_q=0.55-0.8` improves some DC-link behavior but pushes current
    near or above the `1.5 pu` limit.
  - Both positive and negative `m_energy_d` family targets worsened at least one
    gate, so a simple sign flip is not the missing solution.
- Interpretation:
  - Under the new no-profile-selection constraint, the current single fixed
    family actor is not yet a publishable SAC improvement claim.
  - The earlier `4/4` profile-promotion result is still useful diagnostic
    evidence, but it depends on selecting among multiple SAC profiles after
    switch-level checks and should not be reported as the current main
    controller claim.
  - The limiting mismatch is the topology2 energy/DC-link branch.  Proxy SAC
    can exploit an inaccurate energy/DC-link gradient, so further SAC training
    should wait for family-specific proxy/reward alignment or use direct
    switch-level trajectory-aware updates.
- Next action:
  - Build a family-specific proxy alignment table from the new switch-level
    rows and energy-branch probes.
  - Do not expand this method to the remaining 11 specialists until the
    topology2 balanced LVRT family can produce one fixed actor that improves
    the strict switch-level boundary over strong dq without profile selection.

## 2026-07-31 - Family proxy alignment and correction-aware SAC negative result

- Alignment result:
  - Built a mean-action diagnostic matrix from the topology2 balanced LVRT
    family candidates:
    `lab/results/hpt_t2_bal_lvrt_family_proxy_alignment_20260731/family_mean_action_alignment_matrix.csv`.
  - Proxy rollout alignment:
    `lab/results/hpt_t2_bal_lvrt_family_proxy_alignment_20260731/rollout_alignment/family_mean_action_alignment_matrix_summary.json`.
  - The current proxy is strongly misaligned for this family:
    - LV mean MAE: `0.061 pu`;
    - Vdc mean MAE: `0.199 pu`, max `0.499 pu`;
    - grid-current peak MAE: `0.344 pu`, max `0.367 pu`.
  - Error direction is harmful for SAC: proxy overestimates DC-link voltage and
    underestimates grid-current peak, so the actor receives overly optimistic
    gradients near the exact gates that fail in Simulink.
- Code changes:
  - Added conservative reward-correction knobs to
    `sac/hpt_voltage_sac_env.py` and
    `sac/offline/train_hpt_voltage_sac.py`:
    `proxy_vdc_reward_downshift_pu` and
    `proxy_grid_current_reward_upshift_pu`.
- Correction-aware SAC test:
  - Trained
    `hpt_t2_bal_lvrt_correction_aware_sac_from_q04_2x2_20260731`
    from the best `q=0.4` seed using Vdc downshift `0.20 pu` and current
    upshift `0.32 pu`.
  - Switch-level result:
    `lab/results/hpt_t2_bal_lvrt_correction_aware_sac_from_q04_2x2_20260731_eval_tau001/summary.json`.
    It achieved `0/4` strict voltage-survival pass; LV envelope and current
    gates passed, but DC-link survival still failed.
- Current no-profile-selection conclusion:
  - Best fixed family candidate remains
    `energy_head_bc_seed_q04_tau001` with `1/4` strict pass, all four cases
    passing LV envelope, recovery envelope, and grid-current limit.
  - Strong dq remains `0/4` because it violates grid current, but it keeps
    DC-link high.  SAC/BC candidates can satisfy current but tend to consume
    DC-link energy.
  - Under the no-profile-selection constraint, the current topology2 balanced
    LVRT family does not yet provide a robust publishable SAC superiority
    claim.
- Next action:
  - Stop blind proxy SAC for this family.
  - Either collect a true family-level switch matrix with dynamic trajectories
    and train an uncertainty-aware learned proxy, or move to a direct
    switch-level trajectory-aware policy update where the DC/current tradeoff is
    evaluated by Simulink in the loop.

## 2026-07-31 - Fixed topology2 balanced LVRT family SAC without profile selection

- Scope:
  - Followed the updated constraint from the user: do **not** use automatic
    profile selection, do **not** optimize only one point, and first continue on
    the original `1/12` expert family: topology2 balanced LVRT.
  - Objective: one fixed family actor should beat strong conventional dq on a
    switch-level fault-depth/duration family.
- Code changes:
  - Added
    `sac/campaigns/run_hpt_t2_balanced_lvrt_family_distill_sac.py`.
  - The campaign:
    1. reads the earlier per-case switch-level success manifest;
    2. selects one passing teacher trace per case as data only, not as runtime
       profile selection;
    3. collects actual Simulink actor traces;
    4. combines them into one family anchor dataset;
    5. behavior-clones one fixed split-head actor;
    6. applies conservative gate-aware SAC fine-tuning;
    7. validates that one actor on the `0.875/0.90 pu x 100/120 ms`
       switch-level matrix.
  - Fixed the campaign summary code to use current validator field names:
    `gbt_vdc_survive_pass`, `gbt_grid_current_limit_pass`,
    `gbt_voltage_envelope_pass`, `gbt_action_limit_pass`, and `control_score`.
- Diagnostic run `r1`:
  - Run:
    `lab/results/hpt_t2_bal_lvrt_family_distill_gate_sac_2x2_20260731_r1`.
  - Teacher traces were collected with `actor_filter_tau=0.001`, which means the
    training target had already been filtered.  The exported family actor was
    then filtered again in formal evaluation, creating an avoidable lag.
  - Result:
    - family BC seed: `0/4`;
    - family gate-aware SAC: `1/4`;
    - strong dq: `0/4`.
  - Interpretation: SAC improved over BC but the filtered-teacher target is not
    the right distillation target.
- Main run `r2_rawteacher`:
  - Run:
    `lab/results/hpt_t2_bal_lvrt_family_distill_gate_sac_2x2_20260731_r2_rawteacher`.
  - Changed only teacher-trace collection to `actor_filter_tau=0`, while formal
    switch-level evaluation still used the standard `0.001 s` actor filter.
  - Result under one fixed actor, no profile selection:
    - strong dq: `0/4` voltage-survival pass;
    - family BC seed: `0/4` voltage-survival pass;
    - family gate-aware SAC: `2/4` voltage-survival pass.
  - Passed SAC cases:
    - `topology2 balanced LVRT 0.875 pu / 120 ms`;
    - `topology2 balanced LVRT 0.900 pu / 120 ms`.
  - Failed SAC cases:
    - `0.875 pu / 100 ms`: DC-link lower-bound margin remains insufficient;
    - `0.900 pu / 100 ms`: DC-link lower-bound margin remains insufficient.
  - Gate details for the SAC actor:
    - all 4 cases pass LV envelope;
    - all 4 cases pass recovery envelope;
    - all 4 cases pass action limit;
    - all 4 cases pass grid-current limit;
    - all 4 cases pass Vdc survival boolean in the row fields, but the stricter
      voltage-survival gate still reports `dc_link_bounds` for the two short
      cases.  This needs a later cleanup of duplicated Vdc-bound terminology.
- Interpretation:
  - This is the first no-profile-selection evidence that a single topology2
    balanced LVRT family SAC actor beats the strong dq baseline in switch-level
    voltage-survival: `2/4` versus `0/4`.
  - It is **not** a full FRT result, because reactive-current support remains
    failed (`full_frt_pass=0`).
  - It is also not yet a complete family controller, because the short-duration
    points still fail the strict DC-link bound.  The likely next technical issue
    is duration/energy conditioning rather than just more SAC steps.
- Next action:
  - Treat `r2_rawteacher` as the current fixed-family SAC baseline.
  - Next research step should target the two short-duration DC-bound failures:
    add clearer duration/remaining-fault information to the policy input or
    train a direct switch-level trajectory-aware energy-head update for the
    short-duration branch.

## 2026-07-31 - Expanded topology2 balanced LVRT fixed-actor boundary matrix

- Scope:
  - Responded to the request to expand the family-fault matrix and produce a
    clearer SAC-versus-traditional boundary.
  - Kept the comparison clean: one fixed topology2 balanced-LVRT SAC actor, no
    retraining, no profile selection, and the same switch-level voltage-survival
    validator for strong dq and SAC.
- Code changes:
  - Added
    `sac/campaigns/run_hpt_t2_balanced_lvrt_fixed_actor_boundary.py`.
  - The runner exports one SAC actor once and sweeps a depth-duration grid,
    writing:
    `boundary_raw_rows.csv`,
    `boundary_compact_controller_rows.csv`,
    `boundary_case_table.csv`,
    `boundary_relation_map.csv`,
    `boundary_strong_dq_pass_map.csv`,
    `boundary_fixed_sac_pass_map.csv`,
    `summary.json`, and `BOUNDARY_REPORT.md`.
- Main run:
  - Run id:
    `hpt_t2_bal_lvrt_fixed_actor_boundary_25case_20260731_r1`.
  - Command:
    `py -3 -m sac.campaigns.run_hpt_t2_balanced_lvrt_fixed_actor_boundary --run-id hpt_t2_bal_lvrt_fixed_actor_boundary_25case_20260731_r1 --depths 0.85,0.875,0.90,0.925,0.95 --durations-ms 60,80,100,120,160`.
  - Actor:
    `data/models/hpt_t2_bal_lvrt_family_distilled_gate_sac_hpt_t2_bal_lvrt_family_distill_gate_sac_2x2_20260731_r2_rawteacher.zip`.
  - Result folder:
    `lab/results/hpt_t2_bal_lvrt_fixed_actor_boundary_25case_20260731_r1`.
- Switch-level voltage-survival result:
  - strong dq: `0/25`.
  - fixed family SAC: `4/25`.
  - SAC-only points:
    - `0.85 pu / 100 ms`;
    - `0.85 pu / 120 ms`;
    - `0.875 pu / 120 ms`;
    - `0.90 pu / 120 ms`.
  - dq-only points: `0`.
  - both-fail points: `21`.
- Boundary interpretation:
  - The strong dq baseline fails this validator mostly at the grid-current gate.
  - The SAC actor lowers grid current enough to pass several mid-duration
    voltage-survival cases, but many failures remain due to DC-link lower bound
    or timestep voltage/recovery envelope violations.
  - The current feasible SAC region is not monotonic in depth or duration; it is
    a narrow energy-dynamics island around `100-120 ms`, especially `120 ms`.
  - This is useful boundary evidence, but still not a full FRT claim because
    reactive-current support remains outside the current pass scope.
- Next action:
  - Use the new boundary table to target the failed neighboring cells:
    `0.85/80 ms`, `0.875/100 ms`, `0.90/100 ms`, and `0.925/120 ms`.
  - The likely next model change is duration/remaining-fault conditioning or a
    direct switch-level energy-head update, not simply more proxy SAC steps.

## 2026-08-01 - Topology2 balanced LVRT neighbor debug with dq-seeded full-head SAC

- Scope:
  - Tested whether the 25-case boundary result proves a monotonic SAC coverage
    expansion as LVRT depth and duration increase.
  - Because the earlier fixed-actor map was non-monotonic, treated the claim as
    unproven and ran a focused debug on four neighboring cells before expanding
    to all 12 specialist families.
- Code changes:
  - Updated
    `sac/campaigns/run_hpt_t2_balanced_lvrt_dq_seeded_boundary.py`
    so explicit `fault_pu:duration_ms` case pairs can be passed through
    `--case-pairs`.
  - Changed the default SAC fine-tune from energy-head-only to full split-head
    updates.  The old behavior remains available through
    `--sac-energy-head-only`.
  - Added
    `sac/summaries/plot_hpt_dqseed_case_evidence.py` to export
    switch-level action traces, LV/Vdc traces, and SAC reward convergence plots
    for one campaign case.
- Main run:
  - Run id:
    `hpt_t2_bal_lvrt_dqseed_fullhead_boundary_neighbors_20260801_r1`.
  - Command:
    `py -3 -m sac.campaigns.run_hpt_t2_balanced_lvrt_dq_seeded_boundary --run-id hpt_t2_bal_lvrt_dqseed_fullhead_boundary_neighbors_20260801_r1 --case-pairs 0.85:80;0.875:100;0.90:100;0.925:120 --bc-epochs 180 --sac-steps 1600 --fault-start-s 0.08 --anchor-min-time-s 0.02`.
  - Result folder:
    `lab/results/hpt_t2_bal_lvrt_dqseed_fullhead_boundary_neighbors_20260801_r1`.
- Aggregate switch-level voltage-survival result:
  - strong dq: `0/4`.
  - dq-seeded actor before SAC: `1/4`, with `2/4` scores better than strong dq.
  - dq-seeded actor after SAC: `1/4`, with `3/4` scores better than strong dq.
  - SAC fine-tune improved the seed score in all 4 cases and did not lose the
    one seed pass, but it did not increase the pass count.
- Per-case conclusion:
  - `0.85 pu / 80 ms`: strong dq failed grid-current limit; SAC variants failed
    DC-link bound and recovery envelope.
  - `0.875 pu / 100 ms`: strong dq failed grid-current limit; SAC variants
    failed DC-link bound.
  - `0.90 pu / 100 ms`: strong dq failed grid-current limit; both dq-seeded
    actor and SAC fine-tuned actor passed voltage-survival.
  - `0.925 pu / 120 ms`: strong dq failed grid-current limit; SAC variants
    failed DC-link bound.
- Figures generated:
  - Successful representative case:
    `lab/results/hpt_t2_bal_lvrt_dqseed_fullhead_boundary_neighbors_20260801_r1/figures/t2_bal_lvrt_pu0900_d100ms/`.
  - Failed neighbor case:
    `lab/results/hpt_t2_bal_lvrt_dqseed_fullhead_boundary_neighbors_20260801_r1/figures/t2_bal_lvrt_pu0875_d100ms/`.
  - Each folder includes action-trace comparison, LV/Vdc switch-level traces,
    reward convergence, and a figure manifest.
- Interpretation:
  - The user's monotonic boundary-expansion hypothesis is not supported yet.
    The tested SAC actor covers more cells than strong dq in the bounded matrix,
    but the coverage island is non-monotonic and energy-limited.
  - The main bottleneck is no longer LV voltage tracking.  In the failed SAC
    neighbor cases, LV RMS stays inside the voltage band, while the DC link
    drops below the strict bound after the fault/recovery transient.
  - Expanding this exact mechanism to all 12 specialists now would likely
    multiply a known energy-branch weakness rather than prove the larger claim.
- Next action:
  - Do not expand to 12 families until topology2 balanced LVRT has a robust
    duration/depth-conditioned energy strategy.
  - The next experiment should add duration/remaining-fault/recovery-state
    conditioning or direct switch-level energy-head fine-tuning, then rerun the
    same 4-neighbor matrix and the prior 25-case matrix.

## 2026-08-01 - Causal time-normalization fix and micro-SAC boundary debug

- Scope:
  - Continued the topology2 balanced-LVRT boundary investigation before any
    expansion to the 12 specialist families.
  - Treated the non-monotonic 25-case boundary as a debug signal rather than a
    publishable family-coverage proof.
- Interface/debug fixes:
  - `add_hpt_sac_controller.m` now accepts
    `hpt_sac_fault_time_norm_s` and `hpt_sac_recovery_time_norm_s`, replacing
    the hard-coded 0.5 s normalization used in SAC observations.
  - The topology1/topology2 builders provide backward-compatible defaults of
    0.5 s, while the topology2 balanced-LVRT campaign uses a causal family
    value of 0.12 s.
  - `collect_hpt_v2_trajectory_trace.m` now sets
    `hpt_sac_gridnorm_startup_s` the same way as the switch-level validator.
    This fixed a trace/validator mismatch where plots showed Vdc near 800 V
    while the validator correctly reported a 628.9 V DC-link minimum.
- Main repeat runs:
  - `hpt_t2_bal_lvrt_dqseed_fullhead_timenorm012_neighbors_20260801_r1`
    with 1600 SAC steps.
  - `hpt_t2_bal_lvrt_dqseed_energyonly_timenorm012_neighbors_20260801_r1`
    with 1600 SAC steps, energy-head-only actor update.
  - `hpt_t2_bal_lvrt_dqseed_micro120_timenorm012_neighbors_20260801_r1`.
  - `hpt_t2_bal_lvrt_dqseed_micro040_timenorm012_neighbors_20260801_r1`.
  - `hpt_t2_bal_lvrt_dqseed_micro020_timenorm012_neighbors_20260801_r1`.
- Key switch-level evidence:
  - With 0.12 s time normalization, the dq-seeded split-head actor improved
    from the previous `1/4` neighbor pass result to `3/4`.
  - Strong dq remained `0/4` on the same four boundary-neighbor cases.
  - Naive longer SAC fine-tuning was harmful:
    - 1600-step full-head SAC: `0/4`.
    - 1600-step energy-head-only SAC: `0/4`.
    - 120-step SAC: `1/4`.
  - Short 40-step SAC was the best fine-tune tested so far:
    - dq seed: `3/4`;
    - after SAC: `2/4`;
    - after SAC beat strong dq score on `3/4`;
    - SAC improved score and preserved pass for `0.875 pu / 100 ms` and
      `0.90 pu / 100 ms`, but lost the seed pass at `0.925 pu / 120 ms`
      because Vdc fell to 628.9 V.
- Figures and summary:
  - Summary table:
    `lab/results/hpt_t2_bal_lvrt_dqseed_micro040_timenorm012_neighbors_20260801_r1/TIME_NORM_DEBUG_SUMMARY.md`.
  - Pass-and-improve trace:
    `lab/results/hpt_t2_bal_lvrt_dqseed_micro040_timenorm012_neighbors_20260801_r1/figures/t2_bal_lvrt_pu0875_d100ms/`.
  - Seed-pass/SAC-fail trace:
    `lab/results/hpt_t2_bal_lvrt_dqseed_micro040_timenorm012_neighbors_20260801_r1/figures/t2_bal_lvrt_pu0925_d120ms/`.
- Interpretation:
  - The user's desired claim, "SAC covers a larger monotonic depth-duration
    boundary than strong dq," is still not proven.
  - The strongest current result is narrower: topology2 balanced LVRT has
    boundary-neighbor cases where a dq-seeded SAC actor passes while strong dq
    fails, and very short SAC fine-tuning can reduce score on some pass cases.
  - The failure mechanism is now clear and reproducible: SAC fine-tune tends to
    erode DC-link margin, especially near `0.925 pu / 120 ms`.
- Next action:
  - Do not expand to all 12 families yet.
  - Add a switch-level promotion/rollback gate or a DC-link-constrained
    fine-tune objective so that a SAC chunk is accepted only if it preserves
    voltage-survival and improves switch-level score.
  - Then rerun the same four-neighbor matrix and the 25-case matrix.

## 2026-08-01 - Post-hoc switch-level promotion check over SAC micro-candidates

- Scope:
  - Combined the already validated 20/40/120/1600-step topology2 balanced-LVRT
    SAC fine-tune candidates to test a switch-level promotion/rollback rule.
  - This is not proxy-only selection: every candidate row came from the
    Simulink switch-level validator.
- Promotion rule:
  - For each boundary-neighbor case, select the lowest-score candidate that
    passes voltage-survival.
  - If no candidate passes, keep the best failed candidate only as a diagnostic.
  - The dq-seeded actor is included as the rollback baseline.
- Result file:
  - `lab/results/hpt_t2_bal_lvrt_dqseed_micro040_timenorm012_neighbors_20260801_r1/PROMOTED_CANDIDATE_SUMMARY.md`.
- Aggregate result:
  - strong dq: `0/4`.
  - dq-seeded actor: `3/4`.
  - promoted candidate: `3/4`.
  - promoted score beats strong dq: `3/4`.
  - promoted score beats dq-seed: `3/4`.
- Per-case promotion:
  - `0.875 pu / 100 ms`: promotes 40-step SAC.
  - `0.90 pu / 100 ms`: promotes 20-step SAC.
  - `0.925 pu / 120 ms`: rolls back to dq-seeded actor because all SAC
    fine-tune chunks drop Vdc below the 650 V bound.
  - `0.85 pu / 80 ms`: no candidate passes; failure remains DC-link/recovery
    limited.
- Interpretation:
  - Promotion/rollback is necessary; without it, naive SAC fine-tune destroys
    feasible seed policies near the DC-link boundary.
  - It stabilizes the current result but does not yet prove larger boundary
    coverage than the dq-seeded actor.
  - The remaining research gap is a DC-link-aware SAC update that turns
    `0.85 pu / 80 ms` into a pass and preserves `0.925 pu / 120 ms`.

## 2026-08-01 - DC-safe SAC fine-tune expands topology2 balanced-LVRT family coverage

- Scope:
  - Continued the topology2 balanced-LVRT debug instead of prematurely
    expanding to all 12 specialist families.
  - Added campaign-level knobs for DC-link-conservative SAC:
    learning rate, support weight, Vdc bounds/margin reward, proxy Vdc
    downshift, LV/envelope reward, calibrated-survival reward, and validation
    actor-filter tau.
- Negative control:
  - `hpt_t2_bal_lvrt_dqseed_dcsafe040_tau0_neighbors_20260801_r1` set the
    actor command filter to zero.
  - Result: `0/4`; no-filter control made the transient/recovery envelope
    worse.  The 1-ms actor filter remains the better validated setting for
    this family.
- DC-safe four-neighbor run:
  - Run id:
    `hpt_t2_bal_lvrt_dqseed_dcsafe040_timenorm012_neighbors_20260801_r1`.
  - Key settings:
    `sac_steps=40`, learning rate `5e-9`, support weight `80000`,
    Vdc bounds weight `120000`, Vdc margin weight `180000`,
    Vdc margin `0.06 pu`, proxy Vdc downshift `0.04 pu`.
  - Result: strong dq `0/4`, dq-seeded initial actor `1/4`, DC-safe SAC
    after fine-tune `3/4`.
  - Remaining failed case `0.875 pu / 100 ms` has only a small early LVRT
    envelope violation (`~0.006 pu`) while DC-link and current pass.
- DC-safe 3x3 family matrix:
  - Run id:
    `hpt_t2_bal_lvrt_dqseed_dcsafe040_3x3_20260801_r1`.
  - Matrix: `0.85/0.875/0.90 pu x 80/100/120 ms`.
  - Result summary:
    `lab/results/hpt_t2_bal_lvrt_dqseed_dcsafe040_3x3_20260801_r1/DCSAFE_3X3_BOUNDARY_SUMMARY.md`.
  - Switch-level result:
    - strong dq: `0/9`;
    - dq-seeded initial actor: `4/9`;
    - DC-safe SAC after fine-tune: `6/9`;
    - SAC score beats strong dq: `7/9`;
    - SAC score beats dq-seed: `5/9`.
  - Representative figure set:
    `lab/results/hpt_t2_bal_lvrt_dqseed_dcsafe040_3x3_20260801_r1/figures/t2_bal_lvrt_pu0850_d080ms/`,
    where strong dq and the dq-seeded actor fail, but DC-safe SAC passes.
- Interpretation:
  - This is the first topology2 balanced-LVRT case-specialist matrix where SAC
    fine-tuning expands pass coverage beyond both strong dq and the dq-seeded
    initial actor under the same switch-level validator.  It is not yet a
    one-actor-per-family boundary.
  - The result supports expanding the DC-safe mechanism to the 12 specialist
    families, but the expansion must keep per-case and then per-family
    switch-level gates because the pass map is still not a perfectly monotonic
    depth-duration frontier.
- Next action:
  - Build a 12-family expansion manifest/runner using the same evidence
    structure: family matrix, dq baseline, dq-seeded initial actor, DC-safe SAC
    fine-tune, reward trace, and representative action/voltage figures.

## 2026-08-01 - 12-family DC-safe center smoke and figure repair

- Scope:
  - Expanded the DC-safe dq-seeded SAC pipeline from the validated topology2
    balanced-LVRT 3x3 family matrix to the 12 specialist fault-family center
    cases.
  - Fixed Python 3.8 compatibility in the 12-family runner.
  - Fixed the evidence plotting script so Simulink trace collection and figure
    titles use the actual topology and phase key instead of hard-coded
    `topology2 balanced`.
- 12-family center run:
  - Run id: `hpt_dcsafe_12family_center_20260801_r1`.
  - Center cases:
    - LVRT families: `0.90 pu / 60 ms`;
    - HVRT families: `1.10 pu / 60 ms`;
    - phases: balanced ABC, A-phase, AB-phase;
    - topologies: topology1 and topology2.
  - Result summary:
    `lab/results/hpt_dcsafe_12family_center_20260801_r1/CENTER_SMOKE_SUMMARY.md`.
  - Manifest:
    `sac/experiments/hpt_dcsafe_12family_center_20260801_r1_manifest.csv`.
- Center-case switch-level result:
  - strong dq: `6/12`;
  - dq-seeded initial actor: `10/12`;
  - DC-safe SAC after fine-tune: `10/12`;
  - SAC pass while dq fails: `5/12`;
  - SAC fail while dq passes: `1/12`;
  - SAC lower-score-than-dq: `4/12`.
- Representative figures:
  - dq-fail/SAC-pass example:
    `lab/results/hpt_dcsafe_12family_center_20260801_r1_t2_a_lvrt/figures/t2_a_lvrt_pu0900_d060ms/`.
  - SAC-fail diagnostic example:
    `lab/results/hpt_dcsafe_12family_center_20260801_r1_t2_bal_lvrt/figures/t2_bal_lvrt_pu0900_d060ms/`.
  - Topology2 balanced-LVRT 3x3 pass-matrix figure:
    `lab/results/hpt_t2_bal_lvrt_dqseed_dcsafe040_3x3_20260801_r1/figures/t2_bal_lvrt_3x3_pass_matrix.png`.
- Interpretation:
  - The user's coverage-area hypothesis is supported for the topology2
    balanced-LVRT case-specialist matrix: strong dq `0/9`, dq-seeded initial
    actor `4/9`, DC-safe SAC `6/9`.
  - The 12-family center smoke does not yet prove 12 full family boundaries.
    It verifies the expansion interface and shows five center cases where SAC
    passes while strong dq fails.
  - Center-level SAC does not improve pass count over the dq-seeded initial
    actor (`10/12` vs `10/12`), so the next evidence target must be
    family-level boundary matrices, not center-only claims.
- Next action:
  - Promote topology2 balanced-LVRT as the first clean family-level
    boundary-expansion evidence.
  - Run reduced depth-duration matrices on the 12 families in priority order,
    starting with the five center dq-fail/SAC-pass topology2 families and the
    two remaining center SAC-fail diagnostics.

## 2026-08-01 - 12-family reduced 2x2 matrix completed

- Scope:
  - Added `run_hpt_dcsafe_12_family_reduced_matrix.py` to run the DC-safe
    dq-seeded SAC pipeline across all 12 fault families on a reduced
    depth-duration matrix.
  - Matrix:
    - LVRT: `0.875/0.90 pu x 60/100 ms`;
    - HVRT: `1.10/1.15 pu x 60/100 ms`;
    - topologies: topology1 and topology2;
    - phases: balanced ABC, A-phase, AB-phase.
  - Run id: `hpt_dcsafe_12family_reduced2x2_20260801_r1`.
- Debug note:
  - The first summary pass double-counted duplicate switch-level rows in some
    child CSVs.  The reducer was fixed to count only the latest row per
    `boundary_label + controller`, then the existing run was re-summarized
    without rerunning Simulink.
- Corrected switch-level result:
  - Total cases: `48`.
  - strong dq: `24/48`.
  - dq-seeded initial actor: `40/48`.
  - DC-safe SAC after fine-tune: `40/48`.
  - SAC pass while strong dq fails: `17/48`.
  - SAC lower-score-than-dq: `19/48`.
  - SAC lower-score-than-seed: `27/48`.
- Evidence artifacts:
  - Summary:
    `lab/results/hpt_dcsafe_12family_reduced2x2_20260801_r1/REDUCED_2X2_MATRIX_SUMMARY.md`.
  - Aggregate pass-count figure:
    `lab/results/hpt_dcsafe_12family_reduced2x2_20260801_r1/reduced_matrix_pass_counts.png`.
  - Per-family pass-count figure:
    `lab/results/hpt_dcsafe_12family_reduced2x2_20260801_r1/reduced_matrix_per_family_pass_counts.png`.
  - Representative dq-fail/SAC-pass trajectory:
    `lab/results/hpt_dcsafe_12family_reduced2x2_20260801_r1_t2_a_lvrt/figures/t2_a_lvrt_pu0900_d100ms/`.
- Representative case interpretation:
  - `topology2 A-phase LVRT 0.90 pu / 100 ms`:
    - strong dq fails `grid_current_limit`;
    - dq-seeded actor passes;
    - SAC after fine-tune passes and slightly lowers peak grid current relative
      to the seed, although its score is slightly worse than the seed.
- Interpretation:
  - The reduced matrix supports the claim that case-specialist learned actors
    expand voltage-survival coverage over strong dq (`40/48` vs `24/48`).
  - The result does not support claiming that SAC universally improves pass
    count over the dq-seeded initial actor, because both are `40/48`.
  - SAC contribution is currently strongest as support-constrained,
    DC-safe fine-tuning and action shaping; stronger family-level SAC gains
    require harder topology1 ranges and a better promotion objective for cases
    where the seed already passes.

## 2026-08-01 - Post-run audit found overclaim risks

- Scope:
  - Audited the completed 3x3, 12-family center, and 12-family reduced 2x2
    evidence for statistical, implementation, and claim-support consistency.
  - Report:
    `lab/results/hpt_dcsafe_12family_reduced2x2_20260801_r1/POSTRUN_DATA_AUDIT.md`.
- Issues found:
  - Raw child CSVs from existing runs contain duplicate `strong_dq` rows
    because the evaluator outputs conventional dq during both seed and SAC
    evaluations.
  - The reduced summary was already corrected by deduplicating
    `boundary_label + controller`; future campaign code was fixed so the raw
    duplicate is no longer written.
  - Matrix cells currently train separate case-specific actors.  Therefore the
    current matrices should not be presented as one family actor covering all
    depth-duration cells.
  - The current staged `voltage_survival_pass` includes `grid_current_limit`
    because `hpt_compare_voltage_survival_current_gate=true`; reports should
    call this "voltage-survival with current gate."
  - SAC fine-tune does not yet increase pass count over the dq-seeded actor on
    the 12-family reduced matrix (`40/48` vs `40/48`), though it improves score
    on `27/48` rows and beats strong dq on `17/48` pass/fail rows.
- Fixes applied:
  - `run_hpt_t2_balanced_lvrt_dq_seeded_boundary.py` now skips the repeated
    strong dq row when merging SAC-fine-tune evaluator output.
  - `eval_hpt_v2_control_comparison.m` comments now reflect the current-gated
    staged survival gate.
  - Existing summaries were edited to avoid claiming a single family actor
    boundary.
- Next action:
  - Build the true family-specialist experiment: one actor per family trained
    over a multi-case matrix, then validated on held-out depth-duration cells.

## 2026-08-01 - True one-actor-per-family campaign smoke and pilot

- Scope:
  - Repaired the matrix design risk where each depth-duration cell had its own
    case-specific actor.
  - Added `sac/campaigns/run_hpt_family_specialist_matrix.py` as the
    canonical family-specialist campaign entry point.
- Method change:
  - The new campaign collects strong-dq switch-level traces for all training
    cases in a family and merges them into one `family_anchor.npz`.
  - It trains one `family_seed_before_sac` actor for the entire family.
  - It optionally fine-tunes one `family_sac_after_finetune` actor.
  - The same exported actor is then evaluated across the whole matrix.  Rows
    for `strong_dq` intentionally have no actor file attached.
- Validation:
  - Python compile passed:
    `py -3 -m py_compile sac\campaigns\run_hpt_family_specialist_matrix.py`.
  - Smoke run:
    `hpt_family_specialist_smoke_t2_a_lvrt_20260801_r1`.
    Result: one topology2 A-phase LVRT point; seed and SAC both passed while
    strong dq failed the current gate.
  - 2x2 pilot run:
    `hpt_family_specialist_t2_a_lvrt_2x2_20260801_r1`.
    Family: `topology2`, `A-phase`, `LVRT`.
    Train/eval matrix: `0.875/0.90 pu x 60/100 ms`.
- 2x2 pilot switch-level result:
  - strong dq: `0/4`, failed by `grid_current_limit`.
  - one family seed actor: `4/4` voltage-survival with current gate.
  - one family SAC actor: `4/4` voltage-survival with current gate.
  - SAC score beat strong dq on `4/4` rows and beat the seed actor on `4/4`
    rows.
  - CSV audit confirmed `family_seed_before_sac` has one actor model across
    all four rows and `family_sac_after_finetune` has one actor model across
    all four rows.
- Evidence:
  - Summary:
    `lab/results/hpt_family_specialist_t2_a_lvrt_2x2_20260801_r1/FAMILY_SPECIALIST_SUMMARY.md`.
  - CSV:
    `lab/results/hpt_family_specialist_t2_a_lvrt_2x2_20260801_r1/family_specialist_comparison_rows.csv`.
  - Campaign summary:
    `lab/results/hpt_family_specialist_t2_a_lvrt_2x2_20260801_r1/campaign_summary.json`.
- Interpretation:
  - This fixes the specific overclaim raised by the user for this pilot family:
    the matrix cells are no longer separate case-specific actors.
  - The result is still a small same-matrix pilot, not a full 12-family claim.
    The next step should add held-out family cells, then repeat the campaign
    for the other 11 families.

## 2026-08-01 - Topology2 A-phase LVRT true family 5x5 matrix completed

- Scope:
  - Ran the first full 5x5 one-actor-per-family evidence matrix after the
    case-specific actor audit.
  - Family: `topology2`, `A-phase`, `LVRT`.
  - Matrix: `0.85/0.875/0.90/0.925/0.95 pu x 40/60/80/100/120 ms`.
  - Run id: `hpt_family_specialist_t2_a_lvrt_5x5_20260801_r1`.
- Reproducibility:
  - The campaign command is stored in
    `lab/results/hpt_family_specialist_t2_a_lvrt_5x5_20260801_r1/campaign_metadata.json`.
  - The merged family anchor contains `25,575` samples from 25 strong-dq
    switch-level traces.
  - CSV audit confirms all `family_seed_before_sac` rows use one seed actor,
    and all `family_sac_after_finetune` rows use one SAC actor.
- Switch-level result:
  - strong dq: `0/25` voltage-survival with current gate.
  - family seed actor: `25/25`.
  - family SAC actor: `25/25`.
  - SAC score beat strong dq on `23/25` cells.
  - SAC score beat the seed actor on `15/25` cells.
- Diagnosis:
  - strong dq failed because the grid-current peak was `1.540 pu`, above the
    current gate; its sampled LV fault/recovery/envelope metrics were otherwise
    zero-violation.
  - The learned family actors reduced the grid-current peak to about
    `1.466-1.469 pu`, so they passed every cell.
  - This matrix does not reveal a depth-duration pass/fail boundary because
    the learned seed actor is already feasible on all 25 cells.
- Evidence:
  - Main summary:
    `lab/results/hpt_family_specialist_t2_a_lvrt_5x5_20260801_r1/FAMILY_SPECIALIST_SUMMARY.md`.
  - Analysis:
    `lab/results/hpt_family_specialist_t2_a_lvrt_5x5_20260801_r1/FAMILY_5X5_ANALYSIS.md`.
  - CSV:
    `lab/results/hpt_family_specialist_t2_a_lvrt_5x5_20260801_r1/family_specialist_comparison_rows.csv`.
- Interpretation:
  - The one-family actor requirement is now satisfied for this pilot family.
  - The result supports a current-limited voltage-survival improvement over
    strong dq, but not the stronger claim that SAC moved a monotonic pass/fail
    boundary toward deeper or longer faults.
  - Next evidence should use a harder holdout matrix such as
    `0.75/0.80/0.825/0.85/0.875 pu x 80/120/160/200 ms`, or train on the
    current 5x5 core and validate on harder cells.

## 2026-08-01 - Representative family actor trace figure generated

- Scope:
  - Generated a representative waveform/action trace for a cell where
    `strong_dq` fails and `family_sac_after_finetune` passes in the true
    topology2 A-phase LVRT family matrix.
- Case:
  - `topology2 A-phase LVRT 0.85 pu / 120 ms`.
  - Source run:
    `hpt_family_specialist_t2_a_lvrt_5x5_20260801_r1`.
- Code update:
  - `sac/summaries/plot_hpt_dqseed_case_evidence.py` now supports
    family-specialist campaign summaries in addition to older case-specific
    campaign summaries.
- Figures:
  - Action commands:
    `lab/results/hpt_family_specialist_t2_a_lvrt_5x5_20260801_r1/figures/t2_a_lvrt_pu0850_d120ms/t2_a_lvrt_pu0850_d120ms_action_trace_comparison.png`.
  - Switch-level LV/Vdc traces:
    `lab/results/hpt_family_specialist_t2_a_lvrt_5x5_20260801_r1/figures/t2_a_lvrt_pu0850_d120ms/t2_a_lvrt_pu0850_d120ms_voltage_vdc_trace_comparison.png`.
  - SAC reward convergence:
    `lab/results/hpt_family_specialist_t2_a_lvrt_5x5_20260801_r1/figures/t2_a_lvrt_pu0850_d120ms/t2_a_lvrt_pu0850_d120ms_sac_reward_convergence.png`.
- Interpretation:
  - strong dq produces larger oscillatory regulating commands and fails the
    current-gated voltage-survival metric.
  - The learned family actors use smoother regulating commands and small
    energy-branch corrections, while maintaining LV RMS and Vdc inside the
    staged survival bands.

## 2026-08-01 - Same-family-actor hard holdout boundary found

- Scope:
  - Reused the same topology2 A-phase LVRT family SAC actor from
    `hpt_family_specialist_t2_a_lvrt_5x5_20260801_r1`.
  - No retraining or new teacher collection was performed.
  - Evaluated a harder holdout matrix to locate the boundary of the same actor.
- Run:
  - Run id: `hpt_family_specialist_t2_a_lvrt_hardholdout_20260801_r1`.
  - Matrix:
    `0.75/0.80/0.825/0.85/0.875 pu x 80/120/160/200 ms`.
- Result:
  - strong dq: `0/20`.
  - same family SAC actor: `17/20`.
  - SAC score beats strong dq on `17/20`.
  - SAC grid-current peak max: about `1.469 pu`.
  - strong dq grid-current peak max: about `1.540 pu`.
- Boundary:
  - SAC passes:
    - all tested cells at `0.825/0.85/0.875 pu`;
    - `0.80 pu` up to `160 ms`;
    - `0.75 pu` up to `120 ms`.
  - SAC fails:
    - `0.75 pu / 160 ms`;
    - `0.75 pu / 200 ms`;
    - `0.80 pu / 200 ms`.
- Failure mode:
  - All SAC failures are `dc_link_bounds`.
  - LV fault-window envelope and recovery envelope remain satisfied.
- Evidence:
  - Analysis:
    `lab/results/hpt_family_specialist_t2_a_lvrt_hardholdout_20260801_r1/HARD_HOLDOUT_BOUNDARY_ANALYSIS.md`.
  - Pass matrix figure:
    `lab/results/hpt_family_specialist_t2_a_lvrt_hardholdout_20260801_r1/hard_holdout_pass_matrix.png`.
- Interpretation:
  - This is the clearest boundary result so far: the same family actor has a
    physically interpretable pass/fail frontier, and the frontier is limited by
    DC-link energy depletion under deep/long LVRT.
  - Next improvement target is energy-head/DC-link control for the three failed
    cells, not LV voltage tracking.

## 2026-08-01 - Current-window grid-current gate repaired and boundary rechecked

- Scope:
  - Audited why `grid_current_limit` and current-gated voltage-survival were
    failing all traditional dq cells.
  - Found that the evaluator used the global full-waveform instantaneous peak:
    `max(abs(Igrid_abc)) / iBasePeak`.
  - Across the previous topology2 A-phase LVRT matrices, strong dq had a
    constant global peak of `1.539962 pu`, causing all cells to fail despite
    zero LV envelope/recovery violations.
- Code update:
  - Updated `simulink/evaluators/eval_hpt_v2_control_comparison.m`.
  - Updated `simulink/evaluators/eval_hpt_v2_sac_single_case.m`.
  - Added separate current diagnostics:
    `grid_current_peak_global_pu`, `grid_current_peak_fault_pu`,
    `grid_current_peak_recovery_pu`, `grid_current_eval_start_s`, and
    `grid_current_limit_pu`.
  - `grid_current_peak_pu` now means the current-gate evaluation-window peak
    from fault start + 20 ms to the end of simulation.  The global peak remains
    diagnostic only.
- Recheck 1:
  - Run id:
    `hpt_family_specialist_t2_a_lvrt_hardholdout_currentwindow_20260801_r1`.
  - Matrix:
    `0.75/0.80/0.825/0.85/0.875 pu x 80/120/160/200 ms`.
  - Result:
    strong dq `20/20`, family seed `17/20`, family SAC `17/20`.
  - Interpretation:
    the old `strong dq = 0/20` result was a current-window artifact.  This
    moderate holdout is too easy for strong dq under the corrected gate.
- Recheck 2:
  - Run id:
    `hpt_family_specialist_t2_a_lvrt_deep_probe_currentwindow_20260801_r1`.
  - Matrix:
    `0.20/0.50/0.65 pu x 120/200/300 ms`.
  - Result:
    strong dq `4/9`, family seed `0/9`, family SAC `0/9`.
  - Failure mode:
    strong dq fails deep/long cells by DC-link/recovery/fault-band limits, not
    current limit; the existing SAC family actor fails mainly by
    `dc_link_bounds`.
- Evidence:
  - Detailed report:
    `lab/results/hpt_family_specialist_t2_a_lvrt_deep_probe_currentwindow_20260801_r1/CURRENT_WINDOW_BOUNDARY_ANALYSIS.md`.
- Interpretation:
  - Current-aware voltage-survival boundary claims must use the corrected
    current-window evaluator.
  - The next SAC target is a deep-LVRT topology2 A-phase family specialist with
    stronger energy-head/DC-link reward; the previous 0.85-0.95 pu family actor
    does not extrapolate to 0.20-0.65 pu deep LVRT.

## 2026-08-01 - Corrected-current-window DQ/SAC boundary matrix generated

- Scope:
  - Generated a consolidated depth-duration boundary for topology2 A-phase
    LVRT using the repaired current-window evaluator.
  - Reused the same family seed/SAC actors from
    `hpt_family_specialist_t2_a_lvrt_5x5_20260801_r1`; no retraining was done.
- Additional focus run:
  - Run id:
    `hpt_family_specialist_t2_a_lvrt_focus_boundary_currentwindow_20260801_r1`.
  - Matrix:
    `0.50/0.575/0.65/0.70/0.75 pu x 120/160/200/240/300 ms`.
  - Result:
    strong dq `19/25`, family seed `1/25`, family SAC `1/25`.
- Consolidated matrix:
  - Combined corrected-current-window runs:
    - `hpt_family_specialist_t2_a_lvrt_hardholdout_currentwindow_20260801_r1`
    - `hpt_family_specialist_t2_a_lvrt_deep_probe_currentwindow_20260801_r1`
    - `hpt_family_specialist_t2_a_lvrt_focus_boundary_currentwindow_20260801_r1`
  - Total known cells: 45.
  - strong dq: `36/45`.
  - family seed before SAC: `17/45`.
  - family SAC after fine-tune: `17/45`.
  - All controllers passed the corrected grid-current gate on all known cells;
    failures are dominated by DC-link and recovery/fault-band constraints.
- Artifacts:
  - Summary report:
    `lab/results/hpt_family_specialist_t2_a_lvrt_focus_boundary_currentwindow_20260801_r1/BOUNDARY_RESULT_REPORT.md`.
  - Pass/fail matrix:
    `lab/results/hpt_family_specialist_t2_a_lvrt_focus_boundary_currentwindow_20260801_r1/boundary_summary/t2_a_lvrt_currentwindow_pass_matrix.png`.
  - Score matrix:
    `lab/results/hpt_family_specialist_t2_a_lvrt_focus_boundary_currentwindow_20260801_r1/boundary_summary/t2_a_lvrt_currentwindow_score_matrix.png`.
  - Combined CSV:
    `lab/results/hpt_family_specialist_t2_a_lvrt_focus_boundary_currentwindow_20260801_r1/boundary_summary/t2_a_lvrt_currentwindow_combined_cells.csv`.
- Interpretation:
  - The current shallow-family SAC actor does not beat strong dq on the
    corrected boundary.  Its pass region is smaller and limited by
    `dc_link_bounds`.
  - The next paper-relevant step is a new deep-LVRT family SAC specialist,
    centered on `0.50-0.65 pu`, with stronger energy-head/DC-link survival
    optimization.

## 2026-08-02 - Corrected-current-window matrix completed with no missing cells

- Scope:
  - Completed the topology2 A-phase LVRT corrected-current-window
    voltage-survival boundary matrix.
  - Filled the 15 cells that were gray/missing in the previous 45-cell combined
    plot.
  - Reused the same family seed/SAC actors from
    `hpt_family_specialist_t2_a_lvrt_5x5_20260801_r1`; no per-cell actor was
    trained or selected.
- New eval-only runs:
  - `hpt_family_specialist_t2_a_lvrt_squarefill_deep020_currentwindow_20260802_r1`
    for `0.20 pu x 80/160/240 ms`.
  - `hpt_family_specialist_t2_a_lvrt_squarefill_short080_currentwindow_20260802_r1`
    for `0.50/0.575/0.65/0.70 pu x 80 ms`.
  - `hpt_family_specialist_t2_a_lvrt_squarefill_shallowlong_currentwindow_20260802_r1`
    for `0.80/0.825/0.85/0.875 pu x 240/300 ms`.
- Complete matrix:
  - Depths:
    `0.20/0.50/0.575/0.65/0.70/0.75/0.80/0.825/0.85/0.875 pu`.
  - Durations:
    `80/120/160/200/240/300 ms`.
  - Total: `60` cells per controller.
- Result:
  - strong dq: `48/60`, current pass `60/60`, Vdc pass `48/60`,
    mean score `123.600`.
  - family seed before SAC: `23/60`, current pass `60/60`, Vdc pass `29/60`,
    mean score `125.338`.
  - family SAC after fine-tune: `23/60`, current pass `60/60`, Vdc pass
    `28/60`, mean score `127.318`.
- Artifacts:
  - Report:
    `lab/results/hpt_family_specialist_t2_a_lvrt_square_currentwindow_20260802_r1/BOUNDARY_SQUARE_RESULT_REPORT.md`.
  - Square-cell matrix:
    `lab/results/hpt_family_specialist_t2_a_lvrt_square_currentwindow_20260802_r1/boundary_summary/t2_a_lvrt_square_currentwindow_pass_matrix_square_cells.png`.
  - Combined CSV:
    `lab/results/hpt_family_specialist_t2_a_lvrt_square_currentwindow_20260802_r1/boundary_summary/t2_a_lvrt_square_currentwindow_combined_cells.csv`.
- Interpretation:
  - The completed matrix removes the gray-cell ambiguity from the previous
    boundary figure.
  - Current-window grid current is not the active limitation: all controllers
    pass the current gate in all evaluated cells.
  - The current shallow-family SAC actor still does not beat strong dq.  Its
    failures remain dominated by `dc_link_bounds`.
  - Next work should train a new deep-LVRT, energy-aware family SAC specialist
    instead of continuing to tune the shallow `0.85-0.95 pu` family actor.

## 2026-08-02 - DQ-fail-focused deep LVRT matrix sampled

- Scope:
  - Expanded the topology2 A-phase LVRT corrected-current-window matrix into
    the region where the strong dq baseline begins to fail.
  - Purpose is to identify a useful target region for a new deep-LVRT,
    energy-aware SAC specialist.
- Run:
  - `hpt_family_specialist_t2_a_lvrt_dqfail_expanded_currentwindow_20260802_r1`.
- Matrix:
  - Depths:
    `0.30/0.40/0.45/0.50/0.55/0.60/0.625 pu`.
  - Durations:
    `160/200/240/300/360 ms`.
  - Total: `35` cells per controller.
- Result:
  - strong dq: `6/35`, current pass `35/35`, Vdc pass `19/35`,
    recovery pass `18/35`, mean score `137.862`.
  - family seed before SAC: `0/35`, current pass `35/35`, Vdc pass `0/35`,
    recovery pass `35/35`, mean score `143.884`.
  - family SAC after fine-tune: `0/35`, current pass `35/35`, Vdc pass
    `0/35`, recovery pass `32/35`, mean score `146.762`.
- Artifacts:
  - Report:
    `lab/results/hpt_family_specialist_t2_a_lvrt_dqfail_expanded_currentwindow_20260802_r1/DQ_FAIL_EXPANDED_MATRIX_REPORT.md`.
  - Pass matrix:
    `lab/results/hpt_family_specialist_t2_a_lvrt_dqfail_expanded_currentwindow_20260802_r1/boundary_summary/t2_a_lvrt_dqfail_expanded_currentwindow_pass_matrix.png`.
  - Combined CSV:
    `lab/results/hpt_family_specialist_t2_a_lvrt_dqfail_expanded_currentwindow_20260802_r1/boundary_summary/t2_a_lvrt_dqfail_expanded_currentwindow_combined_cells.csv`.
- Interpretation:
  - This expanded region is appropriate for the next SAC target because dq has
    a clear fail boundary while the current shallow-family SAC fails all cells.
  - All controllers pass the corrected current-window gate; the active
    limitation is DC-link survival.
  - The next step should collect deep-LVRT energy-branch response data and
    train a new split-head, energy-aware SAC rather than reusing the shallow
    family actor.

## 2026-08-03 - One topology2 A-phase deep-LVRT family SAC expanded the dq boundary

- Scope:
  - Trained and verified one state-feedback SAC actor for the complete
    `0.500/0.600/0.625 pu x 160/200/240 ms` family matrix.
  - The same checkpoint was used in all nine cells.  No per-case actor,
    runtime selector, or per-cell checkpoint was used.
- Switch-level support collection:
  - Joint `m_reg_d` / `m_energy_q` sweep:
    `hpt_t2_a_lvrt_joint_support_switch_20260803_r1`.
  - `12/18` fixed-action samples passed voltage survival; the action region
    near `[m_reg_d,m_reg_q,m_energy_d,m_energy_q] = [0.06,0,0,0.60]`
    passed all three representative boundary cases.
  - Energy-d zero-neighborhood sweep:
    `hpt_t2_a_lvrt_energyd_zero_neighborhood_switch_20260803_r1`.
    All `12/12` samples passed, indicating that the earlier lost `0.600 pu`
    cells were dominated by insufficient regulation command rather than the
    sign of a small energy-d command.
- Proxy/reward calibration:
  - Family calibration:
    `lab/results/hpt_t2_a_lvrt_deep_family_proxy_matrix_20260803/hpt_proxy_calibration_t2_a_deep_lvrt_joint_support_r2.json`.
  - Calibration SHA-256:
    `94f225d8937f3795b2dcdd93ea02f63fdcd603597263d6e4217bf02bb858a8e3`.
  - Measured-support reward alignment: Spearman `rho=1.0`, Kendall
    `tau=1.0`, top-3 overlap `3/3`.  This is an in-support alignment check,
    not a holdout-generalization claim.
- Implementation defect fixed:
  - SB3 actor outputs in normalized `[-1,1]` space were previously compared
    directly with physical-action support targets.
  - Physical support actions are now mapped to normalized actor space before
    the support loss is evaluated.
  - Regression coverage is in `tests/test_hpt_sac_action_scaling.py`.
- Final actor:
  - Checkpoint:
    `data/models/hpt_t2_a_lvrt_joint_support_family_sac_r6_20260803.zip`.
  - SHA-256:
    `44dadac630f30d72555ae5ed363301296ac6b1ed2cd6201bfb1043ae1299cde5`.
  - Training used one nine-scenario family, a four-dimensional split-head
    action, `6000` SAC steps, and an in-update support regularizer.  No
    post-training BC projection was applied.
- Final switch-level matrix:
  - Run:
    `hpt_family_specialist_t2_a_lvrt_joint_support_sac_r6_probe9_20260803`.
  - SAC voltage-survival pass: `8/9`; strong dq: `4/9`.
  - DQ-fail/SAC-pass cells: `4/9`:
    `0.500 pu / 200 ms`, `0.500 pu / 240 ms`,
    `0.625 pu / 160 ms`, and `0.625 pu / 200 ms`.
  - SAC score was lower than dq in `9/9` cells; envelope, recovery, and
    corrected grid-current diagnostics passed in `9/9` cells.
  - The retained failure is `0.625 pu / 240 ms`, where the active `650 V`
    DC-link floor is violated (`Vdc_min=626.49 V`). Because the deeper
    `0.500 pu / 240 ms` case passes, this is a non-monotonic DC-link failure,
    not a monotonic depth-duration outer boundary.
- Evidence:
  - Report:
    `lab/results/hpt_family_specialist_t2_a_lvrt_joint_support_sac_r6_probe9_20260803/BOUNDARY_EXPANSION_REPORT.md`.
  - Per-cell CSV SHA-256:
    `d0a23a2a448621d4330a2f474190a2d87bbef0a5093a024c139e582713ff7fc8`.
  - Training reward and diagnostics:
    `lab/results/hpt_t2_a_lvrt_joint_support_family_sac_r6_20260803/`.
- Interpretation:
  - This closes the current family-level boundary-expansion objective: one
    family actor beats strong dq on switch-level voltage survival and expands
    four boundary cells.
  - The claim remains limited to topology2 A-phase deep LVRT and does not
    establish full FRT certification or transfer to the other eleven fault
    families.

## 2026-08-03 - Final r6 boundary, convergence, and raw control-trace figures

- Scope:
  - Synchronized the final family-SAC boundary and convergence figures into
    the paper figure package.
  - Exported a new raw switch-level conventional-dq versus family-SAC-r6 trace
    for the `topology2 A-phase LVRT 0.50 pu / 200 ms` boundary cell.
  - This cell is intentionally selected because strong dq fails and the same
    family SAC r6 checkpoint used across the matrix passes.
- Simulink trace export:
  - Reproducible MATLAB runner:
    `paper/figures/simulink_control_traces/run_t2_a_deep_lvrt_r6_traces.m`.
  - Strong-dq trace:
    `lab/results/hpt_v2_trajectory_traces/trajectory_trace_topology2_r6_boundary_pu0500_d200ms_strong_dq_20260803_091954.csv`.
  - Family-SAC-r6 trace:
    `lab/results/hpt_v2_trajectory_traces/trajectory_trace_topology2_r6_boundary_pu0500_d200ms_family_sac_20260803_092010.csv`.
  - Both traces are exported from the switch-level Simulink model at a 2-ms
    control-step stride using the same case and model parameters.
- Paper outputs:
  - `paper/figures/fig11_t2_a_deep_lvrt_family_boundary_r6.{png,pdf}`.
  - `paper/figures/fig12_t2_a_deep_lvrt_family_sac_convergence_r6.{png,pdf}`.
  - `paper/figures/fig13_t2_a_deep_lvrt_r6_control_trace.{png,pdf}`.
  - Fig. 13 overlays LV RMS, Vdc, and all four modulation commands for strong
    dq and family SAC r6.  It is based on raw traces, not summary-row waveform
    reconstruction.
- Key trace result:
  - Strong dq minimum DC-link voltage: `552.07 V`, below the active `650 V`
    floor.
  - Family SAC r6 minimum DC-link voltage: `670.19 V`, above the active floor.
  - The SAC energy head maintains `m_energy_q` near `0.60`, while the strong
    dq profile leaves both energy-bridge commands at zero.
- Reproducibility:
  - Figure generator:
    `paper/figures/simulink_control_traces/make_t2_a_deep_lvrt_r6_evidence.py`.
  - Source paths, SHA-256 hashes, outputs, and trace metrics:
    `paper/figures/simulink_control_traces/fig_t2_a_deep_lvrt_r6_evidence_manifest.json`.

## 2026-08-03 - SAC continuation audit, numerical fixes, and failed r7-r9 promotions

- Scope:
  - Audited the accepted topology2 A-phase deep-LVRT r6 result, its paper
    figures, reward trace, and three continuation candidates.
  - Kept the switch-level `0.500/0.600/0.625 pu x 160/200/240 ms` matrix as
    the only promotion gate.
- Confirmed evidence:
  - r6 remains valid at `8/9` voltage-survival passes versus strong dq `4/9`.
  - The same r6 checkpoint is used in all nine cells; no per-cell actor or
    runtime selector is used.
  - Paper Figs. 11-13 remain synchronized with r6.  The training figure is
    explicitly diagnostic and does not claim monotonic proxy convergence.
- Reporting defects fixed:
  - `vdc_pass_count` now evaluates the active `650-1000 V` gate directly.
  - The looser `gbt_vdc_survive_pass_count` remains a separate diagnostic.
  - Historical r6/r7 summaries were rebuilt from the original per-case CSVs.
    Correct active Vdc counts are r6 `8/9` and r7 `6/9`.
  - Eval-only family reports no longer display default depths/durations as if
    they were a training matrix.
  - Windows runner/MATLAB artifact names are bounded and hash-compacted to
    avoid path-length failures.
- SAC numerical/debug changes:
  - Added `reward_scale` while retaining `reward_unscaled` in environment
    diagnostics.
  - Added actor-only initialization so a validated actor can be paired with a
    fresh critic, target critic, entropy state, and replay buffer.
  - Added critic-only warm-up updates before actor optimization.  Regression
    tests verify that the actor is bitwise unchanged while the critic updates.
  - Added actor-update/warm-up fields to the training diagnostic trace.
- Continuation results:
  - r7, scaled reward plus weak support: `6/9`; not promoted.
  - r8, scaled reward plus medium support: `2/9`; not promoted.
  - r9, medium support plus 1000 critic-only warm-up updates: `4/9`; not
    promoted.
  - r9 reduces actor drift relative to r8, but still lowers the family
    `m_reg_d` trajectory enough for five cells to violate the active DC-link
    floor.
- Root-cause finding:
  - Proxy return ranks r8 and r9 above r6, but switch-level pass count ranks
    them below r6.
  - The proxy reports nearly identical episode minimum Vdc for these policies,
    while switch-level Vdc minima change by tens of volts after small trajectory
    action changes.  Fixed-action calibration is therefore insufficient for
    policy-rollout DC-link ranking near the hard gate.
- Decision:
  - r6 remains the accepted actor.
  - r7-r9 are retained as diagnostic failed evidence and have explicit
    `promotion_status.json` files.
  - Stop blind proxy-only hyperparameter sweeps.  Next work must collect local
    trajectory-level switch transitions or use short SAC chunks with immediate
    switch-level checkpoint promotion.
- Tests:
  - `py -3 -m pytest -q tests/test_hpt_sac_critic_warmup.py tests/test_hpt_sac_reward_scaling.py tests/test_hpt_sac_action_scaling.py tests/test_hpt_campaign_artifact_paths.py tests/test_hpt_family_specialist_summary.py tests/test_hpt_family_proxy_support.py`
  - Result: `10 passed`.
- Consolidated report:
  - `lab/results/hpt_t2a_proxy_sac_debug_20260803/REPORT.md`.

## 2026-08-03 - Fresh current-r6 topology2 A-phase LVRT 10x6 matrix

- Scope:
  - Re-ran the historical 10-depth by 6-duration topology2 A-phase LVRT grid
    with the unchanged accepted r6 checkpoint and the corrected current-window
    voltage-survival evaluator.
  - Evaluated `0.20/0.50/0.575/0.65/0.70/0.75/0.80/0.825/0.85/0.875 pu`
    by `80/120/160/200/240/300 ms`.
  - Every SAC cell uses the same r6 actor; no per-cell checkpoint or action
    profile is used.
- Frozen actor:
  - `data/models/hpt_t2_a_lvrt_joint_support_family_sac_r6_20260803.zip`.
  - SHA-256:
    `44dadac630f30d72555ae5ed363301296ac6b1ed2cd6201bfb1043ae1299cde5`.
- Fresh switch-level result:
  - r6 voltage-survival: `46/60`; strong dq: `48/60`.
  - Both pass: `43`; dq-fail/r6-pass: `3`; dq-pass/r6-fail: `5`;
    both fail: `9`.
  - r6 score is lower in `45/60` cells and mean score improves from `123.600`
    to `115.571`.
  - r6 recovery, corrected-current, and timestep-envelope diagnostics pass in
    `60/60`; remaining r6 failures are six fault-band cells at `0.20 pu` and
    eight active DC-link-floor cells.
- Interpretation:
  - r6 creates three valid local boundary-expansion cells, including
    `0.500 pu / 200-240 ms` and `0.575 pu / 300 ms`.
  - It does not expand the total historical 10x6 pass area because its
    `46/60` total is below dq's `48/60`.  Retain the accepted targeted 3x3
    claim and do not promote r6 as a global 10x6 actor.
  - The coverage matrix is non-monotonic in duration because DC-link minima
    depend on the state-feedback trajectory and fault-clearing instant; it is
    not a certified monotonic withstand curve.
- Evidence:
  - Run:
    `lab/results/hpt_family_specialist_t2_a_lvrt_r6_square60_currentwindow_20260803_r1`.
  - Report: `R6_SQUARE60_RESULT_REPORT.md`.
  - Comparison CSV SHA-256:
    `b227804bbe3897b7964edb2914438188bf5d8cb1ab2aa9edd110b81669adb482`.
  - Fresh pass and shared-scale score figures are under `boundary_summary/`.

## 2026-08-03 - Workspace preservation snapshot

- Audited the accumulated dirty workspace before result consolidation.
- Staged source code, tests, MATLAB/Simulink models, reorganized SAC and
  Simulink entry points, experiment manifests, paper artifacts, figures,
  literature, and research documentation.
- Force-included the accepted topology2 A-phase deep-LVRT r6 actor and its
  compact fresh 10-by-6 switch-level evidence package.
- Recorded the preservation scope and large local evidence inventory in
  `docs/autonomy/snapshots/2026-08-03-workspace-snapshot.md`.
- Kept approximately 15.8 GB of bulk `data/` and `lab/results/` payloads out
  of ordinary Git; these remain local and require a dedicated artifact store
  for a complete remote raw-data backup.
- Verification: six focused HPT SAC regression modules completed with
  `10 passed`.

## 2026-08-03 - Active-family codebase cleanup

- Removed obsolete executable methods and compatibility wrappers from
  `sac`, plus redundant Simulink teacher collectors, raw smoke tools,
  and source-tree actor archives.
- Preserved all compact experiment manifests, paper evidence, accepted/rejected
  result directories, and Git history so negative results remain auditable.
- Migrated the active action-trajectory utility into the `datasets` package and
  updated maintained imports.
- Rewrote root, SAC, campaign, calibration, dataset, summary, and Simulink
  inventories around the one-actor-per-family SAC workflow.
- Marked the previous-generation `src/hpt_frt` and `lab/simulink` trees as
  reproducibility-only rather than mixing them into the version-2 mainline.

## 2026-08-03 - HPT research skill upgraded for MCP and evidence governance

- Revised `.codex/skills/hpt-research-agent/SKILL.md` around the maintained
  one-actor-per-family SAC workflow and the current r6 promotion boundary.
- Added `docs/autonomy/current_research_state.json` as the
  machine-readable promoted-state pointer. It records the accepted r6 actor,
  targeted `8/9` versus `4/9` family evidence, expanded `46/60` versus `48/60`
  evidence, known proxy trajectory-ranking limitation, and canonical paths.
- Enhanced `collect_project_snapshot.py` to validate promoted actor hashes,
  canonical paths, recent result folders, and current research-log headings.
- Added a MATLAB/Simulink tool-routing policy based on the official MathWorks
  MATLAB MCP Server and Agentic Toolkits. Official MCP detection confirmed
  MATLAB, Simulink, Simscape, and Simscape Electrical R2025a in this session.
- Added an evidence passport and seven-rung claim ladder adapted for HPT. The
  protocol explicitly separates proxy diagnostics, switch-level single-case,
  family, boundary, robustness, and full-FRT claims.
- Tightened experiment rules around untouched proxy holdout trajectories,
  reward/convergence recording, exact-checkpoint promotion, strong-dq
  comparison, negative-result retention, and full-FRT missing-signal handling.
- Validation: the Codex skill validator passed; the enhanced snapshot verified
  the promoted actor SHA-256 and all canonical paths; MATLAB Code Analyzer was
  exercised on the maintained switch-level evaluator and returned warnings but
  no execution-blocking analysis error.

## 2026-08-03 - Twelve expert workspaces made canonical

- Created `experts/registry.json` and twelve workspaces covering two
  topologies, LVRT/HVRT, and balanced/single-phase/two-phase fault families.
- Copied one representative checkpoint and compact center-case switch-level
  evidence into every workspace. The model manifests preserve source paths and
  SHA-256 hashes; they do not relabel historical BC/DAgger checkpoints as SAC.
- Moved the active topology2 single-phase deep-LVRT r6 evidence pointers to
  `experts/topology2_single_phase_lvrt`, including its training
  diagnostics, targeted 3-by-3 matrix, and expanded 10-by-6 matrix.
- Updated the family campaign, SAC trainer, Simulink trace collector, and
  switch-level evaluator so new family runs write to their expert workspace.
- Root `data/models` and `lab/results` are now legacy provenance stores rather
  than canonical output destinations. The twelve representative checkpoints
  are tracked through Git LFS; bulk run payloads remain ignored while compact
  descriptors, result indexes, and hashes are versioned.
## 2026-08-03 - Curated topology2 single-phase LVRT data lineage

- Consolidated the promoted r6 expert's useful legacy inputs under
  `experts/topology2_single_phase_lvrt/{data,proxy}`.
- Selected nine exact switch-level support traces, the final 25,647-sample
  support anchor, the r2 proxy calibration and all directly referenced source
  matrices, targeted/expanded validation tables, and the r5 predecessor
  checkpoint.
- Excluded superseded proxy revisions, unrelated probes, and failed candidates
  outside the promoted dependency chain. Source artifacts remain available as
  provenance; canonical copies are hash-indexed by `manifests/data_manifest.json`.
- Rebuilt the final support anchor from canonical traces: observations and
  actions matched the original arrays exactly. Loaded and stepped the
  canonical proxy calibration successfully.
- No persisted SAC replay buffer or untouched holdout dataset exists for this
  run. The 60-cell matrix remains expanded validation evidence and is not
  relabeled as holdout.
## 2026-08-03 - GB/T evaluator correction

- Implemented exact GB/T 19963.1-2021 PCC LVRT/HVRT breakpoints.
- Split PCC scenario validity from project-defined HPT load-voltage quality.
- Added `scenario_valid`, `remained_connected`, and L1/L2/L3 result fields.
- Added Python and MATLAB breakpoint regression tests.
- Disabled stale pre-v3 fault proxy tables pending fresh switch-level data.
- Marked the previous topology2 A-phase r6 promotion evidence stale; actor and
  historical artifacts remain intact for reproducibility.
## 2026-08-03 - v3 training-pipeline migration and archival

- Centralized scenario-valid and L1/L2/L3 semantics in `sac/gate_contract.py`.
- Restricted fault SAC training to the measurable L1 target and made stale or
  uncalibrated fault proxies a hard error by default.
- Updated family matrices, trajectory comparison, and conventional-dq tuning
  to exclude invalid PCC scenarios from controller pass/fail counts.
- Introduced the `tuned_v2_l1` baseline profile name. Its inherited parameters
  are a candidate only; a fresh v3 switch-level tuning matrix is still needed.
- Archived 482 pre-v3 data, proxy, checkpoint, result, and manifest files with
  SHA-256 provenance under `pre_gbt_v3_20260803` and cleared every active expert
  pointer. No controller remains promoted after this migration.

## 2026-08-03 - v3 topology2 conventional baseline smoke tuning

- Corrected the baseline tuner to read and write canonical
  `results` paths instead of the legacy `lab/results` tree.
- Evaluated fixed-plant topology2 dq/energy candidates with the current v3
  schema, valid-PCC filtering, current gate, and L1 ranking.
- Selected `t2_v3_l1_energy015_fixed_plant` as the `tuned_v2_l1` topology2
  parameter profile without modifying chopper resistance or threshold.
- The profile passed L1 for 0.90-pu/60-ms LVRT. It failed 1.10-pu/60-ms HVRT
  only on `dc_link_bounds` (Vdc peak about 1038 V), establishing a measured
  baseline boundary rather than hiding the failure.
- A diagnostic chopper-hardware variant passed both smoke cases, but it was
  not promoted because changing plant hardware only for the baseline would
  make later SAC comparisons unfair.
- Archived two pre-v3 MATLAB actor-performance scripts. Active MATLAB tests
  now cover the switch models, 24/4 interface, GB/T breakpoints, and PCC
  assessment channel; new controller performance must use the v3 evaluator.

## 2026-08-04 - topology2 single-phase LVRT v3 family baseline boundary

- Added phase-list support to the maintained family campaign and SAC trainer
  so one single-phase family actor can cover `a,b,c` instead of silently using
  one representative phase.
- Added a baseline-only family campaign for fresh `tuned_v2_l1`
  conventional-dq switch-level matrices.  It uses the v3 evaluator, stores
  rows under the corresponding expert workspace, and shortens MATLAB run
  labels to avoid Windows `MAX_PATH` failures.
- Ran a one-case topology2 A-phase LVRT smoke at `0.90 pu / 60 ms`; the v3
  schema was present and L1 passed.
- Ran a 27-case smoke matrix
  `A/B/C x {0.85,0.90,0.95} pu x {40,60,80} ms`; all 27 scenarios were valid
  and `tuned_v2_l1` passed L1 in every row.
- Ran the original 108-case shallow matrix
  `A/B/C x {0.825,0.85,0.875,0.90,0.925,0.95} pu x {40,60,80,100,120,160} ms`;
  all 108 rows passed L1, so this matrix is too mild to support a SAC-over-dq
  boundary-expansion claim.
- Ran an A-phase deep probe
  `{0.20,0.30,0.40,0.50,0.65,0.75,0.825} pu x {160,200,240,300,360} ms`;
  `tuned_v2_l1` passed only `1/35`, with failures dominated by `dc_link_bounds`
  and load-voltage/recovery envelope violations.
- Ran the corresponding A/B/C deep-family baseline matrix with 105 cases.
  `tuned_v2_l1` passed `4/105`; all scenarios were valid and all rows passed
  the post-inception grid-current gate.  This is the first fresh v3 matrix in
  this family with a useful conventional boundary.
- Built and fit a baseline-only family proxy seed from the 105-case matrix.
  Reward alignment is not sufficient for SAC promotion: the joint-sweep group
  is self-aligned by construction, while the conventional-dq group has weak
  ranking (`rho=0.323`, proxy top-1 rank `102/105`).  The next gate is
  fixed-action/trajectory action-response collection around the deep-boundary
  cases before any SAC training can be interpreted as meaningful.

## 2026-08-04 - topology2 single-phase LVRT fixed-action proxy72 and first SAC rejection

- Added a maintained fixed-action family sweep campaign for switch-level
  action-response data under the active expert workspace.  It preserves the
  four-command contract `[m_reg_d, m_reg_q, m_energy_d, m_energy_q]` and stores
  rows under `experts/topology2_single_phase_lvrt/data/action_response`.
- Collected fixed-action smoke, boundary, and q-axis action-response runs:
  `v3_t2sp_fixed_smoke_r1`, `v3_t2sp_fixed_boundary_r1`,
  `v3_t2sp_fixed_holdout_r1`, `v3_t2sp_fixed_q_holdout_r1`, and
  `v3_t2sp_fixed_q_holdout_r2`.  These are calibration/holdout evidence only;
  none of the fixed actions is promoted as a controller.
- Fixed reward-alignment diagnostics so joint-sweep ranking is evaluated inside
  each physical fault case instead of mixing A/B/C phases into one global
  ranking.  Also aligned the switch-level truth score with the current
  Simulink evaluator's `control_score`; the older Python heuristic now remains
  a fallback only.
- Refit `hpt_proxy_calibration_plus_fixed72.json` from the 105-case
  conventional boundary plus 72 fixed-action rows.  The untouched q-axis
  holdout `v3_t2sp_q_holdout_r2_plus_fixed72_model_v3` passed the local ranking
  gate for all three phase cases (`rho` about 0.738, 0.949, and 0.949).
- Trained one split-head family-level SAC candidate
  `v3_t2sp_l1_family_sac_proxy72_r1` on the supported local deep-boundary
  subset `A/B/C x {0.75,0.825} pu x {160,200} ms`.  Proxy-side reward traces
  improved substantially, but this is not switch-level evidence.
- Switch-level promotion check
  `v3_t2sp_l1_family_sac_proxy72_r1_switch12` rejected the candidate:
  `0/12` L1 pass for SAC versus `12/12` in the actor-evaluation inline
  strong-dq rows.  SAC failures were dominated by
  `timestep_recovery_envelope`; Vdc and current were mostly survivable.
- A comparison audit found that inline strong-dq rows produced during actor
  evaluation disagree with the standalone conventional boundary for the same
  nominal case (for example `t2_single_phase_lvrt_a_pu0750_d160ms`), especially
  in DC-link behavior.  The next gate is to make the dq baseline evaluation
  path identical before any SAC-over-dq boundary-expansion claim.

## 2026-08-04 - proxy 2.0 wording and Phase-A strong-dq boundary integration

- Updated the manuscript and version-2 architecture notes so the next proxy is
  described as a timestep-level transition proxy, not a whole-window average
  calibration table.
- Proxy 2.0 records local transition samples
  `(fault context, time, state, action) -> (next state, next LV/Vdc/grid-current/
  sequence metrics, violations)`.  SAC training should query/interpolate these
  transition samples at every control step and compute timestep reward from the
  resulting state update.
- The preferred data lineage is now strong-dq baseline trajectories, accepted
  expert trajectories, and small perturbations around those trajectories.
  Fixed-action sweeps are retained only as diagnostics or local gap filling,
  not as the main family-level SAC data source.
- Integrated the newly generated Phase-A filled strong-dq boundary evidence:
  `experts/topology2_single_phase_lvrt/results/combined_strong_dq_boundary_20260804/refined_rows/combined_strong_dq_family_rows_phase_a_filled.csv`.
  The analysis matrix in
  `analysis_matrix_phase_a_filled/` reports 290 cells, 160 L1-passing cells,
  and a deepest passing LVRT point of `0.5 pu` for the strong-dq baseline.
- Interpretation: the filled CSV is still a case/window-level summary table,
  useful for boundary selection and reporting.  It is not yet a proxy-2.0
  timestep transition dataset.  The next implementation step is to dereference
  each row's `source_csv` and extract per-control-step state/action/next-state
  samples for calibration, validation, and untouched holdout splits.

## 2026-08-04 - proxy2 trajectory smoke, DAgger repair, and SAC actor-update diagnostic

- Implemented proxy2 transition-data tooling for topology2 single-phase LVRT:
  `sac/datasets/collect_hpt_proxy2_transition_traces.py`,
  `sac/datasets/build_hpt_proxy2_dagger_anchor.py`, and
  `sac/calibration/proxy2_transition_pilot.py`.
- Collected a reduced Phase-A 4-case switch-level trajectory set
  `A x {0.825,0.900} pu x {60,120} ms`.  The aggregate transition data has
  504 timestep rows; the strong-dq BC anchor has 2944 state/action samples.
- Fitted a pilot timestep transition proxy.  One-step alignment was promising
  (`lv_pu_inst` RMSE about 0.016 and `vdc_pu_inst` RMSE about 0.0067), but
  autoregressive Vdc rollout remains diagnostic only.  This does not yet meet
  the proxy2 holdout-ranking gate.
- Pure BC from teacher-state traces failed the switch-level gate (`0/4`), showing
  closed-loop distribution shift.  Iterative DAgger-style anchors repaired the
  visited-state mismatch.  The DAgger4 actor passed the reduced 4-case
  switch-level matrix (`4/4`) while strong dq passed `3/4`.
- Ran a support-constrained SAC fine-tune initialized from DAgger4 with actor
  updates enabled after a critic warmup (`p2sacdiag4_actorupd_20260804`).  The
  training trace contains 78 reward episodes and the summary records
  `actor_update_enabled_fraction=1` through the actor-update path.
- Switch-level diagnostic check
  `experts/topology2_single_phase_lvrt/results/p2sacdiag4_actorupd_4case_chk_r1`
  passed `4/4` L1 cells versus strong dq `3/4`.  The SAC actor preserved the
  DAgger4 boundary expansion at `0.825 pu / 120 ms` and slightly improved the
  score at `0.900 pu / 120 ms`, but it did not beat strong dq in the easier
  `60 ms` cells.
- Classification: diagnostic, not promoted.  The SAC trainer still used the
  legacy averaged proxy path with `--allow-uncalibrated-fault-proxy`, so this is
  evidence that protected SAC updates can preserve switch-level feasibility in a
  reduced gate, not evidence for a final proxy2 family-level SAC claim.
