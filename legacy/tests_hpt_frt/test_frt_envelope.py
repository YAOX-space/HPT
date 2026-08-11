"""test_frt_envelope — GB/T LVRT/HVRT envelopes (frt-v2): ONE explicit boundary, no legacy slack."""
import numpy as np
import pytest
from hpt_frt.common import frt_v2 as F


def test_lvrt_lower_boundary_is_fixed_standard_floor_in_hold():
    res = 0.5
    assert F.lvrt_lower_env(-0.1, res) == 0.9
    assert F.lvrt_lower_env(0.1, res) == 0.20
    assert F.lvrt_lower_env(0.4, res) == 0.20
    mid = F.lvrt_lower_env(1.0, res)
    assert 0.20 < mid < 0.9                           # ramps after the 625 ms hold
    assert abs(F.lvrt_lower_env(2.0, res) - 0.9) < 1e-9


def test_lvrt_boundary_does_not_follow_fault_residual():
    res = 0.5
    assert F.lvrt_lower_env(0.1, res) == 0.20
    assert F.lvrt_lower_env(0.1, 0.9) == 0.20


def test_hvrt_upper_is_time_varying_not_static_135():
    assert F.hvrt_upper_env(0.2) == 1.30
    assert F.hvrt_upper_env(0.8) == 1.25
    assert F.hvrt_upper_env(2.0) == 1.20
    assert F.hvrt_upper_env(10.1) == 1.10
    assert 1.35 not in {F.hvrt_upper_env(x) for x in (0.0, 0.2, 0.8, 1.5, 3.0)}


def test_iq_ref_droop_sign_and_cap():
    assert F.iq_ref_droop(0.5) > 0 and F.iq_ref_droop(0.0) == 0.30
    assert F.iq_ref_droop(1.0) == 0.0
    assert F.iq_ref_droop(1.3) < 0 and F.iq_ref_droop(2.0) == -0.30


def test_invalid_category_is_rejected_not_treated_as_hvrt():
    t = np.linspace(0.0, 1.0, 101)
    x = np.ones_like(t)
    with pytest.raises(ValueError, match='category'):
        F.evaluate(t, x, 'TYPO', 0.5, 0.1, 0.2,
                   Vdc=x, iq=np.zeros_like(t), i_peak=np.zeros_like(t),
                   idq_mag=np.zeros_like(t), i2=np.zeros_like(t))
    with pytest.raises(ValueError, match='category'):
        F.envelope_value('TYPO', 0.0, 0.5)
