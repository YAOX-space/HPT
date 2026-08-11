"""Build a reproducible aggregate switch-trace CSV for DAgger-style BC.

The trajectory specialist needs to train on the states it actually visits in
closed-loop switch-level simulations.  This utility concatenates several trace
CSVs, keeps their original columns, and adds a ``trace_source`` column so the
result can be audited later.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Iterable


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / ".git").exists() or (parent / "pyproject.toml").exists():
            return parent
    return Path(__file__).resolve().parents[3]


ROOT = _repo_root()
RESULTS = ROOT / "lab" / "results" / "hpt_trace_aggregates"


def read_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError(f"CSV has no header: {path}")
        return list(reader.fieldnames), [dict(row) for row in reader]


def ordered_fields(headers: Iterable[list[str]]) -> list[str]:
    fields: list[str] = []
    seen: set[str] = set()
    for header in headers:
        for name in header:
            if name not in seen:
                fields.append(name)
                seen.add(name)
    if "trace_source" not in seen:
        fields.append("trace_source")
    return fields


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--trace", type=Path, action="append", required=True)
    parser.add_argument("--out-dir", type=Path, default=RESULTS)
    args = parser.parse_args()

    traces = [p.resolve() for p in args.trace]
    loaded: list[tuple[Path, list[str], list[dict[str, str]]]] = []
    for path in traces:
        if not path.exists():
            raise FileNotFoundError(path)
        header, rows = read_rows(path)
        loaded.append((path, header, rows))

    out_dir = args.out_dir / args.run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_csv = out_dir / "aggregate_trace.csv"
    fields = ordered_fields(header for _, header, _ in loaded)
    total_rows = 0
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for path, _, rows in loaded:
            for row in rows:
                row = {key: row.get(key, "") for key in fields}
                row["trace_source"] = path.name
                writer.writerow(row)
                total_rows += 1

    metadata = {
        "schema": "hpt-trace-aggregate-v1",
        "run_id": args.run_id,
        "trace_count": len(loaded),
        "row_count": total_rows,
        "traces": [str(path) for path in traces],
        "aggregate_csv": str(out_csv),
    }
    (out_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    main()


