import numpy as np
import pytest

from sac.frt_envelope import (
    hvrt_upper_envelope,
    lvrt_lower_envelope,
    summarize_grid_code_envelope,
    summarize_load_voltage_quality,
)


@pytest.mark.parametrize(
    ("time_s", "expected_pu"),
    [
        (0.0, 0.20),
        (0.5, 0.20),
        (0.625, 0.20),
        (1.0, 0.20 + 0.70 * (1.0 - 0.625) / (2.0 - 0.625)),
        (2.0, 0.90),
        (10.0, 0.90),
    ],
)
def test_lvrt_standard_breakpoints(time_s, expected_pu):
    assert float(lvrt_lower_envelope(time_s, residual_pu=0.75)) == pytest.approx(
        expected_pu
    )


@pytest.mark.parametrize(
    ("time_s", "expected_pu"),
    [
        (0.0, 1.30),
        (0.5, 1.30),
        (0.625, 1.25),
        (1.0, 1.25),
        (2.0, 1.20),
        (10.0, 1.20),
        (10.0001, 1.10),
    ],
)
def test_hvrt_standard_breakpoints(time_s, expected_pu):
    assert float(hvrt_upper_envelope(time_s)) == pytest.approx(expected_pu)


def test_lvrt_boundary_is_independent_of_applied_residual():
    times = np.array([0.0, 0.625, 1.0, 2.0])
    np.testing.assert_allclose(
        lvrt_lower_envelope(times, residual_pu=0.2),
        lvrt_lower_envelope(times, residual_pu=0.9),
    )


def test_grid_code_scenario_and_load_quality_are_independent_gates():
    t = np.array([0.0, 0.1, 0.2, 0.3])
    pcc = np.array([1.0, 0.50, 0.50, 1.0])
    load = np.array([1.0, 0.70, 0.70, 1.0])

    scenario = summarize_grid_code_envelope(
        t,
        pcc,
        fault_pu=0.50,
        fault_start_s=0.1,
        stop_time_s=0.3,
        assessment_signal="pcc_line_voltage_min",
    )
    quality = summarize_load_voltage_quality(
        t,
        load,
        fault_start_s=0.1,
        fault_clear_s=0.2,
        stop_time_s=0.3,
        recovery_settle_s=0.0,
    )

    assert scenario.scenario_valid
    assert not quality.load_quality_pass

