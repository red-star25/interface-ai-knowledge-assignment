"""Validate our ingestion extensions without relying on private harness types."""
from __future__ import annotations

import unittest
from types import SimpleNamespace

from solution import build


def page(url="https://sample-cu.test/certificates", markdown="6-month certificate APY: 3.23%"):
    return SimpleNamespace(url=url, title="Certificates", markdown=markdown, fetched_at="2027-01-05T12:00:00Z")


def snapshot(sid="first", day="2027-01-05", pages=None):
    return SimpleNamespace(snapshot_id=sid, taken_on=day, pages=[page()] if pages is None else pages)


class IngestionTest(unittest.TestCase):
    def setUp(self):
        self.ks = build()

    def test_duplicate_snapshot_id_is_rejected(self):
        self.ks.ingest(snapshot())
        with self.assertRaises(ValueError):
            self.ks.ingest(snapshot(day="2027-02-05"))

    def test_duplicate_source_urls_inside_snapshot_are_rejected(self):
        with self.assertRaises(ValueError):
            self.ks.ingest(snapshot(pages=[page(), page(markdown="6-month certificate APY: 4.23%")]))
        self.assertFalse(self.ks.answer("What is the 6-month certificate APY?").confident)

    def test_nonchronological_ingestion_is_rejected(self):
        self.ks.ingest(snapshot(day="2027-02-05"))
        with self.assertRaises(ValueError):
            self.ks.ingest(snapshot(sid="older", day="2027-01-05"))

    def test_validation_failure_does_not_partially_apply_a_pull(self):
        self.ks.ingest(snapshot())
        before = self.ks.answer("What is the 6-month certificate APY?")
        bad_pull = snapshot("second", "2027-02-05", [
            page(markdown="6-month certificate APY: 4.23%"),
            page(url="relative/path", markdown="Unsupported relative source URL"),
        ])
        with self.assertRaises(ValueError):
            self.ks.ingest(bad_pull)
        self.assertEqual(self.ks.answer("What is the 6-month certificate APY?"), before)
        # Reusing the rejected ID must work: metadata was not partially committed.
        self.ks.ingest(snapshot("second", "2027-02-05", [page(markdown="6-month certificate APY: 3.53%")]))
        self.assertTrue(self.ks.answer("What is the 6-month certificate APY?").confident)

    def test_nontext_content_is_rejected_before_state_mutation(self):
        with self.assertRaises(ValueError):
            self.ks.ingest(snapshot(pages=[page(), page("https://sample-cu.test/other", None)]))
        self.assertFalse(self.ks.answer("What is the 6-month certificate APY?").confident)


if __name__ == "__main__":
    unittest.main()
