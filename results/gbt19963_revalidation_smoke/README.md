# GB/T Validator Smoke Recheck

Validator: `hpt-frt-gates-v3-gbt19963.1`

Plant/controller: topology2 switch-level model with `conventional_dq`.

Cases:

| Case | PCC signal | scenario_valid | L1 | L2 | L3 |
|---|---|---:|---:|---:|---:|
| balanced LVRT 0.20 pu / 625 ms | minimum line RMS | false | false | false | false |
| balanced HVRT 1.30 pu / 500 ms | maximum line RMS | true | false | false | false |
| balanced LVRT 0.90 pu / 60 ms runtime check | minimum line RMS | true | false | false | false |

The LVRT source/PCC trace crosses below the exact lower envelope during the
strict per-sample RMS assessment (`0.168470 pu` maximum violation). The HVRT
PCC trace remains inside its upper envelope. Both controller runs fail L1 due
to load-quality, DC-link, and current-limit violations. L2/L3 additionally
remain unavailable because the current model has no explicit breaker/trip
state and no active-power recovery criterion.

These rows are evaluator smoke evidence only. They do not re-promote the
legacy r6 SAC actor and are not a complete standard boundary campaign.

The additional 0.90-pu/60-ms row was run after the final evaluator helper and
function-signature cleanup. It confirms that the runtime path emits the new
schema and gate fields without rebuilding a promotion claim.
