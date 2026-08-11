"""Build a family-specific proxy matrix from switch-level comparison rows.

The family specialist evaluator writes one source-of-truth row per controller
and fault case.  This utility converts those rows into the calibration schema
consumed by :mod:`calibrate_hpt_frt_proxy_from_matrix`.  Dynamic actor rows are
treated as measured joint-action responses using their fault-window command
means.  Strong-dq rows are also duplicated as conventional-reference rows.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any

from sac.experiment_metadata import sha256_file, write_experiment_metadata


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / ".git").exists() or (parent / "pyproject.toml").exists():
            return parent
    return Path(__file__).resolve().parents[3]


ROOT = _repo_root()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    keys: list[str] = []
    for row in rows:
        for key in row:
            if key not in keys:
                keys.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


def number(row: dict[str, str], key: str, default: float = math.nan) -> float:
    value = row.get(key, "")
    if value in ("", None):
        return float(default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def finite(value: float) -> float | str:
    return float(value) if math.isfinite(float(value)) else ""


def pu(value: float, base: float) -> float | str:
    return finite(value / base) if math.isfinite(value) else ""


def command(row: dict[str, str], axis: str) -> float:
    return number(
        row,
        f"cmd_m_{axis}_fault_mean",
        number(row, f"cmd_m_{axis}_mean", 0.0),
    )


def convert(row: dict[str, str], *, mode: str) -> dict[str, Any]:
    fault_pu = number(row, "fault_pu", number(row, "family_fault_pu", 1.0))
    duration_s = number(
        row,
        "fault_duration_s",
        number(row, "family_duration_ms", 0.0) / 1000.0,
    )
    fault_start = number(row, "fault_start_s", 0.08)
    fault_clear = number(row, "fault_clear_s", fault_start + duration_s)
    lv_mean = number(row, "lv_mean")
    lv_recovery = number(row, "lv_recovery_mean")
    lv_peak = number(row, "lv_peak")
    lv_min = number(row, "lv_min")
    vdc_mean = number(row, "vdc_mean")
    vdc_min = number(row, "vdc_min")
    vdc_max = number(row, "vdc_max")
    category = str(row.get("gbt_category") or row.get("category") or "LVRT").upper()
    out: dict[str, Any] = dict(row)
    out.update(
        {
            "scenario_type": "fault",
            "mode": mode,
            "source": "family_switchlevel_comparison",
            "source_controller": row.get("controller", row.get("mode", "")),
            "fault": row.get("family_eval_label", row.get("case_name", "")),
            "case_name": row.get("family_eval_label", row.get("case_name", "")),
            "category": category,
            "gbt_category": category,
            "grid_pu": fault_pu,
            "fault_pu": fault_pu,
            "fault_start": fault_start,
            "fault_clear": fault_clear,
            "fault_duration_s": duration_s,
            "raw_m_reg_d": command(row, "reg_d"),
            "raw_m_reg_q": command(row, "reg_q"),
            "raw_m_energy_d": command(row, "energy_d"),
            "raw_m_energy_q": command(row, "energy_q"),
            "cmd_m_reg_d_mean": command(row, "reg_d"),
            "cmd_m_reg_q_mean": command(row, "reg_q"),
            "cmd_m_energy_d_mean": command(row, "energy_d"),
            "cmd_m_energy_q_mean": command(row, "energy_q"),
            "lv_pu_mean": pu(lv_mean, 207.0),
            "lv_recovery_pu_mean": pu(lv_recovery, 207.0),
            "lv_peak_pu": pu(lv_peak, 207.0),
            "lv_min_pu": pu(lv_min, 207.0),
            "vdc_pu_mean": pu(vdc_mean, 800.0),
            "vdc_min_pu": pu(vdc_min, 800.0),
            "vdc_max_pu": pu(vdc_max, 800.0),
            "fault_lv_min_pu": pu(number(row, "fault_lv_min"), 207.0),
            "fault_lv_max_pu": pu(number(row, "fault_lv_max"), 207.0),
        }
    )
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--comparison-csv", type=Path, nargs="+", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--run-id", default=None)
    args = parser.parse_args()

    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for source_path in args.comparison_csv:
        for source_row in read_csv(source_path):
            controller = str(source_row.get("controller", source_row.get("mode", "")))
            label = str(source_row.get("family_eval_label", source_row.get("case_name", "")))
            source_csv = str(source_row.get("source_csv", ""))
            key = (str(source_row.get("topology", "")), label, controller, source_csv)
            if key in seen:
                continue
            seen.add(key)
            rows.append(convert(source_row, mode="joint_sweep"))
            if controller == "strong_dq" or source_row.get("mode") == "conventional_dq":
                rows.append(convert(source_row, mode="conventional_dq"))

    if not rows:
        raise RuntimeError("No switch-level family rows were loaded")
    write_csv(args.out, rows)
    run_id = args.run_id or f"hpt_family_proxy_matrix_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    manifest = {
        "schema": "hpt-family-proxy-matrix-v1",
        "run_id": run_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "sources": [
            {"path": str(path.resolve()), "sha256": sha256_file(path)}
            for path in args.comparison_csv
        ],
        "out": str(args.out.resolve()),
        "out_sha256": sha256_file(args.out),
        "rows": len(rows),
        "joint_rows": sum(row["mode"] == "joint_sweep" for row in rows),
        "conventional_rows": sum(row["mode"] == "conventional_dq" for row in rows),
    }
    manifest_path = args.out.with_suffix(".json")
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    write_experiment_metadata(
        args.out.parent / run_id,
        experiment_name="hpt_family_proxy_matrix",
        config=manifest,
        dataset_manifest=manifest_path,
        extra=manifest,
    )
    print(json.dumps(manifest, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
