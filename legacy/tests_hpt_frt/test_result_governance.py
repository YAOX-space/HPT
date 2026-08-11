"""Govern previous-generation frt-v2 result artifacts.

The version-2 ``lab/results`` tree is a mixed artifact store containing actor
weights, trajectories, calibration matrices, and evaluator outputs with
different MAT schemas. It is governed by version-2 metadata, actor hashes, and
promotion tests rather than by the legacy ``metrics_version`` field.
"""
from pathlib import Path

import numpy as np
import pytest
import scipy.io as sio


ROOT = Path(__file__).resolve().parents[1]
ACTIVE_RESULT_DIRS = [ROOT / "src/hpt_frt/network/results"]


def _active_mats():
    for directory in ACTIVE_RESULT_DIRS:
        if not directory.exists():
            continue
        for path in directory.rglob("*.mat"):
            if "legacy_pre_audit" in path.parts:
                continue
            yield path


def _metrics_version(path: Path):
    try:
        data = sio.loadmat(str(path), squeeze_me=True, struct_as_record=False)
    except Exception:
        return "<unreadable>"
    value = data.get("metrics_version")
    if value is None:
        return None
    return str(np.ravel(value)[0]) if isinstance(value, np.ndarray) else str(value)


def test_no_unversioned_or_frtv1_mat_in_active_dirs():
    bad = [
        (str(path.relative_to(ROOT)), _metrics_version(path))
        for path in _active_mats()
        if _metrics_version(path) != "frt-v2"
    ]
    details = "\n".join(f"  {rel}: metrics_version={version!r}" for rel, version in bad)
    assert not bad, f"active legacy result directory contains non-frt-v2 MAT files:\n{details}"


def test_no_frt320_legacy_naming_in_active_dirs():
    bad = []
    for directory in ACTIVE_RESULT_DIRS:
        if not directory.exists():
            continue
        for path in directory.rglob("frt320_*"):
            if "legacy_pre_audit" not in path.parts:
                bad.append(str(path.relative_to(ROOT)))
    assert not bad, "legacy frt320 files must be under legacy_pre_audit:\n" + "\n".join(bad)


def test_legacy_spotcheck_mats_are_isolated():
    sim = ROOT / "src/hpt_frt/network/results/simulink_cases"
    if not sim.exists():
        pytest.skip("simulink_cases absent")
    root_mats = [path.name for path in sim.glob("*.mat")]
    assert root_mats == [], f"unversioned MAT files remain in simulink_cases: {root_mats}"
