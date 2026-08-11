# HPT Direct SAC Trajectory Autoresearch Progress - 2026-07-18

## Objective

Move from fixed-state/fixed-action validation to trajectory-level direct HPT
control:

- Simulink switch-level model receives a time-varying 4-D action trajectory.
- SAC actor action contract remains `[m_reg_d, m_reg_q, m_energy_d, m_energy_q]`.
- The first target case is `topology2 / LVRT / 0.95 pu / 80 ms`.
- The first promotion gate is voltage-survival and score improvement over
  `conventional_dq`; full GBT-style FRT remains the final gate.

## Implemented

- Added `trajectory_action` mode in `HPTSACController`.
  - `hpt_sac_policy_mode = -2`.
  - Reads `hpt_sac_trajectory.mat` containing `hpt_traj_t` and
    `hpt_traj_action`.
- Added `sac_actor_always_raw` evaluation mode.
  - Actor is active from simulation start.
  - This is the correct mode for direct SAC control experiments.
  - It avoids the old hidden assumption that the dynamic actor is enabled
    only after fault detection.
- Added trajectory tools:
  - `sac/build_hpt_action_trajectory.py`
  - `sac/validate_hpt_trajectory_switchlevel.py`
  - `simulink/collectors/collect_hpt_v2_trajectory_trace.m`
- Updated SAC interface regression to cover `policy_mode = -2`.

## Switch-Level Results

Case: `topology2 / LVRT / 0.95 pu / 80 ms`.

| Run | Mode | Voltage Survival | Score | LV Mean | LV Recovery | Vdc Min | Vdc Max | Notes |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| conventional baseline | `conventional_dq` | pass | 239.88 | 199.32 | 214.54 | 683.00 | 998.54 | Full FRT fails reactive/current/envelope checks. |
| constant trajectory | `trajectory_action` | pass | 127.58 | 194.95 | 220.89 | 728.73 | 995.45 | Exact match to fixed action. |
| all-window BC actor | `sac_actor_always_raw` | fail | 129.17 | 194.94 | 220.67 | 765.18 | 1008.20 | Better than baseline, but DC-link upper bound fails. |
| DAgger1 actor | `sac_actor_always_raw` | fail | 128.23 | 195.10 | 221.91 | 665.17 | 1005.74 | Better score, still DC-link upper bound; lower Vdc margin. |
| DAgger2 actor | `sac_actor_always_raw` | fail | 128.68 | 194.98 | 220.77 | 736.75 | 1005.68 | Balanced but still DC-link upper bound. |
| DAgger3 noisy actor | `sac_actor_always_raw` | fail | 127.40 | 194.89 | 221.91 | 646.09 | 1000.97 | Nearly best score, but DC-link lower/upper margins fail. |
| DAgger4 Vdc-feedback actor | `sac_actor_always_raw` | pass | 127.85 | 194.99 | 220.86 | 716.15 | 999.56 | First direct actor to pass voltage-survival and beat conventional. |
| fault-window trajectory | `trajectory_action` | fail | 115.44 | 202.63 | 207.51 | 783.66 | 1006.65 | Best score so far, but DC-link upper bound fails. |

## Autoresearch Update

The reusable trajectory-specialist campaign is now implemented in
`sac/run_hpt_trajectory_specialist_campaign.py`.

Engineering fixes:

- Fixed switch-trace case filtering so `lvrt_080ms_0.950pu` and
  `lvrt_080ms_0p950pu` both match.
- Added a hard failure when BC training receives zero switch-level samples.
  The first smoke run silently trained with `samples=0`; that result is invalid.
- Fixed campaign promotion logic so the final exported actor is the best
  evaluated model, not always the last DAgger iteration.  This matters because
  DAgger can improve one topology but degrade another.

New switch-level specialist results:

| Case | Traditional Baseline | Fixed/Trajectory Teacher | Best Actor | Result |
| --- | ---: | ---: | ---: | --- |
| `topology2 / LVRT / 0.95 pu / 80 ms` | pass, score `239.88` | pass, score `127.58` | DAgger1, score `127.02` | Actor passes voltage-survival and beats baseline. |
| `topology2 / LVRT / 0.90 pu / 80 ms` | fail, score `296.53` | pass, score `135.13` | DAgger1, score `135.70` | Actor passes voltage-survival while baseline fails. |
| `topology1 / LVRT / 0.90 pu / 80 ms` | pass, score `152.69` | pass, score `145.31` | BC0, score `150.76` | Actor passes voltage-survival and slightly beats baseline. |
| `topology2 / HVRT / 1.10 pu / 80 ms` | `12/12` candidate sweeps pass baseline | `0/12` fixed candidates pass | not trained | Treat as a traditional-baseline strong case for now. |

Important interpretation:

- The autoresearch loop can now create continuous 2-ms action trajectories,
  collect switch-level state/action traces, train a direct actor, and verify the
  actor in switch-level Simulink.
- The strongest current evidence is for LVRT specialists, not one unified SAC.
- Full GB/T FRT still fails because recovery envelope, grid-current limit, and
  reactive-current support/sign are not yet solved.
- HVRT requires a different action search/control law.  The simple negative
  `m_reg_d` sweep degraded voltage-survival while the traditional baseline
  already passed.

Reactive-current exploration:

- Added q-axis support to `build_hpt_local_action_sweep.py`.
- For `topology2 / LVRT / 0.90 pu / 80 ms`, constant `m_reg_q=0` preserves
  voltage-survival but fails reactive-current direction.
- Constant negative q can make the reactive-current status pass:
  - Example: `m_reg_d=0.172`, `m_reg_q=-0.300`, `m_energy_d=0.010`
    gives `gbt_reactive_status=pass`.
  - But it fails LV fault-window mean and/or DC-link survival.
- A two-stage trajectory was added to test delayed q injection:
  - `two_stage`: base -> voltage support -> voltage+q support.
  - `two_stage_window`: same, then down-ramp after fault clearing.
- Delayed q reduced the score and reactive shortfall, but still failed
  voltage-survival because Vdc exceeded the upper bound.
- Fast post-fault down-ramp made DC-link oscillation worse
  (`Vdc min/max ~= 375/1111 V` in the first test).
- Sweeping `m_energy_q` in the two-stage trajectory did not materially change
  the limiting `Vdc max ~= 1005.6 V`; it only changed LV/score slightly.

Dynamic trajectory sweep update:

- Added `sac/run_hpt_dynamic_trajectory_sweep.py` to run compact
  switch-level trajectory matrices and summarize the same promotion metrics
  used by `validate_hpt_trajectory_switchlevel`.
- Completed
  `hpt_dynamic_traj_sweep_topo2_lvrt090_tradeoff_20260718`:
  - topology: `topology2`
  - fault: `LVRT 0.90 pu / 80 ms`
  - cases: `12/12` completed
  - voltage-survival passes: `0/12`
  - full-FRT passes: `0/12`
- Best score was:
  `m_reg_d=0.25`, `m_reg_q=-0.4`, `m_energy_d=-0.02`,
  `m_energy_q=0.002`, `d_ramp=20 ms`, `q_ramp=40 ms`.
  - score: `119.54`
  - LV mean: `192.17 V`
  - LV recovery mean: `211.17 V`
  - Vdc range: `783.66-1005.62 V`
  - reactive status: `reactive_wrong_sign`
  - full-FRT reason:
    `gbt_voltage_envelope;gbt_recover;gbt_vdc_survive;grid_current_limit;reactive_wrong_sign`
- Interpretation:
  - More negative `m_reg_q` improves the objective and reduces reactive-current
    shortfall, but pushes the case out of the voltage-survival gate because
    DC-link upper-bound survival fails.
  - Raising `m_reg_d` from `0.172` to `0.25` improves recovery voltage and the
    score, but does not solve the DC-link or GB/T reactive-current criteria.
  - The tested static `m_energy_d/q` offsets do not provide enough dynamic
    damping for topology2 LVRT reactive support.

State-gated q-label update:

- Added q-axis label gating to `pretrain_hpt_actor_bc.py` and
  `run_hpt_trajectory_specialist_campaign.py`.
- Purpose:
  - preserve the full-action contract `[m_reg_d, m_reg_q, m_energy_d, m_energy_q]`;
  - keep `m_reg_q=0` while LV voltage or Vdc margin is unsafe;
  - allow negative `m_reg_q` only after the fault trajectory enters a safer
    support region.
- New training arguments:
  - `--q-gate-lv-min-pu`
  - `--q-gate-time-min-s`
  - `--q-gate-vdc-min-pu`
  - `--q-gate-vdc-max-pu`

Gated-q switch-level campaigns:

| Run | Label Strategy | Voltage Pass | Score | LV Mean | LV Recovery | Vdc Min/Max | Full-FRT Reason |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| `topology2_lvrt090_qm03_vdcfb` DAgger1 | no q gate, `m_reg_d=0.172`, `q=-0.3` | fail | `180.94` | `129.92` | `211.24` | `346.09/1036.21` | `gbt_voltage_envelope;gbt_recover;gbt_vdc_survive;grid_current_limit` |
| `topology2_lvrt090_rd025_qm03_vdcfb08` DAgger1 | no q gate, `m_reg_d=0.25`, `q=-0.3` | fail | `150.31` | `136.27` | `181.75` | `729.35/937.57` | `gbt_voltage_envelope;gbt_recover;grid_current_limit` |
| `topology2_lvrt090_rd025_qm03_gatedq` DAgger1 | strict gate: `LV>=0.88 pu`, `t>=75 ms` | fail | `144.22` | `183.90` | `215.58` | `796.57/1012.12` | `gbt_voltage_envelope;gbt_recover;gbt_vdc_survive;grid_current_limit;reactive_wrong_sign` |
| `topology2_lvrt090_rd025_qm03_gatedq2` DAgger1 | relaxed gate: `LV>=0.70 pu`, `t>=55 ms` | pass | `181.46` | `193.08` | `226.99` | `797.45/965.02` | `gbt_voltage_envelope;gbt_recover;grid_current_limit;reactive_wrong_sign` |

Interpretation:

- Negative q is physically active: the aggressive no-gate cases remove
  `reactive_wrong_sign`, but they over-prioritize q and collapse LV fault mean.
- State-gated q labels restore LV and DC-link survival.
- The relaxed gate is currently the best compromise:
  - it passes staged voltage-survival;
  - it beats the failed conventional baseline on the LVRT 0.90 case;
  - it still does not satisfy full GB/T reactive-current support.
- The next label/controller iteration should increase q support only in the
  later part of the fault/recovery window or use a continuous q target rather
  than binary `q=0` vs `q=-0.3`.

Implication:

- Full FRT is now limited by coupled reactive-current and DC-link dynamics, not
  by the trajectory interface.
- The next controller needs an explicit dynamic tradeoff: delay/shape q-axis
  support while actively damping DC-link energy, instead of cloning a constant
  full-action target.
- For topology2, the energy branch still needs a dynamic response model or a
  direct Simulink-in-loop optimizer; simple fixed `m_energy_d/q` labels are not
  enough for full-FRT training.

## What This Proves

- The new trajectory interface works: constant trajectory is exactly
  equivalent to fixed-action mode at switch level.
- Direct always-on actor control is now testable in the same switch-level
  comparison framework.
- Switch-level trajectory samples can train a 24-D/4-D actor:
  - BC error reached `~1e-8` to `~1e-7` action MSE.
  - The actor reproduces the successful control region well enough to reduce
    score from `239.88` to about `128-129`.
- DAgger-style closed-loop state collection is necessary.
  - Training only on open-loop trajectory states causes closed-loop action
    peaks and DC-link overshoot.
- Adding local observation-neighborhood BC augmentation plus a Vdc-feedback
  energy label produced the first direct actor that passes the staged
  voltage-survival gate.

## What Is Not Done

- No actor has passed full GBT-style FRT yet.
- Full GBT-style FRT is not passed.
  - Existing failures include voltage envelope, recovery, current limit, and
    reactive-current sign/support.
- The current successful actor is a topology/scenario specialist:
  `topology2 / LVRT / 0.95 pu / 80 ms`.
- This is still BC/DAgger warm-start, not final SAC reinforcement fine-tuning.

## Interpretation

The fixed/trajectory command has a real successful switch-level operating
point.  A neural actor can reproduce it only after closed-loop DAgger data are
added.  The decisive fix was to label energy action as a function of measured
Vdc, not as a fixed scalar.  This lets the actor keep Vdc inside the staged
survival window while still using the regulating bridge to recover LV voltage.

## Next Autoresearch Plan

1. Preserve DAgger4 as the current promoted voltage-survival specialist:
   `hpt_sac_actor_weights_topology2_lvrt095_dagger4.mat`.
2. Generate a small family of shaped trajectories around the successful region:
   - pre-fault target vs zero pre-fault,
   - ramp-in duration `5/10/20 ms`,
   - recovery ramp-out,
   - reg_d around `0.160-0.176`,
   - energy_d around `0.000-0.030`.
3. Run switch-level validation for those shaped trajectories and select only
   trajectories that pass voltage survival.
4. Collect switch-level traces from the passing trajectories.
5. Train actor with mixed DAgger data:
   - successful open-loop trajectory states,
   - actor-visited states,
   - explicit DC-link over/under states with corrected labels.
6. Add a behavior-regularized SAC stage only after the BC actor passes the
   voltage-survival gate.
7. Re-run switch-level comparison:
   - `conventional_dq`
   - `trajectory_action`
   - `sac_actor_always_raw`
8. Promote only if the actor passes voltage survival and beats conventional
   on score.  Full GBT reactive-current/current-limit checks remain the next
   certification phase.

