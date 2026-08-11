"""Copy selected legacy HPT artifacts into one canonical expert workspace."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import numpy as np

from sac.expert_workspace import EXPERT_BY_ID, EXPERTS_ROOT, ROOT


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def repo_path(value: str) -> Path:
    return (ROOT / Path(value.replace("/", "\\"))).resolve()


def relative_path(path: Path) -> str:
    return str(path.relative_to(ROOT)).replace("\\", "/")


def git_head() -> str:
    process = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return process.stdout.strip() if process.returncode == 0 else "unknown"


def inspect_artifact(path: Path) -> dict[str, Any]:
    suffix = path.suffix.lower()
    if suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        return {
            "format": "json",
            "schema": payload.get("schema") if isinstance(payload, dict) else None,
        }
    if suffix == ".csv":
        with path.open("r", newline="", encoding="utf-8-sig") as stream:
            reader = csv.reader(stream)
            header = next(reader, [])
            rows = sum(1 for _ in reader)
        return {"format": "csv", "rows": rows, "columns": len(header)}
    if suffix == ".npz":
        with np.load(path, allow_pickle=False) as payload:
            return {
                "format": "npz",
                "arrays": {key: list(payload[key].shape) for key in payload.files},
            }
    return {"format": suffix.lstrip(".") or "unknown"}


def canonicalize_anchor(workspace: Path) -> list[dict[str, Any]]:
    support = workspace / "data" / "support_anchor"
    raw = workspace / "data" / "raw_switch_level"
    records: list[dict[str, Any]] = []

    base_source = support / "base_family_anchor.source.json"
    base_target = support / "base_family_anchor.json"
    base = json.loads(base_source.read_text(encoding="utf-8"))
    base["dataset"] = relative_path(support / "base_family_anchor.npz")
    for item in base.get("per_case", []):
        source = Path(str(item.get("trace_csv", "")))
        item["trace_csv"] = relative_path(raw / source.name)
    base["curation"] = {
        "source": relative_path(base_source),
        "source_sha256": sha256_file(base_source),
    }
    base_target.write_text(json.dumps(base, indent=2) + "\n", encoding="utf-8")
    records.append(
        {
            "role": "canonical_base_anchor_metadata",
            "target": relative_path(base_target),
            "sha256": sha256_file(base_target),
            "inspection": inspect_artifact(base_target),
        }
    )

    final_source = support / "family_anchor_joint_support.source.json"
    final_target = support / "family_anchor_joint_support.json"
    final = json.loads(final_source.read_text(encoding="utf-8"))
    final["dataset"] = relative_path(support / "family_anchor_joint_support.npz")
    final["base_family_anchor_json"] = relative_path(base_target)
    for item in final.get("source_summaries", []):
        source = Path(str(item.get("trace_csv", "")))
        item["trace_csv"] = relative_path(raw / source.name)
    final["curation"] = {
        "source": relative_path(final_source),
        "source_sha256": sha256_file(final_source),
    }
    final_target.write_text(json.dumps(final, indent=2) + "\n", encoding="utf-8")
    records.append(
        {
            "role": "canonical_support_anchor_metadata",
            "target": relative_path(final_target),
            "sha256": sha256_file(final_target),
            "inspection": inspect_artifact(final_target),
        }
    )
    return records


def canonicalize_proxy(workspace: Path) -> dict[str, Any]:
    proxy_model = workspace / "proxy" / "model"
    alignment = workspace / "proxy" / "alignment"
    source = proxy_model / "hpt_proxy_calibration_r2.source.json"
    target = proxy_model / "hpt_proxy_calibration.json"
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["source_csv"] = relative_path(alignment / "base_proxy_sweep.csv")
    payload["energy_source_csv"] = relative_path(alignment / "base_energy_sweep.csv")
    payload["frt_source_csv"] = [
        relative_path(alignment / "family_switch_matrix.csv"),
        relative_path(alignment / "energy_q_support_matrix.csv"),
        relative_path(alignment / "joint_support_matrix.csv"),
        relative_path(alignment / "energy_d_zero_matrix.csv"),
    ]
    payload["conventional_source_csv"] = relative_path(
        alignment / "family_switch_matrix.csv"
    )
    payload["curation"] = {
        "source": relative_path(source),
        "source_sha256": sha256_file(source),
        "alignment_scope": "calibration sources; no untouched trajectory holdout",
    }
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return {
        "role": "canonical_family_proxy_calibration",
        "target": relative_path(target),
        "sha256": sha256_file(target),
        "inspection": inspect_artifact(target),
    }


def curate(spec_path: Path) -> dict[str, Any]:
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    expert_id = str(spec["expert_id"])
    if expert_id not in EXPERT_BY_ID:
        raise ValueError(f"Unknown expert_id: {expert_id}")
    workspace = (EXPERTS_ROOT / expert_id).resolve()
    records: list[dict[str, Any]] = []
    for artifact in spec["artifacts"]:
        source = repo_path(str(artifact["source"]))
        target = (workspace / Path(str(artifact["target"]))).resolve()
        if workspace not in target.parents:
            raise ValueError(f"Target escapes expert workspace: {target}")
        if not source.is_file():
            raise FileNotFoundError(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        source_hash = sha256_file(source)
        target_hash = sha256_file(target)
        if source_hash != target_hash:
            raise RuntimeError(f"Hash mismatch after copying {source} to {target}")
        records.append(
            {
                "role": artifact["role"],
                "source": relative_path(source),
                "target": relative_path(target),
                "sha256": target_hash,
                "bytes": target.stat().st_size,
                "inspection": inspect_artifact(target),
            }
        )

    records.extend(canonicalize_anchor(workspace))
    records.append(canonicalize_proxy(workspace))
    manifest = {
        "schema": "hpt-v2-curated-expert-data-v1",
        "expert_id": expert_id,
        "git_head_at_curation": git_head(),
        "selection_spec": relative_path(spec_path),
        "selection_spec_sha256": sha256_file(spec_path),
        "selection_policy": spec["selection_policy"],
        "dataset_status": spec["dataset_status"],
        "artifact_count": len(records),
        "artifacts": records,
    }
    manifest_path = workspace / "manifests" / "data_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("selection_spec", type=Path)
    args = parser.parse_args()
    spec_path = args.selection_spec
    if not spec_path.is_absolute():
        spec_path = ROOT / spec_path
    print(json.dumps(curate(spec_path.resolve()), indent=2))


if __name__ == "__main__":
    main()
