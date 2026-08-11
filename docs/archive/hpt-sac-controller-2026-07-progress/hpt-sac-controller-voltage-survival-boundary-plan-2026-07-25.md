# HPT Voltage-Survival Boundary Plan - 2026-07-25

## Objective

Build a switch-level voltage-survival boundary matrix that compares the tuned
traditional `conventional_dq` controller against the current Stage-2 SAC
specialists.  The claim target is not full FRT certification yet.  The target
is narrower and paper-critical:

- identify where the traditional controller passes or fails;
- evaluate whether the current SAC specialists pass the same scenarios;
- identify regions where SAC passes and traditional control fails;
- identify boundary-near failures for the next specialist SAC training loop.

## Confirmed Scope

- Promotion gate: `voltage_survival_pass`, not `full_frt_pass`.
- Full scenario matrix: 630 scenarios.
- SAC boundary mode: nearest-neighbor extrapolation from the Stage-2 accepted
  specialist manifest, followed by targeted retraining near failures.
- First retraining priority after the matrix: topology1 unbalanced boundary.
- Durations: 40, 60, 80, 120, and 200 ms.
- LVRT depths: 0.75, 0.80, 0.85, 0.90, and 0.95 pu.
- HVRT depths: 1.05, 1.10, 1.15, and 1.20 pu.
- Phase modes: balanced ABC, A, B, C, AB, BC, and CA.

Total scenarios:

```text
2 topologies * 9 fault depths * 5 durations * 7 phase modes = 630
```

## Success Metrics

For each scenario and controller mode, record at least:

- `voltage_survival_pass`
- `voltage_survival_reason`
- `control_score`
- `fault_lv_band_violation_max_pu`
- `envelope_violation_max_pu`
- `recovery_violation_max_pu`
- `vdc_min`, `vdc_max`
- `action_max_abs`
- `full_frt_pass` and `full_frt_reason` as diagnostic fields only

SAC beats conventional on a scenario only if:

- SAC `voltage_survival_pass = true`, and
- either conventional fails voltage-survival, or both pass and SAC has lower
  `control_score`.

## Scenario Timing

Use the current Stage-2 validated timing:

- balanced scenarios: `fault_start_s = 0.080`, `fault_settle_s = 0.020`;
- unbalanced phase-source scenarios: `fault_start_s = 0.035`,
  `fault_settle_s = 0.020`;
- all rows: `fault_stop_margin_s = 0.125`.

These choices keep the boundary matrix aligned with the currently accepted
Stage-2 switch-level rows rather than older one-off boundary sweeps.

## Actor Mapping Rule

The first SAC boundary scan uses nearest-neighbor specialists:

- exact topology and fault family are preferred;
- balanced rows use the balanced accepted actor for the same topology/family;
- unbalanced LVRT single-phase rows use the A-phase accepted actor;
- unbalanced LVRT two-phase rows use the AB accepted actor;
- unbalanced HVRT rows initially use the balanced HVRT accepted actor because
  no unbalanced HVRT specialist is accepted yet.

Rows using an extrapolated actor are tagged in the manifest.  They are boundary
probes, not final promoted specialists.

## Execution Plan

1. Generate the 630-row manifest.
2. Run a smoke subset:
   - depths: LVRT 0.90 pu and HVRT 1.10 pu;
   - duration: 60 ms;
   - phase modes: balanced, A, AB;
   - both topologies.
3. If smoke produces valid CSVs, run the full grouped switch-level matrix with
   `conventional_dq` and nearest-neighbor SAC actor modes.
4. Summarize:
   - traditional pass boundary;
   - SAC pass boundary;
   - `traditional fail / SAC pass`;
   - `traditional pass / SAC fail`;
   - both fail.
5. Select boundary-near SAC retraining targets, prioritizing topology1
   unbalanced A/B/C/AB/BC/CA rows where traditional is stronger than the
   current SAC actor.
6. Train new specialist SAC actors only after the boundary matrix exposes a
   meaningful target.

## Artifacts

- Manifest:
  `sac/experiments/voltage_survival_boundary_manifest_20260725.csv`
- Smoke run:
  `lab/results/hpt_voltage_survival_boundary_smoke_20260725/`
- Full run:
  `lab/results/hpt_voltage_survival_boundary_full_20260725/`
- Research log:
  `docs/autonomy/logs/research_log.md`

