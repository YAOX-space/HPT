"""Fit a DC-link energy/correction model for the HPT proxy.

The model predicts a stable DC-link target equilibrium from physically
motivated energy-balance features and a weighted data correction.  It is
trained on the boundary-weighted timestep transition table produced by
build_boundary_weighted_dataset.py.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont


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
    / "proxy_ode_v5_blockwise_pilot"
)


@dataclass
class WeightedScaler:
    mean: np.ndarray
    scale: np.ndarray

    @classmethod
    def fit(cls, x: np.ndarray, w: np.ndarray) -> "WeightedScaler":
        w = np.asarray(w, dtype=float)
        w = w / np.sum(w)
        mean = np.sum(x * w[:, None], axis=0)
        var = np.sum(((x - mean) ** 2) * w[:, None], axis=0)
        scale = np.sqrt(var)
        scale[scale < 1e-9] = 1.0
        return cls(mean=mean, scale=scale)

    def transform(self, x: np.ndarray) -> np.ndarray:
        return (x - self.mean) / self.scale


def _font(size: int):
    try:
        return ImageFont.truetype("arial.ttf", size)
    except OSError:
        return ImageFont.load_default()


def feature_frame(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    vdc = df["vdc"].astype(float)
    grid_v = df["grid_v_mag"].astype(float)
    energy_v = df["energy_v_mag"].astype(float)
    grid_id = df["grid_i_d"].astype(float)
    grid_iq = df["grid_i_q"].astype(float)
    energy_id = df["energy_i_d"].astype(float)
    energy_iq = df["energy_i_q"].astype(float)
    mrd = df["m_reg_d"].astype(float)
    mrq = df["m_reg_q"].astype(float)
    med = df["m_energy_d"].astype(float)
    meq = df["m_energy_q"].astype(float)
    chopper_thr_pu = 850.0 / 800.0

    out = pd.DataFrame(index=df.index)
    out["bias"] = 1.0
    out["vdc"] = vdc
    out["vdc_minus_1"] = vdc - 1.0
    out["vdc_sq_minus_1"] = vdc * vdc - 1.0
    out["grid_cmd"] = df["grid_cmd"].astype(float)
    out["grid_v_mag"] = grid_v
    out["energy_v_mag"] = energy_v
    out["fault_flag"] = df["fault_flag"].astype(float)
    out["recovery_flag"] = df["recovery_flag"].astype(float)
    out["time_in_fault"] = df["time_in_fault"].astype(float)
    out["time_in_recovery"] = df.get("time_in_recovery", pd.Series(0.0, index=df.index)).astype(float)
    out["m_reg_d"] = mrd
    out["m_reg_q"] = mrq
    out["m_energy_d"] = med
    out["m_energy_q"] = meq
    out["reg_action_mag"] = df["reg_action_mag"].astype(float)
    out["energy_action_mag"] = df["energy_action_mag"].astype(float)
    out["grid_i_d"] = grid_id
    out["grid_i_q"] = grid_iq
    out["energy_i_d"] = energy_id
    out["energy_i_q"] = energy_iq
    out["grid_i_mag"] = df["grid_i_mag"].astype(float)
    out["energy_i_mag"] = df["energy_i_mag"].astype(float)

    out["p_grid_proxy"] = grid_v * grid_id
    out["q_grid_proxy"] = grid_v * grid_iq
    out["p_energy_terminal"] = energy_v * energy_id
    out["q_energy_terminal"] = energy_v * energy_iq
    out["p_reg_mod"] = vdc * (mrd * grid_id + mrq * grid_iq)
    out["p_energy_mod"] = vdc * (med * energy_id + meq * energy_iq)
    out["p_mod_balance"] = out["p_energy_mod"] - out["p_reg_mod"]
    out["p_terminal_balance"] = out["p_energy_terminal"] - out["p_grid_proxy"]
    out["chopper_excess_sq"] = np.maximum(0.0, vdc - chopper_thr_pu) ** 2
    out["dc_loss_linear"] = vdc - 1.0
    out["recovery_p_balance"] = out["recovery_flag"] * out["p_mod_balance"]
    out["recovery_chopper"] = out["recovery_flag"] * out["chopper_excess_sq"]
    out["fault_p_balance"] = out["fault_flag"] * out["p_mod_balance"]
    out["recovery_time"] = out["recovery_flag"] * out["time_in_recovery"]
    out["recovery_time_sq"] = out["recovery_time"] * out["recovery_time"]
    out["recovery_vdc_error_time"] = out["recovery_time"] * out["vdc_minus_1"]
    out["fault_pu"] = df.get("fault_pu", pd.Series(0.0, index=df.index)).astype(float)
    out["duration_s"] = df.get("duration_ms", pd.Series(0.0, index=df.index)).astype(float) / 1000.0
    out["fault_pu_recovery"] = out["fault_pu"] * out["recovery_flag"]
    out["duration_recovery"] = out["duration_s"] * out["recovery_flag"]
    out["t_ms_recovery"] = (
        out["time_in_fault"] + out["time_in_recovery"]
    ) * out["recovery_flag"]
    out["vdc_recovery"] = vdc * out["recovery_flag"]
    out["energy_mag_recovery"] = out["energy_action_mag"] * out["recovery_flag"]
    return out, out.columns.tolist()


def fit_weighted_ridge(x: np.ndarray, y: np.ndarray, w: np.ndarray, ridge: float) -> tuple[WeightedScaler, np.ndarray]:
    scaler = WeightedScaler.fit(x, w)
    xs = scaler.transform(x)
    sw = np.sqrt(w / np.mean(w))
    xw = xs * sw[:, None]
    yw = y * sw
    coef = np.linalg.solve(xw.T @ xw + ridge * np.eye(xs.shape[1]), xw.T @ yw)
    return scaler, coef


def fit_direct_vdc_channel(
    x: np.ndarray,
    y: np.ndarray,
    w: np.ndarray,
    ridge: float,
) -> tuple[WeightedScaler, np.ndarray, dict[str, float]]:
    scaler, coef = fit_weighted_ridge(x, y, w, ridge)
    pred = scaler.transform(x) @ coef
    train_metric = metric(y, pred)
    err = pred - y
    train_metric["weighted_rmse"] = float(np.sqrt(np.average(err * err, weights=w)))
    return scaler, coef, train_metric


def predict_dvdt(features: pd.DataFrame, scaler: WeightedScaler, coef: np.ndarray) -> np.ndarray:
    return scaler.transform(features.to_numpy(dtype=float)) @ coef


def fit_stable_target_ode(
    x: np.ndarray,
    vdc: np.ndarray,
    next_vdc: np.ndarray,
    dt: np.ndarray,
    w: np.ndarray,
    ridge: float,
    *,
    vdc_min: float,
    vdc_max: float,
    max_step: float,
) -> tuple[WeightedScaler, np.ndarray, float, dict[str, float]]:
    scaler = WeightedScaler.fit(x, w)
    xs = scaler.transform(x)
    sw = np.sqrt(w / np.mean(w))
    xw = xs * sw[:, None]
    eye = np.eye(xs.shape[1])
    best: tuple[float, float, np.ndarray] | None = None
    for tau in np.geomspace(0.002, 0.50, 220):
        beta = np.clip(1.0 - np.exp(-dt / tau), 1e-4, 1.0)
        eq_target = (next_vdc - (1.0 - beta) * vdc) / beta
        coef = np.linalg.solve(xw.T @ xw + ridge * eye, xw.T @ (eq_target * sw))
        eq = np.clip(xs @ coef, vdc_min, vdc_max)
        raw = (1.0 - beta) * vdc + beta * eq
        pred = np.clip(np.clip(raw, vdc - max_step, vdc + max_step), vdc_min, vdc_max)
        rmse = float(np.sqrt(np.average((pred - next_vdc) ** 2, weights=w)))
        if best is None or rmse < best[0]:
            best = (rmse, float(tau), coef)
    assert best is not None
    rmse, tau, coef = best
    pred = predict_next_vdc(x, vdc, dt, scaler, coef, tau, vdc_min=vdc_min, vdc_max=vdc_max, max_step=max_step)
    train_metric = metric(next_vdc, pred)
    train_metric["weighted_rmse"] = rmse
    return scaler, coef, tau, train_metric


def predict_next_vdc(
    x: np.ndarray,
    vdc: np.ndarray,
    dt: np.ndarray,
    scaler: WeightedScaler,
    coef: np.ndarray,
    tau: float,
    *,
    vdc_min: float,
    vdc_max: float,
    max_step: float,
) -> np.ndarray:
    xs = scaler.transform(x)
    beta = np.clip(1.0 - np.exp(-dt / tau), 1e-4, 1.0)
    eq = np.clip(xs @ coef, vdc_min, vdc_max)
    raw = (1.0 - beta) * vdc + beta * eq
    limited = np.clip(raw, vdc - max_step, vdc + max_step)
    return np.clip(limited, vdc_min, vdc_max)


def predict_direct_next_vdc(
    x: np.ndarray,
    vdc: np.ndarray,
    scaler: WeightedScaler,
    coef: np.ndarray,
    *,
    target_mode: str,
    vdc_min: float,
    vdc_max: float,
    max_step: float,
) -> np.ndarray:
    y = scaler.transform(x) @ coef
    if target_mode == "delta_vdc":
        raw = vdc + y
    elif target_mode == "next_vdc":
        raw = y
    else:
        raise ValueError(f"Unsupported direct target mode: {target_mode}")
    limited = np.clip(raw, vdc - max_step, vdc + max_step)
    return np.clip(limited, vdc_min, vdc_max)


def metric(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    err = y_pred - y_true
    return {
        "rmse": float(np.sqrt(np.mean(err * err))),
        "mae": float(np.mean(np.abs(err))),
        "max_abs": float(np.max(np.abs(err))),
    }


def rollout_vdc(
    holdout: pd.DataFrame,
    scaler: WeightedScaler,
    coef: np.ndarray,
    tau: float,
    *,
    vdc_min: float,
    vdc_max: float,
    max_step: float,
    target_mode: str = "stable_vdc_equilibrium",
) -> pd.DataFrame:
    rows: list[dict[str, float | str]] = []
    vdc = float(holdout.iloc[0]["vdc"])
    for _, raw in holdout.iterrows():
        row = raw.copy()
        row["vdc"] = vdc
        features, _ = feature_frame(pd.DataFrame([row]))
        if target_mode in {"delta_vdc", "next_vdc"}:
            next_vdc = float(
                predict_direct_next_vdc(
                    features.to_numpy(dtype=float),
                    np.asarray([vdc], dtype=float),
                    scaler,
                    coef,
                    target_mode=target_mode,
                    vdc_min=vdc_min,
                    vdc_max=vdc_max,
                    max_step=max_step,
                )[0]
            )
        else:
            next_vdc = float(
                predict_next_vdc(
                    features.to_numpy(dtype=float),
                    np.asarray([vdc], dtype=float),
                    np.asarray([float(raw["dt"])], dtype=float),
                    scaler,
                    coef,
                    tau,
                    vdc_min=vdc_min,
                    vdc_max=vdc_max,
                    max_step=max_step,
                )[0]
            )
        dvdt = (next_vdc - vdc) / max(float(raw["dt"]), 1e-9)
        rows.append(
            {
                "t_ms": float(raw["t_ms"]),
                "zone": str(raw["zone"]),
                "sim_vdc": float(raw["vdc"]),
                "proxy_vdc": float(vdc),
                "dvdc_dt_pred": dvdt,
            }
        )
        vdc = next_vdc
    return pd.DataFrame(rows)


def draw_vdc_plot(comp: pd.DataFrame, out_png: Path, title: str) -> None:
    width, height = 1200, 560
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    draw.text((55, 28), title, fill=(20, 20, 20), font=_font(25))
    draw.text((55, 62), "DC-link only: black = Simulink, red dashed = energy/correction model", fill=(80, 80, 80), font=_font(16))
    left, top, right, bottom = 105, 105, 1145, 430
    x = comp["t_ms"].to_numpy(dtype=float)
    sim = comp["sim_vdc"].to_numpy(dtype=float)
    pred = comp["proxy_vdc"].to_numpy(dtype=float)
    x_min, x_max = float(x.min()), float(x.max())
    y_min, y_max = float(min(sim.min(), pred.min())), float(max(sim.max(), pred.max()))
    pad = 0.08 * max(y_max - y_min, 1e-9)
    y_min -= pad
    y_max += pad

    def px(v: float) -> int:
        return int(left + (v - x_min) / max(x_max - x_min, 1e-9) * (right - left))

    def py(v: float) -> int:
        return int(bottom - (v - y_min) / max(y_max - y_min, 1e-9) * (bottom - top))

    fault = comp["zone"].astype(str).eq("fault")
    if fault.any():
        draw.rectangle(
            [px(float(comp.loc[fault, "t_ms"].min())), top, px(float(comp.loc[fault, "t_ms"].max())), bottom],
            fill=(250, 239, 214),
        )
    for frac in np.linspace(0, 1, 5):
        yy = int(top + frac * (bottom - top))
        draw.line([(left, yy), (right, yy)], fill=(225, 225, 225), width=1)
    draw.rectangle([left, top, right, bottom], outline=(80, 80, 80), width=1)
    sim_pts = [(px(float(a)), py(float(b))) for a, b in zip(x, sim)]
    pred_pts = [(px(float(a)), py(float(b))) for a, b in zip(x, pred)]
    draw.line(sim_pts, fill=(20, 20, 20), width=3)
    for idx in range(len(pred_pts) - 1):
        if idx % 2 == 0:
            draw.line([pred_pts[idx], pred_pts[idx + 1]], fill=(210, 40, 40), width=3)
    draw.text((left, bottom + 8), f"{x_min:.0f} ms", fill=(80, 80, 80), font=_font(13))
    draw.text((right - 55, bottom + 8), f"{x_max:.0f} ms", fill=(80, 80, 80), font=_font(13))
    draw.text((left + 5, top + 5), f"{y_max:.2f}", fill=(80, 80, 80), font=_font(12))
    draw.text((left + 5, bottom - 18), f"{y_min:.2f}", fill=(80, 80, 80), font=_font(12))
    draw.text((55, 250), "Vdc pu", fill=(20, 20, 20), font=_font(16))
    yleg = height - 75
    draw.line([(95, yleg), (150, yleg)], fill=(20, 20, 20), width=3)
    draw.text((160, yleg - 12), "Simulink", fill=(30, 30, 30), font=_font(17))
    draw.line([(350, yleg), (405, yleg)], fill=(210, 40, 40), width=3)
    draw.text((415, yleg - 12), "DC energy/correction model", fill=(30, 30, 30), font=_font(17))
    draw.rectangle([735, yleg - 16, 790, yleg + 16], fill=(250, 239, 214), outline=(230, 210, 170))
    draw.text((802, yleg - 12), "fault window", fill=(30, 30, 30), font=_font(17))
    img.save(out_png)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--holdout", default="pu0825_d120ms")
    parser.add_argument(
        "--train-all",
        action="store_true",
        help="Fit one deployable model on the full transition table instead of leaving out a holdout trace.",
    )
    parser.add_argument(
        "--model-name",
        default="dc_link_energy_correction_model.json",
        help="Model JSON filename written under --out-dir.",
    )
    parser.add_argument("--ridge", type=float, default=1e-2)
    parser.add_argument("--vdc-min", type=float, default=0.45)
    parser.add_argument("--vdc-max", type=float, default=1.30)
    parser.add_argument("--max-step-pu", type=float, default=0.035)
    parser.add_argument(
        "--target-mode",
        choices=["stable_vdc_equilibrium", "delta_vdc", "next_vdc"],
        default="stable_vdc_equilibrium",
        help=(
            "DC-link channel target. stable_vdc_equilibrium preserves the v5 "
            "relaxation model; delta_vdc directly learns the control-step "
            "DC-link change and is usually better for free rollout."
        ),
    )
    parser.add_argument(
        "--blockwise",
        action="store_true",
        help=(
            "Also fit local models by fault_pu, duration_ms, and zone. The "
            "runtime channel uses the nearest matching block and falls back to "
            "the global model outside calibrated blocks."
        ),
    )
    parser.add_argument("--min-block-rows", type=int, default=12)
    parser.add_argument("--profile-blend-fault", type=float, default=0.0)
    parser.add_argument("--profile-blend-recovery", type=float, default=0.0)
    parser.add_argument("--profile-blend-tail", type=float, default=0.0)
    parser.add_argument(
        "--action-local-profiles",
        action="store_true",
        help=(
            "Keep each trace as a separate local profile inside a "
            "fault_pu/duration/zone block. This prevents high-action failure "
            "traces from being averaged into the strong-dq profile."
        ),
    )
    parser.add_argument("--action-distance-weight", type=float, default=1.0)
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    data = pd.read_csv(args.dataset)
    if args.train_all:
        train = data.copy()
        holdout = pd.DataFrame()
    else:
        holdout_mask = data["case_name"].astype(str).str.lower().str.contains(args.holdout.lower(), regex=False)
        if not holdout_mask.any():
            raise ValueError(f"No holdout rows matched {args.holdout!r}")
        train = data.loc[~holdout_mask].copy()
        holdout = data.loc[holdout_mask].sort_values("t").copy()

    x_train, feature_names = feature_frame(train)
    w_train = train["proxy_weight"].to_numpy(dtype=float)
    if args.target_mode == "stable_vdc_equilibrium":
        scaler, coef, tau, train_metrics = fit_stable_target_ode(
            x_train.to_numpy(dtype=float),
            train["vdc"].to_numpy(dtype=float),
            train["next_vdc"].to_numpy(dtype=float),
            train["dt"].to_numpy(dtype=float),
            w_train,
            args.ridge,
            vdc_min=args.vdc_min,
            vdc_max=args.vdc_max,
            max_step=args.max_step_pu,
        )
    else:
        y_train = (
            (train["next_vdc"] - train["vdc"]).to_numpy(dtype=float)
            if args.target_mode == "delta_vdc"
            else train["next_vdc"].to_numpy(dtype=float)
        )
        scaler, coef, train_metrics = fit_direct_vdc_channel(
            x_train.to_numpy(dtype=float),
            y_train,
            w_train,
            args.ridge,
        )
        tau = 0.0

    blocks: list[dict[str, object]] = []
    if args.blockwise:
        if args.target_mode == "stable_vdc_equilibrium":
            raise ValueError("--blockwise currently requires --target-mode delta_vdc or next_vdc")
        group_cols = ["fault_pu", "duration_ms", "zone"]
        if args.action_local_profiles:
            group_cols.append("case_name")
        for group_key, block in train.groupby(group_cols, sort=True):
            if args.action_local_profiles:
                fault_pu, duration_ms, zone, case_name = group_key
            else:
                fault_pu, duration_ms, zone = group_key
                case_name = ""
            if len(block) < int(args.min_block_rows):
                continue
            x_block, block_feature_names = feature_frame(block)
            y_block = (
                (block["next_vdc"] - block["vdc"]).to_numpy(dtype=float)
                if args.target_mode == "delta_vdc"
                else block["next_vdc"].to_numpy(dtype=float)
            )
            w_block = block["proxy_weight"].to_numpy(dtype=float)
            block_scaler, block_coef, block_metrics = fit_direct_vdc_channel(
                x_block.to_numpy(dtype=float),
                y_block,
                w_block,
                args.ridge,
            )
            block_sorted = block.sort_values("t").copy()
            if str(zone) == "fault":
                profile_time = block_sorted["time_in_fault"].to_numpy(dtype=float)
                profile_blend = float(args.profile_blend_fault)
            elif str(zone) == "recovery":
                profile_time = block_sorted["time_in_recovery"].to_numpy(dtype=float)
                profile_blend = float(args.profile_blend_recovery)
            else:
                profile_time = block_sorted["time_in_recovery"].to_numpy(dtype=float)
                profile_blend = float(args.profile_blend_tail)
            blocks.append(
                {
                    "fault_pu": float(fault_pu),
                    "duration_ms": float(duration_ms),
                    "zone": str(zone),
                    "case_name": str(case_name),
                    "n_rows": int(len(block)),
                    "feature_names": block_feature_names,
                    "feature_mean": block_scaler.mean.tolist(),
                    "feature_scale": block_scaler.scale.tolist(),
                    "coef": block_coef.tolist(),
                    "target": args.target_mode,
                    "tau_s": 0.0,
                    "max_step_pu": float(args.max_step_pu),
                    "train_metrics": block_metrics,
                    "profile_time_s": profile_time.tolist(),
                    "profile_next_vdc": block_sorted["next_vdc"].to_numpy(dtype=float).tolist(),
                    "profile_m_reg_d": block_sorted["m_reg_d"].to_numpy(dtype=float).tolist(),
                    "profile_m_reg_q": block_sorted["m_reg_q"].to_numpy(dtype=float).tolist(),
                    "profile_m_energy_d": block_sorted["m_energy_d"].to_numpy(dtype=float).tolist(),
                    "profile_m_energy_q": block_sorted["m_energy_q"].to_numpy(dtype=float).tolist(),
                    "profile_action_mean": [
                        float(block_sorted["m_reg_d"].mean()),
                        float(block_sorted["m_reg_q"].mean()),
                        float(block_sorted["m_energy_d"].mean()),
                        float(block_sorted["m_energy_q"].mean()),
                    ],
                    "action_distance_weight": float(args.action_distance_weight),
                    "profile_blend": profile_blend,
                }
            )

    one_step_metrics = {}
    rollout_metrics = {}
    artifacts: dict[str, str] = {}
    if not args.train_all:
        x_holdout, _ = feature_frame(holdout)
        if args.target_mode in {"delta_vdc", "next_vdc"}:
            holdout_one_step_vdc = predict_direct_next_vdc(
                x_holdout.to_numpy(dtype=float),
                holdout["vdc"].to_numpy(dtype=float),
                scaler,
                coef,
                target_mode=args.target_mode,
                vdc_min=args.vdc_min,
                vdc_max=args.vdc_max,
                max_step=args.max_step_pu,
            )
        else:
            holdout_one_step_vdc = predict_next_vdc(
                x_holdout.to_numpy(dtype=float),
                holdout["vdc"].to_numpy(dtype=float),
                holdout["dt"].to_numpy(dtype=float),
                scaler,
                coef,
                tau,
                vdc_min=args.vdc_min,
                vdc_max=args.vdc_max,
                max_step=args.max_step_pu,
            )
        one_step_metrics = metric(holdout["next_vdc"].to_numpy(dtype=float), holdout_one_step_vdc)
        comp = rollout_vdc(
            holdout,
            scaler,
            coef,
            tau,
            vdc_min=args.vdc_min,
            vdc_max=args.vdc_max,
            max_step=args.max_step_pu,
            target_mode=args.target_mode,
        )
        rollout_metrics = metric(comp["sim_vdc"].to_numpy(dtype=float), comp["proxy_vdc"].to_numpy(dtype=float))
        comp_csv = args.out_dir / f"dc_link_holdout_{args.holdout}_rollout.csv"
        fig_png = args.out_dir / f"dc_link_holdout_{args.holdout}_rollout.png"
        comp.to_csv(comp_csv, index=False)
        draw_vdc_plot(comp, fig_png, f"DC-Link Energy/Correction Model Holdout: {args.holdout}")
        artifacts.update(
            {
                "comparison_csv": str(comp_csv),
                "figure_png": str(fig_png),
            }
        )

    model_json = args.out_dir / args.model_name
    summary_name = "dc_link_energy_model_final_summary.json" if args.train_all else f"dc_link_energy_model_{args.holdout}_summary.json"
    summary_json = args.out_dir / summary_name
    model_json.write_text(
        json.dumps(
            {
                "schema": "hpt-proxy-v5-dc-link-energy-correction",
                "fit_mode": "full_dataset" if args.train_all else "leave_one_case_out",
                "dataset": str(args.dataset),
                "n_train_rows": int(len(train)),
                "feature_names": feature_names,
                "feature_mean": scaler.mean.tolist(),
                "feature_scale": scaler.scale.tolist(),
                "coef": coef.tolist(),
                "target": args.target_mode,
                "tau_s": tau,
                "ridge": float(args.ridge),
                "vdc_min": float(args.vdc_min),
                "vdc_max": float(args.vdc_max),
                "max_step_pu": float(args.max_step_pu),
                "block_mode": "fault_pu_duration_zone" if args.blockwise else "",
                "action_local_profiles": bool(args.action_local_profiles),
                "action_distance_weight": float(args.action_distance_weight),
                "blocks": blocks,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    summary = {
        "schema": "hpt-proxy-v5-dc-link-energy-correction-summary",
        "dataset": str(args.dataset),
        "out_dir": str(args.out_dir),
        "fit_mode": "full_dataset" if args.train_all else "leave_one_case_out",
        "holdout": None if args.train_all else args.holdout,
        "n_train_rows": int(len(train)),
        "n_holdout_rows": int(len(holdout)),
        "ridge": float(args.ridge),
        "target_mode": args.target_mode,
        "blockwise": bool(args.blockwise),
        "n_blocks": int(len(blocks)),
        "tau_s": float(tau),
        "vdc_min": float(args.vdc_min),
        "vdc_max": float(args.vdc_max),
        "max_step_pu": float(args.max_step_pu),
        "weighted_train_next_vdc_metrics": train_metrics,
        "one_step_next_vdc_metrics": one_step_metrics,
        "free_rollout_vdc_metrics": rollout_metrics,
        "artifacts": {
            "model_json": str(model_json),
            "summary_json": str(summary_json),
            **artifacts,
        },
    }
    summary_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
