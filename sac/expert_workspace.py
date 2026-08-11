"""Canonical filesystem layout for the twelve HPT fault-family experts."""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path


def repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / ".git").exists() or (parent / "pyproject.toml").exists():
            return parent
    return Path(__file__).resolve().parents[2]


ROOT = repo_root()
EXPERTS_ROOT = ROOT / "experts"


@dataclass(frozen=True)
class ExpertSpec:
    expert_id: str
    topology: str
    category: str
    phase_family: str
    representative_phase_key: str
    covered_phase_keys: tuple[str, ...]


def _specs() -> tuple[ExpertSpec, ...]:
    specs: list[ExpertSpec] = []
    phase_groups = (
        ("balanced", "abc", ("abc",)),
        ("single_phase", "a", ("a", "b", "c")),
        ("two_phase", "ab", ("ab", "bc", "ca")),
    )
    for topology in ("topology1", "topology2"):
        for category in ("lvrt", "hvrt"):
            for phase_family, representative, covered in phase_groups:
                specs.append(
                    ExpertSpec(
                        expert_id=f"{topology}_{phase_family}_{category}",
                        topology=topology,
                        category=category.upper(),
                        phase_family=phase_family,
                        representative_phase_key=representative,
                        covered_phase_keys=covered,
                    )
                )
    return tuple(specs)


EXPERT_SPECS = _specs()
EXPERT_BY_ID = {spec.expert_id: spec for spec in EXPERT_SPECS}


@dataclass(frozen=True)
class ExpertWorkspace:
    spec: ExpertSpec
    root: Path
    data: Path
    raw_switch_level: Path
    train_data: Path
    validation_data: Path
    holdout_data: Path
    support_anchor: Path
    proxy: Path
    proxy_model: Path
    proxy_alignment: Path
    models: Path
    results: Path
    manifests: Path


def normalize_phase_key(phase_key: str | None) -> str:
    key = str(phase_key or "abc").strip().lower().replace("-", "_")
    aliases = {
        "": "abc",
        "balanced": "abc",
        "three_phase": "abc",
        "3ph": "abc",
        "single": "a",
        "single_phase": "a",
        "two": "ab",
        "two_phase": "ab",
    }
    return aliases.get(key, key)


def expert_spec(topology: str, category: str, phase_key: str | None) -> ExpertSpec:
    topology_key = str(topology).strip().lower()
    category_key = str(category).strip().lower()
    phase = normalize_phase_key(phase_key)
    if phase == "abc":
        phase_family = "balanced"
    elif phase in {"a", "b", "c"}:
        phase_family = "single_phase"
    elif phase in {"ab", "bc", "ca"}:
        phase_family = "two_phase"
    else:
        raise ValueError(f"Unsupported HPT fault phase key: {phase_key!r}")
    expert_id = f"{topology_key}_{phase_family}_{category_key}"
    try:
        return EXPERT_BY_ID[expert_id]
    except KeyError as exc:
        raise ValueError(
            f"Unsupported HPT expert family: topology={topology!r}, "
            f"category={category!r}, phase_key={phase_key!r}"
        ) from exc


def expert_workspace(
    topology: str,
    category: str,
    phase_key: str | None,
    *,
    create: bool = False,
) -> ExpertWorkspace:
    spec = expert_spec(topology, category, phase_key)
    root = EXPERTS_ROOT / spec.expert_id
    data = root / "data"
    proxy = root / "proxy"
    workspace = ExpertWorkspace(
        spec=spec,
        root=root,
        data=data,
        raw_switch_level=data / "raw_switch_level",
        train_data=data / "train",
        validation_data=data / "validation",
        holdout_data=data / "holdout",
        support_anchor=data / "support_anchor",
        proxy=proxy,
        proxy_model=proxy / "model",
        proxy_alignment=proxy / "alignment",
        models=root / "models",
        results=root / "results",
        manifests=root / "manifests",
    )
    if create:
        for directory in (
            EXPERTS_ROOT,
            workspace.root,
            workspace.data,
            workspace.raw_switch_level,
            workspace.train_data,
            workspace.validation_data,
            workspace.holdout_data,
            workspace.support_anchor,
            workspace.proxy,
            workspace.proxy_model,
            workspace.proxy_alignment,
            workspace.models,
            workspace.results,
            workspace.manifests,
        ):
            directory.mkdir(parents=True, exist_ok=True)
    return workspace


def initialize_expert_workspaces() -> dict:
    entries: list[dict] = []
    for spec in EXPERT_SPECS:
        workspace = expert_workspace(
            spec.topology,
            spec.category,
            spec.representative_phase_key,
            create=True,
        )
        descriptor = {
            "schema": "hpt-v2-expert-workspace-v1",
            **asdict(spec),
            "validator_schema": "hpt-frt-gates-v3-gbt19963.1",
            "target_gate": "L1",
            "paths": {
                "data": "data",
                "raw_switch_level": "data/raw_switch_level",
                "train_data": "data/train",
                "validation_data": "data/validation",
                "holdout_data": "data/holdout",
                "support_anchor": "data/support_anchor",
                "proxy": "proxy",
                "proxy_model": "proxy/model",
                "proxy_alignment": "proxy/alignment",
                "models": "models",
                "results": "results",
                "manifests": "manifests",
            },
            "current_model": None,
            "current_result": None,
            "current_data_manifest": None,
            "current_proxy_calibration": None,
            "promotion_status": "not_assigned",
            "latest_archive": None,
        }
        descriptor_path = workspace.root / "expert.json"
        if descriptor_path.exists():
            existing = json.loads(descriptor_path.read_text(encoding="utf-8"))
            for key in (
                "current_model",
                "current_result",
                "current_data_manifest",
                "current_proxy_calibration",
                "promotion_status",
                "validator_schema",
                "target_gate",
                "latest_archive",
            ):
                descriptor[key] = existing.get(key, descriptor[key])
        if descriptor["latest_archive"] is None:
            archive_root = workspace.root / "archive"
            archives = sorted(path for path in archive_root.glob("*") if path.is_dir())
            if archives:
                descriptor["latest_archive"] = str(
                    archives[-1].relative_to(ROOT)
                ).replace("\\", "/")
        descriptor_path.write_text(
            json.dumps(descriptor, indent=2) + "\n",
            encoding="utf-8",
        )
        entries.append(
            {
                **asdict(spec),
                "workspace": str(workspace.root.relative_to(ROOT)).replace("\\", "/"),
                "data": str(workspace.data.relative_to(ROOT)).replace("\\", "/"),
                "proxy": str(workspace.proxy.relative_to(ROOT)).replace("\\", "/"),
                "descriptor": str(descriptor_path.relative_to(ROOT)).replace("\\", "/"),
                "current_model": descriptor["current_model"],
                "current_result": descriptor["current_result"],
                "current_data_manifest": descriptor["current_data_manifest"],
                "current_proxy_calibration": descriptor["current_proxy_calibration"],
                "promotion_status": descriptor["promotion_status"],
                "validator_schema": descriptor["validator_schema"],
                "target_gate": descriptor["target_gate"],
                "latest_archive": descriptor["latest_archive"],
            }
        )
    registry = {
        "schema": "hpt-v2-expert-registry-v1",
        "expert_count": len(entries),
        "taxonomy": "2 topologies x 2 FRT categories x 3 phase families",
        "validator_schema": "hpt-frt-gates-v3-gbt19963.1",
        "target_gate": "L1",
        "phase_equivalence": {
            "balanced": ["abc"],
            "single_phase": ["a", "b", "c"],
            "two_phase": ["ab", "bc", "ca"],
        },
        "experts": entries,
    }
    (EXPERTS_ROOT / "registry.json").write_text(
        json.dumps(registry, indent=2) + "\n",
        encoding="utf-8",
    )
    return registry


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--initialize",
        action="store_true",
        help="Create all twelve workspaces and refresh registry.json.",
    )
    parser.add_argument(
        "--resolve",
        nargs=3,
        metavar=("TOPOLOGY", "CATEGORY", "PHASE_KEY"),
        help="Print the canonical workspace for one family.",
    )
    args = parser.parse_args()
    if args.initialize:
        print(json.dumps(initialize_expert_workspaces(), indent=2))
        return
    if args.resolve:
        workspace = expert_workspace(*args.resolve)
        print(workspace.root)
        return
    parser.print_help()


if __name__ == "__main__":
    main()
