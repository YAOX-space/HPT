# HPT 12-Specialist Fault Setup and Ride-Through Gate Standard

Date: 2026-07-29

This document fixes the current experiment standard for the HPT voltage-survival SAC work.  It is an audit of the latest 12-specialist setting and the validator currently used by `sac/validate_hpt_accepted_specialists.py` and `simulink/evaluators/eval_hpt_v2_control_comparison.m`.

## 1. Scope

The current claim boundary is:

> switch-level, case-specialized load-side voltage-survival.

It is not yet:

> full grid-code FRT certification.

Therefore, the accepted specialist pass condition is `voltage_survival_pass`, not `full_frt_pass`.  Full FRT additionally checks grid current limit and reactive current support/absorption, which currently remains a later phase.

## 2. The 12 Specialist Center Cases

The current 12 experts are generated from:

- 2 topologies: `topology1`, `topology2`
- 2 fault classes: `LVRT`, `HVRT`
- 3 phase classes: `balanced`, `A-phase`, `AB-phase`

This gives:

| ID | Topology | Fault class | Phase class | Fault setting | Duration | Current role |
| --- | --- | --- | --- | --- | --- | --- |
| `t1_balanced_lvrt` | topology1 | LVRT | balanced ABC | `[0.90, 0.90, 0.90] pu` | 60 ms | center specialist |
| `t1_balanced_hvrt` | topology1 | HVRT | balanced ABC | `[1.10, 1.10, 1.10] pu` | 60 ms | center specialist |
| `t1_a_lvrt` | topology1 | LVRT | A-phase | `[0.90, 1.00, 1.00] pu` | 60 ms | center specialist for single-phase LVRT |
| `t1_ab_lvrt` | topology1 | LVRT | AB-phase | `[0.90, 0.90, 1.00] pu` | 60 ms | center specialist for two-phase LVRT |
| `t1_a_hvrt` | topology1 | HVRT | A-phase | `[1.10, 1.00, 1.00] pu` | 60 ms | center specialist for single-phase HVRT |
| `t1_ab_hvrt` | topology1 | HVRT | AB-phase | `[1.10, 1.10, 1.00] pu` | 60 ms | center specialist for two-phase HVRT |
| `t2_balanced_lvrt` | topology2 | LVRT | balanced ABC | `[0.90, 0.90, 0.90] pu` | 60 ms | center specialist |
| `t2_balanced_hvrt` | topology2 | HVRT | balanced ABC | `[1.10, 1.10, 1.10] pu` | 60 ms | center specialist |
| `t2_a_lvrt` | topology2 | LVRT | A-phase | `[0.90, 1.00, 1.00] pu` | 60 ms | center specialist for single-phase LVRT |
| `t2_ab_lvrt` | topology2 | LVRT | AB-phase | `[0.90, 0.90, 1.00] pu` | 60 ms | center specialist for two-phase LVRT |
| `t2_a_hvrt` | topology2 | HVRT | A-phase | `[1.10, 1.00, 1.00] pu` | 60 ms | center specialist for single-phase HVRT |
| `t2_ab_hvrt` | topology2 | HVRT | AB-phase | `[1.10, 1.10, 1.00] pu` | 60 ms | center specialist for two-phase HVRT |

The current 12-specialist matrix deliberately uses A and AB as representative unbalanced centers.  B/C and BC/CA are phase-permutation holdout cases for generalization tests, not separate center specialists in the current 12-expert standard.

## 3. Fault Timing

Current center-case timing in `stage6_recheck_manifest_current12_repaired_sac_20260728.csv`:

| Phase class | Fault start | Fault duration | Fault clear | Post-fault stop margin | Fault-settle gate |
| --- | ---: | ---: | ---: | ---: | ---: |
| balanced | 0.080 s | 0.060 s | 0.140 s | 0.125 s | 0.020 s |
| A-phase / AB-phase | 0.035 s | 0.060 s | 0.095 s | 0.125 s | 0.020 s |

The different start times are historical Simulink interface settings.  They are acceptable only if reported explicitly; future family experiments should preferably normalize timing unless there is a model-interface reason not to.

## 4. Voltage Signal Used by the Validator

The nominal load-side phase RMS base is:

```text
V_LV_base = 207 V
```

For balanced faults, the validator uses the instantaneous three-phase RMS trace from the switch-level LV voltage.

For unbalanced faults, the validator currently uses the controller filtered LV per-unit observation, multiplied by 207 V.  In output CSVs this is marked as:

```text
lv_metric_source = controller_filtered_lv_pu
```

This is important: the current unbalanced voltage-survival claim is based on the same filtered LV metric seen by the controller, not a separate per-phase raw RMS envelope for each A/B/C phase.

## 5. LVRT and HVRT Envelope Direction

The LVRT and HVRT gates are different.

### 5.1 LVRT

LVRT is a voltage sag case.  The envelope is a lower bound.  The voltage-survival requirement is:

```text
LV_pu(t) >= LVRT_lower_envelope(t)
```

The current helper is:

```text
0 <= t_rel <= 0.625 s: lower = max(0.20, fault_pu)
0.625 < t_rel <= 2.0 s: lower ramps from max(0.20, fault_pu) to 0.90
t_rel > 2.0 s: lower = 0.90
```

### 5.2 HVRT

HVRT is a voltage swell case.  The envelope is an upper bound.  The voltage-survival requirement is:

```text
LV_pu(t) <= HVRT_upper_envelope(t)
```

The current helper is:

```text
0 <= t_rel <= 0.5 s: upper = 1.30
0.5 < t_rel <= 1.0 s: upper = 1.20
t_rel > 1.0 s: upper = 1.10
```

## 6. Current Voltage-Survival Pass Gate

The accepted specialist must satisfy all of the following in switch-level Simulink:

| Gate | Metric | Pass condition | Meaning |
| --- | --- | --- | --- |
| Fault load-side band | `fault_lv_band_violation_max_pu` | `<= 1e-3` | During the fault window, LV RMS must stay inside 176-238 V. |
| LVRT/HVRT timestep envelope | `envelope_violation_max_pu` | `<= 1e-3` | Every evaluated timestep respects the LVRT lower envelope or HVRT upper envelope. |
| Recovery envelope | `recovery_violation_max_pu` | `<= 1e-3` | After fault clear + 35 ms, LV must stay within `1.00 +/- 0.07 pu`. |
| DC-link survival | `vdc_min`, `vdc_max` | `650 V <= Vdc <= 1000 V` | DC link must not collapse or overcharge. |
| Action limit | `action_max_abs` | `<= 0.9501` | Actor output must remain inside physical modulation/action bound. |

The `fault_lv_band_violation_max_pu` gate is intentionally kept.  It is not redundant with the one-sided LVRT/HVRT envelope: LVRT lower-envelope pass alone would not prevent over-boost during the fault, and HVRT upper-envelope pass alone would not guarantee useful load-side voltage support.  If a future validator uses a full two-sided load-side envelope over the fault window, this separate band can be merged; the current validator has not made that change.

## 7. Full FRT Gate for Later Work

`full_frt_pass` is stricter than `voltage_survival_pass`.  It includes the voltage-survival-related checks plus:

| Full-FRT item | Current condition |
| --- | --- |
| Grid current limit | `grid_current_peak_pu <= 1.50` |
| Reactive current direction | LVRT requires positive voltage-supporting `iq`; HVRT requires negative/absorbing `iq`. |
| Reactive current reference | `iq_ref = min(0.30, 1.5*(0.9 - Vpos))` for `Vpos < 0.9`; `iq_ref = max(-0.30, -1.5*(Vpos - 1.1))` for `Vpos > 1.1`; otherwise zero. |
| Reactive current tolerance | Demand is evaluated only when `abs(iq_ref) > 0.12 pu`. |
| Reactive response delay | Assessment starts at fault start + 60 ms. |
| Reactive dwell | At least 80% of demanded samples must meet the current requirement. |

Because these items are not yet passed systematically, current papers and reports must not claim full FRT certification.

## 8. Audit of the Previous 12-Case Judgment

The latest authoritative recheck is:

```text
lab/results/hpt_stage6_recheck_current12_repaired_sac_20260728/summary.json
```

It reports:

```text
case_count = 12
voltage_survival_pass_count = 12
beats_conventional_count = 12
full_frt_pass_count = 0
```

The corresponding manifest is:

```text
sac/experiments/stage6_recheck_manifest_current12_repaired_sac_20260728.csv
```

Therefore, the previous corrected judgment is:

1. The old "8 specialist" statement is historical Stage-2 only and is no longer the complete current matrix.
2. The current representative matrix has 12 center specialists.
3. All 12 pass switch-level voltage-survival under the current validator.
4. All 12 beat the tuned conventional dq baseline by the current `control_score`.
5. None of the 12 pass full FRT; dominant failure reasons include `grid_current_limit`, `gbt_recover`, and reactive-current not-evaluated/shortfall statuses.

## 9. Recommended Family Expansion Around Each Center

For future training, each of the 12 center specialists should become one fault family:

| Dimension | LVRT family values | HVRT family values |
| --- | --- | --- |
| Depth / magnitude | 0.85, 0.875, 0.90, 0.925, 0.95 pu | 1.05, 1.075, 1.10, 1.125, 1.15 pu |
| Duration | 40, 60, 80, 100, 120 ms | 40, 60, 80, 100, 120 ms |
| Phase mode | balanced, A/B/C, AB/BC/CA by permutation | balanced, A/B/C, AB/BC/CA by permutation |

For each family, train and validate with trajectory/state-feedback rollouts rather than a single fixed action.  The final promotion gate remains switch-level `voltage_survival_pass` first; full FRT is a later, explicitly separate gate.

