"""Build paper-facing evidence tables from validated HPT switch-level runs.

This script does not run Simulink.  It reorganizes already-generated
switch-level validation CSV files into tables that are easier to audit in the
paper:

* per-case metrics for SAC-compatible specialists and conventional baseline;
* score-sensitivity checks that separate feasibility from quality;
* reproducibility manifest with hashes for actors and result CSVs.

The default inputs are the current Stage-2 8-row recheck and the 2026-07-25
reduced-boundary 6-row probe.  Missing metrics are left blank rather than
silently invented.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import subprocess
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_STAGE2 = ROOT / "lab/results/hpt_stage2_voltage_survival_matrix_20260722_8row_warmsac_recheck/accepted_specialist_validation.csv"
DEFAULT_REDUCED_PAIRED = ROOT / "lab/results/hpt_reduced_boundary_exact_push_20260725/boundary_case_summary.csv"
DEFAULT_REDUCED_RAW = ROOT / "lab/results/hpt_reduced_boundary_exact_push_20260725/boundary_raw_rows.csv"
DEFAULT_OUT = ROOT / "paper/evidence"


def read_csv(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: List[Dict[str, object]], fieldnames: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def as_float(value: object, default: float = math.nan) -> float:
    if value is None:
        return default
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "missing"}:
        return default
    try:
        return float(text)
    except ValueError:
        return default


def as_bool(value: object) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def rel(path_text: str) -> Path:
    p = Path(path_text)
    if p.is_absolute():
        return p
    return ROOT / p


def sha256_file(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def git_metadata() -> Dict[str, str]:
    def run(args: List[str]) -> str:
        try:
            return subprocess.check_output(args, cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()
        except Exception:
            return ""

    status = run(["git", "status", "--short"])
    return {
        "git_commit": run(["git", "rev-parse", "HEAD"]),
        "git_branch": run(["git", "branch", "--show-current"]),
        "git_dirty": "true" if status else "false",
    }


def find_mode_rows(control_csv: Path) -> Tuple[Dict[str, str], Dict[str, str]]:
    rows = read_csv(control_csv)
    conventional: Dict[str, str] = {}
    specialist: Dict[str, str] = {}
    for row in rows:
        mode = row.get("mode", "").lower()
        if mode == "conventional_dq":
            conventional = row
        elif "sac" in mode or "actor" in mode:
            specialist = row
    return conventional, specialist


def get(row: Dict[str, str], *names: str) -> str:
    for name in names:
        if name in row and str(row[name]).strip() != "":
            return row[name]
    return ""


def metric_row(
    dataset: str,
    case_id: str,
    case: Dict[str, str],
    controller_role: str,
    row: Dict[str, str],
    actor_path: str,
    control_csv: Path,
) -> Dict[str, object]:
    vdc_min = as_float(get(row, "vdc_min", "sac_vdc_min", "conventional_vdc_min"))
    vdc_max = as_float(get(row, "vdc_max", "sac_vdc_max", "conventional_vdc_max"))
    action_max = as_float(get(row, "action_max_abs", "cmd_action_max_abs"))
    voltage_pass = as_bool(get(row, "voltage_survival_pass", f"{controller_role}_voltage_survival_pass"))
    full_pass = as_bool(get(row, "full_frt_pass", f"{controller_role}_full_frt_pass"))
    score = as_float(get(row, "control_score", f"{controller_role}_score"))
    grid_peak = as_float(get(row, "grid_current_peak_pu", f"{controller_role}_grid_current_peak_pu"))

    return {
        "dataset": dataset,
        "case_id": case_id,
        "controller_role": controller_role,
        "topology": get(case, "topology") or get(row, "topology"),
        "fault_family": get(case, "fault_family") or get(row, "gbt_category"),
        "phase_mode": get(case, "phase_mode", "fault_phase_key"),
        "fault_pu": get(case, "fault_pu") or get(row, "fault_pu"),
        "duration_s": get(case, "duration_s") or get(row, "fault_duration_s"),
        "fault_start_s": get(case, "fault_start_s") or get(row, "fault_start_s"),
        "chopper_threshold": get(case, "chopper_threshold"),
        "rchop_scale": get(case, "rchop_scale"),
        "actor_filter_tau": get(case, "actor_filter_tau"),
        "model_path": actor_path if controller_role == "specialist" else "",
        "model_sha256": sha256_file(rel(actor_path)) if actor_path and controller_role == "specialist" else "",
        "control_csv": str(control_csv),
        "control_csv_sha256": sha256_file(control_csv),
        "voltage_survival_pass": voltage_pass,
        "full_frt_pass": full_pass,
        "control_score": score,
        "lv_mean": as_float(get(row, "lv_mean", f"{controller_role}_lv_mean")),
        "lv_recovery_mean": as_float(get(row, "lv_recovery_mean", f"{controller_role}_lv_recovery_mean")),
        "lv_peak": as_float(get(row, "lv_peak", f"{controller_role}_lv_peak")),
        "lv_min": as_float(get(row, "lv_min", f"{controller_role}_lv_min")),
        "fault_lv_min": as_float(get(row, "fault_lv_min", f"{controller_role}_fault_lv_min")),
        "fault_lv_max": as_float(get(row, "fault_lv_max", f"{controller_role}_fault_lv_max")),
        "fault_lv_band_violation_max_pu": as_float(get(row, "fault_lv_band_violation_max_pu", f"{controller_role}_fault_lv_band_violation_max_pu")),
        "fault_lv_band_violation_duration_s": as_float(get(row, "fault_lv_band_violation_duration_s", f"{controller_role}_fault_lv_band_violation_duration_s")),
        "envelope_violation_max_pu": as_float(get(row, "envelope_violation_max_pu", f"{controller_role}_envelope_violation_max_pu")),
        "envelope_violation_duration_s": as_float(get(row, "envelope_violation_duration_s", f"{controller_role}_envelope_violation_duration_s")),
        "recovery_violation_max_pu": as_float(get(row, "recovery_violation_max_pu", f"{controller_role}_recovery_violation_max_pu")),
        "recovery_violation_duration_s": as_float(get(row, "recovery_violation_duration_s", f"{controller_role}_recovery_violation_duration_s")),
        "vdc_min": vdc_min,
        "vdc_max": vdc_max,
        "vdc_lower_margin_v": vdc_min - 650.0 if not math.isnan(vdc_min) else math.nan,
        "vdc_upper_margin_v": 1000.0 - vdc_max if not math.isnan(vdc_max) else math.nan,
        "grid_current_peak_pu": grid_peak,
        "grid_current_margin_pu": 1.5 - grid_peak if not math.isnan(grid_peak) else math.nan,
        "grid_iq_shortfall_max_pu": as_float(get(row, "grid_iq_shortfall_max_pu", f"{controller_role}_grid_iq_shortfall_max_pu")),
        "gbt_reactive_status": get(row, "gbt_reactive_status"),
        "action_max_abs": action_max,
        "cmd_action_max_abs": as_float(get(row, "cmd_action_max_abs")),
        "bridge_modulation_abs_max": as_float(get(row, "bridge_modulation_abs_max")),
        "voltage_reason": get(row, "voltage_survival_reason", f"{controller_role}_reason"),
        "full_frt_reason": get(row, "full_frt_reason"),
    }


def sensitivity_score(row: Dict[str, object], current_w: float, recovery_w: float, fail_penalty: float) -> float:
    lv_mean = as_float(row.get("lv_mean"))
    lv_rec = as_float(row.get("lv_recovery_mean"))
    lv_peak = as_float(row.get("lv_peak"))
    lv_min = as_float(row.get("lv_min"))
    vdc_min = as_float(row.get("vdc_min"))
    vdc_max = as_float(row.get("vdc_max"))
    grid_peak = as_float(row.get("grid_current_peak_pu"))
    env = as_float(row.get("envelope_violation_max_pu"), 0.0)
    rec = as_float(row.get("recovery_violation_max_pu"), 0.0)
    band = as_float(row.get("fault_lv_band_violation_max_pu"), 0.0)
    env_t = as_float(row.get("envelope_violation_duration_s"), 0.0)
    rec_t = as_float(row.get("recovery_violation_duration_s"), 0.0)
    band_t = as_float(row.get("fault_lv_band_violation_duration_s"), 0.0)
    action = as_float(row.get("action_max_abs"))

    score = 0.0
    if not math.isnan(lv_mean):
        score += abs(lv_mean - 207.0) / 5.0
    if not math.isnan(lv_rec):
        score += abs(lv_rec - 207.0) / 5.0
    if not math.isnan(lv_peak):
        score += max(lv_peak - 235.0, 0.0) / 3.0
    if not math.isnan(lv_min):
        score += max(180.0 - lv_min, 0.0) / 3.0
    if not math.isnan(vdc_min):
        score += max(650.0 - vdc_min, 0.0) / 10.0
    if not math.isnan(vdc_max):
        score += max(vdc_max - 1000.0, 0.0) / 10.0
    if not math.isnan(grid_peak):
        score += current_w * max(grid_peak - 1.5, 0.0)
    score += 300.0 * env * env
    score += recovery_w * rec * rec
    score += 180.0 * band * band
    score += 60.0 * env_t
    score += 30.0 * rec_t
    score += 35.0 * band_t
    if not math.isnan(action):
        score += 100.0 * max(action - 0.9501, 0.0)
    if not as_bool(row.get("voltage_survival_pass")):
        score += fail_penalty
    return score


def build_tables(stage2_csv: Path, reduced_paired_csv: Path, reduced_raw_csv: Path) -> Tuple[List[Dict[str, object]], List[Dict[str, object]]]:
    metrics: List[Dict[str, object]] = []
    paired_cases: List[Dict[str, object]] = []

    for case in read_csv(stage2_csv):
        control_csv = rel(case.get("control_csv", ""))
        conventional, specialist = find_mode_rows(control_csv)
        case_id = case.get("case_id", "")
        actor_path = case.get("model_path", "")
        if conventional:
            metrics.append(metric_row("stage2_8row", case_id, case, "conventional", conventional, "", control_csv))
        if specialist:
            metrics.append(metric_row("stage2_8row", case_id, case, "specialist", specialist, actor_path, control_csv))

    reduced_raw = read_csv(reduced_raw_csv)
    raw_by_key: Dict[Tuple[str, str], Dict[str, str]] = {}
    for row in reduced_raw:
        mode = row.get("mode", "").lower()
        role = "conventional" if mode == "conventional_dq" else "specialist" if ("sac" in mode or "actor" in mode) else mode
        raw_by_key[(row.get("case_name", ""), role)] = row

    manifest_by_case = {r.get("case_name", ""): r for r in read_csv(ROOT / "sac/experiments/reduced_boundary_exact_push_20260725.csv")}
    for case in read_csv(reduced_paired_csv):
        case_name = case.get("case_name", "")
        manifest = manifest_by_case.get(case_name, {})
        actor_path = manifest.get("model_path", "")
        for role in ("conventional", "specialist"):
            raw = raw_by_key.get((case_name, role), {})
            if raw:
                metrics.append(metric_row("reduced_boundary_6row", case_name, {**manifest, **case}, role, raw, actor_path, reduced_raw_csv))

    # Build paired rows from metric table.
    by_case: Dict[Tuple[str, str], Dict[str, Dict[str, object]]] = {}
    for row in metrics:
        by_case.setdefault((str(row["dataset"]), str(row["case_id"])), {})[str(row["controller_role"])] = row
    for (dataset, case_id), roles in by_case.items():
        conv = roles.get("conventional", {})
        spec = roles.get("specialist", {})
        if not conv or not spec:
            continue
        conv_pass = as_bool(conv.get("voltage_survival_pass"))
        spec_pass = as_bool(spec.get("voltage_survival_pass"))
        conv_score = as_float(conv.get("control_score"))
        spec_score = as_float(spec.get("control_score"))
        paired_cases.append({
            "dataset": dataset,
            "case_id": case_id,
            "topology": spec.get("topology") or conv.get("topology"),
            "fault_family": spec.get("fault_family") or conv.get("fault_family"),
            "phase_mode": spec.get("phase_mode") or conv.get("phase_mode"),
            "fault_pu": spec.get("fault_pu") or conv.get("fault_pu"),
            "duration_s": spec.get("duration_s") or conv.get("duration_s"),
            "conventional_pass": conv_pass,
            "specialist_pass": spec_pass,
            "conventional_score": conv_score,
            "specialist_score": spec_score,
            "score_delta_specialist_minus_conventional": spec_score - conv_score if not math.isnan(spec_score) and not math.isnan(conv_score) else math.nan,
            "feasibility_improvement": spec_pass and not conv_pass,
            "quality_improvement": spec_pass and conv_pass and spec_score < conv_score,
            "comparison_label": "feasibility_improvement" if spec_pass and not conv_pass else "quality_improvement" if spec_pass and conv_pass and spec_score < conv_score else "no_improvement_or_unresolved",
            "specialist_grid_current_peak_pu": spec.get("grid_current_peak_pu", math.nan),
            "specialist_grid_current_margin_pu": spec.get("grid_current_margin_pu", math.nan),
            "specialist_vdc_lower_margin_v": spec.get("vdc_lower_margin_v", math.nan),
            "specialist_vdc_upper_margin_v": spec.get("vdc_upper_margin_v", math.nan),
            "specialist_full_frt_pass": as_bool(spec.get("full_frt_pass")),
            "specialist_full_frt_reason": spec.get("full_frt_reason", ""),
        })
    return metrics, paired_cases


def build_sensitivity(metrics: List[Dict[str, object]]) -> List[Dict[str, object]]:
    by_case: Dict[Tuple[str, str], Dict[str, Dict[str, object]]] = {}
    for row in metrics:
        by_case.setdefault((str(row["dataset"]), str(row["case_id"])), {})[str(row["controller_role"])] = row

    rows: List[Dict[str, object]] = []
    for (dataset, case_id), roles in by_case.items():
        conv = roles.get("conventional")
        spec = roles.get("specialist")
        if not conv or not spec:
            continue
        for current_w in (25.0, 50.0, 100.0):
            for recovery_w in (60.0, 120.0, 240.0):
                for fail_penalty in (0.0, 50.0, 100.0, 200.0):
                    conv_s = sensitivity_score(conv, current_w, recovery_w, fail_penalty)
                    spec_s = sensitivity_score(spec, current_w, recovery_w, fail_penalty)
                    rows.append({
                        "dataset": dataset,
                        "case_id": case_id,
                        "current_weight": current_w,
                        "recovery_weight": recovery_w,
                        "fail_penalty": fail_penalty,
                        "conventional_sensitivity_score": conv_s,
                        "specialist_sensitivity_score": spec_s,
                        "specialist_beats_under_weights": spec_s < conv_s,
                        "comparison_type": "no_fail_penalty_continuous" if fail_penalty == 0.0 else "with_fail_penalty",
                    })
    return rows


def build_repro(metrics: List[Dict[str, object]], metadata: Dict[str, str]) -> List[Dict[str, object]]:
    rows = []
    seen = set()
    for row in metrics:
        if row.get("controller_role") != "specialist":
            continue
        key = (row.get("dataset"), row.get("case_id"), row.get("model_path"))
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            "dataset": row.get("dataset"),
            "case_id": row.get("case_id"),
            "model_path": row.get("model_path"),
            "model_sha256": row.get("model_sha256"),
            "control_csv": row.get("control_csv"),
            "control_csv_sha256": row.get("control_csv_sha256"),
            "git_commit": metadata.get("git_commit", ""),
            "git_branch": metadata.get("git_branch", ""),
            "git_dirty": metadata.get("git_dirty", ""),
            "training_dataset_sha256": "",
            "teacher_trajectory_sha256": "",
            "exact_training_command": "",
            "exact_validation_command": "",
            "matlab_version": "",
            "solver_settings": "",
            "manifest_status": "needs_completion" if not row.get("model_sha256") else "partial_hash_recorded",
        })
    return rows


def write_report(out_dir: Path, metrics: List[Dict[str, object]], paired: List[Dict[str, object]], sens: List[Dict[str, object]], repro: List[Dict[str, object]]) -> None:
    stage2 = [r for r in paired if r["dataset"] == "stage2_8row"]
    reduced = [r for r in paired if r["dataset"] == "reduced_boundary_6row"]
    sensitivity_failures = [r for r in sens if str(r["specialist_beats_under_weights"]).lower() != "true"]
    text = f"""# HPT Paper Evidence Package

Generated by `sac.summaries.build_hpt_paper_evidence_package`.

## Inputs

- Stage-2 validation: `{DEFAULT_STAGE2}`
- Reduced-boundary paired CSV: `{DEFAULT_REDUCED_PAIRED}`
- Reduced-boundary raw CSV: `{DEFAULT_REDUCED_RAW}`

## Outputs

- `per_case_metrics.csv`
- `paired_case_comparison.csv`
- `score_sensitivity.csv`
- `reproducibility_manifest.csv`

## Summary

- Stage-2 paired cases: {len(stage2)}
- Reduced-boundary paired cases: {len(reduced)}
- Per-controller metric rows: {len(metrics)}
- Specialist reproducibility rows: {len(repro)}
- Score-sensitivity rows: {len(sens)}
- Score-sensitivity rows where specialist does not beat under the tested weights: {len(sensitivity_failures)}

## Interpretation Rules

- `feasibility_improvement` means the specialist passes voltage-survival while conventional fails.
- `quality_improvement` means both pass voltage-survival and the specialist has lower continuous score.
- `full_frt_pass` is not promoted by this package; current full FRT remains outside the L1 voltage-survival claim.
- Blank hashes or commands in `reproducibility_manifest.csv` are unresolved reproducibility gaps, not evidence.
"""
    (out_dir / "REPORT.md").write_text(text, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage2", type=Path, default=DEFAULT_STAGE2)
    parser.add_argument("--reduced-paired", type=Path, default=DEFAULT_REDUCED_PAIRED)
    parser.add_argument("--reduced-raw", type=Path, default=DEFAULT_REDUCED_RAW)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    metrics, paired = build_tables(args.stage2, args.reduced_paired, args.reduced_raw)
    sens = build_sensitivity(metrics)
    repro = build_repro(metrics, git_metadata())

    args.out.mkdir(parents=True, exist_ok=True)
    metric_fields = list(metrics[0].keys()) if metrics else []
    paired_fields = list(paired[0].keys()) if paired else []
    sens_fields = list(sens[0].keys()) if sens else []
    repro_fields = list(repro[0].keys()) if repro else []

    write_csv(args.out / "per_case_metrics.csv", metrics, metric_fields)
    write_csv(args.out / "paired_case_comparison.csv", paired, paired_fields)
    write_csv(args.out / "score_sensitivity.csv", sens, sens_fields)
    write_csv(args.out / "reproducibility_manifest.csv", repro, repro_fields)
    write_report(args.out, metrics, paired, sens, repro)
    print(json.dumps({
        "out": str(args.out),
        "metric_rows": len(metrics),
        "paired_cases": len(paired),
        "score_sensitivity_rows": len(sens),
        "repro_rows": len(repro),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
