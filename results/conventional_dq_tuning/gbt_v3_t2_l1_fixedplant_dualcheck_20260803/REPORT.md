# Conventional dq Tuning Campaign

Run directory: `E:\research_space\Hybrid-power-transformer\results\conventional_dq_tuning\gbt_v3_t2_l1_fixedplant_dualcheck_20260803`

## Ranked Candidates

| rank | topology | candidate | valid | L1 pass | L2 | L3 | score_sum | load-quality max | recovery max | vdc_min | vdc_max | csv |
|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 1 | topology2 | t2_v3_l1_energy015_fixed_plant | 2/2 | 1/2 | 0 | 0 | 116.443 | 0.000000 | 0.000000 | 795.560 | 1038.401 | `control_comparison_topology2_fault_all_gbt_v3_t2_l1_fixedplant_dualcheck_20260803_topology2_t2_v3_l1_energy015_fixed_plant_20260803_211608.csv` |

## Interpretation

- Only rows with the current v3 schema and `scenario_valid=true` are eligible.
- `l1_pass_count` is the current promotion-relevant gate.
- L2/L3 are tracked but cannot be promoted until their measurement interfaces exist.
- A candidate is only a strong baseline candidate after switch-level CSV evidence, not from proxy-only ranking.
