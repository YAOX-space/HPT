"""Roll out an HPT SAC actor into a trajectory MAT file for Simulink validation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from stable_baselines3 import SAC

from sac.datasets.build_hpt_action_trajectory import write_csv, write_mat
from sac.hpt_voltage_sac_env import (
    HPTVoltageEnvConfig,
    HPTVoltageSACEnv,
    HPTVoltageScenario,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--topology", choices=["topology1", "topology2"], default="topology2")
    parser.add_argument("--category", choices=["LVRT", "HVRT"], default="LVRT")
    parser.add_argument("--phase-key", default="a")
    parser.add_argument("--fault-pu", type=float, required=True)
    parser.add_argument("--duration-s", type=float, required=True)
    parser.add_argument("--fault-start-s", type=float, default=0.04)
    parser.add_argument("--fault-stop-margin-s", type=float, default=0.125)
    parser.add_argument("--dt", type=float, default=2e-3)
    parser.add_argument("--reg-d-limit", type=float, default=0.80)
    parser.add_argument("--reg-q-limit", type=float, default=0.40)
    parser.add_argument("--energy-d-limit", type=float, default=0.95)
    parser.add_argument("--energy-q-limit", type=float, default=0.95)
    parser.add_argument("--hybrid-dc-model", type=Path, default=None)
    parser.add_argument("--hybrid-dc-fault-pu-max", type=float, default=0.85)
    parser.add_argument("--hybrid-dc-duration-ms-min", type=float, default=100.0)
    parser.add_argument("--hybrid-dc-duration-ms-max", type=float, default=180.0)
    parser.add_argument("--slow-state-correction", type=Path, default=None)
    parser.add_argument("--slow-state-correction-fault-pu-max", type=float, default=0.85)
    parser.add_argument("--slow-state-correction-duration-ms-min", type=float, default=100.0)
    parser.add_argument("--slow-state-correction-duration-ms-max", type=float, default=180.0)
    parser.add_argument("--write-csv", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    stop_time = float(args.fault_start_s) + float(args.duration_s) + float(args.fault_stop_margin_s)
    scenario = HPTVoltageScenario(
        topology=str(args.topology),
        grid_pu=float(args.fault_pu),
        duration_s=stop_time,
        category=str(args.category),
        fault_type="1ph_g" if str(args.phase_key).lower() in {"a", "b", "c"} else "sym3ph",
        fault_phase_key=str(args.phase_key),
        fault_start_s=float(args.fault_start_s),
        fault_duration_s=float(args.duration_s),
    )
    config = HPTVoltageEnvConfig(
        dt=float(args.dt),
        reg_d_limit=float(args.reg_d_limit),
        reg_q_limit=float(args.reg_q_limit),
        energy_d_limit=float(args.energy_d_limit),
        energy_q_limit=float(args.energy_q_limit),
        use_switch_calibration=False,
        calibration_path="",
        hybrid_dc_channel_enable=bool(args.hybrid_dc_model),
        hybrid_dc_model_path=str(args.hybrid_dc_model.resolve()) if args.hybrid_dc_model else "",
        hybrid_dc_fault_pu_max=float(args.hybrid_dc_fault_pu_max),
        hybrid_dc_duration_ms_min=float(args.hybrid_dc_duration_ms_min),
        hybrid_dc_duration_ms_max=float(args.hybrid_dc_duration_ms_max),
        slow_state_correction_enable=bool(args.slow_state_correction),
        slow_state_correction_path=(
            str(args.slow_state_correction.resolve()) if args.slow_state_correction else ""
        ),
        slow_state_correction_fault_pu_max=float(args.slow_state_correction_fault_pu_max),
        slow_state_correction_duration_ms_min=float(args.slow_state_correction_duration_ms_min),
        slow_state_correction_duration_ms_max=float(args.slow_state_correction_duration_ms_max),
    )
    model = SAC.load(str(args.model), device="cpu")
    env = HPTVoltageSACEnv([scenario], config=config, train_mode=False)
    obs, _ = env.reset()

    t_rows: list[float] = []
    action_rows: list[np.ndarray] = []
    source_counts: dict[str, int] = {}
    done = False
    while not done:
        action, _ = model.predict(obs, deterministic=True)
        t_rows.append(float(env.t))
        action_rows.append(np.asarray(action, dtype=float).reshape(4))
        obs, _, terminated, truncated, info = env.step(action)
        source = str(info.get("hybrid_dc_channel_source", "unknown"))
        source_counts[source] = source_counts.get(source, 0) + 1
        done = bool(terminated or truncated)

    t = np.asarray(t_rows, dtype=float).reshape(-1, 1)
    action = np.asarray(action_rows, dtype=float)
    write_mat(args.out, t, action)
    csv_path = None
    if args.write_csv:
        csv_path = args.out.with_suffix(".csv")
        write_csv(csv_path, t, action)
    manifest = {
        "schema": "hpt-sac-actor-trajectory-v1",
        "model": str(args.model),
        "mat_file": str(args.out),
        "csv_file": str(csv_path) if csv_path else None,
        "n_points": int(t.shape[0]),
        "dt": float(args.dt),
        "stop_time": stop_time,
        "scenario": {
            "topology": args.topology,
            "category": args.category,
            "phase_key": args.phase_key,
            "fault_pu": float(args.fault_pu),
            "duration_s": float(args.duration_s),
            "fault_start_s": float(args.fault_start_s),
            "fault_stop_margin_s": float(args.fault_stop_margin_s),
        },
        "hybrid_dc_model": str(args.hybrid_dc_model.resolve()) if args.hybrid_dc_model else None,
        "slow_state_correction": (
            str(args.slow_state_correction.resolve()) if args.slow_state_correction else None
        ),
        "hybrid_dc_source_counts": dict(sorted(source_counts.items())),
        "action_min": action.min(axis=0).tolist(),
        "action_max": action.max(axis=0).tolist(),
        "action_mean": action.mean(axis=0).tolist(),
    }
    manifest_path = args.out.with_suffix(".json")
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
