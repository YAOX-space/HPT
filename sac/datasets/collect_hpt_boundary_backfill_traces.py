"""Collect explicit boundary backfill traces for proxy repair.

This script directly runs the strong-dq switch-level trajectory collector for
specified fault_pu:duration_ms pairs.  It is intended to add raw timestep
traces near the pass/fail boundary without requiring a pre-existing matrix CSV.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from sac.campaigns.run_hpt_t2_balanced_lvrt_dq_seeded_boundary import (
    BoundaryCase,
    ROOT,
    make_family_label,
    matlab_collect_dq_trace,
)
from sac.expert_workspace import expert_workspace


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_case_pairs(raw: str, *, topology: str, category: str, phase_key: str, family_label: str) -> list[BoundaryCase]:
    cases: list[BoundaryCase] = []
    for item in str(raw or "").split(";"):
        item = item.strip()
        if not item:
            continue
        if ":" not in item:
            raise ValueError(f"Bad case pair {item!r}; expected fault_pu:duration_ms")
        pu_text, duration_text = item.split(":", 1)
        cases.append(
            BoundaryCase(
                fault_pu=float(pu_text),
                duration_s=float(duration_text) / 1000.0,
                topology=topology,
                category=category.upper(),
                phase_key=phase_key.lower(),
                family_label=family_label,
            )
        )
    return cases


def default_case_pairs() -> str:
    depths = [0.800, 0.825, 0.850, 0.875]
    durations = [100, 120, 160]
    return ";".join(f"{depth:.3f}:{duration}" for depth in depths for duration in durations)


def jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default="p2_t2sp_boundary_backfill_dc_v5_20260804")
    parser.add_argument("--topology", choices=["topology1", "topology2"], default="topology2")
    parser.add_argument("--category", choices=["LVRT", "HVRT"], default="LVRT")
    parser.add_argument("--phase-key", choices=["abc", "a", "b", "c", "ab", "bc", "ca"], default="a")
    parser.add_argument("--family-label", default="")
    parser.add_argument("--case-pairs", default=default_case_pairs())
    parser.add_argument("--fault-start-s", type=float, default=0.035)
    parser.add_argument("--max-cases", type=int, default=None)
    args = parser.parse_args()

    family_label = args.family_label or make_family_label(args.topology, args.category, args.phase_key)
    cases = parse_case_pairs(
        args.case_pairs,
        topology=args.topology,
        category=args.category,
        phase_key=args.phase_key,
        family_label=family_label,
    )
    if args.max_cases is not None:
        cases = cases[: args.max_cases]
    if not cases:
        raise RuntimeError("No boundary backfill cases requested.")

    workspace = expert_workspace(args.topology, args.category, args.phase_key, create=True)
    run_dir = workspace.data / "proxy2_transition" / args.run_id
    raw_dir = run_dir / "raw_traces"
    matlab_dir = run_dir / "matlab"
    raw_dir.mkdir(parents=True, exist_ok=True)
    matlab_dir.mkdir(parents=True, exist_ok=True)

    records: list[dict[str, Any]] = []
    for idx, case in enumerate(cases, start=1):
        case_dir = matlab_dir / f"case_{idx:03d}"
        case_dir.mkdir(parents=True, exist_ok=True)
        trace_csv = matlab_collect_dq_trace(
            case,
            case_dir,
            fault_start_s=args.fault_start_s,
            trace_dir=raw_dir,
        )
        records.append(
            {
                "case_index": idx,
                "case_label": case.label,
                "fault_pu": case.fault_pu,
                "duration_ms": case.duration_ms,
                "phase_key": case.phase_key,
                "trace_csv": str(trace_csv),
                "trace_sha256": sha256_file(trace_csv),
            }
        )
        (run_dir / "progress.json").write_text(json.dumps(records, indent=2), encoding="utf-8")

    summary = {
        "schema": "hpt-boundary-backfill-trace-collection-v1",
        "run_id": args.run_id,
        "repo_root": str(ROOT),
        "raw_trace_dir": str(raw_dir),
        "config": jsonable(vars(args)),
        "case_count": len(cases),
        "traces": records,
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
