"""Read authorized local kit inputs without modifying or extracting archives."""
from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable


@dataclass(frozen=True)
class Page:
    url: str
    title: str
    markdown: str
    fetched_at: str


@dataclass(frozen=True)
class Snapshot:
    snapshot_id: str
    taken_on: str
    pages: list[Page]


def _relative(name: str) -> str:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or "\\" in name:
        raise ValueError("Source path must stay within its snapshot")
    return str(path)


def _snapshot(manifest: dict, read: Callable[[str], str]) -> Snapshot:
    return Snapshot(
        snapshot_id=manifest["snapshot_id"],
        taken_on=manifest["taken_on"],
        pages=[Page(p["url"], p.get("title", ""), read(_relative(p["file"])),
                    p.get("fetched_at", manifest["taken_on"])) for p in manifest["pages"]],
    )


def load_snapshots(root: Path) -> list[Snapshot]:
    """Accept manifest folders or the supplied ZIP directory; never use mtimes."""
    root = root.resolve()
    if not root.is_dir():
        raise ValueError(f"Snapshot directory does not exist: {root}")
    manifests = sorted(root.glob("*/manifest.json"))
    if (root / "manifest.json").is_file():
        manifests.insert(0, root / "manifest.json")
    snapshots = []
    for manifest_path in manifests:
        base = manifest_path.parent
        if not base.resolve().is_relative_to(root) or not manifest_path.resolve().is_relative_to(base.resolve()):
            raise ValueError("Manifest or snapshot symlink escapes the selected snapshot root")

        def read(name: str, base: Path = base) -> str:
            path = (base / name).resolve()
            if not path.is_relative_to(base.resolve()):
                raise ValueError("Source symlink escapes its snapshot")
            return path.read_text(encoding="utf-8")

        snapshots.append(_snapshot(json.loads(manifest_path.read_text(encoding="utf-8")), read))
    if not manifests:
        for archive in sorted(root.glob("*.zip")):
            with zipfile.ZipFile(archive) as zf:
                for name in sorted(zf.namelist()):
                    if PurePosixPath(name).name != "manifest.json":
                        continue
                    name = _relative(name)
                    base = PurePosixPath(name).parent

                    def read(member: str) -> str:
                        return zf.read(str(base / member)).decode("utf-8")

                    snapshots.append(_snapshot(json.loads(zf.read(name)), read))
    if not snapshots:
        raise ValueError("No snapshot manifests or snapshot ZIPs found")
    return sorted(snapshots, key=lambda s: (s.taken_on, s.snapshot_id))
