# HPT Specialist SAC Matrix Progress - 2026-07-19

## Goal

Build usable specialist SAC controllers split by topology and fault family, and
evaluate them against the switch-level Simulink models and the conventional DQ
baseline.

## What Was Added

- Added `sac.run_hpt_specialist_matrix_campaign`.
- The runner reuses completed switch-level specialist campaigns when available,
  launches missing cases, and writes:
  - `case_manifest.csv`
  - `specialist_matrix_results.csv`
  - `summary.json`
  - `REPORT.md`
- Promotion levels are explicit:
  - `full_frt`: full switch-level FRT pass.
  - `voltage_survival`: switch-level voltage-survival pass and better score than
    conventional DQ, but full-FRT blockers remain.
  - `diagnostic`: not a usable specialist.
- Fixed campaign metadata so the recorded policy checkpoint points to the best
  actor instead of the last trained actor.
- Added continuous q-gating support in the BC/DAgger teacher path before this
  matrix run, so topology2 LVRT can gradually introduce reactive action instead
  of applying an abrupt q command.

## Matrix Run

Command:

```powershell
py -3 -m sac.run_hpt_specialist_matrix_campaign --campaign-id hpt_specialist_matrix_20260719 --case-timeout-s 3600 --matlab-timeout-s 1200 --train-timeout-s 600
```

Output:

- Result directory:
  `lab/results/hpt_specialist_matrix_20260719`
- Matrix CSV:
  `lab/results/hpt_specialist_matrix_20260719/specialist_matrix_results.csv`

## Current Promoted Specialist Controllers

| Case | Level | Result |
| --- | --- | --- |
| `topology1_lvrt090_80ms` | `voltage_survival` | Passes voltage-survival and slightly beats conventional DQ. Full FRT still fails: `gbt_recover;grid_current_limit;reactive_wrong_sign`. |
| `topology2_lvrt095_80ms` | `voltage_survival` | Passes voltage-survival and strongly beats conventional DQ. Full FRT still fails: voltage envelope/recovery, grid current, reactive sign. |
| `topology2_lvrt090_80ms` | `voltage_survival` | Passes voltage-survival and beats conventional DQ after DAgger with continuous q-gate. Full FRT still fails: voltage envelope/recovery, grid current, reactive sign. |

No actor currently passes full FRT certification.

## Failed Boundary Probes

### topology1 / LVRT / 0.75 pu / 80 ms

- New specialist probe:
  `hpt_specialist_matrix_20260719_topology1_lvrt075_80ms_probe`
- Result: `diagnostic`
- Failure:
  - `lv_fault_mean_bounds`
  - `dc_link_bounds`
  - `reactive_wrong_sign`
- Interpretation:
  A fixed high `m_reg_d` plus energy command is not enough for this deeper sag.
  The conventional DQ controller survives voltage in this case, but the current
  hand-made teacher action drains the DC link and undershoots the LV fault mean.

Additional sweep:

```powershell
py -3 -m sac.campaigns.run_hpt_dynamic_trajectory_sweep --run-id hpt_boundary_sweep_topo1_lvrt075_ramp5_20260719 --topology topology1 --fault-pu 0.75 --duration-s 0.08 --reg-d-grid 0.45,0.55,0.62,0.70 --reg-q-grid 0 --energy-d-grid 0,0.10,0.20,0.35 --energy-q-grid 0 --d-ramp-ms-grid 5 --q-ramp-ms-grid 5 --down-ms-grid 0 --max-cases 16 --timeout-s 1200
```

Result:

- Completed: `16 / 16`
- Voltage-survival pass: `0 / 16`
- Best score still failed due `lv_fault_mean_bounds;dc_link_bounds`.

Rule-teacher follow-up:

```powershell
py -3 -m sac.run_hpt_trajectory_specialist_campaign --run-id hpt_rule_teacher_topo1_lvrt075_20260719 --topology topology1 --fault-pu 0.75 --duration-s 0.08 --teacher-source rule --dagger-iters 0 --switch-trace-repeat 64 --epochs 60 --bc-obs-noise-repeat 3 --matlab-timeout-s 1200 --train-timeout-s 600
```

Result:

- BC loss was low, but the switch-level actor still failed voltage-survival.
- Failure reason: `lv_fault_mean_bounds`.
- Interpretation:
  matching the teacher action at sampled states is not enough, because the actor
  creates its own closed-loop state trajectory after being inserted into
  Simulink.  This is a rollout-alignment problem, not only an action-label MSE
  problem.

Rollout-alignment follow-up:

```powershell
py -3 -m sac.run_hpt_trajectory_specialist_campaign --run-id hpt_rule_teacher_topo1_lvrt075_align_strongbc_20260719 --topology topology1 --fault-pu 0.75 --duration-s 0.08 --teacher-source rule --dagger-iters 0 --switch-trace-repeat 128 --epochs 200 --bc-obs-noise-repeat 6 --collect-final-actor-trace --matlab-timeout-s 1200 --train-timeout-s 1200
```

Result:

- Score improved from `168.3` to `165.5`, but still did not beat/pass the
  baseline gate.
- Actor trace vs teacher trace:
  - `m_reg_d_mae`: `0.065`
  - `m_energy_d_mae`: `0.033`
  - `lv_rms_mae`: `4.53 V`
  - `vdc_mae`: `7.13 V`
- The main problem is not static BC loss; it is recovery/fault-window rollout
  drift.

Delayed-window trajectory follow-up:

```powershell
py -3 -m sac.validate_hpt_trajectory_switchlevel --run-id hpt_topo1_lvrt075_delayed_ds145_de185_20260719 --topology topology1 --fault-pu 0.75 --duration-s 0.08 --preset two_stage_window --base-action 0 0 0 0 --start-action 0.45 0 0 0 --action 0.45 0 0 0 --ramp-start 0.035 --step-time 0.040 --ramp-end 0.045 --down-start 0.145 --down-end 0.185 --timeout-s 1200
```

Result:

- The trajectory itself passes voltage-survival:
  - LV mean: `178.35 V`
  - LV recovery mean: `185.03 V`
  - Vdc min/max: `762.98 / 911.22 V`
- It does not beat conventional score (`179.6` vs `162.8`), but it proves a
  hand-designed fault-window action can survive the deeper sag.

BC actor from that delayed trajectory:

```powershell
py -3 -m sac.run_hpt_trajectory_specialist_campaign --run-id hpt_traj_specialist_topo1_lvrt075_delayed_20260719 --topology topology1 --fault-pu 0.75 --duration-s 0.08 --preset two_stage_window --base-action 0 0 0 0 --start-action 0.45 0 0 0 --action 0.45 0 0 0 --safe-target 0.45 0 0 0 --ramp-start 0.035 --step-time 0.040 --ramp-end 0.045 --down-start 0.145 --down-end 0.185 --dagger-iters 0 --switch-trace-repeat 96 --epochs 120 --bc-obs-noise-repeat 4 --collect-final-actor-trace --matlab-timeout-s 1200 --train-timeout-s 1200
```

Result:

- The BC actor failed badly:
  - LV mean dropped to `123.64 V`.
  - `m_reg_d` trace alignment MAE was `0.206`.
  - actor mean `m_reg_d` was only `0.057` vs teacher mean `0.237`.
- Interpretation:
  ordinary BC is not reliable for short fault-window pulse policies.  Training
  must overweight the fault window and preserve the delayed-down transition, or
  the controller needs an explicit state-machine/gating variable.

### topology2 / HVRT / 1.10 pu / 80 ms

- New specialist probe:
  `hpt_specialist_matrix_20260719_topology2_hvrt110_80ms_probe`
- Result: `diagnostic`
- Failure:
  - `dc_link_bounds`
  - `grid_current_limit`
  - reactive-current demand was not evaluated after the delay because the
    trajectory collapsed into a no-demand region.

Additional sweep:

```powershell
py -3 -m sac.campaigns.run_hpt_dynamic_trajectory_sweep --run-id hpt_boundary_sweep_topo2_hvrt110_energy_20260719 --topology topology2 --fault-pu 1.10 --duration-s 0.08 --reg-d-grid=0,-0.05 --reg-q-grid 0 --energy-d-grid=-0.30,-0.20,-0.10,-0.05 --energy-q-grid 0.002 --d-ramp-ms-grid 5 --q-ramp-ms-grid 20 --down-ms-grid 40 --max-cases 8 --timeout-s 1200
```

Result:

- Completed: `8 / 8`
- Voltage-survival pass: `0 / 8`
- Best trajectories lower the score relative to conventional but fail DC-link
  bounds, so they cannot be used as SAC teachers yet.

Rule-teacher follow-up:

```powershell
py -3 -m sac.run_hpt_trajectory_specialist_campaign --run-id hpt_rule_teacher_topo2_hvrt110_20260719 --topology topology2 --fault-pu 1.10 --duration-s 0.08 --teacher-source rule --dagger-iters 0 --switch-trace-repeat 64 --epochs 60 --bc-obs-noise-repeat 3 --matlab-timeout-s 1200 --train-timeout-s 600
```

Result:

- The actor almost reproduced the conventional score, but did not pass.
- Failure reason: `dc_link_bounds`.
- Interpretation:
  topology2/HVRT needs an explicit DC-link/energy-loop safe rollout objective.
  Pure BC from rule/DQ traces is not enough.

## Technical Interpretation

The useful progress is not a universal FRT controller yet.  It is a reliable
pipeline that can promote per-case switch-level voltage-survival actors and
separate them from diagnostic failures.

The main blocker is now clear:

1. LVRT voltage regulation can be learned for shallow and mid sag cases.
2. Full FRT fails mostly because grid-side reactive-current support and current
   limits are not satisfied.
3. Deeper LVRT and HVRT need a dynamic teacher derived from the conventional DQ
   controller or a redesigned energy/DC-link loop; fixed full-action teachers
   are not physically safe enough.

## Next Plan

1. Add conventional-trace teacher collection for failed boundary cases.
   Instead of fixed action labels, collect `policy_mode=0` rule/DQ action traces
   during `topology1_lvrt075` and `topology2_hvrt110`.
   This was implemented and tested; both cases still failed after insertion into
   the closed-loop switch-level model.
2. Add rollout-alignment evaluation for rule-teacher BC:
   compare teacher trace, actor trace, LV/Vdc waveforms, and action error along
   actor-visited states, not just static sampled states. This is now implemented
   through `--collect-final-actor-trace`.
3. Add fault-window weighted BC:
   oversample/weight fault and delayed recovery windows so the actor preserves
   short pulse actions instead of averaging them away.
4. Train BC warm-start actors from those conventional traces, then apply small
   residual action targets only inside switch-level validated safe regions.
5. Add a dynamic energy/DC-link constraint to the teacher label generator:
   reduce regulating action when `Vdc < 0.80 pu`, and prefer energy current
   recovery before voltage/recovery-window aggressiveness.
6. Re-run the specialist matrix with:
   - topology1: LVRT 0.75/0.85/0.90
   - topology2: LVRT 0.90/0.95 and HVRT 1.10
7. Only if the conventional-trace actor survives the switch-level gate, train a
   residual/SAC specialist to beat conventional score without violating DC link
   or grid-current constraints.

## Follow-up: Fault-Window DAgger BC

New code added after the first matrix run:

- `pretrain_hpt_actor_bc.py`
  - Added fault/recovery window repeat multipliers for switch trace BC.
  - Added trajectory-profile relabeling for actor-visited switch traces.
- `run_hpt_trajectory_specialist_campaign.py`
  - Added `--fault-window-repeat-mult` and
    `--recovery-window-repeat-mult`.
  - Added `--dagger-label-source trajectory`, so DAgger can use states from
    the actor rollout but labels from the same dynamic trajectory teacher.
  - Added `--action-weights` passthrough.
  - Added optional final actor trace collection and rollout alignment summary.

### topology1 / LVRT / 0.75 pu / 80 ms

Three variants were tested:

1. `hpt_traj_specialist_topo1_lvrt075_delayed_weighted_20260719`
   - Only fault/recovery oversampling.
   - Result: failed.
   - Actor still averaged the pulse away:
     `m_reg_d_mean = 0.066` vs teacher `0.237`.
2. `hpt_traj_specialist_topo1_lvrt075_delayed_daggertraj_20260719`
   - Added trajectory-label DAgger.
   - Result: failed but improved.
   - Best actor reached `policy_lv_mean = 163.82 V`.
3. `hpt_traj_specialist_topo1_lvrt075_delayed_daggertraj_clean_20260719`
   - Removed observation-noise augmentation and increased `m_reg_d` loss
     weight.
   - Result: closest boundary actor so far.
   - Best switch-level actor:
     - `policy_lv_mean = 175.36 V`
     - `policy_lv_recovery_mean = 199.49 V`
     - `policy_vdc_min = 765.90 V`
     - `policy_score = 169.86`
   - It still fails the voltage gate by roughly `0.65 V` on the aggregated
     fault-window metric.

Additional teacher search:

- `hpt_validate_topo1_lvrt075_spike060_hold045_20260719`
  validates a startup-spike teacher:
  `start_action=[0.60,0,0,0]`, `action=[0.45,0,0,0]`,
  `down_start=0.145`, `down_end=0.185`.
  The teacher itself passes voltage survival:
  `lv_mean=176.86 V`, `lv_recovery_mean=184.39 V`, `vdc_min=729.54 V`.
- The corresponding BC/DAgger actor
  `hpt_traj_specialist_topo1_lvrt075_spike060_hold045_daggertraj_clean_20260719`
  did not pass; the best actor over-injected in recovery and still failed
  `lv_fault_mean_bounds`.

Interpretation:

- Fault-window weighted BC alone is insufficient.
- Trajectory-label DAgger is useful and moves the closed-loop actor toward the
  teacher, but a memoryless actor still produces high-frequency action
  variation around the fault/recovery boundary.
- The next modeling change should be either:
  - add an explicit controller-stage feature / fault timer feature that is
    guaranteed consistent between Simulink and proxy, or
  - add a normal actuator-side action slew/low-pass block and train/evaluate
    with that same dynamic action interface.

Current promoted specialist set is unchanged:

- topology1 LVRT 0.90: voltage-survival specialist.
- topology2 LVRT 0.95: voltage-survival specialist.
- topology2 LVRT 0.90: voltage-survival specialist.

No topology1 LVRT 0.75 specialist is promoted yet.

## Follow-up: Actor Execution Smoothing

The deep-LVRT actor trace showed high-frequency action variation at the
fault/recovery boundary.  The HPTSACController already keeps `last_act`, but
there was no actor-side actuator dynamic.  A 1-ms first-order action smoothing
stage was added only for actor modes:

- `policy_mode >= 0.5`
- `actor_select_mode >= 1.5`

This does not affect:

- `conventional_dq`
- fixed-action validation
- trajectory-teacher validation

Re-test after rebuilding the switch-level model:

```powershell
py -3 -m sac.export_hpt_sac_actor --model data/models/hpt_traj_specialist_topo1_lvrt075_delayed_daggertraj_clean_20260719_dagger2.zip --out simulink/hpt_sac_actor_weights_dynamic.mat
matlab --% -batch "cd('E:/research_space/Hybrid-power-transformer/simulink'); hpt_compare_topology='topology1'; hpt_compare_scenario_type='fault'; hpt_compare_case_name='lvrt_080ms_0p750pu'; hpt_compare_faults={'lvrt_080ms_0p750pu',0.75,0.08}; hpt_compare_modes={'conventional_dq','sac_actor_raw_guard0'}; hpt_compare_run_label='smooth_check2_topo1_lvrt075_dagger2'; eval_hpt_v2_control_comparison"
```

Result:

- `sac_actor_raw_guard0`
  - `voltage_survival_pass = 1`
  - `lv_mean = 177.13 V`
  - `lv_recovery_mean = 205.99 V`
  - `vdc_min = 764.85 V`
  - `control_score = 163.88`
- `conventional_dq`
  - `voltage_survival_pass = 1`
  - `lv_mean = 176.00 V`
  - `lv_recovery_mean = 191.30 V`
  - `vdc_min = 760.91 V`
  - `control_score = 162.76`

Interpretation:

- topology1 / LVRT 0.75 now has a switch-level voltage-survival SAC
  specialist candidate.
- It is not yet a full-FRT success because both SAC and conventional still fail
  `gbt_recover`, `grid_current_limit`, and `reactive_wrong_sign`.
- It is not yet a strict "beats conventional" result on the aggregate score,
  but it has better fault-window LV mean and better Vdc minimum.

## Follow-up: Q-Aware Topology2 LVRT 0.925 Specialist

The accepted topology2/LVRT 0.925 actor was upgraded from the previous q=0
candidate to a q-aware candidate.  A focused switch-level probe around the
successful voltage-survival island found that small negative `m_reg_q` is the
useful direction for LVRT reactive-current support in the current topology2
model.  Larger negative q commands improve the reactive direction more, but
they either drain the DC link or pull the LV fault-window mean below the
survival threshold.

Accepted teacher command:

```text
[m_reg_d, m_reg_q, m_energy_d, m_energy_q] = [0.21, -0.04, 0.02, 0.002]
```

Training command:

```powershell
py -3 -m sac.run_hpt_trajectory_specialist_campaign --run-id hpt_traj_specialist_topo2_lvrt0925_qaware_20260719 --topology topology2 --fault-pu 0.925 --duration-s 0.08 --fault-start 0.035 --fault-stop-margin 0.125 --teacher-source trajectory --preset constant --decision-dt 0.002 --base-action 0 0 0 0 --start-action 0 0 0 0 --action 0.21 -0.04 0.02 0.002 --safe-target 0.21 -0.04 0.02 0.002 --dagger-iters 1 --switch-trace-repeat 3 --window-zones fault,recovery --epochs 220 --batch-size 256 --lr 0.0008 --action-weights 1.0,2.0,8.0,4.0 --fault-window-repeat-mult 4 --recovery-window-repeat-mult 4 --dagger-label-source safe_target --collect-final-actor-trace --matlab-timeout-s 300 --train-timeout-s 900
```

Result:

- Best actor: `bc0`, not `dagger1`.
- Model:
  `data/models/hpt_traj_specialist_topo2_lvrt0925_qaware_20260719_bc0.zip`
- SAC score / conventional score: `140.000 / 279.629`.
- LV mean / recovery: `176.32 / 219.33 V`.
- DC link min / max: `788.03 / 977.05 V`.
- `grid_iq_mean_pu`: `0.0396`.
- `grid_iq_shortfall_max_pu`: `0.3304`.
- `grid_current_peak_pu`: `1.736`.

The q-aware actor passes the voltage-survival gate and beats conventional, and
it improves the reactive-current direction relative to the previous q=0 actor.
It still fails full FRT because the reactive support is not sustained enough
and the grid-current peak remains above the current full-FRT limit.

The accepted manifest was updated and revalidated:

```powershell
py -3 -m sac.validate_hpt_accepted_specialists --run-id hpt_accepted_specialist_validation_qaware_20260719 --timeout-s 900
```

Revalidation summary:

- Cases: `4`.
- Voltage-survival pass: `4 / 4`.
- Beats conventional: `2 / 4`.
- Full FRT pass: `0 / 4`.

## Follow-up: Topology2 HVRT Boundary Probe

Additional topology2/HVRT 1.12 fixed-action probes were run around negative
`m_energy_d` and small q commands.  None passed the voltage-survival gate.  In
the current switch-level model, simple negative energy commands pushed the
DC-link peak to about `1135 V`, so these points are not safe SAC teachers.

Interpretation:

- The topology2 HVRT branch is not ready for specialist SAC training from
  fixed full-action labels.
- The next HVRT step must recalibrate the topology2 energy/DC-link response or
  introduce a separate DC-link-safe teacher before training an actor.

## Follow-up: Topology1 HVRT 1.18 Specialist

Topology1/HVRT 1.18 was a better HVRT boundary case: conventional DQ fails the
current voltage-survival gate because of DC-link bounds, while several
mid-range fixed actions pass.  The best fixed teacher tested was:

```text
[m_reg_d, m_reg_q, m_energy_d, m_energy_q] = [0.145, 0, 0.08, 0]
```

Training command:

```powershell
py -3 -m sac.run_hpt_trajectory_specialist_campaign --run-id hpt_traj_specialist_topo1_hvrt118_20260719 --topology topology1 --fault-pu 1.18 --duration-s 0.08 --fault-start 0.035 --fault-stop-margin 0.125 --teacher-source trajectory --preset constant --decision-dt 0.002 --base-action 0 0 0 0 --start-action 0 0 0 0 --action 0.145 0 0.08 0 --safe-target 0.145 0 0.08 0 --dagger-iters 1 --switch-trace-repeat 3 --window-zones fault,recovery --epochs 220 --batch-size 256 --lr 0.0008 --action-weights 2.0,1.0,6.0,2.0 --fault-window-repeat-mult 4 --recovery-window-repeat-mult 4 --dagger-label-source safe_target --collect-final-actor-trace --matlab-timeout-s 300 --train-timeout-s 900
```

Best actor:

```text
data/models/hpt_traj_specialist_topo1_hvrt118_20260719_bc0.zip
```

Switch-level result:

- SAC score / conventional score: `143.790 / 155.854`.
- LV mean / recovery: `210.36 / 185.64 V`.
- DC link min / max: `762.74 / 904.16 V`.
- The actor passes voltage-survival and beats conventional.
- Full FRT still fails due `gbt_recover`, `grid_current_limit`, and
  `reactive_wrong_sign`.

This is the first accepted HVRT specialist in the HPT2.0 matrix.

