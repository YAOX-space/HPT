# HPT SAC Controller System And Architecture

Last updated: 2026-07-14

## Objective

Build one topology-neutral SAC controller interface for the two final switch-level HPT models:

- `simulink/topoloty1/hpt_v2_1to1_switchlevel.slx`
- `simulink/topology2/hpt_v2_topology2_paper.slx`

The controller must regulate the low-voltage bus to nominal voltage while keeping the shared DC link and converter modulation inside safe limits. The same actor shape is used for both topologies so a policy can be trained on one topology and fine-tuned on the other without changing the deployment interface.

Nominal target:

- Phase RMS voltage: `230 V`
- Line-line RMS voltage: `400 V`
- DC link reference: `800 V`

## Interface Contract

### Observation

The HPT SAC observation is 16-D:

| Index | Name | Unit | Definition |
|---:|---|---|---|
| 1 | `v_lv_rms_pu` | pu | filtered phase RMS / 230 V |
| 2 | `v_pos_pu` | pu | positive-sequence peak / `(sqrt(2)*230)` |
| 3 | `v_neg_pu` | pu | negative-sequence peak / `(sqrt(2)*230)` |
| 4 | `vdc_pu` | pu | DC-link voltage / 800 V |
| 5 | `vdc_err_pu` | pu | `(800 - Vdc) / 800` |
| 6 | `v_err_pu` | pu | `(230 - Vlv_rms) / 230` |
| 7 | `energy_id_pu` | pu | energy-converter d-current peak / system current peak |
| 8 | `energy_iq_pu` | pu | energy-converter q-current peak / system current peak |
| 9 | `last_m_reg_d` | pu | previous regulating d-axis modulation |
| 10 | `last_m_reg_q` | pu | previous regulating q-axis modulation |
| 11 | `last_i_energy_d_ref` | pu | previous energy d-axis current-reference command |
| 12 | `last_i_energy_q_ref` | pu | previous energy q-axis current-reference command |
| 13 | `sag_flag` | 0/1 | `v_lv_rms_pu < 0.97` |
| 14 | `swell_flag` | 0/1 | `v_lv_rms_pu > 1.03` |
| 15 | `reg_headroom` | pu | regulating modulation headroom |
| 16 | `energy_headroom` | pu | energy modulation headroom |

All observation elements are clipped to `[-5, 5]` before actor inference.

### Action

The HPT SAC action is 4-D and uses one unified physical meaning: normalized voltage modulation commands.

| Index | Name | Range | Meaning |
|---:|---|---|---|
| 1 | `m_reg_d` | `[-0.8, 0.8]` | regulating converter d-axis series voltage command |
| 2 | `m_reg_q` | `[-0.8, 0.8]` | regulating converter q-axis series voltage command |
| 3 | `i_energy_d_ref_pu` | `[-0.95, 0.95]` | normalized TPFBVSC d-axis current reference |
| 4 | `i_energy_q_ref_pu` | `[-0.95, 0.95]` | normalized TPFBVSC q-axis current reference |

The actor does not output PWM gates directly. The deployment layer converts the four modulation commands to three-phase SPWM references and then to IGBT gate signals.

## Control Architecture

The controller has three layers:

1. Measurement and observation builder
   - Computes RMS, sequence magnitudes, DC-link state, energy-converter dq current, flags, and last-action memory.

2. High-level SAC policy
   - Final mode: deterministic actor inference from exported `hpt_sac_actor_weights.mat`.
   - Bootstrap mode: same 16/4 interface with a rule-based teacher used only for interface testing and initial data generation.

3. Low-level execution
   - `m_reg_d/m_reg_q` are converted to six H-bridge modulation references for the regulating bridge.
   - `i_energy_d_ref_pu/i_energy_q_ref_pu` are tracked by the energy-bridge dq current loop, which then generates three PWM modulation references for the TPFBVSC.
   - Chopper and modulation saturation remain hard safety layers.

## Acceptance Criteria

Initial interface and model-construction tests:

- Both topology builders create an `HPTSACController` subsystem.
- The subsystem outputs a 16-D observation and 4-D action.
- Existing pure switch-level regressions still pass with `hpt_sac_enable = 0`.
- Both topologies simulate with `hpt_sac_enable = 1` in bootstrap-teacher mode.
- SAC action signals remain within configured modulation bounds.

Final training criteria, after SAC training is run:

- `Vlv_phase_rms` settles near `230 V` for sag, nominal, and swell grid cases.
- Phase unbalance remains low under balanced sag/swell tests.
- Mean DC link remains inside `800 V` to `900 V`; transient survival remains inside `750 V` to `950 V`.
- No non-physical average injection source or debug clamp is introduced.

## Research Plan

1. Build the topology-neutral interface.
   - Freeze 16-D observation and 4-D modulation action.
   - Add the same controller subsystem to topology1 and topology2 builders.

2. Train on a fast HPT-specific surrogate.
   - Use the averaged Python environment in `sac/hpt_voltage_sac_env.py`.
   - Start with mixed topology randomization.
   - Use the bootstrap teacher as a behavioral-cloning or warm-start data source only if needed.

3. Export and deploy.
   - Export the deterministic actor to `simulink/hpt_sac_actor_weights.mat`.
   - Run Simulink with actor mode enabled.

4. Fine-tune per topology.
   - Use the same actor input/output dimensions.
   - Maintain separate checkpoints if topology2 needs more authority or a different phase calibration.

5. Validate in switch-level Simulink.
   - Sag: `9000 V` MV source.
   - Nominal: `10000 V`.
   - Swell: `11000 V`.
   - Then add unbalanced and dynamic transient cases.

## Open Calibration Items

- Topology2 currently has looser swell regulation than topology1; final SAC training should weight topology2 swell cases more heavily.
- The first implementation uses a rule-based bootstrap policy for interface testing. A successful final result requires trained SAC weights, not the bootstrap policy.
- Detailed current limiting is still delegated to modulation bounds and the existing physical converter model; a later stage should add measured current penalties and hard projection.
