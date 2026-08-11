"""Build SAC support anchors for one HPT fault-family specialist.

The output is a compressed ``.npz`` containing ``observations`` and ``actions``.
It is intended for ``train_hpt_voltage_sac --sac-support-anchor-dataset`` when
the support set mixes actor rollouts and switch-validated trajectory candidates.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from sac.hpt_voltage_sac_env import (
    ACT_DIM_HPT,
    OBS_DIM_HPT,
    HPTVoltageEnvConfig,
    HPTVoltageSACEnv,
    HPTVoltageScenario,
)
from sac.offline.train_hpt_voltage_sac import (
    collect_manifest_actor_anchor_samples,
)


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / ".git").exists() or (parent / "pyproject.toml").exists():
            return parent
    return Path(__file__).resolve().parents[3]


ROOT = _repo_root()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as f:
        return [dict(row) for row in csv.DictReader(f)]


def truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "1.0", "true", "yes"}


def to_float(row: dict[str, str], key: str, default: float = 0.0) -> float:
    raw = row.get(key, "")
    if raw in ("", None):
        return float(default)
    return float(raw)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def git_head() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return "unknown"


def topology1_balanced_lvrt_scenario(
    *, fault_pu: float, duration_s: float, fault_start_s: float, fault_stop_margin_s: float
) -> HPTVoltageScenario:
    return HPTVoltageScenario(
        topology="topology1",
        grid_pu=float(fault_pu),
        neg_seq_pu=0.0,
        fault_phase_key="abc",
        duration_s=max(0.220, float(fault_start_s) + float(duration_s) + float(fault_stop_margin_s)),
        category="LVRT",
        fault_type="sym3ph",
        fault_start_s=float(fault_start_s),
        fault_duration_s=float(duration_s),
        recovery_tau_s=0.035,
    )


def piecewise_action(row: dict[str, str], *, t: float, fault_start_s: float, fault_duration_s: float) -> np.ndarray:
    pre = np.asarray(
        [
            to_float(row, "pre_reg_d", 0.0),
            0.0,
            to_float(row, "pre_energy_d", 0.0),
            0.0,
        ],
        dtype=np.float32,
    )
    fault = np.asarray(
        [
            to_float(row, "fault_reg_d", 0.0),
            to_float(row, "fault_reg_q", 0.0),
            to_float(row, "fault_energy_d", 0.0),
            to_float(row, "fault_energy_q", 0.0),
        ],
        dtype=np.float32,
    )
    recovery = np.asarray(
        [
            to_float(row, "recovery_reg_d", 0.0),
            to_float(row, "recovery_reg_q", 0.0),
            to_float(row, "recovery_energy_d", 0.0),
            to_float(row, "recovery_energy_q", 0.0),
        ],
        dtype=np.float32,
    )
    fault_end_s = float(fault_start_s) + float(fault_duration_s)
    if t < fault_start_s:
        return pre
    if t <= fault_end_s:
        return fault
    return recovery


def collect_trajectory_anchor_samples(
    sweep_csv: Path,
    *,
    config: HPTVoltageEnvConfig,
    episodes_per_row: int,
    seed: int,
    fault_pu: float,
    duration_s: float,
    fault_start_s: float,
    fault_stop_margin_s: float,
) -> tuple[np.ndarray, np.ndarray, list[dict[str, Any]]]:
    rows = [row for row in read_csv(sweep_csv) if truthy(row.get("trajectory_voltage_pass"))]
    scenario = topology1_balanced_lvrt_scenario(
        fault_pu=fault_pu,
        duration_s=duration_s,
        fault_start_s=fault_start_s,
        fault_stop_margin_s=fault_stop_margin_s,
    )
    obs_rows: list[np.ndarray] = []
    act_rows: list[np.ndarray] = []
    accepted_rows: list[dict[str, Any]] = []
    for row_idx, row in enumerate(rows):
        accepted_rows.append(
            {
                "token": row.get("token", ""),
                "trajectory_score": row.get("trajectory_score", ""),
                "trajectory_recovery_violation_max_pu": row.get(
                    "trajectory_recovery_violation_max_pu", ""
                ),
                "fault_reg_d": row.get("fault_reg_d", ""),
                "recovery_reg_d": row.get("recovery_reg_d", ""),
                "fault_energy_d": row.get("fault_energy_d", ""),
                "recovery_energy_d": row.get("recovery_energy_d", ""),
            }
        )
        for ep in range(max(1, int(episodes_per_row))):
            env = HPTVoltageSACEnv(
                [scenario],
                config=config,
                seed=seed + 1000 * row_idx + ep,
                train_mode=False,
            )
            obs, _ = env.reset()
            done = False
            while not done:
                action = piecewise_action(
                    row,
                    t=float(env.t),
                    fault_start_s=fault_start_s,
                    fault_duration_s=duration_s,
                )
                obs_rows.append(np.asarray(obs, dtype=np.float32))
                act_rows.append(action.astype(np.float32))
                obs, _, terminated, truncated, _ = env.step(action)
                done = bool(terminated or truncated)
    if not obs_rows:
        return (
            np.zeros((0, OBS_DIM_HPT), dtype=np.float32),
            np.zeros((0, ACT_DIM_HPT), dtype=np.float32),
            accepted_rows,
        )
    return (
        np.asarray(obs_rows, dtype=np.float32),
        np.asarray(act_rows, dtype=np.float32),
        accepted_rows,
    )


def infer_sweep_case_config(
    sweep_csv: Path,
    *,
    default_fault_pu: float,
    default_duration_s: float,
    default_fault_start_s: float,
    default_fault_stop_margin_s: float,
) -> dict[str, float]:
    """Infer the simulated fault case for one trajectory sweep CSV.

    The trajectory sweep runner writes ``summary.json`` next to
    ``sweep_results.csv``.  Prefer that metadata so a single support dataset can
    mix rows from different durations/depths without relying on one global
    ``--fault-pu`` / ``--duration-s`` pair.
    """

    config = {
        "fault_pu": float(default_fault_pu),
        "duration_s": float(default_duration_s),
        "fault_start_s": float(default_fault_start_s),
        "fault_stop_margin_s": float(default_fault_stop_margin_s),
    }
    summary_path = sweep_csv.with_name("summary.json")
    if not summary_path.exists():
        return config
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        sweep_config = summary.get("config", {})
        config["fault_pu"] = float(sweep_config.get("fault_pu", config["fault_pu"]))
        config["duration_s"] = float(sweep_config.get("duration_s", config["duration_s"]))
        config["fault_start_s"] = float(
            sweep_config.get("fault_start", config["fault_start_s"])
        )
        config["fault_stop_margin_s"] = float(
            sweep_config.get("fault_stop_margin", config["fault_stop_margin_s"])
        )
    except Exception:
        return config
    return config


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed-pass-manifest", type=Path, required=True)
    parser.add_argument(
        "--trajectory-sweep-csv",
        type=Path,
        action="append",
        required=True,
        help=(
            "One or more switch-level trajectory sweep CSVs.  Repeat this "
            "argument to mix passing trajectories from different family cases."
        ),
    )
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20260729)
    parser.add_argument("--seed-episodes-per-row", type=int, default=1)
    parser.add_argument("--seed-noise-std", type=float, default=0.0)
    parser.add_argument("--trajectory-episodes-per-row", type=int, default=1)
    parser.add_argument("--fault-pu", type=float, default=0.85)
    parser.add_argument("--duration-s", type=float, default=0.080)
    parser.add_argument("--fault-start-s", type=float, default=0.080)
    parser.add_argument("--fault-stop-margin-s", type=float, default=0.125)
    parser.add_argument("--reg-q-limit", type=float, default=0.80)
    args = parser.parse_args()

    seed_manifest = args.seed_pass_manifest
    if not seed_manifest.exists():
        raise FileNotFoundError(seed_manifest)
    sweep_csvs = [Path(path) for path in args.trajectory_sweep_csv]
    for sweep_csv in sweep_csvs:
        if not sweep_csv.exists():
            raise FileNotFoundError(sweep_csv)

    config = HPTVoltageEnvConfig(reg_q_limit=float(args.reg_q_limit))
    if args.seed_episodes_per_row > 0:
        seed_obs, seed_actions = collect_manifest_actor_anchor_samples(
            seed_manifest,
            config=config,
            episodes_per_row=args.seed_episodes_per_row,
            noise_std=args.seed_noise_std,
            seed=args.seed,
        )
    else:
        seed_obs = np.zeros((0, OBS_DIM_HPT), dtype=np.float32)
        seed_actions = np.zeros((0, ACT_DIM_HPT), dtype=np.float32)
    traj_obs_parts: list[np.ndarray] = []
    traj_action_parts: list[np.ndarray] = []
    accepted_traj: list[dict[str, Any]] = []
    sweep_metadata: list[dict[str, Any]] = []
    for sweep_idx, sweep_csv in enumerate(sweep_csvs):
        case_config = infer_sweep_case_config(
            sweep_csv,
            default_fault_pu=args.fault_pu,
            default_duration_s=args.duration_s,
            default_fault_start_s=args.fault_start_s,
            default_fault_stop_margin_s=args.fault_stop_margin_s,
        )
        part_obs, part_actions, part_rows = collect_trajectory_anchor_samples(
            sweep_csv,
            config=config,
            episodes_per_row=args.trajectory_episodes_per_row,
            seed=args.seed + 100_000 + 10_000 * sweep_idx,
            fault_pu=case_config["fault_pu"],
            duration_s=case_config["duration_s"],
            fault_start_s=case_config["fault_start_s"],
            fault_stop_margin_s=case_config["fault_stop_margin_s"],
        )
        for row in part_rows:
            row["source_sweep_csv"] = str(sweep_csv)
            row["source_fault_pu"] = case_config["fault_pu"]
            row["source_duration_s"] = case_config["duration_s"]
        traj_obs_parts.append(part_obs)
        traj_action_parts.append(part_actions)
        accepted_traj.extend(part_rows)
        sweep_metadata.append(
            {
                "trajectory_sweep_csv": str(sweep_csv),
                "trajectory_sweep_csv_sha256": sha256_file(sweep_csv),
                "case_config": case_config,
                "accepted_rows": len(part_rows),
                "anchor_samples": int(part_obs.shape[0]),
            }
        )
    if traj_obs_parts:
        traj_obs = np.concatenate(traj_obs_parts, axis=0)
        traj_actions = np.concatenate(traj_action_parts, axis=0)
    else:
        traj_obs = np.zeros((0, OBS_DIM_HPT), dtype=np.float32)
        traj_actions = np.zeros((0, ACT_DIM_HPT), dtype=np.float32)
    observations = np.concatenate([seed_obs, traj_obs], axis=0)
    actions = np.concatenate([seed_actions, traj_actions], axis=0)
    if observations.shape[1] != OBS_DIM_HPT or actions.shape[1] != ACT_DIM_HPT:
        raise RuntimeError(
            f"Unexpected support shape: observations={observations.shape}, actions={actions.shape}"
        )

    out = args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        out,
        observations=observations.astype(np.float32),
        actions=actions.astype(np.float32),
    )
    metadata = {
        "schema": "hpt-family-support-dataset-v1",
        "created_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "git_head": git_head(),
        "dataset": str(out),
        "seed_pass_manifest": str(seed_manifest),
        "seed_pass_manifest_sha256": sha256_file(seed_manifest),
        "trajectory_sweeps": sweep_metadata,
        "seed_anchor_samples": int(seed_obs.shape[0]),
        "trajectory_anchor_samples": int(traj_obs.shape[0]),
        "total_anchor_samples": int(observations.shape[0]),
        "action_mean": actions.mean(axis=0).astype(float).tolist(),
        "action_min": actions.min(axis=0).astype(float).tolist(),
        "action_max": actions.max(axis=0).astype(float).tolist(),
        "accepted_trajectory_rows": accepted_traj,
        "config": {
            "seed": int(args.seed),
            "seed_episodes_per_row": int(args.seed_episodes_per_row),
            "seed_noise_std": float(args.seed_noise_std),
            "trajectory_episodes_per_row": int(args.trajectory_episodes_per_row),
            "fault_pu": float(args.fault_pu),
            "duration_s": float(args.duration_s),
            "fault_start_s": float(args.fault_start_s),
            "fault_stop_margin_s": float(args.fault_stop_margin_s),
            "reg_q_limit": float(args.reg_q_limit),
        },
    }
    out.with_suffix(".json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    main()
