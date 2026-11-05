"""Original effective-date and applicability cases for fee schedules."""
from __future__ import annotations

import unittest
from types import SimpleNamespace

from solution import build


def schedule(text: str, path: str, title: str = "Willow CU fee schedule"):
    return SimpleNamespace(url="https://willow.test/" + path, title=title, markdown=text, fetched_at="2028-06-01T12:00:00Z")


class FeeTest(unittest.TestCase):
    def setUp(self):
        self.ks = build()
        self.docs = {}

    def ingest(self, *pages, day="2028-06-01"):
        sid = "synthetic_" + day
        self.ks.ingest(SimpleNamespace(snapshot_id=sid, taken_on=day, pages=list(pages)))
        self.docs.update({(sid, p.url): p.markdown for p in pages})

    def grounded(self, answer):
        self.assertTrue(answer.confident, answer.text)
        self.assertTrue(answer.sources)
        for source in answer.sources:
            self.assertIn(source.quote, self.docs[source.snapshot_id, source.url])

    def test_newer_effective_schedule_wins_across_different_urls(self):
        self.ingest(
            schedule("# Fee schedule\n\nEffective January 1, 2028\n\nLost debit card replacement fee: $3.25.\n", "old.pdf"),
            schedule("# Fee schedule\n\nEffective May 1, 2028\n\nLost debit card replacement fee: $6.75.\n", "new.pdf"),
        )
        answer = self.ks.answer("What is the lost debit card replacement fee?")
        self.grounded(answer)
        self.assertIn("$6.75", answer.text)
        self.assertNotIn("$3.25", answer.text)
        self.assertTrue(any(s.url.endswith("new.pdf") for s in answer.sources))
        fee_conflicts = [c for c in self.ks.conflicts() if "fee" in c.topic.lower()]
        self.assertTrue(fee_conflicts)
        self.assertTrue(any("$6.75" in c.resolution for c in fee_conflicts if c.resolution))

    def test_future_effective_fee_does_not_apply_early(self):
        self.ingest(
            schedule("# Fees\n\nEffective 2028-01-01\n\nLost debit card replacement fee: $3.25.\n", "old.pdf"),
            schedule("# Fees\n\nEffective 2028-07-01\n\nLost debit card replacement fee: $6.75.\n", "future.pdf"),
        )
        answer = self.ks.answer("What is the lost debit card replacement fee?")
        self.grounded(answer)
        self.assertIn("$3.25", answer.text)
        self.assertNotIn("$6.75", answer.text)

    def test_only_future_fee_is_not_a_current_answer(self):
        self.ingest(schedule("# Fees\n\nEffective 2028-07-01\n\nLost debit card replacement fee: $6.75.\n", "future.pdf"))
        answer = self.ks.answer("What is the lost debit card replacement fee?")
        self.assertFalse(answer.confident, answer.text)
        self.assertNotIn("$6.75", answer.text)

    def test_future_replacement_at_same_url_preserves_current_schedule(self):
        self.ingest(schedule("# Fees\n\nEffective 2028-01-01\n\nLost debit card replacement fee: $3.25.\n", "fees.pdf"), day="2028-01-05")
        self.ingest(schedule("# Fees\n\nEffective 2028-07-01\n\nLost debit card replacement fee: $6.75.\n", "fees.pdf"))
        answer = self.ks.answer("What is the lost debit card replacement fee?")
        self.grounded(answer)
        self.assertIn("$3.25", answer.text)
        self.assertNotIn("$6.75", answer.text)
        self.assertEqual(answer.sources[0].snapshot_id, "synthetic_2028-01-05")

    def test_numeric_formatting_does_not_create_a_fee_conflict(self):
        self.ingest(schedule("# Fees\n\nWire transfer fee: $12.00.\n", "a.pdf"), schedule("# Fees\n\nWire transfer fee: $12.\n", "b.pdf"))
        answer = self.ks.answer("What is the wire transfer fee?")
        self.grounded(answer)
        self.assertFalse([c for c in self.ks.conflicts() if "fee" in c.topic.lower()])

    def test_equally_applicable_fee_disagreement_refuses(self):
        self.ingest(
            schedule("# Fees\n\nEffective 2028-05-01\n\nLost debit card replacement fee: $3.25.\n", "a.pdf"),
            schedule("# Fees\n\nEffective 2028-05-01\n\nLost debit card replacement fee: $6.75.\n", "b.pdf"),
        )
        answer = self.ks.answer("What is the lost debit card replacement fee?")
        self.assertFalse(answer.confident, answer.text)
        self.assertTrue(answer.conflict_note)
        self.assertEqual(len(answer.sources), 2)
        conflicts = [c for c in self.ks.conflicts() if "fee" in c.topic.lower()]
        self.assertTrue(any(c.resolution is None for c in conflicts))

    def test_undated_equally_applicable_fee_disagreement_refuses(self):
        self.ingest(schedule("# Fees\n\nWire transfer fee: $12.25.\n", "a.pdf"), schedule("# Fees\n\nWire transfer fee: $19.75.\n", "b.pdf"))
        answer = self.ks.answer("What is the wire transfer fee?")
        self.assertFalse(answer.confident, answer.text)

    def test_consumer_and_business_scopes_are_distinct(self):
        self.ingest(schedule("# Fees\n\nEffective 2028-05-01\n\n## Consumer services\n\nWire transfer fee: $12.25.\n\n## Business services\n\nWire transfer fee: $19.75.\n", "fees.pdf"))
        consumer = self.ks.answer("What is the consumer wire transfer fee?")
        business = self.ks.answer("What is the business wire transfer fee?")
        self.grounded(consumer)
        self.grounded(business)
        self.assertIn("$12.25", consumer.text)
        self.assertNotIn("$19.75", consumer.text)
        self.assertIn("$19.75", business.text)
        self.assertNotIn("$12.25", business.text)
        self.assertFalse([c for c in self.ks.conflicts() if "fee" in c.topic.lower()])

    def test_loan_payment_illustrations_are_not_fee_conflicts(self):
        self.ingest(schedule("# Comparing borrowing costs\n\n## Interest costs\n\nAt 5% interest = $310/month, saving $1,200 over five years.\n\nAt 7% interest = $330/month, saving $600 over five years.\n", "learn/blog/comparing-loans", "Comparing borrowing costs"))
        self.assertFalse([c for c in self.ks.conflicts() if "fee" in c.topic.lower()])

    def test_page_omission_keeps_known_fee_with_original_provenance(self):
        self.ingest(schedule("# Fees\n\nEffective 2028-01-01\n\nLost debit card replacement fee: $3.25.\n", "fees.pdf"), day="2028-01-05")
        self.ingest(schedule("# Contact\n\nContact your local branch.\n", "contact"))
        answer = self.ks.answer("What is the lost debit card replacement fee?")
        self.grounded(answer)
        self.assertIn("$3.25", answer.text)
        self.assertEqual(answer.sources[0].snapshot_id, "synthetic_2028-01-05")

    def test_waiver_stays_with_fee_row(self):
        self.ingest(schedule("# Fees\n\nEffective 2028-01-01\n\nLost debit card replacement fee: $3.25; waived for members under age 18.\n", "fees.pdf"))
        answer = self.ks.answer("What is the lost debit card replacement fee?")
        self.grounded(answer)
        self.assertIn("waived", answer.text)
        self.assertIn("18", answer.text)


if __name__ == "__main__":
    unittest.main()
