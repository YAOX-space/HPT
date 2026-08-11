"""Build a DAgger-style anchor from actor rollouts and teacher traces.

For each matched pair, observations come from the actor-visited switch-level
trace, while target actions come from a strong-dq teacher trace at the same
control-step time.  This repairs the common closed-loop mismatch where plain
BC is accurate on teacher states but drifts on actor-visited states.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import numpy as np


OBS_DIM = 24
ACT_DIM = 4


def parse_pair(text: str) -> tuple[Path, Path]:
    if "::" not in text:
        raise ValueError("--pair must be ACTOR_TRACE::TEACHER_TRACE")
    left, right = text.split("::", 1)
    return Path(left), Path(right)


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def row_float(row: dict[str, str], key: str, default: float = 0.0) -> float:
    try:
        return float(row.get(key, default))
    except Exception:
        return float(default)


def allowed_zone(row: dict[str, str], zones: set[str]) -> bool:
    if not zones:
        return True
    return str(row.get("window_zone") or "").strip().lower() in zones


def build_pair_samples(
    actor_trace: Path,
    teacher_trace: Path,
    *,
    zones: set[str],
    repeat: int,
) -> tuple[np.ndarray, np.ndarray, dict]:
    actor_rows = [row for row in read_rows(actor_trace) if allowed_zone(row, zones)]
    teacher_rows = read_rows(teacher_trace)
    teacher_by_t = {round(row_float(row, "t"), 9): row for row in teacher_rows}

    obs_samples: list[np.ndarray] = []
    action_samples: list[np.ndarray] = []
    matched = 0
    skipped = 0
    for actor_row in actor_rows:
        t_key = round(row_float(actor_row, "t"), 9)
        teacher_row = teacher_by_t.get(t_key)
        if teacher_row is None:
            skipped += 1
            continue
        obs = np.asarray(
            [row_float(actor_row, f"obs_{idx:02d}") for idx in range(1, OBS_DIM + 1)],
            dtype=np.float32,
        )
        action = np.asarray(
            [row_float(teacher_row, f"action_{idx:02d}") for idx in range(1, ACT_DIM + 1)],
            dtype=np.float32,
        )
        for _ in range(max(1, int(repeat))):
            obs_samples.append(obs)
            action_samples.append(action)
        matched += 1
    if not obs_samples:
        raise RuntimeError(f"No matched samples for {actor_trace} vs {teacher_trace}")
    return (
        np.asarray(obs_samples, dtype=np.float32),
        np.asarray(action_samples, dtype=np.float32),
        {
            "actor_trace": str(actor_trace),
            "teacher_trace": str(teacher_trace),
            "actor_rows": len(actor_rows),
            "matched_rows": matched,
            "skipped_rows": skipped,
            "repeat": int(max(1, repeat)),
            "samples": int(len(obs_samples)),
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pair", action="append", required=True)
    parser.add_argument("--out-npz", type=Path, required=True)
    parser.add_argument("--out-json", type=Path, default=None)
    parser.add_argument("--zones", default="fault,recovery")
    parser.add_argument("--repeat", type=int, default=8)
    args = parser.parse_args()

    zones = {part.strip().lower() for part in args.zones.split(",") if part.strip()}
    obs_parts: list[np.ndarray] = []
    action_parts: list[np.ndarray] = []
    pair_summaries: list[dict] = []
    for pair_text in args.pair:
        actor_trace, teacher_trace = parse_pair(pair_text)
        obs, actions, summary = build_pair_samples(
            actor_trace,
            teacher_trace,
            zones=zones,
            repeat=args.repeat,
        )
        obs_parts.append(obs)
        action_parts.append(actions)
        pair_summaries.append(summary)

    observations = np.concatenate(obs_parts, axis=0)
    actions = np.concatenate(action_parts, axis=0)
    args.out_npz.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(args.out_npz, observations=observations, actions=actions)
    summary = {
        "schema": "hpt-proxy2-dagger-anchor-v1",
        "dataset": str(args.out_npz),
        "samples": int(observations.shape[0]),
        "zones": sorted(zones),
        "pair_count": len(pair_summaries),
        "teacher_source": "strong_dq_same_time_action_on_actor_visited_state",
        "action_mean": [float(x) for x in actions.mean(axis=0)],
        "action_min": [float(x) for x in actions.min(axis=0)],
        "action_max": [float(x) for x in actions.max(axis=0)],
        "pairs": pair_summaries,
    }
    out_json = args.out_json or args.out_npz.with_suffix(".json")
    out_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
