"""Tune the switch-level conventional-dq HPT baseline.

This runner evaluates small, named parameter profiles with the canonical
Simulink comparison evaluator.  It is intentionally conservative: each
candidate is validated by switch-level simulation, and no profile is promoted
automatically unless the CSV evidence shows an improvement.
"""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from sac.experiment_metadata import write_experiment_metadata
from sac.gate_contract import (
    CURRENT_FRT_VALIDATOR_SCHEMA,
    classify_result_row,
    summarize_gate_rows,
)


ROOT = Path(__file__).resolve().parents[3]
SIMULINK_DIR = ROOT / "simulink"
CONTROL_DIR = ROOT / "results" / "control_comparison"
RESULTS_ROOT = ROOT / "results" / "conventional_dq_tuning"


@dataclass(frozen=True)
class Candidate:
    topology: str
    name: str
    params: dict[str, float]


FAULTS = [
    ("sag_0p90", 0.90, 0.060),
    ("swell_1p10", 1.10, 0.060),
]


def matlab_string(text: str | Path) -> str:
    return "'" + str(text).replace("\\", "/").replace("'", "''") + "'"


def matlab_struct(params: dict[str, float]) -> str:
    parts: list[str] = []
    for key, value in params.items():
        parts.append(f"'{key}',{float(value):.12g}")
    return "struct(" + ",".join(parts) + ")"


def faults_expr(faults: list[tuple[str, float, float]]) -> str:
    rows = []
    for name, pu, duration in faults:
        rows.append(f"{matlab_string(name)},{pu:.12g},{duration:.12g}")
    return "{" + "; ".join(rows) + "}"


def candidate_set(topology: str) -> list[Candidate]:
    if topology == "topology1":
        base = {
            "hpt_vreg_kp": 4.0,
            "hpt_vreg_ki": 1.0,
            "hpt_vdc_kp": 0.16,
            "hpt_vdc_ki": 0.30,
            "hpt_m_reg_max": 0.65,
            "hpt_sac_reg_max": 0.65,
            "hpt_sac_reg_q_gain": 1.0,
            "hpt_inj_phase_offset": -1.05,
            "hpt_energy_i_kp": 0.65,
            "hpt_energy_i_ki": 90.0,
            "hpt_energy_vff_gain": 1.06,
            "hpt_energy_control_sign": -1.0,
            "hpt_energy_bridge_polarity": -1.0,
        }
        variants = [
            ("t1_base_closed_dq", {}),
            ("t1_more_voltage", {"hpt_vreg_kp": 5.0, "hpt_vreg_ki": 0.8}),
            ("t1_strong_voltage", {"hpt_vreg_kp": 6.0, "hpt_vreg_ki": 0.5}),
            ("t1_phase_m090", {"hpt_vreg_kp": 5.0, "hpt_vreg_ki": 0.8, "hpt_inj_phase_offset": -0.90}),
            ("t1_phase_m120", {"hpt_vreg_kp": 5.0, "hpt_vreg_ki": 0.8, "hpt_inj_phase_offset": -1.20}),
            ("t1_soft_recovery", {"hpt_vreg_kp": 5.0, "hpt_vreg_ki": 0.6, "hpt_conventional_recovery_reg_gain": 2.5, "hpt_conventional_recovery_reg_max": 0.45}),
            ("t1_refine_reg075_k7", {"hpt_vreg_kp": 7.0, "hpt_vreg_ki": 0.3, "hpt_m_reg_max": 0.75, "hpt_sac_reg_max": 0.75}),
            ("t1_refine_reg080_k8", {"hpt_vreg_kp": 8.0, "hpt_vreg_ki": 0.2, "hpt_m_reg_max": 0.80, "hpt_sac_reg_max": 0.80}),
            ("t1_refine_phase095_reg075", {"hpt_vreg_kp": 6.5, "hpt_vreg_ki": 0.3, "hpt_m_reg_max": 0.75, "hpt_sac_reg_max": 0.75, "hpt_inj_phase_offset": -0.95}),
            ("t1_refine_phase090_softrec", {"hpt_vreg_kp": 6.0, "hpt_vreg_ki": 0.3, "hpt_m_reg_max": 0.75, "hpt_sac_reg_max": 0.75, "hpt_inj_phase_offset": -0.90, "hpt_conventional_recovery_reg_gain": 2.0, "hpt_conventional_recovery_reg_max": 0.40}),
        ]
    elif topology == "topology2":
        base = {
            "hpt_vreg_kp": 5.6,
            "hpt_vreg_ki": 0.35,
            "hpt_vdc_kp": 0.05,
            "hpt_vdc_ki": 0.02,
            "hpt_m_reg_max": 0.60,
            "hpt_sac_reg_max": 0.60,
            "hpt_sac_reg_q_gain": -1.0,
            "hpt_inj_phase_offset": -1.05,
            "hpt_energy_i_kp": 0.20,
            "hpt_energy_i_ki": 35.0,
            "hpt_energy_vff_gain": 0.0,
            "hpt_energy_control_sign": -1.0,
            "hpt_energy_bridge_polarity": -1.0,
            "hpt_conventional_energy_scale": 0.15,
            "hpt_conventional_recovery_reg_gain": 2.4,
            "hpt_conventional_recovery_reg_max": 0.44,
        }
        variants = [
            ("t2_base_closed_dq", {}),
            ("t2_less_dc", {"hpt_vdc_kp": 0.30, "hpt_vdc_ki": 0.10}),
            ("t2_more_voltage", {"hpt_vreg_kp": 7.5, "hpt_vreg_ki": 0.6}),
            ("t2_phase_m090", {"hpt_vreg_kp": 7.0, "hpt_vreg_ki": 0.6, "hpt_inj_phase_offset": -0.90}),
            ("t2_phase_m120", {"hpt_vreg_kp": 7.0, "hpt_vreg_ki": 0.6, "hpt_inj_phase_offset": -1.20}),
            ("t2_q_polarity_flip", {"hpt_sac_reg_q_gain": -1.0}),
            ("t2_energy_sign_flip", {"hpt_energy_control_sign": 1.0, "hpt_energy_bridge_polarity": 1.0, "hpt_vdc_kp": 0.30, "hpt_vdc_ki": 0.10}),
            ("t2_refine_qflip_lessdc", {"hpt_sac_reg_q_gain": -1.0, "hpt_vdc_kp": 0.25, "hpt_vdc_ki": 0.08}),
            ("t2_refine_qflip_energyoff", {"hpt_sac_reg_q_gain": -1.0, "hpt_conventional_energy_scale": 0.0, "hpt_vdc_kp": 0.0, "hpt_vdc_ki": 0.0}),
            ("t2_refine_qflip_energysoft", {"hpt_sac_reg_q_gain": -1.0, "hpt_conventional_energy_scale": 0.25, "hpt_vdc_kp": 0.10, "hpt_vdc_ki": 0.04}),
            ("t2_refine_qflip_reg070", {"hpt_sac_reg_q_gain": -1.0, "hpt_m_reg_max": 0.70, "hpt_sac_reg_max": 0.70, "hpt_vdc_kp": 0.20, "hpt_vdc_ki": 0.06}),
            ("t2_currentgate_reg055_energyoff", {"hpt_sac_reg_q_gain": -1.0, "hpt_m_reg_max": 0.55, "hpt_sac_reg_max": 0.55, "hpt_conventional_energy_scale": 0.0, "hpt_vdc_kp": 0.0, "hpt_vdc_ki": 0.0, "hpt_vreg_kp": 5.2, "hpt_vreg_ki": 0.35, "hpt_conventional_recovery_reg_gain": 2.2, "hpt_conventional_recovery_reg_max": 0.40}),
            ("t2_currentgate_reg060_energyoff", {"hpt_sac_reg_q_gain": -1.0, "hpt_m_reg_max": 0.60, "hpt_sac_reg_max": 0.60, "hpt_conventional_energy_scale": 0.0, "hpt_vdc_kp": 0.0, "hpt_vdc_ki": 0.0, "hpt_vreg_kp": 5.6, "hpt_vreg_ki": 0.35, "hpt_conventional_recovery_reg_gain": 2.4, "hpt_conventional_recovery_reg_max": 0.44}),
            ("t2_currentgate_reg065_energy025", {"hpt_sac_reg_q_gain": -1.0, "hpt_m_reg_max": 0.65, "hpt_sac_reg_max": 0.65, "hpt_conventional_energy_scale": 0.25, "hpt_vdc_kp": 0.10, "hpt_vdc_ki": 0.03, "hpt_vreg_kp": 5.8, "hpt_vreg_ki": 0.40, "hpt_conventional_recovery_reg_gain": 2.6, "hpt_conventional_recovery_reg_max": 0.48}),
            ("t2_currentgate_reg050_energy_disabled", {"hpt_sac_energy_enable": 0.0, "hpt_sac_reg_q_gain": -1.0, "hpt_m_reg_max": 0.50, "hpt_sac_reg_max": 0.50, "hpt_vreg_kp": 5.0, "hpt_vreg_ki": 0.30, "hpt_conventional_recovery_reg_gain": 2.0, "hpt_conventional_recovery_reg_max": 0.36}),
            ("t2_currentgate_reg060_energy_disabled", {"hpt_sac_energy_enable": 0.0, "hpt_sac_reg_q_gain": -1.0, "hpt_m_reg_max": 0.60, "hpt_sac_reg_max": 0.60, "hpt_vreg_kp": 5.8, "hpt_vreg_ki": 0.35, "hpt_conventional_recovery_reg_gain": 2.4, "hpt_conventional_recovery_reg_max": 0.44}),
            ("t2_currentgate_vff000_reg060_energyoff", {"hpt_sac_reg_q_gain": -1.0, "hpt_m_reg_max": 0.60, "hpt_sac_reg_max": 0.60, "hpt_conventional_energy_scale": 0.0, "hpt_energy_vff_gain": 0.0, "hpt_energy_i_kp": 0.20, "hpt_energy_i_ki": 35.0, "hpt_vdc_kp": 0.0, "hpt_vdc_ki": 0.0, "hpt_vreg_kp": 5.6, "hpt_vreg_ki": 0.35, "hpt_conventional_recovery_reg_gain": 2.4, "hpt_conventional_recovery_reg_max": 0.44}),
            ("t2_v3_l1_vff000_reg060_chop800", {"hpt_sac_reg_q_gain": -1.0, "hpt_m_reg_max": 0.60, "hpt_sac_reg_max": 0.60, "hpt_conventional_energy_scale": 0.0, "hpt_energy_vff_gain": 0.0, "hpt_energy_i_kp": 0.20, "hpt_energy_i_ki": 35.0, "hpt_vdc_kp": 0.0, "hpt_vdc_ki": 0.0, "hpt_vreg_kp": 5.6, "hpt_vreg_ki": 0.35, "hpt_conventional_recovery_reg_gain": 2.4, "hpt_conventional_recovery_reg_max": 0.44, "hpt_chopper_threshold": 800.0}),
            ("t2_v3_l1_vff000_reg060_chop780_r4", {"hpt_sac_reg_q_gain": -1.0, "hpt_m_reg_max": 0.60, "hpt_sac_reg_max": 0.60, "hpt_conventional_energy_scale": 0.0, "hpt_energy_vff_gain": 0.0, "hpt_energy_i_kp": 0.20, "hpt_energy_i_ki": 35.0, "hpt_vdc_kp": 0.0, "hpt_vdc_ki": 0.0, "hpt_vreg_kp": 5.6, "hpt_vreg_ki": 0.35, "hpt_conventional_recovery_reg_gain": 2.4, "hpt_conventional_recovery_reg_max": 0.44, "hpt_chopper_threshold": 780.0, "hpt_rchop": 4.0}),
            ("t2_v3_l1_energy015_chop780_r4", {"hpt_sac_reg_q_gain": -1.0, "hpt_m_reg_max": 0.60, "hpt_sac_reg_max": 0.60, "hpt_conventional_energy_scale": 0.15, "hpt_energy_vff_gain": 0.0, "hpt_energy_i_kp": 0.20, "hpt_energy_i_ki": 35.0, "hpt_vdc_kp": 0.05, "hpt_vdc_ki": 0.02, "hpt_vreg_kp": 5.6, "hpt_vreg_ki": 0.35, "hpt_conventional_recovery_reg_gain": 2.4, "hpt_conventional_recovery_reg_max": 0.44, "hpt_chopper_threshold": 780.0, "hpt_rchop": 4.0}),
            ("t2_v3_l1_energy015_fixed_plant", {"hpt_sac_reg_q_gain": -1.0, "hpt_m_reg_max": 0.60, "hpt_sac_reg_max": 0.60, "hpt_conventional_energy_scale": 0.15, "hpt_energy_vff_gain": 0.0, "hpt_energy_i_kp": 0.20, "hpt_energy_i_ki": 35.0, "hpt_vdc_kp": 0.05, "hpt_vdc_ki": 0.02, "hpt_vreg_kp": 5.6, "hpt_vreg_ki": 0.35, "hpt_conventional_recovery_reg_gain": 2.4, "hpt_conventional_recovery_reg_max": 0.44}),
            ("t2_v3_l1_energy030_fixed_plant", {"hpt_sac_reg_q_gain": -1.0, "hpt_m_reg_max": 0.60, "hpt_sac_reg_max": 0.60, "hpt_conventional_energy_scale": 0.30, "hpt_energy_vff_gain": 0.0, "hpt_energy_i_kp": 0.20, "hpt_energy_i_ki": 35.0, "hpt_vdc_kp": 0.10, "hpt_vdc_ki": 0.04, "hpt_vreg_kp": 5.6, "hpt_vreg_ki": 0.35, "hpt_conventional_recovery_reg_gain": 2.4, "hpt_conventional_recovery_reg_max": 0.44}),
            ("t2_v3_l1_energy050_fixed_plant", {"hpt_sac_reg_q_gain": -1.0, "hpt_m_reg_max": 0.60, "hpt_sac_reg_max": 0.60, "hpt_conventional_energy_scale": 0.50, "hpt_energy_vff_gain": 0.0, "hpt_energy_i_kp": 0.20, "hpt_energy_i_ki": 35.0, "hpt_vdc_kp": 0.15, "hpt_vdc_ki": 0.05, "hpt_vreg_kp": 5.6, "hpt_vreg_ki": 0.35, "hpt_conventional_recovery_reg_gain": 2.4, "hpt_conventional_recovery_reg_max": 0.44}),
            ("t2_currentgate_vff020_reg058_energyoff", {"hpt_sac_reg_q_gain": -1.0, "hpt_m_reg_max": 0.58, "hpt_sac_reg_max": 0.58, "hpt_conventional_energy_scale": 0.0, "hpt_energy_vff_gain": 0.20, "hpt_energy_i_kp": 0.25, "hpt_energy_i_ki": 45.0, "hpt_vdc_kp": 0.0, "hpt_vdc_ki": 0.0, "hpt_vreg_kp": 5.5, "hpt_vreg_ki": 0.34, "hpt_conventional_recovery_reg_gain": 2.35, "hpt_conventional_recovery_reg_max": 0.42}),
            ("t2_currentgate_vff020_reg060_qm095", {"hpt_sac_reg_q_gain": -0.95, "hpt_m_reg_max": 0.60, "hpt_sac_reg_max": 0.60, "hpt_conventional_energy_scale": 0.0, "hpt_energy_vff_gain": 0.20, "hpt_energy_i_kp": 0.25, "hpt_energy_i_ki": 45.0, "hpt_vdc_kp": 0.0, "hpt_vdc_ki": 0.0, "hpt_vreg_kp": 5.6, "hpt_vreg_ki": 0.35, "hpt_conventional_recovery_reg_gain": 2.4, "hpt_conventional_recovery_reg_max": 0.44}),
            ("t2_currentgate_vff020_reg060_qm090", {"hpt_sac_reg_q_gain": -0.90, "hpt_m_reg_max": 0.60, "hpt_sac_reg_max": 0.60, "hpt_conventional_energy_scale": 0.0, "hpt_energy_vff_gain": 0.20, "hpt_energy_i_kp": 0.25, "hpt_energy_i_ki": 45.0, "hpt_vdc_kp": 0.0, "hpt_vdc_ki": 0.0, "hpt_vreg_kp": 5.6, "hpt_vreg_ki": 0.35, "hpt_conventional_recovery_reg_gain": 2.4, "hpt_conventional_recovery_reg_max": 0.44}),
            ("t2_currentgate_vff020_reg060_energyoff", {"hpt_sac_reg_q_gain": -1.0, "hpt_m_reg_max": 0.60, "hpt_sac_reg_max": 0.60, "hpt_conventional_energy_scale": 0.0, "hpt_energy_vff_gain": 0.20, "hpt_energy_i_kp": 0.25, "hpt_energy_i_ki": 45.0, "hpt_vdc_kp": 0.0, "hpt_vdc_ki": 0.0, "hpt_vreg_kp": 5.6, "hpt_vreg_ki": 0.35, "hpt_conventional_recovery_reg_gain": 2.4, "hpt_conventional_recovery_reg_max": 0.44}),
            ("t2_currentgate_vff040_reg065_energy025", {"hpt_sac_reg_q_gain": -1.0, "hpt_m_reg_max": 0.65, "hpt_sac_reg_max": 0.65, "hpt_conventional_energy_scale": 0.25, "hpt_energy_vff_gain": 0.40, "hpt_energy_i_kp": 0.30, "hpt_energy_i_ki": 55.0, "hpt_vdc_kp": 0.10, "hpt_vdc_ki": 0.03, "hpt_vreg_kp": 5.8, "hpt_vreg_ki": 0.40, "hpt_conventional_recovery_reg_gain": 2.6, "hpt_conventional_recovery_reg_max": 0.48}),
        ]
    else:
        raise ValueError(f"unknown topology {topology}")

    out: list[Candidate] = []
    for name, patch in variants:
        params = dict(base)
        params.update(patch)
        out.append(Candidate(topology=topology, name=name, params=params))
    return out


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as f:
        return [dict(row) for row in csv.DictReader(f)]


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


def row_float(row: dict[str, str], key: str, default: float = 0.0) -> float:
    try:
        value = row.get(key, "")
        if value in {"", "NaN", "nan"}:
            return default
        return float(value)
    except Exception:
        return default


def row_bool(row: dict[str, str], key: str) -> bool:
    return str(row.get(key, "")).strip().lower() in {"1", "1.0", "true"}


def latest_control_csv(label: str, after: float) -> Path:
    pattern = f"control_comparison_*{label}*.csv"
    matches = [
        p for p in CONTROL_DIR.glob(pattern)
        if p.stat().st_mtime >= after - 1.0
    ]
    if not matches:
        raise FileNotFoundError(f"No control CSV for label {label}")
    return max(matches, key=lambda p: p.stat().st_mtime)


def run_candidate(
    candidate: Candidate,
    campaign_id: str,
    timeout_s: int,
    faults: list[tuple[str, float, float]],
    voltage_survival_current_gate: bool,
) -> dict[str, Any]:
    label = f"{campaign_id}_{candidate.topology}_{candidate.name}"
    statement = (
        f"cd({matlab_string(SIMULINK_DIR)}); "
        f"hpt_compare_topology={matlab_string(candidate.topology)}; "
        "hpt_compare_scenario_type='fault'; "
        "hpt_compare_modes=string({'conventional_dq'}); "
        f"hpt_compare_faults={faults_expr(faults)}; "
        "hpt_compare_conventional_profile='tuned_v2_l1'; "
        f"hpt_compare_voltage_survival_current_gate={str(bool(voltage_survival_current_gate)).lower()}; "
        f"hpt_compare_conventional_params={matlab_struct(candidate.params)}; "
        f"hpt_compare_run_label={matlab_string(label)}; "
        "run(fullfile(pwd,'evaluators','eval_hpt_v2_control_comparison.m'));"
    )
    started = time.time()
    proc = subprocess.run(
        ["matlab", "-batch", statement],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=timeout_s,
        check=False,
    )
    row: dict[str, Any] = {
        "campaign_id": campaign_id,
        "topology": candidate.topology,
        "candidate": candidate.name,
        "returncode": proc.returncode,
        "runtime_s": round(time.time() - started, 3),
        "params_json": json.dumps(candidate.params, sort_keys=True),
    }
    if proc.returncode != 0:
        row.update({
            "ok": False,
            "error": proc.stderr[-2000:] or proc.stdout[-2000:],
        })
        return row

    csv_path = latest_control_csv(label, started)
    rows = read_csv(csv_path)
    gate_summary = summarize_gate_rows(rows, "L1")
    pass_count = int(gate_summary["target_gate_pass_count"])
    full_count = sum(row_bool(r, "full_frt_pass") for r in rows)
    score_sum = sum(row_float(r, "control_score", 999.0) for r in rows)
    env_max = max(row_float(r, "envelope_violation_max_pu", 0.0) for r in rows)
    rec_max = max(row_float(r, "recovery_violation_max_pu", 0.0) for r in rows)
    vdc_min = min(row_float(r, "vdc_min", 0.0) for r in rows)
    vdc_max = max(row_float(r, "vdc_max", 0.0) for r in rows)
    action_max = max(row_float(r, "cmd_action_max_abs", 0.0) for r in rows)
    row.update({
        "ok": True,
        "csv": str(csv_path),
        "case_count": len(rows),
        "validator_schema": CURRENT_FRT_VALIDATOR_SCHEMA,
        "target_gate": "L1",
        "scenario_valid_count": gate_summary["scenario_valid_count"],
        "eligible_count": gate_summary["eligible_count"],
        "invalid_scenario_count": gate_summary["invalid_scenario_count"],
        "stale_schema_count": gate_summary["stale_schema_count"],
        "l1_pass_count": gate_summary["l1_pass_count"],
        "l2_pass_count": gate_summary["l2_pass_count"],
        "l3_pass_count": gate_summary["l3_pass_count"],
        "voltage_survival_pass_count": pass_count,
        "full_frt_pass_count": full_count,
        "control_score_sum": score_sum,
        "envelope_violation_max_pu": env_max,
        "recovery_violation_max_pu": rec_max,
        "vdc_min": vdc_min,
        "vdc_max": vdc_max,
        "cmd_action_max_abs": action_max,
    })
    return row


def rank_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        not bool(row.get("ok")),
        int(row.get("stale_schema_count") or 0) > 0,
        -int(row.get("eligible_count") or 0),
        -int(row.get("voltage_survival_pass_count") or 0),
        float(row.get("envelope_violation_max_pu") or 999.0)
        + float(row.get("recovery_violation_max_pu") or 999.0),
        float(row.get("control_score_sum") or 999999.0),
    )


def write_report(run_dir: Path, rows: list[dict[str, Any]], ranked: list[dict[str, Any]]) -> None:
    lines = [
        "# Conventional dq Tuning Campaign",
        "",
        f"Run directory: `{run_dir}`",
        "",
        "## Ranked Candidates",
        "",
        "| rank | topology | candidate | valid | L1 pass | L2 | L3 | score_sum | load-quality max | recovery max | vdc_min | vdc_max | csv |",
        "|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for idx, row in enumerate(ranked, 1):
        lines.append(
            f"| {idx} | {row.get('topology')} | {row.get('candidate')} | "
            f"{row.get('scenario_valid_count', '')}/{row.get('case_count', '')} | "
            f"{row.get('l1_pass_count', '')}/{row.get('eligible_count', '')} | "
            f"{row.get('l2_pass_count', '')} | {row.get('l3_pass_count', '')} | "
            f"{float(row.get('control_score_sum', 0.0)):.3f} | "
            f"{float(row.get('envelope_violation_max_pu', 0.0)):.6f} | "
            f"{float(row.get('recovery_violation_max_pu', 0.0)):.6f} | "
            f"{float(row.get('vdc_min', 0.0)):.3f} | "
            f"{float(row.get('vdc_max', 0.0)):.3f} | "
            f"`{Path(str(row.get('csv', ''))).name}` |"
        )
    lines += [
        "",
        "## Interpretation",
        "",
        "- Only rows with the current v3 schema and `scenario_valid=true` are eligible.",
        "- `l1_pass_count` is the current promotion-relevant gate.",
        "- L2/L3 are tracked but cannot be promoted until their measurement interfaces exist.",
        "- A candidate is only a strong baseline candidate after switch-level CSV evidence, not from proxy-only ranking.",
    ]
    (run_dir / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-id", default="")
    parser.add_argument("--topology", choices=["topology1", "topology2", "all"], default="all")
    parser.add_argument("--case-limit", type=int, default=0)
    parser.add_argument("--name-filter", default="", help="Run only candidates whose name contains this text.")
    parser.add_argument("--fault-name", default="", help="Optional single fault name, e.g. sag_0p90.")
    parser.add_argument("--fault-pu", type=float, default=float("nan"))
    parser.add_argument("--fault-duration-s", type=float, default=0.060)
    parser.add_argument("--voltage-survival-current-gate", action="store_true")
    parser.add_argument("--timeout-s", type=int, default=360)
    args = parser.parse_args()

    campaign_id = args.campaign_id or "hpt_conventional_dq_tuning_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = RESULTS_ROOT / campaign_id
    run_dir.mkdir(parents=True, exist_ok=True)

    topologies = ["topology1", "topology2"] if args.topology == "all" else [args.topology]
    candidates = [c for top in topologies for c in candidate_set(top)]
    if args.name_filter:
        candidates = [c for c in candidates if args.name_filter in c.name]
    if args.case_limit > 0:
        candidates = candidates[: args.case_limit]
    faults = FAULTS
    if args.fault_name:
        if args.fault_pu != args.fault_pu:
            raise ValueError("--fault-pu is required when --fault-name is set")
        faults = [(args.fault_name, float(args.fault_pu), float(args.fault_duration_s))]

    config = {
        "campaign_id": campaign_id,
        "topology": args.topology,
        "faults": faults,
        "candidate_count": len(candidates),
        "timeout_s": args.timeout_s,
        "voltage_survival_current_gate": bool(args.voltage_survival_current_gate),
        "validator_schema": CURRENT_FRT_VALIDATOR_SCHEMA,
        "target_gate": "L1",
        "conventional_profile": "tuned_v2_l1",
    }
    write_experiment_metadata(
        run_dir,
        experiment_name="hpt_conventional_dq_tuning",
        config=config,
        topology_models={
            "topology1": ROOT / "simulink" / "topology1" / "hpt_v2_1to1_switchlevel.slx",
            "topology2": ROOT / "simulink" / "topology2" / "hpt_v2_topology2_paper.slx",
        },
    )

    rows: list[dict[str, Any]] = []
    for idx, candidate in enumerate(candidates, 1):
        print(f"[{idx}/{len(candidates)}] {candidate.topology} {candidate.name}", flush=True)
        row = run_candidate(
            candidate,
            campaign_id,
            args.timeout_s,
            faults,
            bool(args.voltage_survival_current_gate),
        )
        rows.append(row)
        write_csv(run_dir / "summary_partial.csv", rows)
        print(json.dumps(row, ensure_ascii=False), flush=True)

    ranked = sorted(rows, key=rank_key)
    write_csv(run_dir / "summary.csv", rows)
    write_csv(run_dir / "ranked.csv", ranked)
    write_report(run_dir, rows, ranked)
    print(f"Saved {run_dir / 'ranked.csv'}", flush=True)


if __name__ == "__main__":
    main()
