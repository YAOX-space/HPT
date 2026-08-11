# HPT SAC Trajectory Autoresearch Progress - 2026-07-20

## Goal

Move from fixed-state / fixed-action specialist checks to trajectory-level
switch-level validation.  The controller must survive a full fault waveform,
not only produce a useful action at one sampled operating point.

## Code Changes

- Added `sac/build_hpt_trace_aggregate.py`.
  - Aggregates multiple switch-level trace CSVs into one reproducible DAgger
    dataset.
  - Writes `aggregate_trace.csv` and `metadata.json`.
- Updated `sac/pretrain_hpt_actor_bc.py`.
  - Added `--switch-trace-pre-window-repeat-mult`.
  - The BC trainer can now up-weight pre-fault samples, matching existing
    fault/recovery window weighting.
- Updated `sac/run_hpt_trajectory_specialist_campaign.py`.
  - Passes `--pre-window-repeat-mult` through to the BC trainer.
- Updated `simulink/evaluators/eval_hpt_v2_control_comparison.m`.
  - Fixed `hpt_compare_actor_filter_tau` propagation into nested steady/fault
    evaluation functions.
  - This allows direct raw-actor switch-level diagnostics with
    `hpt_compare_actor_filter_tau=0`.

## Key Finding 1: Export and Simulink Actor Execution Are Correct

For the old `fault_start=0.035 s` case, Python forward inference and Simulink
logged actor actions matched to numerical precision after setting
`actor_filter_tau=0`.

Therefore the actor export path is not the main failure source.  The remaining
gap comes from the policy/training problem and the closed-loop state
distribution.

## Key Finding 2: The Old `fault_start=0.035 s` Case Is Contaminated

The controller observation showed `fault_active=1` before the scheduled fault
started.  The cause is startup RMS/voltage transient: LV RMS is still low at
0.030-0.034 s, so the online detector treats startup as sag.

This creates contradictory labels:

- Observation says: fault-like state.
- Teacher trajectory says: pre-fault action should be zero.

Training on this case can force the actor into an impossible static mapping.
Moving the fault later is necessary for a clean trajectory-learning
experiment.

## Clean Scenario Retest

I reran trajectory search with:

- topology: `topology1`
- fault: `0.90 pu`
- duration: `60 ms`
- fault start: `0.080 s`
- fault settle: `20 ms`

Run:

`lab/results/hpt_cem_traj_topology1_lvrt090_60ms_start080_20260720`

Switch-level CEM/anchor search found three voltage-survival teacher
trajectories.

Best teacher by score:

- candidate: `006`
- score: `116.760`
- LV fault mean: `213.681 V`
- LV recovery mean: `205.682 V`
- DC link min/max: `721.099 / 901.528 V`
- timestep envelope violation: `0`
- recovery violation: `0`

Lower-recovery teacher:

- candidate: `007`
- score: `117.082`
- LV fault mean: `213.681 V`
- LV recovery mean: `200.251 V`
- DC link min/max: `721.099 / 901.528 V`
- timestep envelope violation: `0`
- recovery violation: `0`

## Actor Training Results

### Candidate 006 Teacher

Run:

`lab/results/hpt_traj_specialist_topo1_lvrt090_start080_cem_c006_dagger3_20260720`

Best actor was `dagger2`:

- policy voltage-survival pass: `false`
- policy score: `115.026`
- baseline score: `109.906`
- LV fault mean: `209.821 V`
- LV recovery mean: `227.494 V`
- DC link min/max: `761.492 / 890.020 V`
- failure reason: `timestep_recovery_envelope`

This is close on the fault window, but recovery overshoots.

### Candidate 007 Teacher

Run:

`lab/results/hpt_traj_specialist_topo1_lvrt090_start080_cem_c007_dagger3_20260720`

Best actor was `dagger3`:

- policy voltage-survival pass: `false`
- policy score: `117.202`
- baseline score: `109.906`
- LV fault mean: `177.937 V`
- LV recovery mean: `200.199 V`
- DC link min/max: `759.001 / 874.665 V`
- failure reason: `timestep_voltage_envelope;timestep_recovery_envelope`

Lower recovery action fixed recovery mean, but sacrificed fault support.

## Current Interpretation

We have proven that switch-level feasible teacher trajectories exist for the
clean topology1 LVRT case.  We have not yet proven that the current stateless
MLP actor can reliably reproduce those trajectories in closed-loop.

The main problem is no longer proxy-vs-Simulink action export.  The main
problem is trajectory policy representation:

- A fixed teacher action schedule can pass.
- A static observation-to-action BC actor does not reliably reproduce the
schedule after its own earlier actions move the plant state.
- DAgger improves some windows but can over-correct another window.

## Next Research Direction

The next step should stop trying to solve trajectory control with only
single-step behavior cloning.  The controller needs one of these upgrades:

1. Add an explicit trajectory phase / controller memory feature.
   - Examples: time since scheduled disturbance, filtered fault timer, or an
     internal state block.
   - This makes "early fault", "sustained fault", and "recovery" separable.

2. Split the controller into two heads.
   - `survival_head`: fast voltage-support action during LVRT/HVRT.
   - `recovery_head`: taper action after clearing to avoid overvoltage.

3. Train with closed-loop rollout loss, not only pointwise BC.
   - Use CEM/PETS-style trajectory search to find passing trajectories.
   - Use switch-level rollouts to evaluate candidate actor checkpoints.
   - Accept only actors whose whole waveform satisfies every timestep envelope.

4. Keep `fault_start >= 0.080 s` for training and testing unless the model is
   initialized to steady state before `t=0`.
   - Otherwise startup transient is incorrectly mixed with FRT behavior.

## Grid-Observation / Episode-Clock Fix

The first trajectory-specialist attempts failed because the actor observation
mixed two different meanings into the same voltage features:

- LV voltage was both the controlled output and the inferred disturbance state.
- During a successful trajectory, LV can already be near nominal while the grid
  is still in fault.
- The fault timer also reset when the detector bounced, so recovery and
  sustained-fault states could look similar to the actor.

I changed the controller interface so the actor now receives the grid-side
positive-sequence voltage as `obs[1]` and grid-side negative-sequence voltage
as `obs[2]`.  LV voltage remains `obs[0]`, so the actor can separately see:

- what the grid is doing;
- what the load voltage is doing;
- where it is in the episode.

I also changed the active-fault phase feature to a monotonic episode-clock
feature while the fault latch is active.  This is not a physical plant state,
but it is a compact controller state that lets a static MLP distinguish early
fault support from later recovery shaping.

Related implementation changes:

- `simulink/add_hpt_sac_controller.m`
- `simulink/topoloty1/build_hpt_v2_1to1_switchlevel.m`
- `simulink/topology2/build_hpt_v2_topology2_paper.m`
- `sac/hpt_voltage_sac_env.py`
- `sac/pretrain_hpt_actor_bc.py`

The behavior-cloning dataset weighting was also fixed so both `pre` and
`prefault` trace labels receive pre-fault repeat weighting.

## Accepted Switch-Level Specialist

Run:

`lab/results/hpt_t1_l090_pre24_b60_down35_clk_dg3`

Accepted actor:

`data/models/hpt_t1_l090_pre24_b60_down35_clk_dg3_dagger2.zip`

Exported Simulink weights:

`simulink/hpt_sac_actor_weights_hpt_t1_l090_pre24_b60_down35_clk_dg3.mat`

Scenario:

- topology: `topology1`
- category: `LVRT`
- grid fault: `0.90 pu`
- fault duration: `60 ms`
- fault start: `0.080 s`
- decision interval: `2 ms`

Switch-level result:

- voltage-survival pass: `true`
- beats conventional baseline: `true`
- full FRT pass: `false`
- policy score: `102.802`
- conventional baseline score: `112.166`
- LV fault mean: `209.206 V`
- LV recovery mean: `207.372 V`
- DC link min/max: `770.473 / 883.515 V`
- max absolute command: `0.653`

Evaluation sequence:

- `bc0`: failed voltage and recovery timestep envelope.
- `dagger1`: fixed most fault-window support but still failed recovery envelope.
- `dagger2`: passed voltage-survival and beat baseline.
- `dagger3`: also passed voltage-survival, but had a worse score than
  `dagger2`.

This result has been added to:

`sac/experiments/accepted_specialists_20260719.csv`

## Current Boundary

This is a real switch-level closed-loop result, not only a proxy result.  It
does prove that a topology1 LVRT specialist can learn a trajectory policy that
keeps LV/DC inside the voltage-survival envelope and beats the tuned
conventional baseline on this case.

It does not prove full grid-code FRT compliance yet.  The full-FRT evaluator
still reports:

- `gbt_recover`
- `grid_current_limit`
- `not_evaluated_no_sustained_reactive_demand_after_delay`

So the next research target is not to count this as certified FRT.  The next
target is to repeat the trajectory-specialist method across more topology/fault
cases, then separately close the grid-code reactive-current and recovery gates.

## Post-Rebuild Regression Check

After the controller interface fix, I rebuilt both switch-level Simulink
models:

- `simulink/topoloty1/hpt_v2_1to1_switchlevel.slx`
- `simulink/topology2/hpt_v2_topology2_paper.slx`

I then revalidated the accepted topology1 actor with the same scenario timing
used by the successful campaign:

Run:

`lab/results/hpt_accepted_single_t1_l090_gridobs_clock_recheck_20260720`

Result:

- case: `topology1_lvrt090_60ms_gridobs_clock`
- voltage-survival pass: `true`
- beats conventional: `true`
- full FRT pass: `false`
- SAC score: `102.945`
- conventional score: `112.166`
- LV fault mean / recovery mean: `210.137 / 205.971 V`
- DC link min/max: `769.813 / 878.141 V`
- full-FRT reason:
  `gbt_recover;grid_current_limit;not_evaluated_no_sustained_reactive_demand_after_delay`

This confirms the accepted specialist still works after rebuilding the `.slx`
files with the grid-observation and episode-clock controller changes.

## Accepted Matrix Cleanup

I ran a full regression of the previous accepted-specialist manifest after the
grid-observation controller change:

`lab/results/hpt_accepted_matrix_gridobs_regression2_20260720`

Result:

- cases checked: `7`
- voltage-survival pass: `1 / 7`
- beats conventional: `1 / 7`
- full FRT pass: `0 / 7`

Important conclusion:

Most earlier accepted specialists were trained against the old observation
semantics, where the actor saw LV positive-sequence voltage as `obs[1]`.
After the controller was corrected to feed grid-side positive-sequence voltage
as `obs[1]`, those old actors are no longer valid current candidates.  Keeping
them in the accepted matrix would overstate progress.

Cleanup performed:

- `sac/experiments/accepted_specialists_20260719.csv`
  now keeps only the revalidated current actor.
- `sac/experiments/stale_specialists_after_gridobs_20260720.csv`
  records the old failed/unsupported entries and the reason each was removed
  from the current accepted set.
- `sac/validate_hpt_accepted_specialists.py`
  now supports per-case validation, per-row fault timing, and skips unsupported
  `.pt` offline checkpoints instead of aborting the whole regression.

Clean current manifest regression:

`lab/results/hpt_accepted_current_manifest_recheck_20260720`

Result:

- cases checked: `1`
- voltage-survival pass: `1 / 1`
- beats conventional: `1 / 1`
- full FRT pass: `0 / 1`

## New Grid-Observation Trajectory Specialist Retraining

I restarted the trajectory-specialist search under the corrected controller
interface:

- actor observation uses grid-side positive/negative sequence voltage;
- fault/recovery timing uses the monotonic episode clock;
- switch-level validation requires the sampled timestep voltage envelope and
  recovery envelope.

### Successful New Specialist

New accepted case:

- case id: `topology1_hvrt110_60ms_gridobs_traj`
- topology: `topology1`
- fault family: `HVRT`
- scenario: `1.10 pu`, `60 ms`, fault start `0.080 s`,
  fault settle `0.020 s`
- teacher search:
  `lab/results/hpt_cem_gridobs_topo1_hvrt110_60ms_start080_settle20_recoveryboost_20260720`
- training run:
  `lab/results/hpt_t1_h110_b0_r30_gridobs_traj_20260720`
- accepted checkpoint:
  `data/models/hpt_t1_h110_b0_r30_gridobs_traj_20260720_dagger1.zip`

The key teacher-search change was to add light HVRT anchors.  The earlier HVRT
anchors were too aggressive and drove LV voltage below the survival window.
The passing teacher used small or zero support during the swell and stronger
post-fault recovery support.  The best teacher passed voltage survival with:

- trajectory score: `113.200`
- conventional score: `115.562`
- LV fault mean / recovery mean: `178.802 / 210.591 V`
- DC link min/max: `762.984 / 979.067 V`
- timestep envelope violation: `0`
- recovery envelope violation: `0`

After BC/DAgger, the accepted manifest regression reports:

- policy score: `106.136`
- conventional score: `115.562`
- LV fault mean / recovery mean: `192.328 / 204.200 V`
- DC link min/max: `762.984 / 918.748 V`
- voltage-survival pass: `true`
- beats conventional: `true`
- full FRT pass: `false`
- full-FRT reason:
  `gbt_recover;not_evaluated_no_sustained_reactive_demand_after_delay`

### Topology2 Boundary Results

The same grid-observation/timestep-envelope search did not yet produce an
accepted topology2 specialist.

Topology2 HVRT:

- search: `lab/results/hpt_cem_gridobs_topo2_hvrt110_60ms_start080_settle20_lightanchors_20260720`
- result: `0` voltage-survival passes
- main failure mode: `dc_link_bounds`, often with recovery-envelope violation
- zero-action diagnostic:
  `lab/results/hpt_validate_gridobs_topo2_hvrt110_zero_60ms_start080_settle20_20260720`
- zero-action DC link: `305.155 / 1039.980 V`

This means topology2 HVRT is not failing only because the regulating bridge is
mis-commanded; the energy/DC-link channel needs an observation-dependent
stabilizing policy.

Topology2 LVRT:

- search: `lab/results/hpt_cem_gridobs_topo2_lvrt090_60ms_start080_settle20_lightanchors_20260720`
- result: `0` teacher voltage-survival passes
- best near-pass teacher had voltage and recovery timestep envelope pass, but
  failed only `dc_link_bounds`:
  `Vdc = 792.144 / 1046.465 V`
- DAgger/Vdc-feedback attempt:
  `lab/results/hpt_t2_l090_pre14_b14_down04_vdcfb_gridobs_20260720`
- best actor still failed only `dc_link_bounds`:
  `Vdc = 792.144 / 1043.894 V`

So the Vdc-feedback relabeling helped but was not enough to reduce the
topology2 DC-link high-side excursion below the current `1000 V` survival
gate.

### Current Accepted Manifest

Regression run:

`lab/results/hpt_accepted_gridobs_manifest_recheck2_20260720`

Result:

- cases checked: `2`
- voltage-survival pass: `2 / 2`
- beats conventional: `2 / 2`
- full FRT pass: `0 / 2`

Current accepted specialists:

- `topology1_lvrt090_60ms_gridobs_clock`
- `topology1_hvrt110_60ms_gridobs_traj`

## Topology2 Energy/Chopper Calibration Addendum

After the topology1 specialists were accepted, I focused on the unresolved
topology2 LVRT energy/DC-link path.

Implementation updates:

- Added `simulink/calibrate_hpt_v2_topology2_energy_branch.m`.
- Parameterized the topology1/topology2 chopper blocks through
  `hpt_chopper_threshold` and `hpt_rchop`.
- Added `hpt_compare_model_params` to
  `simulink/evaluators/eval_hpt_v2_control_comparison.m`.
- Added `hpt_trace_model_params` to
  `simulink/collectors/collect_hpt_v2_trajectory_trace.m`.
- Passed chopper/Rchop overrides through the trajectory validation,
  CEM-search, and specialist-campaign Python entry points.
- Added logical dual-head training semantics in
  `sac/pretrain_hpt_actor_bc.py`: the exported actor interface is
  still one 4-output actor for Simulink compatibility, but the dataset relabels
  the regulating and energy channels separately.

Energy sweep findings:

- Under the default chopper setting (`850 V`, nominal `Rchop`), topology2
  LVRT 0.90 pu can raise the DC-link low dip with energy action, but the
  high-side DC excursion remains above the `1000 V` survival gate.
- Negative `m_energy_d` and positive `m_energy_q` generally support the
  low-side DC dip, but none of the default-chopper sweeps removed the
  high-side spike.
- Increasing `hpt_energy_id_max` worsened several cases, so the issue is not
  simply an energy-current authority limit.
- Lowering the chopper threshold and strengthening the chopper can bound the
  DC link, but too much chopper action depresses the LV waveform.

Representative topology2 LVRT 0.90 pu results:

- default chopper, `m_energy=[0,0]`: `Vdc = 473.7 / 1046.5 V`
- default chopper, `m_energy=[-0.3,0]`: `Vdc = 781.8 / 1039.1 V`
- default chopper, `m_energy=[-0.5,0.4]`: `Vdc = 792.1 / 1038.2 V`
- calibrated chopper (`780 V`, `Rchop_scale=0.85`), fixed action near
  `m_reg_d=0.20`, `m_energy=[0.022,0.002]`: DC link stays close to the
  survival window, but the timestep LV envelope still has a small violation.

Training findings:

- Aggressive two-zone energy relabeling made the actor learn energy actions,
  but it overacted and produced DC-link dips.
- A corridor-limited two-zone energy label stabilized training.  The best
  actor had good command tracking and small switch/proxy alignment error, but
  still failed `dc_link_bounds` under the default chopper.
- This indicates the next topology2 LVRT step should search a calibrated
  dynamic trajectory under explicit chopper/Rchop settings, rather than
  continue default-chopper SAC training.

Current conclusion:

- Topology2 energy branch direction is partly understood: energy action can
  support the low-side DC dip, but the high-side DC spike is dominated by
  chopper/DC-link transient behavior.
- Default topology2 LVRT 0.90 pu is not ready for accepted specialist training.
- The next experiment is a calibrated CEM trajectory search around
  `hpt_chopper_threshold=780 V` and `Rchop_scale=0.85-0.90`, with focus on the
  fault-entry LV envelope.

## Topology2 Timefix Specialist Addendum

I found and fixed a state-feedback representation issue in the 24-D SAC
observation:

- Simulink `obs_19` previously encoded fault time as absolute `t_clock/0.5`.
- The proxy fault detector used the same absolute-time convention.
- Both now encode fault time as elapsed time since detected fault onset:
  `(t - fault_start_t)/0.5`.

This matters because the topology2 trajectory teacher is phase-dependent:
fault entry, fault plateau, and recovery need different regulating actions.
With absolute time, the actor had weak information about where it was inside
the disturbance and under-reproduced the teacher's plateau.

New topology2 LVRT result:

- teacher search:
  `lab/results/hpt_cem_t2_lvrt090_chop780_r065_recovery_anchor_20260720`
- accepted training run:
  `lab/results/hpt_t2_l090_chop780_r065_timefix_purebc_20260720`
- checkpoint:
  `data/models/hpt_t2_l090_chop780_r065_timefix_purebc_20260720_bc0.zip`
- `0.90 pu`, `60 ms`, fault start `0.080 s`,
  `hpt_chopper_threshold=780 V`, `Rchop_scale=0.65`
- switch-level policy voltage-survival: `true`
- beats conventional: `true`
- policy/conventional score: `128.458 / 143.302`
- LV fault/recovery mean: `194.603 / 205.083 V`
- DC link min/max: `762.393 / 978.342 V`
- full FRT: `false`, reason `grid_current_limit;reactive_wrong_sign`

New topology2 HVRT result:

- teacher search:
  `lab/results/hpt_cem_t2_hvrt110_chop780_r065_timefix_anchor_20260720`
- accepted training run:
  `lab/results/hpt_t2_h110_chop780_r065_timefix_purebc_20260720`
- checkpoint:
  `data/models/hpt_t2_h110_chop780_r065_timefix_purebc_20260720_bc0.zip`
- `1.10 pu`, `60 ms`, fault start `0.080 s`,
  `hpt_chopper_threshold=780 V`, `Rchop_scale=0.65`
- switch-level policy voltage-survival: `true`
- beats conventional: `true`
- policy/conventional score: `113.861 / 155.992`
- LV fault/recovery mean: `201.745 / 204.916 V`
- DC link min/max: `762.393 / 999.985 V`
- full FRT: `false`, reason
  `grid_current_limit;not_evaluated_no_sustained_reactive_demand_after_delay`

The accepted manifest was updated as a new dated file:

`sac/experiments/accepted_specialists_20260720.csv`

Regression validation:

`lab/results/hpt_accepted_specialist_validation_20260720_timefix_topology2`

Result:

- cases checked: `4`
- voltage-survival pass: `4 / 4`
- beats conventional: `4 / 4`
- full FRT pass: `0 / 4`

Current accepted voltage-survival specialist matrix:

- `topology1_lvrt090_60ms_gridobs_clock`
- `topology1_hvrt110_60ms_gridobs_traj`
- `topology2_lvrt090_60ms_chop780_r065_timefix`
- `topology2_hvrt110_60ms_chop780_r065_timefix`

These are not full-FRT-certified controllers.  They are the current
switch-level voltage-survival specialists and are the stopping point for the
paused full-FRT work.

