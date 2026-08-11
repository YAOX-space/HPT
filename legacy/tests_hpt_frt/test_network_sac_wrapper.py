"""Regression tests for deployment-side SAC wrapper utilities."""
import numpy as np
import pytest

from hpt_frt.network.sac_wrapper import HPTController


def test_slew_limiter_uses_three_dimensional_last_action():
    ctrl = object.__new__(HPTController)
    ctrl.slew = (0.1, 0.05)
    ctrl.last_a = np.array([0.0, 0.02, -0.02], dtype=np.float32)
    ctrl.slew_clip_total = 0.0

    iq, se_d, se_q = HPTController._apply_slew(ctrl, 0.3, 0.2, -0.2)

    assert iq == pytest.approx(0.1)
    assert se_d == pytest.approx(0.07)
    assert se_q == pytest.approx(-0.07)
    assert ctrl.slew_clip_total > 0.0
