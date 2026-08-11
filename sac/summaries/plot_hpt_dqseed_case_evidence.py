"""Collect and plot dq-seeded SAC case evidence.

For one case in a dq-seeded boundary campaign, this script produces:

1. four modulation-command traces for strong dq, SAC initial, and SAC after
   fine-tuning;
2. switch-level LV RMS and DC-link traces for the same three controllers;
3. the proxy-side SAC reward convergence curve recorded during fine-tuning.

The plots are diagnostic evidence.  Pass/fail claims must still use the
switch-level validator CSVs from the campaign.
"""
from __future__ import annotations

import argparse
import csv
import json
import shutil
import time
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import pandas as pd

from sac.campaigns.run_hpt_t2_balanced_lvrt_dq_seeded_boundary import (
    BoundaryCase,
    COMMON_MODEL_PARAMS,
    ROOT,
    SIMULINK,
    TRACE_DIR,
    _matlab_string,
    _matlab_struct,
    export_actor_for_simulink,
    latest_file,
    mat_vector,
    phase_pu_vector,
    run_logged,
)
from sac.summaries.summarize_sac_reward_traces import summarize_sac_reward_traces


RESULTS = ROOT / "lab" / "results"


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size <= 0:
        return pd.DataFrame()
    return pd.read_csv(path)


def _safe_label(text: str) -> str:
    import re

    return re.sub(r"[^A-Za-z0-9_]+", "_", str(text)).strip("_")


def _load_campaign(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "campaign_summary.json"
    if not path.exists():
        path = run_dir / "campaign_progress.json"
    if not path.exists():
        raise FileNotFoundError(f"No campaign summary/progress JSON in {run_dir}")
    return json.loads(path.read_text(encoding="utf-8"))


def _select_case(summary: dict[str, Any], case_label: str | None) -> dict[str, Any]:
    cases = list(summary.get("cases", []))
    if not cases and summary.get("metadata", {}).get("schema") == "hpt-family-specialist-matrix-v1":
        metadata = summary["metadata"]
        anchor_path = Path(summary.get("anchor_summary", {}).get("dataset", ""))
        anchor_json = anchor_path.with_suffix(".json") if str(anchor_path) else Path()
        trace_by_label: dict[str, str] = {}
        if anchor_json.exists():
            anchor_summary = json.loads(anchor_json.read_text(encoding="utf-8"))
            for item in anchor_summary.get("per_case", []):
                label = str(item.get("case", {}).get("label", ""))
                if label:
                    trace_by_label[label] = str(item.get("trace_csv", ""))
        for spec in metadata.get("eval_cases", []):
            label = str(spec.get("label", ""))
            cases.append(
                {
                    "label": label,
                    "case": spec,
                    "dq_trace_csv": trace_by_label.get(label, ""),
                    "dq_seed_model": summary.get("seed_model", ""),
                    "sac_finetune_model": summary.get("sac_model", ""),
                    "family_label": metadata.get("family_label", ""),
                    "family_training_dir": str(
                        RESULTS / f"{metadata.get('run_id', '')}_{metadata.get('family_label', '')}_sac"
                    ),
                }
            )
    if not cases:
        raise RuntimeError("Campaign summary contains no cases")
    if not case_label:
        return cases[0]
    for case in cases:
        if str(case.get("label")) == case_label:
            return case
    labels = ", ".join(str(case.get("label")) for case in cases)
    raise ValueError(f"Case {case_label!r} not found. Available: {labels}")


def _boundary_case_from_summary(case: dict[str, Any]) -> BoundaryCase:
    spec = case["case"]
    return BoundaryCase(
        fault_pu=float(spec["fault_pu"]),
        duration_s=float(spec["duration_s"]),
        topology=str(spec.get("topology", "topology2")),
        category=str(spec.get("category", "LVRT")).upper(),
        phase_key=str(spec.get("phase_key", "abc")).lower(),
        family_label=str(spec.get("family_label", case.get("label", "hpt_case"))),
    )


def _case_title(case: BoundaryCase) -> str:
    phase_names = {
        "abc": "balanced ABC",
        "balanced": "balanced ABC",
        "a": "A-phase",
        "b": "B-phase",
        "c": "C-phase",
        "ab": "AB-phase",
        "bc": "BC-phase",
        "ca": "CA-phase",
        "ac": "CA-phase",
    }
    phase = phase_names.get(case.phase_key.lower(), case.phase_key)
    return (
        f"{case.topology} {phase} {case.category.upper()} "
        f"{case.fault_pu:.3f} pu / {case.duration_ms} ms"
    )


def _collect_actor_trace(
    *,
    model_path: Path,
    case: dict[str, Any],
    out_dir: Path,
    label: str,
    fault_start_s: float,
    actor_filter_tau: float,
    sample_stride: int,
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    export_actor_for_simulink(model_path, out_dir, label)
    bcase = _boundary_case_from_summary(case)
    runner = out_dir / f"collect_{label}.m"
    runner.write_text(
        "\n".join(
            [
                f"cd('{_matlab_string(ROOT)}');",
                f"addpath(genpath('{_matlab_string(SIMULINK)}'));",
                f'hpt_trace_topology = "{bcase.topology}";',
                f"hpt_trace_fault_pu = {bcase.fault_pu:.12g};",
                f"hpt_trace_fault_phase_pu = {mat_vector(phase_pu_vector(bcase))};",
                f"hpt_trace_fault_duration = {bcase.duration_s:.12g};",
                f"hpt_trace_fault_start = {float(fault_start_s):.12g};",
                "hpt_trace_fault_stop_margin = 0.125;",
                "hpt_trace_policy_mode = 1.0;",
                "hpt_trace_actor_select_mode = 3.0;",
                f"hpt_trace_actor_filter_tau = {float(actor_filter_tau):.12g};",
                f"hpt_trace_model_params = {_matlab_struct(COMMON_MODEL_PARAMS)};",
                f'hpt_trace_run_label = "{label}";',
                f"hpt_trace_sample_stride = {int(sample_stride)};",
                f"run('{_matlab_string(SIMULINK / 'collectors' / 'collect_hpt_v2_trajectory_trace.m')}');",
            ]
        ),
        encoding="utf-8",
    )
    before = time.time()
    run_logged(
        ["matlab", "-batch", f"run('{_matlab_string(runner)}')"],
        cwd=ROOT,
        log_path=out_dir / f"{label}_collect.log",
    )
    trace = latest_file(
        f"trajectory_trace_{bcase.topology}_{label}_*.csv",
        after=before,
        directory=TRACE_DIR,
    )
    archived = out_dir / trace.name
    shutil.copy2(trace, archived)
    return archived


def _find_sac_training_dir(case_label: str, sac_model: Path) -> Path | None:
    candidates = sorted(
        RESULTS.glob(f"{case_label}_currentaware_sacft_*"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    target = str(sac_model)
    for candidate in candidates:
        metadata = candidate / "metadata.json"
        summary = candidate / "summary.json"
        for path in (metadata, summary):
            if path.exists() and target in path.read_text(encoding="utf-8", errors="ignore"):
                return candidate
    return candidates[0] if candidates else None


def _find_training_dir_for_case(case: dict[str, Any], sac_model: Path) -> Path | None:
    family_dir = Path(str(case.get("family_training_dir", "")))
    if family_dir.exists():
        return family_dir
    return _find_sac_training_dir(str(case.get("label", "")), sac_model)


def _plot_actions(traces: dict[str, pd.DataFrame], out_png: Path, *, fault_start: float, fault_clear: float, title: str) -> None:
    names = [
        ("action_01", r"$m_{reg,d}$"),
        ("action_02", r"$m_{reg,q}$"),
        ("action_03", r"$m_{energy,d}$"),
        ("action_04", r"$m_{energy,q}$"),
    ]
    colors = {
        "strong dq closed-loop": "#d95f02",
        "SAC initial from dq": "#7570b3",
        "SAC after fine-tune": "#1b9e77",
    }
    fig, axes = plt.subplots(4, 1, figsize=(10.5, 8.2), sharex=True, constrained_layout=True)
    for ax, (col, label) in zip(axes, names):
        for trace_label, df in traces.items():
            if df.empty or col not in df:
                continue
            ax.plot(df["t"], df[col], lw=1.5, label=trace_label, color=colors.get(trace_label))
        ax.axvspan(fault_start, fault_clear, color="#f4cccc", alpha=0.35)
        ax.axhline(0.0, color="black", lw=0.6, alpha=0.4)
        ax.set_ylabel(label)
        ax.grid(True, alpha=0.25)
    axes[0].legend(frameon=False, ncol=3, loc="upper right")
    axes[-1].set_xlabel("Time (s)")
    fig.suptitle(f"Controller modulation commands per control step\n{title}", fontsize=12)
    fig.savefig(out_png, dpi=220, bbox_inches="tight")
    plt.close(fig)


def _plot_voltage(traces: dict[str, pd.DataFrame], out_png: Path, *, fault_start: float, fault_clear: float, title: str) -> None:
    colors = {
        "strong dq closed-loop": "#d95f02",
        "SAC initial from dq": "#7570b3",
        "SAC after fine-tune": "#1b9e77",
    }
    fig, axes = plt.subplots(2, 1, figsize=(10.5, 6.0), sharex=True, constrained_layout=True)
    for trace_label, df in traces.items():
        if df.empty:
            continue
        if "lv_rms_inst" in df:
            axes[0].plot(df["t"], df["lv_rms_inst"], lw=1.5, label=trace_label, color=colors.get(trace_label))
        if "vdc_inst" in df:
            axes[1].plot(df["t"], df["vdc_inst"], lw=1.5, label=trace_label, color=colors.get(trace_label))
    for ax in axes:
        ax.axvspan(fault_start, fault_clear, color="#f4cccc", alpha=0.35)
        ax.grid(True, alpha=0.25)
    axes[0].axhspan(176, 238, color="#d9ead3", alpha=0.25, label="fault LV band")
    axes[0].set_ylabel("LV RMS (V)")
    axes[1].axhspan(650, 1000, color="#fff2cc", alpha=0.35, label="DC-link survival band")
    axes[1].set_ylabel("Vdc (V)")
    axes[1].set_xlabel("Time (s)")
    axes[0].legend(frameon=False, ncol=3, loc="upper right")
    axes[1].legend(frameon=False, ncol=3, loc="upper right")
    fig.suptitle(f"Switch-level voltage/DC-link traces\n{title}", fontsize=12)
    fig.savefig(out_png, dpi=220, bbox_inches="tight")
    plt.close(fig)


def _plot_reward(training_dir: Path | None, out_png: Path, title: str) -> dict[str, Any]:
    if training_dir is None:
        out_png.write_text("No SAC training directory found", encoding="utf-8")
        return {"training_dir": "", "reward_rows": 0}
    summary = summarize_sac_reward_traces(training_dir)
    combined = Path(summary["combined_reward_csv"])
    df = _read_csv(combined)
    fig, ax = plt.subplots(figsize=(9.5, 4.8), constrained_layout=True)
    if df.empty:
        ax.text(0.5, 0.5, "No reward trace found", ha="center", va="center")
        ax.set_axis_off()
    else:
        df = df.copy()
        df["episode_return"] = pd.to_numeric(df["episode_return"], errors="coerce")
        df["episode"] = range(1, len(df) + 1)
        ax.plot(df["episode"], df["episode_return"], marker="o", lw=1.6, label="episode return")
        if len(df) >= 4:
            ax.plot(
                df["episode"],
                df["episode_return"].rolling(4, min_periods=1).mean(),
                lw=2.2,
                label="rolling mean (4)",
            )
        ax.set_xlabel("Episode")
        ax.set_ylabel("Proxy SAC episode return")
        ax.grid(True, alpha=0.25)
        ax.legend(frameon=False)
    fig.suptitle(f"SAC fine-tune convergence\n{title}", fontsize=12)
    fig.savefig(out_png, dpi=220, bbox_inches="tight")
    plt.close(fig)
    return {"training_dir": str(training_dir), "reward_rows": int(len(df))}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("campaign_run_dir", type=Path)
    parser.add_argument("--case-label", default="")
    parser.add_argument("--fault-start-s", type=float, default=0.08)
    parser.add_argument("--actor-filter-tau", type=float, default=0.001)
    parser.add_argument("--sample-stride", type=int, default=100)
    args = parser.parse_args()

    run_dir = args.campaign_run_dir.resolve()
    summary = _load_campaign(run_dir)
    case = _select_case(summary, args.case_label or None)
    case_label = str(case["label"])
    bcase = _boundary_case_from_summary(case)
    fault_start = float(args.fault_start_s)
    fault_clear = fault_start + bcase.duration_s
    title = _case_title(bcase)

    out_dir = run_dir / "figures" / case_label
    out_dir.mkdir(parents=True, exist_ok=True)

    dq_trace = Path(case["dq_trace_csv"])
    seed_trace = _collect_actor_trace(
        model_path=Path(case["dq_seed_model"]),
        case=case,
        out_dir=out_dir,
        label=f"{case_label}_sac_initial_dqseed",
        fault_start_s=fault_start,
        actor_filter_tau=args.actor_filter_tau,
        sample_stride=args.sample_stride,
    )
    sac_trace = _collect_actor_trace(
        model_path=Path(case["sac_finetune_model"]),
        case=case,
        out_dir=out_dir,
        label=f"{case_label}_sac_after_finetune",
        fault_start_s=fault_start,
        actor_filter_tau=args.actor_filter_tau,
        sample_stride=args.sample_stride,
    )
    traces = {
        "strong dq closed-loop": _read_csv(dq_trace),
        "SAC initial from dq": _read_csv(seed_trace),
        "SAC after fine-tune": _read_csv(sac_trace),
    }

    actions_png = out_dir / f"{case_label}_action_trace_comparison.png"
    voltage_png = out_dir / f"{case_label}_voltage_vdc_trace_comparison.png"
    reward_png = out_dir / f"{case_label}_sac_reward_convergence.png"
    _plot_actions(traces, actions_png, fault_start=fault_start, fault_clear=fault_clear, title=title)
    _plot_voltage(traces, voltage_png, fault_start=fault_start, fault_clear=fault_clear, title=title)
    training_dir = _find_training_dir_for_case(case, Path(case["sac_finetune_model"]))
    reward_summary = _plot_reward(training_dir, reward_png, title)

    manifest = {
        "schema": "hpt-dqseed-case-evidence-figures-v1",
        "campaign_run_dir": str(run_dir),
        "case_label": case_label,
        "title": title,
        "dq_trace_csv": str(dq_trace),
        "sac_initial_trace_csv": str(seed_trace),
        "sac_after_trace_csv": str(sac_trace),
        "actions_png": str(actions_png),
        "voltage_png": str(voltage_png),
        "reward_png": str(reward_png),
        "reward_summary": reward_summary,
    }
    (out_dir / "figure_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
