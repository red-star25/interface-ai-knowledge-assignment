"""Minimal JSON CLI using the same public interface as the official scorer."""
from __future__ import annotations

import argparse
import json
import sys
import zipfile
from dataclasses import asdict
from pathlib import Path

from knowledge.io import load_snapshots
from knowledge.system import KnowledgeSystem


def main() -> int:
    parser = argparse.ArgumentParser(description="Ask the supplied local website snapshots")
    parser.add_argument("--snapshots", required=True, type=Path,
                        help="Folder containing snapshot directories or the original ZIPs")
    parser.add_argument("--as-of", help="Historical ISO date; defaults to latest snapshot")
    parser.add_argument("--conflicts", action="store_true", help="Emit conflict report JSON")
    parser.add_argument("--llm", action="store_true",
                        help="Use optional OpenAI question interpretation; sends the question only")
    parser.add_argument("--llm-debug", action="store_true",
                        help="Print safe LLM status and rewrite details to stderr")
    parser.add_argument("question", nargs="?", help="Question to answer")
    args = parser.parse_args()
    if not args.conflicts and not args.question:
        parser.error("Provide a question or --conflicts")
    if args.llm_debug and not args.llm:
        parser.error("--llm-debug requires --llm")
    try:
        interpreter = None
        if args.llm:
            from knowledge.llm import OpenAIQuestionInterpreter
            interpreter = OpenAIQuestionInterpreter.from_environment()
        system = KnowledgeSystem(query_interpreter=interpreter)
        for snapshot in load_snapshots(args.snapshots):
            system.ingest(snapshot)
        result = ([asdict(c) for c in system.conflicts()] if args.conflicts
                  else asdict(system.answer(args.question, args.as_of)))
        if args.llm_debug:
            print("LLM status: " + interpreter.last_status, file=sys.stderr)
            if interpreter.last_interpretation and interpreter.last_interpretation.rewritten_question:
                print("LLM rewrite: " + interpreter.last_interpretation.rewritten_question,
                      file=sys.stderr)
    except (ValueError, OSError, KeyError, zipfile.BadZipFile) as exc:
        print(f"Input error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
