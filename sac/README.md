# Version 2 SAC Workspace

Fault training and promotion use validator `hpt-frt-gates-v3-gbt19963.1`.
Only `L1` is currently trainable. The trainer rejects stale fault proxies;
`scenario_valid` is assessed from switch-level PCC measurements and is not an
actor-controlled reward term. L2/L3 remain report-only until the plant exposes
connection state and active-power recovery evidence.

This directory contains the maintained Python side of the HPT family-level SAC
workflow. The design target is one 24-observation, four-action state-feedback
actor per fault family:

```text
observation -> [m_reg_d, m_reg_q, m_energy_d, m_energy_q]
```

The actor is trained with an averaged, switch-calibrated proxy and is accepted
only after an unchanged checkpoint passes the Simulink switch-level matrix.

Models and results are stored by family under `experts/`. See
`experts/registry.json` for the twelve canonical workspaces.

## Canonical Entry Point

```powershell
$env:PYTHONPATH = "src"
py -3 -m sac.campaigns.run_hpt_family_specialist_matrix --help
```

The campaign performs the maintained sequence:

1. collect strong-dq switch-level family traces;
2. build one family support/anchor dataset;
3. train one family seed actor;
4. perform support-regularized SAC fine-tuning;
5. export the same actor to MATLAB;
6. evaluate it over the requested depth-duration matrix.

## Maintained Modules

- `hpt_voltage_sac_env.py`: 24-D proxy environment, reward, scenarios, and
  execution semantics.
- `offline/train_hpt_voltage_sac.py`: support-regularized SAC training engine.
- `pretrain_hpt_actor_bc.py`: optional strong-dq data initialization. This is
  initialization, not the claimed final controller.
- `export_hpt_sac_actor.py`: exports SB3 actor weights for Simulink.
- `run_hpt_trajectory_specialist_campaign.py`: lower-level trajectory actor
  campaign used by the family runner.
- `validate_hpt_trajectory_switchlevel.py`: switch-level actor validation.
- `frt_envelope.py`: shared voltage-survival envelope definitions.
- `experiment_metadata.py`: reproducibility metadata.
- `expert_workspace.py`: twelve-family taxonomy and canonical path resolver.
- `campaigns/`: family orchestration and strong-dq tuning.
- `datasets/`: family trace, support, and aggregate dataset builders.
- `calibration/`: proxy calibration and proxy/Simulink alignment checks.
- `summaries/`: current boundary, reward, and paper-evidence plots.
- `experiments/`: historical manifests only; not executable entry points.

## Promotion Rule

Proxy reward is never sufficient for promotion. A candidate must be exported
and evaluated by `eval_hpt_v2_control_comparison.m`. The current claim boundary
is switch-level voltage survival unless all full-FRT current criteria are also
present and passing.

`tuned_v2_l1` is the current named conventional profile. Its topology2
fixed-plant smoke passes 0.90-pu/60-ms LVRT and fails 1.10-pu/60-ms HVRT on
the DC-link bound. It is therefore a reproducible comparison baseline with a
known boundary, not yet a fully tuned all-family baseline.

The canonical family campaign resolves the expert from `--topology`,
`--category`, and `--phase-key`, then writes the model and every generated
trace into that expert workspace.

## Removed Methods

The 2026-08-03 cleanup removed obsolete fixed-action searches, per-case actor
campaigns, generic offline baselines, learned reward correction, safety
classifier experiments, compatibility wrappers, and overnight scripts. Git
history and result artifacts retain their provenance; they are no longer valid
commands for new experiments.
