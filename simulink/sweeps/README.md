# Maintained Sweeps

- `sweep_hpt_v2_conventional_boundary.m`: balanced strong-dq boundary.
- `sweep_hpt_v2_unbalanced_conventional_boundary.m`: unbalanced boundary.
- `tune_hpt_v2_unbalanced_conventional_phase.m`: conventional phase tuning.
- `sweep_hpt_v2_reg_energy_response.m`: joint regulation/energy diagnostics.
- `sweep_hpt_v2_fault_fixed_reg_response.m`: fault fixed-regulation response.
- `sweep_hpt_v2_topology2_fault_fixed_reg.m`: topology2 fault response.
- `sweep_hpt_v2_topology2_energy_signs.m`: topology2 energy direction/sign.
- `run_hpt_v2_gbt19963_boundary_matrix.m`: canonical PCC voltage-time
  breakpoint revalidation (`smoke` or `full`, balanced/A/AB scope).

These scripts diagnose the plant or tune the baseline. They do not train or
promote SAC actors.
