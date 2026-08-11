"""Measure whether proxy reward ranks actions like switch-level FRT metrics.

This script uses the switch-level FRT calibration matrix as the source of truth.
For each fixed-action matrix row it:

1. predicts LV/Vdc from the calibrated proxy lookup tables and computes a
   reward-like proxy score;
2. computes a switch-level score from the matrix LV/Vdc metrics;
3. reports ranking alignment within each topology/category/action-mode group.

It is intentionally a ranking test, not a proof that proxy values are numerically
identical to Simulink.  The question is whether proxy SAC would be pushed toward
the same action choices that the switch-level plant prefers.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from sac.calibration.calibrate_hpt_frt_proxy_from_matrix import validate_envelope_columns
from sac.calibration.measure_hpt_frt_proxy_gap import analyze as proxy_gap_analyze


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / ".git").exists() or (parent / "pyproject.toml").exists():
            return parent
    return Path(__file__).resolve().parents[3]


ROOT = _repo_root()
DEFAULT_MATRIX_DIR = ROOT / "lab" / "results" / "hpt_v2_frt_calibration_matrix"
DEFAULT_OUT_DIR = ROOT / "lab" / "results" / "hpt_v2_reward_alignment"
DEFAULT_CALIBRATION = ROOT / "sac" / "hpt_proxy_calibration.json"


def latest_csv(directory: Path, pattern: str) -> Path:
    files = sorted(Path(directory).glob(pattern), key=lambda p: p.stat().st_mtime)
    if not files:
        raise FileNotFoundError(f"No files matching {pattern} in {directory}")
    return files[-1]


def read_csv(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with Path(path).open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for raw in reader:
            row: dict[str, Any] = {}
            for key, value in raw.items():
                if value in ("", None):
                    row[key] = value
                    continue
                try:
                    row[key] = float(value)
                except ValueError:
                    row[key] = value
            rows.append(row)
    return rows


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    keys: list[str] = []
    for row in rows:
        for key in row:
            if key not in keys:
                keys.append(key)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


def f(row: dict[str, Any], key: str, default: float = 0.0) -> float:
    value = row.get(key, default)
    if value in ("", None):
        return float(default)
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, str):
        lower = value.strip().lower()
        if lower in {"true", "yes"}:
            return 1.0
        if lower in {"false", "no"}:
            return 0.0
    return float(value)


def s(row: dict[str, Any], key: str, default: str = "") -> str:
    value = row.get(key, default)
    return str(value)


def finite_or(row: dict[str, Any], key: str, default: float = 0.0) -> float:
    value = f(row, key, default)
    if not np.isfinite(value):
        return float(default)
    return value


def has_numeric(row: dict[str, Any], key: str) -> bool:
    if key not in row or row.get(key) in ("", None):
        return False
    try:
        return bool(np.isfinite(float(row[key])))
    except (TypeError, ValueError):
        return False


def row_numeric(row: dict[str, Any], preferred: str, fallback: str, default: float = 0.0) -> float:
    if has_numeric(row, preferred):
        return f(row, preferred)
    if has_numeric(row, fallback):
        return f(row, fallback)
    return float(default)


def action_tuple(row: dict[str, Any]) -> tuple[float, float, float, float]:
    return (
        row_numeric(row, "cmd_m_reg_d_mean", "raw_m_reg_d", f(row, "reg_d_mean", 0.0)),
        row_numeric(row, "cmd_m_reg_q_mean", "raw_m_reg_q", f(row, "reg_q_mean", 0.0)),
        row_numeric(row, "cmd_m_energy_d_mean", "raw_m_energy_d", f(row, "energy_d_mean", 0.0)),
        row_numeric(row, "cmd_m_energy_q_mean", "raw_m_energy_q", f(row, "energy_q_mean", 0.0)),
    )


def mode_label(row: dict[str, Any]) -> str:
    mode = s(row, "mode")
    if mode == "reg_sweep" and abs(f(row, "raw_m_reg_q")) > 1e-9:
        return "reg_q_sweep"
    return mode


def proxy_reward_from_lookup(row: dict[str, Any], proxy_row: dict[str, Any]) -> dict[str, float]:
    """Fast proxy reward-like score from calibrated lookup predictions.

    This mirrors the dominant reward terms in ``HPTVoltageSACEnv.step`` without
    doing a dynamic rollout.  It is a ranking diagnostic for matrix actions.
    """

    lv_mean = f(proxy_row, "proxy_lv_pu", np.nan)
    lv_recovery = f(proxy_row, "proxy_lv_recovery_pu", lv_mean)
    lv_peak = f(proxy_row, "proxy_lv_peak_pu", lv_mean)
    lv_min = f(proxy_row, "proxy_lv_min_pu", lv_mean)
    lv_unbalance = finite_or(proxy_row, "proxy_lv_unbalance_pu", 0.0)
    vdc_mean = f(proxy_row, "proxy_vdc_pu", np.nan)
    vdc_min = f(proxy_row, "proxy_vdc_min_pu", vdc_mean)
    vdc_max = f(proxy_row, "proxy_vdc_max_pu", vdc_mean)
    if not np.isfinite(lv_mean) or not np.isfinite(vdc_mean):
        return {
            "proxy_return": float("nan"),
            "proxy_mean_reward": float("nan"),
            "proxy_lv_mean": lv_mean,
            "proxy_vdc_mean": vdc_mean,
            "proxy_vdc_soft": float("nan"),
            "proxy_wrong_sign": float("nan"),
            "proxy_grid_iq_shortfall_pu": float("nan"),
            "proxy_grid_iq_wrong_sign": float("nan"),
            "proxy_grid_current_peak_pu": float("nan"),
            "proxy_grid_current_violation_pu": float("nan"),
            "proxy_envelope_violation_max_pu": float("nan"),
            "proxy_recovery_violation_max_pu": float("nan"),
        }

    reg_d, reg_q, energy_d, energy_q = action_tuple(row)
    reg_mag = float(math.hypot(reg_d, reg_q))
    energy_mag = float(math.hypot(energy_d, energy_q))
    action_max = finite_or(proxy_row, "proxy_action_max_abs", max(reg_mag, energy_mag))
    vdc_soft = max(0.0, 0.95 - vdc_mean) + max(0.0, vdc_mean - 1.12)
    grid = f(row, "grid_pu", f(row, "fault_pu", 1.0))
    wrong_sign = float((grid < 0.92 and reg_d < -1e-9) or (grid > 1.08 and reg_d > 1e-9))
    grid_iq_shortfall = finite_or(proxy_row, "proxy_grid_iq_shortfall_pu", 0.0)
    grid_iq_wrong_sign = bool(finite_or(proxy_row, "proxy_grid_iq_wrong_sign", 0.0) >= 0.5)
    grid_current = finite_or(proxy_row, "proxy_grid_current_peak_pu", 0.0)
    grid_current_violation = max(0.0, grid_current - 1.5)
    fault_band_violation = finite_or(proxy_row, "proxy_fault_lv_band_violation_max_pu", 0.0)
    envelope_violation = finite_or(proxy_row, "proxy_envelope_violation_max_pu", 0.0)
    recovery_violation = finite_or(proxy_row, "proxy_recovery_violation_max_pu", 0.0)

    lv_v = 207.0 * lv_mean
    lv_recovery_v = 207.0 * lv_recovery
    lv_peak_v = 207.0 * lv_peak
    lv_min_v = 207.0 * lv_min
    vdc_min_v = 800.0 * vdc_min
    vdc_max_v = 800.0 * vdc_max

    score = 0.0
    score += abs(lv_v - 207.0) / 5.0
    score += abs(lv_recovery_v - 207.0) / 5.0
    score += max(0.0, lv_peak_v - 235.0) / 3.0
    score += max(0.0, 180.0 - lv_min_v) / 3.0
    score += max(0.0, 650.0 - vdc_min_v) / 10.0
    score += max(0.0, vdc_max_v - 1000.0) / 10.0
    score += 40.0 * grid_iq_shortfall
    score += 50.0 * grid_current_violation
    score += 180.0 * max(0.0, fault_band_violation) ** 2
    score += 120.0 * max(0.0, recovery_violation) ** 2
    score += max(0.0, action_max - 0.9501) * 100.0
    if grid_iq_wrong_sign:
        score += 8.0
    if wrong_sign:
        score += 8.0
    reward = -score

    return {
        "proxy_return": float(reward),
        "proxy_mean_reward": float(reward),
        "proxy_lv_mean": float(lv_mean),
        "proxy_lv_recovery": float(lv_recovery),
        "proxy_lv_peak": float(lv_peak),
        "proxy_lv_min": float(lv_min),
        "proxy_lv_unbalance": float(lv_unbalance),
        "proxy_vdc_mean": float(vdc_mean),
        "proxy_vdc_min": float(vdc_min),
        "proxy_vdc_max": float(vdc_max),
        "proxy_vdc_soft": float(vdc_soft),
        "proxy_wrong_sign": float(wrong_sign),
        "proxy_action_max_abs": float(action_max),
        "proxy_grid_iq_shortfall_pu": float(grid_iq_shortfall),
        "proxy_grid_iq_wrong_sign": float(grid_iq_wrong_sign),
        "proxy_grid_current_peak_pu": float(grid_current),
        "proxy_grid_current_violation_pu": float(grid_current_violation),
        "proxy_fault_lv_band_violation_max_pu": float(fault_band_violation),
        "proxy_envelope_violation_max_pu": float(envelope_violation),
        "proxy_recovery_violation_max_pu": float(recovery_violation),
    }


def switch_score(row: dict[str, Any]) -> dict[str, float | str]:
    """Lower score means better switch-level behavior."""

    lv_mean = f(row, "lv_pu_mean")
    lv_recovery = f(row, "lv_recovery_pu_mean", lv_mean)
    lv_peak = f(row, "lv_peak_pu", lv_mean)
    lv_min = f(row, "lv_min_pu", lv_mean)
    vdc_mean = f(row, "vdc_pu_mean", f(row, "vdc_mean") / 800.0)
    vdc_min = f(row, "vdc_min_pu", f(row, "vdc_min") / 800.0)
    vdc_max = f(row, "vdc_max_pu", f(row, "vdc_max") / 800.0)
    unbalance = f(row, "lv_unbalance_pu")
    action_max = f(row, "action_max_abs")
    grid_iq_shortfall = finite_or(row, "grid_iq_shortfall_max_pu", 0.0)
    grid_current_peak = finite_or(row, "grid_current_peak_pu", 0.0)
    grid_current_violation = max(0.0, grid_current_peak - 1.5)
    grid_iq_wrong_sign = bool(finite_or(row, "grid_iq_wrong_sign", 0.0) > 0.5)
    fault_band_violation = finite_or(row, "fault_lv_band_violation_max_pu", 0.0)
    envelope_violation = finite_or(row, "envelope_violation_max_pu", 0.0)
    recovery_violation = finite_or(row, "recovery_violation_max_pu", 0.0)

    lv_peak_limit = 235.0 / 207.0
    lv_min_limit = 180.0 / 207.0
    vdc_min_limit = 650.0 / 800.0
    vdc_max_limit = 930.0 / 800.0

    official_score = finite_or(row, "control_score", float("nan"))
    if np.isfinite(official_score):
        score = official_score
    else:
        score = 0.0
        score += 90.0 * (lv_mean - 1.0) ** 2
        score += 60.0 * (lv_recovery - 1.0) ** 2
        score += 45.0 * unbalance * unbalance
        score += 55.0 * max(0.0, vdc_min_limit - vdc_min) ** 2
        score += 35.0 * max(0.0, vdc_max - vdc_max_limit) ** 2
        score += 45.0 * max(0.0, lv_peak - lv_peak_limit) ** 2
        score += 45.0 * max(0.0, lv_min_limit - lv_min) ** 2
        score += 40.0 * grid_iq_shortfall
        score += 50.0 * grid_current_violation
        score += 180.0 * max(0.0, fault_band_violation) ** 2
        score += 300.0 * max(0.0, envelope_violation) ** 2
        score += 120.0 * max(0.0, recovery_violation) ** 2
        if grid_iq_wrong_sign:
            score += 8.0
        score += 0.20 * action_max * action_max

    cmd_reg_d, _cmd_reg_q, _cmd_ed, _cmd_eq = action_tuple(row)
    wrong_sign = (
        (f(row, "grid_pu", 1.0) < 0.92 and cmd_reg_d < -1e-9)
        or (f(row, "grid_pu", 1.0) > 1.08 and cmd_reg_d > 1e-9)
    )
    if wrong_sign and not np.isfinite(official_score):
        score += 8.0

    reactive_ok_token = s(row, "gbt_reactive_pass", "")
    if reactive_ok_token == "":
        reactive_ok = True
    else:
        reactive_ok = reactive_ok_token.lower() in {"1", "true"}
    current_ok_token = s(row, "gbt_grid_current_limit_pass", "")
    if current_ok_token == "":
        current_ok = grid_current_peak <= 1.5 if grid_current_peak > 0.0 else True
    else:
        current_ok = current_ok_token.lower() in {"1", "true"}

    derived_pass_like = (
        0.97 <= lv_recovery <= 1.03
        and lv_peak <= lv_peak_limit
        and lv_min >= lv_min_limit
        and vdc_min >= vdc_min_limit
        and vdc_max <= vdc_max_limit
        and action_max <= 0.9501
        and reactive_ok
        and current_ok
        and fault_band_violation <= 1e-3
        and envelope_violation <= 1e-3
        and recovery_violation <= 1e-3
        and not wrong_sign
        and not grid_iq_wrong_sign
    )
    # When the source matrix comes from the current switch-level evaluator,
    # its voltage-survival flag is the authoritative gate.  The historical
    # reward-alignment heuristic above intentionally remains as a fallback for
    # legacy matrices, but must not silently replace the active validator with
    # a narrower 0.97--1.03 pu recovery-mean rule.
    explicit_pass = s(row, "voltage_survival_pass", "").strip().lower()
    if explicit_pass in {"1", "1.0", "true", "yes", "y"}:
        pass_like = True
    elif explicit_pass in {"0", "0.0", "false", "no", "n"}:
        pass_like = False
    else:
        pass_like = derived_pass_like

    return {
        "switch_score": float(score),
        "switch_reward_like": float(-score),
        "switch_pass_like": float(pass_like),
        "switch_wrong_sign": float(wrong_sign),
        "switch_grid_iq_shortfall_pu": float(grid_iq_shortfall),
        "switch_grid_iq_wrong_sign": float(grid_iq_wrong_sign),
        "switch_grid_current_peak_pu": float(grid_current_peak),
        "switch_grid_current_violation_pu": float(grid_current_violation),
        "switch_fault_lv_band_violation_max_pu": float(fault_band_violation),
        "switch_envelope_violation_max_pu": float(envelope_violation),
        "switch_recovery_violation_max_pu": float(recovery_violation),
        "switch_lv_mean": lv_mean,
        "switch_lv_recovery": lv_recovery,
        "switch_lv_peak": lv_peak,
        "switch_lv_min": lv_min,
        "switch_vdc_mean": vdc_mean,
        "switch_vdc_min": vdc_min,
        "switch_vdc_max": vdc_max,
    }


def rankdata(values: np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(len(values), dtype=float)
    i = 0
    while i < len(values):
        j = i + 1
        while j < len(values) and values[order[j]] == values[order[i]]:
            j += 1
        avg = 0.5 * (i + j - 1) + 1.0
        ranks[order[i:j]] = avg
        i = j
    return ranks


def pearson(x: np.ndarray, y: np.ndarray) -> float:
    if len(x) < 2:
        return float("nan")
    x0 = x - np.mean(x)
    y0 = y - np.mean(y)
    denom = float(np.sqrt(np.sum(x0 * x0) * np.sum(y0 * y0)))
    if denom <= 0:
        return float("nan")
    return float(np.sum(x0 * y0) / denom)


def spearman(x: np.ndarray, y: np.ndarray) -> float:
    return pearson(rankdata(x), rankdata(y))


def kendall_tau(x: np.ndarray, y: np.ndarray) -> float:
    n = len(x)
    if n < 2:
        return float("nan")
    concordant = 0
    discordant = 0
    for i in range(n - 1):
        dx = x[i + 1 :] - x[i]
        dy = y[i + 1 :] - y[i]
        prod = dx * dy
        concordant += int(np.sum(prod > 0))
        discordant += int(np.sum(prod < 0))
    denom = concordant + discordant
    if denom == 0:
        return float("nan")
    return float((concordant - discordant) / denom)


def alignment_group_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
    """Group action-ranking diagnostics at the scenario level when possible.

    For fixed-action and joint-sweep rows, the proxy must rank candidate
    actions for the same physical fault case.  Aggregating A/B/C phases or
    several durations into one top-1 ranking asks a different question and can
    incorrectly mark a family proxy as weak.  Conventional-dq rows generally
    have one action per case, so they remain aggregated as a baseline diagnostic.
    """

    mode = s(row, "mode")
    fault = s(row, "fault")
    if mode != "conventional_dq" and fault:
        return (s(row, "topology"), s(row, "category"), mode, fault)
    return (s(row, "topology"), s(row, "category"), mode, "")


def group_label(row: dict[str, Any]) -> str:
    fault = s(row, "fault")
    base = f"{row['topology']} {row['category']} {row['mode']}"
    return f"{base} {fault}" if fault else base


def summarize(detail: list[dict[str, Any]], *, top_k: int = 3) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in detail:
        groups[alignment_group_key(row)].append(row)

    summary: list[dict[str, Any]] = []
    for (topology, category, mode, fault), rows in sorted(groups.items()):
        n = len(rows)
        proxy_all = np.asarray([f(row, "proxy_return", float("nan")) for row in rows], dtype=float)
        switch_reward_all = np.asarray(
            [f(row, "switch_reward_like", float("nan")) for row in rows],
            dtype=float,
        )
        switch_score_all = np.asarray(
            [f(row, "switch_score", float("nan")) for row in rows],
            dtype=float,
        )
        finite_mask = (
            np.isfinite(proxy_all)
            & np.isfinite(switch_reward_all)
            & np.isfinite(switch_score_all)
        )
        finite_indices = np.flatnonzero(finite_mask)
        finite_n = int(finite_indices.size)
        if finite_n == 0:
            pass_like_all = np.asarray([f(row, "switch_pass_like") for row in rows], dtype=float)
            summary.append(
                {
                    "topology": topology,
                    "category": category,
                    "mode": mode,
                    "fault": fault,
                    "n": n,
                    "finite_proxy_n": 0,
                    "spearman_proxy_vs_switch_reward": float("nan"),
                    "kendall_proxy_vs_switch_reward": float("nan"),
                    "top_k": 0,
                    "top_k_overlap": 0,
                    "top_k_overlap_fraction": 0.0,
                    "proxy_top1_switch_rank": -1,
                    "proxy_top1_switch_percentile": float("nan"),
                    "proxy_top1_switch_score": float("nan"),
                    "switch_best_score": (
                        float(np.nanmin(switch_score_all))
                        if np.any(np.isfinite(switch_score_all))
                        else float("nan")
                    ),
                    "switch_pass_like_count": int(np.nansum(pass_like_all > 0.5)),
                    "proxy_topk_pass_like_count": 0,
                }
            )
            continue
        finite_rows = [rows[int(i)] for i in finite_indices]
        proxy = proxy_all[finite_mask]
        switch_reward = switch_reward_all[finite_mask]
        switch_score = switch_score_all[finite_mask]
        k = min(top_k, n)
        k = min(k, finite_n)
        proxy_order = np.argsort(-proxy)
        switch_order = np.argsort(switch_score)
        proxy_top = set(int(i) for i in proxy_order[:k])
        switch_top = set(int(i) for i in switch_order[:k])
        proxy_top1 = int(proxy_order[0]) if finite_n else -1
        sim_rank_of_proxy_top1 = int(np.where(switch_order == proxy_top1)[0][0] + 1) if finite_n else -1
        percentile = (
            float((sim_rank_of_proxy_top1 - 1) / max(finite_n - 1, 1))
            if sim_rank_of_proxy_top1 > 0
            else float("nan")
        )
        pass_like = np.asarray([f(row, "switch_pass_like") for row in finite_rows], dtype=float)
        summary.append(
            {
                "topology": topology,
                "category": category,
                "mode": mode,
                "fault": fault,
                "n": n,
                "finite_proxy_n": finite_n,
                "spearman_proxy_vs_switch_reward": spearman(proxy, switch_reward),
                "kendall_proxy_vs_switch_reward": kendall_tau(proxy, switch_reward),
                "top_k": k,
                "top_k_overlap": len(proxy_top & switch_top),
                "top_k_overlap_fraction": len(proxy_top & switch_top) / max(k, 1),
                "proxy_top1_switch_rank": sim_rank_of_proxy_top1,
                "proxy_top1_switch_percentile": percentile,
                "proxy_top1_switch_score": f(finite_rows[proxy_top1], "switch_score") if finite_n else float("nan"),
                "switch_best_score": float(np.min(switch_score)) if finite_n else float("nan"),
                "switch_pass_like_count": int(np.sum(pass_like > 0.5)),
                "proxy_topk_pass_like_count": int(np.sum(pass_like[list(proxy_order[:k])] > 0.5)),
            }
        )
    return summary


def make_detail(rows: list[dict[str, Any]], calibration: dict[str, Any]) -> list[dict[str, Any]]:
    proxy_rows = proxy_gap_analyze(rows, calibration)
    if len(proxy_rows) != len(rows):
        raise RuntimeError(f"Proxy gap rows mismatch: {len(proxy_rows)} != {len(rows)}")
    detail: list[dict[str, Any]] = []
    for idx, (row, proxy_row) in enumerate(zip(rows, proxy_rows)):
        cmd_reg_d, cmd_reg_q, cmd_energy_d, cmd_energy_q = action_tuple(row)
        proxy = proxy_reward_from_lookup(row, proxy_row)
        switch = switch_score(row)
        detail.append(
            {
                "row_index": idx,
                "topology": s(row, "topology"),
                "category": s(row, "category"),
                "fault": s(row, "fault", s(row, "case_name")),
                "mode": mode_label(row),
                "grid_pu": f(row, "grid_pu", f(row, "fault_pu")),
                "raw_m_reg_d": f(row, "raw_m_reg_d"),
                "raw_m_reg_q": f(row, "raw_m_reg_q"),
                "raw_m_energy_d": f(row, "raw_m_energy_d"),
                "raw_m_energy_q": f(row, "raw_m_energy_q"),
                "cmd_m_reg_d": cmd_reg_d,
                "cmd_m_reg_q": cmd_reg_q,
                "cmd_m_energy_d": cmd_energy_d,
                "cmd_m_energy_q": cmd_energy_q,
                "meas_reg_d": row_numeric(row, "meas_reg_d_mean", "reg_d_mean", 0.0),
                "meas_reg_q": row_numeric(row, "meas_reg_q_mean", "reg_q_mean", 0.0),
                "meas_energy_d": row_numeric(row, "meas_energy_d_mean", "energy_d_mean", 0.0),
                "meas_energy_q": row_numeric(row, "meas_energy_q_mean", "energy_q_mean", 0.0),
                "reg_d_mean": f(row, "reg_d_mean"),
                "reg_q_mean": f(row, "reg_q_mean"),
                "energy_d_mean": f(row, "energy_d_mean"),
                "energy_q_mean": f(row, "energy_q_mean"),
                "proxy_gap_lv_pu": f(proxy_row, "err_lv_pu", np.nan),
                "proxy_gap_vdc_pu": f(proxy_row, "err_vdc_pu", np.nan),
                **proxy,
                **switch,
            }
        )
    return detail


def write_report(path: Path, matrix_csv: Path, summary: list[dict[str, Any]]) -> None:
    weak = [
        row
        for row in summary
        if f(row, "finite_proxy_n", 0.0) <= 0.0
        or (
            math.isnan(f(row, "spearman_proxy_vs_switch_reward", float("nan")))
            or f(row, "spearman_proxy_vs_switch_reward") < 0.65
            or f(row, "top_k_overlap_fraction") < 1.0 / max(1.0, f(row, "top_k"))
            or f(row, "proxy_top1_switch_percentile") > 0.50
        )
    ]
    lines = [
        "# HPT Reward Alignment Report",
        "",
        f"- Updated: `{datetime.now().isoformat(timespec='seconds')}`",
        f"- Matrix: `{matrix_csv}`",
        f"- Groups: `{len(summary)}`",
        f"- Weak groups: `{len(weak)}`",
        "",
        "## Criteria",
        "",
        "- Higher proxy return should align with higher switch-level reward-like score.",
        "- Spearman >= 0.65 is treated as a useful monotonic ranking.",
        "- Proxy top-1 should not land in the worse half of the switch-level ranking.",
        "- Top-3 overlap should be nonzero when at least three actions exist.",
        "",
        "## Summary",
        "",
    ]
    for row in summary:
        lines.append(
            "- "
            f"`{group_label(row)}` "
            f"n `{row['n']}` finite `{int(f(row, 'finite_proxy_n', 0))}` "
            f"rho `{f(row, 'spearman_proxy_vs_switch_reward'):.3f}` "
            f"tau `{f(row, 'kendall_proxy_vs_switch_reward'):.3f}` "
            f"top{int(f(row, 'top_k'))} overlap `{int(f(row, 'top_k_overlap'))}` "
            f"proxy-top1 rank `{int(f(row, 'proxy_top1_switch_rank'))}/{int(f(row, 'n'))}` "
            f"pass-like `{int(f(row, 'switch_pass_like_count'))}`"
        )
    if weak:
        lines.extend(["", "## Weak Groups", ""])
        for row in weak:
            lines.append(
                "- "
                f"`{group_label(row)}`: "
                f"finite `{int(f(row, 'finite_proxy_n', 0))}/{int(f(row, 'n'))}`, "
                f"rho `{f(row, 'spearman_proxy_vs_switch_reward'):.3f}`, "
                f"top1 percentile `{f(row, 'proxy_top1_switch_percentile'):.3f}`, "
                f"top-k overlap `{int(f(row, 'top_k_overlap'))}/{int(f(row, 'top_k'))}`"
            )
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--matrix-csv", type=Path, default=None)
    parser.add_argument("--matrix-dir", type=Path, default=DEFAULT_MATRIX_DIR)
    parser.add_argument("--calibration", type=Path, default=DEFAULT_CALIBRATION)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument(
        "--allow-legacy-no-envelope",
        action="store_true",
        help="Allow pre-envelope matrix CSVs. Use only for forensic debugging.",
    )
    args = parser.parse_args()

    matrix_csv = args.matrix_csv or latest_csv(args.matrix_dir, "frt_calibration_matrix_*.csv")
    validate_envelope_columns([matrix_csv], allow_legacy=args.allow_legacy_no_envelope)
    rows = read_csv(matrix_csv)
    calibration = json.loads(Path(args.calibration).read_text(encoding="utf-8"))
    detail = make_detail(rows, calibration)
    summary = summarize(detail)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(matrix_csv).stem.replace("frt_calibration_matrix_", "reward_alignment_")
    detail_csv = args.out_dir / f"{stem}_detail.csv"
    summary_csv = args.out_dir / f"{stem}_summary.csv"
    summary_json = args.out_dir / f"{stem}_summary.json"
    report_md = args.out_dir / f"{stem}_REPORT.md"
    write_csv(detail_csv, detail)
    write_csv(summary_csv, summary)
    summary_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    write_report(report_md, matrix_csv, summary)
    print(
        json.dumps(
            {
                "detail_csv": str(detail_csv),
                "summary_csv": str(summary_csv),
                "report_md": str(report_md),
            },
            indent=2,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()


