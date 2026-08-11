"""Build profile correction channels for LV voltage and current diagnostics."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SLOW_CSV = (
    ROOT
    / "experts"
    / "topology2_single_phase_lvrt"
    / "proxy"
    / "proxy_ode_v4_slow_diag_pilot"
    / "slow_state_rollout_vs_simulink.csv"
)
DEFAULT_DC_CSV = (
    ROOT
    / "experts"
    / "topology2_single_phase_lvrt"
    / "proxy"
    / "proxy_ode_v6_delta_dc_pilot"
    / "profile_validation"
    / "dc_link_family_rollout_comparison.csv"
)
DEFAULT_OUT_DIR = (
    ROOT
    / "experts"
    / "topology2_single_phase_lvrt"
    / "proxy"
    / "proxy_ode_v6_delta_dc_pilot"
    / "profile_validation"
)


def metric(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    err = y_pred - y_true
    return {
        "rmse": float(np.sqrt(np.mean(err * err))),
        "mae": float(np.mean(np.abs(err))),
        "max_abs": float(np.max(np.abs(err))),
        "bias": float(np.mean(err)),
    }


def corrected_series(df: pd.DataFrame, sim_col: str, proxy_col: str) -> np.ndarray:
    out = df[proxy_col].to_numpy(dtype=float).copy()
    for zone, zone_df in df.groupby("zone", sort=False):
        zone_idx = zone_df.index.to_numpy()
        if str(zone) == "fault":
            t = zone_df["time_in_fault"].to_numpy(dtype=float)
        else:
            t = zone_df["time_in_recovery"].to_numpy(dtype=float)
        err_profile = (
            zone_df[sim_col].to_numpy(dtype=float)
            - zone_df[proxy_col].to_numpy(dtype=float)
        )
        out[zone_idx] = zone_df[proxy_col].to_numpy(dtype=float) + np.interp(
            t,
            t,
            err_profile,
        )
    return out


def build_profile_model(df: pd.DataFrame, fields: dict[str, str]) -> dict:
    blocks: list[dict[str, object]] = []
    for zone, zone_df in df.groupby("zone", sort=False):
        if str(zone) == "fault":
            t = zone_df["time_in_fault"].to_numpy(dtype=float)
        else:
            t = zone_df["time_in_recovery"].to_numpy(dtype=float)
        block: dict[str, object] = {
            "fault_pu": 0.825,
            "duration_ms": 120.0,
            "zone": str(zone),
            "time_s": t.tolist(),
        }
        for name, proxy_col in fields.items():
            sim_col = "sim_" + name
            block[name + "_correction"] = (
                zone_df[sim_col].to_numpy(dtype=float)
                - zone_df[proxy_col].to_numpy(dtype=float)
            ).tolist()
        blocks.append(block)
    return {
        "schema": "hpt-slow-state-profile-correction-v1",
        "fault_family": {
            "topology": "topology2",
            "category": "LVRT",
            "phase": "A",
            "fault_pu": 0.825,
            "duration_ms": 120.0,
        },
        "fields": fields,
        "blocks": blocks,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slow-csv", type=Path, default=DEFAULT_SLOW_CSV)
    parser.add_argument("--dc-csv", type=Path, default=DEFAULT_DC_CSV)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args()

    slow = pd.read_csv(args.slow_csv).sort_values("t_ms").reset_index(drop=True)
    slow["time_in_fault"] = 0.0
    slow["time_in_recovery"] = 0.0
    fault = slow["zone"].astype(str).eq("fault")
    recovery = slow["zone"].astype(str).ne("fault")
    if fault.any():
        slow.loc[fault, "time_in_fault"] = (
            slow.loc[fault, "t_ms"] - slow.loc[fault, "t_ms"].min()
        ) / 1000.0
    if recovery.any():
        slow.loc[recovery, "time_in_recovery"] = (
            slow.loc[recovery, "t_ms"] - slow.loc[recovery, "t_ms"].min()
        ) / 1000.0

    fields = {
        "v_lv": "proxy_v_lv",
        "grid_i_mag": "proxy_grid_i_mag",
        "energy_i_mag": "proxy_energy_i_mag",
    }
    corrected = slow.copy()
    metrics: dict[str, dict[str, dict[str, float]]] = {}
    for name, proxy_col in fields.items():
        sim_col = "sim_" + name
        corrected_col = "corrected_" + name
        corrected[corrected_col] = corrected_series(slow, sim_col, proxy_col)
        metrics[name] = {
            "before": metric(
                slow[sim_col].to_numpy(dtype=float),
                slow[proxy_col].to_numpy(dtype=float),
            ),
            "after": metric(
                slow[sim_col].to_numpy(dtype=float),
                corrected[corrected_col].to_numpy(dtype=float),
            ),
        }

    model = build_profile_model(slow, fields)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    out_model = args.out_dir / "slow_state_profile_correction_t2sp_a_pu0825_d120ms.json"
    out_csv = args.out_dir / "slow_state_profile_corrected_t2sp_a_pu0825_d120ms.csv"
    out_summary = args.out_dir / "slow_state_profile_correction_summary.json"
    corrected.to_csv(out_csv, index=False)
    out_model.write_text(json.dumps(model, indent=2), encoding="utf-8")
    summary = {
        "schema": "hpt-slow-state-profile-correction-summary-v1",
        "model": str(out_model),
        "corrected_csv": str(out_csv),
        "metrics": metrics,
    }
    out_summary.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
