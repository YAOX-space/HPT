"""Summarize conventional-dq FRT boundary sweep results."""
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


def latest_boundary_csv(directory: Path) -> Path:
    files = sorted(
        (
            p
            for p in directory.glob("control_comparison_*conventional_boundary*.csv")
            if "_summary" not in p.stem
        ),
        key=lambda p: p.stat().st_mtime,
    )
    if not files:
        files = sorted(
            (p for p in directory.glob("control_comparison_*.csv") if "_summary" not in p.stem),
            key=lambda p: p.stat().st_mtime,
        )
    if not files:
        raise FileNotFoundError(f"No control comparison CSV in {directory}")
    return files[-1]


def read_rows(path: Path) -> list[dict[str, Any]]:
    with path.open("r", newline="", encoding="utf-8-sig") as f:
        rows: list[dict[str, Any]] = []
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


def f(row: dict[str, Any], key: str, default: float = float("nan")) -> float:
    value = row.get(key, default)
    if value in ("", None):
        return default
    return float(value)


def s(row: dict[str, Any], key: str, default: str = "") -> str:
    return str(row.get(key, default))


def b(row: dict[str, Any], key: str) -> bool:
    value = row.get(key, "")
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).lower() in {"true", "1", "1.0"}


def category(row: dict[str, Any]) -> str:
    return "LVRT" if f(row, "fault_pu") < 1.0 else "HVRT"


def severity(row: dict[str, Any]) -> float:
    pu = f(row, "fault_pu")
    if pu < 1.0:
        return 1.0 - pu
    return pu - 1.0


def pass_flag(row: dict[str, Any], pass_column: str) -> bool:
    if pass_column in row:
        return b(row, pass_column)
    return b(row, "within_window")


def boundary_for_group(rows: list[dict[str, Any]], pass_column: str) -> dict[str, Any]:
    rows = sorted(rows, key=severity)
    passes = [row for row in rows if pass_flag(row, pass_column)]
    fails = [row for row in rows if not pass_flag(row, pass_column)]
    last_pass = None
    first_fail_after_pass = None
    for row in rows:
        if pass_flag(row, pass_column):
            last_pass = row
        elif last_pass is not None and first_fail_after_pass is None:
            first_fail_after_pass = row

    if last_pass is None and fails:
        boundary = f"all_fail_from_{f(fails[0], 'fault_pu'):.3f}pu"
    elif first_fail_after_pass is None and passes:
        boundary = f"all_pass_to_{f(passes[-1], 'fault_pu'):.3f}pu"
    elif last_pass is not None and first_fail_after_pass is not None:
        boundary = (
            f"pass_at_{f(last_pass, 'fault_pu'):.3f}pu__"
            f"fail_at_{f(first_fail_after_pass, 'fault_pu'):.3f}pu"
        )
    else:
        boundary = "no_rows"

    return {
        "n": len(rows),
        "pass_n": len(passes),
        "fail_n": len(fails),
        "mixed": bool(passes and fails),
        "boundary": boundary,
        "last_pass_pu": f(last_pass, "fault_pu") if last_pass else "",
        "first_fail_pu": f(first_fail_after_pass, "fault_pu") if first_fail_after_pass else "",
        "first_fail_reason": s(first_fail_after_pass, reason_column(pass_column))
        if first_fail_after_pass
        else "",
        "full_frt_pass_n": sum(1 for row in rows if b(row, "full_frt_pass")),
        "pass_cases": ";".join(s(row, "case_name") for row in passes),
        "fail_cases": ";".join(s(row, "case_name") for row in fails),
    }


def reason_column(pass_column: str) -> str:
    if pass_column.endswith("_pass"):
        candidate = pass_column[: -len("_pass")] + "_reason"
        if pass_column == "within_window":
            return "window_reason"
        return candidate
    return "window_reason"


def summarize(rows: list[dict[str, Any]], pass_column: str) -> list[dict[str, Any]]:
    rows = [
        row
        for row in rows
        if s(row, "scenario_type") == "fault" and s(row, "mode") == "conventional_dq"
    ]
    groups: dict[tuple[str, str, float], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[(s(row, "topology"), category(row), round(f(row, "fault_duration_s"), 6))].append(row)

    out: list[dict[str, Any]] = []
    for (topology, cat, duration), group_rows in sorted(groups.items()):
        item = {
            "topology": topology,
            "category": cat,
            "duration_s": duration,
            "duration_ms": int(round(1000 * duration)),
            "pass_column": pass_column,
        }
        item.update(boundary_for_group(group_rows, pass_column))
        out.append(item)
    return out


def write_report(path: Path, input_csv: Path, summary: list[dict[str, Any]], pass_column: str) -> None:
    mixed = [row for row in summary if row["mixed"]]
    lines = [
        "# Conventional DQ FRT Boundary Summary",
        "",
        f"- Updated: `{datetime.now().isoformat(timespec='seconds')}`",
        f"- Input CSV: `{input_csv}`",
        f"- Boundary pass column: `{pass_column}`",
        f"- Groups: `{len(summary)}`",
        f"- Mixed pass/fail groups: `{len(mixed)} / {len(summary)}`",
        "",
        "| Topology | Category | Duration | Pass | Fail | Full FRT Pass | Boundary | First Fail Reason |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for row in summary:
        lines.append(
            f"| {row['topology']} | {row['category']} | {row['duration_ms']} ms | "
            f"{row['pass_n']} | {row['fail_n']} | {row['full_frt_pass_n']} | {row['boundary']} | "
            f"{row['first_fail_reason']} |"
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=None)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_DIR)
    parser.add_argument(
        "--pass-column",
        default="voltage_survival_pass",
        help="Boolean column used for boundary detection; full_frt_pass remains reported separately.",
    )
    args = parser.parse_args()

    csv_path = args.csv or latest_boundary_csv(args.out_dir)
    rows = read_rows(csv_path)
    summary = summarize(rows, args.pass_column)
    stem = csv_path.stem
    suffix = args.pass_column.replace("_pass", "")
    summary_csv = args.out_dir / f"{stem}_{suffix}_boundary_summary.csv"
    summary_json = args.out_dir / f"{stem}_{suffix}_boundary_summary.json"
    report_md = args.out_dir / f"{stem}_{suffix}_BOUNDARY_REPORT.md"
    write_csv(summary_csv, summary)
    summary_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    write_report(report_md, csv_path, summary, args.pass_column)
    print(
        json.dumps(
            {
                "input_csv": str(csv_path),
                "pass_column": args.pass_column,
                "summary_csv": str(summary_csv),
                "report_md": str(report_md),
                "groups": len(summary),
                "mixed_groups": sum(1 for row in summary if row["mixed"]),
            },
            indent=2,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


