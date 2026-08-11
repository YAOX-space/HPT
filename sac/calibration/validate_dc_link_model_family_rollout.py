"""Validate a deployable DC-link channel over a fault-family transition table."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ..hybrid_dc_channel import DCChannelInputs, HybridDCLinkChannel


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATASET = (
    ROOT
    / "experts"
    / "topology2_single_phase_lvrt"
    / "proxy"
    / "proxy_ode_v5_blockwise_pilot"
    / "proxy_v5_boundary_weighted_transitions.csv"
)
DEFAULT_OUT_DIR = (
    ROOT
    / "experts"
    / "topology2_single_phase_lvrt"
    / "proxy"
    / "proxy_ode_v6_delta_dc_pilot"
)


def metric(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    err = y_pred - y_true
    return {
        "rmse": float(np.sqrt(np.mean(err * err))),
        "mae": float(np.mean(np.abs(err))),
        "max_abs": float(np.max(np.abs(err))),
        "bias": float(np.mean(err)),
    }


def rollout_case(case: pd.DataFrame, channel: HybridDCLinkChannel) -> pd.DataFrame:
    rows: list[dict[str, float | str]] = []
    vdc = float(case.iloc[0]["vdc"])
    for _, raw in case.iterrows():
        sample = DCChannelInputs(
            vdc=vdc,
            grid_cmd=float(raw.get("grid_cmd", 1.0)),
            grid_v_mag=float(raw.get("grid_v_mag", 1.0)),
            energy_v_mag=float(raw.get("energy_v_mag", 1.0)),
            fault_flag=float(raw.get("fault_flag", 0.0)),
            recovery_flag=float(raw.get("recovery_flag", 0.0)),
            time_in_fault=float(raw.get("time_in_fault", 0.0)),
            time_in_recovery=float(raw.get("time_in_recovery", 0.0)),
            m_reg_d=float(raw.get("m_reg_d", 0.0)),
            m_reg_q=float(raw.get("m_reg_q", 0.0)),
            m_energy_d=float(raw.get("m_energy_d", 0.0)),
            m_energy_q=float(raw.get("m_energy_q", 0.0)),
            grid_i_d=float(raw.get("grid_i_d", 0.0)),
            grid_i_q=float(raw.get("grid_i_q", 0.0)),
            energy_i_d=float(raw.get("energy_i_d", 0.0)),
            energy_i_q=float(raw.get("energy_i_q", 0.0)),
            dt=float(raw.get("dt", 0.002)),
            fault_pu=float(raw.get("fault_pu", 1.0)),
            duration_ms=float(raw.get("duration_ms", 0.0)),
        )
        next_vdc = channel.predict_next_vdc(sample)
        rows.append(
            {
                "case_name": str(raw.get("case_name", "")),
                "fault_pu": float(raw.get("fault_pu", np.nan)),
                "duration_ms": float(raw.get("duration_ms", np.nan)),
                "t_ms": float(raw.get("t_ms", np.nan)),
                "zone": str(raw.get("zone", "")),
                "sim_vdc": float(raw["vdc"]),
                "proxy_vdc": float(vdc),
                "source": "model" if next_vdc is not None else "outside_gate",
            }
        )
        if next_vdc is None:
            next_vdc = float(raw["next_vdc"])
        vdc = float(next_vdc)
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--fault-pu-max", type=float, default=0.85)
    parser.add_argument("--duration-ms-min", type=float, default=100.0)
    parser.add_argument("--duration-ms-max", type=float, default=180.0)
    args = parser.parse_args()

    data = pd.read_csv(args.dataset)
    channel = HybridDCLinkChannel(
        args.model,
        fault_pu_max=args.fault_pu_max,
        duration_ms_min=args.duration_ms_min,
        duration_ms_max=args.duration_ms_max,
    )
    args.out_dir.mkdir(parents=True, exist_ok=True)

    case_frames: list[pd.DataFrame] = []
    rows: list[dict[str, object]] = []
    for case_name, case in data.groupby("case_name", sort=True):
        case = case.sort_values("t").reset_index(drop=True)
        comp = rollout_case(case, channel)
        case_frames.append(comp)
        active = comp.loc[comp["source"].eq("model")]
        if active.empty:
            continue
        metrics = metric(
            active["sim_vdc"].to_numpy(dtype=float),
            active["proxy_vdc"].to_numpy(dtype=float),
        )
        by_zone = {
            str(zone): metric(
                zone_df["sim_vdc"].to_numpy(dtype=float),
                zone_df["proxy_vdc"].to_numpy(dtype=float),
            )
            for zone, zone_df in active.groupby("zone")
        }
        rows.append(
            {
                "case_name": str(case_name),
                "fault_pu": float(case["fault_pu"].iloc[0]),
                "duration_ms": float(case["duration_ms"].iloc[0]),
                "rows": int(len(active)),
                **metrics,
                "zone_metrics": json.dumps(by_zone, sort_keys=True),
            }
        )

    comparison = pd.concat(case_frames, ignore_index=True)
    table = pd.DataFrame(rows).sort_values(["fault_pu", "duration_ms", "case_name"])
    out_comp = args.out_dir / "dc_link_family_rollout_comparison.csv"
    out_csv = args.out_dir / "dc_link_family_rollout_summary.csv"
    out_json = args.out_dir / "dc_link_family_rollout_summary.json"
    comparison.to_csv(out_comp, index=False)
    table.to_csv(out_csv, index=False)
    summary = {
        "schema": "hpt-dc-link-family-rollout-validation-v1",
        "dataset": str(args.dataset),
        "model": str(args.model),
        "gate": {
            "fault_pu_max": float(args.fault_pu_max),
            "duration_ms_min": float(args.duration_ms_min),
            "duration_ms_max": float(args.duration_ms_max),
        },
        "n_cases": int(len(table)),
        "summary_csv": str(out_csv),
        "comparison_csv": str(out_comp),
        "overall": metric(
            comparison.loc[comparison["source"].eq("model"), "sim_vdc"].to_numpy(dtype=float),
            comparison.loc[comparison["source"].eq("model"), "proxy_vdc"].to_numpy(dtype=float),
        )
        if not comparison.loc[comparison["source"].eq("model")].empty
        else {},
        "worst_case_rmse": (
            table.sort_values("rmse", ascending=False).head(1).to_dict("records")[0]
            if not table.empty
            else {}
        ),
    }
    out_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
