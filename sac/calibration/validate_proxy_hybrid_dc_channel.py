"""Validate a hybrid DC-link channel for the HPT slow-state proxy.

The hybrid keeps the stable v4 slow-state proxy globally, but allows a v5
DC-link energy/correction channel inside a configurable boundary region.  This
script evaluates the channel-selection rule on tracked holdout rollouts.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
PROXY_ROOT = ROOT / "experts" / "topology2_single_phase_lvrt" / "proxy"
DEFAULT_OUT_DIR = PROXY_ROOT / "proxy_ode_v5_blockwise_pilot"

CASES = {
    "pu0825_d120ms": {
        "v4_summary": PROXY_ROOT / "proxy_ode_v4_slow_diag_pilot" / "summary.json",
        "v5_summary": DEFAULT_OUT_DIR / "dc_link_energy_model_pu0825_d120ms_summary.json",
    },
    "pu0875_d100ms": {
        "v4_summary": PROXY_ROOT / "proxy_ode_v4_slow_diag_pilot_holdout_0875_100" / "summary.json",
        "v5_summary": DEFAULT_OUT_DIR / "dc_link_energy_model_pu0875_d100ms_summary.json",
    },
    "pu0925_d060ms": {
        "v4_summary": PROXY_ROOT / "proxy_ode_v4_slow_diag_pilot_holdout_0925_060" / "summary.json",
        "v5_summary": DEFAULT_OUT_DIR / "dc_link_energy_model_pu0925_d060ms_summary.json",
    },
}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_holdout_key(key: str) -> tuple[float, int]:
    pu_match = re.search(r"pu(\d{4})", key)
    dur_match = re.search(r"d(\d{3})ms", key)
    if pu_match is None or dur_match is None:
        raise ValueError(f"Cannot parse holdout key: {key}")
    return float(pu_match.group(1)) / 1000.0, int(dur_match.group(1))


def metric(y_true: pd.Series, y_pred: pd.Series) -> dict[str, float]:
    err = y_pred.to_numpy(dtype=float) - y_true.to_numpy(dtype=float)
    return {
        "rmse": float(np.sqrt(np.mean(err * err))),
        "mae": float(np.mean(np.abs(err))),
        "max_abs": float(np.max(np.abs(err))),
    }


def use_v5_boundary_channel(
    fault_pu: float,
    duration_ms: int,
    *,
    pu_max: float,
    duration_min_ms: int,
    duration_max_ms: int,
) -> bool:
    return fault_pu <= pu_max and duration_min_ms <= duration_ms <= duration_max_ms


def evaluate_case(
    holdout: str,
    paths: dict[str, Path],
    *,
    out_dir: Path,
    pu_max: float,
    duration_min_ms: int,
    duration_max_ms: int,
) -> dict[str, object]:
    fault_pu, duration_ms = parse_holdout_key(holdout)
    v4_summary = load_json(paths["v4_summary"])
    v5_summary = load_json(paths["v5_summary"])
    v4_csv = Path(v4_summary["artifacts"]["comparison_csv"])
    v5_csv = Path(v5_summary["artifacts"]["comparison_csv"])
    v4_raw = pd.read_csv(v4_csv)
    v5_raw = pd.read_csv(v5_csv)
    v4_raw["t_key"] = v4_raw["t_ms"].round(9)
    v5_raw["t_key"] = v5_raw["t_ms"].round(9)
    v4 = v4_raw.merge(
        v5_raw[["t_key", "proxy_vdc"]].rename(columns={"proxy_vdc": "v5_proxy_vdc"}),
        on="t_key",
        how="inner",
        validate="one_to_one",
    )
    if v4.empty:
        raise ValueError(f"No aligned timesteps for {holdout}")

    choose_v5 = use_v5_boundary_channel(
        fault_pu,
        duration_ms,
        pu_max=pu_max,
        duration_min_ms=duration_min_ms,
        duration_max_ms=duration_max_ms,
    )
    hybrid = v4.copy()
    hybrid["v4_proxy_vdc"] = v4["proxy_vdc"].astype(float)
    hybrid["v5_proxy_vdc"] = v4["v5_proxy_vdc"].astype(float)
    hybrid["hybrid_proxy_vdc"] = hybrid["v5_proxy_vdc"] if choose_v5 else hybrid["v4_proxy_vdc"]
    hybrid["hybrid_dc_source"] = "v5_boundary_dc" if choose_v5 else "v4_slow_state_dc"
    out_csv = out_dir / f"hybrid_dc_{holdout}_rollout.csv"
    hybrid.to_csv(out_csv, index=False)

    v4_metrics = metric(hybrid["sim_vdc"], hybrid["v4_proxy_vdc"])
    v5_metrics = metric(hybrid["sim_vdc"], hybrid["v5_proxy_vdc"])
    hybrid_metrics = metric(hybrid["sim_vdc"], hybrid["hybrid_proxy_vdc"])
    return {
        "holdout": holdout,
        "fault_pu": fault_pu,
        "duration_ms": duration_ms,
        "hybrid_dc_source": "v5_boundary_dc" if choose_v5 else "v4_slow_state_dc",
        "v4_vdc_rmse": v4_metrics["rmse"],
        "v5_vdc_rmse": v5_metrics["rmse"],
        "hybrid_vdc_rmse": hybrid_metrics["rmse"],
        "hybrid_beats_v4": bool(hybrid_metrics["rmse"] < v4_metrics["rmse"]),
        "hybrid_not_worse_than_v4": bool(hybrid_metrics["rmse"] <= v4_metrics["rmse"]),
        "comparison_csv": str(out_csv),
        "aligned_rows": int(len(hybrid)),
        "v4_rows": int(len(v4_raw)),
        "v5_rows": int(len(v5_raw)),
        "v4_summary": str(paths["v4_summary"]),
        "v5_summary": str(paths["v5_summary"]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--boundary-pu-max", type=float, default=0.85)
    parser.add_argument("--boundary-duration-min-ms", type=int, default=100)
    parser.add_argument("--boundary-duration-max-ms", type=int, default=180)
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    rows = [
        evaluate_case(
            holdout,
            paths,
            out_dir=args.out_dir,
            pu_max=args.boundary_pu_max,
            duration_min_ms=args.boundary_duration_min_ms,
            duration_max_ms=args.boundary_duration_max_ms,
        )
        for holdout, paths in CASES.items()
    ]
    table = pd.DataFrame(rows)
    out_csv = args.out_dir / "proxy_hybrid_dc_validation_summary.csv"
    out_json = args.out_dir / "proxy_hybrid_dc_validation_summary.json"
    table.to_csv(out_csv, index=False)
    summary = {
        "schema": "hpt-proxy-hybrid-dc-validation-v1",
        "rule": {
            "use_v5_if": (
                f"fault_pu <= {args.boundary_pu_max} and "
                f"{args.boundary_duration_min_ms} <= duration_ms <= {args.boundary_duration_max_ms}"
            ),
            "otherwise": "use v4 slow-state DC channel",
        },
        "out_csv": str(out_csv),
        "rows": rows,
        "overall_not_worse_than_v4": bool(all(row["hybrid_not_worse_than_v4"] for row in rows)),
        "overall_beats_v4_somewhere": bool(any(row["hybrid_beats_v4"] for row in rows)),
        "decision": (
            "hybrid_dc_candidate_passes_tracked_holdouts"
            if all(row["hybrid_not_worse_than_v4"] for row in rows)
            else "hybrid_dc_candidate_not_ready"
        ),
    }
    out_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
