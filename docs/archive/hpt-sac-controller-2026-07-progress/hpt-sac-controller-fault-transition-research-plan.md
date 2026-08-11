# HPT SAC Fault-Transition Research Plan

Last updated: 2026-07-14

## Purpose

Extend the version 2 HPT SAC controller from steady sag/swell regulation to
fault-transition ride-through:

- pre-fault operation
- fault detection and entry
- fault hold regulation
- fault clearing
- post-fault recovery

The source of truth for final claims remains the version 2 pure physical
switch-level Simulink models in `simulink`.

## Reference Basis

Local references reviewed:

- `references/week1/娣峰悎寮忕數鍔涘彉鍘嬪櫒澶氬伐浣滄ā寮忔帶鍒剁瓥鐣ョ爺绌禵瀹嬪垢.pdf`
  - HPT contains an electromagnetic transformer, an energy converter, and a
    regulating converter sharing a DC link.
  - The energy converter maintains DC-link voltage and can provide shunt
    reactive compensation.
  - The regulating converter injects a controllable series voltage and is the
    main voltage-regulation actuator.
  - Without independent long-duration energy storage, active power exchange
    must be balanced between regulating and energy converters.

- `references/week2/鍩轰簬娣峰悎鍙樺帇鍣ㄧ數鍘嬫敮鎾戠殑鍙岄椋庣數鏈虹粍鏁呴殰绌胯秺鎺у埗绛栫暐_璧栭敠鏈?pdf`
  - Normal operation uses a shunt/parallel mode for smoothing.
  - Fault operation switches to a series compensation mode when voltage is
    outside the approximate normal band, below 0.9 pu or above 1.1 pu.
  - The transition must be flexible/bumpless to avoid overvoltage and
    overcurrent during switching.
  - The injected voltage command is based on the difference between the
    desired terminal voltage and the measured grid-side voltage.

- `references/week1/鍩轰簬鐢垫祦鍗忓悓浼樺寲鐨勬煍鐩磋緭鐢电郴缁熷彈绔崲娴佺珯鏁呴殰绌胯秺鎺у埗鏂规硶_璐剧.pdf`
  - FRT control must coordinate voltage support with active/DC-link energy
    balance.
  - Pure reactive priority can create DC-link stress if active power imbalance
    is ignored.
  - Detection delay and measurement error should be explicitly represented.
  - Energy dissipation/chopper action should be considered for severe or
    long-duration events.

- `src/hpt_frt/common/frt_v2.py` and `docs/FRT_SPEC.md`
  - LVRT/HVRT envelope logic:
    - LVRT lower envelope: hold residual for 625 ms, recover to 0.9 pu by 2 s.
    - HVRT upper envelope: 1.3 pu up to 500 ms, 1.2 pu up to 1 s, then 1.1 pu.
  - Reactive support uses signed minimum-support logic:
    - under-voltage: inject positive reactive support.
    - over-voltage: absorb reactive support.
  - Mandatory certification signals include voltage envelope, reactive support,
    current limit, recovery, DC-link survival, and negative-sequence current.

## Current State

Implemented:

- 16-D observation / 4-D action control interface.
- Unified action:
  - `m_reg_d`, `m_reg_q`
  - `m_energy_d`, `m_energy_q`
- SAC actor trained on a steady averaged surrogate.
- Actor export to `simulink/hpt_sac_actor_weights.mat`.
- Simulink interface test for topology1 and topology2.

Not yet implemented:

- Time-varying fault profile in the version2 SAC environment.
- Online fault-transition state estimator.
- Mode-transition logic with hysteresis, timers, slew limits, and bumpless
  transfer.
- Switch-level closed-loop sag/swell transient certification with SAC enabled.

## Recommended Controller Architecture

Keep the 4-D action interface:

```text
[m_reg_d, m_reg_q, m_energy_d, m_energy_q]
```

Expand the observation interface for fault-transition learning. The current
16-D observation is enough for steady regulation but weak for transition
control because it does not tell the actor how long the system has been in a
fault or recovery state.

Recommended observation: 24-D

```text
existing 16:
  v_lv_rms_pu
  v_pos_pu
  v_neg_pu
  vdc_pu
  vdc_err_pu
  v_err_pu
  energy_id_pu
  energy_iq_pu
  last_m_reg_d
  last_m_reg_q
  last_m_energy_d
  last_m_energy_q
  sag_flag
  swell_flag
  reg_headroom
  energy_headroom

new 8:
  fault_active_est
  recovery_active_est
  t_fault_est_pu
  t_recovery_est_pu
  v_fault_min_pu
  v_fault_max_pu
  dv_pos_dt_pu
  d_vdc_dt_pu
```

All new signals must be derived online from measured voltage/DC-link signals,
not from privileged scenario labels.

## Fault-Transition Supervisor

The SAC actor should sit behind a deterministic safety/supervisory layer.

Modes:

- `NORMAL`
  - voltage within normal deadband.
  - actions ramp toward normal small-signal regulation.

- `FAULT_ENTRY`
  - detected by filtered positive-sequence voltage crossing:
    - sag entry: `v_pos < 0.92 pu`
    - swell entry: `v_pos > 1.08 pu`
  - latch with debounce to avoid chatter.
  - initialize timers and last-action states.

- `FAULT_HOLD`
  - active compensation during voltage abnormality.
  - actor output is safety-projected for sign consistency.

- `RECOVERY`
  - entered when voltage returns into a hysteresis band:
    - sag exit: `v_pos > 0.97 pu`
    - swell exit: `v_pos < 1.03 pu`
  - ramp injected series voltage down smoothly.
  - prioritize DC-link restoration and current limiting.

Safety projection:

- Under-voltage:
  - enforce `m_reg_d >= 0` unless voltage is already above target.
  - prevent reactive wrong-sign action.

- Over-voltage:
  - enforce `m_reg_d <= 0` unless voltage is already below target.
  - prevent reactive wrong-sign action.

- DC-link emergency:
  - if `vdc < 0.82 pu`, reduce regulating effort and increase energy-side
    active support.
  - if `vdc > 1.12 pu`, reduce energy charging and allow chopper/dissipation
    behavior in the plant model.

- Slew-rate limit:
  - bound per-step changes of all four actions.
  - use tighter bounds during `FAULT_ENTRY` and `RECOVERY`.

## Training Environment Changes

Update `sac/hpt_voltage_sac_env.py`.

Add a scenario structure with:

- topology: `topology1` or `topology2`
- event type:
  - `lvrt_3ph`
  - `lvrt_asym`
  - `hvrt_3ph`
  - `hvrt_asym`
- pre-fault grid voltage: normally 1.0 pu
- fault onset time: randomized, for example 20 ms to 80 ms
- fault duration:
  - short smoke: 100 ms to 250 ms
  - full LVRT curriculum: up to 625 ms hold
- residual/swell magnitude:
  - LVRT: 0.2, 0.5, 0.75, 0.85, 0.9 pu
  - HVRT: 1.1, 1.2, 1.3 pu
- negative-sequence level for asymmetric faults
- weak-grid/topology gain variation
- DC-link initial condition variation

Fault voltage profile:

- pre-fault: 1.0 pu
- fault entry: finite ramp rather than ideal step
- fault hold: residual or swell level
- clearing: finite recovery slope
- post-fault: return to 1.0 pu

State dynamics to add:

- measurement filter lag
- PLL/sequence-estimation lag approximation
- regulating converter lag
- energy converter/DC-link lag
- action-dependent DC-link droop/overshoot during fault clearing
- negative-sequence persistence during asymmetric faults

Reward terms:

- voltage tracking during load-side ride-through
- LVRT/HVRT envelope margin
- DC-link survival, strong penalty outside `[0.75, 1.25] pu`
- post-clear recovery within +/-7 percent
- reactive sign correctness
- current/action magnitude limit
- action slew penalty
- bumpless transition penalty at fault entry/clear

## Simulink Validation Changes

Add a new validation script:

```text
simulink/tests/test_hpt_v2_sac_fault_transition.m
```

For both topology1 and topology2:

- rebuild model
- set:
  - `hpt_sac_enable = 1`
  - `hpt_sac_policy_mode = 1`
- apply time-varying grid voltage scenarios
- log:
  - LV phase RMS / positive sequence
  - negative sequence
  - Vdc
  - SAC observation
  - SAC action
  - converter command RMS/slew

Initial smoke scenarios:

- sag: 1.0 -> 0.85 pu -> 1.0
- deep sag: 1.0 -> 0.50 pu -> 1.0
- swell: 1.0 -> 1.15 pu -> 1.0
- severe swell: 1.0 -> 1.25 pu -> 1.0

Final certification scenarios:

- LVRT residual set: 0.2, 0.5, 0.75, 0.85 pu
- HVRT set: 1.1, 1.2, 1.3 pu
- balanced and asymmetric variants
- weak and strong grid cases
- topology1 and topology2

Acceptance criteria:

- no Simulink errors or non-finite signals
- action bounds respected:
  - regulating: `abs(m_reg_d/q) <= 0.8`
  - energy: `abs(m_energy_d/q) <= 0.95`
- DC link remains inside `[0.75, 1.25] pu`
- post-clear LV voltage settles within +/-7 percent
- no wrong-sign sag/swell support after response delay
- recovery action is bumpless: no large command step at clearing

## Training Plan

Phase 0 - freeze interface

- Decide whether to expand observation from 16-D to 24-D.
- Keep 4-D action unchanged.
- Update Python tests and Simulink actor loader to enforce the frozen shape.

Phase 1 - averaged fault-transition environment

- Implement time-varying fault profiles.
- Add online fault-state estimator and timers.
- Add transition-aware reward.
- Add unit tests for sag/swell entry, clearing, and recovery.

Phase 2 - teacher/fallback transition control

- Extend `teacher_action` to be transition-aware.
- Verify deterministic teacher produces:
  - positive boost for sag
  - negative buck for swell
  - DC-link recovery support after clearing
  - smooth ramp-down in recovery

Phase 3 - SAC fine-tuning

- Initialize from the current version2 SAC actor if the observation dimension is
  preserved.
- If observation expands to 24-D, train a new actor and optionally initialize
  the old 16-D subnetwork weights.
- Curriculum:
  - 100k steps: shallow sag/swell transitions
  - 200k steps: deep sag and severe swell
  - 200k steps: asymmetric/negative-sequence cases
  - 100k steps: randomized topology and DC-link parameter variation

Phase 4 - switch-level smoke validation

- Run 4 short scenarios per topology.
- Use short fault durations first to avoid long iteration time.
- Compare:
  - old PI/dq controller
  - transition teacher
  - trained SAC actor

Phase 5 - switch-level certification sweep

- Run full LVRT/HVRT matrix on topology1 and topology2.
- Produce CSV/JSON summary with pass/fail per criterion.
- Keep only the best successful trained switch-level actor export.

## Key Risk Items

- Direct training on switch-level Simulink is too slow for first iteration.
  Use averaged training plus switch-level validation, then calibrate the
  surrogate from Simulink failures.

- The current 16-D observation may hide fault timing from the actor.
  Recommended fix is 24-D observation.

- Topology2 may need different calibration because series/energy converter
  directions and gains differ.
  Keep one shared actor but include topology randomization/gain variation.

- Severe HVRT can cause DC-link undershoot or overshoot after clearing.
  Reward and safety projection must explicitly include DC-link survival.

- Wrong-sign support near the 0.9/1.1 pu boundary can fail FRT criteria.
  Use sign-consistent deadband/projection.

## Decision Required Before Implementation

Recommended choice:

- Expand observation to 24-D.
- Keep the action at 4-D.
- Retrain the actor for fault-transition operation.

Alternative:

- Keep the old 16-D observation and encode transition behavior only through
  sag/swell flags and last action.
- This preserves the old interface but is less robust for clearing and
  post-fault recovery.

