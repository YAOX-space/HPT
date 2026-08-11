# HPT SAC Trajectory Search Progress - 2026-07-19

## Purpose

This note records the first switch-level trajectory-search results after moving
from fixed-state/fixed-action validation to full time-series action commands:

```text
action(t) = [m_reg_d, m_reg_q, m_energy_d, m_energy_q]
```

The new workflow uses proxy-guided CEM only as a proposal mechanism.  The source
of truth is still switch-level Simulink validation through
`eval_hpt_v2_control_comparison.m`.

## New Tool

Added:

```text
sac/search_hpt_frt_trajectory_cem.py
```

Main behavior:

- Generates piecewise-linear HPT action trajectories.
- Scores candidates in `HPTVoltageSACEnv`.
- Validates selected candidates in switch-level Simulink using
  `trajectory_action` mode.
- Writes `proxy_candidates.csv`, `switch_candidates.csv`, `REPORT.md`, and
  metadata under `lab/results/<run_id>/`.
- Holds the recovery action through `StopTime` by default.  Returning to zero
  before the validation window ends is available only with `--return-to-zero`.

## Important Debug Finding

The first trajectory template ramped back to zero before `StopTime`.  This made
the recovery window fail even when the fault-window action was reasonable.

Fix:

- Recovery action is now held through the validation horizon by default.

This is important for SAC: the episode objective is a trajectory survival task,
not a single-point fixed-action task.

## Topology1 Result

Scenario:

```text
topology1, LVRT 0.90 pu, 60 ms fault, fault_start=0.035 s,
fault_settle_s=0.020 s, StopTime=0.220 s
```

Run:

```text
lab/results/hpt_cem_traj_topology1_sag090_60ms_anchor_switch8_20260719
```

Switch-level candidates evaluated: 8.

Voltage-survival passes: 4.

Accepted examples:

| Candidate | reg_boost | reg_recovery | Vdc min | LV fault mean | LV recovery mean | Envelope viol | Recovery viol | Score |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 3 | 0.48 | 0.24 | 762.98 V | 205.89 V | 202.45 V | 0.0 pu | 0.0 pu | 113.40 |
| 4 | 0.52 | 0.30 | 762.98 V | 208.07 V | 210.27 V | 0.0 pu | 0.0 pu | 114.80 |
| 5 | 0.52 | 0.24 | 762.98 V | 208.07 V | 201.90 V | 0.0 pu | 0.0 pu | 114.88 |
| 6 | 0.56 | 0.28 | 668.92 V | 206.94 V | 203.59 V | 0.0 pu | 0.0 pu | 111.31 |

Current interpretation:

- Direct trajectory search is useful for topology1.
- The best topology1 trajectory currently found is candidate 6, but candidate 3
  has a larger DC-link margin.
- These are trajectory teachers/candidates for later specialist SAC training.

## Topology2 Result

Scenario:

```text
topology2, LVRT 0.90 pu, 60 ms fault, fault_start=0.035 s,
fault_settle_s=0.020 s, StopTime=0.220 s
```

Runs:

```text
lab/results/hpt_cem_traj_topology2_sag090_60ms_anchor_switch8_20260719
lab/results/hpt_cem_traj_topology2_sag090_60ms_lowanchor_switch10_20260719
lab/results/hpt_cem_traj_topology2_sag090_60ms_vdctrim_switch14_20260719
```

Strict voltage-survival passes: 0.

However, several candidates satisfy the LV voltage envelope and recovery
envelope at every sampled step.  They fail only on `dc_link_bounds` because the
20-us waveform has a marginal DC-link peak around `1001.48 V`, just above the
current `1000 V` hard limit.

Closest examples:

| Candidate | reg_boost | reg_recovery | energy_d | LV fault mean | LV recovery mean | Vdc min/max | Envelope viol | Recovery viol | Reason |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 3 | 0.32 | 0.06 | 0.00 | 207.23 V | 205.73 V | 783.66/1001.48 V | 0.0 pu | 0.0 pu | dc_link_bounds |
| 4 | 0.32 | 0.06 | -0.05 | 207.23 V | 205.53 V | 783.66/1001.48 V | 0.0 pu | 0.0 pu | dc_link_bounds |
| 5 | 0.32 | 0.06 | -0.10 | 207.28 V | 205.76 V | 783.66/1001.48 V | 0.0 pu | 0.0 pu | dc_link_bounds |
| 6 | 0.36 | 0.08 | 0.00 | 209.75 V | 205.67 V | 783.66/1001.48 V | 0.0 pu | 0.0 pu | dc_link_bounds |

Current interpretation:

- Topology2 needs topology-specific low-gain trajectories.
- The LV voltage trajectory can already be controlled, but the strict DC-link
  criterion blocks acceptance.
- Negative `m_energy_d` did not remove the marginal 1001.48 V spike, so the
  remaining issue is likely a fast DC-link/chopper/model transient or a too
  strict no-tolerance DC bound.

## Proxy Gap Found

The proxy is good enough to propose rough regions, but not good enough to rank
trajectory candidates reliably:

- It mis-ranked several topology1 candidates before switch-level validation.
- It ranked topology2 high-gain actions poorly after low-gain actions were
  shown to be necessary.
- It cannot yet model trajectory-dependent startup/fault-edge transients well.

Therefore:

- Do not train SAC only against the current proxy as the final objective.
- Use proxy as a proposal generator.
- Use switch-level accepted trajectories as the dataset/teacher source.
- Add trajectory traces, not only fixed-action matrix rows, to proxy calibration.

## Next Research Steps

1. Build a trajectory dataset from switch-level accepted candidates.
2. Add per-step trajectory traces to proxy calibration so the proxy sees
   transient action history, not only fixed action points.
3. For topology2, decide whether `1000 V` is an absolute internal DC hard limit
   or whether a small engineering tolerance/short transient window is allowed.
4. If the hard limit stays exact, tune physical DC-link mitigation:
   chopper threshold/resistance, DC capacitance, or energy-controller anti-windup.
5. Train trajectory specialist SAC heads per topology and fault family after the
   trajectory dataset is available.

## Trajectory Dataset Gate

New script:

```text
sac/build_hpt_trajectory_teacher_dataset.py
```

Purpose:

- Keep trajectory-level candidates separate from legacy fixed-action rows.
- Mark each switch-level validated trajectory as `strict_pass`,
  `near_pass_dc_margin`, `voltage_pass_dc_fail`, or `fail`.
- Allow SAC training to consume only `accepted_for_training=true` rows.
- Allow proxy calibration/debug to also inspect `accepted_for_calibration=true`
  near-pass rows without treating them as final teachers.

Run:

```text
py -3 -m sac.datasets.build_hpt_trajectory_teacher_dataset \
  --run-id trajectory_teacher_dataset_20260719_from_cem_runs_v2 \
  --near-dc-tol-v 5
```

Output:

```text
lab/results/hpt_trajectory_teacher_dataset/trajectory_teacher_dataset_20260719_from_cem_runs_v2/
```

Summary:

| Item | Count |
| --- | ---: |
| Total trajectory candidates | 51 |
| Strict switch-level training rows | 4 |
| Calibration-only near-pass rows | 10 |
| Diagnostic/fail rows | 37 |
| Cases covered | 2 |

Best rows by case:

| Case | Status | Candidate | Score | LV fault mean | LV recovery mean | Vdc min/max |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| topology1 LVRT 0.90 pu / 60 ms | strict_pass | 6 | 111.31 | 206.94 V | 203.59 V | 668.92/901.82 V |
| topology2 LVRT 0.90 pu / 60 ms | near_pass_dc_margin | 3 | 113.85 | 207.23 V | 205.73 V | 783.66/1001.48 V |

Important correction:

- Fault type is now inferred from the input disturbance `fault_pu`, not from
  the controlled LV output voltage.  Earlier aggregation could incorrectly
  label over-compensated LVRT rows as HVRT.

Current training implication:

- Only topology1 / LVRT 0.90 pu / 60 ms has strict switch-level trajectory
  teacher rows today.
- Topology2 already has voltage-envelope-safe trajectories, but they are not
  final teachers until the marginal DC-link peak is resolved or the acceptance
  rule is formally revised.

