"""Build and validate a slow-state ODE proxy with diagnostics windows.

This script is a repair of the earlier measured-state ODE pilot.  The proxy
rolls out only slow control states, while fast internal Simulink measurements
are summarized as diagnostics instead of being free-rolled by the ODE.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

try:
    import matplotlib.pyplot as plt

    HAS_MATPLOTLIB = True
except ModuleNotFoundError:
    from PIL import Image, ImageDraw, ImageFont

    HAS_MATPLOTLIB = False


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
    / "proxy_ode_v4_slow_diag_pilot"
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
DIAG_COLS = [
    "reg_i_mag",
    "hbc_cap_v_mag",
    "series_inj_v_mag",
    "idc_cap_500a_pu",
]


@dataclass
class Scaler:
    mean: np.ndarray
    scale: np.ndarray

    @classmethod
    def fit(cls, x: np.ndarray) -> "Scaler":
        mean = np.mean(x, axis=0)
        scale = np.std(x, axis=0)
        scale[scale < 1e-9] = 1.0
        return cls(mean, scale)

    def transform(self, x: np.ndarray) -> np.ndarray:
        return (x - self.mean) / self.scale


@dataclass
class SlowOdeFit:
    scaler: Scaler
    coef: np.ndarray
    taus: np.ndarray
    feature_names: list[str]

    def equilibrium(self, x: np.ndarray) -> np.ndarray:
        xs = self.scaler.transform(x.reshape(1, -1))
        return (xs @ self.coef).reshape(-1)

    def to_jsonable(self) -> dict[str, object]:
        return {
            "schema": "hpt-proxy-ode-v4-slow-state",
            "state_names": STATE_COLS,
            "feature_names": self.feature_names,
            "taus_s": self.taus.tolist(),
            "feature_mean": self.scaler.mean.tolist(),
            "feature_scale": self.scaler.scale.tolist(),
            "coef": self.coef.tolist(),
        }


def parse_case(path: Path) -> tuple[float, int]:
    text = path.stem.lower()
    pu_match = re.search(r"pu(\d{4})", text)
    dur_match = re.search(r"d(\d{3})ms", text)
    fault_pu = float(pu_match.group(1)) / 1000.0 if pu_match else float("nan")
    duration_ms = int(dur_match.group(1)) if dur_match else -1
    return fault_pu, duration_ms


def read_physical_params(trace_dir: Path) -> dict[str, float]:
    candidates = sorted(trace_dir.glob("*_physical_params.json"))
    if not candidates:
        return {}
    raw = json.loads(candidates[0].read_text(encoding="utf-8"))
    return {k: float(v) for k, v in raw.items() if isinstance(v, (int, float))}


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
    out["time_from_start"] = out["t"] - float(out["t"].iloc[0])
    out["time_in_fault"] = np.maximum(0.0, out["t"] - 0.035)
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


def features(row: pd.Series, phys: dict[str, float]) -> tuple[np.ndarray, list[str]]:
    state = {name: float(row[name]) for name in STATE_COLS}
    action = {name: float(row[name]) for name in ACTION_COLS}
    grid_cmd = float(row["grid_cmd"])
    grid_v = float(row["grid_v_mag"])
    energy_v = float(row["energy_v_mag"])
    fault = float(row["fault_flag"])
    recovery = float(row["recovery_flag"])
    time_fault = float(row["time_in_fault"])
    grid_i_mag = float(np.hypot(state["grid_i_d"], state["grid_i_q"]))
    energy_i_mag = float(np.hypot(state["energy_i_d"], state["energy_i_q"]))
    reg_mag = float(np.hypot(action["m_reg_d"], action["m_reg_q"]))
    energy_mag = float(np.hypot(action["m_energy_d"], action["m_energy_q"]))
    cdc = phys.get("dc_link_c_f", 0.0022)
    lhbc = phys.get("hbc_filter_l_h", 0.002)
    lenergy = phys.get("energy_filter_l_h", 0.0015)

    names = [
        "bias",
        *STATE_COLS,
        *ACTION_COLS,
        "grid_cmd",
        "grid_v_mag",
        "energy_v_mag",
        "fault",
        "recovery",
        "time_in_fault",
        "grid_cmd_minus_lv",
        "grid_v_minus_lv",
        "vdc_minus_1",
        "grid_i_mag",
        "energy_i_mag",
        "reg_action_mag",
        "energy_action_mag",
        "vdc_m_reg_d",
        "vdc_m_reg_q",
        "vdc_m_energy_d",
        "vdc_m_energy_q",
        "p_grid_proxy",
        "q_grid_proxy",
        "p_energy_proxy",
        "q_energy_proxy",
        "dc_power_over_c",
        "reg_voltage_over_l",
        "energy_voltage_over_l",
        "fault_m_reg_d",
        "fault_m_reg_q",
    ]
    values = np.asarray(
        [
            1.0,
            *(state[name] for name in STATE_COLS),
            *(action[name] for name in ACTION_COLS),
            grid_cmd,
            grid_v,
            energy_v,
            fault,
            recovery,
            time_fault,
            grid_cmd - state["v_lv"],
            grid_v - state["v_lv"],
            state["vdc"] - 1.0,
            grid_i_mag,
            energy_i_mag,
            reg_mag,
            energy_mag,
            state["vdc"] * action["m_reg_d"],
            state["vdc"] * action["m_reg_q"],
            state["vdc"] * action["m_energy_d"],
            state["vdc"] * action["m_energy_q"],
            grid_v * state["grid_i_d"],
            grid_v * state["grid_i_q"],
            energy_v * state["energy_i_d"],
            energy_v * state["energy_i_q"],
            (grid_v * state["grid_i_d"] - energy_v * state["energy_i_d"]) / max(cdc, 1e-9),
            (state["vdc"] * action["m_reg_d"] - state["v_lv"]) / max(lhbc, 1e-9),
            (state["vdc"] * action["m_energy_d"] - energy_v) / max(lenergy, 1e-9),
            fault * action["m_reg_d"],
            fault * action["m_reg_q"],
        ],
        dtype=float,
    )
    return values, names


def build_ode_rows(
    traces: list[pd.DataFrame], phys: dict[str, float]
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, list[str]]:
    x_rows: list[np.ndarray] = []
    state_rows: list[np.ndarray] = []
    next_rows: list[np.ndarray] = []
    dt_rows: list[float] = []
    names: list[str] | None = None
    for trace in traces:
        for idx in range(len(trace) - 1):
            cur = trace.iloc[idx]
            nxt = trace.iloc[idx + 1]
            dt = float(nxt["t"] - cur["t"])
            if dt <= 0:
                continue
            x, names = features(cur, phys)
            x_rows.append(x)
            state_rows.append(cur[STATE_COLS].astype(float).to_numpy())
            next_rows.append(nxt[STATE_COLS].astype(float).to_numpy())
            dt_rows.append(dt)
    if names is None:
        raise RuntimeError("No transition rows were built.")
    return (
        np.vstack(x_rows),
        np.vstack(state_rows),
        np.vstack(next_rows),
        np.asarray(dt_rows, dtype=float),
        names,
    )


def fit_slow_ode(
    x: np.ndarray,
    state: np.ndarray,
    next_state: np.ndarray,
    dt: np.ndarray,
    feature_names: list[str],
    *,
    ridge: float,
) -> SlowOdeFit:
    scaler = Scaler.fit(x)
    xs = scaler.transform(x)
    tau_grid = np.geomspace(0.002, 0.35, 180)
    coefs: list[np.ndarray] = []
    taus: list[float] = []
    eye = np.eye(xs.shape[1])
    for idx in range(state.shape[1]):
        best_rmse = float("inf")
        best_tau = float(tau_grid[0])
        best_coef = np.zeros(xs.shape[1])
        for tau in tau_grid:
            beta = np.clip(1.0 - np.exp(-dt / tau), 1e-4, 1.0)
            eq_target = (next_state[:, idx] - (1.0 - beta) * state[:, idx]) / beta
            coef = np.linalg.solve(xs.T @ xs + ridge * eye, xs.T @ eq_target)
            pred = (1.0 - beta) * state[:, idx] + beta * (xs @ coef)
            rmse = float(np.sqrt(np.mean((pred - next_state[:, idx]) ** 2)))
            if rmse < best_rmse:
                best_rmse = rmse
                best_tau = float(tau)
                best_coef = coef
        taus.append(best_tau)
        coefs.append(best_coef)
    return SlowOdeFit(
        scaler=scaler,
        coef=np.vstack(coefs).T,
        taus=np.asarray(taus, dtype=float),
        feature_names=feature_names,
    )


def rollout(trace: pd.DataFrame, model: SlowOdeFit, phys: dict[str, float]) -> pd.DataFrame:
    state = trace.iloc[0][STATE_COLS].astype(float).to_numpy()
    records: list[dict[str, float | str]] = []
    for idx in range(len(trace)):
        row = trace.iloc[idx].copy()
        for name, value in zip(STATE_COLS, state):
            row[name] = float(value)
        sim_state = trace.iloc[idx][STATE_COLS].astype(float)
        records.append(
            {
                "t_ms": float(trace.iloc[idx]["t_ms"]),
                "zone": str(trace.iloc[idx]["zone"]),
                "sim_v_lv": float(sim_state["v_lv"]),
                "proxy_v_lv": float(state[0]),
                "sim_vdc": float(sim_state["vdc"]),
                "proxy_vdc": float(state[1]),
                "sim_grid_i_mag": float(np.hypot(sim_state["grid_i_d"], sim_state["grid_i_q"])),
                "proxy_grid_i_mag": float(np.hypot(state[2], state[3])),
                "sim_energy_i_mag": float(np.hypot(sim_state["energy_i_d"], sim_state["energy_i_q"])),
                "proxy_energy_i_mag": float(np.hypot(state[4], state[5])),
                "sim_reg_i_peak_src": float(trace.iloc[idx]["reg_i_mag"]),
                "sim_hbc_cap_v_src": float(trace.iloc[idx]["hbc_cap_v_mag"]),
                "sim_series_inj_v_src": float(trace.iloc[idx]["series_inj_v_mag"]),
                "sim_idc_cap_src": float(trace.iloc[idx]["idc_cap_500a_pu"]),
            }
        )
        if idx >= len(trace) - 1:
            break
        dt = float(trace.iloc[idx + 1]["t"] - trace.iloc[idx]["t"])
        eq = model.equilibrium(features(row, phys)[0])
        beta = np.clip(1.0 - np.exp(-dt / model.taus), 1e-4, 1.0)
        state = (1.0 - beta) * state + beta * eq
        state[0] = np.clip(state[0], 0.0, 1.4)
        state[1] = np.clip(state[1], 0.0, 1.5)
        state[2:6] = np.clip(state[2:6], -3.0, 3.0)
    return pd.DataFrame(records)


def diagnostics_windows(trace: pd.DataFrame, *, window_s: float) -> pd.DataFrame:
    t0 = float(trace["t"].iloc[0])
    block = np.floor((trace["t"] - t0) / window_s).astype(int)
    rows: list[dict[str, float | str]] = []
    for _, group in trace.groupby(block, sort=True):
        rec: dict[str, float | str] = {
            "t_ms": float(group["t_ms"].mean()),
            "zone": str(group["zone"].mode().iloc[0]),
        }
        for col in DIAG_COLS:
            values = group[col].to_numpy(dtype=float)
            rec[f"{col}_peak"] = float(np.max(np.abs(values)))
            rec[f"{col}_rms"] = float(np.sqrt(np.mean(values * values)))
            rec[f"{col}_min"] = float(np.min(values))
            rec[f"{col}_max"] = float(np.max(values))
        rows.append(rec)
    return pd.DataFrame(rows)


def metric(y_true: pd.Series, y_pred: pd.Series) -> dict[str, float]:
    err = y_pred.to_numpy(dtype=float) - y_true.to_numpy(dtype=float)
    return {
        "rmse": float(np.sqrt(np.mean(err * err))),
        "mae": float(np.mean(np.abs(err))),
        "max_abs": float(np.max(np.abs(err))),
    }


def summarize_rollout(comp: pd.DataFrame) -> dict[str, dict[str, float]]:
    return {
        "v_lv_pu": metric(comp["sim_v_lv"], comp["proxy_v_lv"]),
        "vdc_pu": metric(comp["sim_vdc"], comp["proxy_vdc"]),
        "grid_current_mag_pu": metric(comp["sim_grid_i_mag"], comp["proxy_grid_i_mag"]),
        "energy_current_mag_pu": metric(comp["sim_energy_i_mag"], comp["proxy_energy_i_mag"]),
    }


def plot_rollout_matplotlib(comp: pd.DataFrame, diag: pd.DataFrame, out_png: Path, title: str) -> None:
    fig, axes = plt.subplots(6, 1, figsize=(8.2, 9.2), dpi=190, sharex=True, facecolor="white")
    fault = comp["zone"] == "fault"
    if fault.any():
        fault_start = comp.loc[fault, "t_ms"].min()
        fault_end = comp.loc[fault, "t_ms"].max()
    else:
        fault_start = fault_end = None

    slow_specs = [
        ("sim_v_lv", "proxy_v_lv", "Load-side voltage (pu)"),
        ("sim_vdc", "proxy_vdc", "DC-link voltage (pu)"),
        ("sim_grid_i_mag", "proxy_grid_i_mag", "Grid current |i| (pu)"),
        ("sim_energy_i_mag", "proxy_energy_i_mag", "Energy current |i| (pu)"),
    ]
    for ax, (sim, pred, ylabel) in zip(axes[:4], slow_specs):
        if fault_start is not None:
            ax.axvspan(fault_start, fault_end, color="#f0c36a", alpha=0.23)
        ax.plot(comp["t_ms"], comp[sim], color="#111111", lw=1.6, label="Simulink")
        ax.plot(comp["t_ms"], comp[pred], color="#d62728", lw=1.35, ls="--", label="slow ODE proxy")
        ax.set_ylabel(ylabel, fontsize=8.5)
        ax.grid(True, color="#dddddd", lw=0.6)
        ax.tick_params(labelsize=8)

    if fault_start is not None:
        axes[4].axvspan(fault_start, fault_end, color="#f0c36a", alpha=0.23)
        axes[5].axvspan(fault_start, fault_end, color="#f0c36a", alpha=0.23)
    axes[4].plot(diag["t_ms"], diag["reg_i_mag_peak"], color="#1f77b4", lw=1.5, label="reg |i| peak")
    axes[4].plot(diag["t_ms"], diag["idc_cap_500a_pu_peak"], color="#9467bd", lw=1.3, label="Idc cap peak")
    axes[4].set_ylabel("Diagnostics current\nSimulink only", fontsize=8.5)
    axes[4].grid(True, color="#dddddd", lw=0.6)
    axes[4].legend(loc="best", fontsize=7.5)
    axes[4].tick_params(labelsize=8)

    axes[5].plot(diag["t_ms"], diag["hbc_cap_v_mag_peak"], color="#2ca02c", lw=1.5, label="HBC cap V peak")
    axes[5].plot(diag["t_ms"], diag["series_inj_v_mag_peak"], color="#ff7f0e", lw=1.3, label="series injection V peak")
    axes[5].set_ylabel("Diagnostics voltage\nSimulink only", fontsize=8.5)
    axes[5].grid(True, color="#dddddd", lw=0.6)
    axes[5].legend(loc="best", fontsize=7.5)
    axes[5].tick_params(labelsize=8)

    axes[0].legend(loc="best", fontsize=7.5)
    axes[-1].set_xlabel("Time (ms)", fontsize=9)
    fig.suptitle(title, fontsize=11)
    fig.tight_layout(rect=[0, 0, 1, 0.965])
    fig.savefig(out_png, facecolor="white", bbox_inches="tight")
    plt.close(fig)


def _font(size: int):
    try:
        return ImageFont.truetype("arial.ttf", size)
    except OSError:
        return ImageFont.load_default()


def _draw_panel(
    draw,
    box: tuple[int, int, int, int],
    x: np.ndarray,
    series: list[tuple[np.ndarray, str, tuple[int, int, int], str]],
    ylabel: str,
    *,
    fault_span: tuple[float, float] | None,
) -> None:
    left, top, right, bottom = box
    width = right - left
    height = bottom - top
    x_min = float(np.nanmin(x))
    x_max = float(np.nanmax(x))
    y_values = np.concatenate([s[0] for s in series])
    y_min = float(np.nanmin(y_values))
    y_max = float(np.nanmax(y_values))
    if abs(y_max - y_min) < 1e-9:
        y_min -= 0.5
        y_max += 0.5
    pad = 0.08 * (y_max - y_min)
    y_min -= pad
    y_max += pad

    def px(xv: float) -> int:
        return int(left + (xv - x_min) / max(x_max - x_min, 1e-9) * width)

    def py(yv: float) -> int:
        return int(bottom - (yv - y_min) / max(y_max - y_min, 1e-9) * height)

    if fault_span is not None:
        draw.rectangle([px(fault_span[0]), top, px(fault_span[1]), bottom], fill=(250, 239, 214))

    for frac in np.linspace(0, 1, 5):
        yy = int(top + frac * height)
        draw.line([(left, yy), (right, yy)], fill=(225, 225, 225), width=1)
    draw.rectangle([left, top, right, bottom], outline=(80, 80, 80), width=1)

    for y, _, color, style in series:
        pts = [(px(float(xv)), py(float(yv))) for xv, yv in zip(x, y)]
        if len(pts) < 2:
            continue
        if style == "dash":
            for idx in range(len(pts) - 1):
                if idx % 2 == 0:
                    draw.line([pts[idx], pts[idx + 1]], fill=color, width=2)
        else:
            draw.line(pts, fill=color, width=2)

    draw.text((left - 86, top + 4), ylabel, fill=(20, 20, 20), font=_font(13))
    draw.text((left, bottom + 3), f"{x_min:.0f} ms", fill=(70, 70, 70), font=_font(11))
    draw.text((right - 46, bottom + 3), f"{x_max:.0f} ms", fill=(70, 70, 70), font=_font(11))
    draw.text((left + 4, top + 3), f"{y_max:.2f}", fill=(70, 70, 70), font=_font(10))
    draw.text((left + 4, bottom - 14), f"{y_min:.2f}", fill=(70, 70, 70), font=_font(10))


def plot_rollout_pillow(comp: pd.DataFrame, diag: pd.DataFrame, out_png: Path, title: str) -> None:
    width, height = 1450, 1620
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    title_lines = title.splitlines()
    draw.text((70, 26), title_lines[0], fill=(20, 20, 20), font=_font(27))
    if len(title_lines) > 1:
        short_case = title_lines[1]
        short_case = short_case.replace("trajectory_trace_topology2_dqseed_", "")
        short_case = re.sub(r"_\d{8}_\d{6}$", "", short_case)
        draw.text((70, 62), short_case, fill=(70, 70, 70), font=_font(18))
    draw.text(
        (70, 88),
        "Fast internal signals are Simulink diagnostics only; they are not free-rolled by the ODE.",
        fill=(80, 80, 80),
        font=_font(18),
    )

    fault = comp["zone"] == "fault"
    fault_span = None
    if fault.any():
        fault_span = (float(comp.loc[fault, "t_ms"].min()), float(comp.loc[fault, "t_ms"].max()))

    x = comp["t_ms"].to_numpy(dtype=float)
    panels = [
        (
            "LV voltage",
            [
                (comp["sim_v_lv"].to_numpy(dtype=float), "Simulink", (20, 20, 20), "solid"),
                (comp["proxy_v_lv"].to_numpy(dtype=float), "slow ODE proxy", (210, 40, 40), "dash"),
            ],
        ),
        (
            "DC-link",
            [
                (comp["sim_vdc"].to_numpy(dtype=float), "Simulink", (20, 20, 20), "solid"),
                (comp["proxy_vdc"].to_numpy(dtype=float), "slow ODE proxy", (210, 40, 40), "dash"),
            ],
        ),
        (
            "Grid |i|",
            [
                (comp["sim_grid_i_mag"].to_numpy(dtype=float), "Simulink", (20, 20, 20), "solid"),
                (comp["proxy_grid_i_mag"].to_numpy(dtype=float), "slow ODE proxy", (210, 40, 40), "dash"),
            ],
        ),
        (
            "Energy |i|",
            [
                (comp["sim_energy_i_mag"].to_numpy(dtype=float), "Simulink", (20, 20, 20), "solid"),
                (comp["proxy_energy_i_mag"].to_numpy(dtype=float), "slow ODE proxy", (210, 40, 40), "dash"),
            ],
        ),
    ]
    top0 = 145
    panel_h = 190
    gap = 38
    for idx, (ylabel, series) in enumerate(panels):
        y0 = top0 + idx * (panel_h + gap)
        _draw_panel(draw, (170, y0, 1370, y0 + panel_h), x, series, ylabel, fault_span=fault_span)

    dx = diag["t_ms"].to_numpy(dtype=float)
    diag_panels = [
        (
            "Diag current",
            [
                (diag["reg_i_mag_peak"].to_numpy(dtype=float), "reg |i| peak", (30, 110, 190), "solid"),
                (diag["idc_cap_500a_pu_peak"].to_numpy(dtype=float), "Idc peak", (130, 80, 170), "solid"),
            ],
        ),
        (
            "Diag voltage",
            [
                (diag["hbc_cap_v_mag_peak"].to_numpy(dtype=float), "HBC cap V peak", (40, 150, 70), "solid"),
                (diag["series_inj_v_mag_peak"].to_numpy(dtype=float), "series Vinj peak", (220, 125, 25), "solid"),
            ],
        ),
    ]
    for jdx, (ylabel, series) in enumerate(diag_panels):
        y0 = top0 + (len(panels) + jdx) * (panel_h + gap)
        _draw_panel(draw, (170, y0, 1370, y0 + panel_h), dx, series, ylabel, fault_span=fault_span)

    legend_y = height - 88
    draw.line([(85, legend_y), (135, legend_y)], fill=(20, 20, 20), width=3)
    draw.text((145, legend_y - 12), "Simulink slow state", fill=(30, 30, 30), font=_font(17))
    draw.line([(365, legend_y), (415, legend_y)], fill=(210, 40, 40), width=3)
    draw.text((425, legend_y - 12), "slow ODE proxy", fill=(30, 30, 30), font=_font(17))
    draw.line([(645, legend_y), (695, legend_y)], fill=(30, 110, 190), width=3)
    draw.text((705, legend_y - 12), "diagnostics current", fill=(30, 30, 30), font=_font(17))
    draw.line([(950, legend_y), (1000, legend_y)], fill=(40, 150, 70), width=3)
    draw.text((1010, legend_y - 12), "diagnostics voltage", fill=(30, 30, 30), font=_font(17))
    draw.rectangle([85, legend_y + 28, 135, legend_y + 56], fill=(250, 239, 214), outline=(230, 210, 170))
    draw.text((145, legend_y + 30), "fault window", fill=(30, 30, 30), font=_font(17))
    draw.text((85, height - 48), "x-axis: time (ms)", fill=(80, 80, 80), font=_font(16))
    img.save(out_png)


def plot_rollout(comp: pd.DataFrame, diag: pd.DataFrame, out_png: Path, title: str) -> None:
    if HAS_MATPLOTLIB:
        plot_rollout_matplotlib(comp, diag, out_png, title)
    else:
        plot_rollout_pillow(comp, diag, out_png, title)


def run(args: argparse.Namespace) -> dict[str, object]:
    args.out_dir.mkdir(parents=True, exist_ok=True)
    phys = read_physical_params(args.trace_dir)
    paths = sorted(args.trace_dir.glob("trajectory_trace_*.csv"))
    if not paths:
        raise FileNotFoundError(f"No trace CSV files in {args.trace_dir}")

    loaded = [(path, load_trace(path, startup_skip_s=args.startup_skip_s)) for path in paths]
    matches = [(path, trace) for path, trace in loaded if args.holdout.lower() in path.stem.lower()]
    if not matches:
        raise ValueError(f"No holdout matched {args.holdout!r}")
    holdout_path, holdout_trace = matches[0]
    train_traces = [trace for path, trace in loaded if path != holdout_path]

    x, state, next_state, dt, feature_names = build_ode_rows(train_traces, phys)
    model = fit_slow_ode(x, state, next_state, dt, feature_names, ridge=args.ridge)
    comp = rollout(holdout_trace, model, phys)
    diag = diagnostics_windows(holdout_trace, window_s=args.diag_window_ms / 1000.0)
    metrics = summarize_rollout(comp)

    comp_csv = args.out_dir / "slow_state_rollout_vs_simulink.csv"
    diag_csv = args.out_dir / "diagnostics_windows_from_simulink.csv"
    fig_png = args.out_dir / "slow_state_ode_plus_diagnostics_vs_simulink.png"
    model_json = args.out_dir / "slow_state_ode_model.json"
    summary_json = args.out_dir / "summary.json"

    comp.to_csv(comp_csv, index=False)
    diag.to_csv(diag_csv, index=False)
    plot_rollout(
        comp,
        diag,
        fig_png,
        f"Slow-State ODE Proxy + Diagnostics vs Switch-Level Simulink\n{holdout_path.stem}",
    )
    model_json.write_text(json.dumps(model.to_jsonable(), indent=2), encoding="utf-8")
    summary = {
        "schema": "hpt-proxy-ode-v4-slow-state-plus-diagnostics",
        "trace_dir": str(args.trace_dir),
        "out_dir": str(args.out_dir),
        "startup_skip_s": float(args.startup_skip_s),
        "diagnostics_window_ms": float(args.diag_window_ms),
        "ridge": float(args.ridge),
        "n_traces": len(loaded),
        "n_train_traces": len(train_traces),
        "holdout_trace": str(holdout_path),
        "slow_rollout_state_cols": STATE_COLS,
        "action_cols": ACTION_COLS,
        "diagnostics_cols": DIAG_COLS,
        "physical_params_used": phys,
        "metrics_holdout_free_rollout": metrics,
        "notes": [
            "The ODE rolls out only slow states.",
            "Fast internal signals are summarized from Simulink windows as diagnostics; they are not free rollout states.",
            "This is a proxy repair/validation script, not an SAC training run.",
        ],
        "artifacts": {
            "comparison_csv": str(comp_csv),
            "diagnostics_csv": str(diag_csv),
            "figure_png": str(fig_png),
            "model_json": str(model_json),
        },
    }
    summary_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace-dir", type=Path, default=DEFAULT_TRACE_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--holdout", default="pu0825_d120ms")
    parser.add_argument("--startup-skip-s", type=float, default=0.040)
    parser.add_argument("--diag-window-ms", type=float, default=2.0)
    parser.add_argument("--ridge", type=float, default=1e-3)
    args = parser.parse_args()
    print(json.dumps(run(args), indent=2))


if __name__ == "__main__":
    main()
