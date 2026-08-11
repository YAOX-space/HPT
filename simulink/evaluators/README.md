# Evaluators

- `eval_hpt_v2_control_comparison.m`: canonical strong-dq, trajectory, and SAC
  switch-level comparison under validator schema
  `hpt-frt-gates-v3-gbt19963.1`.
- `eval_hpt_v2_sac_single_case.m`: single-case trace export used by paper plots.
- `hpt_gbt19963_envelope.m`: exact PCC LVRT/HVRT voltage-time breakpoints.
- `hpt_pcc_assessment_voltage.m`: single-phase affected-phase and multi-phase
  line-voltage RMS signal selection.

The result gates are deliberately separate:

- `scenario_valid`: injected PCC voltage remains inside the GB/T envelope.
- `l1_load_voltage_survival_pass`: project-defined load voltage, DC-link,
  action, and optional current gate.
- `l2_grid_code_ride_through_pass`: L1 plus valid PCC scenario, explicit
  connection evidence, and equipment safety.
- `l3_full_frt_pass`: L2 plus reactive-current and active-power recovery.

The current model does not expose a breaker/trip-state signal, so L2/L3 remain
false until that evidence is implemented. A completed simulation is recorded
as `simulation_completed`, not as formal connection proof.

Promotion decisions must come from these switch-level evaluators. Proxy scores
and the removed raw-smoke evaluator are not promotion evidence.
