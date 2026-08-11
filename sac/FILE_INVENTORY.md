# Version 2 SAC File Inventory

## Active Core

| Path | Purpose |
|---|---|
| `hpt_voltage_sac_env.py` | Current SAC environment, scenarios, observations, actions, and reward; being migrated from window-average calibration toward timestep-level transition proxy semantics |
| `offline/train_hpt_voltage_sac.py` | Support-regularized SAC update loop and checkpoint output |
| `pretrain_hpt_actor_bc.py` | Optional strong-dq behavior initialization |
| `export_hpt_sac_actor.py` | SB3-to-MAT actor export |
| `run_hpt_trajectory_specialist_campaign.py` | Lower-level actor train/export/validate pipeline |
| `validate_hpt_trajectory_switchlevel.py` | MATLAB switch-level validation adapter |
| `frt_envelope.py` | Voltage-survival envelope definitions |
| `experiment_metadata.py` | Git, source, arguments, and artifact metadata |

## Active Campaign

| Path | Purpose |
|---|---|
| `campaigns/run_hpt_family_specialist_matrix.py` | Canonical one-actor-per-family campaign |
| `campaigns/run_hpt_t2_balanced_lvrt_dq_seeded_boundary.py` | Shared family/boundary helper functions |
| `campaigns/tune_hpt_conventional_dq_profile.py` | Strong conventional-dq baseline tuning |
| `campaigns/summarize_hpt_boundary_run.py` | Boundary run summary helper |

## Active Data And Calibration

| Directory | Maintained contents |
|---|---|
| `datasets/` | family trace collection, support/anchor datasets, aggregate traces, trace-to-trajectory conversion, focused local sweeps |
| `calibration/` | Proxy calibration and alignment. New proxy work should favor timestep transition datasets from strong-dq/expert trajectories and small perturbations; fixed-action sweeps are diagnostic/local gap filling only |
| `summaries/` | boundary plots, reward traces, trace alignment, paper evidence |

## Data Files

- `hpt_proxy_calibration.json`: active balanced proxy calibration.
- `hpt_proxy_calibration_unbalanced_pilot.json`: diagnostic unbalanced pilot;
  not a final promotion source.
- `experiments/*.csv` and `experiments/*.json`: historical experiment manifests.
  Their filenames and original result paths are preserved for provenance.

## Non-Active Trees

- `lab/results/`: generated evidence, including failed and interrupted runs.
- `data/models/`: trained actor checkpoints.
- `src/hpt_frt/` and `lab/simulink/`: previous-generation research retained for
  reproducibility, not imported by the active family campaign.

Do not add top-level compatibility wrappers. Add new code to the matching
subpackage and update this inventory in the same commit.

## Proxy Data Policy

Proxy 2.0 should be described and implemented as a timestep-level transition
proxy: each row is a local transition sample, not a whole-window average.
Inputs include fault family, depth, duration, phase, current time, current
state, and `[m_reg_d, m_reg_q, m_energy_d, m_energy_q]`; outputs include next
LV voltage, DC-link, grid current, positive/negative sequence voltage, and
constraint violations. The preferred data lineage is strong-dq baseline traces,
accepted expert traces, and small perturbations around those traces.
