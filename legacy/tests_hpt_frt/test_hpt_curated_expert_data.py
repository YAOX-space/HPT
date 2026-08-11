import hashlib
import json
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
EXPERT = ROOT / "experts" / "topology2_single_phase_lvrt"
ARCHIVE = EXPERT / "archive" / "pre_gbt_v3_20260803"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def test_archived_curated_manifest_targets_exist_and_match_hashes() -> None:
    manifest = json.loads(
        (ARCHIVE / "manifests" / "data_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["expert_id"] == "topology2_single_phase_lvrt"
    assert manifest["artifact_count"] == 37
    for artifact in manifest["artifacts"]:
        former_target = ROOT / artifact["target"]
        target = ARCHIVE / former_target.relative_to(EXPERT)
        assert target.is_file(), target
        assert sha256_file(target) == artifact["sha256"], target


def test_archived_support_anchor_preserves_observation_action_contract() -> None:
    path = ARCHIVE / "data" / "support_anchor" / "family_anchor_joint_support.npz"
    with np.load(path, allow_pickle=False) as payload:
        assert payload["observations"].shape == (25647, 24)
        assert payload["actions"].shape == (25647, 4)


def test_archived_metadata_preserves_portable_expert_paths() -> None:
    anchor = json.loads(
        (
            ARCHIVE
            / "data"
            / "support_anchor"
            / "family_anchor_joint_support.json"
        ).read_text(encoding="utf-8")
    )
    proxy = json.loads(
        (ARCHIVE / "proxy" / "model" / "hpt_proxy_calibration.json").read_text(
            encoding="utf-8"
        )
    )
    serialized = json.dumps({"anchor": anchor, "proxy": proxy})
    assert "lab/results" not in serialized
    assert "lab\\results" not in serialized
    assert all(
        item["trace_csv"].startswith("experts/")
        for item in anchor["source_summaries"]
    )


def test_archived_validation_tables_keep_their_original_row_counts() -> None:
    targeted = ARCHIVE / "data" / "validation" / "targeted_family_comparison_rows.csv"
    expanded = ARCHIVE / "data" / "validation" / "expanded_boundary_comparison_rows.csv"
    assert sum(1 for _ in targeted.open(encoding="utf-8-sig")) - 1 == 27
    assert sum(1 for _ in expanded.open(encoding="utf-8-sig")) - 1 == 120


def test_active_workspace_requires_fresh_v3_evidence() -> None:
    descriptor = json.loads((EXPERT / "expert.json").read_text(encoding="utf-8"))
    migration = json.loads(
        (EXPERT / "manifests" / "validator_migration.json").read_text(
            encoding="utf-8"
        )
    )

    assert descriptor["current_model"] is None
    assert descriptor["current_result"] is None
    assert descriptor["current_data_manifest"] is None
    assert descriptor["current_proxy_calibration"] is None
    assert descriptor["promotion_status"] == "archived_pre_v3_revalidation_required"
    assert migration["status"] == "awaiting_fresh_data_proxy_training_and_revalidation"
