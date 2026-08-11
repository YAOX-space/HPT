# Family Dataset Builders

- `collect_hpt_family_actor_traces.py`: collect switch-level family traces.
- `build_hpt_family_anchor_from_actor_traces.py`: create behavior anchors from
  accepted traces.
- `build_hpt_family_support_dataset.py`: build the action-support dataset used
  by support-regularized SAC.
- `build_hpt_trace_aggregate.py`: merge trace CSV files.
- `build_hpt_trajectory_from_trace.py`: convert a trace to a replay trajectory.
- `build_hpt_action_trajectory.py`: generate deterministic diagnostic action
  schedules and write the MAT/CSV bridge used by the evaluator.
- `build_hpt_local_action_sweep.py`: focused diagnostic action candidates.
- `build_hpt_energyq_boost_anchor.py`: targeted energy-q anchor utility.

There are no compatibility wrappers. Import these modules by their package
paths under `sac.datasets`.
