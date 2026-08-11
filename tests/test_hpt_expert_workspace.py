import json
from pathlib import Path

import pytest

from sac.expert_workspace import (
    EXPERT_SPECS,
    EXPERTS_ROOT,
    expert_spec,
    expert_workspace,
)


def test_registry_has_exactly_twelve_unique_experts() -> None:
    assert len(EXPERT_SPECS) == 12
    assert len({spec.expert_id for spec in EXPERT_SPECS}) == 12


@pytest.mark.parametrize(
    ("phase_key", "phase_family"),
    [
        ("abc", "balanced"),
        ("balanced", "balanced"),
        ("a", "single_phase"),
        ("b", "single_phase"),
        ("c", "single_phase"),
        ("ab", "two_phase"),
        ("bc", "two_phase"),
        ("ca", "two_phase"),
    ],
)
def test_phase_keys_resolve_to_three_family_types(
    phase_key: str,
    phase_family: str,
) -> None:
    spec = expert_spec("topology2", "LVRT", phase_key)
    assert spec.phase_family == phase_family


def test_workspace_stays_under_experts() -> None:
    workspace = expert_workspace("topology1", "HVRT", "ab")
    parts = workspace.root.parts
    assert parts[-2:] == ("experts", "topology1_two_phase_hvrt")
    assert workspace.data == workspace.root / "data"
    assert workspace.raw_switch_level == workspace.data / "raw_switch_level"
    assert workspace.train_data == workspace.data / "train"
    assert workspace.validation_data == workspace.data / "validation"
    assert workspace.holdout_data == workspace.data / "holdout"
    assert workspace.support_anchor == workspace.data / "support_anchor"
    assert workspace.proxy == workspace.root / "proxy"
    assert workspace.proxy_model == workspace.proxy / "model"
    assert workspace.proxy_alignment == workspace.proxy / "alignment"
    assert workspace.models == workspace.root / "models"
    assert workspace.results == workspace.root / "results"
    assert workspace.manifests == workspace.root / "manifests"


def test_unknown_phase_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unsupported HPT fault phase key"):
        expert_spec("topology1", "LVRT", "ac")


def test_committed_registry_matches_the_twelve_specs() -> None:
    registry = json.loads((EXPERTS_ROOT / "registry.json").read_text(encoding="utf-8"))
    assert registry["expert_count"] == 12
    assert {entry["expert_id"] for entry in registry["experts"]} == {
        spec.expert_id for spec in EXPERT_SPECS
    }
    for entry in registry["experts"]:
        assert entry["data"] == f"{entry['workspace']}/data"
        assert entry["proxy"] == f"{entry['workspace']}/proxy"
        assert "current_data_manifest" in entry
        assert "current_proxy_calibration" in entry


def test_registry_uses_relative_paths_and_existing_current_artifacts() -> None:
    registry = json.loads((EXPERTS_ROOT / "registry.json").read_text(encoding="utf-8"))
    root = EXPERTS_ROOT.parent
    path_keys = (
        "workspace",
        "data",
        "proxy",
        "descriptor",
        "latest_archive",
        "current_model",
        "current_result",
        "current_data_manifest",
        "current_proxy_calibration",
    )
    current_keys = (
        "current_model",
        "current_result",
        "current_data_manifest",
        "current_proxy_calibration",
    )
    for entry in registry["experts"]:
        for key in path_keys:
            value = entry.get(key)
            if value is not None:
                assert not Path(value).is_absolute(), (entry["expert_id"], key, value)
        for key in current_keys:
            value = entry.get(key)
            if value is not None:
                assert (root / value).exists(), (entry["expert_id"], key, value)
