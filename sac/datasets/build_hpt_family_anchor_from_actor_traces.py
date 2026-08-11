"""Build one family SAC support dataset from switch-level actor traces.

The input is the summary emitted by ``collect_hpt_family_actor_traces``.  Each
listed CSV already contains the observation and four-dimensional action used
at every control step in Simulink.  This utility preserves those actions and
only reweights temporal zones before concatenating the family dataset.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path

from sac.campaigns.run_hpt_family_specialist_matrix import (
    combine_anchor_datasets,
)
from sac.campaigns.run_hpt_t2_balanced_lvrt_dq_seeded_boundary import (
    build_anchor_from_trace,
)


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / ".git").exists() or (parent / "pyproject.toml").exists():
            return parent
    return Path(__file__).resolve().parents[3]


ROOT = _repo_root()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_head() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return "unknown"


def resolve_path(raw: str | Path) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace-summary", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--dataset-name", default="family_actor_trace_anchor")
    parser.add_argument("--min-time-s", type=float, default=0.0)
    parser.add_argument("--prefault-repeat", type=int, default=2)
    parser.add_argument("--fault-repeat", type=int, default=12)
    parser.add_argument("--recovery-repeat", type=int, default=8)
    parser.add_argument("--tail-repeat", type=int, default=1)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary_path = resolve_path(args.trace_summary).resolve()
    out_dir = resolve_path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    trace_summary = json.loads(summary_path.read_text(encoding="utf-8"))
    cases = list(trace_summary.get("cases") or [])
    if not cases:
        cases = [
            {
                "case_id": item.get("case_label")
                or item.get("case")
                or f"case_{int(item.get('case_index', 0)):03d}",
                "trace_csv": item.get("trace_csv"),
            }
            for item in trace_summary.get("traces") or []
        ]
    if not cases:
        raise RuntimeError(f"No cases found in trace summary: {summary_path}")

    anchor_files: list[Path] = []
    case_summaries: list[dict] = []
    per_case_dir = out_dir / "per_case"
    per_case_dir.mkdir(parents=True, exist_ok=True)
    for case in cases:
        case_id = str(case.get("case_id") or "").strip()
        trace_csv = resolve_path(str(case.get("trace_csv") or "")).resolve()
        if not case_id or not trace_csv.is_file():
            raise FileNotFoundError(f"Missing actor trace for {case_id!r}: {trace_csv}")
        case_npz = per_case_dir / f"{case_id}.npz"
        case_json = per_case_dir / f"{case_id}.json"
        case_summary = build_anchor_from_trace(
            trace_csv,
            case_npz,
            case_json,
            min_time_s=float(args.min_time_s),
            prefault_repeat=int(args.prefault_repeat),
            fault_repeat=int(args.fault_repeat),
            recovery_repeat=int(args.recovery_repeat),
            tail_repeat=int(args.tail_repeat),
        )
        case_summary.update(
            {
                "case_id": case_id,
                "trace_sha256": sha256_file(trace_csv),
                "teacher_source": "validated_transfer_actor_switch_trace",
            }
        )
        case_json.write_text(json.dumps(case_summary, indent=2), encoding="utf-8")
        anchor_files.append(case_npz)
        case_summaries.append(case_summary)

    out_npz = out_dir / f"{args.dataset_name}.npz"
    out_json = out_dir / f"{args.dataset_name}.json"
    combined = combine_anchor_datasets(anchor_files, out_npz, out_json)
    combined.update(
        {
            "schema": "hpt-family-actor-trace-anchor-v1",
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "teacher_source": "validated_transfer_actor_switch_traces",
            "trace_summary": str(summary_path),
            "trace_summary_sha256": sha256_file(summary_path),
            "source_actor": trace_summary.get("dynamic_model"),
            "actor_select_mode": trace_summary.get("actor_select_mode"),
            "policy_mode": trace_summary.get("policy_mode"),
            "sample_stride": trace_summary.get("sample_stride"),
            "temporal_repeats": {
                "prefault": int(args.prefault_repeat),
                "fault": int(args.fault_repeat),
                "recovery": int(args.recovery_repeat),
                "tail": int(args.tail_repeat),
            },
            "actions_modified": False,
            "git_commit": git_head(),
            "cases": case_summaries,
        }
    )
    out_json.write_text(json.dumps(combined, indent=2), encoding="utf-8")
    print(json.dumps(combined, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
