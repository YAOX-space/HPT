"""Experiment metadata helpers for version 2 HPT SAC runs.

The switch-level HPT workflow produces many result folders.  This module keeps
each run tied to the source state, configuration, model files, and checkpoints
used to create it.
"""
from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[2]


def _run_git(args: Sequence[str], root: Path = ROOT) -> str | None:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(root),
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def git_metadata(root: Path = ROOT, *, status_sample_limit: int = 60) -> dict[str, Any]:
    """Return compact Git state for a result metadata file."""

    status_text = _run_git(["status", "--short"], root) or ""
    status_lines = [line for line in status_text.splitlines() if line.strip()]
    return {
        "commit": _run_git(["rev-parse", "HEAD"], root),
        "commit_short": _run_git(["rev-parse", "--short", "HEAD"], root),
        "branch": _run_git(["rev-parse", "--abbrev-ref", "HEAD"], root),
        "dirty": bool(status_lines),
        "status_count": len(status_lines),
        "status_sample": status_lines[:status_sample_limit],
        "status_truncated": len(status_lines) > status_sample_limit,
    }


def sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str | None:
    """Return a file SHA-256 hash, or None when the file is absent."""

    p = Path(path)
    if not p.exists() or not p.is_file():
        return None
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def _path_string(path: Path | str | None) -> str | None:
    if path is None:
        return None
    return str(Path(path))


def _hash_map(paths: Mapping[str, Path | str] | None) -> dict[str, str | None]:
    if not paths:
        return {}
    return {name: sha256_file(Path(path)) for name, path in sorted(paths.items())}


def make_experiment_metadata(
    *,
    experiment_name: str,
    run_dir: Path,
    config: Mapping[str, Any] | None = None,
    topology_models: Mapping[str, Path | str] | None = None,
    dataset_manifest: Path | str | None = None,
    policy_checkpoint: Path | str | None = None,
    extra: Mapping[str, Any] | None = None,
    root: Path = ROOT,
) -> dict[str, Any]:
    """Build a JSON-serializable metadata record for an experiment run."""

    topology_models = topology_models or {}
    metadata: dict[str, Any] = {
        "schema": "hpt-v2-experiment-metadata-v1",
        "experiment_name": experiment_name,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "run_dir": str(run_dir),
        "command": sys.argv,
        "git": git_metadata(root),
        "python": {
            "executable": sys.executable,
            "version": sys.version,
            "platform": platform.platform(),
        },
        "topology_models": {
            name: _path_string(path) for name, path in sorted(topology_models.items())
        },
        "model_hashes": _hash_map(topology_models),
        "dataset_manifest": _path_string(dataset_manifest),
        "policy_checkpoint": _path_string(policy_checkpoint),
        "policy_checkpoint_hash": sha256_file(Path(policy_checkpoint))
        if policy_checkpoint is not None
        else None,
        "config": dict(config or {}),
    }
    if extra:
        metadata["extra"] = dict(extra)
    return metadata


def write_experiment_metadata(
    run_dir: Path,
    *,
    experiment_name: str,
    config: Mapping[str, Any] | None = None,
    topology_models: Mapping[str, Path | str] | None = None,
    dataset_manifest: Path | str | None = None,
    policy_checkpoint: Path | str | None = None,
    extra: Mapping[str, Any] | None = None,
    filename: str = "metadata.json",
    root: Path = ROOT,
) -> dict[str, Any]:
    """Write metadata into ``run_dir`` and return the record."""

    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    metadata = make_experiment_metadata(
        experiment_name=experiment_name,
        run_dir=run_dir,
        config=config,
        topology_models=topology_models,
        dataset_manifest=dataset_manifest,
        policy_checkpoint=policy_checkpoint,
        extra=extra,
        root=root,
    )
    (run_dir / filename).write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return metadata
