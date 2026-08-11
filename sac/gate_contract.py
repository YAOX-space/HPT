"""Shared FRT gate semantics for HPT training and switch-level campaigns.

The v3 validator separates three different questions:

* ``scenario_valid``: did the PCC voltage actually realize a GB/T test case?
* ``L1``: did the HPT preserve project-defined load quality and equipment limits?
* ``L2``/``L3``: did the plant expose and pass the additional grid-code evidence?

Only L1 is currently trainable because the switch-level plants do not yet log
an explicit connection/trip state or active-power recovery evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


CURRENT_FRT_VALIDATOR_SCHEMA = "hpt-frt-gates-v3-gbt19963.1"
TRAINABLE_GATES = ("L1",)
REPORTABLE_GATES = ("L1", "L2", "L3")

GATE_FIELDS = {
    "L1": "l1_load_voltage_survival_pass",
    "L2": "l2_grid_code_ride_through_pass",
    "L3": "l3_full_frt_pass",
}


def normalize_target_gate(value: str, *, trainable_only: bool = False) -> str:
    gate = str(value).strip().upper()
    allowed = TRAINABLE_GATES if trainable_only else REPORTABLE_GATES
    if gate not in allowed:
        suffix = " for training" if trainable_only else ""
        raise ValueError(
            f"Unsupported HPT target gate {value!r}{suffix}; allowed: {', '.join(allowed)}"
        )
    return gate


def truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "1.0", "true", "yes"}


def row_has_current_schema(row: dict[str, Any]) -> bool:
    return str(row.get("validator_schema", "")) == CURRENT_FRT_VALIDATOR_SCHEMA


@dataclass(frozen=True)
class RowGateStatus:
    eligible: bool
    passed: bool
    reason: str


def classify_result_row(row: dict[str, Any], target_gate: str = "L1") -> RowGateStatus:
    """Classify one switch-level row without conflating test validity and control.

    A row outside the requested PCC envelope is an invalid test scenario, not a
    controller failure.  Missing or stale schemas are likewise ineligible.
    """

    gate = normalize_target_gate(target_gate)
    if not row_has_current_schema(row):
        return RowGateStatus(False, False, "stale_or_missing_validator_schema")
    if not truthy(row.get("scenario_valid")):
        return RowGateStatus(False, False, "invalid_test_scenario")
    field = GATE_FIELDS[gate]
    if field not in row:
        return RowGateStatus(False, False, f"missing_{field}")
    passed = truthy(row.get(field))
    return RowGateStatus(True, passed, "pass" if passed else f"{gate.lower()}_controller_failure")


def summarize_gate_rows(
    rows: Iterable[dict[str, Any]], target_gate: str = "L1"
) -> dict[str, int | str]:
    gate = normalize_target_gate(target_gate)
    materialized = list(rows)
    statuses = [classify_result_row(row, gate) for row in materialized]
    return {
        "validator_schema": CURRENT_FRT_VALIDATOR_SCHEMA,
        "target_gate": gate,
        "row_count": len(materialized),
        "scenario_valid_count": sum(
            row_has_current_schema(row) and truthy(row.get("scenario_valid"))
            for row in materialized
        ),
        "eligible_count": sum(status.eligible for status in statuses),
        "target_gate_pass_count": sum(status.eligible and status.passed for status in statuses),
        "invalid_scenario_count": sum(status.reason == "invalid_test_scenario" for status in statuses),
        "stale_schema_count": sum(
            status.reason == "stale_or_missing_validator_schema" for status in statuses
        ),
        "l1_pass_count": sum(
            row_has_current_schema(row)
            and truthy(row.get("scenario_valid"))
            and truthy(row.get(GATE_FIELDS["L1"]))
            for row in materialized
        ),
        "l2_pass_count": sum(
            row_has_current_schema(row)
            and truthy(row.get("scenario_valid"))
            and truthy(row.get(GATE_FIELDS["L2"]))
            for row in materialized
        ),
        "l3_pass_count": sum(
            row_has_current_schema(row)
            and truthy(row.get("scenario_valid"))
            and truthy(row.get(GATE_FIELDS["L3"]))
            for row in materialized
        ),
    }
