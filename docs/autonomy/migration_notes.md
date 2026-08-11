# Interface Migration Notes

## 2026-07-21 - FRT Matrix Fault-Band Envelope Fields

- Old interface:
  - `collect_hpt_v2_frt_calibration_matrix.m` emitted sampled GBT envelope
    and recovery-envelope metrics, but did not emit the explicit fault-window
    LV band metrics used by the 20260721 voltage-survival gate.
- New additive fields:
  - `fault_lv_min`
  - `fault_lv_max`
  - `fault_lv_band_violation_max_pu`
  - `fault_lv_band_violation_mean_pu`
  - `fault_lv_band_violation_duration_s`
  - `fault_lv_band_pass`
  - `trace_fault_lv_band_violation_pu` in stripped trace payloads.
- Function signature change:
  - Internal `run_fixed_case(...)` calls now pass `faultSettleS` explicitly
    instead of relying on a script-scope variable that is invisible inside
    MATLAB subfunctions.
- Compatibility:
  - Existing matrix readers still accept older CSVs for diagnostic purposes,
    but final proxy calibration and SAC training should use matrices that
    include `fault_lv_band_violation_max_pu`,
    `envelope_violation_max_pu`, and `recovery_violation_max_pu`.
- Validation:
  - `py -3 -m py_compile sac\calibration\calibrate_hpt_frt_proxy_from_matrix.py sac\hpt_voltage_sac_env.py sac\frt_envelope.py`
    passed.
  - `py -3 -m sac.smoke_matlab_engine --dry-run` passed.
  - Pilot matrix `frt_calibration_matrix_pilot_all_20260721_034530.csv`
    contains the three voltage-survival calibration fields and aligns with
    `hpt_proxy_calibration.json` on pilot support points.

## 2026-07-21 - Conventional DQ Baseline Tuning Knobs

- Old interface:
  - `hpt_conventional_reg_scale`
  - `hpt_conventional_energy_scale`
- New additive workspace variables:
  - `hpt_conventional_reg_scale_sag`
  - `hpt_conventional_reg_scale_swell`
  - `hpt_conventional_energy_scale_sag`
  - `hpt_conventional_energy_scale_swell`
  - `hpt_conventional_recovery_reg_gain`
  - `hpt_conventional_recovery_reg_max`
  - `hpt_conventional_recovery_hold_s`
- Compatibility:
  - Defaults are `1.0` for sag/swell scale multipliers and `0.0` for recovery
    damping/hold, so the generated Simulink models preserve previous
    conventional-dq behavior unless a sweep explicitly overrides the new
    parameters.
- Validation:
  - `py -3 -m sac.smoke_matlab_engine --runner batch --test interface
    --timeout-s 900` passed after the interface migration.
- Follow-up:
  - Keep all conventional-boundary reports tied to their run labels because
    Stage-2 claims depend on the exact baseline parameter profile.

## 2026-07-21 - Unbalanced Fault Source And Grid Negative-Sequence Observation

- Old interface:
  - Fault descriptors in `eval_hpt_v2_control_comparison.m` and the main FRT
    collector represented only balanced source amplitude changes:
    `{case_name, fault_pu}` or `{case_name, fault_pu, duration_s}`.
  - The Simulink `HPTSACController` observation vector reserved `obs_03` for
    grid negative-sequence voltage, but the grid-side implementation set
    `g_vneg = 0`.
- New additive fault descriptor:
  - `{case_name, fault_pu, duration_s, [puA puB puC]}`.
  - If the phase vector is omitted, the old balanced programmable-source path
    is preserved.
  - If the phase vector is present, the grid source is replaced by three
    controlled phase voltage sources driven by a common waveform block.
- New/additive result fields:
  - `fault_a_pu`, `fault_b_pu`, `fault_c_pu`
  - `grid_va_fault_pu`, `grid_vb_fault_pu`, `grid_vc_fault_pu`
  - `grid_vabc_unbalance_fault_pu`
  - `grid_vpos_seq_fault_pu`, `grid_vneg_seq_fault_pu`
  - trace fields `grid_vneg_seq_pu_inst` and
    `grid_vabc_unbalance_pu_inst` in the FRT calibration collector.
- Controller observation fix:
  - `add_hpt_sac_controller.m` now estimates grid positive/negative sequence
    using the same quarter-cycle delay method used for LV sequence estimation.
  - A topology1 A-phase LVRT trace smoke confirmed fault-window `obs_03`
    is nonzero and tracks the measured grid negative-sequence order of
    magnitude.
- Compatibility:
  - Existing balanced evaluator/collector calls remain valid.
  - New trajectory wrappers accept `--fault-phase-pu A B C`; old calls without
    that option keep the balanced source.

## 2026-07-21 - Reproducible Fault/Recovery Action Trajectory Preset

- Old workflow:
  - Some topology2 recovery-shaping teachers were generated as one-off MAT/CSV
    files, making it hard to reproduce the exact fault-support and recovery
    transition profile from a command.
- New additive preset:
  - `sac.build_hpt_action_trajectory --preset fault_recovery`
  - Interpretation:
    - `base-action`: pre-event command;
    - `start-action`: high fault-window command;
    - `action`: lower recovery command;
    - `ramp-start` to `step-time`: ramp from base to fault command;
    - `ramp-end` to `down-start`: ramp from fault command to recovery command.
- Compatibility:
  - Existing trajectory presets are unchanged.
  - Existing MAT trajectory files remain valid.
- Experiment caution:
  - Do not run multiple MATLAB evaluator/validator jobs in parallel when they
    write the same `lab/results/hpt_v2_control_comparison` filename pattern and
    the caller selects the newest file.  Use sequential validation or unique
    result-discovery logic before treating results as evidence.

## 2026-07-21 - Grid Sequence Observation Startup Normalization

- Old behavior:
  - `HPTSACController` normalized grid positive/negative sequence voltage using
    the ideal configured grid phase RMS.
  - In topology2 unbalanced controlled-source cases, the measured primary-side
    sequence seen by the controller could sit around `0.6-0.8 pu` even before
    or after the commanded event, so the internal fault state could become
    active before the actual fault and remain active during the evaluator
    recovery window.
- New behavior:
  - During startup, the controller estimates a local measured grid positive
    sequence baseline and normalizes `g_vpos/g_vneg` by that baseline.
  - Fault detection is blanked for the first `30 ms` to avoid sequence-buffer
    initialization artifacts.
  - Internal controller thresholds now use the startup-normalized grid
    sequence observation.
- Compatibility:
  - Observation dimension remains 24 and action dimension remains 4.
  - Actor weight file structure is unchanged, but old actors and unbalanced
    accepted-specialist rows are not semantically equivalent after this change.
  - Rerun unbalanced specialist validation before citing any prior unbalanced
    pass count.
- Stale evidence marker:
  - `sac/experiments/stale_specialists_after_gridnorm_20260721.csv`

## 2026-07-21 - Unbalanced Source/Observation Smoke Gate Rebuild

- Old behavior:
  - `smoke_hpt_v2_unbalanced_source.m` checked only fault-window phase ordering
    and negative-sequence presence at the grid measurement point.
  - In topology2, that measurement is affected by HPT/DC-link dynamics, so it
    could not cleanly distinguish source-command correctness from plant
    response.
  - The evaluator also used one final observation average, so pre-fault,
    fault-window, and recovery-window observation-state problems were hidden.
- New additive evaluator fields:
  - `source_va_*_pu`, `source_vb_*_pu`, `source_vc_*_pu`,
    `source_vpos_seq_*_pu`, `source_vneg_seq_*_pu`,
    `source_vabc_unbalance_*_pu` for `pre`, `fault`, and `recovery` windows.
  - Matching `grid_*` pre/fault/recovery fields remain available for plant-side
    and controller-observation diagnostics.
  - Observation aggregates are now split into `obs_*_pre_mean`,
    `obs_*_fault_mean`, and `obs_*_recovery_mean`.
- Controller startup migration:
  - Added `hpt_sac_gridnorm_startup_s` to control how long the local grid
    sequence baseline is updated and fault/recovery state is blanked.
  - The evaluator sets this to a value before the configured fault start, while
    the model default remains `30 ms`.
- Smoke evidence:
  - Topology2 source/observation smoke passed:
    `lab/results/hpt_unbalanced_source_smoke_topology2_20260721_164301/REPORT.md`.
  - Topology1 source/observation smoke passed:
    `lab/results/hpt_unbalanced_source_smoke_topology1_20260721_164456/REPORT.md`.
- Compatibility:
  - Balanced scalar fault descriptors remain valid.
  - The 24-D observation / 4-D action actor contract remains valid.
  - Unbalanced specialist results generated before this gate should remain
    marked stale until rerun.

## 2026-07-21 - Conventional-DQ LV-Error Fallback

- Old behavior:
  - `conventional_dq` policy mode `0` responded mainly to the internal
    grid-side `fault_active` / `recovery_active` state.
  - Mild unbalanced source faults could leave `fault_active` low while LV
    voltage was already outside the voltage-survival band, so the conventional
    rule path produced zero regulating command.
- New behavior:
  - Policy mode `0` now also has an LV-voltage-error fallback:
    if `vpu < 0.98` or `vpu > 1.02`, it generates a bounded `reg_d` command
    from `hpt_conventional_recovery_reg_gain * (1 - vpu)`.
  - The tuned-v1 conventional profile sets nonzero recovery/LV-error gain and
    max command limits for both topologies.
- Compatibility:
  - Observation/action dimensions and actor weight formats are unchanged.
  - This changes the traditional baseline behavior, so old conventional
    boundary matrices must not be mixed with post-fallback matrices.
- Current status:
  - The fallback improves topology1 unbalanced recovery voltage, but gain-only
    pilots still do not produce a mixed pass/fail boundary.
  - Further tuning must sweep injection phase/polarity and recovery law.

## 2026-07-21 - Diagnostic Phase-Override Observation Contract

- Old behavior:
  - The 24-D SAC observation used measured/internal fault and recovery flags
    derived from startup-normalized grid sequence voltage.
  - In topology2 LVRT trajectory actor traces, the actor could still see
    ambiguous fault/recovery phase indicators in closed loop and therefore did
    not reliably reproduce the teacher transition.
- New additive interface:
  - Added default-off model-workspace variables:
    `hpt_sac_phase_override_enable`,
    `hpt_sac_phase_fault_start_s`,
    `hpt_sac_phase_fault_clear_s`, and
    `hpt_sac_phase_recovery_end_s`.
  - When enabled, only the observation phase fields are replaced by scheduled
    fault/recovery features.  The 24-D observation size, 4-D action size, actor
    MAT format, and default behavior are unchanged.
  - Python trajectory validator/campaign runners expose this as
    `--phase-override`.
- Purpose:
  - This is a diagnostic/training contract to test whether topology2 actor
    failures are due to phase-identification ambiguity.
  - It is not a final deployable FRT mechanism unless later replaced by a
    measured, robust phase detector.
- Smoke evidence:
  - Teacher validation with phase override passed for topology2 LVRT
    0.90 pu / 60 ms:
    `lab/results/hpt_t2_lvrt090_phase_override_validation_20260721/summary.json`.
  - BC actor smoke improved action imitation but did not promote:
    `lab/results/hpt_t2_lvrt090_phase_override_actor_smoke_20260721/summary.json`.

## 2026-07-29 - Runtime Depth-Selector SAC Mode

- Old behavior:
  - `sac_actor_always_raw` loaded one exported dynamic SAC actor and used it for
    the whole fault case.
  - The first topology1 balanced LVRT family improvement was only demonstrated
    by a manifest-level actor choice: deep cases used a support-dataset SAC
    checkpoint and all other cases used the seed actor.
- New additive interface:
  - Added evaluator mode `sac_actor_depth_selector_raw`.
  - Added controller `actor_select_mode = 4.0`.
  - In this mode, the Simulink HPTSACController loads the base actor from
    `hpt_sac_actor_weights.mat` and the dynamic actor from
    `hpt_sac_actor_weights_dynamic.mat`, then switches online to the dynamic
    actor for topology1 deep LVRT when `g_vpos` or remembered `v_fault_min` is
    below `0.885` during fault/recovery.
  - `validate_hpt_accepted_specialists.py` now supports optional manifest
    columns `comparison_mode`, `base_model_path`, and `dynamic_model_path`.
- Compatibility:
  - Existing manifest rows without these optional columns keep the old
    `sac_actor_always_raw` behavior.
  - The 24-D observation, 4-D action, and actor MAT weight format are unchanged.
- Evidence:
  - Runtime selector smoke:
    `lab/results/hpt_t1_lvrt_bal_family_runtime_selector_smoke_20260729/summary.json`.
  - Runtime selector full 19-case family gate:
    `lab/results/hpt_t1_lvrt_bal_family_runtime_selector_full_20260729/summary.json`.
  - Full-family result: `14 / 19` voltage-survival pass and `14 / 19` beat
    conventional, matching the earlier case-level selector and improving over
    the seed actor's `13 / 19`.

## 2026-08-03 - Family-SAC Workspace Cleanup

- Canonical interface:
  - Family orchestration is now exclusively
    `sac.campaigns.run_hpt_family_specialist_matrix`.
  - Switch-level promotion is exclusively based on
    `evaluators/eval_hpt_v2_control_comparison.m`.
  - The 24-D observation and 4-D action contracts are unchanged.
- Moved capability:
  - `sac.build_hpt_action_trajectory` moved to
    `sac.datasets.build_hpt_action_trajectory`.
  - All maintained imports were migrated; no compatibility wrapper remains.
- Removed executable paths:
  - fixed-action/per-case campaigns, overnight runners, CEM search, generic
    offline baselines, learned reward correction, safety-classifier training,
    old calibration sweep adapters, and old raw switch smoke tools;
  - source-tree actor archives and redundant teacher collectors.
- Evidence policy:
  - Historical manifests and generated result directories remain for
    provenance but are not supported launch commands.
  - Earlier accepted-manifest claims do not override the current evaluator.
  - The current r6 topology2 A-phase LVRT result is local voltage-survival
    boundary evidence and is not full-FRT certification.

## 2026-08-03 - GB/T PCC Envelope and Load-Quality Gate Split

- Old behavior:
  - The evaluator and calibration collector applied the GB/T voltage-time
    curve to the HPT low-voltage load RMS signal.
  - The project load-quality limits (176--238 V during the fault and +/-7%
    after clearing) were mixed with the PCC grid-code envelope.
- New behavior:
  - Validator schema `hpt-frt-gates-v3-gbt19963.1` evaluates the exact
    GB/T 19963.1-2021 LVRT/HVRT breakpoints only at the PCC.
  - Single-phase events use affected-phase RMS; two-phase and balanced events
    use line-to-line RMS.
  - Project load quality is reported separately from `scenario_valid`.
  - L1 is HPT load-voltage/equipment survival, L2 adds PCC scenario validity
    and connection continuity, and L3 additionally requires reactive support
    and active-power recovery evidence.
- Compatibility and evidence policy:
  - Historical fields named `envelope_*` remain load-quality aliases only.
  - Pre-v3 fault calibration is disabled in the Python proxy.
  - All prior accepted controller evidence is retained but marked
    `stale_pending_revalidation`; no current promotion claim is carried over.

## 2026-08-10 - Topology1 Path and Subsystem Layout Cleanup

- Old name:
  - `simulink/topoloty1`
- New name:
  - `simulink/topology1`
- Reason:
  - Correct the misspelled active topology1 path and make both switch-level
    builders easier to inspect by grouping the plant into named subsystems.
- Affected active entry points:
  - Simulink collectors, evaluators, sweeps, and tests now reference
    `topology1`.
  - SAC launch/config helpers that locate the topology1 model now reference
    `topology1`.
  - `current_research_state.json` now points to
    `simulink/topology1/hpt_v2_1to1_switchlevel.slx`.
- Model layout:
  - The generated switch-level models expose named plant and control
    subsystems. Topology2 uses `CouplingAndInjection`; topology1 was later
    refined into `PrimaryEnergyCoupling` and `SecondarySeriesInjection`.
  - Both models expose `MainTransformer`, `RegulatingConverter`,
    `EnergyConverter`, and `DQControl`.
  - The 24-D observation, 4-D action, workspace variables, and exported
    logging signal names are unchanged.
- Compatibility:
  - No wrapper for `topoloty1` was kept because the user requested the active
    file/path spelling be corrected.
  - Historical evidence, archive metadata, and research-log references keep
    the spelling that existed when those artifacts were produced.
- Validation:
  - `test_hpt_v2_sac_interface.m` passed for topology1 and topology2.
  - `test_hpt_v2_1to1_pure_switchlevel.m` passed after regeneration.
  - `test_hpt_v2_topology2_pure_switchlevel.m` passed after regeneration.
- Rollback:
  - Move `simulink/topology1` back to
    `simulink/topoloty1`, revert the active path edits listed above,
    and regenerate both `.slx` files from the previous builders.

## 2026-08-10 - Topology1 Primary/Secondary Converter Placement

- Old behavior:
  - The topology1 energy-coupling transformer W3/W4 was tapped from the main
    transformer secondary side, which made the top-level drawing look like both
    converters lived on the same side of the main transformer.
- New behavior:
  - W3/W4 is tapped from the main transformer primary side and its primary
    winding rating now follows the medium-voltage side.
  - The top-level generated model separates `PrimaryEnergyCoupling` from
    `SecondarySeriesInjection`.
  - `EnergyConverter` is presented on the primary-side coupling branch for
    DC-link control, while `RegulatingConverter` is presented on the
    secondary/load-side series-injection branch.
- Contract:
  - The SAC observation/action contract remains 24/4.
  - Workspace signal names used by evaluators remain unchanged.
- Validation:
  - `test_hpt_v2_1to1_pure_switchlevel.m` passed after regeneration.
  - Nominal smoke values after the change: LV RMS about
    `202.714 / 203.798 / 205.035 V` for 9/10/11 kV grid cases; Vdc about
    `845.140 / 851.455 / 857.040 V`.
- Rollback:
  - Reconnect W3 from the main transformer secondary conductor, restore W3
    winding1 to the low-voltage rating, regroup W3/W4 and W5/W6 under the old
    `CouplingAndInjection` subsystem, and regenerate the model.

## 2026-08-10 - Topology1 DC-Link and Logging Visibility Cleanup

- Old behavior:
  - The topology1 root diagram exposed DC-link details (`Cdc`, `MeasVdc`,
    chopper comparator/gate/protection blocks) and every `To Workspace` logging
    sink as separate top-level blocks.
- New behavior:
  - `DCLink` groups the shared DC capacitor, voltage measurement, and chopper
    protection.
  - `MeasurementAndLogging` groups the top-level logging sinks while preserving
    their workspace variable names.
- Contract:
  - The SAC observation/action contract remains 24/4.
  - Evaluator-facing workspace variables such as `Vlv_abc`, `Vdc`,
    `Mref6_cmd`, `HPTSAC_obs`, and `HPTSAC_action` are unchanged.
- Validation:
  - `hpt_v2_1to1_switchlevel.slx` regenerated from the topology1 builder.
  - `test_hpt_v2_1to1_pure_switchlevel.m` passed after the visibility cleanup.
  - `test_hpt_v2_sac_interface.m` passed after the visibility cleanup for both
    topology1 and topology2.
- Rollback:
  - Move the contents of `DCLink` and `MeasurementAndLogging` back to the model
    root, then regenerate the model from the previous builder.
