# Version 2 Architecture

## Purpose

The version-2 stack connects Python RL/proxy tooling with switch-level
MATLAB/Simulink HPT validation.

## Main Components

- Python package entry points live under `sac`.
- Proxy/controller contracts currently live in
  `sac/hpt_voltage_sac_env.py`. The next-generation research direction
  is a timestep-level transition proxy calibrated from switch-level strong-dq
  and expert trajectories, not a window-average calibration table.
- Experiment metadata helpers live in `sac/experiment_metadata.py`.
- Switch-level models and MATLAB scripts live under `simulink`.
- MATLAB smoke and regression scripts live under `simulink/tests`.
- The twelve fault-family controller workspaces live under
  `experts/<expert_id>`.
- Family checkpoints and long-run results must be written to that expert's
  `models/` and `results/` directories. Root `data/models` and `lab/results`
  are legacy provenance stores only.

## Proxy 2.0 Direction

The active research direction is to replace window-average proxy descriptions
with a timestep-level transition proxy. Each calibration sample should represent
`(fault context, time, state, action) -> (next state, next LV/Vdc/grid-current/sequence metrics, violations)`.
Primary data should come from strong-dq trajectories, accepted expert
trajectories, and small local perturbations around those trajectories. Fixed
action sweeps are diagnostic or local gap-filling evidence only; they are not
the main data source for family-level SAC training claims.

## Controller Contract

The current SAC interface is a 24-D observation and 4-D action contract. The
MATLAB regression `simulink/tests/test_hpt_v2_sac_interface.m`
checks this contract for topology1 and topology2.

Any change to this contract must update Python producers, MATLAB consumers,
actor export, Simulink tests, docs, and migration notes in one traceable unit.

## Reproducibility Contract

Long-running experiments must record:

- command and configuration;
- Git branch, commit, and dirty state;
- input dataset or trajectory path;
- actor/model hashes where applicable;
- summary metrics and failure reason;
- next action.
