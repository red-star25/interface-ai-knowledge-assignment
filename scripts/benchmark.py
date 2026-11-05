"""Measure local ingestion and query latency; emit aggregate metadata only."""
from __future__ import annotations

import argparse
import json
import resource
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from knowledge.io import load_snapshots  # noqa: E402
from solution import build  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshots", required=True, type=Path)
    parser.add_argument("--questions", required=True, type=Path)
    parser.add_argument("--repeat", type=int, default=3)
    args = parser.parse_args()
    if args.repeat < 1:
        parser.error("--repeat must be positive")
    start = time.perf_counter()
    snapshots = load_snapshots(args.snapshots)
    load_seconds = time.perf_counter() - start
    system = build()
    start = time.perf_counter()
    for snapshot in snapshots:
        system.ingest(snapshot)
    ingest_seconds = time.perf_counter() - start
    questions = [json.loads(line) for line in args.questions.read_text().splitlines() if line.strip()]
    elapsed = []
    for _ in range(args.repeat):
        for item in questions:
            start = time.perf_counter()
            system.answer(item["question"], item.get("as_of"))
            elapsed.append(time.perf_counter() - start)
    elapsed.sort()
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    print(json.dumps({
        "python": sys.version.split()[0], "snapshot_count": len(snapshots),
        "page_observations": sum(len(s.pages) for s in snapshots),
        "load_seconds": round(load_seconds, 4), "ingest_seconds": round(ingest_seconds, 4),
        "queries": len(elapsed), "median_ms": round(statistics.median(elapsed) * 1000, 3),
        "p95_ms": round(elapsed[min(len(elapsed) - 1, int(.95 * len(elapsed)))] * 1000, 3),
        "max_ms": round(max(elapsed) * 1000, 3),
        "peak_rss_mib": round(rss / (1024 * 1024 if sys.platform == "darwin" else 1024), 2),
        "external_api_calls": 0,
    }, indent=2))


if __name__ == "__main__":
    main()
