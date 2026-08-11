# Conventional dq Tuning Campaign

Run directory: `E:\research_space\Hybrid-power-transformer\results\conventional_dq_tuning\gbt_v3_t2_l1_baseline_narrow_20260803`

## Ranked Candidates

| rank | topology | candidate | valid | L1 pass | L2 | L3 | score_sum | load-quality max | recovery max | vdc_min | vdc_max | csv |
|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 1 | topology2 | t2_currentgate_vff000_reg060_energyoff | 1/1 | 1/1 | 0 | 0 | 9.075 | 0.000000 | 0.000000 | 795.560 | 867.148 | `control_comparison_topology2_fault_all_gbt_v3_t2_l1_baseline_narrow_20260803_topology2_t2_currentgate_vff000_reg060_energyoff_20260803_210356.csv` |
| 2 | topology2 | t2_currentgate_reg060_energyoff | 1/1 | 0/1 | 0 | 0 | 129.107 | 0.005901 | 0.005901 | 781.203 | 1028.220 | `control_comparison_topology2_fault_all_gbt_v3_t2_l1_baseline_narrow_20260803_topology2_t2_currentgate_reg060_energyoff_20260803_205641.csv` |
| 3 | topology2 | t2_currentgate_reg065_energy025 | 1/1 | 0/1 | 0 | 0 | 128.736 | 0.013816 | 0.013816 | 779.343 | 1026.220 | `control_comparison_topology2_fault_all_gbt_v3_t2_l1_baseline_narrow_20260803_topology2_t2_currentgate_reg065_energy025_20260803_205837.csv` |
| 4 | topology2 | t2_currentgate_reg060_energy_disabled | 1/1 | 0/1 | 0 | 0 | 174.632 | 0.078327 | 0.078327 | 237.628 | 1049.337 | `control_comparison_topology2_fault_all_gbt_v3_t2_l1_baseline_narrow_20260803_topology2_t2_currentgate_reg060_energy_disabled_20260803_210204.csv` |
| 5 | topology2 | t2_currentgate_reg050_energy_disabled | 1/1 | 0/1 | 0 | 0 | 182.243 | 0.086434 | 0.086434 | 216.124 | 1079.062 | `control_comparison_topology2_fault_all_gbt_v3_t2_l1_baseline_narrow_20260803_topology2_t2_currentgate_reg050_energy_disabled_20260803_210024.csv` |
| 6 | topology2 | t2_currentgate_reg055_energyoff | 1/1 | 0/1 | 0 | 0 | 128.541 | 0.000000 | 0.000000 | 782.455 | 1052.713 | `control_comparison_topology2_fault_all_gbt_v3_t2_l1_baseline_narrow_20260803_topology2_t2_currentgate_reg055_energyoff_20260803_205436.csv` |

## Interpretation

- Only rows with the current v3 schema and `scenario_valid=true` are eligible.
- `l1_pass_count` is the current promotion-relevant gate.
- L2/L3 are tracked but cannot be promoted until their measurement interfaces exist.
- A candidate is only a strong baseline candidate after switch-level CSV evidence, not from proxy-only ranking.
