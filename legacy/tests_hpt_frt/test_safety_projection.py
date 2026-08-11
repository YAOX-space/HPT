"""test_safety_projection — deployment-side reactive sign-consistent dead-band projection
(src/hpt_frt/device/safety_projection.py). Verifies the projection forces iq onto the correct side of
zero in the constrained regions, never touches a correct-direction command, keeps the action 3-D and
within the current bound, and reports metadata. NO training / Simulink / result mutation involved."""
import numpy as np
import pytest
from hpt_frt.device.safety_projection import project_action, required_iq_sign, is_wrong_sign, DEFAULTS


def test_undervolt_negative_iq_projected_nonnegative():
    # LVRT under-voltage (V+<0.9): absorbing (iq<0) is wrong sign -> projected to >= 0
    proj, meta = project_action([-0.08, 0.05, -0.03], V1_pu=0.875, category='LVRT')
    assert proj[0] >= 0.0
    assert meta['triggered'] and meta['region'] == 'undervolt'
    assert meta['iq_in'] == -0.08 and meta['iq_out'] >= 0.0
    assert not is_wrong_sign(proj[0], 0.875)


def test_overvolt_positive_iq_projected_nonpositive():
    # HVRT over-voltage (V+>1.1): sourcing (iq>0) is wrong sign -> projected to <= 0
    proj, meta = project_action([0.06, -0.02, 0.01], V1_pu=1.105, category='HVRT')
    assert proj[0] <= 0.0
    assert meta['triggered'] and meta['region'] == 'overvolt'
    assert not is_wrong_sign(proj[0], 1.105)


def test_near_zero_demand_wrong_sign_zeroed():
    # near-boundary, tiny wrong-signed iq -> projected to 0 (dead-band), correct direction
    proj, meta = project_action([-0.005, 0.0, 0.0], V1_pu=0.899, category='LVRT')
    assert proj[0] == 0.0 and meta['triggered']
    proj2, meta2 = project_action([0.004, 0.0, 0.0], V1_pu=1.101, category='HVRT')
    assert proj2[0] == 0.0 and meta2['triggered']


def test_correct_direction_iq_unchanged():
    # under-voltage with capacitive (iq>0) is CORRECT -> untouched
    proj, meta = project_action([0.20, 0.05, -0.05], V1_pu=0.6, category='LVRT')
    assert proj[0] == pytest.approx(0.20) and not meta['triggered']
    # over-voltage with absorbing (iq<0) is CORRECT -> untouched
    proj2, meta2 = project_action([-0.18, 0.0, 0.0], V1_pu=1.25, category='HVRT')
    assert proj2[0] == pytest.approx(-0.18) and not meta2['triggered']


def test_neutral_band_no_sign_constraint():
    # 0.9 <= V+ <= 1.1: no wrong-sign rule -> command passes through (any sign)
    for iq in (-0.1, 0.0, 0.1):
        proj, meta = project_action([iq, 0.0, 0.0], V1_pu=1.0, category='LVRT')
        assert proj[0] == pytest.approx(iq) and meta['region'] == 'neutral' and not meta['triggered']


def test_output_is_3d_and_mse_preserved():
    proj, _ = project_action([-0.07, 0.111, -0.222], V1_pu=0.8)
    assert proj.shape == (3,)
    assert proj[1] == pytest.approx(0.111) and proj[2] == pytest.approx(-0.222)  # mse untouched


def test_current_bound_never_exceeded():
    cap = DEFAULTS['iq_cap']
    # an over-cap correct-direction command is clipped to the bound
    proj, meta = project_action([0.5, 0.0, 0.0], V1_pu=0.5, current_limit=cap)
    assert abs(proj[0]) <= cap + 1e-12
    # projection never produces |iq| above cap in any region
    for V1 in (0.2, 0.875, 1.0, 1.1, 1.3):
        for iq in (-0.5, -0.05, 0.0, 0.05, 0.5):
            p, _ = project_action([iq, 0, 0], V1_pu=V1)
            assert abs(p[0]) <= DEFAULTS['iq_cap'] + 1e-12


def test_metadata_records_reason_and_signs():
    proj, meta = project_action([-0.09, 0, 0], V1_pu=0.85)
    for k in ('triggered', 'reason', 'iq_in', 'iq_out', 'V1_pu', 'required_sign', 'region', 'cap'):
        assert k in meta
    assert 'wrong_sign' in meta['reason'] and meta['required_sign'] == 1


def test_projection_removes_wrong_sign_invariant():
    # core guarantee: after projection, is_wrong_sign is NEVER true in a constrained region
    for V1 in (0.2, 0.6, 0.875, 0.899, 1.101, 1.105, 1.3):
        for iq in np.linspace(-0.27, 0.27, 25):
            p, _ = project_action([iq, 0, 0], V1_pu=V1)
            assert not is_wrong_sign(p[0], V1), (V1, iq, p[0])


def test_required_sign_thresholds():
    assert required_iq_sign(0.89) == 1 and required_iq_sign(1.11) == -1 and required_iq_sign(1.0) == 0
