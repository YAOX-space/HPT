"""Run a v3 switch-level conventional-dq matrix for one HPT fault family.

This is the baseline-only companion to ``run_hpt_family_specialist_matrix``.
It produces fresh strong-dq evidence before proxy calibration or SAC training,
so the family has a real boundary target instead of relying on stale pre-v3
results.
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
from sac.expert_workspace import expert_workspace
from sac.gate_contract import (
    CURRENT_FRT_VALIDATOR_SCHEMA,
    summarize_gate_rows,
)


def matlab_evaluate_strong_dq(
    case,
    run_dir: Path,
    *,
    fault_start_s: float,
    fault_stop_margin_s: float,
    compare_dir: Path,
    conventional_profile: str,
    wait_for_csv: bool = True,
) -> Path:
    compare_dir.mkdir(parents=True, exist_ok=True)
    label = f"{case.label}_strong_dq"
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
                'hpt_compare_modes = ["conventional_dq"];',
                "hpt_compare_energy_enable = 1.0;",
                "hpt_compare_voltage_survival_current_gate = true;",
                f"hpt_compare_fault_start = {fault_start_s:.12g};",
                f"hpt_compare_fault_stop_margin = {fault_stop_margin_s:.12g};",
                f'hpt_compare_conventional_profile = "{conventional_profile}";',
                "hpt_compare_conventional_params = struct();",
                (
                    "hpt_compare_faults = "
                    f"{{'{case.case_name}', {case.fault_pu:.12g}, "
                    f"{case.duration_s:.12g}, {mat_vector(phase_pu_vector(case))}}};"
                ),
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
        if not wait_for_csv:
            return saved_path
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


def read_strong_dq_rows(csv_path: Path, case) -> list[dict]:
    deadline = time.time() + 300.0
    while time.time() <= deadline and not csv_path.exists():
        time.sleep(0.2)
    rows: list[dict] = []
    with csv_path.open("r", newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            if str(row.get("mode") or "") != "conventional_dq":
                continue
            out = dict(row)
            out["controller"] = "strong_dq"
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
    summary = {
        **gate_summary,
        "rows": len(rows),
        "voltage_survival_pass_count": gate_summary["l1_pass_count"],
        "envelope_pass_count": sum(truthy(row.get("envelope_pass")) for row in rows),
        "recovery_pass_count": sum(truthy(row.get("recovery_envelope_pass")) for row in rows),
        "vdc_pass_count": sum(
            as_float(row.get("vdc_min")) >= 650.0
            and as_float(row.get("vdc_max")) <= 1000.0
            for row in rows
        ),
        "grid_current_pass_count": sum(truthy(row.get("gbt_grid_current_limit_pass")) for row in rows),
        "score_mean": float(np.nanmean(scores)) if scores else float("nan"),
        "score_min": float(np.nanmin(scores)) if scores else float("nan"),
        "score_max": float(np.nanmax(scores)) if scores else float("nan"),
        "grid_current_peak_max_pu": float(np.nanmax(grid_i)) if grid_i else float("nan"),
        "envelope_violation_max_pu": float(np.nanmax(env)) if env else float("nan"),
    }
    out_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def write_markdown(run_dir: Path, metadata: dict, summary: dict, rows: Iterable[dict]) -> None:
    lines = [
        "# HPT conventional-dq family matrix summary",
        "",
        "This run evaluates the strong conventional dq baseline only.",
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
        "conventional_profile",
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
            f"- grid current peak max pu: `{summary.get('grid_current_peak_max_pu')}`",
            f"- envelope violation max pu: `{summary.get('envelope_violation_max_pu')}`",
            "",
            "## Per-case rows",
            "",
            "| case | phase | scenario valid | L1 pass | reason | score | grid I | Vdc min/max | load quality | recovery | source |",
            "|---|---|---:|---:|---|---:|---:|---:|---:|---:|---|",
        ]
    )
    for row in rows:
        lines.append(
            "| {case} | {phase} | {valid} | {l1} | {reason} | {score:.3f} | {grid:.3f} | "
            "{vmin:.1f}/{vmax:.1f} | {env:.5f} | {rec:.5f} | {src} |".format(
                case=row.get("family_eval_label", ""),
                phase=row.get("fault_phase_key", ""),
                valid=row.get("scenario_valid", ""),
                l1=row.get("l1_load_voltage_survival_pass", ""),
                reason=row.get("l1_reason", ""),
                score=as_float(row.get("control_score")),
                grid=as_float(row.get("grid_current_peak_pu")),
                vmin=as_float(row.get("vdc_min")),
                vmax=as_float(row.get("vdc_max")),
                env=as_float(row.get("envelope_violation_max_pu")),
                rec=as_float(row.get("recovery_violation_max_pu")),
                src=Path(str(row.get("source_csv", ""))).name,
            )
        )
    (run_dir / "CONVENTIONAL_FAMILY_SUMMARY.md").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


def summarize_existing_run(run_dir: Path) -> None:
    metadata_path = run_dir / "campaign_metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    eval_cases = list(metadata.get("eval_cases", []))
    case_by_label = {str(item["label"]): item for item in eval_cases}
    def expected_case_name(item: dict) -> str:
        prefix = "hvrt" if str(item.get("category") or metadata.get("category")).upper() == "HVRT" else "lvrt"
        fault = int(round(float(item["fault_pu"]) * 1000.0))
        duration_ms = int(round(float(item["duration_s"]) * 1000.0))
        return f"{prefix}_{fault:04d}_{duration_ms:03d}ms"
    case_by_case_name = {
        str(item.get("case_name") or expected_case_name(item)): item
        for item in eval_cases
    }
    rows: list[dict] = []
    for csv_path in sorted((run_dir / "control_comparison").glob("control_comparison_*.csv")):
        label_matches = [label for label in case_by_label if label in csv_path.name]
        item = case_by_label[label_matches[0]] if label_matches else None
        if item is None:
            with csv_path.open("r", newline="", encoding="utf-8-sig") as handle:
                csv_rows = list(csv.DictReader(handle))
            case_names = [str(row.get("case") or "") for row in csv_rows if str(row.get("case") or "")]
            for case_name in case_names:
                item = case_by_case_name.get(case_name)
                if item is not None:
                    break
            if item is None and len(eval_cases) == 1 and csv_rows:
                item = eval_cases[0]
        if item is None:
            continue
        case = type(
            "Case",
            (),
            {
                "label": item["label"],
                "fault_pu": float(item["fault_pu"]),
                "duration_ms": int(round(float(item["duration_s"]) * 1000.0)),
                "phase_key": str(item.get("phase_key") or ""),
            },
        )()
        rows.extend(read_strong_dq_rows(csv_path, case))
    comparison_csv = run_dir / "strong_dq_family_rows.csv"
    write_csv(comparison_csv, rows)
    summary = summarize_rows(rows, run_dir / "strong_dq_family_summary.json")
    final = {
        "metadata": metadata,
        "comparison_csv": str(comparison_csv),
        "summary": summary,
    }
    (run_dir / "campaign_summary.json").write_text(
        json.dumps(final, indent=2),
        encoding="utf-8",
    )
    write_markdown(run_dir, metadata, summary, rows)
    print(json.dumps({"run_dir": str(run_dir), "summary": summary}, indent=2), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--summarize-run-dir",
        type=Path,
        default=None,
        help="Summarize CSVs from a previous --collect-only run and exit.",
    )
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--topology", choices=["topology1", "topology2"], default="topology2")
    parser.add_argument("--category", choices=["LVRT", "HVRT"], default="LVRT")
    parser.add_argument("--phase-key", choices=["abc", "a", "b", "c", "ab", "bc", "ca"], default="abc")
    parser.add_argument("--phase-keys", default="")
    parser.add_argument("--family-label", default="")
    parser.add_argument("--eval-depths", default="0.875,0.90")
    parser.add_argument("--eval-durations-ms", default="60,100")
    parser.add_argument("--fault-start-s", type=float, default=0.080)
    parser.add_argument("--fault-stop-margin-s", type=float, default=0.125)
    parser.add_argument("--conventional-profile", default="tuned_v2_l1")
    parser.add_argument(
        "--collect-only",
        action="store_true",
        help="Run MATLAB cases and record expected CSV paths, but do not read CSVs in this process.",
    )
    args = parser.parse_args()
    if args.summarize_run_dir is not None:
        summarize_existing_run(args.summarize_run_dir)
        return

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
    workspace = expert_workspace(
        args.topology,
        args.category,
        representative_phase_key(phase_keys),
        create=True,
    )
    run_id = args.run_id or f"hpt_conventional_family_{family_label}_{time.strftime('%Y%m%d_%H%M%S')}"
    run_dir = workspace.results / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    compare_dir = run_dir / "control_comparison"
    metadata = {
        "schema": "hpt-conventional-family-matrix-v1",
        "run_id": run_id,
        "command": [
            sys.executable,
            "-m",
            "sac.campaigns.run_hpt_conventional_family_matrix",
            *sys.argv[1:],
        ],
        "family_label": family_label,
        "topology": args.topology,
        "category": args.category,
        "phase_keys": phase_keys,
        "eval_depths": eval_depths,
        "eval_durations_ms": eval_durations_ms,
        "eval_cases": [{**asdict(case), "label": case.label} for case in cases],
        "fault_start_s": args.fault_start_s,
        "fault_stop_margin_s": args.fault_stop_margin_s,
        "conventional_profile": args.conventional_profile,
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
    collected_paths: list[str] = []
    for case in cases:
        csv_path = matlab_evaluate_strong_dq(
            case,
            run_dir,
            fault_start_s=args.fault_start_s,
            fault_stop_margin_s=args.fault_stop_margin_s,
            compare_dir=compare_dir,
            conventional_profile=args.conventional_profile,
            wait_for_csv=not args.collect_only,
        )
        collected_paths.append(str(csv_path))
        if args.collect_only:
            continue
        rows.extend(read_strong_dq_rows(csv_path, case))
    if args.collect_only:
        (run_dir / "collected_csv_manifest.json").write_text(
            json.dumps({"csv_paths": collected_paths}, indent=2),
            encoding="utf-8",
        )
        print(json.dumps({"run_dir": str(run_dir), "csv_paths": collected_paths}, indent=2), flush=True)
        return
    comparison_csv = run_dir / "strong_dq_family_rows.csv"
    write_csv(comparison_csv, rows)
    summary = summarize_rows(rows, run_dir / "strong_dq_family_summary.json")
    final = {
        "metadata": metadata,
        "comparison_csv": str(comparison_csv),
        "summary": summary,
    }
    (run_dir / "campaign_summary.json").write_text(
        json.dumps(final, indent=2),
        encoding="utf-8",
    )
    write_markdown(run_dir, metadata, summary, rows)
    print(json.dumps({"run_dir": str(run_dir), "summary": summary}, indent=2), flush=True)


if __name__ == "__main__":
    main()
