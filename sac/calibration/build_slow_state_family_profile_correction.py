"""Build family profile correction channels for slow-state proxy outputs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
ACTION_FEATURES = ["m_reg_d", "m_reg_q", "m_energy_d", "m_energy_q"]
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


def baseline_proxy(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    # Causal, simple baselines that match the scale and slow trend of the v4
    # proxy but are available for every collected family trace.
    out["proxy_v_lv"] = (
        out.groupby("case_name")["v_lv"]
        .transform(lambda s: s.ewm(alpha=0.18, adjust=False).mean())
        .to_numpy(dtype=float)
    )
    out["grid_i_mag"] = np.hypot(out["grid_i_d"], out["grid_i_q"])
    out["energy_i_mag"] = np.hypot(out["energy_i_d"], out["energy_i_q"])
    out["proxy_grid_i_mag"] = (
        out.groupby("case_name")["grid_i_mag"]
        .transform(lambda s: s.ewm(alpha=0.22, adjust=False).mean())
        .to_numpy(dtype=float)
    )
    out["proxy_energy_i_mag"] = (
        out.groupby("case_name")["energy_i_mag"]
        .transform(lambda s: s.ewm(alpha=0.22, adjust=False).mean())
        .to_numpy(dtype=float)
    )
    return out


def time_key(block: pd.DataFrame, zone: str) -> np.ndarray:
    if zone == "fault":
        return block["time_in_fault"].to_numpy(dtype=float)
    return block["time_in_recovery"].to_numpy(dtype=float)


def _add_action_profiles(item: dict[str, object], block: pd.DataFrame) -> None:
    for name in ACTION_FEATURES:
        if name in block:
            item[name + "_profile"] = block[name].to_numpy(dtype=float).tolist()


def build_model(df: pd.DataFrame, *, blend: float) -> dict:
    fields = {
        "v_lv": ("v_lv", "proxy_v_lv"),
        "grid_i_mag": ("grid_i_mag", "proxy_grid_i_mag"),
        "energy_i_mag": ("energy_i_mag", "proxy_energy_i_mag"),
    }
    blocks: list[dict[str, object]] = []
    for (fault_pu, duration_ms, zone), block in df.groupby(
        ["fault_pu", "duration_ms", "zone"], sort=True
    ):
        block = block.sort_values("t").copy()
        t = time_key(block, str(zone))
        item: dict[str, object] = {
            "fault_pu": float(fault_pu),
            "duration_ms": float(duration_ms),
            "zone": str(zone),
            "time_s": t.tolist(),
            "profile_blend": float(blend),
        }
        _add_action_profiles(item, block)
        for name, (sim_col, proxy_col) in fields.items():
            item[name + "_correction"] = (
                block[sim_col].to_numpy(dtype=float)
                - block[proxy_col].to_numpy(dtype=float)
            ).tolist()
        blocks.append(item)
    return {
        "schema": "hpt-slow-state-family-profile-correction-v2",
        "fault_family": {
            "topology": "topology2",
            "category": "LVRT",
            "phase": "A",
        },
        "fields": fields,
        "action_features": ACTION_FEATURES,
        "blocks": blocks,
    }


def nearest_average_model(train: pd.DataFrame, test: pd.DataFrame, *, blend: float) -> dict:
    fields = {
        "v_lv": ("v_lv", "proxy_v_lv"),
        "grid_i_mag": ("grid_i_mag", "proxy_grid_i_mag"),
        "energy_i_mag": ("energy_i_mag", "proxy_energy_i_mag"),
    }
    test_fault = float(test["fault_pu"].iloc[0])
    test_duration = float(test["duration_ms"].iloc[0])
    blocks: list[dict[str, object]] = []
    for zone, zone_test in test.groupby("zone", sort=False):
        zone_train = train.loc[train["zone"].astype(str).eq(str(zone))].copy()
        if zone_train.empty:
            continue
        zone_train["dist"] = (
            (zone_train["fault_pu"].astype(float) - test_fault).abs() / 0.025
            + (zone_train["duration_ms"].astype(float) - test_duration).abs() / 20.0
        )
        nearest = zone_train.loc[zone_train["dist"] <= zone_train["dist"].min() + 1e-9]
        t_test = time_key(zone_test, str(zone))
        item: dict[str, object] = {
            "fault_pu": test_fault,
            "duration_ms": test_duration,
            "zone": str(zone),
            "time_s": t_test.tolist(),
            "profile_blend": float(blend),
        }
        for action_name in ACTION_FEATURES:
            action_profiles = []
            for _, near_case in nearest.groupby("case_name"):
                near_case = near_case.sort_values("t")
                t_near = time_key(near_case, str(zone))
                action_profiles.append(
                    np.interp(t_test, t_near, near_case[action_name].to_numpy(dtype=float))
                )
            item[action_name + "_profile"] = np.mean(action_profiles, axis=0).tolist()
        for name, (sim_col, proxy_col) in fields.items():
            corr_samples = []
            for _, near_case in nearest.groupby("case_name"):
                near_case = near_case.sort_values("t")
                t_near = time_key(near_case, str(zone))
                corr = near_case[sim_col].to_numpy(dtype=float) - near_case[proxy_col].to_numpy(dtype=float)
                corr_samples.append(np.interp(t_test, t_near, corr))
            item[name + "_correction"] = np.mean(corr_samples, axis=0).tolist()
        blocks.append(item)
    return {
        "schema": "hpt-slow-state-family-profile-correction-v2",
        "fault_family": {"topology": "topology2", "category": "LVRT", "phase": "A"},
        "fields": fields,
        "action_features": ACTION_FEATURES,
        "blocks": blocks,
    }


def apply_model(df: pd.DataFrame, model: dict) -> pd.DataFrame:
    out = df.copy()
    blocks = model["blocks"]
    fields = model["fields"]
    action_features = list(model.get("action_features", ACTION_FEATURES))
    action_residual_gains = dict(model.get("action_residual_gains", {}))
    for name in fields:
        out["corrected_" + name] = out[fields[name][1]].to_numpy(dtype=float)
    for idx, row in out.iterrows():
        zone = str(row["zone"])
        candidates = [b for b in blocks if str(b["zone"]) == zone]
        if not candidates:
            candidates = blocks
        block = min(
            candidates,
            key=lambda b: abs(float(b["fault_pu"]) - float(row["fault_pu"])) / 0.025
            + abs(float(b["duration_ms"]) - float(row["duration_ms"])) / 20.0,
        )
        t = float(row["time_in_fault"] if zone == "fault" else row["time_in_recovery"])
        blend = float(block.get("profile_blend", 1.0))
        for name in fields:
            correction = float(
                np.interp(
                    t,
                    np.asarray(block["time_s"], dtype=float),
                    np.asarray(block[name + "_correction"], dtype=float),
                )
            )
            action_residual = 0.0
            gain_item = action_residual_gains.get(str(zone), {}).get(name)
            if gain_item:
                gains = np.asarray(gain_item.get("gains", []), dtype=float)
                if gains.size == len(action_features):
                    deltas = []
                    for feature in action_features:
                        profile = np.asarray(block.get(feature + "_profile", []), dtype=float)
                        if profile.size != len(block["time_s"]):
                            deltas = []
                            break
                        baseline = float(
                            np.interp(t, np.asarray(block["time_s"], dtype=float), profile)
                        )
                        deltas.append(float(row[feature]) - baseline)
                    if deltas:
                        action_residual = float(np.dot(gains, np.asarray(deltas, dtype=float)))
                        limit = float(gain_item.get("limit", 0.0))
                        if limit > 0.0:
                            action_residual = float(np.clip(action_residual, -limit, limit))
            out.at[idx, "corrected_" + name] = (
                float(row[fields[name][1]]) + blend * correction + action_residual
            )
    return out


def collect_action_residual_training_rows(
    df: pd.DataFrame,
    *,
    blend: float,
) -> pd.DataFrame:
    parts: list[pd.DataFrame] = []
    for case_name, test in df.groupby("case_name", sort=True):
        train = df.loc[df["case_name"].astype(str).ne(str(case_name))].copy()
        model = nearest_average_model(train, test.copy(), blend=blend)
        corrected = apply_model(test.copy(), model)
        blocks = model["blocks"]
        rows = []
        for _, row in corrected.iterrows():
            zone = str(row["zone"])
            candidates = [b for b in blocks if str(b["zone"]) == zone] or blocks
            block = min(
                candidates,
                key=lambda b: abs(float(b["fault_pu"]) - float(row["fault_pu"])) / 0.025
                + abs(float(b["duration_ms"]) - float(row["duration_ms"])) / 20.0,
            )
            t = float(row["time_in_fault"] if zone == "fault" else row["time_in_recovery"])
            time_s = np.asarray(block["time_s"], dtype=float)
            item = {"zone": zone}
            for action_name in ACTION_FEATURES:
                profile = np.asarray(block[action_name + "_profile"], dtype=float)
                baseline = float(np.interp(t, time_s, profile))
                item["delta_" + action_name] = float(row[action_name]) - baseline
            for name, (sim_col, _) in model["fields"].items():
                item["residual_" + name] = float(row[sim_col]) - float(row["corrected_" + name])
            rows.append(item)
        parts.append(pd.DataFrame(rows))
    if not parts:
        return pd.DataFrame()
    return pd.concat(parts, ignore_index=True)


def fit_action_residual_gains(
    residual_rows: pd.DataFrame,
    *,
    ridge: float,
    limits: dict[str, float],
) -> dict[str, dict[str, dict[str, object]]]:
    if residual_rows.empty:
        return {}
    gains: dict[str, dict[str, dict[str, object]]] = {}
    x_cols = ["delta_" + name for name in ACTION_FEATURES]
    for zone, block in residual_rows.groupby("zone", sort=True):
        x = block[x_cols].to_numpy(dtype=float)
        xtx = x.T @ x + float(ridge) * np.eye(len(x_cols))
        gains[str(zone)] = {}
        for name in ("v_lv", "grid_i_mag", "energy_i_mag"):
            y = block["residual_" + name].to_numpy(dtype=float)
            try:
                beta = np.linalg.solve(xtx, x.T @ y)
            except np.linalg.LinAlgError:
                beta = np.zeros(len(x_cols), dtype=float)
            gains[str(zone)][name] = {
                "features": ACTION_FEATURES,
                "gains": beta.tolist(),
                "limit": float(limits.get(name, 0.0)),
            }
    return gains


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--fault-pu-max", type=float, default=0.85)
    parser.add_argument("--duration-ms-min", type=float, default=100.0)
    parser.add_argument("--duration-ms-max", type=float, default=180.0)
    parser.add_argument("--blend", type=float, default=1.0)
    parser.add_argument("--leave-one-case-out", action="store_true")
    parser.add_argument("--action-aware", action="store_true")
    parser.add_argument("--action-ridge", type=float, default=1e-3)
    parser.add_argument("--v-lv-action-limit", type=float, default=0.035)
    parser.add_argument("--grid-i-action-limit", type=float, default=0.25)
    parser.add_argument("--energy-i-action-limit", type=float, default=0.20)
    args = parser.parse_args()

    raw = pd.read_csv(args.dataset)
    raw = raw[
        (raw["fault_pu"].astype(float) <= args.fault_pu_max)
        & (raw["duration_ms"].astype(float) >= args.duration_ms_min)
        & (raw["duration_ms"].astype(float) <= args.duration_ms_max)
    ].copy()
    df = baseline_proxy(raw).sort_values(["case_name", "t"]).reset_index(drop=True)
    fields = {
        "v_lv": ("v_lv", "proxy_v_lv"),
        "grid_i_mag": ("grid_i_mag", "proxy_grid_i_mag"),
        "energy_i_mag": ("energy_i_mag", "proxy_energy_i_mag"),
    }
    action_residual_rows = pd.DataFrame()
    action_residual_gains: dict[str, dict[str, dict[str, object]]] = {}
    if args.action_aware:
        action_residual_rows = collect_action_residual_training_rows(df, blend=args.blend)
        action_residual_gains = fit_action_residual_gains(
            action_residual_rows,
            ridge=float(args.action_ridge),
            limits={
                "v_lv": float(args.v_lv_action_limit),
                "grid_i_mag": float(args.grid_i_action_limit),
                "energy_i_mag": float(args.energy_i_action_limit),
            },
        )

    if args.leave_one_case_out:
        corrected_parts: list[pd.DataFrame] = []
        for case_name, test in df.groupby("case_name", sort=True):
            train = df.loc[df["case_name"].astype(str).ne(str(case_name))].copy()
            model = nearest_average_model(train, test.copy(), blend=args.blend)
            if args.action_aware:
                model["action_residual_gains"] = action_residual_gains
            corrected_parts.append(apply_model(test.copy(), model))
        corrected = pd.concat(corrected_parts, ignore_index=True)
        model = build_model(df, blend=args.blend)
    else:
        model = build_model(df, blend=args.blend)
        if args.action_aware:
            model["action_residual_gains"] = action_residual_gains
        corrected = apply_model(df, model)
    if args.action_aware:
        model["action_residual_gains"] = action_residual_gains

    metrics: dict[str, dict[str, dict[str, float]]] = {}
    for name, (sim_col, proxy_col) in fields.items():
        metrics[name] = {
            "before": metric(df[sim_col].to_numpy(dtype=float), df[proxy_col].to_numpy(dtype=float)),
            "after": metric(
                corrected[sim_col].to_numpy(dtype=float),
                corrected["corrected_" + name].to_numpy(dtype=float),
            ),
        }

    args.out_dir.mkdir(parents=True, exist_ok=True)
    out_model = args.out_dir / "slow_state_family_profile_correction_t2sp_a_lvrt.json"
    out_csv = args.out_dir / "slow_state_family_profile_corrected_t2sp_a_lvrt.csv"
    out_summary = args.out_dir / "slow_state_family_profile_correction_summary.json"
    out_model.write_text(json.dumps(model, indent=2), encoding="utf-8")
    corrected.to_csv(out_csv, index=False)
    summary = {
        "schema": "hpt-slow-state-family-profile-correction-summary-v1",
        "dataset": str(args.dataset),
        "rows": int(len(df)),
        "validation_mode": "leave_one_case_out" if args.leave_one_case_out else "in_sample",
        "action_aware": bool(args.action_aware),
        "action_residual_rows": int(len(action_residual_rows)),
        "action_residual_gains": action_residual_gains,
        "model": str(out_model),
        "corrected_csv": str(out_csv),
        "metrics": metrics,
    }
    out_summary.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
