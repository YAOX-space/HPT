"""Collect switch-level fixed-action responses for one HPT fault family.

This campaign is the data gate between the conventional-dq boundary matrix and
family-level SAC training.  It evaluates fixed four-command actions through the
same v3 Simulink validator used by the strong-dq matrix, then writes compact
rows that can be merged into the family proxy calibration matrix.

The produced rows are calibration evidence only.  They are not promoted actors.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Iterable

import numpy as np

from sac.campaigns.run_hpt_family_specialist_matrix import (
    as_float,
    default_family_label,
    make_cases,
    parse_float_list,
    parse_int_list,
    parse_phase_key_list,
    representative_phase_key,
    truthy,
)
from sac.campaigns.run_hpt_t2_balanced_lvrt_dq_seeded_boundary import (
    ROOT,
    SIMULINK,
    bounded_artifact_path,
    compact_label,
    latest_file,
    mat_vector,
    phase_pu_vector,
    run_logged,
    write_csv,
    _matlab_string,
)
from sac.experiment_metadata import write_experiment_metadata
from sac.expert_workspace import expert_workspace
from sac.gate_contract import CURRENT_FRT_VALIDATOR_SCHEMA, summarize_gate_rows


def parse_action_list(raw: str) -> list[tuple[float, float, float, float]]:
    """Parse ``a,b,c,d;...`` candidate actions."""

    actions: list[tuple[float, float, float, float]] = []
    for chunk in str(raw or "").split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        values = [float(part.strip()) for part in chunk.split(",") if part.strip()]
        if len(values) != 4:
            raise argparse.ArgumentTypeError(
                f"Each action must have four values [m_reg_d,m_reg_q,m_energy_d,m_energy_q], got {chunk!r}"
            )
        actions.append((values[0], values[1], values[2], values[3]))
    return actions


def build_cartesian_actions(args: argparse.Namespace) -> list[tuple[float, float, float, float]]:
    explicit = parse_action_list(args.candidate_actions)
    if explicit:
        return explicit
    reg_d = parse_float_list(args.reg_d_grid)
    reg_q = parse_float_list(args.reg_q_grid)
    energy_d = parse_float_list(args.energy_d_grid)
    energy_q = parse_float_list(args.energy_q_grid)
    return [
        (float(rd), float(rq), float(ed), float(eq))
        for rd in reg_d
        for rq in reg_q
        for ed in energy_d
        for eq in energy_q
    ]


def action_token(action: tuple[float, float, float, float]) -> str:
    names = ("rd", "rq", "ed", "eq")
    parts = []
    for name, value in zip(names, action):
        token = f"{value:+.3f}".replace("+", "p").replace("-", "m").replace(".", "p")
        parts.append(f"{name}{token}")
    return "_".join(parts)


def matlab_evaluate_fixed_action(
    case,
    action: tuple[float, float, float, float],
    action_id: str,
    run_dir: Path,
    *,
    fault_start_s: float,
    fault_stop_margin_s: float,
    compare_dir: Path,
) -> Path:
    compare_dir.mkdir(parents=True, exist_ok=True)
    label = f"{case.label}_{action_id}_fix"
    matlab_label = compact_label(label)
    runner = bounded_artifact_path(
        run_dir,
        prefix="eval_",
        label=label,
        suffix=".m",
    )
    runner.write_text(
        "\n".join(
            [
                f"cd('{_matlab_string(ROOT)}');",
                f"addpath(genpath('{_matlab_string(SIMULINK)}'));",
                f'hpt_compare_topology = "{case.topology}";',
                'hpt_compare_scenario_type = "fault";',
                'hpt_compare_case_name = "all";',
                'hpt_compare_modes = ["fixed_action"];',
                "hpt_compare_energy_enable = 1.0;",
                "hpt_compare_voltage_survival_current_gate = true;",
                f"hpt_compare_fault_start = {fault_start_s:.12g};",
                f"hpt_compare_fault_stop_margin = {fault_stop_margin_s:.12g};",
                (
                    "hpt_compare_faults = "
                    f"{{'{case.case_name}', {case.fault_pu:.12g}, "
                    f"{case.duration_s:.12g}, {mat_vector(phase_pu_vector(case))}}};"
                ),
                f"hpt_compare_fixed_action = {mat_vector(action)};",
                f'hpt_compare_run_label = "{matlab_label}";',
                f"hpt_compare_output_dir = '{_matlab_string(compare_dir)}';",
                f"run('{_matlab_string(SIMULINK / 'evaluators' / 'eval_hpt_v2_control_comparison.m')}');",
            ]
        ),
        encoding="utf-8",
    )
    before = time.time()
    log_path = bounded_artifact_path(
        run_dir,
        prefix="",
        label=label,
        suffix="_eval.log",
    )
    run_logged(
        ["matlab", "-batch", f"run('{_matlab_string(runner)}')"],
        cwd=ROOT,
        log_path=log_path,
    )
    log_text = log_path.read_text(encoding="utf-8", errors="replace")
    saved = re.findall(r"Saved CSV:\s*(.+?\.csv)", log_text)
    if saved:
        saved_path = Path(saved[-1].strip())
        deadline = time.time() + 300.0
        while time.time() <= deadline:
            if saved_path.exists():
                return saved_path
            time.sleep(0.2)
        return saved_path
    return latest_file(
        f"control_comparison_{case.topology}_fault_all_{matlab_label}_*.csv",
        after=before,
        directory=compare_dir,
    )


def read_fixed_rows(
    csv_path: Path,
    case,
    action: tuple[float, float, float, float],
    action_id: str,
) -> list[dict]:
    deadline = time.time() + 300.0
    while time.time() <= deadline and not csv_path.exists():
        time.sleep(0.2)
    rows: list[dict] = []
    with csv_path.open("r", newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            if str(row.get("mode") or "") != "fixed_action":
                continue
            out = dict(row)
            out["controller"] = "fixed_action"
            out["action_id"] = action_id
            out["requested_m_reg_d"] = f"{action[0]:.9g}"
            out["requested_m_reg_q"] = f"{action[1]:.9g}"
            out["requested_m_energy_d"] = f"{action[2]:.9g}"
            out["requested_m_energy_q"] = f"{action[3]:.9g}"
            out["family_eval_label"] = case.label
            out["family_fault_pu"] = f"{case.fault_pu:.6g}"
            out["family_duration_ms"] = str(case.duration_ms)
            out["fault_phase_key"] = case.phase_key
            out["source_csv"] = str(csv_path)
            rows.append(out)
    stale = [
        row
        for row in rows
        if str(row.get("validator_schema") or "") != CURRENT_FRT_VALIDATOR_SCHEMA
    ]
    if stale:
        found = sorted({str(row.get("validator_schema") or "missing") for row in stale})
        raise RuntimeError(
            f"Refusing stale switch-level evidence from {csv_path}: "
            f"validator_schema={found!r}, expected {CURRENT_FRT_VALIDATOR_SCHEMA!r}"
        )
    return rows


def summarize_rows(rows: list[dict], out_json: Path) -> dict:
    gate_summary = summarize_gate_rows(rows, "L1")
    scores = [as_float(row.get("control_score")) for row in rows]
    grid_i = [as_float(row.get("grid_current_peak_pu")) for row in rows]
    env = [as_float(row.get("envelope_violation_max_pu")) for row in rows]
    vdc_min = [as_float(row.get("vdc_min")) for row in rows]
    vdc_max = [as_float(row.get("vdc_max")) for row in rows]
    by_action: dict[str, dict[str, object]] = {}
    for action_id in sorted({str(row.get("action_id", "")) for row in rows}):
        subset = [row for row in rows if str(row.get("action_id", "")) == action_id]
        action_scores = [as_float(row.get("control_score")) for row in subset]
        by_action[action_id] = {
            "rows": len(subset),
            "l1_pass_count": sum(truthy(row.get("l1_load_voltage_survival_pass")) for row in subset),
            "score_mean": float(np.nanmean(action_scores)) if action_scores else float("nan"),
        }
    summary = {
        **gate_summary,
        "rows": len(rows),
        "voltage_survival_pass_count": gate_summary["l1_pass_count"],
        "envelope_pass_count": sum(truthy(row.get("envelope_pass")) for row in rows),
        "recovery_pass_count": sum(truthy(row.get("recovery_envelope_pass")) for row in rows),
        "vdc_pass_count": sum(
            as_float(row.get("vdc_min")) >= 650.0 and as_float(row.get("vdc_max")) <= 1000.0
            for row in rows
        ),
        "grid_current_pass_count": sum(truthy(row.get("gbt_grid_current_limit_pass")) for row in rows),
        "score_mean": float(np.nanmean(scores)) if scores else float("nan"),
        "score_min": float(np.nanmin(scores)) if scores else float("nan"),
        "score_max": float(np.nanmax(scores)) if scores else float("nan"),
        "grid_current_peak_max_pu": float(np.nanmax(grid_i)) if grid_i else float("nan"),
        "envelope_violation_max_pu": float(np.nanmax(env)) if env else float("nan"),
        "vdc_min": float(np.nanmin(vdc_min)) if vdc_min else float("nan"),
        "vdc_max": float(np.nanmax(vdc_max)) if vdc_max else float("nan"),
        "by_action": by_action,
    }
    out_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def write_markdown(run_dir: Path, metadata: dict, summary: dict, rows: Iterable[dict]) -> None:
    lines = [
        "# HPT fixed-action family response summary",
        "",
        "This run collects switch-level fixed-action responses for proxy calibration.",
        "It is not actor promotion evidence.",
        "",
        "## Configuration",
        "",
    ]
    for key in (
        "family_label",
        "topology",
        "category",
        "phase_keys",
        "eval_depths",
        "eval_durations_ms",
        "candidate_actions",
        "validator_schema",
    ):
        lines.append(f"- {key}: `{metadata.get(key)}`")
    lines.extend(
        [
            "",
            "## Summary",
            "",
            f"- rows: `{summary.get('rows')}`",
            f"- scenario valid: `{summary.get('scenario_valid_count')}`",
            f"- L1 pass: `{summary.get('l1_pass_count')}`",
            f"- score mean: `{summary.get('score_mean')}`",
            f"- score min/max: `{summary.get('score_min')}` / `{summary.get('score_max')}`",
            f"- Vdc min/max: `{summary.get('vdc_min')}` / `{summary.get('vdc_max')}`",
            f"- grid current peak max pu: `{summary.get('grid_current_peak_max_pu')}`",
            f"- envelope violation max pu: `{summary.get('envelope_violation_max_pu')}`",
            "",
            "## Per-case rows",
            "",
            "| case | phase | action | scenario valid | L1 pass | reason | score | grid I | Vdc min/max | env | rec |",
            "|---|---|---|---:|---:|---|---:|---:|---:|---:|---:|",
        ]
    )
    for row in rows:
        lines.append(
            "| {case} | {phase} | {action} | {valid} | {l1} | {reason} | {score:.3f} | {grid:.3f} | "
            "{vmin:.1f}/{vmax:.1f} | {env:.5f} | {rec:.5f} |".format(
                case=row.get("family_eval_label", ""),
                phase=row.get("fault_phase_key", ""),
                action=row.get("action_id", ""),
                valid=row.get("scenario_valid", ""),
                l1=row.get("l1_load_voltage_survival_pass", ""),
                reason=row.get("l1_reason", ""),
                score=as_float(row.get("control_score")),
                grid=as_float(row.get("grid_current_peak_pu")),
                vmin=as_float(row.get("vdc_min")),
                vmax=as_float(row.get("vdc_max")),
                env=as_float(row.get("envelope_violation_max_pu")),
                rec=as_float(row.get("recovery_violation_max_pu")),
            )
        )
    (run_dir / "FIXED_ACTION_FAMILY_SUMMARY.md").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--topology", choices=["topology1", "topology2"], default="topology2")
    parser.add_argument("--category", choices=["LVRT", "HVRT"], default="LVRT")
    parser.add_argument("--phase-key", choices=["abc", "a", "b", "c", "ab", "bc", "ca"], default="a")
    parser.add_argument("--phase-keys", default="")
    parser.add_argument("--family-label", default="")
    parser.add_argument("--eval-depths", default="0.75,0.825")
    parser.add_argument("--eval-durations-ms", default="160,200")
    parser.add_argument("--fault-start-s", type=float, default=0.080)
    parser.add_argument("--fault-stop-margin-s", type=float, default=0.125)
    parser.add_argument(
        "--candidate-actions",
        default="",
        help="Semicolon-separated explicit actions: rd,rq,ed,eq;rd,rq,ed,eq.",
    )
    parser.add_argument("--reg-d-grid", default="0.00,0.12,0.24")
    parser.add_argument("--reg-q-grid", default="-0.08,0.00,0.08")
    parser.add_argument("--energy-d-grid", default="-0.08,0.00,0.08")
    parser.add_argument("--energy-q-grid", default="-0.04,0.00,0.04")
    parser.add_argument(
        "--max-evals",
        type=int,
        default=0,
        help="Optional cap for smoke tests after case/action expansion.",
    )
    args = parser.parse_args()

    phase_keys = parse_phase_key_list(args.phase_keys or args.phase_key)
    family_label = args.family_label or default_family_label(args.topology, args.category, phase_keys)
    eval_depths = parse_float_list(args.eval_depths)
    eval_durations_ms = parse_int_list(args.eval_durations_ms)
    cases = make_cases(
        topology=args.topology,
        category=args.category,
        phase_keys=phase_keys,
        family_label=family_label,
        depths=eval_depths,
        durations_ms=eval_durations_ms,
    )
    actions = build_cartesian_actions(args)
    expanded = [(case, action) for case in cases for action in actions]
    if args.max_evals and args.max_evals > 0:
        expanded = expanded[: args.max_evals]

    workspace = expert_workspace(
        args.topology,
        args.category,
        representative_phase_key(phase_keys),
        create=True,
    )
    run_id = args.run_id or f"hpt_fixed_action_family_{family_label}_{time.strftime('%Y%m%d_%H%M%S')}"
    run_dir = workspace.data / "action_response" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    compare_dir = run_dir / "control_comparison"
    metadata = {
        "schema": "hpt-fixed-action-family-response-v1",
        "run_id": run_id,
        "command": [
            sys.executable,
            "-m",
            "sac.campaigns.run_hpt_fixed_action_family_sweep",
            *sys.argv[1:],
        ],
        "family_label": family_label,
        "topology": args.topology,
        "category": args.category,
        "phase_keys": phase_keys,
        "eval_depths": eval_depths,
        "eval_durations_ms": eval_durations_ms,
        "eval_cases": [{**asdict(case), "label": case.label} for case in cases],
        "candidate_actions": [
            {
                "action_id": action_token(action),
                "m_reg_d": action[0],
                "m_reg_q": action[1],
                "m_energy_d": action[2],
                "m_energy_q": action[3],
            }
            for action in actions
        ],
        "expanded_eval_count": len(expanded),
        "fault_start_s": args.fault_start_s,
        "fault_stop_margin_s": args.fault_stop_margin_s,
        "validator_schema": CURRENT_FRT_VALIDATOR_SCHEMA,
        "target_gate": "L1",
        "expert_id": workspace.spec.expert_id,
        "expert_workspace": str(workspace.root),
    }
    (run_dir / "campaign_metadata.json").write_text(
        json.dumps(metadata, indent=2),
        encoding="utf-8",
    )

    rows: list[dict] = []
    for case, action in expanded:
        action_id = action_token(action)
        csv_path = matlab_evaluate_fixed_action(
            case,
            action,
            action_id,
            run_dir,
            fault_start_s=args.fault_start_s,
            fault_stop_margin_s=args.fault_stop_margin_s,
            compare_dir=compare_dir,
        )
        rows.extend(read_fixed_rows(csv_path, case, action, action_id))

    rows_csv = run_dir / "fixed_action_family_rows.csv"
    write_csv(rows_csv, rows)
    summary = summarize_rows(rows, run_dir / "fixed_action_family_summary.json")
    final = {
        "metadata": metadata,
        "rows_csv": str(rows_csv),
        "summary": summary,
    }
    (run_dir / "campaign_summary.json").write_text(
        json.dumps(final, indent=2),
        encoding="utf-8",
    )
    write_markdown(run_dir, metadata, summary, rows)
    write_experiment_metadata(
        run_dir,
        experiment_name="hpt_fixed_action_family_response",
        config=metadata,
        extra=final,
    )
    print(json.dumps({"run_dir": str(run_dir), "summary": summary}, indent=2), flush=True)


if __name__ == "__main__":
    main()
