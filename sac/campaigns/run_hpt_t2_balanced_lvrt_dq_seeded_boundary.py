"""Topology2 balanced LVRT boundary campaign with dq-seeded SAC.

This campaign intentionally avoids hand/search pre-ramp trajectory teachers.
For each fault-depth/duration case it:

1. collects a strong conventional-dq switch-level trace;
2. builds a behavior-anchor dataset from the dq command actions;
3. behavior-clones a split-head SAC actor from that dataset;
4. fine-tunes the actor with current-aware, support-regularized SAC;
5. validates strong dq, dq-seeded actor, and SAC fine-tuned actor in Simulink.

The final evidence is still switch-level validation.  Proxy-side SAC rewards
are stored as diagnostics only.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import numpy as np


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / ".git").exists() or (parent / "pyproject.toml").exists():
            return parent
    return Path(__file__).resolve().parents[3]


ROOT = _repo_root()
RESULTS = ROOT / "lab" / "results"
MODELS = ROOT / "data" / "models"
SIMULINK = ROOT / "simulink"
TRACE_DIR = RESULTS / "hpt_v2_trajectory_traces"
COMPARE_DIR = RESULTS / "hpt_v2_control_comparison"

OBS_DIM = 24


def compact_label(label: str, *, max_chars: int = 40) -> str:
    """Keep MATLAB-generated result filenames below legacy Windows limits."""

    if len(label) <= max_chars:
        return label
    digest = hashlib.sha256(label.encode("utf-8")).hexdigest()[:12]
    keep = max(12, max_chars - len(digest) - 1)
    return f"{label[:keep]}_{digest}"


def bounded_artifact_path(
    directory: Path,
    *,
    prefix: str,
    label: str,
    suffix: str,
    max_path_chars: int = 238,
) -> Path:
    """Return a deterministic Windows-safe path for long experiment labels."""

    direct = directory / f"{prefix}{label}{suffix}"
    if len(str(direct)) <= max_path_chars:
        return direct
    digest = hashlib.sha256(label.encode("utf-8")).hexdigest()[:12]
    fixed_chars = len(str(directory)) + 1 + len(prefix) + len(suffix) + len(digest) + 1
    keep = max(12, max_path_chars - fixed_chars)
    return directory / f"{prefix}{label[:keep]}_{digest}{suffix}"
ACT_DIM = 4
FAMILY_TIME_NORM_S = 0.12

COMMON_MODEL_PARAMS = {
    "hpt_m_reg_max": 0.6,
    "hpt_sac_reg_max": 0.6,
    "hpt_sac_reg_q_gain": -1.0,
    "hpt_inj_phase_offset": -1.05,
    "hpt_energy_i_kp": 0.25,
    "hpt_energy_i_ki": 45.0,
    "hpt_energy_vff_gain": 0.2,
    "hpt_energy_control_sign": -1.0,
    "hpt_energy_bridge_polarity": -1.0,
    "hpt_sac_fault_time_norm_s": FAMILY_TIME_NORM_S,
    "hpt_sac_recovery_time_norm_s": FAMILY_TIME_NORM_S,
}

STRONG_DQ_PARAMS = {
    "hpt_vreg_kp": 5.6,
    "hpt_vreg_ki": 0.35,
    "hpt_vdc_kp": 0.05,
    "hpt_vdc_ki": 0.02,
    "hpt_energy_i_kp": 0.20,
    "hpt_energy_i_ki": 35.0,
    "hpt_energy_vff_gain": 0.0,
    "hpt_energy_control_sign": -1.0,
    "hpt_energy_bridge_polarity": -1.0,
    "hpt_conventional_energy_scale": 0.15,
    "hpt_conventional_recovery_reg_gain": 2.4,
    "hpt_conventional_recovery_reg_max": 0.44,
}


@dataclass(frozen=True)
class BoundaryCase:
    fault_pu: float
    duration_s: float
    topology: str = "topology2"
    category: str = "LVRT"
    phase_key: str = "abc"
    family_label: str = "t2_bal_lvrt"

    @property
    def duration_ms(self) -> int:
        return int(round(self.duration_s * 1000))

    @property
    def label(self) -> str:
        phase = str(self.phase_key or "abc").lower()
        phase_label = "bal" if phase in ("abc", "balanced") else phase
        family = self.family_label
        if phase_label != "bal" and f"_{phase_label}_" not in f"_{family}_":
            family = f"{family}_{phase_label}"
        return (
            f"{family}_pu{int(round(self.fault_pu * 1000)):04d}"
            f"_d{self.duration_ms:03d}ms"
        )

    @property
    def case_name(self) -> str:
        prefix = "hvrt" if self.category.upper() == "HVRT" else "lvrt"
        return f"{prefix}_{int(round(self.fault_pu * 1000)):04d}_{self.duration_ms:03d}ms"


def phase_pu_vector(case: BoundaryCase) -> list[float]:
    phase = str(case.phase_key or "abc").lower()
    if phase in ("abc", "balanced"):
        return [case.fault_pu, case.fault_pu, case.fault_pu]
    if phase == "a":
        return [case.fault_pu, 1.0, 1.0]
    if phase == "b":
        return [1.0, case.fault_pu, 1.0]
    if phase == "c":
        return [1.0, 1.0, case.fault_pu]
    if phase == "ab":
        return [case.fault_pu, case.fault_pu, 1.0]
    if phase == "bc":
        return [1.0, case.fault_pu, case.fault_pu]
    if phase in ("ca", "ac"):
        return [case.fault_pu, 1.0, case.fault_pu]
    raise ValueError(f"Unsupported phase key: {case.phase_key}")


def make_family_label(topology: str, category: str, phase_key: str) -> str:
    top = "t1" if str(topology).lower() == "topology1" else "t2"
    cat = "hvrt" if str(category).upper() == "HVRT" else "lvrt"
    phase = str(phase_key or "abc").lower()
    phase_label = "bal" if phase in ("abc", "balanced") else phase
    return f"{top}_{phase_label}_{cat}"


def _matlab_string(path: Path) -> str:
    return str(path).replace("\\", "/").replace("'", "''")


def _matlab_struct(params: dict[str, float]) -> str:
    parts: list[str] = []
    for key, value in params.items():
        parts.append(f"{key},{float(value):.17g}")
    if not parts:
        return "struct()"
    fields = []
    for key, value in params.items():
        fields.append(f"'{key}', {float(value):.17g}")
    return "struct(" + ", ".join(fields) + ")"


def mat_vector(values: Iterable[float]) -> str:
    return "[" + " ".join(f"{float(v):.17g}" for v in values) + "]"


def run_logged(
    cmd: list[str],
    *,
    cwd: Path,
    log_path: Path,
    env: dict[str, str] | None = None,
) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8", errors="replace") as log:
        log.write("$ " + " ".join(cmd) + "\n\n")
        log.flush()
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
        )
    if proc.returncode != 0:
        raise RuntimeError(f"Command failed with exit code {proc.returncode}: {' '.join(cmd)}")


def latest_file(pattern: str, *, after: float, directory: Path) -> Path:
    deadline = time.time() + 60.0
    matches: list[tuple[float, Path]] = []
    fallback_matches: list[tuple[float, Path]] = []
    while time.time() <= deadline:
        matches = []
        fallback_matches = []
        for path in directory.glob(pattern):
            try:
                mtime = path.stat().st_mtime
            except FileNotFoundError:
                continue
            fallback_matches.append((mtime, path))
            if mtime >= after - 1.0:
                matches.append((mtime, path))
        if matches:
            return max(matches, key=lambda item: item[0])[1]
        time.sleep(0.2)
    if fallback_matches:
        return max(fallback_matches, key=lambda item: item[0])[1]
    raise FileNotFoundError(f"No new file matched {directory / pattern}")


def matlab_collect_dq_trace(
    case: BoundaryCase,
    run_dir: Path,
    *,
    fault_start_s: float,
    trace_dir: Path | None = None,
) -> Path:
    trace_dir = Path(trace_dir) if trace_dir is not None else TRACE_DIR
    trace_dir.mkdir(parents=True, exist_ok=True)
    label = f"dqseed_{case.label}"
    runner = run_dir / f"collect_{label}.m"
    model_params = {**COMMON_MODEL_PARAMS, **STRONG_DQ_PARAMS}
    runner.write_text(
        "\n".join(
            [
                f"cd('{_matlab_string(ROOT)}');",
                f"addpath(genpath('{_matlab_string(SIMULINK)}'));",
                f'hpt_trace_topology = "{case.topology}";',
                f"hpt_trace_fault_pu = {case.fault_pu:.12g};",
                "hpt_trace_fault_phase_pu = " + mat_vector(phase_pu_vector(case)) + ";",
                f"hpt_trace_fault_duration = {case.duration_s:.12g};",
                f"hpt_trace_fault_start = {fault_start_s:.12g};",
                "hpt_trace_fault_stop_margin = 0.125;",
                "hpt_trace_policy_mode = 0.0;",
                "hpt_trace_actor_select_mode = 0.0;",
                "hpt_trace_actor_filter_tau = 0.001;",
                f"hpt_trace_model_params = {_matlab_struct(model_params)};",
                f'hpt_trace_run_label = "{label}";',
                "hpt_trace_sample_stride = 100;",
                f"hpt_trace_output_dir = '{_matlab_string(trace_dir)}';",
                f"run('{_matlab_string(SIMULINK / 'collectors' / 'collect_hpt_v2_trajectory_trace.m')}');",
            ]
        ),
        encoding="utf-8",
    )
    before = time.time()
    run_logged(
        ["matlab", "-batch", f"run('{_matlab_string(runner)}')"],
        cwd=ROOT,
        log_path=run_dir / f"{label}_collect.log",
    )
    return latest_file(
        f"trajectory_trace_{case.topology}_{label}_*.csv",
        after=before,
        directory=trace_dir,
    )


def build_anchor_from_trace(
    trace_csv: Path,
    out_npz: Path,
    out_json: Path,
    *,
    min_time_s: float,
    prefault_repeat: int,
    fault_repeat: int,
    recovery_repeat: int,
    tail_repeat: int,
) -> dict:
    obs_rows: list[np.ndarray] = []
    act_rows: list[np.ndarray] = []
    zone_counts: dict[str, int] = {}
    target_prefix = "action"
    with trace_csv.open("r", newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            row_t = float(row.get("t") or 0.0)
            if row_t < float(min_time_s):
                continue
            obs = np.asarray(
                [float(row[f"obs_{idx:02d}"]) for idx in range(1, OBS_DIM + 1)],
                dtype=np.float32,
            )
            action = np.asarray(
                [float(row[f"{target_prefix}_{idx:02d}"]) for idx in range(1, ACT_DIM + 1)],
                dtype=np.float32,
            )
            zone = str(row.get("window_zone") or "").strip().lower()
            repeat = {
                "prefault": prefault_repeat,
                "fault": fault_repeat,
                "recovery": recovery_repeat,
                "tail": tail_repeat,
            }.get(zone, 1)
            zone_counts[zone or "unknown"] = zone_counts.get(zone or "unknown", 0) + 1
            for _ in range(max(1, int(repeat))):
                obs_rows.append(obs)
                act_rows.append(action)
    observations = np.asarray(obs_rows, dtype=np.float32)
    actions = np.asarray(act_rows, dtype=np.float32)
    if observations.ndim != 2 or observations.shape[1] != OBS_DIM:
        raise RuntimeError(f"Bad anchor observation shape: {observations.shape}")
    if actions.ndim != 2 or actions.shape[1] != ACT_DIM:
        raise RuntimeError(f"Bad anchor action shape: {actions.shape}")
    out_npz.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out_npz, observations=observations, actions=actions)
    summary = {
        "trace_csv": str(trace_csv),
        "dataset": str(out_npz),
        "samples": int(observations.shape[0]),
        "source_rows": int(sum(zone_counts.values())),
        "zone_counts": zone_counts,
        "action_mean": [float(v) for v in np.mean(actions, axis=0)],
        "action_min": [float(v) for v in np.min(actions, axis=0)],
        "action_max": [float(v) for v in np.max(actions, axis=0)],
        "target_columns": f"{target_prefix}_01..{target_prefix}_04",
        "teacher_source": "strong_conventional_dq_simulink_trace",
        "min_time_s": float(min_time_s),
    }
    out_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def train_dq_seed_actor(
    case: BoundaryCase,
    anchor_npz: Path,
    run_dir: Path,
    *,
    bc_epochs: int,
    seed: int,
    fault_start_s: float,
    artifact_tag: str,
    models_dir: Path | None = None,
) -> Path:
    models_dir = Path(models_dir) if models_dir is not None else MODELS
    model_out = models_dir / f"hpt_{case.label}_{artifact_tag}_dqseed_split_actor.zip"
    run_id = f"{case.label}_dqseed_bc_{time.strftime('%Y%m%d_%H%M%S')}"
    cmd = [
        sys.executable,
        "-m",
        "sac.offline.train_hpt_voltage_sac",
        "--single-topology",
        case.topology,
        "--single-fault-pu",
        f"{case.fault_pu:.12g}",
        "--single-fault-duration-s",
        f"{case.duration_s:.12g}",
        "--single-fault-start-s",
        f"{fault_start_s:.12g}",
        "--single-category",
        case.category.upper(),
        "--single-phase-key",
        case.phase_key,
        "--controller-heads",
        "split",
        "--steps",
        "1",
        "--n-envs",
        "1",
        "--learning-rate",
        "1e-9",
        "--behavior-anchor-dataset",
        str(anchor_npz),
        "--behavior-anchor-epochs",
        str(bc_epochs),
        "--behavior-anchor-interval-steps",
        "1",
        "--behavior-anchor-lr",
        "1e-4",
        "--behavior-anchor-batch-size",
        "512",
        "--behavior-anchor-action-weights",
        "8,6,12,12",
        "--eval-rollouts",
        "1",
        "--run-id",
        run_id,
        "--model-out",
        str(model_out),
        "--reg-d-limit",
        "0.6",
        "--reg-q-limit",
        "0.6",
        "--reg-limit",
        "0.6",
        "--grid-current-reward-weight",
        "180",
        "--envelope-reward-weight",
        "360",
        "--fault-time-norm-s",
        f"{FAMILY_TIME_NORM_S:.12g}",
        "--recovery-time-norm-s",
        f"{FAMILY_TIME_NORM_S:.12g}",
    ]
    run_logged(cmd, cwd=ROOT, log_path=run_dir / f"{case.label}_dqseed_bc.log")
    return model_out


def train_sac_finetune(
    case: BoundaryCase,
    seed_model: Path,
    anchor_npz: Path,
    run_dir: Path,
    *,
    sac_steps: int,
    seed: int,
    fault_start_s: float,
    artifact_tag: str,
    energy_head_only: bool = False,
    learning_rate: float = 2e-8,
    support_weight: float = 12000.0,
    vdc_bounds_weight: float = 35000.0,
    vdc_margin_weight: float = 0.0,
    vdc_margin_pu: float = 0.05,
    proxy_vdc_downshift_pu: float = 0.0,
    envelope_weight: float = 900.0,
    calibrated_survival_weight: float = 6000.0,
    lv_margin_weight: float = 0.0,
    lv_margin_pu: float = 0.02,
    behavior_anchor_interval_steps: int = 120,
    models_dir: Path | None = None,
) -> Path:
    models_dir = Path(models_dir) if models_dir is not None else MODELS
    model_out = models_dir / f"hpt_{case.label}_{artifact_tag}_dqseed_split_currentaware_sacft.zip"
    run_id = f"{case.label}_currentaware_sacft_{time.strftime('%Y%m%d_%H%M%S')}"
    cmd = [
        sys.executable,
        "-m",
        "sac.offline.train_hpt_voltage_sac",
        "--single-topology",
        case.topology,
        "--single-fault-pu",
        f"{case.fault_pu:.12g}",
        "--single-fault-duration-s",
        f"{case.duration_s:.12g}",
        "--single-fault-start-s",
        f"{fault_start_s:.12g}",
        "--single-category",
        case.category.upper(),
        "--single-phase-key",
        case.phase_key,
        "--controller-heads",
        "split",
        "--init-model",
        str(seed_model),
        "--steps",
        str(sac_steps),
        "--n-envs",
        "2",
        "--learning-rate",
        f"{float(learning_rate):.12g}",
        "--sac-support-regularization-weight",
        f"{float(support_weight):.12g}",
        "--sac-support-regularization-batch-size",
        "256",
        "--sac-support-anchor-dataset",
        str(anchor_npz),
        "--sac-support-action-weights",
        "16,14,45,45",
        "--sac-support-nearest-replay",
        "--behavior-anchor-dataset",
        str(anchor_npz),
        "--behavior-anchor-epochs",
        "6",
        "--behavior-anchor-interval-steps",
        str(int(behavior_anchor_interval_steps)),
        "--behavior-anchor-lr",
        "2e-5",
        "--behavior-anchor-batch-size",
        "512",
        "--behavior-anchor-action-weights",
        "14,12,35,35",
        "--eval-rollouts",
        "3",
        "--run-id",
        run_id,
        "--model-out",
        str(model_out),
        "--reg-d-limit",
        "0.6",
        "--reg-q-limit",
        "0.6",
        "--reg-limit",
        "0.6",
        "--grid-current-reward-weight",
        "120",
        "--grid-reactive-reward-weight",
        "0",
        "--envelope-reward-weight",
        f"{float(envelope_weight):.12g}",
        "--calibrated-survival-reward-weight",
        f"{float(calibrated_survival_weight):.12g}",
        "--vdc-soft-reward-weight",
        "260",
        "--vdc-bounds-reward-weight",
        f"{float(vdc_bounds_weight):.12g}",
        "--vdc-margin-reward-weight",
        f"{float(vdc_margin_weight):.12g}",
        "--vdc-margin-pu",
        f"{float(vdc_margin_pu):.12g}",
        "--proxy-vdc-reward-downshift-pu",
        f"{float(proxy_vdc_downshift_pu):.12g}",
        "--lv-margin-reward-weight",
        f"{float(lv_margin_weight):.12g}",
        "--lv-margin-pu",
        f"{float(lv_margin_pu):.12g}",
        "--action-slew-weight",
        "0.16",
        "--fault-time-norm-s",
        f"{FAMILY_TIME_NORM_S:.12g}",
        "--recovery-time-norm-s",
        f"{FAMILY_TIME_NORM_S:.12g}",
    ]
    if energy_head_only:
        cmd.append("--sac-energy-head-only")
    run_logged(cmd, cwd=ROOT, log_path=run_dir / f"{case.label}_sacft.log")
    return model_out


def export_actor_for_simulink(model_path: Path, run_dir: Path, tag: str) -> Path:
    out_root = SIMULINK / "hpt_sac_actor_weights_dynamic.mat"
    cmd = [
        sys.executable,
        "-m",
        "sac.export_hpt_sac_actor",
        "--model",
        str(model_path),
        "--out",
        str(out_root),
    ]
    run_logged(cmd, cwd=ROOT, log_path=run_dir / f"{tag}_export.log")
    for folder in (SIMULINK / "topology2", SIMULINK / "topology1"):
        folder.mkdir(parents=True, exist_ok=True)
        shutil.copy2(out_root, folder / "hpt_sac_actor_weights_dynamic.mat")
    archived = run_dir / f"{tag}_hpt_sac_actor_weights_dynamic.mat"
    shutil.copy2(out_root, archived)
    return archived


def matlab_evaluate_actor(
    case: BoundaryCase,
    run_dir: Path,
    *,
    tag: str,
    fault_start_s: float,
    actor_filter_tau: float,
    compare_dir: Path | None = None,
) -> Path:
    compare_dir = Path(compare_dir) if compare_dir is not None else COMPARE_DIR
    compare_dir.mkdir(parents=True, exist_ok=True)
    label = f"{case.label}_{tag}"
    matlab_label = compact_label(label)
    runner = bounded_artifact_path(
        run_dir,
        prefix="eval_",
        label=label,
        suffix=".m",
    )
    model_params = COMMON_MODEL_PARAMS
    runner.write_text(
        "\n".join(
            [
                f"cd('{_matlab_string(ROOT)}');",
                f"addpath(genpath('{_matlab_string(SIMULINK)}'));",
                f'hpt_compare_topology = "{case.topology}";',
                'hpt_compare_scenario_type = "fault";',
                'hpt_compare_case_name = "all";',
                'hpt_compare_modes = ["conventional_dq", "sac_actor_always_raw"];',
                "hpt_compare_energy_enable = 1.0;",
                "hpt_compare_voltage_survival_current_gate = true;",
                f"hpt_compare_actor_filter_tau = {float(actor_filter_tau):.12g};",
                f"hpt_compare_fault_start = {fault_start_s:.12g};",
                "hpt_compare_fault_stop_margin = 0.125;",
                "hpt_compare_conventional_profile = \"tuned_v2_l1\";",
                f"hpt_compare_model_params = {_matlab_struct(model_params)};",
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
    run_logged(
        ["matlab", "-batch", f"run('{_matlab_string(runner)}')"],
        cwd=ROOT,
        log_path=bounded_artifact_path(
            run_dir,
            prefix="",
            label=label,
            suffix="_eval.log",
        ),
    )
    return latest_file(
        f"control_comparison_{case.topology}_fault_all_{matlab_label}_*.csv",
        after=before,
        directory=compare_dir,
    )


def read_comparison_rows(
    csv_path: Path,
    *,
    controller_label: str,
    include_strong_dq: bool = True,
) -> list[dict]:
    rows: list[dict] = []
    with csv_path.open("r", newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            out = dict(row)
            mode = str(out.get("mode") or "")
            if mode == "sac_actor_always_raw":
                out["controller"] = controller_label
            elif mode == "conventional_dq":
                if not include_strong_dq:
                    continue
                out["controller"] = "strong_dq"
            else:
                out["controller"] = mode
            out["source_csv"] = str(csv_path)
            rows.append(out)
    return rows


def write_csv(path: Path, rows: Iterable[dict]) -> None:
    rows = list(rows)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def run_case(
    case: BoundaryCase,
    run_dir: Path,
    *,
    bc_epochs: int,
    sac_steps: int,
    seed: int,
    fault_start_s: float,
    anchor_min_time_s: float,
    energy_head_only: bool = False,
    actor_filter_tau: float = 0.001,
    sac_learning_rate: float = 2e-8,
    sac_support_weight: float = 12000.0,
    sac_vdc_bounds_weight: float = 35000.0,
    sac_vdc_margin_weight: float = 0.0,
    sac_vdc_margin_pu: float = 0.05,
    sac_proxy_vdc_downshift_pu: float = 0.0,
    sac_envelope_weight: float = 900.0,
    sac_calibrated_survival_weight: float = 6000.0,
    sac_lv_margin_weight: float = 0.0,
    sac_lv_margin_pu: float = 0.02,
    sac_behavior_anchor_interval_steps: int = 120,
) -> dict:
    case_dir = run_dir / case.label
    case_dir.mkdir(parents=True, exist_ok=True)
    artifact_tag = "".join(ch if ch.isalnum() or ch in ("_", "-") else "_" for ch in run_dir.name)
    dq_trace_csv = matlab_collect_dq_trace(case, case_dir, fault_start_s=fault_start_s)
    anchor_npz = case_dir / f"{case.label}_dq_anchor.npz"
    anchor_json = case_dir / f"{case.label}_dq_anchor.json"
    anchor_summary = build_anchor_from_trace(
        dq_trace_csv,
        anchor_npz,
        anchor_json,
        min_time_s=anchor_min_time_s,
        prefault_repeat=2,
        fault_repeat=12,
        recovery_repeat=6,
        tail_repeat=1,
    )
    seed_model = train_dq_seed_actor(
        case,
        anchor_npz,
        case_dir,
        bc_epochs=bc_epochs,
        seed=seed,
        fault_start_s=fault_start_s,
        artifact_tag=artifact_tag,
    )
    export_actor_for_simulink(seed_model, case_dir, f"{case.label}_dqseed")
    seed_eval_csv = matlab_evaluate_actor(
        case,
        case_dir,
        tag="dqseed",
        fault_start_s=fault_start_s,
        actor_filter_tau=actor_filter_tau,
    )

    sac_model = train_sac_finetune(
        case,
        seed_model,
        anchor_npz,
        case_dir,
        sac_steps=sac_steps,
        seed=seed + 1000,
        fault_start_s=fault_start_s,
        artifact_tag=artifact_tag,
        energy_head_only=energy_head_only,
        learning_rate=sac_learning_rate,
        support_weight=sac_support_weight,
        vdc_bounds_weight=sac_vdc_bounds_weight,
        vdc_margin_weight=sac_vdc_margin_weight,
        vdc_margin_pu=sac_vdc_margin_pu,
        proxy_vdc_downshift_pu=sac_proxy_vdc_downshift_pu,
        envelope_weight=sac_envelope_weight,
        calibrated_survival_weight=sac_calibrated_survival_weight,
        lv_margin_weight=sac_lv_margin_weight,
        lv_margin_pu=sac_lv_margin_pu,
        behavior_anchor_interval_steps=sac_behavior_anchor_interval_steps,
    )
    export_actor_for_simulink(sac_model, case_dir, f"{case.label}_sacft")
    sac_eval_csv = matlab_evaluate_actor(
        case,
        case_dir,
        tag="sacft",
        fault_start_s=fault_start_s,
        actor_filter_tau=actor_filter_tau,
    )

    rows = []
    rows.extend(read_comparison_rows(seed_eval_csv, controller_label="dq_seeded_actor_before_sac"))
    rows.extend(
        read_comparison_rows(
            sac_eval_csv,
            controller_label="dq_seeded_actor_after_sac",
            include_strong_dq=False,
        )
    )
    case_summary_csv = case_dir / f"{case.label}_comparison_summary.csv"
    write_csv(case_summary_csv, rows)
    return {
        "case": asdict(case),
        "label": case.label,
        "dq_trace_csv": str(dq_trace_csv),
        "anchor_npz": str(anchor_npz),
        "anchor_summary": anchor_summary,
        "dq_seed_model": str(seed_model),
        "sac_finetune_model": str(sac_model),
        "dq_seed_eval_csv": str(seed_eval_csv),
        "sac_finetune_eval_csv": str(sac_eval_csv),
        "case_summary_csv": str(case_summary_csv),
    }


def parse_list(raw: str, cast=float) -> list:
    return [cast(part.strip()) for part in raw.split(",") if part.strip()]


def parse_case_pairs(
    raw: str,
    *,
    topology: str,
    category: str,
    phase_key: str,
    family_label: str,
) -> list[BoundaryCase]:
    """Parse explicit depth:duration-ms pairs.

    Example: ``0.85:80;0.875:100;0.90:100``.
    """

    cases: list[BoundaryCase] = []
    for item in str(raw or "").split(";"):
        item = item.strip()
        if not item:
            continue
        if ":" not in item:
            raise ValueError(f"Bad --case-pairs item {item!r}; expected fault_pu:duration_ms")
        depth_text, duration_text = item.split(":", 1)
        cases.append(
            BoundaryCase(
                float(depth_text),
                float(duration_text) / 1000.0,
                topology=topology,
                category=category.upper(),
                phase_key=phase_key.lower(),
                family_label=family_label,
            )
        )
    return cases


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--topology", choices=["topology1", "topology2"], default="topology2")
    parser.add_argument("--category", choices=["LVRT", "HVRT"], default="LVRT")
    parser.add_argument(
        "--phase-key",
        choices=["abc", "a", "b", "c", "ab", "bc", "ca"],
        default="abc",
    )
    parser.add_argument(
        "--family-label",
        default="",
        help="Optional label prefix. Defaults to t1/t2 + phase + lvrt/hvrt.",
    )
    parser.add_argument("--depths", default="0.85,0.875,0.90")
    parser.add_argument("--durations-ms", default="80,100,120")
    parser.add_argument(
        "--case-pairs",
        default="",
        help="Optional explicit fault_pu:duration_ms pairs separated by ';'. Overrides depths/durations.",
    )
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--bc-epochs", type=int, default=180)
    parser.add_argument("--sac-steps", type=int, default=1200)
    parser.add_argument(
        "--sac-energy-head-only",
        action="store_true",
        help="If set, only update the energy head during SAC fine-tune. Default updates both split heads.",
    )
    parser.add_argument("--sac-learning-rate", type=float, default=2e-8)
    parser.add_argument("--sac-support-weight", type=float, default=12000.0)
    parser.add_argument("--sac-vdc-bounds-weight", type=float, default=35000.0)
    parser.add_argument("--sac-vdc-margin-weight", type=float, default=0.0)
    parser.add_argument("--sac-vdc-margin-pu", type=float, default=0.05)
    parser.add_argument("--sac-proxy-vdc-downshift-pu", type=float, default=0.0)
    parser.add_argument("--sac-envelope-weight", type=float, default=900.0)
    parser.add_argument("--sac-calibrated-survival-weight", type=float, default=6000.0)
    parser.add_argument("--sac-lv-margin-weight", type=float, default=0.0)
    parser.add_argument("--sac-lv-margin-pu", type=float, default=0.02)
    parser.add_argument("--sac-behavior-anchor-interval-steps", type=int, default=120)
    parser.add_argument("--seed", type=int, default=20260731)
    parser.add_argument(
        "--fault-start-s",
        type=float,
        default=0.080,
        help="Fault insertion time. 0.080 s avoids startup-transient teacher contamination.",
    )
    parser.add_argument(
        "--anchor-min-time-s",
        type=float,
        default=0.020,
        help="Discard earlier switch-trace samples from behavior anchors.",
    )
    parser.add_argument(
        "--actor-filter-tau",
        type=float,
        default=0.001,
        help="SAC actor command filter time constant used in switch-level validation.",
    )
    args = parser.parse_args()

    family_label = args.family_label.strip() or make_family_label(
        args.topology,
        args.category,
        args.phase_key,
    )
    run_id = args.run_id or f"hpt_{family_label}_dqseed_boundary_{time.strftime('%Y%m%d_%H%M%S')}"
    run_dir = RESULTS / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    depths = parse_list(args.depths, float)
    durations_ms = parse_list(args.durations_ms, int)
    if args.case_pairs.strip():
        cases = parse_case_pairs(
            args.case_pairs,
            topology=args.topology,
            category=args.category,
            phase_key=args.phase_key,
            family_label=family_label,
        )
    else:
        cases = [
            BoundaryCase(
                depth,
                dur / 1000.0,
                topology=args.topology,
                category=args.category,
                phase_key=args.phase_key,
                family_label=family_label,
            )
            for depth in depths
            for dur in durations_ms
        ]
    if args.smoke:
        smoke_pu = 1.10 if args.category.upper() == "HVRT" else 0.90
        cases = [
            BoundaryCase(
                smoke_pu,
                0.080,
                topology=args.topology,
                category=args.category,
                phase_key=args.phase_key,
                family_label=family_label,
            )
        ]

    metadata = {
        "run_id": run_id,
        "hypothesis": (
            "A split-head actor seeded only from strong dq switch-level traces, "
            "then fine-tuned with current-aware support-regularized SAC, can "
            "improve topology2 balanced LVRT boundary cases without a manual "
            "pre-ramp trajectory teacher."
        ),
        "topology": args.topology,
        "fault_family": family_label,
        "category": args.category,
        "phase_key": args.phase_key,
        "cases": [{**asdict(c), "label": c.label} for c in cases],
        "common_model_params": COMMON_MODEL_PARAMS,
        "strong_dq_params": STRONG_DQ_PARAMS,
        "bc_epochs": args.bc_epochs,
        "sac_steps": args.sac_steps,
        "sac_learning_rate": args.sac_learning_rate,
        "sac_support_weight": args.sac_support_weight,
        "sac_vdc_bounds_weight": args.sac_vdc_bounds_weight,
        "sac_vdc_margin_weight": args.sac_vdc_margin_weight,
        "sac_vdc_margin_pu": args.sac_vdc_margin_pu,
        "sac_proxy_vdc_downshift_pu": args.sac_proxy_vdc_downshift_pu,
        "sac_envelope_weight": args.sac_envelope_weight,
        "sac_calibrated_survival_weight": args.sac_calibrated_survival_weight,
        "sac_lv_margin_weight": args.sac_lv_margin_weight,
        "sac_lv_margin_pu": args.sac_lv_margin_pu,
        "sac_behavior_anchor_interval_steps": args.sac_behavior_anchor_interval_steps,
        "seed": args.seed,
        "fault_start_s": args.fault_start_s,
        "anchor_min_time_s": args.anchor_min_time_s,
        "actor_filter_tau": args.actor_filter_tau,
        "case_pairs": args.case_pairs,
        "sac_energy_head_only": bool(args.sac_energy_head_only),
    }
    (run_dir / "campaign_metadata.json").write_text(
        json.dumps(metadata, indent=2),
        encoding="utf-8",
    )

    summaries: list[dict] = []
    aggregate_rows: list[dict] = []
    for idx, case in enumerate(cases):
        summary = run_case(
            case,
            run_dir,
            bc_epochs=args.bc_epochs,
            sac_steps=args.sac_steps,
            seed=args.seed + idx,
            fault_start_s=args.fault_start_s,
            anchor_min_time_s=args.anchor_min_time_s,
            energy_head_only=args.sac_energy_head_only,
            actor_filter_tau=args.actor_filter_tau,
            sac_learning_rate=args.sac_learning_rate,
            sac_support_weight=args.sac_support_weight,
            sac_vdc_bounds_weight=args.sac_vdc_bounds_weight,
            sac_vdc_margin_weight=args.sac_vdc_margin_weight,
            sac_vdc_margin_pu=args.sac_vdc_margin_pu,
            sac_proxy_vdc_downshift_pu=args.sac_proxy_vdc_downshift_pu,
            sac_envelope_weight=args.sac_envelope_weight,
            sac_calibrated_survival_weight=args.sac_calibrated_survival_weight,
            sac_lv_margin_weight=args.sac_lv_margin_weight,
            sac_lv_margin_pu=args.sac_lv_margin_pu,
            sac_behavior_anchor_interval_steps=args.sac_behavior_anchor_interval_steps,
        )
        summaries.append(summary)
        with Path(summary["case_summary_csv"]).open("r", newline="", encoding="utf-8-sig") as handle:
            for row in csv.DictReader(handle):
                row["boundary_label"] = case.label
                row["boundary_fault_pu"] = f"{case.fault_pu:.6g}"
                row["boundary_duration_ms"] = str(case.duration_ms)
                aggregate_rows.append(row)
        (run_dir / "campaign_progress.json").write_text(
            json.dumps(summaries, indent=2),
            encoding="utf-8",
        )
        write_csv(run_dir / "boundary_comparison_rows.csv", aggregate_rows)

    (run_dir / "campaign_summary.json").write_text(
        json.dumps({"metadata": metadata, "cases": summaries}, indent=2),
        encoding="utf-8",
    )
    write_csv(run_dir / "boundary_comparison_rows.csv", aggregate_rows)
    print(json.dumps({"run_dir": str(run_dir), "cases": len(cases)}, indent=2))


if __name__ == "__main__":
    main()
