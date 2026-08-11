# HPT SAC Stabilize and Expand Plan - 2026-07-26

## Scope

This phase keeps the claim at switch-level voltage-survival specialist SAC.
It does not claim full FRT certification.  Grid current limit, reactive current
support, and GBT recovery certification remain later-stage criteria.

## Current Evidence

The promoted recheck run `hpt_promoted_recheck_20260726_round1` evaluated 11
cases with the same switch-level voltage-survival validator:

- conventional dq voltage-survival pass: 2 / 11
- promoted SAC voltage-survival pass: 11 / 11
- SAC beats conventional: 9 / 11
- traditional fail / SAC pass: 9 / 11
- traditional pass / SAC fail: 0 / 11

The remaining weak cases are topology1 A/AB LVRT 0.90 pu / 60 ms.  Both pass
voltage-survival, but their scores are worse than conventional.

## Experiment Plan

### Stage A - Stabilize

1. Keep `protected_sac_promoted_specialists_20260726_round1.csv` as the active
   voltage-survival promoted manifest.
2. Recheck all promoted rows through
   `run_hpt_voltage_survival_boundary_matrix.py`.
3. Any row that fails switch-level recheck is downgraded to diagnostic.
4. Any row that passes but does not beat conventional is labeled
   `survival_only`.

### Stage B - Improve Weak Rows

Targets:

1. topology1 A-phase LVRT 0.90 pu / 60 ms
2. topology1 AB LVRT 0.90 pu / 60 ms
3. topology2 AB-HVRT 1.05 pu / 60 ms

Method:

- start from the latest switch-level-passing checkpoint;
- use protected SAC chunks with rollback-on-non-improvement;
- keep behavior anchoring strong enough to avoid proxy drift;
- evaluate every chunk in switch-level Simulink;
- accept only switch-level voltage-survival pass with lower score.

### Stage C - Boundary Extension

After Stage B, run a reduced boundary matrix:

- LVRT: 0.85 / 0.90 / 0.95 pu
- HVRT: 1.05 / 1.10 / 1.15 pu
- duration: 40 / 60 / 80 / 120 ms
- phase modes: balanced / A / AB
- topology: topology1 / topology2

Promotion target:

- SAC must pass voltage-survival.
- Boundary success means SAC passes where conventional fails, or both pass but
  SAC has lower control score.

## Stop Conditions

- Stop a target after repeated recovery-envelope failures without any passing
  improvement.
- Do not accept proxy-only gains.
- Do not claim full FRT certified results in this phase.
