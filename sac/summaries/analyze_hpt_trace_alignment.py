"""Analyze teacher-vs-actor trajectory trace alignment by window zone.

The trajectory specialist workflow already reports overall trace MAE, but the
topology2 LVRT blocker is phase-specific.  This utility compares two trace CSVs
at matching sample indices and writes per-zone action, LV, and DC-link error
summaries so the next actor/training change can target the right window.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any

from ..experiment_metadata import write_experiment_metadata


ACTION_KEYS = [
    ("m_reg_d", "action_01"),
    ("m_reg_q", "action_02"),
    ("m_energy_d", "action_03"),
    ("m_energy_q", "action_04"),
]
STATE_KEYS = [
    ("lv_rms", "lv_rms_inst"),
    ("vdc", "vdc_inst"),
]


def read_rows(path: Path) -> list[dict[str, str]]:
    with Path(path).open("r", newline="", encoding="utf-8-sig") as f:
        return [dict(row) for row in csv.DictReader(f)]


def to_float(value: Any, default: float = float("nan")) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def mean(values: list[float]) -> float:
    finite = [x for x in values if math.isfinite(x)]
    if not finite:
        return float("nan")
    return sum(finite) / len(finite)


def max_abs(values: list[float]) -> float:
    finite = [abs(x) for x in values if math.isfinite(x)]
    if not finite:
        return float("nan")
    return max(finite)


def percentile_abs(values: list[float], q: float) -> float:
    finite = sorted(abs(x) for x in values if math.isfinite(x))
    if not finite:
        return float("nan")
    idx = min(len(finite) - 1, max(0, int(round((len(finite) - 1) * q))))
    return finite[idx]


def row_time(row: dict[str, str]) -> float:
    return to_float(row.get("t"))


def zone_of(reference: dict[str, str], actor: dict[str, str]) -> str:
    return reference.get("window_zone") or actor.get("window_zone") or "unknown"


def paired_errors(
    reference: list[dict[str, str]],
    actor: list[dict[str, str]],
) -> list[dict[str, Any]]:
    n = min(len(reference), len(actor))
    out: list[dict[str, Any]] = []
    for idx in range(n):
        ref = reference[idx]
        act = actor[idx]
        item: dict[str, Any] = {
            "idx": idx,
            "t_ref": row_time(ref),
            "t_actor": row_time(act),
            "window_zone": zone_of(ref, act),
        }
        for name, key in ACTION_KEYS + STATE_KEYS:
            ref_value = to_float(ref.get(key))
            act_value = to_float(act.get(key))
            item[f"{name}_ref"] = ref_value
            item[f"{name}_actor"] = act_value
            item[f"{name}_diff"] = act_value - ref_value
        out.append(item)
    return out


def summarize_group(name: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {"window_zone": name, "samples": len(items)}
    if not items:
        return summary
    times = [to_float(item.get("t_ref")) for item in items]
    summary["t_start"] = min(t for t in times if math.isfinite(t))
    summary["t_end"] = max(t for t in times if math.isfinite(t))
    for signal, _ in ACTION_KEYS + STATE_KEYS:
        diffs = [to_float(item.get(f"{signal}_diff")) for item in items]
        summary[f"{signal}_mae"] = mean([abs(x) for x in diffs])
        summary[f"{signal}_max_abs_error"] = max_abs(diffs)
        summary[f"{signal}_p95_abs_error"] = percentile_abs(diffs, 0.95)
        worst = max(
            items,
            key=lambda item: abs(to_float(item.get(f"{signal}_diff"), 0.0)),
        )
        summary[f"{signal}_worst_t"] = to_float(worst.get("t_ref"))
        summary[f"{signal}_worst_ref"] = to_float(worst.get(f"{signal}_ref"))
        summary[f"{signal}_worst_actor"] = to_float(worst.get(f"{signal}_actor"))
        summary[f"{signal}_worst_diff"] = to_float(worst.get(f"{signal}_diff"))
    return summary


def write_csv_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    keys: list[str] = []
    for row in rows:
        for key in row:
            if key not in keys:
                keys.append(key)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-csv", type=Path, required=True)
    parser.add_argument("--actor-csv", type=Path, required=True)
    parser.add_argument("--run-id", default="")
    parser.add_argument("--out-dir", type=Path, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_id = args.run_id or f"trace_alignment_{Path(args.actor_csv).stem}"
    out_dir = args.out_dir or Path("lab") / "results" / run_id
    reference = read_rows(args.reference_csv)
    actor = read_rows(args.actor_csv)
    pairs = paired_errors(reference, actor)
    zones = sorted({str(item["window_zone"]) for item in pairs})
    summaries = [summarize_group("all", pairs)]
    summaries.extend(
        summarize_group(zone, [item for item in pairs if item["window_zone"] == zone])
        for zone in zones
    )
    config = {
        "schema": "hpt-trace-window-alignment-v1",
        "run_id": run_id,
        "reference_csv": str(args.reference_csv),
        "actor_csv": str(args.actor_csv),
        "reference_rows": len(reference),
        "actor_rows": len(actor),
        "paired_rows": len(pairs),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    write_csv_rows(out_dir / "window_alignment_summary.csv", summaries)
    write_csv_rows(out_dir / "sample_alignment_errors.csv", pairs)
    result = {**config, "window_summaries": summaries}
    (out_dir / "summary.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    write_experiment_metadata(
        out_dir,
        experiment_name="hpt_trace_window_alignment",
        config=config,
        dataset_manifest=args.reference_csv,
        extra={"actor_csv": str(args.actor_csv)},
    )
    print(json.dumps(result, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
