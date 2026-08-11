"""Summarize HPT legacy/conventional/SAC switch-level comparisons."""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / ".git").exists() or (parent / "pyproject.toml").exists():
            return parent
    return Path(__file__).resolve().parents[3]


ROOT = _repo_root()
DEFAULT_DIR = ROOT / "lab" / "results" / "hpt_v2_control_comparison"


def latest_csv(directory: Path) -> Path:
    files = sorted(directory.glob("control_comparison_*.csv"), key=lambda p: p.stat().st_mtime)
    if not files:
        raise FileNotFoundError(f"No control comparison CSV in {directory}")
    return files[-1]


def read_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", newline="", encoding="utf-8-sig") as f:
        for raw in csv.DictReader(f):
            row: dict[str, Any] = {}
            for key, value in raw.items():
                if value in ("", None):
                    row[key] = value
                    continue
                try:
                    row[key] = float(value)
                except ValueError:
                    row[key] = value
            rows.append(row)
    return rows


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    keys: list[str] = []
    for row in rows:
        for key in row:
            if key not in keys:
                keys.append(key)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


def f(row: dict[str, Any] | None, key: str, default: float = 0.0) -> float:
    if row is None:
        return default
    value = row.get(key, default)
    if value in ("", None):
        return default
    return float(value)


def b(row: dict[str, Any] | None, key: str) -> bool:
    if row is None:
        return False
    return str(row.get(key, "")).lower() in {"true", "1"}


def s(row: dict[str, Any] | None, key: str, default: str = "") -> str:
    if row is None:
        return default
    return str(row.get(key, default))


def summarize(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in rows:
        key = (s(row, "topology"), s(row, "scenario_type"), s(row, "case_name"))
        groups[key][s(row, "mode")] = row

    out: list[dict[str, Any]] = []
    for (topology, scenario_type, case_name), by_mode in sorted(groups.items()):
        legacy = by_mode.get("legacy_conventional") or by_mode.get("no_control")
        conv = by_mode.get("conventional_dq")
        rule = by_mode.get("rule_fallback")
        sac = by_mode.get("sac_actor_raw_guard0")
        best_mode = min(
            by_mode,
            key=lambda mode: f(by_mode[mode], "control_score", float("inf")),
        )
        out.append(
            {
                "topology": topology,
                "scenario_type": scenario_type,
                "case_name": case_name,
                "best_mode": best_mode,
                "legacy_score": f(legacy, "control_score", float("nan")),
                "conventional_score": f(conv, "control_score", float("nan")),
                "rule_fallback_score": f(rule, "control_score", float("nan")),
                "sac_score": f(sac, "control_score", float("nan")),
                "sac_minus_conventional_score": f(sac, "control_score", float("nan"))
                - f(conv, "control_score", float("nan")),
                "sac_beat_conventional": f(sac, "control_score", float("inf"))
                < f(conv, "control_score", float("inf")),
                "legacy_pass": b(legacy, "within_window"),
                "conventional_pass": b(conv, "within_window"),
                "sac_pass": b(sac, "within_window"),
                "legacy_lv_recovery": f(legacy, "lv_recovery_mean", float("nan")),
                "conventional_lv_recovery": f(conv, "lv_recovery_mean", float("nan")),
                "sac_lv_recovery": f(sac, "lv_recovery_mean", float("nan")),
                "legacy_vdc_min": f(legacy, "vdc_min", float("nan")),
                "conventional_vdc_min": f(conv, "vdc_min", float("nan")),
                "sac_vdc_min": f(sac, "vdc_min", float("nan")),
                "legacy_reason": s(legacy, "window_reason"),
                "conventional_reason": s(conv, "window_reason"),
                "sac_reason": s(sac, "window_reason"),
            }
        )
    return out


def write_report(path: Path, input_csv: Path, summary: list[dict[str, Any]]) -> None:
    sac_rows = [row for row in summary if row["sac_score"] == row["sac_score"]]
    beat = [row for row in sac_rows if row["sac_beat_conventional"]]
    pass_rows = [row for row in sac_rows if row["sac_pass"]]
    lines = [
        "# HPT Control Comparison Summary",
        "",
        f"- Updated: `{datetime.now().isoformat(timespec='seconds')}`",
        f"- Input CSV: `{input_csv}`",
        f"- Cases: `{len(summary)}`",
        f"- SAC beat conventional: `{len(beat)} / {len(sac_rows)}`",
        f"- SAC pass: `{len(pass_rows)} / {len(sac_rows)}`",
        "",
        "| Topology | Scenario | Case | Best | Legacy | Conventional | SAC | SAC - conv |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for row in summary:
        lines.append(
            f"| {row['topology']} | {row['scenario_type']} | {row['case_name']} | "
            f"{row['best_mode']} | {row['legacy_score']:.3f} | "
            f"{row['conventional_score']:.3f} | {row['sac_score']:.3f} | "
            f"{row['sac_minus_conventional_score']:.3f} |"
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=None)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_DIR)
    args = parser.parse_args()

    csv_path = args.csv or latest_csv(args.out_dir)
    rows = read_rows(csv_path)
    summary = summarize(rows)
    stem = csv_path.stem
    summary_csv = args.out_dir / f"{stem}_summary.csv"
    summary_json = args.out_dir / f"{stem}_summary.json"
    report_md = args.out_dir / f"{stem}_REPORT.md"
    write_csv(summary_csv, summary)
    summary_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    write_report(report_md, csv_path, summary)
    print(
        json.dumps(
            {
                "input_csv": str(csv_path),
                "summary_csv": str(summary_csv),
                "report_md": str(report_md),
                "cases": len(summary),
            },
            indent=2,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


