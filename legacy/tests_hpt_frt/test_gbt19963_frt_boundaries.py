import numpy as np
import pytest

from hpt_frt.common import frt_v2 as FV2


def test_gbt19963_lvrt_boundary_anchor_points():
    for residual in (0.2, 0.5, 0.9):
        assert FV2.lvrt_lower_env(0.0, residual) == pytest.approx(0.2)
        assert FV2.lvrt_lower_env(0.625, residual) == pytest.approx(0.2)
        assert FV2.lvrt_lower_env(2.0, residual) == pytest.approx(0.9)
        assert FV2.lvrt_lower_env(2.5, residual) == pytest.approx(0.9)


def test_gbt19963_hvrt_boundary_anchor_points():
    assert FV2.hvrt_upper_env(0.0) == pytest.approx(1.30)
    assert FV2.hvrt_upper_env(0.5) == pytest.approx(1.30)
    assert FV2.hvrt_upper_env(1.0) == pytest.approx(1.25)
    assert FV2.hvrt_upper_env(2.0) == pytest.approx(1.20)
    assert FV2.hvrt_upper_env(10.0) == pytest.approx(1.20)
    assert FV2.hvrt_upper_env(10.1) == pytest.approx(1.10)


def test_vdc_survive_uses_previous_version_full_domain_limits():
    t = np.array([0.0, 0.1, 0.2, 0.3])
    v1 = np.ones_like(t)
    i2 = np.zeros_like(t)
    good = FV2.evaluate(
        t,
        v1,
        "LVRT",
        0.9,
        0.0,
        0.1,
        Vdc=np.array([1.0, 0.75, 1.0, 1.25]),
        i2=i2,
    )
    low = FV2.evaluate(
        t,
        v1,
        "LVRT",
        0.9,
        0.0,
        0.1,
        Vdc=np.array([1.0, 0.749, 1.0, 1.0]),
        i2=i2,
    )
    assert good["survive"]["status"] == FV2.PASS
    assert low["survive"]["status"] == FV2.FAIL
    assert low["survive"]["reason"] == "Vdc<0.75"
