# Collectors

- `collect_hpt_v2_frt_calibration_matrix.m`: collect fixed and grouped
  switch-level calibration rows for proxy fitting. New rows carry validator
  schema `hpt-frt-gates-v3-gbt19963.1`, separate PCC `scenario_valid` from
  project load quality, and default to `results/calibration/`.
- `collect_hpt_v2_trajectory_trace.m`: export per-control-step observations,
  commands, measured responses, and FRT metrics for a trajectory.

Run from `simulink` with
`run(fullfile(pwd,'collectors','<script>.m'))`. Older guard/energy/step teacher
collectors were removed; the trajectory collector owns the maintained trace
schema.
