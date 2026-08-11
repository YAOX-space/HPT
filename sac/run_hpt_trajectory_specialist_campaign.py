"""Run a trajectory-level HPT direct-SAC specialist campaign.

This script automates the workflow that was first proven manually on
``topology2 / LVRT / 0.95 pu / 80 ms``:

1. Validate a trajectory action schedule in the switch-level model.
2. Collect 2-ms switch-level observation/action traces for that trajectory.
3. Behavior-clone a 24-D/4-D actor from those traces.
4. Optionally run DAgger iterations: collect actor-visited states, relabel
   them with a safe target action and Vdc feedback, and retrain.
5. Export the final actor and evaluate it against ``conventional_dq`` in
   ``sac_actor_always_raw`` mode.

The campaign is intentionally scenario-specialist.  It does not claim full FRT
certification; promotion is based on the staged voltage-survival gate and
score improvement over the conventional baseline.
"""
from __future__ import annotations

import argparse
import atexit
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


ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "lab" / "results"
MODELS = ROOT / "data" / "models"
SIMULINK_DIR = ROOT / "simulink"
CONTROL_DIR = RESULTS / "hpt_v2_control_comparison"
TRACE_DIR = RESULTS / "hpt_v2_trajectory_traces"


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


def safe_token(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]+", "_", str(text)).strip("_")


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


def hpt_model_param_struct(
    args: argparse.Namespace,
    *,
    include_control_profile: bool = False,
) -> str:
    base_rchop = (800.0**2) / 120e3
    items = [
        ("hpt_chopper_threshold", float(args.chopper_threshold)),
        ("hpt_rchop", base_rchop * float(args.rchop_scale)),
    ]
    profile_items = STRONG_DQ_PROFILES.get(str(args.strong_dq_profile), [])
    if include_control_profile:
        items.extend(profile_items)
    else:
        items.extend(
            (name, value)
            for name, value in profile_items
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


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as f:
        return [dict(row) for row in csv.DictReader(f)]


def truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "1.0", "true", "yes"}


def to_float(value: Any, default: float = float("nan")) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def latest_new_file(directory: Path, pattern: str, before: set[Path]) -> Path:
    after = set(directory.glob(pattern))
    new_files = sorted(after - before, key=lambda p: p.stat().st_mtime)
    if new_files:
        return new_files[-1]
    files = sorted(after, key=lambda p: p.stat().st_mtime)
    if not files:
        raise FileNotFoundError(f"No files match {directory / pattern}")
    return files[-1]


def new_file_or_none(directory: Path, pattern: str, before: set[Path]) -> Path | None:
    after = set(directory.glob(pattern))
    new_files = sorted(after - before, key=lambda p: p.stat().st_mtime)
    if not new_files:
        return None
    return new_files[-1]


def run_command(
    cmd: list[str],
    *,
    run_dir: Path,
    log_name: str,
    timeout_s: int,
    allow_nonzero: bool = False,
) -> subprocess.CompletedProcess[str]:
    run_dir.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        cmd,
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        timeout=timeout_s,
    )
    (run_dir / log_name).write_text(
        "COMMAND:\n"
        + " ".join(cmd)
        + "\n\nSTDOUT:\n"
        + proc.stdout
        + "\n\nSTDERR:\n"
        + proc.stderr,
        encoding="utf-8",
    )
    if proc.returncode != 0 and not allow_nonzero:
        raise RuntimeError(f"Command failed ({proc.returncode}): {' '.join(cmd)}")
    return proc


def run_matlab_command_with_expected_file(
    cmd: list[str],
    *,
    run_dir: Path,
    log_name: str,
    timeout_s: int,
    expected_dir: Path,
    expected_pattern: str,
    before: set[Path],
) -> tuple[subprocess.CompletedProcess[str], Path]:
    """Run MATLAB and tolerate an exit crash only if a new output file exists."""

    proc = run_command(
        cmd,
        run_dir=run_dir,
        log_name=log_name,
        timeout_s=timeout_s,
        allow_nonzero=True,
    )
    out_path = new_file_or_none(expected_dir, expected_pattern, before)
    if proc.returncode != 0 and out_path is None:
        raise RuntimeError(f"Command failed ({proc.returncode}): {' '.join(cmd)}")
    if out_path is None:
        out_path = latest_new_file(expected_dir, expected_pattern, before)
    return proc, out_path


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def register_dynamic_actor_restore(actor_mat: Path, run_dir: Path) -> str:
    """Backup and restore the transient Simulink dynamic actor file.

    The campaign evaluates candidate actors by exporting them to the shared
    ``hpt_sac_actor_weights_dynamic.mat`` entry point.  Keep a per-run backup so
    interrupted experiments do not silently change the default Simulink actor.
    """

    if not actor_mat.exists():
        return ""
    backup = run_dir / f"{actor_mat.stem}_backup_before_campaign{actor_mat.suffix}"
    shutil.copy2(actor_mat, backup)

    def _restore() -> None:
        try:
            if backup.exists():
                shutil.copy2(backup, actor_mat)
        except Exception:
            # Avoid masking the original training/evaluation failure.
            pass

    atexit.register(_restore)
    return str(backup)


def jsonable_config(args: argparse.Namespace) -> dict[str, Any]:
    config: dict[str, Any] = {}
    for key, value in vars(args).items():
        if isinstance(value, Path):
            config[key] = str(value)
        else:
            config[key] = value
    return config


def trace_alignment_summary(reference_csv: Path, actor_csv: Path) -> dict[str, Any]:
    reference = read_csv(reference_csv)
    actor = read_csv(actor_csv)
    n = min(len(reference), len(actor))
    if n == 0:
        return {
            "schema": "hpt-trace-alignment-v1",
            "reference_csv": str(reference_csv),
            "actor_csv": str(actor_csv),
            "samples": 0,
            "error": "empty_trace",
        }

    def values(rows: list[dict[str, str]], key: str) -> list[float]:
        return [to_float(row.get(key), 0.0) for row in rows[:n]]

    out: dict[str, Any] = {
        "schema": "hpt-trace-alignment-v1",
        "reference_csv": str(reference_csv),
        "actor_csv": str(actor_csv),
        "samples": n,
    }
    for idx, name in enumerate(("m_reg_d", "m_reg_q", "m_energy_d", "m_energy_q"), 1):
        key = f"action_{idx:02d}"
        ref = values(reference, key)
        act = values(actor, key)
        diff = [a - r for a, r in zip(act, ref)]
        out[f"{name}_mae"] = sum(abs(x) for x in diff) / n
        out[f"{name}_max_abs_error"] = max(abs(x) for x in diff)
        out[f"{name}_ref_mean"] = sum(ref) / n
        out[f"{name}_actor_mean"] = sum(act) / n
    for key, name in (("lv_rms_inst", "lv_rms"), ("vdc_inst", "vdc")):
        ref = values(reference, key)
        act = values(actor, key)
        diff = [a - r for a, r in zip(act, ref)]
        out[f"{name}_mae"] = sum(abs(x) for x in diff) / n
        out[f"{name}_max_abs_error"] = max(abs(x) for x in diff)
        out[f"{name}_ref_mean"] = sum(ref) / n
        out[f"{name}_actor_mean"] = sum(act) / n
    return out


def summarize_control_csv(path: Path, policy_mode: str) -> dict[str, Any]:
    rows = read_csv(path)
    by_mode = {row.get("mode", ""): row for row in rows}
    baseline = by_mode.get("conventional_dq", {})
    policy = by_mode.get(policy_mode, {})
    baseline_pass = truthy(baseline.get("voltage_survival_pass", ""))
    policy_pass = truthy(policy.get("voltage_survival_pass", ""))
    baseline_score = to_float(baseline.get("control_score"))
    policy_score = to_float(policy.get("control_score"))
    return {
        "control_csv": str(path),
        "baseline_voltage_pass": baseline_pass,
        "policy_voltage_pass": policy_pass,
        "baseline_score": baseline_score,
        "policy_score": policy_score,
        "policy_beats_baseline": bool(
            (policy_pass and not baseline_pass)
            or (
                policy_pass
                and baseline_pass
                and math.isfinite(policy_score)
                and math.isfinite(baseline_score)
                and policy_score < baseline_score
            )
        ),
        "policy_full_frt_pass": truthy(policy.get("full_frt_pass", "")),
        "policy_voltage_reason": policy.get("voltage_survival_reason", ""),
        "policy_full_frt_reason": policy.get("full_frt_reason", ""),
        "policy_lv_mean": to_float(policy.get("lv_mean")),
        "policy_lv_recovery_mean": to_float(policy.get("lv_recovery_mean")),
        "policy_fault_lv_min": to_float(policy.get("fault_lv_min")),
        "policy_fault_lv_max": to_float(policy.get("fault_lv_max")),
        "policy_fault_lv_band_violation_max_pu": to_float(
            policy.get("fault_lv_band_violation_max_pu")
        ),
        "policy_envelope_violation_max_pu": to_float(policy.get("envelope_violation_max_pu")),
        "policy_recovery_violation_max_pu": to_float(policy.get("recovery_violation_max_pu")),
        "policy_vdc_min": to_float(policy.get("vdc_min")),
        "policy_vdc_max": to_float(policy.get("vdc_max")),
        "policy_action_max_abs": to_float(policy.get("action_max_abs")),
        "policy_cmd_action_max_abs": to_float(policy.get("cmd_action_max_abs")),
        "policy_cmd_m_reg_d_mean": to_float(policy.get("cmd_m_reg_d_mean")),
        "policy_cmd_m_energy_d_mean": to_float(policy.get("cmd_m_energy_d_mean")),
    }


def make_case_name(duration_s: float, fault_pu: float) -> str:
    prefix = "hvrt" if fault_pu > 1.0 else "lvrt"
    return f"{prefix}_{int(round(duration_s * 1000)):03d}ms_{fault_pu:.3f}pu".replace(".", "p")


def build_initial_trajectory(args: argparse.Namespace, run_dir: Path) -> Path:
    if args.trajectory_file is not None:
        source = args.trajectory_file.resolve()
        if not source.exists():
            raise FileNotFoundError(f"Trajectory file does not exist: {source}")
        path = run_dir / "initial_trajectory.mat"
        if source != path.resolve():
            shutil.copy2(source, path)
        copied_sidecars: list[str] = []
        for suffix in (".csv", ".json"):
            sidecar = source.with_suffix(suffix)
            if sidecar.exists():
                sidecar_out = run_dir / f"initial_trajectory{suffix}"
                shutil.copy2(sidecar, sidecar_out)
                copied_sidecars.append(str(sidecar_out))
        write_json(
            run_dir / "initial_trajectory_source.json",
            {
                "schema": "hpt-trajectory-specialist-source-trajectory-v1",
                "source_trajectory_file": str(source),
                "path": str(path),
                "copied_sidecars": copied_sidecars,
            },
        )
        return path

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
    path = run_dir / "initial_trajectory.mat"
    write_mat(path, t, action)
    write_csv(run_dir / "initial_trajectory.csv", t, action)
    write_json(
        run_dir / "initial_trajectory.json",
        {
            "schema": "hpt-trajectory-specialist-initial-trajectory-v1",
            "spec": spec.__dict__,
            "n_points": int(t.shape[0]),
            "path": str(path),
        },
    )
    return path


def validate_trajectory(args: argparse.Namespace, run_dir: Path) -> dict[str, Any]:
    cmd = [
        "py",
        "-3",
        "-m",
        "sac.validate_hpt_trajectory_switchlevel",
        "--run-id",
        f"{args.run_id}_trajectory_validation",
        "--topology",
        args.topology,
        "--preset",
        args.preset,
        "--fault-pu",
        str(args.fault_pu),
        "--duration-s",
        str(args.duration_s),
        "--fault-start",
        str(args.fault_start),
        "--fault-stop-margin",
        str(args.fault_stop_margin),
        "--fault-settle-s",
        str(args.fault_settle_s),
        *(
            ["--voltage-survival-current-gate"]
            if args.voltage_survival_current_gate
            else []
        ),
        "--strong-dq-profile",
        args.strong_dq_profile,
        "--chopper-threshold",
        str(args.chopper_threshold),
        "--rchop-scale",
        str(args.rchop_scale),
        "--decision-dt",
        str(args.decision_dt),
        "--step-time",
        str(args.step_time),
        "--ramp-start",
        str(args.ramp_start),
        "--ramp-end",
        str(args.ramp_end),
        "--action",
        *[str(x) for x in args.action],
        "--start-action",
        *[str(x) for x in args.start_action],
        "--base-action",
        *[str(x) for x in args.base_action],
        "--timeout-s",
        str(args.matlab_timeout_s),
    ]
    if args.fault_phase_pu is not None:
        cmd += ["--fault-phase-pu", *[str(x) for x in args.fault_phase_pu]]
    if args.trajectory_file is not None:
        cmd += ["--trajectory-file", str(args.trajectory_file)]
    if args.phase_override:
        cmd += ["--phase-override"]
    if args.down_start is not None:
        cmd += ["--down-start", str(args.down_start)]
    if args.down_end is not None:
        cmd += ["--down-end", str(args.down_end)]
    summary_path = RESULTS / f"{args.run_id}_trajectory_validation" / "summary.json"
    data: dict[str, Any] = {}
    for attempt in range(2):
        log_name = "trajectory_validation.log" if attempt == 0 else f"trajectory_validation_retry{attempt}.log"
        run_command(
            cmd,
            run_dir=run_dir,
            log_name=log_name,
            timeout_s=args.matlab_timeout_s + 60,
            allow_nonzero=True,
        )
        data = json.loads(summary_path.read_text(encoding="utf-8"))
        if not data.get("error"):
            break
        if attempt == 0:
            time.sleep(2.0)
    if data.get("error"):
        raise RuntimeError(
            f"Trajectory validation failed after retry: {data.get('error')} "
            f"for {summary_path}"
        )
    write_json(run_dir / "trajectory_validation_summary.json", data)
    return data


def collect_trace(
    args: argparse.Namespace,
    run_dir: Path,
    *,
    label: str,
    policy_mode: float,
    actor_select_mode: float,
    trajectory_file: Path | None,
) -> Path:
    before = set(TRACE_DIR.glob("trajectory_trace_*.csv"))
    statements = [
        f"cd({matlab_string(str(SIMULINK_DIR).replace(chr(92), '/'))})",
        f"hpt_trace_topology={matlab_string(args.topology)}",
        f"hpt_trace_fault_pu={args.fault_pu:.12g}",
        (
            f"hpt_trace_fault_phase_pu={matlab_vector(args.fault_phase_pu)}"
            if args.fault_phase_pu is not None
            else ""
        ),
        f"hpt_trace_fault_duration={args.duration_s:.12g}",
        f"hpt_trace_fault_start={args.fault_start:.12g}",
        f"hpt_trace_fault_stop_margin={args.fault_stop_margin:.12g}",
        f"hpt_trace_fault_settle_s={args.fault_settle_s:.12g}",
        f"hpt_trace_model_params={hpt_model_param_struct(args, include_control_profile=(policy_mode == 0.0))}",
        f"hpt_trace_run_label={matlab_string(label)}",
        f"hpt_trace_policy_mode={policy_mode:.12g}",
        f"hpt_trace_actor_select_mode={actor_select_mode:.12g}",
        f"hpt_trace_actor_filter_tau={args.actor_filter_tau:.12g}",
    ]
    if trajectory_file is not None:
        statements.append(
            f"hpt_trace_trajectory_file={matlab_string(str(trajectory_file).replace(chr(92), '/'))}"
        )
    statements.append("run(fullfile(pwd,'collectors','collect_hpt_v2_trajectory_trace.m'))")
    statements = [stmt for stmt in statements if stmt]
    proc = run_command(
        [args.matlab_cmd, "-batch", "; ".join(statements)],
        run_dir=run_dir,
        log_name=f"collect_trace_{safe_token(label)}.log",
        timeout_s=args.matlab_timeout_s,
        allow_nonzero=True,
    )
    path = new_file_or_none(TRACE_DIR, "trajectory_trace_*.csv", before)
    if proc.returncode != 0 and path is None:
        raise RuntimeError(
            f"Trace collection failed ({proc.returncode}) and produced no new CSV"
        )
    if path is None:
        path = latest_new_file(TRACE_DIR, "trajectory_trace_*.csv", before)
    if proc.returncode != 0:
        warning_path = run_dir / f"collect_trace_{safe_token(label)}_nonzero_return.warning.txt"
        warning_path.write_text(
            f"MATLAB returned {proc.returncode}, but trace collection produced {path}.\n",
            encoding="utf-8",
        )
    (run_dir / f"trace_{safe_token(label)}.txt").write_text(str(path), encoding="utf-8")
    return path


def train_bc(
    args: argparse.Namespace,
    run_dir: Path,
    *,
    trace_csv: Path,
    run_id: str,
    model_out: Path,
    init_model: Path | None,
    fixed_target: list[float] | None,
    vdc_feedback_gain: float,
    relabel_with_trajectory: bool,
) -> dict[str, Any]:
    cmd = [
        "py",
        "-3",
        "-m",
        "sac.pretrain_hpt_actor_bc",
        "--run-id",
        run_id,
        "--episodes-per-scenario",
        "0",
        "--switch-trace-csv",
        str(trace_csv),
        "--switch-trace-repeat",
        str(args.switch_trace_repeat),
        "--switch-trace-scenario-types",
        "fault",
        "--switch-trace-topologies",
        args.topology,
        "--switch-trace-case-contains",
        args.case_contains,
        "--switch-trace-window-zones",
        args.window_zones,
        "--epochs",
        str(args.epochs),
        "--batch-size",
        str(args.batch_size),
        "--lr",
        str(args.lr),
        "--action-weights",
        args.action_weights,
        "--teacher-prior-weight",
        str(args.teacher_prior_weight),
        "--model-out",
        str(model_out),
    ]
    if init_model is not None:
        cmd += ["--init-model", str(init_model)]
    if fixed_target is not None:
        cmd += ["--switch-trace-fixed-target", ",".join(str(x) for x in fixed_target)]
    if vdc_feedback_gain != 0.0:
        cmd += [
            "--switch-trace-energy-vdc-feedback-gain",
            str(vdc_feedback_gain),
            "--switch-trace-energy-vdc-ref-pu",
            str(args.vdc_feedback_ref_pu),
        ]
    if args.energy_two_zone:
        cmd += [
            "--switch-trace-energy-two-zone",
            "--switch-trace-energy-vdc-low-pu",
            str(args.energy_vdc_low_pu),
            "--switch-trace-energy-vdc-high-pu",
            str(args.energy_vdc_high_pu),
            "--switch-trace-energy-low-d-gain",
            str(args.energy_low_d_gain),
            "--switch-trace-energy-low-q-gain",
            str(args.energy_low_q_gain),
            "--switch-trace-energy-high-d-gain",
            str(args.energy_high_d_gain),
            "--switch-trace-energy-high-q-gain",
            str(args.energy_high_q_gain),
            "--switch-trace-energy-dvdc-d-gain",
            str(args.energy_dvdc_d_gain),
            "--switch-trace-energy-dvdc-q-gain",
            str(args.energy_dvdc_q_gain),
            "--switch-trace-energy-d-min",
            str(args.energy_d_min),
            "--switch-trace-energy-d-max",
            str(args.energy_d_max),
            "--switch-trace-energy-q-min",
            str(args.energy_q_min),
            "--switch-trace-energy-q-max",
            str(args.energy_q_max),
        ]
        if args.energy_two_zone_all_topologies:
            cmd += ["--switch-trace-energy-two-zone-all-topologies"]
    if args.q_gate_lv_min_pu > 0.0:
        cmd += ["--switch-trace-q-gate-lv-min-pu", str(args.q_gate_lv_min_pu)]
    if args.q_gate_time_min_s > 0.0:
        cmd += ["--switch-trace-q-gate-time-min-s", str(args.q_gate_time_min_s)]
    if args.q_gate_vdc_min_pu > 0.0:
        cmd += ["--switch-trace-q-gate-vdc-min-pu", str(args.q_gate_vdc_min_pu)]
    if math.isfinite(args.q_gate_vdc_max_pu):
        cmd += ["--switch-trace-q-gate-vdc-max-pu", str(args.q_gate_vdc_max_pu)]
    if args.q_gate_mode != "binary":
        cmd += ["--switch-trace-q-gate-mode", args.q_gate_mode]
    if math.isfinite(args.q_gate_lv_full_pu):
        cmd += ["--switch-trace-q-gate-lv-full-pu", str(args.q_gate_lv_full_pu)]
    if math.isfinite(args.q_gate_time_full_s):
        cmd += ["--switch-trace-q-gate-time-full-s", str(args.q_gate_time_full_s)]
    if args.fault_window_repeat_mult > 1:
        cmd += [
            "--switch-trace-fault-window-repeat-mult",
            str(args.fault_window_repeat_mult),
        ]
    if args.recovery_window_repeat_mult > 1:
        cmd += [
            "--switch-trace-recovery-window-repeat-mult",
            str(args.recovery_window_repeat_mult),
        ]
    if args.pre_window_repeat_mult > 1:
        cmd += [
            "--switch-trace-pre-window-repeat-mult",
            str(args.pre_window_repeat_mult),
        ]
    if relabel_with_trajectory:
        copied_profile_csv = run_dir / "initial_trajectory.csv"
        if args.trajectory_file is not None and copied_profile_csv.exists():
            cmd += [
                "--switch-trace-target-profile",
                "csv_file",
                "--switch-trace-profile-csv",
                str(copied_profile_csv),
            ]
        else:
            stop_time = args.fault_start + args.duration_s + args.fault_stop_margin
            cmd += [
                "--switch-trace-target-profile",
                args.preset,
                "--switch-trace-profile-dt",
                str(args.decision_dt),
                "--switch-trace-profile-stop-time",
                str(stop_time),
                "--switch-trace-profile-base-action",
                *[str(x) for x in args.base_action],
                "--switch-trace-profile-start-action",
                *[str(x) for x in args.start_action],
                "--switch-trace-profile-action",
                *[str(x) for x in args.action],
                "--switch-trace-profile-step-time",
                str(args.step_time),
                "--switch-trace-profile-ramp-start",
                str(args.ramp_start),
                "--switch-trace-profile-ramp-end",
                str(args.ramp_end),
            ]
            if args.down_start is not None:
                cmd += ["--switch-trace-profile-down-start", str(args.down_start)]
            if args.down_end is not None:
                cmd += ["--switch-trace-profile-down-end", str(args.down_end)]
    if args.bc_obs_noise_repeat > 0 and args.bc_obs_noise_std > 0:
        cmd += [
            "--bc-obs-noise-std",
            str(args.bc_obs_noise_std),
            "--bc-obs-noise-repeat",
            str(args.bc_obs_noise_repeat),
        ]
    run_command(cmd, run_dir=run_dir, log_name=f"train_{safe_token(run_id)}.log", timeout_s=args.train_timeout_s)
    summary = json.loads((RESULTS / run_id / "summary.json").read_text(encoding="utf-8"))
    metrics = summary.get("metrics", {})
    if int(metrics.get("switch_trace_augmented_samples", 0)) <= 0:
        raise RuntimeError(
            "BC training did not consume any switch trace samples. "
            f"trace_csv={trace_csv}, case_contains={args.case_contains}, "
            f"topology={args.topology}, window_zones={args.window_zones}"
        )
    write_json(run_dir / f"train_summary_{safe_token(run_id)}.json", summary)
    return summary


def export_actor(args: argparse.Namespace, run_dir: Path, *, model: Path, out: Path, label: str) -> None:
    run_command(
        [
            "py",
            "-3",
            "-m",
            "sac.export_hpt_sac_actor",
            "--model",
            str(model),
            "--out",
            str(out),
        ],
        run_dir=run_dir,
        log_name=f"export_{safe_token(label)}.log",
        timeout_s=300,
    )


def evaluate_actor(args: argparse.Namespace, run_dir: Path, *, label: str) -> dict[str, Any]:
    before = set(CONTROL_DIR.glob("control_comparison_*.csv"))
    case_name = args.case_name or make_case_name(args.duration_s, args.fault_pu)
    statements = [
        f"cd({matlab_string(str(SIMULINK_DIR).replace(chr(92), '/'))})",
        f"hpt_compare_topology={matlab_string(args.topology)}",
        "hpt_compare_scenario_type='fault'",
        "hpt_compare_modes=string({'conventional_dq','sac_actor_always_raw'})",
        f"hpt_compare_faults={matlab_fault_cell(case_name, args.fault_pu, args.duration_s, args.fault_phase_pu)}",
        f"hpt_compare_model_params={hpt_model_param_struct(args)}",
        "hpt_compare_conventional_profile='model_default'",
        f"hpt_compare_conventional_params={hpt_conventional_param_struct(args)}",
        f"hpt_compare_fault_start={args.fault_start:.12g}",
        f"hpt_compare_fault_stop_margin={args.fault_stop_margin:.12g}",
        f"hpt_compare_fault_settle_s={args.fault_settle_s:.12g}",
        f"hpt_compare_voltage_survival_current_gate={str(bool(args.voltage_survival_current_gate)).lower()}",
        f"hpt_compare_actor_filter_tau={args.actor_filter_tau:.12g}",
        f"hpt_compare_run_label={matlab_string(label)}",
        "run(fullfile(pwd,'evaluators','eval_hpt_v2_control_comparison.m'))",
    ]
    proc = run_command(
        [args.matlab_cmd, "-batch", "; ".join(statements)],
        run_dir=run_dir,
        log_name=f"eval_actor_{safe_token(label)}.log",
        timeout_s=args.matlab_timeout_s,
        allow_nonzero=True,
    )
    csv_path = new_file_or_none(CONTROL_DIR, "control_comparison_*.csv", before)
    if proc.returncode != 0 and csv_path is None:
        raise RuntimeError(
            f"Actor evaluation failed ({proc.returncode}) and produced no new CSV"
        )
    if csv_path is None:
        csv_path = latest_new_file(CONTROL_DIR, "control_comparison_*.csv", before)
    if proc.returncode != 0:
        warning_path = run_dir / f"eval_actor_{safe_token(label)}_nonzero_return.warning.txt"
        warning_path.write_text(
            f"MATLAB returned {proc.returncode}, but actor evaluation produced {csv_path}.\n",
            encoding="utf-8",
        )
    summary = summarize_control_csv(csv_path, "sac_actor_always_raw")
    write_json(run_dir / f"eval_summary_{safe_token(label)}.json", summary)
    return summary


def write_report(run_dir: Path, summary: dict[str, Any]) -> None:
    evals = summary.get("actor_evaluations", [])
    lines = [
        "# HPT Trajectory Specialist Campaign",
        "",
        f"- Run ID: `{summary['run_id']}`",
        f"- Topology: `{summary['topology']}`",
        f"- Fault: `{summary['fault_pu']} pu / {summary['duration_s']} s`",
        f"- Final model: `{summary.get('final_model', '')}`",
        f"- Final exported actor: `{summary.get('final_actor_mat', '')}`",
        f"- Promoted voltage-survival: `{summary.get('promoted_voltage_survival', False)}`",
        f"- Promoted beats conventional: `{summary.get('promoted_beats_baseline', False)}`",
        "",
        "## Evaluations",
        "",
        "| Iteration | Voltage Pass | Beat | Score | Baseline | Vdc min/max | LV mean/recovery | Reason |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for item in evals:
        lines.append(
            f"| `{item['label']}` | {item['policy_voltage_pass']} | "
            f"{item['policy_beats_baseline']} | {item['policy_score']:.3f} | "
            f"{item['baseline_score']:.3f} | {item['policy_vdc_min']:.2f}/{item['policy_vdc_max']:.2f} | "
            f"{item['policy_lv_mean']:.2f}/{item['policy_lv_recovery_mean']:.2f} | "
            f"`{item['policy_voltage_reason'] or item['policy_full_frt_reason']}` |"
        )
    (run_dir / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--topology", default="topology2", choices=["topology1", "topology2"])
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
    parser.add_argument("--chopper-threshold", type=float, default=850.0)
    parser.add_argument("--rchop-scale", type=float, default=1.0)
    parser.add_argument(
        "--strong-dq-profile",
        choices=sorted(STRONG_DQ_PROFILES),
        default="none",
        help="Optional named conventional-DQ parameter set to inject into traces and evaluations.",
    )
    parser.add_argument(
        "--voltage-survival-current-gate",
        action="store_true",
        help="Require grid-current limit pass in the staged voltage-survival gate.",
    )
    parser.add_argument(
        "--actor-filter-tau",
        type=float,
        default=0.001,
        help="SAC actor command filter time constant in seconds; use 0 for raw actor diagnostics.",
    )
    parser.add_argument("--case-name", default="")
    parser.add_argument(
        "--trajectory-file",
        type=Path,
        default=None,
        help="Use an existing hpt_traj_t/hpt_traj_action MAT file as the initial teacher trajectory.",
    )
    parser.add_argument(
        "--teacher-source",
        choices=["trajectory", "rule"],
        default="trajectory",
        help="Initial BC teacher source. 'rule' collects policy_mode=0 conventional/rule-DQ traces.",
    )
    parser.add_argument("--teacher-policy-mode", type=float, default=0.0)
    parser.add_argument("--teacher-actor-select-mode", type=float, default=0.0)
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
    parser.add_argument("--decision-dt", type=float, default=2e-3)
    parser.add_argument("--action", type=float, nargs=4, default=[0.172, 0.0, 0.022, 0.002])
    parser.add_argument("--start-action", type=float, nargs=4, default=[0.0, 0.0, 0.0, 0.0])
    parser.add_argument("--base-action", type=float, nargs=4, default=[0.0, 0.0, 0.0, 0.0])
    parser.add_argument("--safe-target", type=float, nargs=4, default=[0.172, 0.0, 0.014, 0.002])
    parser.add_argument("--step-time", type=float, default=0.035)
    parser.add_argument("--ramp-start", type=float, default=0.035)
    parser.add_argument("--ramp-end", type=float, default=0.055)
    parser.add_argument("--down-start", type=float, default=None)
    parser.add_argument("--down-end", type=float, default=None)
    parser.add_argument("--dagger-iters", type=int, default=2)
    parser.add_argument("--vdc-feedback-gain", type=float, default=0.10)
    parser.add_argument("--vdc-feedback-ref-pu", type=float, default=1.0)
    parser.add_argument(
        "--energy-two-zone",
        action="store_true",
        help=(
            "Use state-feedback energy-head relabeling during BC/DAgger: "
            "one signed d/q response for low Vdc and another for high Vdc."
        ),
    )
    parser.add_argument(
        "--energy-two-zone-all-topologies",
        action="store_true",
        help="Apply two-zone energy relabeling to topology1 as well as topology2.",
    )
    parser.add_argument("--energy-vdc-low-pu", type=float, default=0.95)
    parser.add_argument("--energy-vdc-high-pu", type=float, default=1.12)
    parser.add_argument("--energy-low-d-gain", type=float, default=-2.0)
    parser.add_argument("--energy-low-q-gain", type=float, default=1.0)
    parser.add_argument("--energy-high-d-gain", type=float, default=0.20)
    parser.add_argument("--energy-high-q-gain", type=float, default=-0.80)
    parser.add_argument("--energy-dvdc-d-gain", type=float, default=0.0)
    parser.add_argument("--energy-dvdc-q-gain", type=float, default=-0.20)
    parser.add_argument("--energy-d-min", type=float, default=-0.95)
    parser.add_argument("--energy-d-max", type=float, default=0.95)
    parser.add_argument("--energy-q-min", type=float, default=-0.95)
    parser.add_argument("--energy-q-max", type=float, default=0.95)
    parser.add_argument("--q-gate-lv-min-pu", type=float, default=0.0)
    parser.add_argument("--q-gate-time-min-s", type=float, default=0.0)
    parser.add_argument("--q-gate-vdc-min-pu", type=float, default=0.0)
    parser.add_argument("--q-gate-vdc-max-pu", type=float, default=float("inf"))
    parser.add_argument("--q-gate-mode", choices=["binary", "continuous"], default="binary")
    parser.add_argument("--q-gate-lv-full-pu", type=float, default=float("inf"))
    parser.add_argument("--q-gate-time-full-s", type=float, default=float("inf"))
    parser.add_argument("--switch-trace-repeat", type=int, default=64)
    parser.add_argument("--window-zones", default="all")
    parser.add_argument("--case-contains", default="")
    parser.add_argument("--epochs", type=int, default=80)
    parser.add_argument("--batch-size", type=int, default=512)
    parser.add_argument("--lr", type=float, default=2e-4)
    parser.add_argument("--action-weights", default="4,1,0.5,0.5")
    parser.add_argument("--teacher-prior-weight", type=float, default=30.0)
    parser.add_argument("--bc-obs-noise-std", type=float, default=0.012)
    parser.add_argument("--bc-obs-noise-repeat", type=int, default=4)
    parser.add_argument(
        "--fault-window-repeat-mult",
        type=int,
        default=1,
        help="Extra BC repeat multiplier for switch trace rows marked window_zone=fault.",
    )
    parser.add_argument(
        "--recovery-window-repeat-mult",
        type=int,
        default=1,
        help="Extra BC repeat multiplier for switch trace rows marked window_zone=recovery.",
    )
    parser.add_argument(
        "--pre-window-repeat-mult",
        type=int,
        default=1,
        help="Extra BC repeat multiplier for switch trace rows marked window_zone=pre.",
    )
    parser.add_argument(
        "--dagger-label-source",
        choices=["safe_target", "trajectory"],
        default="safe_target",
        help="How to relabel actor-visited states during DAgger iterations.",
    )
    parser.add_argument(
        "--collect-final-actor-trace",
        action="store_true",
        help="After promotion selection, collect actor-visited trace and compare it with the initial teacher trace.",
    )
    parser.add_argument("--matlab-cmd", default="matlab")
    parser.add_argument("--matlab-timeout-s", type=int, default=1200)
    parser.add_argument("--train-timeout-s", type=int, default=600)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.case_contains == "":
        args.case_contains = make_case_name(args.duration_s, args.fault_pu)
    args.run_id = args.run_id or (
        f"hpt_traj_specialist_{safe_token(args.topology)}_"
        f"{safe_token(args.case_contains)}_{time.strftime('%Y%m%d_%H%M%S')}"
    )
    run_dir = RESULTS / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    MODELS.mkdir(parents=True, exist_ok=True)

    trajectory_file: Path | None = None
    if args.teacher_source == "trajectory":
        trajectory_file = build_initial_trajectory(args, run_dir)
        trajectory_summary = validate_trajectory(args, run_dir)
        initial_trace = collect_trace(
            args,
            run_dir,
            label="trajectory_teacher",
            policy_mode=-2.0,
            actor_select_mode=0.0,
            trajectory_file=trajectory_file,
        )
    else:
        trajectory_summary = {
            "schema": "hpt-trajectory-switch-validation-v1",
            "run_id": f"{args.run_id}_rule_teacher",
            "topology": args.topology,
            "fault_pu": args.fault_pu,
            "duration_s": args.duration_s,
            "teacher_source": "rule",
            "trajectory_voltage_pass": False,
            "trajectory_beats_baseline": False,
            "trajectory_reason": "not_applicable_rule_teacher",
        }
        initial_trace = collect_trace(
            args,
            run_dir,
            label="rule_teacher",
            policy_mode=args.teacher_policy_mode,
            actor_select_mode=args.teacher_actor_select_mode,
            trajectory_file=None,
        )

    model = MODELS / f"{args.run_id}_bc0.zip"
    train_summaries: list[dict[str, Any]] = []
    actor_evals: list[dict[str, Any]] = []
    train_summaries.append(
        train_bc(
            args,
            run_dir,
            trace_csv=initial_trace,
            run_id=f"{args.run_id}_bc0",
            model_out=model,
            init_model=None,
            fixed_target=None,
            vdc_feedback_gain=0.0,
            relabel_with_trajectory=args.teacher_source == "trajectory",
        )
    )

    actor_mat = SIMULINK_DIR / "hpt_sac_actor_weights_dynamic.mat"
    dynamic_actor_backup = register_dynamic_actor_restore(actor_mat, run_dir)
    export_actor(args, run_dir, model=model, out=actor_mat, label="bc0_dynamic")
    eval_summary = evaluate_actor(args, run_dir, label=f"{args.run_id}_bc0_actor")
    eval_summary["label"] = "bc0"
    eval_summary["model_path"] = str(model)
    actor_evals.append(eval_summary)

    for idx in range(1, max(0, args.dagger_iters) + 1):
        actor_trace = collect_trace(
            args,
            run_dir,
            label=f"actor_dagger{idx}_trace",
            policy_mode=1.0,
            actor_select_mode=3.0,
            trajectory_file=None,
        )
        next_model = MODELS / f"{args.run_id}_dagger{idx}.zip"
        train_summaries.append(
            train_bc(
                args,
                run_dir,
                trace_csv=actor_trace,
                run_id=f"{args.run_id}_dagger{idx}",
                model_out=next_model,
                init_model=model,
                fixed_target=list(args.safe_target) if args.dagger_label_source == "safe_target" else None,
                vdc_feedback_gain=args.vdc_feedback_gain,
                relabel_with_trajectory=args.dagger_label_source == "trajectory",
            )
        )
        model = next_model
        export_actor(args, run_dir, model=model, out=actor_mat, label=f"dagger{idx}_dynamic")
        eval_summary = evaluate_actor(args, run_dir, label=f"{args.run_id}_dagger{idx}_actor")
        eval_summary["label"] = f"dagger{idx}"
        eval_summary["model_path"] = str(model)
        actor_evals.append(eval_summary)

    best = min(
        actor_evals,
        key=lambda item: (
            not item["policy_voltage_pass"],
            not item["policy_beats_baseline"],
            item["policy_score"],
        ),
    )
    best_model = Path(best["model_path"])
    final_actor = SIMULINK_DIR / f"hpt_sac_actor_weights_{safe_token(args.run_id)}.mat"
    export_actor(args, run_dir, model=best_model, out=final_actor, label=f"final_specialist_{best['label']}")
    final_actor_trace = ""
    trace_alignment: dict[str, Any] = {}
    if args.collect_final_actor_trace:
        export_actor(args, run_dir, model=best_model, out=actor_mat, label=f"final_dynamic_{best['label']}")
        actor_trace_path = collect_trace(
            args,
            run_dir,
            label="final_actor_trace",
            policy_mode=1.0,
            actor_select_mode=3.0,
            trajectory_file=None,
        )
        final_actor_trace = str(actor_trace_path)
        trace_alignment = trace_alignment_summary(initial_trace, actor_trace_path)
        write_json(run_dir / "trace_alignment_summary.json", trace_alignment)
    summary = {
        "schema": "hpt-trajectory-specialist-campaign-v1",
        "run_id": args.run_id,
        "topology": args.topology,
        "fault_pu": args.fault_pu,
        "duration_s": args.duration_s,
        "trajectory_summary": trajectory_summary,
        "trajectory_trace": str(initial_trace),
        "train_summaries": train_summaries,
        "actor_evaluations": actor_evals,
        "best_actor_evaluation": best,
        "final_model": str(best_model),
        "final_actor_mat": str(final_actor),
        "dynamic_actor_backup": dynamic_actor_backup,
        "final_actor_trace": final_actor_trace,
        "trace_alignment": trace_alignment,
        "promoted_voltage_survival": bool(best["policy_voltage_pass"]),
        "promoted_beats_baseline": bool(best["policy_beats_baseline"]),
        "config": jsonable_config(args),
    }
    write_json(run_dir / "summary.json", summary)
    write_report(run_dir, summary)
    write_experiment_metadata(
        run_dir,
        experiment_name="hpt_trajectory_specialist_campaign",
        config=summary["config"],
        dataset_manifest=initial_trace,
        policy_checkpoint=best_model,
        extra={
            "summary_path": str(run_dir / "summary.json"),
            "final_actor_mat": str(final_actor),
        },
    )
    print(json.dumps(summary, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
