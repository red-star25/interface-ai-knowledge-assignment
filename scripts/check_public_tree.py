"""Audit all Git revisions for prohibited inputs and common secret formats.

This complements manual review; no pattern scanner can prove absence of secrets.
It reads Git objects, so ignored local participant files are never opened.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import PurePosixPath


PRIVATE_DIRS = {"snapshots", "snapshots_zip", "eval", "harness", "starter", "results", "indexes", "cache", "data"}
SECRET_PATTERNS = [
    re.compile(rb"(?:sk-(?:proj-)?[A-Za-z0-9_-]{24,}|gh[pousr]_[A-Za-z0-9]{30,})"),
    re.compile(rb"AKIA[0-9A-Z]{16}"),
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
]


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", *args])


def private_path(name: str) -> bool:
    path = PurePosixPath(name)
    return (bool(PRIVATE_DIRS.intersection(path.parts))
            or path.suffix.lower() in {".zip", ".pdf", ".jsonl", ".db", ".sqlite", ".pickle", ".pkl", ".pem", ".key"}
            or (path.name.startswith(".env") and path.name != ".env.example")
            or bool({".aws", ".codex", ".agents"}.intersection(path.parts)))


def main() -> int:
    revisions = git("rev-list", "--all").decode().splitlines()
    objects = {}
    problems = set()
    # Include the index, so this also protects the first local commit.
    listings = [git("ls-files", "--stage", "-z")]
    listings.extend(git("ls-tree", "-r", "-z", rev) for rev in revisions)
    for listing in listings:
        for record in listing.split(b"\0"):
            if not record:
                continue
            metadata, raw_name = record.split(b"\t", 1)
            parts = metadata.decode().split()
            oid = parts[2] if parts[1] == "blob" else parts[1]
            name = raw_name.decode()
            if private_path(name):
                problems.add("Private input or artifact tracked: " + name)
            objects.setdefault(oid, set()).add(name)
    for oid, names in objects.items():
        content = git("cat-file", "blob", oid)
        if any(pattern.search(content) for pattern in SECRET_PATTERNS):
            problems.add("Possible secret in Git history: " + ", ".join(sorted(names)))
    for problem in sorted(problems):
        print(problem)
    if problems:
        return 1
    print(f"PASS: {len(revisions)} revisions and {len(objects)} indexed/history blobs audited; no prohibited paths or matching secrets.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
