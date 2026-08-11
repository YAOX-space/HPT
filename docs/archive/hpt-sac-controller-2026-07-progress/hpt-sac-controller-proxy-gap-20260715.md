# HPT Proxy Gap Note - 2026-07-15

## Run

Command:

```powershell
py -3.8 -m sac.calibration.measure_hpt_proxy_gap
```

Local result folder:

```text
lab/results/hpt_v2_proxy_gap/proxy_gap_20260715_181544
```

Inputs:

- Calibration: `sac/hpt_proxy_calibration.json`
- Regulating sweep:
  `lab/results/hpt_v2_sac_proxy_sweep/hpt_v2_sac_proxy_sweep_20260715_014435.csv`
- Energy sweep:
  `lab/results/hpt_v2_sac_energy_sweep/hpt_v2_sac_energy_sweep_20260715_024945.csv`

## Key Findings

| Area | Finding |
| --- | --- |
| Reg table proxy | RMSE `0.066 pu` on the fixed-action regulating sweep |
| Reg linear fit | RMSE `0.129 pu`; too crude for final SAC training |
| Energy fit | Vdc RMSE `0.028 pu`, but sweep contains near-zero/negative Vdc minima |
| Topology1 | Larger LV mismatch than topology2 in the current static comparison |
| Topology2 | Vdc mismatch remains important, especially around strong negative regulating actions |

The most important discovery is a semantic mismatch:

- The Python training proxy applies safety projection to SAC actions.
- The fixed-action Simulink sweep can force actions that the controller would
  normally project away.

Example:

- In swell conditions, positive `m_reg_d` is projected to zero in the Python
  training proxy.
- The fixed-action Simulink sweep still applies positive regulating injection,
  so the measured plant response is not the same experiment.

## Consequence

Future datasets must label whether an action is:

1. raw commanded action,
2. projected controller action, or
3. measured effective converter action.

The learned proxy should train on the measured effective action for plant
dynamics, but the RL environment must also model the projection layer because
the deployed SAC actor is constrained by it.

## Next Correction

Update the data-collection plan so every Simulink rollout stores:

- `action_raw`
- `action_projected`
- `action_effective`
- projection reason/mode
- whether the run used fixed-action bypass or normal SAC controller path

This is required before PETS/MOPO training; otherwise the learned proxy will
mix two different action semantics.

