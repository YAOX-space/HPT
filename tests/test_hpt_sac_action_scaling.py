import numpy as np

from sac.offline.train_hpt_voltage_sac import (
    scale_physical_actions_to_unit_box,
)


def test_support_targets_are_scaled_to_sb3_actor_space() -> None:
    actions = np.asarray([[0.06, 0.0, 0.0, 0.60]], dtype=np.float32)
    low = np.asarray([-0.60, -0.60, -0.95, -0.95], dtype=np.float32)
    high = np.asarray([0.60, 0.60, 0.95, 0.95], dtype=np.float32)

    scaled = scale_physical_actions_to_unit_box(actions, low, high)

    np.testing.assert_allclose(
        scaled,
        np.asarray([[0.10, 0.0, 0.0, 0.60 / 0.95]], dtype=np.float32),
        rtol=1e-6,
        atol=1e-6,
    )


def test_support_target_scaling_clips_out_of_range_actions() -> None:
    actions = np.asarray([[2.0, -2.0, 1.5, -1.5]], dtype=np.float32)
    low = np.asarray([-0.60, -0.60, -0.95, -0.95], dtype=np.float32)
    high = np.asarray([0.60, 0.60, 0.95, 0.95], dtype=np.float32)

    scaled = scale_physical_actions_to_unit_box(actions, low, high)

    np.testing.assert_array_equal(
        scaled,
        np.asarray([[1.0, -1.0, 1.0, -1.0]], dtype=np.float32),
    )
