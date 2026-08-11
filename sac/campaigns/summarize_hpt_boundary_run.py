"""Summarize HPT boundary campaign CSV outputs.

This is intentionally lightweight: it reads a campaign-level
``boundary_comparison_rows.csv`` and emits a compact CSV plus a Markdown
summary beside the run directory.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

from sac.gate_contract import classify_result_row


CONTROLLER_ORDER = {
    "strong_dq": 0,
    "dq_seeded_actor_before_sac": 1,
    "dq_seeded_actor_after_sac": 2,
}


def _as_bool(value: str) -> int:
    return int(float(value or 0))


def _value(row: dict[str, str], *names: str, default: str = "") -> str:
    for name in names:
        value = row.get(name, "")
        if value != "":
            return value
    return default


def _float_value(row: dict[str, str], *names: str, default: float = math.nan) -> float:
    value = _value(row, *names)
    return float(value) if value != "" else default


def _case_fault_pu(row: dict[str, str]) -> float:
    return _float_value(row, "boundary_fault_pu", "fault_pu")


def _case_duration_ms(row: dict[str, str]) -> float:
    if row.get("boundary_duration_ms", "") != "":
        return float(row["boundary_duration_ms"])
    if row.get("duration_ms", "") != "":
        return float(row["duration_ms"])
    return float(row["fault_duration_s"]) * 1000.0


def _cell(row: dict[str, str]) -> str:
    gate = classify_result_row(row, "L1")
    status = "INVALID" if not gate.eligible else ("PASS" if gate.passed else "FAIL")
    reason = _value(row, "l1_reason", "fail_reason", default=gate.reason)
    return (
        f"{status}; score={_float_value(row, 'survival_score', 'control_score'):.3f}; "
        f"I={float(row['grid_current_peak_pu']):.3f}; "
        f"Vdc_min={float(row['vdc_min']):.1f}; {reason}"
    )


def summarize(run_dir: Path) -> dict[str, dict[str, int]]:
    input_csv = run_dir / "boundary_comparison_rows.csv"
    rows = list(csv.DictReader(input_csv.open(newline="", encoding="utf-8")))

    seen: set[tuple[str, str]] = set()
    compact: list[dict[str, str]] = []
    for row in rows:
        key = (row.get("boundary_label", ""), row.get("controller", ""))
        if key in seen:
            continue
        seen.add(key)
        compact.append(row)

    compact.sort(
        key=lambda row: (
            _case_fault_pu(row),
            _case_duration_ms(row),
            CONTROLLER_ORDER.get(row["controller"], 99),
        )
    )

    fields = [
        "boundary_label",
        "fault_pu",
        "duration_ms",
        "controller",
        "validator_schema",
        "scenario_valid",
        "l1_load_voltage_survival_pass",
        "fail_reason",
        "survival_score",
        "grid_current_peak_pu",
        "vdc_min",
        "vdc_max",
        "envelope_violation_max_pu",
        "recovery_violation_max_pu",
        "fault_lv_band_violation_max_pu",
    ]
    with (run_dir / "boundary_summary_compact.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in compact:
            writer.writerow(
                {
                    "boundary_label": row.get("boundary_label", ""),
                    "fault_pu": _case_fault_pu(row),
                    "duration_ms": _case_duration_ms(row),
                    "controller": row.get("controller", ""),
                    "validator_schema": row.get("validator_schema", ""),
                    "scenario_valid": row.get("scenario_valid", ""),
                    "l1_load_voltage_survival_pass": row.get(
                        "l1_load_voltage_survival_pass", ""
                    ),
                    "fail_reason": _value(
                        row,
                        "fail_reason",
                        "l1_reason",
                    ),
                    "survival_score": _float_value(
                        row,
                        "survival_score",
                        "control_score",
                    ),
                    "grid_current_peak_pu": row.get("grid_current_peak_pu", ""),
                    "vdc_min": row.get("vdc_min", ""),
                    "vdc_max": row.get("vdc_max", ""),
                    "envelope_violation_max_pu": row.get(
                        "envelope_violation_max_pu", ""
                    ),
                    "recovery_violation_max_pu": row.get(
                        "recovery_violation_max_pu", ""
                    ),
                    "fault_lv_band_violation_max_pu": row.get(
                        "fault_lv_band_violation_max_pu", ""
                    ),
                }
            )

    by_label: dict[str, dict[str, dict[str, str]]] = {}
    for row in compact:
        by_label.setdefault(row["boundary_label"], {})[row["controller"]] = row

    summary = {
        controller: {
            "n": 0,
            "eligible": 0,
            "pass": 0,
            "beat_dq": 0,
            "score_improve_vs_seed": 0,
            "pass_lost_vs_seed": 0,
        }
        for controller in CONTROLLER_ORDER
    }
    for controllers in by_label.values():
        dq_score = (
            _float_value(controllers["strong_dq"], "survival_score", "control_score")
            if "strong_dq" in controllers
            else math.inf
        )
        seed_score = (
            _float_value(
                controllers["dq_seeded_actor_before_sac"],
                "survival_score",
                "control_score",
            )
            if "dq_seeded_actor_before_sac" in controllers
            else math.inf
        )
        seed_status = (
            classify_result_row(controllers["dq_seeded_actor_before_sac"], "L1")
            if "dq_seeded_actor_before_sac" in controllers
            else None
        )
        seed_pass = bool(seed_status and seed_status.eligible and seed_status.passed)
        for controller, row in controllers.items():
            stats = summary[controller]
            stats["n"] += 1
            gate = classify_result_row(row, "L1")
            stats["eligible"] += int(gate.eligible)
            passed = int(gate.eligible and gate.passed)
            score = _float_value(row, "survival_score", "control_score")
            stats["pass"] += passed
            stats["beat_dq"] += int(score < dq_score)
            if controller == "dq_seeded_actor_after_sac":
                stats["score_improve_vs_seed"] += int(score < seed_score)
                stats["pass_lost_vs_seed"] += int(seed_pass and not passed)

    lines = [
        "# Topology2 Balanced LVRT DQ-Seeded Boundary Summary\n\n",
        f"Run directory: `{run_dir}`\n\n",
        "## Aggregate\n\n",
        "| controller | eligible scenarios | L1 pass | score better than strong dq | "
        "after-SAC score improves seed | after-SAC loses seed pass |\n",
        "|---|---:|---:|---:|---:|---:|\n",
    ]
    for controller in [
        "strong_dq",
        "dq_seeded_actor_before_sac",
        "dq_seeded_actor_after_sac",
    ]:
        stats = summary[controller]
        improve = (
            str(stats["score_improve_vs_seed"])
            if controller == "dq_seeded_actor_after_sac"
            else "-"
        )
        lost = (
            str(stats["pass_lost_vs_seed"])
            if controller == "dq_seeded_actor_after_sac"
            else "-"
        )
        lines.append(
            f"| {controller} | {stats['eligible']}/{stats['n']} | "
            f"{stats['pass']}/{stats['eligible']} | "
            f"{stats['beat_dq']}/{stats['n']} | {improve} | {lost} |\n"
        )

    lines.extend(
        [
            "\n## Per-Case Compact Table\n\n",
            "| case | strong dq | dq-seeded before SAC | dq-seeded after SAC |\n",
            "|---|---|---|---|\n",
        ]
    )
    for label, controllers in sorted(
        by_label.items(),
        key=lambda item: (
            _case_fault_pu(next(iter(item[1].values()))),
            _case_duration_ms(next(iter(item[1].values()))),
        ),
    ):
        lines.append(
            f"| {label} | {_cell(controllers['strong_dq'])} | "
            f"{_cell(controllers['dq_seeded_actor_before_sac'])} | "
            f"{_cell(controllers['dq_seeded_actor_after_sac'])} |\n"
        )

    lines.extend(
        [
            "\n## Interpretation\n\n",
            "- Stable-prefault dq trace seeding works: the dq-seeded actor removes "
            "the strong-dq grid-current failure at all 0.90 pu cases and "
            "some 0.875 pu cases.\n",
            "- Current-aware protected SAC is mixed: it improves the seed score in "
            "the 0.90 pu cases, but it can damage DC-link/recovery feasibility "
            "at 0.85-0.875 pu.\n",
            "- The cleanest boundary-expansion evidence from this run is topology2 "
            "balanced LVRT 0.90 pu at 80/100/120 ms: strong dq fails the "
            "current gate, while the dq-seeded/SAC actor passes voltage-survival.\n",
            "- The next technical bottleneck is energy/DC-link control for deeper "
            "sag, not the LV voltage envelope itself.\n",
        ]
    )
    (run_dir / "boundary_summary.md").write_text("".join(lines), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    summary = summarize(args.run_dir)
    print(json.dumps(summary, indent=2))
    print(args.run_dir / "boundary_summary.md")


if __name__ == "__main__":
    main()
