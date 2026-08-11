# HPT SAC Stage-1/Stage-2 Progress - 2026-07-21

## Scope

This note is the current Stage-2 evidence index after the timestep-envelope
gate, grid-sequence observation normalization, and `old iterative workspace` directory
cleanup.

The active staged claim is:

1. prove switch-level voltage-survival specialist SAC first;
2. compare specialists against a meaningful conventional/rule baseline on
   boundary cases;
3. keep full FRT certification as a later phase until voltage survival is
   stable.

Do not use this document to claim full FRT certification.

## Current Pass Criteria

The current voltage-survival gate is sampled over the trajectory, not judged
only by mean LV values.  A voltage-survival specialist must satisfy:

- fault-window LV samples inside the 176-238 V survival band;
- timestep LVRT/HVRT voltage-envelope samples satisfied;
- recovery-window samples inside the recovery envelope;
- DC link inside the survival range;
- action magnitude inside the allowed command range;
- switch-level Simulink validation, not proxy-only validation.

`lv_mean` and `lv_recovery_mean` are diagnostics only.

## Authoritative Balanced Evidence

The current balanced accepted manifest is:

`sac/experiments/accepted_specialists_20260721_balanced.csv`

It contains four currently reproducible switch-level trajectory/state-feedback
specialists after the 2026-07-22 current-interface recheck:

`lab/results/hpt_accepted_balanced_matrix_20260722_current4_recheck/REPORT.md`

| case | topology | fault | duration | policy score | conventional score | result |
| --- | --- | --- | --- | ---: | ---: | --- |
| `topology1_lvrt090_60ms_gridobs_clock` | topology1 | LVRT 0.90 pu | 60 ms | 104.012 | 122.356 | voltage-survival pass, beats conventional |
| `topology1_hvrt110_60ms_current_iface_const249` | topology1 | HVRT 1.10 pu | 60 ms | 105.383 | 116.834 | voltage-survival pass, beats conventional |
| `topology2_lvrt090_60ms_phase_nonoise_retrain` | topology2 | LVRT 0.90 pu | 60 ms | 113.665 | 264.260 | voltage-survival pass, beats conventional |
| `topology2_hvrt110_60ms_balanced_retrain` | topology2 | HVRT 1.10 pu | 60 ms | 114.076 | 188.705 | voltage-survival pass, beats conventional |

All four rows report:

- `voltage_survival_pass = true`;
- `beats_conventional = true`;
- `fault_lv_band_violation_max_pu = 0`;
- `envelope_violation_max_pu = 0`;
- `full_frt_pass = false`.

This is the strongest current Stage-1/Stage-2 result.

The topology1 LVRT row still reports a very small
`recovery_violation_max_pu = 0.0008097`; the current evaluator returns
`voltage_survival_pass = true`, so it remains accepted under the current gate,
but this should be watched if the recovery tolerance is tightened.

The previous topology1 HVRT 1.10 pu / 60 ms row
`topology1_hvrt110_60ms_balanced_retrain` is no longer counted as accepted.  It
failed the current phase-aware/per-case recheck with
`timestep_fault_lv_band;timestep_recovery_envelope` and is archived in
`sac/experiments/stale_specialists_after_phaseaware_recheck_20260722.csv`.
It is replaced by `topology1_hvrt110_60ms_current_iface_const249`, a retrain
from the current-interface constant trajectory `[0.249, 0, -0.005, 0]`.

The topology2 LVRT row was upgraded on 2026-07-22 from the earlier balanced
retrain actor to the no-noise, high-weight actor trained from the best
phase-grid trajectory teacher.  The promoted actor uses the model
`data/models/hpt_t2_lvrt090_fr052_rr016_re008_phase_nonoise_actor_20260722_bc0.zip`
and passed switch-level voltage survival with zero fault/recovery envelope
violations, `Vdc_min = 761.40 V`, `Vdc_max = 978.45 V`, and score `113.665`
against the conventional score `264.260`.

## Current Mixed Boundary Evidence

The first usable unbalanced voltage-survival boundary matrix is:

`lab/results/hpt_v2_control_comparison/control_comparison_all_fault_all_unbalanced_legacy_mixed_boundary_20260721_20260721_191851.csv`

Summary:

| topology | rows | voltage-survival pass | full-FRT pass | interpretation |
| --- | ---: | ---: | ---: | --- |
| topology1 | 16 | 12 | 0 | usable mixed voltage-survival boundary |
| topology2 | 16 | 0 | 0 | not yet a usable topology2 boundary |
| all | 32 | 12 | 0 | voltage-survival boundary only |

Important limitation: this matrix uses `legacy_conventional` as the
conventional/rule reference because the stronger `conventional_dq` path was
all-fail on the regenerated unbalanced matrix.  Use it to study voltage-survival
boundary behavior, not to claim final superiority over a full grid-code
controller.

## Unbalanced Source And Observation Gate

The unbalanced source/observation interface is now usable:

- topology1 smoke report:
  `lab/results/hpt_unbalanced_source_smoke_topology1_20260721_164456/REPORT.md`
- topology2 smoke report:
  `lab/results/hpt_unbalanced_source_smoke_topology2_20260721_164301/REPORT.md`

Both passed `14 / 14` source cases.  The smoke gate now checks source command
and recovery using `Vgrid_cmd_abc`, plus source/grid/observation diagnostics
across pre-fault, fault, and recovery windows.

Old unbalanced accepted specialists from before grid-sequence normalization are
stale.  They are documented in:

`sac/experiments/stale_specialists_after_gridnorm_20260721.csv`

Do not quote old unbalanced pass counts without rerunning the switch-level gate.

## Proxy Calibration Status

The current unbalanced proxy calibration is a pilot, not final training
evidence.

Artifacts:

- calibration matrix:
  `lab/results/hpt_v2_frt_calibration_matrix/frt_calibration_matrix_pilot_all_20260721_193807.csv`
- calibration JSON:
  `sac/hpt_proxy_calibration_unbalanced_pilot.json`

Pilot size: 104 fixed-action calibration rows.

Observed rollout-alignment quality:

- LV mean MAE: about 0.0106 pu;
- Vdc mean MAE: about 0.0122 pu;
- maximum Vdc error: about 0.443 pu;
- maximum recovery-violation error: about 0.085 pu.

Weak groups:

- topology1 HVRT `energy_sweep`;
- topology1 HVRT `reg_sweep`;
- topology2 DC-link and energy-branch dynamics.

Decision: do not train unbalanced SAC directly from this proxy as final
evidence.  It may be used for coarse ranking or diagnostics only.

## Topology2 Energy-Branch Pilot

The first topology2 energy branch pilot exposed and fixed a calibration-script
bug.

Initial run:

`lab/results/hpt_v2_topology2_energy_branch_calibration/topology2_energy_branch_stage2_t2_energy_pilot_20260721_20260721_205608.csv`

Problem:

- requested `cmd_m_energy_d=-0.3/0/+0.3`;
- measured `cmd_m_energy_d_mean` was `0` for all rows;
- LV/Vdc responses were identical across the energy commands.

Fix:

- `simulink/calibration/calibrate_hpt_v2_topology2_energy_branch.m`
  now injects `hpt_traj_t` and `hpt_traj_action` directly through
  `SimulationInput`.

Re-run:

`lab/results/hpt_v2_topology2_energy_branch_calibration/topology2_energy_branch_stage2_t2_energy_pilot_after_trajinput_fix_20260721_20260721_205941.csv`

Post-fix finding:

- `cmd_m_energy_d_mean` now tracks the requested command;
- LVRT 0.90 remains failed because the regulating anchor is too weak
  (`LV_fault` about 146-147 V);
- HVRT 1.10 remains failed by recovery envelope;
- positive `m_energy_d` raises HVRT recovery voltage and worsens recovery
  violation in this anchor;
- DC link stays inside the survival range in this small sweep.

Implication: topology2 needs a joint regulating-plus-energy sweep.  Energy-only
d-axis calibration around a weak regulating anchor is not enough to recover
LVRT voltage survival.

Follow-up joint pilot:

`lab/results/hpt_v2_topology2_energy_branch_calibration/topology2_energy_branch_stage2_t2_energy_joint_lvrt_pilot_20260721_20260721_210334.csv`

This used a strong LVRT regulating anchor
`[reg_pre, reg_fault, reg_recovery] = [0.00, 0.80, 0.38]` and swept
`m_energy_d=-0.30/0/+0.30`.

Finding:

- fault LV rose to about 225 V, which is over-boosted for the timestep
  envelope;
- recovery stayed high at about 229-232 V;
- DC link collapsed below the survival lower bound, with `Vdc_min` about
  556-561 V;
- negative `m_energy_d` was least harmful in this pilot but did not make the
  case pass.

Implication: topology2 needs constrained joint trajectory search, not a fixed
energy sign rule.  The proxy calibration matrix should include both
under-boosted and over-boosted regulating anchors so it can learn the LV/DC
tradeoff.

Local pass-region sweep:

`lab/results/hpt_v2_topology2_energy_branch_calibration/topology2_energy_branch_stage2_t2_lvrt_reg_recovery_fine_ed030_20260721_20260721_211456.csv`

Search space:

- fault: topology2 LVRT 0.90 pu / 60 ms;
- fixed `m_energy_d=+0.30`, `m_energy_q=0`;
- `reg_fault=0.48/0.50/0.52/0.54`;
- `reg_recovery=0.08/0.12/0.16`.

Passing voltage-survival seed rows:

| reg fault | reg recovery | m energy d | LV fault | LV recovery | Vdc min | Vdc max |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0.48 | 0.16 | 0.30 | 217.05 V | 202.07 V | 761.40 V | 970.48 V |
| 0.50 | 0.16 | 0.30 | 218.80 V | 202.74 V | 761.40 V | 970.48 V |
| 0.52 | 0.16 | 0.30 | 219.87 V | 202.51 V | 759.15 V | 970.48 V |

These rows have zero timestep envelope and recovery violations in the
calibration script.  They are trajectory/action seeds, not trained SAC actors
yet.

Standard trajectory validation:

`lab/results/hpt_t2_lvrt090_reg050_rec016_ed030_piecewise_validate_20260721/summary.json`

The piecewise trajectory

- pre-fault: `[0, 0, 0, 0]`;
- fault: `[0.50, 0, 0.30, 0]`;
- recovery: `[0.16, 0, 0.30, 0]`;

passed the switch-level trajectory validator:

- `trajectory_voltage_pass = true`;
- `trajectory_beats_baseline = true`;
- `trajectory_score = 128.799`, baseline score `264.260`;
- `trajectory_lv_mean = 216.953 V`;
- `trajectory_lv_recovery_mean = 201.074 V`;
- `trajectory_vdc_min = 760.765 V`;
- `trajectory_vdc_max = 978.342 V`;
- timestep envelope and recovery violations `0`.

The fixed-action comparator failed, so topology2 LVRT needs a time-varying
trajectory or state-feedback policy rather than one fixed action across the
whole fault.

Trajectory actor campaign:

`lab/results/hpt_t2_lvrt090_reg050_rec016_ed030_actor_bc_20260721_r3/summary.json`

This campaign trained BC/DAgger actors from the passing trajectory seed.  It
did not produce a promotable actor:

| actor | voltage survival | reason | score | fault LV min/max | Vdc min/max |
| --- | --- | --- | ---: | --- | --- |
| `bc0` | false | timestep fault-band/envelope | 128.108 | 173.12 / 204.94 V | 760.29 / 967.01 V |
| `dagger1` | false | fault-band and DC-link bounds | 131.841 | 192.04 / 250.30 V | 598.35 / 1072.70 V |

Trace alignment shows the actor did not internalize the sharp trajectory
transition:

- `m_reg_d_mae = 0.159`;
- `m_reg_d_max_abs_error = 0.543`;
- `m_energy_d_mae = 0.072`;
- LV RMS MAE `18.12 V`;
- Vdc MAE `29.69 V`.

Decision: this is a useful negative result.  The trajectory seed remains valid,
but the actor is not part of the accepted matrix.  The next actor-training
revision must explicitly separate startup, fault, and recovery behavior before
claiming a topology2 trajectory/state-feedback SAC promotion.

Observation diagnosis:

- In the final actor trace, prefault/startup samples already contain nonzero
  actor commands.  The actor enters the fault with a different state
  distribution from the teacher.
- In recovery, the actor trace still reports high fault-active observation
  values and low recovery-active values for much of the window.  Therefore the
  current 24-D observation contract does not reliably tell the actor when to
  transition from the fault action to the recovery action in topology2.
- This explains why increasing BC epochs or fault-window weights alone did not
  promote the actor: the issue is a state/phase-identification gap, not simply
  a small supervised-training loss.

Next decision: topology2 trajectory SAC should not continue with blind
hyperparameter sweeps.  The next experiment should first revise the phase
contract used by actor training and validation, for example by adding robust
startup blanking plus explicit fault/recovery phase features, or by training
separate phase-conditioned heads.

## Completed Engineering Work

- Added timestep voltage-survival fields to the evaluator and Python side:
  - `fault_lv_band_violation_max_pu`;
  - `envelope_violation_max_pu`;
  - `recovery_violation_max_pu`.
- Added grid-side current/reactive-current fields to the evaluator/proxy hooks,
  but these are not yet passing full FRT gates.
- Added unbalanced source command logging via `Vgrid_cmd_abc`.
- Added local grid-sequence observation normalization and startup blanking in
  the shared HPTSACController path.
- Fixed the topology2 energy-branch calibration script so trajectory energy
  commands are actually injected into the model workspace.
- Hardened the trajectory-specialist campaign against two MATLAB automation
  failure modes:
  - transient trajectory-validation `matlab_failed` summaries now retry once;
  - trace collection can continue after a MATLAB nonzero return only if the
    expected trace CSV was written.
- Cleaned `sac` and `simulink` into maintained
  subdirectories with canonical commands documented in their README files.

## Not Completed

- No current specialist is full-FRT certified.
- Grid-code reactive-current support and grid-current limit criteria remain
  incomplete for the accepted balanced rows.
- topology2 unbalanced trajectory/action seeds now exist for LVRT 0.90, but no
  topology2 unbalanced SAC actor has been promoted yet.
- The topology2 balanced LVRT piecewise trajectory actor has one promoted
  no-noise/high-weight BC realization, but this remains a narrow
  voltage-survival specialist rather than a full-FRT controller.
- The unbalanced proxy does not yet match switch-level behavior tightly enough
  for final SAC training.
- The topology2 energy branch still needs dedicated command/response and
  DC-link calibration before direct four-action SAC claims are trustworthy.

## Latest Topology2 Phase-Observation Experiment

An opt-in diagnostic phase-observation override was added on 2026-07-21.  It
does not change the 24-D observation / 4-D action contract and is default off.
It is used only to test whether topology2 trajectory actor failures come from
ambiguous startup/fault/recovery observation features.

Results:

| run | teacher pass | actor pass | key finding |
| --- | ---: | ---: | --- |
| `hpt_t2_lvrt090_phase_override_actor_smoke_20260721` | true | false | action imitation improved to `m_reg_d_mae=0.00435`, but actor still had `0.03376 pu` envelope violation |
| `hpt_t2_lvrt090_reg052_rec018_ed030_phase_margin_actor_smoke_20260721` | true | false | higher recovery margin lowered score but caused recovery-envelope violation |
| `hpt_t2_lvrt090_reg052_rec016_ed030_phase_margin_actor_smoke_20260721` | true | false | fault envelope passed, but recovery overvoltage and DC-link collapse appeared |

Interpretation:

- The phase-observation fix is productive because it makes the actor reproduce
  teacher actions much more accurately.
- It is not enough for promotion.  topology2 closed-loop energy/DC-link
  behavior still diverges during recovery.
- None of these new actors should be added to
  `accepted_specialists_20260721_balanced.csv`.

Follow-up recovery-energy tests:

| run | teacher pass | actor pass | result |
| --- | ---: | ---: | --- |
| `hpt_t2_lvrt090_reg052_rec016_ed030_phase_energy_dagger_20260721` | true | false | two-zone DAgger improved BC0 DC link to `653.62 V`, but DAgger1 worsened to `504.04 V` |
| `hpt_t2_lvrt090_reg052_rec016_ed010_phase_actor_smoke_20260721` | true | false | recovery `m_energy_d=0.10` fixed DC link (`Vdc_min=762.39 V`) but left small envelope/recovery violations |
| `hpt_t2_lvrt090_reg050_rec014_ed010_phase_actor_smoke_20260721` | true | false | recovery violation disappeared, but fault-window envelope violation grew to `0.03959 pu` |

Decision: the topology2 LVRT actor is now bounded to a narrow recovery-energy
region.  The next promotion attempt should not continue broad blind training;
it should use finer trajectory search or phase-conditioned heads around
`m_reg_d_fault=0.50-0.52`, `m_reg_d_recovery=0.14-0.16`, and
`m_energy_d_recovery=0.10`, with evaluator-level correction samples capturing
20-us DC/envelope extrema.

Additional fine-grid result:

- Added `sac.campaigns.sweep_hpt_t2_lvrt_phase_grid`, a small
  reproducible switch-level teacher grid for topology2 LVRT 0.90 pu / 60 ms.
- Run:
  `lab/results/hpt_t2_lvrt090_phase_grid_smoke_20260721/summary.json`.
- Six phase-aware fault/recovery teacher trajectories were tested.  All six
  passed voltage survival and beat the conventional baseline.
- Best ranked teacher:
  `fr052_rr016_fe030_re008`, with fault action `[0.52,0,0.30,0]` and recovery
  action `[0.16,0,0.08,0]`.
- The best teacher passed with zero timestep/recovery violations:
  trajectory score `128.086`, baseline score `264.260`, `Vdc_min=758.31 V`,
  `Vdc_max=978.34 V`.
- A BC actor trained from this teacher did not promote:
  `lab/results/hpt_t2_lvrt090_fr052_rr016_re008_phase_actor_20260721/summary.json`.
  It failed `timestep_voltage_envelope` with
  `policy_envelope_violation_max_pu=0.02644`, although DC link was healthy
  (`Vdc_min=762.39 V`) and action imitation was close
  (`m_reg_d_mae=0.00597`, `m_energy_d_mae=0.00407`).
- Interpretation: the remaining issue is no longer finding a feasible
  trajectory.  The issue is converting the trajectory into a state-feedback
  actor without 20-us switch-level voltage excursions.  Next work should focus
  on phase/window-conditioned actor heads or evaluator-level correction samples
  near the fault/recovery boundary.

DAgger repair attempt:

- Run:
  `lab/results/hpt_t2_lvrt090_fr052_rr016_re008_phase_trajdagger1_20260722/summary.json`.
- Setup:
  same best teacher, `--dagger-iters 1`, `--dagger-label-source trajectory`,
  no extra Vdc feedback.
- BC0 reproduced the prior failure exactly:
  `policy_envelope_violation_max_pu=0.02644`, `Vdc_min=762.39 V`.
- DAgger1 changed the failure mode rather than promoting:
  `policy_envelope_violation_max_pu=0`,
  `policy_recovery_violation_max_pu=0.03771`,
  `Vdc_min=613.03 V`.
- Decision:
  simple 2-ms actor-visited trajectory relabeling is not sufficient for
  topology2 LVRT promotion.  It can fix the fault-window envelope but moves the
  problem into recovery/DC-link dynamics.  The next architecture change should
  explicitly separate fault and recovery behavior, for example with
  phase/window-conditioned actor heads or a recovery-specific correction
  dataset with switch-level extrema.

No-noise high-weight actor promotion:

- Run:
  `lab/results/hpt_t2_lvrt090_fr052_rr016_re008_phase_nonoise_actor_20260722/summary.json`.
- Setup:
  same best phase-grid teacher, no observation-noise augmentation,
  high action weights `32,1,12,1`, teacher-prior weight `300`, and direct
  switch-trace behavior cloning.
- Result:
  `policy_voltage_pass = true`, `policy_beats_baseline = true`,
  `policy_score = 113.665`, baseline score `264.260`.
- Switch-level voltage-survival metrics:
  `fault_lv_band_violation_max_pu = 0`,
  `envelope_violation_max_pu = 0`,
  `recovery_violation_max_pu = 0`,
  `Vdc_min = 761.40 V`, `Vdc_max = 978.45 V`.
- Limitation:
  `policy_full_frt_pass = false` with
  `grid_current_limit;not_evaluated_no_sustained_reactive_demand_after_delay`.
- Decision:
  promote this actor as the current topology2 LVRT balanced
  voltage-survival specialist and replace the older topology2 LVRT row in
  `accepted_specialists_20260721_balanced.csv`.

## Next Research Actions

1. Improve proxy calibration where the pilot is weak:
   topology1 HVRT `energy_sweep`/`reg_sweep` and topology2 DC-link dynamics.
2. For topology2, run a focused energy-branch command/response sweep:
   `m_energy_d`, `m_energy_q`, `Vdc_min`, `Vdc_max`, `LV_fault`, and
   `LV_recovery`.
3. Extend the topology2 sweep to constrained joint `m_reg_d` plus
   `m_energy_d/q`, because the fixed-reg pilots showed both sides of the
   tradeoff: weak reg under-boosts LV, while strong reg over-boosts LV and
   collapses the DC link.
4. Extend topology2 trajectory actor training beyond the current narrow
   no-noise LVRT success.  The promoted actor is useful evidence, but
   topology2 still needs a more robust phase/window-conditioned or two-head
   reg/energy policy before expanding to deeper LVRT/HVRT and unbalanced cases.
5. Generate switch-level trajectory teachers for other unbalanced cases instead
   of
   relying on the current fixed-action proxy ranking.
6. Retrain unbalanced trajectory/state-feedback specialists only after the
   teacher trace and proxy-diagnostic gates agree.
7. Re-run `validate_hpt_accepted_specialists.py` before quoting any accepted
   matrix after further interface or envelope changes.
