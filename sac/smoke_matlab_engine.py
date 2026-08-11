"""Smoke runner for the version-2 HPT MATLAB/Simulink interface.

The runner provides a single Python entry point for checking that MATLAB Engine
can reach the version-2 Simulink tests. Use ``--dry-run`` in CI or on machines
without MATLAB. Use ``--runner engine`` for the preferred research workflow.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SIMULINK_DIR = ROOT / "simulink"

TESTS = {
    "interface": "run(fullfile(pwd,'tests','test_hpt_v2_sac_interface.m'));",
    "topology1": "run(fullfile(pwd,'topology1','test_hpt_v2_1to1_pure_switchlevel.m'));",
    "topology2": "run(fullfile(pwd,'topology2','test_hpt_v2_topology2_pure_switchlevel.m'));",
}


def build_statement(test: str) -> str:
    if test not in TESTS:
        raise KeyError(f"Unknown smoke test: {test}")
    sim_dir = str(SIMULINK_DIR).replace("\\", "/")
    return f"cd('{sim_dir}'); {TESTS[test]}"


def run_engine(test: str) -> dict[str, Any]:
    try:
        import matlab.engine  # type: ignore[import-not-found]
    except Exception as exc:
        return {"ok": False, "runner": "engine", "error": f"matlab_engine_import_failed: {exc}"}

    started = time.time()
    eng = matlab.engine.start_matlab()
    try:
        eng.cd(str(SIMULINK_DIR), nargout=0)
        eng.eval(TESTS[test], nargout=0)
    finally:
        eng.quit()
    return {
        "ok": True,
        "runner": "engine",
        "test": test,
        "elapsed_s": round(time.time() - started, 3),
    }


def run_batch(test: str, matlab_cmd: str, timeout_s: int) -> dict[str, Any]:
    started = time.time()
    proc = subprocess.run(
        [matlab_cmd, "-batch", build_statement(test)],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        timeout=timeout_s,
        check=False,
    )
    return {
        "ok": proc.returncode == 0,
        "runner": "batch",
        "test": test,
        "returncode": proc.returncode,
        "elapsed_s": round(time.time() - started, 3),
        "stdout_tail": proc.stdout[-4000:],
        "stderr_tail": proc.stderr[-4000:],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test", choices=sorted(TESTS), default="interface")
    parser.add_argument("--runner", choices=["engine", "batch"], default="engine")
    parser.add_argument("--matlab-cmd", default="matlab")
    parser.add_argument("--timeout-s", type=int, default=900)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.dry_run:
        result = {
            "ok": True,
            "dry_run": True,
            "root": str(ROOT),
            "simulink_dir": str(SIMULINK_DIR),
            "runner": args.runner,
            "test": args.test,
            "statement": build_statement(args.test),
        }
    elif args.runner == "engine":
        result = run_engine(args.test)
    else:
        result = run_batch(args.test, args.matlab_cmd, args.timeout_s)

    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
