"""Validate time-varying HPT action trajectories in switch-level Simulink.

This runner is the first dynamic-control gate after fixed-action validation.
It generates a trajectory MAT file, runs ``eval_hpt_v2_control_comparison``
with ``trajectory_action`` mode, and compares the waveform-level result against
both ``conventional_dq`` and a fixed action with the same target command.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from .datasets.build_hpt_action_trajectory import (
    TrajectorySpec,
    make_trajectory,
    write_csv,
    write_mat,
)
from .experiment_metadata import write_experiment_metadata
from .gate_contract import classify_result_row


ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "lab" / "results"
SIMULINK_DIR = ROOT / "simulink"
CONTROL_DIR = RESULTS / "hpt_v2_control_comparison"
SIMULINK_CONTROL_DIR = ROOT / "results" / "control_comparison"
CONTROL_DIRS = (CONTROL_DIR, SIMULINK_CONTROL_DIR)


STRONG_DQ_PROFILES: dict[str, list[tuple[str, float]]] = {
    "none": [],
    "t2_bal_lvrt090_currentgate": [
        ("hpt_vreg_kp", 5.6),
        ("hpt_vreg_ki", 0.35),
        ("hpt_m_reg_max", 0.60),
        ("hpt_sac_reg_max", 0.60),
        ("hpt_sac_reg_q_gain", -1.0),
        ("hpt_inj_phase_offset", -1.05),
        ("hpt_vdc_kp", 0.0),
        ("hpt_vdc_ki", 0.0),
        ("hpt_energy_i_kp", 0.25),
        ("hpt_energy_i_ki", 45.0),
        ("hpt_energy_vff_gain", 0.20),
        ("hpt_energy_control_sign", -1.0),
        ("hpt_energy_bridge_polarity", -1.0),
        ("hpt_conventional_energy_scale", 0.0),
        ("hpt_conventional_recovery_reg_gain", 2.4),
        ("hpt_conventional_recovery_reg_max", 0.44),
    ],
}

COMMON_ACTUATION_PROFILE_NAMES = {
    "hpt_m_reg_max",
    "hpt_sac_reg_max",
    "hpt_sac_reg_q_gain",
    "hpt_inj_phase_offset",
    "hpt_energy_i_kp",
    "hpt_energy_i_ki",
    "hpt_energy_vff_gain",
    "hpt_energy_control_sign",
    "hpt_energy_bridge_polarity",
}


def matlab_string(text: str) -> str:
    return "'" + str(text).replace("'", "''") + "'"


def matlab_vector(values: list[float] | None) -> str:
    if not values:
        return ""
    return "[" + " ".join(f"{float(x):.12g}" for x in values) + "]"


def matlab_fault_cell(
    case_name: str,
    fault_pu: float,
    duration_s: float,
    phase_pu: list[float] | None,
) -> str:
    if phase_pu:
        return (
            "{ "
            f"{matlab_string(case_name)}, {fault_pu:.12g}, {duration_s:.12g}, "
            f"{matlab_vector(phase_pu)} }}"
        )
    return "{ " f"{matlab_string(case_name)}, {fault_pu:.12g}, {duration_s:.12g} }}"


def phase_recovery_end(args: argparse.Namespace) -> float:
    return float(args.fault_start) + float(args.duration_s) + float(args.fault_stop_margin)


def hpt_model_param_struct(args: argparse.Namespace) -> str:
    base_rchop = (800.0**2) / 120e3
    items = [
        ("hpt_chopper_threshold", float(args.chopper_threshold)),
        ("hpt_rchop", base_rchop * float(args.rchop_scale)),
    ]
    items.extend(
        (name, value)
        for name, value in STRONG_DQ_PROFILES.get(str(args.strong_dq_profile), [])
        if name in COMMON_ACTUATION_PROFILE_NAMES
    )
    if getattr(args, "phase_override", False):
        fault_clear = float(args.fault_start) + float(args.duration_s)
        items.extend(
            [
                ("hpt_sac_phase_override_enable", 1.0),
                ("hpt_sac_phase_fault_start_s", float(args.fault_start)),
                ("hpt_sac_phase_fault_clear_s", fault_clear),
                ("hpt_sac_phase_recovery_end_s", phase_recovery_end(args)),
            ]
        )
    body = ",".join(f"'{name}',{value:.12g}" for name, value in items)
    return f"struct({body})"


def hpt_conventional_param_struct(args: argparse.Namespace) -> str:
    items = [
        (name, value)
        for name, value in STRONG_DQ_PROFILES.get(str(args.strong_dq_profile), [])
        if name not in COMMON_ACTUATION_PROFILE_NAMES
    ]
    if not items:
        return "struct()"
    body = ",".join(f"'{name}',{value:.12g}" for name, value in items)
    return f"struct({body})"


def safe_token(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]+", "_", str(text)).strip("_")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as f:
        return [dict(row) for row in csv.DictReader(f)]


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


def truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "1.0", "true", "yes"}


def make_case_name(duration_s: float, fault_pu: float) -> str:
    prefix = "hvrt" if fault_pu > 1.0 else "lvrt"
    return f"{prefix}_{int(round(duration_s * 1000)):03d}ms_{fault_pu:.3f}pu".replace(".", "p")


def to_float(value: Any, default: float = float("nan")) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def control_csvs() -> set[Path]:
    files: set[Path] = set()
    for directory in CONTROL_DIRS:
        files.update(directory.glob("control_comparison_*.csv"))
    return files


def latest_control_csv(before: set[Path]) -> Path:
    after = control_csvs()
    existing_new = [p for p in after - before if p.exists()]
    new_files = sorted(existing_new, key=lambda p: p.stat().st_mtime)
    if new_files:
        return new_files[-1]
    all_files = sorted((p for p in after if p.exists()), key=lambda p: p.stat().st_mtime)
    if not all_files:
        searched = ", ".join(str(p) for p in CONTROL_DIRS)
        raise FileNotFoundError(f"No control comparison CSVs under {searched}")
    return all_files[-1]


def new_control_csv(before: set[Path]) -> Path | None:
    after = control_csvs()
    new_files = sorted((p for p in after - before if p.exists()), key=lambda p: p.stat().st_mtime)
    if not new_files:
        return None
    return new_files[-1]


def result_by_mode(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    return {row.get("mode", ""): row for row in rows}


def score_improved(policy: dict[str, str], baseline: dict[str, str]) -> bool:
    ps = to_float(policy.get("control_score"))
    bs = to_float(baseline.get("control_score"))
    return math.isfinite(ps) and math.isfinite(bs) and ps < bs


def summarize_modes(rows: list[dict[str, str]]) -> dict[str, Any]:
    by_mode = result_by_mode(rows)
    baseline = by_mode.get("conventional_dq", {})
    fixed = by_mode.get("fixed_action", {})
    traj = by_mode.get("trajectory_action", {})
    fixed_status = classify_result_row(fixed, "L1")
    traj_status = classify_result_row(traj, "L1")
    baseline_status = classify_result_row(baseline, "L1")
    fixed_pass = fixed_status.eligible and fixed_status.passed
    traj_pass = traj_status.eligible and traj_status.passed
    baseline_pass = baseline_status.eligible and baseline_status.passed
    summary = {
        "target_gate": "L1",
        "baseline_scenario_eligible": baseline_status.eligible,
        "fixed_scenario_eligible": fixed_status.eligible,
        "trajectory_scenario_eligible": traj_status.eligible,
        "baseline_voltage_pass": baseline_pass,
        "fixed_voltage_pass": fixed_pass,
        "trajectory_voltage_pass": traj_pass,
        "fixed_beats_baseline": bool(
            (fixed_pass and not baseline_pass)
            or (fixed_pass and baseline_pass and score_improved(fixed, baseline))
        ),
        "trajectory_beats_baseline": bool(
            (traj_pass and not baseline_pass)
            or (traj_pass and baseline_pass and score_improved(traj, baseline))
        ),
        "trajectory_score": to_float(traj.get("control_score")),
        "fixed_score": to_float(fixed.get("control_score")),
        "baseline_score": to_float(baseline.get("control_score")),
        "trajectory_lv_mean": to_float(traj.get("lv_mean")),
        "trajectory_lv_recovery_mean": to_float(traj.get("lv_recovery_mean")),
        "trajectory_vdc_min": to_float(traj.get("vdc_min")),
        "trajectory_vdc_max": to_float(traj.get("vdc_max")),
        "trajectory_envelope_violation_max_pu": to_float(traj.get("envelope_violation_max_pu")),
        "trajectory_envelope_violation_duration_s": to_float(traj.get("envelope_violation_duration_s")),
        "trajectory_recovery_violation_max_pu": to_float(traj.get("recovery_violation_max_pu")),
        "trajectory_recovery_violation_duration_s": to_float(traj.get("recovery_violation_duration_s")),
        "trajectory_timestep_envelope_pass": truthy(traj.get("timestep_envelope_pass", "")),
        "fixed_envelope_violation_max_pu": to_float(fixed.get("envelope_violation_max_pu")),
        "fixed_recovery_violation_max_pu": to_float(fixed.get("recovery_violation_max_pu")),
        "baseline_envelope_violation_max_pu": to_float(baseline.get("envelope_violation_max_pu")),
        "baseline_recovery_violation_max_pu": to_float(baseline.get("recovery_violation_max_pu")),
        "trajectory_reason": traj.get("l1_reason", traj_status.reason),
    }
    if fixed and traj:
        summary["constant_equivalence_score_gap"] = abs(
            to_float(traj.get("control_score")) - to_float(fixed.get("control_score"))
        )
        summary["constant_equivalence_lv_gap"] = abs(
            to_float(traj.get("lv_recovery_mean")) - to_float(fixed.get("lv_recovery_mean"))
        )
        summary["constant_equivalence_vdc_min_gap"] = abs(
            to_float(traj.get("vdc_min")) - to_float(fixed.get("vdc_min"))
        )
    return summary


def write_report(run_dir: Path, summary: dict[str, Any], rows: list[dict[str, str]]) -> None:
    lines = [
        "# HPT Trajectory Switch-Level Validation",
        "",
        "## Summary",
        "",
    ]
    for key, value in summary.items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(
        [
            "",
            "## Modes",
            "",
            "| Mode | Scenario valid | L1 pass | L2 pass | L3 pass | Score | LV mean | LV recovery | Vdc min/max | Load/Recy viol | Reason |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for row in rows:
        lines.append(
            f"| `{row.get('mode','')}` | {row.get('scenario_valid','')} | "
            f"{row.get('l1_load_voltage_survival_pass','')} | "
            f"{row.get('l2_grid_code_ride_through_pass','')} | "
            f"{row.get('l3_full_frt_pass','')} | {row.get('control_score','')} | "
            f"{row.get('lv_mean','')} | {row.get('lv_recovery_mean','')} | "
            f"{row.get('vdc_min','')}/{row.get('vdc_max','')} | "
            f"{row.get('envelope_violation_max_pu','')}/{row.get('recovery_violation_max_pu','')} | "
            f"`{row.get('l1_reason', row.get('l3_reason',''))}` |"
        )
    (run_dir / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def run_matlab_case(args: argparse.Namespace, run_dir: Path, trajectory_file: Path) -> tuple[Path, str, str, int]:
    modes = "{'conventional_dq','fixed_action','trajectory_action'}"
    action = [float(x) for x in args.action]
    case_name = args.case_name or make_case_name(args.duration_s, args.fault_pu)
    label = safe_token(f"traj_{args.topology}_{args.preset}_{case_name}")
    base_rchop = (800.0**2) / 120e3
    statement = "; ".join(
        [
            f"cd({matlab_string(str(SIMULINK_DIR).replace(chr(92), '/'))})",
            f"hpt_compare_topology={matlab_string(args.topology)}",
            "hpt_compare_scenario_type='fault'",
            f"hpt_compare_modes=string({modes})",
            f"hpt_compare_faults={matlab_fault_cell(case_name, args.fault_pu, args.duration_s, args.fault_phase_pu)}",
            f"hpt_compare_model_params={hpt_model_param_struct(args)}",
            "hpt_compare_conventional_profile='model_default'",
            f"hpt_compare_conventional_params={hpt_conventional_param_struct(args)}",
            f"hpt_compare_fault_start={args.fault_start:.12g}",
            f"hpt_compare_fault_stop_margin={args.fault_stop_margin:.12g}",
            f"hpt_compare_fault_settle_s={args.fault_settle_s:.12g}",
            f"hpt_compare_voltage_survival_current_gate={str(bool(args.voltage_survival_current_gate)).lower()}",
            f"hpt_compare_run_label={matlab_string(label)}",
            "hpt_compare_fixed_action=[" + " ".join(f"{x:.12g}" for x in action) + "]",
            f"hpt_compare_trajectory_file={matlab_string(str(trajectory_file).replace(chr(92), '/'))}",
            "run(fullfile(pwd,'evaluators','eval_hpt_v2_control_comparison.m'))",
        ]
    )
    before = control_csvs()
    proc = subprocess.run(
        [args.matlab_cmd, "-batch", statement],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        timeout=args.timeout_s,
    )
    log_text = "STDOUT:\n" + proc.stdout + "\n\nSTDERR:\n" + proc.stderr
    log_path = run_dir / "matlab.log"
    log_path.write_text(log_text, encoding="utf-8")
    if proc.returncode != 0:
        csv_path = new_control_csv(before)
        if csv_path is not None:
            return csv_path, proc.stdout, proc.stderr, proc.returncode
        return Path(), proc.stdout, proc.stderr, proc.returncode
    return latest_control_csv(before), proc.stdout, proc.stderr, proc.returncode


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--topology", default="topology2", choices=["topology1", "topology2"])
    parser.add_argument(
        "--preset",
        default="constant",
        choices=[
            "zero",
            "constant",
            "step",
            "ramp",
            "two_stage",
            "two_stage_window",
            "fault_window",
            "fault_recovery",
        ],
    )
    parser.add_argument("--fault-pu", type=float, default=0.95)
    parser.add_argument("--fault-phase-pu", type=float, nargs=3, default=None)
    parser.add_argument("--duration-s", type=float, default=0.08)
    parser.add_argument("--fault-start", type=float, default=0.035)
    parser.add_argument("--fault-stop-margin", type=float, default=0.125)
    parser.add_argument("--fault-settle-s", type=float, default=0.0)
    parser.add_argument(
        "--phase-override",
        action="store_true",
        help=(
            "Opt-in diagnostic observation contract: replace measured "
            "fault/recovery phase features with scheduled phase features "
            "derived from fault-start, duration, and fault-stop-margin."
        ),
    )
    parser.add_argument("--decision-dt", type=float, default=2e-3)
    parser.add_argument(
        "--trajectory-file",
        type=Path,
        default=None,
        help="Use an existing hpt_traj_t/hpt_traj_action MAT file instead of generating a preset trajectory.",
    )
    parser.add_argument("--action", type=float, nargs=4, default=[0.172, 0.0, 0.022, 0.002])
    parser.add_argument("--start-action", type=float, nargs=4, default=[0.0, 0.0, 0.0, 0.0])
    parser.add_argument("--base-action", type=float, nargs=4, default=[0.0, 0.0, 0.0, 0.0])
    parser.add_argument("--step-time", type=float, default=0.035)
    parser.add_argument("--ramp-start", type=float, default=0.035)
    parser.add_argument("--ramp-end", type=float, default=0.055)
    parser.add_argument("--down-start", type=float, default=None)
    parser.add_argument("--down-end", type=float, default=None)
    parser.add_argument("--case-name", default="")
    parser.add_argument("--chopper-threshold", type=float, default=850.0)
    parser.add_argument("--rchop-scale", type=float, default=1.0)
    parser.add_argument(
        "--strong-dq-profile",
        choices=sorted(STRONG_DQ_PROFILES),
        default="none",
        help="Optional named conventional-DQ parameter set to inject into validation.",
    )
    parser.add_argument(
        "--voltage-survival-current-gate",
        action="store_true",
        help="Require grid-current limit pass in the staged voltage-survival gate.",
    )
    parser.add_argument("--matlab-cmd", default="matlab")
    parser.add_argument("--timeout-s", type=int, default=900)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_id = args.run_id or f"hpt_traj_switch_{time.strftime('%Y%m%d_%H%M%S')}"
    run_dir = RESULTS / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    trajectory_file = run_dir / "hpt_sac_trajectory.mat"
    source_trajectory_file = ""
    if args.trajectory_file is not None:
        source = args.trajectory_file.resolve()
        if not source.exists():
            raise FileNotFoundError(f"Trajectory file does not exist: {source}")
        source_trajectory_file = str(source)
        if source != trajectory_file.resolve():
            shutil.copy2(source, trajectory_file)
        for suffix in (".csv", ".json"):
            sidecar = source.with_suffix(suffix)
            if sidecar.exists():
                shutil.copy2(sidecar, run_dir / f"hpt_sac_trajectory{suffix}")
    else:
        stop_time = args.fault_start + args.duration_s + args.fault_stop_margin
        spec = TrajectorySpec(
            preset=args.preset,
            dt=args.decision_dt,
            stop_time=stop_time,
            base_action=tuple(args.base_action),
            start_action=tuple(args.start_action),
            action=tuple(args.action),
            step_time=args.step_time,
            ramp_start=args.ramp_start,
            ramp_end=args.ramp_end,
            down_start=args.down_start,
            down_end=args.down_end,
        )
        t, action = make_trajectory(spec)
        write_mat(trajectory_file, t, action)
        write_csv(run_dir / "hpt_sac_trajectory.csv", t, action)

    csv_path, stdout, stderr, returncode = run_matlab_case(args, run_dir, trajectory_file)
    if returncode != 0 and not csv_path.exists():
        summary = {
            "schema": "hpt-trajectory-switch-validation-v1",
            "run_id": run_id,
            "matlab_returncode": returncode,
            "trajectory_file": str(trajectory_file),
            "error": "matlab_failed",
        }
        (run_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(json.dumps(summary, indent=2), flush=True)
        return returncode

    rows = read_csv(csv_path)
    write_csv_rows(run_dir / "control_comparison_rows.csv", rows)
    summary = summarize_modes(rows)
    summary.update(
        {
            "schema": "hpt-trajectory-switch-validation-v1",
            "run_id": run_id,
            "control_csv": str(csv_path),
            "trajectory_file": str(trajectory_file),
            "source_trajectory_file": source_trajectory_file,
            "matlab_returncode": returncode,
            "matlab_nonzero_accepted": bool(returncode != 0),
            "topology": args.topology,
            "preset": args.preset,
            "fault_pu": args.fault_pu,
            "duration_s": args.duration_s,
            "fault_settle_s": args.fault_settle_s,
            "chopper_threshold": args.chopper_threshold,
            "rchop_scale": args.rchop_scale,
            "decision_dt": args.decision_dt,
            "target_action": [float(x) for x in args.action],
        }
    )
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    write_report(run_dir, summary, rows)
    write_experiment_metadata(
        run_dir,
        experiment_name="hpt_trajectory_switch_validation",
        config=summary,
        dataset_manifest=trajectory_file,
        extra={"stdout_tail": stdout[-2000:], "stderr_tail": stderr[-2000:]},
    )
    print(json.dumps(summary, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
