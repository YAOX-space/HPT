"""Build a boundary-weighted timestep transition dataset for HPT proxy fitting.

The input is a directory of switch-level Simulink trajectory CSV files.  The
output is a row-per-control-step transition table with explicit weights for
boundary cases and recovery windows.  The table is intended for the v5 proxy
calibration scripts.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_TRACE_DIR = (
    ROOT
    / "experts"
    / "topology2_single_phase_lvrt"
    / "data"
    / "proxy2_transition"
    / "p2_t2sp_a12_ode_v3_measure_20260804"
    / "raw_traces"
)
DEFAULT_OUT_DIR = (
    ROOT
    / "experts"
    / "topology2_single_phase_lvrt"
    / "proxy"
    / "proxy_ode_v5_blockwise_pilot"
)

STATE_COLS = [
    "v_lv",
    "vdc",
    "grid_i_d",
    "grid_i_q",
    "energy_i_d",
    "energy_i_q",
]
ACTION_COLS = ["m_reg_d", "m_reg_q", "m_energy_d", "m_energy_q"]
ENV_COLS = [
    "grid_cmd",
    "grid_v_mag",
    "energy_v_mag",
    "fault_flag",
    "recovery_flag",
    "time_in_fault",
    "time_in_recovery",
]
DIAG_COLS = ["reg_i_mag", "hbc_cap_v_mag", "series_inj_v_mag", "idc_cap_500a_pu"]


def parse_case(path: Path) -> tuple[float, int]:
    text = path.stem.lower()
    pu_match = re.search(r"pu(\d{4})", text)
    if pu_match is None:
        pu_match = re.search(r"(?:^|[_-])(?:a|b|c|ab|bc|ca)(\d{4})(?:d|[_-])", text)
    if pu_match is None:
        pu_match = re.search(r"(?:a|b|c|ab|bc|ca)(\d{4})d\d{3}", text)
    dur_match = re.search(r"d(\d{3})ms", text)
    if dur_match is None:
        dur_match = re.search(r"d(\d{3})(?:[_-]|$)", text)
    fault_pu = float(pu_match.group(1)) / 1000.0 if pu_match else float("nan")
    duration_ms = int(dur_match.group(1)) if dur_match else -1
    return fault_pu, duration_ms


def load_trace(path: Path, *, startup_skip_s: float) -> pd.DataFrame:
    df = pd.read_csv(path)
    required = [
        "t",
        "window_zone",
        "lv_v_mag_pu_inst",
        "vdc_pu_inst",
        "grid_cmd_v_mag_pu_inst",
        "grid_v_mag_pu_inst",
        "grid_i_d_pu_inst",
        "grid_i_q_pu_inst",
        "energy_v_mag_pu_inst",
        "energy_i_d_pu_inst",
        "energy_i_q_pu_inst",
        "reg_i_d_pu_inst",
        "reg_i_q_pu_inst",
        "hbc_cap_v_mag_pu_inst",
        "series_inj_v_mag_pu_inst",
        "idc_cap_inst",
        "cmd_action_01",
        "cmd_action_02",
        "cmd_action_03",
        "cmd_action_04",
    ]
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise KeyError(f"{path} is missing columns: {missing}")

    for col in required:
        if col != "window_zone":
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=required).sort_values("t")
    df = df[df["t"] >= startup_skip_s].reset_index(drop=True)
    if len(df) < 4:
        raise ValueError(f"Not enough rows after startup skip: {path}")

    fault_pu, duration_ms = parse_case(path)
    out = pd.DataFrame(index=df.index)
    out["trace_source"] = str(path)
    out["case_name"] = path.stem
    out["fault_pu"] = fault_pu
    out["duration_ms"] = duration_ms
    out["t"] = df["t"].astype(float)
    out["t_ms"] = out["t"] * 1000.0
    out["zone"] = df["window_zone"].astype(str)
    out["fault_flag"] = (out["zone"] == "fault").astype(float)
    out["recovery_flag"] = (out["zone"] == "recovery").astype(float)
    fault_rows = out["zone"] == "fault"
    fault_start = float(out.loc[fault_rows, "t"].min()) if fault_rows.any() else 0.035
    out["time_in_fault"] = np.where(fault_rows, np.maximum(0.0, out["t"] - fault_start), 0.0)
    recovery_rows = out["zone"] == "recovery"
    if recovery_rows.any():
        recovery_start = float(out.loc[recovery_rows, "t"].min())
        out["time_in_recovery"] = np.where(recovery_rows, out["t"] - recovery_start, 0.0)
    else:
        out["time_in_recovery"] = 0.0
    out["grid_cmd"] = df["grid_cmd_v_mag_pu_inst"].astype(float)
    out["grid_v_mag"] = df["grid_v_mag_pu_inst"].astype(float)
    out["energy_v_mag"] = df["energy_v_mag_pu_inst"].astype(float)
    out["v_lv"] = df["lv_v_mag_pu_inst"].astype(float)
    out["vdc"] = df["vdc_pu_inst"].astype(float)
    out["grid_i_d"] = df["grid_i_d_pu_inst"].astype(float)
    out["grid_i_q"] = df["grid_i_q_pu_inst"].astype(float)
    out["energy_i_d"] = df["energy_i_d_pu_inst"].astype(float)
    out["energy_i_q"] = df["energy_i_q_pu_inst"].astype(float)
    out["reg_i_mag"] = np.hypot(
        df["reg_i_d_pu_inst"].astype(float),
        df["reg_i_q_pu_inst"].astype(float),
    )
    out["hbc_cap_v_mag"] = df["hbc_cap_v_mag_pu_inst"].astype(float)
    out["series_inj_v_mag"] = df["series_inj_v_mag_pu_inst"].astype(float)
    out["idc_cap_500a_pu"] = df["idc_cap_inst"].astype(float) / 500.0
    out["m_reg_d"] = df["cmd_action_01"].astype(float)
    out["m_reg_q"] = df["cmd_action_02"].astype(float)
    out["m_energy_d"] = df["cmd_action_03"].astype(float)
    out["m_energy_q"] = df["cmd_action_04"].astype(float)
    return out.replace([np.inf, -np.inf], np.nan).dropna().reset_index(drop=True)


def transition_weight(row: pd.Series) -> float:
    fault_pu = float(row["fault_pu"])
    duration_ms = float(row["duration_ms"])
    zone = str(row["zone"])
    weight = 1.0

    if 0.80 <= fault_pu <= 0.875 and 200 <= duration_ms <= 240:
        weight *= 5.0
    elif 0.80 <= fault_pu <= 0.875 and 100 <= duration_ms <= 160:
        weight *= 4.0
    elif 0.80 <= fault_pu <= 0.90 and 80 <= duration_ms <= 180:
        weight *= 2.0

    if zone == "recovery":
        weight *= 3.0
    elif zone == "fault":
        weight *= 1.4

    if abs(float(row["next_vdc"]) - float(row["vdc"])) > 0.015:
        weight *= 1.5

    return float(weight)


def build_transitions(traces: list[pd.DataFrame]) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    for trace in traces:
        cur = trace.iloc[:-1].copy().reset_index(drop=True)
        nxt = trace.iloc[1:].copy().reset_index(drop=True)
        trans = cur[
            [
                "trace_source",
                "case_name",
                "fault_pu",
                "duration_ms",
                "t",
                "t_ms",
                "zone",
                *STATE_COLS,
                *ACTION_COLS,
                *ENV_COLS,
                *DIAG_COLS,
            ]
        ].copy()
        trans["next_zone"] = nxt["zone"].to_numpy()
        trans["dt"] = (nxt["t"].to_numpy(dtype=float) - cur["t"].to_numpy(dtype=float)).astype(float)
        for col in STATE_COLS:
            trans[f"next_{col}"] = nxt[col].to_numpy(dtype=float)
            trans[f"delta_{col}"] = trans[f"next_{col}"] - trans[col]
            trans[f"d{col}_dt"] = trans[f"delta_{col}"] / trans["dt"].clip(lower=1e-9)
        trans["grid_i_mag"] = np.hypot(trans["grid_i_d"], trans["grid_i_q"])
        trans["energy_i_mag"] = np.hypot(trans["energy_i_d"], trans["energy_i_q"])
        trans["reg_action_mag"] = np.hypot(trans["m_reg_d"], trans["m_reg_q"])
        trans["energy_action_mag"] = np.hypot(trans["m_energy_d"], trans["m_energy_q"])
        trans["proxy_weight"] = trans.apply(transition_weight, axis=1)
        rows.append(trans[trans["dt"] > 0])

    if not rows:
        raise RuntimeError("No transition rows were built.")
    return pd.concat(rows, ignore_index=True).replace([np.inf, -np.inf], np.nan).dropna()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace-dir", type=Path, default=DEFAULT_TRACE_DIR)
    parser.add_argument(
        "--extra-trace-dir",
        type=Path,
        action="append",
        default=[],
        help="Additional raw trace directories to merge into the transition table.",
    )
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--startup-skip-s", type=float, default=0.040)
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    trace_dirs = [args.trace_dir, *args.extra_trace_dir]
    paths: list[Path] = []
    for trace_dir in trace_dirs:
        paths.extend(sorted(trace_dir.glob("trajectory_trace_*.csv")))
    paths = sorted(dict.fromkeys(paths))
    if not paths:
        raise FileNotFoundError(f"No trace CSV files in {trace_dirs}")
    traces = [load_trace(path, startup_skip_s=args.startup_skip_s) for path in paths]
    transitions = build_transitions(traces)

    out_csv = args.out_dir / "proxy_v5_boundary_weighted_transitions.csv"
    out_json = args.out_dir / "proxy_v5_boundary_weighted_dataset_summary.json"
    transitions.to_csv(out_csv, index=False)

    summary = {
        "schema": "hpt-proxy-v5-boundary-weighted-transitions",
        "trace_dirs": [str(path) for path in trace_dirs],
        "out_csv": str(out_csv),
        "startup_skip_s": float(args.startup_skip_s),
        "n_traces": len(paths),
        "n_transition_rows": int(len(transitions)),
        "state_cols": STATE_COLS,
        "action_cols": ACTION_COLS,
        "env_cols": ENV_COLS,
        "diagnostics_cols": DIAG_COLS,
        "weight_rule": {
            "long_duration_boundary": "5x for 0.80--0.875 pu and 200--240 ms",
            "primary_boundary": "4x for 0.80--0.875 pu and 100--160 ms",
            "secondary_boundary": "2x for 0.80--0.90 pu and 80--180 ms",
            "recovery_window": "3x",
            "fault_window": "1.4x",
            "large_vdc_step": "1.5x if |next_vdc-vdc| > 0.015 pu",
        },
        "weight_stats": {
            "min": float(transitions["proxy_weight"].min()),
            "mean": float(transitions["proxy_weight"].mean()),
            "max": float(transitions["proxy_weight"].max()),
        },
        "cases": sorted(transitions["case_name"].unique().tolist()),
    }
    out_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
