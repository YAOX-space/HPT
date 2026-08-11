import pytest

from sac.gate_contract import (
    CURRENT_FRT_VALIDATOR_SCHEMA,
    classify_result_row,
    normalize_target_gate,
    summarize_gate_rows,
)


def _row(*, valid=True, l1=False, l2=False, l3=False):
    return {
        "validator_schema": CURRENT_FRT_VALIDATOR_SCHEMA,
        "scenario_valid": valid,
        "l1_load_voltage_survival_pass": l1,
        "l2_grid_code_ride_through_pass": l2,
        "l3_full_frt_pass": l3,
    }


def test_invalid_scenario_is_not_a_controller_failure():
    status = classify_result_row(_row(valid=False, l1=False), "L1")
    assert not status.eligible
    assert not status.passed
    assert status.reason == "invalid_test_scenario"


def test_l1_pass_requires_current_schema_and_valid_scenario():
    status = classify_result_row(_row(valid=True, l1=True), "L1")
    assert status.eligible
    assert status.passed


def test_only_l1_is_currently_trainable():
    assert normalize_target_gate("l1", trainable_only=True) == "L1"
    with pytest.raises(ValueError, match="Unsupported HPT target gate"):
        normalize_target_gate("L2", trainable_only=True)


def test_gate_summary_reports_all_layers_without_aliasing():
    summary = summarize_gate_rows(
        [_row(valid=True, l1=True), _row(valid=True, l1=True, l2=True), _row(valid=False)],
        "L1",
    )
    assert summary["scenario_valid_count"] == 2
    assert summary["l1_pass_count"] == 2
    assert summary["l2_pass_count"] == 1
    assert summary["l3_pass_count"] == 0
    assert summary["invalid_scenario_count"] == 1
