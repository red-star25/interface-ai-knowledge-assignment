"""Input hygiene for our optional local loader, beyond the evaluator contract."""
from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from knowledge.io import load_snapshots


class LoaderTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def manifest(self, sid="synthetic", day="2027-01-05", file="pages/rates.md"):
        return {"snapshot_id": sid, "taken_on": day, "pages": [
            {"url": "https://sample-cu.test/rates", "title": "Rates", "file": file},
        ]}

    def write_folder(self, folder, manifest, markdown="# Rates\n\n6-month certificate APY: 3.23%\n"):
        directory = self.root / folder
        directory.mkdir(parents=True)
        (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        page = directory / manifest["pages"][0]["file"]
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text(markdown, encoding="utf-8")
        return directory

    def test_folder_loading_sorts_official_dates_and_preserves_markdown(self):
        text = "# Synthetic disclosure\n\n| A | B |\n|---|---|\n| café | 3.23% |\n"
        self.write_folder("aaa-later", self.manifest("later", "2027-03-05"))
        self.write_folder("zzz-earlier", self.manifest("earlier", "2027-01-05"), text)
        snapshots = load_snapshots(self.root)
        self.assertEqual([s.snapshot_id for s in snapshots], ["earlier", "later"])
        self.assertEqual(snapshots[0].pages[0].markdown, text)
        self.assertEqual(snapshots[0].pages[0].fetched_at, "2027-01-05")
        self.assertEqual(snapshots[0].pages[0].url, "https://sample-cu.test/rates")

    def test_single_snapshot_directory_is_supported(self):
        directory = self.write_folder("single", self.manifest())
        self.assertEqual(len(load_snapshots(directory)), 1)

    def test_manifest_fetch_timestamp_is_preserved(self):
        manifest = self.manifest()
        manifest["pages"][0]["fetched_at"] = "2027-01-05T22:16:00Z"
        self.write_folder("single", manifest)
        self.assertEqual(load_snapshots(self.root)[0].pages[0].fetched_at, "2027-01-05T22:16:00Z")

    def test_zip_loading_preserves_content_without_extracting_files(self):
        text = "# Rates\n\n6-month certificate APY: 3.23%\n"
        with zipfile.ZipFile(self.root / "input.zip", "w") as zf:
            zf.writestr("pull/manifest.json", json.dumps(self.manifest()))
            zf.writestr("pull/pages/rates.md", text)
        snapshots = load_snapshots(self.root)
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0].pages[0].markdown, text)
        self.assertFalse((self.root / "pull").exists())

    def test_zip_snapshots_are_sorted_by_manifest_dates(self):
        for filename, sid, day in (("a.zip", "later", "2027-03-05"), ("z.zip", "earlier", "2027-01-05")):
            with zipfile.ZipFile(self.root / filename, "w") as zf:
                zf.writestr("manifest.json", json.dumps(self.manifest(sid, day)))
                zf.writestr("pages/rates.md", "Synthetic rates")
        self.assertEqual([s.snapshot_id for s in load_snapshots(self.root)], ["earlier", "later"])

    def test_manifest_parent_traversal_is_rejected(self):
        directory = self.root / "single"
        directory.mkdir()
        (directory / "manifest.json").write_text(json.dumps(self.manifest(file="../outside.md")))
        (self.root / "outside.md").write_text("This is outside the snapshot")
        with self.assertRaises(ValueError):
            load_snapshots(self.root)

    def test_manifest_absolute_path_is_rejected(self):
        directory = self.root / "single"
        directory.mkdir()
        outside = self.root / "outside.md"
        outside.write_text("Outside snapshot")
        (directory / "manifest.json").write_text(json.dumps(self.manifest(file=str(outside))))
        with self.assertRaises(ValueError):
            load_snapshots(self.root)

    def test_zip_manifest_page_traversal_is_rejected(self):
        with zipfile.ZipFile(self.root / "input.zip", "w") as zf:
            zf.writestr("pull/manifest.json", json.dumps(self.manifest(file="../outside.md")))
            zf.writestr("outside.md", "Outside snapshot")
        with self.assertRaises(ValueError):
            load_snapshots(self.root)

    def test_zip_traversal_in_manifest_member_name_is_rejected(self):
        with zipfile.ZipFile(self.root / "input.zip", "w") as zf:
            zf.writestr("../pull/manifest.json", json.dumps(self.manifest()))
            zf.writestr("../pull/pages/rates.md", "Outside snapshot")
        with self.assertRaises(ValueError):
            load_snapshots(self.root)

    def test_source_symlink_cannot_escape_its_snapshot(self):
        directory = self.root / "single"
        directory.mkdir()
        (directory / "pages").mkdir()
        (directory / "manifest.json").write_text(json.dumps(self.manifest()))
        outside = self.root / "outside.md"
        outside.write_text("Outside snapshot")
        (directory / "pages/rates.md").symlink_to(outside)
        with self.assertRaises(ValueError):
            load_snapshots(self.root)

    def test_manifest_symlink_cannot_escape_its_snapshot(self):
        directory = self.root / "single"
        directory.mkdir()
        (directory / "pages").mkdir()
        (directory / "pages/rates.md").write_text("Synthetic rates")
        outside = self.root / "outside.json"
        outside.write_text(json.dumps(self.manifest()))
        (directory / "manifest.json").symlink_to(outside)
        with self.assertRaises(ValueError):
            load_snapshots(self.root)

    def test_nested_snapshot_directory_symlink_cannot_escape_selected_root(self):
        with tempfile.TemporaryDirectory() as other_temp:
            outside = Path(other_temp)
            (outside / "manifest.json").write_text(json.dumps(self.manifest()))
            (outside / "pages").mkdir()
            (outside / "pages/rates.md").write_text("Synthetic rates")
            (self.root / "linked-pull").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(ValueError):
                load_snapshots(self.root)

    def test_missing_root_is_controlled_error(self):
        with self.assertRaises(ValueError):
            load_snapshots(self.root / "missing")

    def test_no_manifest_is_controlled_error(self):
        (self.root / "unrelated.md").write_text("No manifest")
        with self.assertRaises(ValueError):
            load_snapshots(self.root)


if __name__ == "__main__":
    unittest.main()
