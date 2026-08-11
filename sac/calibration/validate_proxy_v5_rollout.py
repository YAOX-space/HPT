"""Validate v5 proxy repair candidates against existing v4 slow-state results.

This validator does not run SAC.  It compares the current stable v4 slow-state
rollout with the v5 DC-link energy/correction candidate and records whether the
candidate is good enough to replace the v4 DC-link channel.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
PROXY_ROOT = ROOT / "experts" / "topology2_single_phase_lvrt" / "proxy"
DEFAULT_OUT_DIR = PROXY_ROOT / "proxy_ode_v5_blockwise_pilot"

V4_CASES = {
    "pu0825_d120ms": PROXY_ROOT / "proxy_ode_v4_slow_diag_pilot" / "summary.json",
    "pu0875_d100ms": PROXY_ROOT / "proxy_ode_v4_slow_diag_pilot_holdout_0875_100" / "summary.json",
    "pu0925_d060ms": PROXY_ROOT / "proxy_ode_v4_slow_diag_pilot_holdout_0925_060" / "summary.json",
}


def dc_summary_path(out_dir: Path, holdout: str) -> Path:
    return out_dir / f"dc_link_energy_model_{holdout}_summary.json"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--promote-tolerance", type=float, default=0.95)
    args = parser.parse_args()

    rows: list[dict[str, object]] = []
    for holdout, v4_path in V4_CASES.items():
        if not v4_path.exists():
            rows.append({"holdout": holdout, "status": "missing_v4_summary", "v4_summary": str(v4_path)})
            continue
        dc_path = dc_summary_path(args.out_dir, holdout)
        if not dc_path.exists():
            rows.append({"holdout": holdout, "status": "missing_v5_dc_summary", "v5_summary": str(dc_path)})
            continue
        v4 = load_json(v4_path)
        dc = load_json(dc_path)
        v4_vdc_rmse = float(v4["metrics_holdout_free_rollout"]["vdc_pu"]["rmse"])
        dc_vdc_rmse = float(dc["free_rollout_vdc_metrics"]["rmse"])
        promoted = dc_vdc_rmse <= args.promote_tolerance * v4_vdc_rmse
        rows.append(
            {
                "holdout": holdout,
                "status": "ok",
                "v4_vdc_rmse": v4_vdc_rmse,
                "v5_dc_candidate_rmse": dc_vdc_rmse,
                "rmse_ratio_v5_over_v4": dc_vdc_rmse / max(v4_vdc_rmse, 1e-12),
                "promote_v5_dc_channel": bool(promoted),
                "decision": "promote" if promoted else "keep_v4_dc_channel_and_collect_more_boundary_data",
                "v4_summary": str(v4_path),
                "v5_summary": str(dc_path),
            }
        )

    args.out_dir.mkdir(parents=True, exist_ok=True)
    table = pd.DataFrame(rows)
    out_csv = args.out_dir / "proxy_v5_candidate_validation_summary.csv"
    out_json = args.out_dir / "proxy_v5_candidate_validation_summary.json"
    table.to_csv(out_csv, index=False)
    summary = {
        "schema": "hpt-proxy-v5-candidate-validation",
        "out_csv": str(out_csv),
        "promote_rule": "promote v5 DC only if its heldout Vdc RMSE is <= promote_tolerance * v4 Vdc RMSE",
        "promote_tolerance": float(args.promote_tolerance),
        "rows": rows,
        "overall_decision": (
            "promote_v5_dc_channel"
            if rows and all(row.get("promote_v5_dc_channel") is True for row in rows)
            else "do_not_promote_v5_dc_channel_yet"
        ),
    }
    out_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
