"""Run the organizer's unmodified evaluator from a separately supplied kit."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kit", required=True, type=Path, help="Authorized participant kit directory")
    parser.add_argument("--out", type=Path, default=Path("results/public"))
    args = parser.parse_args()
    kit = args.kit.resolve()
    submission = Path(__file__).resolve().parents[1]
    harness = kit / "harness" / "run_eval.py"
    if not harness.is_file() or not (kit / "eval" / "public_eval.jsonl").is_file():
        parser.error("The kit must contain the original harness and public evaluation file")
    return subprocess.call([
        sys.executable, str(harness), "--submission", str(submission),
        "--snapshots", str(kit / "snapshots"), "--eval", str(kit / "eval" / "public_eval.jsonl"),
        "--out", str(args.out.resolve()),
    ], cwd=kit)


if __name__ == "__main__":
    raise SystemExit(main())
