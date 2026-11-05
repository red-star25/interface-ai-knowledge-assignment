"""Independent boundary cases for qualified claims and history."""
import unittest

from solution import build
from test_system import page, snapshot, certificates, percentages


class PolicyTest(unittest.TestCase):
    def test_iso_date_comparison_cites_both_periods(self):
        ks = build()
        ks.ingest(snapshot("2027-01-05", certificates("2.75")))
        ks.ingest(snapshot("2027-03-05", certificates("3.25")))
        answer = ks.answer("How did the 6-month certificate APY change between 2027-01-05 and 2027-03-05?")
        self.assertTrue(answer.confident, answer.text)
        self.assertEqual(percentages(answer.text), {2.75, 3.25})
        self.assertEqual({s.snapshot_id for s in answer.sources}, {"pull_2027-01-05", "pull_2027-03-05"})

    def test_requested_date_after_available_snapshots_refuses(self):
        ks = build()
        ks.ingest(snapshot("2027-01-05", certificates("2.75")))
        self.assertFalse(ks.answer("What is the 6-month certificate APY?", as_of="2027-02-05").confident)

    def test_open_ended_balance_tier(self):
        ks = build()
        ks.ingest(snapshot("2027-01-05", page("""# Share Savings

| Balance | APY |
|---|---|
| $0 - $999.99 | 0.11% |
| $1,000 and up | 0.21% |
""", "personal/savings", "Share Savings")))
        answer = ks.answer("What Share Savings APY applies to a $5,000 balance?")
        self.assertTrue(answer.confident, answer.text)
        self.assertEqual(percentages(answer.text), {0.21})

    def test_mortgage_amount_above_all_published_tiers_refuses(self):
        ks = build()
        ks.ingest(snapshot("2027-01-05", page("""# Home loans

| Program | Rate | APR |
|---|---|---|
| Purchase: 30-Year Fixed Conventional $100,000 or less | 6.11% | 6.21% |
| Purchase: 30-Year Fixed Conventional $500,000 or less | 6.31% | 6.41% |
""", "personal/home-loans", "Home loans")))
        answer = ks.answer("What is the 30-year mortgage rate for $900,000?")
        self.assertFalse(answer.confident, answer.text)

    def test_future_effective_date_before_table(self):
        ks = build()
        ks.ingest(snapshot("2027-01-05", certificates("2.75")))
        ks.ingest(snapshot("2027-02-05", page("""# Certificate rates

Effective March 1, 2027

| Term | APY |
|---|---|
| 6-month certificate | 3.25% |
""")))
        answer = ks.answer("What is the 6-month certificate APY?")
        self.assertTrue(answer.confident, answer.text)
        self.assertEqual(percentages(answer.text), {2.75})

    def test_missing_metric_preserves_last_observation(self):
        ks = build()
        ks.ingest(snapshot("2027-01-05", page("""# Certificate rates

| Term | Dividend Rate | APY |
|---|---|---|
| 6-month certificate | 3.18% | 3.23% |
""")))
        ks.ingest(snapshot("2027-02-05", page("""# Certificate rates

| Term | APY |
|---|---|
| 6-month certificate | 3.33% |
""")))
        answer = ks.answer("What is the dividend rate on the 6-month certificate?")
        self.assertTrue(answer.confident, answer.text)
        self.assertEqual(percentages(answer.text), {3.18})
        self.assertTrue(any(s.snapshot_id == "pull_2027-01-05" for s in answer.sources))


if __name__ == "__main__":
    unittest.main()
