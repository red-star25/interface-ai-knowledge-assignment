"""Original public-safe fixtures exercising the submission's three-method contract.

No practice questions, institution values, or supplied pages are embedded here.
Run from the repository root with ``python3 -m unittest discover -s tests -v``.
"""
from __future__ import annotations

import re
import unittest
from dataclasses import dataclass

from solution import build


@dataclass(frozen=True)
class Page:
    url: str
    title: str
    markdown: str
    fetched_at: str = "2027-01-01T12:00:00Z"


@dataclass(frozen=True)
class Snapshot:
    snapshot_id: str
    taken_on: str
    pages: list[Page]


def page(text: str, path: str = "rates/certificates", title: str = "Certificate rates") -> Page:
    return Page("https://sample-cu.test/" + path, title, text)


def snapshot(day: str, *pages: Page) -> Snapshot:
    return Snapshot("pull_" + day, day, list(pages))


def certificates(apy: str, term: int = 6) -> Page:
    return page(f"# Certificate rates\n\n{term}-month certificate APY: {apy}%\n")


def percentages(text: str) -> set[float]:
    return {float(value) for value in re.findall(r"(\d+(?:\.\d+)?)\s*%", text)}


class KnowledgeTest(unittest.TestCase):
    def setUp(self):
        self.ks = build()

    def ingest(self, day: str, *pages: Page) -> None:
        self.ks.ingest(snapshot(day, *pages))

    def assert_rate(self, answer, expected: float, *excluded: float):
        self.assertTrue(answer.confident, answer.text)
        self.assertIn(expected, percentages(answer.text), answer.text)
        for wrong in excluded:
            self.assertNotIn(wrong, percentages(answer.text), answer.text)

    def assert_grounded(self, answer, *snapshots: Snapshot):
        self.assertTrue(answer.sources, answer.text)
        docs = {(s.snapshot_id, p.url): p.markdown for s in snapshots for p in s.pages}
        for source in answer.sources:
            self.assertIn((source.snapshot_id, source.url), docs)
            self.assertTrue(source.quote, "Every substantive answer should cite an excerpt")
            self.assertIn(source.quote, docs[source.snapshot_id, source.url])

    def test_latest_rate_increase_and_historical_cutoff(self):
        self.ingest("2027-01-05", certificates("2.75"))
        self.ingest("2027-03-05", certificates("3.25"))
        self.assert_rate(self.ks.answer("What is the 6-month certificate APY?"), 3.25, 2.75)
        self.assert_rate(self.ks.answer("What is the 6-month certificate APY?", as_of="2027-02-01"), 2.75, 3.25)

    def test_rate_decrease_is_not_mistaken_for_an_inferior_source(self):
        self.ingest("2027-01-05", certificates("3.75"))
        self.ingest("2027-03-05", certificates("2.25"))
        self.assert_rate(self.ks.answer("Current 6-month certificate APY?"), 2.25, 3.75)

    def test_unchanged_other_term_is_preserved(self):
        old = page("# Certificates\n\n6-month certificate APY: 2.75%\n\n12-month certificate APY: 3.60%\n")
        new = page("# Certificates\n\n6-month certificate APY: 3.25%\n\n12-month certificate APY: 3.60%\n")
        self.ingest("2027-01-05", old)
        self.ingest("2027-03-05", new)
        self.assert_rate(self.ks.answer("What is the 12-month certificate APY?"), 3.60, 2.75, 3.25)

    def test_omitted_page_does_not_prove_a_fee_disappeared(self):
        fee = page("# Fees\n\nLost debit card replacement fee: $4.75\n", "fees", "Fee schedule")
        old = snapshot("2027-01-05", fee)
        new = snapshot("2027-03-05", certificates("3.25"))
        self.ks.ingest(old)
        self.ks.ingest(new)
        answer = self.ks.answer("How much is a lost debit card replacement?")
        self.assertTrue(answer.confident, answer.text)
        self.assertRegex(answer.text, r"\$4\.75")
        self.assert_grounded(answer, old, new)
        self.assertEqual(answer.sources[0].snapshot_id, old.snapshot_id)

    def test_effective_date_after_capture_does_not_apply_early(self):
        self.ingest("2027-01-05", certificates("2.75"))
        self.ingest("2027-02-05", page("# Certificates\n\nEffective March 1, 2027\n\n6-month certificate APY: 3.25%\n"))
        self.assert_rate(self.ks.answer("What is the 6-month certificate APY?"), 2.75, 3.25)

    def test_future_effective_date_becomes_eligible_at_a_later_snapshot(self):
        self.ingest("2027-01-05", certificates("2.75"))
        notice = page("# Certificates\n\nEffective March 1, 2027\n\n6-month certificate APY: 3.25%\n")
        self.ingest("2027-02-05", notice)
        self.ingest("2027-03-05", notice)
        self.assert_rate(self.ks.answer("What is the 6-month certificate APY?"), 3.25, 2.75)

    def test_history_does_not_leak_later_observed_documents(self):
        self.ingest("2027-01-05", certificates("2.75"))
        self.ingest("2027-03-05", page("# Certificates\n\nEffective February 1, 2027\n\n6-month certificate APY: 3.25%\n"))
        self.assert_rate(self.ks.answer("What was the 6-month certificate APY?", as_of="2027-02-05"), 2.75, 3.25)

    def test_before_first_snapshot_abstains(self):
        self.ingest("2027-01-05", certificates("2.75"))
        self.assertFalse(self.ks.answer("What was the 6-month certificate APY?", as_of="2026-12-31").confident)

    def test_conflicting_equal_authority_pages_abstain(self):
        self.ingest("2027-01-05", certificates("2.75"), page("# Certificate rates\n\n6-month certificate APY: 3.25%\n", "other/certificate-rates"))
        answer = self.ks.answer("What is the 6-month certificate APY?")
        self.assertFalse(answer.confident, answer.text)
        conflicts = self.ks.conflicts()
        self.assertTrue(any({2.75, 3.25} <= percentages(" ".join(c.values)) for c in conflicts))

    def test_conflict_resolution_records_a_changed_rate_with_provenance(self):
        old = snapshot("2027-01-05", certificates("2.75"))
        new = snapshot("2027-03-05", certificates("3.25"))
        self.ks.ingest(old)
        self.ks.ingest(new)
        matches = [c for c in self.ks.conflicts() if {2.75, 3.25} <= percentages(" ".join(c.values))]
        self.assertTrue(matches)
        conflict = matches[0]
        self.assertIn(3.25, percentages(conflict.resolution or ""))
        self.assertTrue(conflict.reason)
        self.assertTrue(conflict.sources)
        for source in conflict.sources:
            self.assertIn(source.snapshot_id, {old.snapshot_id, new.snapshot_id})

    def test_expired_promotion_cannot_overrule_current_rate(self):
        self.ingest("2027-03-05", certificates("3.25"), page("# Summer promotion\n\n6-month certificate APY: 4.75% (offer ended 2026-09-30)\n", "promotions/summer", "Expired certificate promotion"))
        self.assert_rate(self.ks.answer("What is the 6-month certificate APY?"), 3.25, 4.75)

    def test_markdown_table_preserves_rate_and_apy_columns(self):
        self.ingest("2027-01-05", page("""# Certificate rates

| Term | Dividend Rate | APY | Minimum Deposit |
|---|---|---|---|
| 6-month certificate | 3.18% | 3.23% | $500 |
| 12-month certificate | 3.42% | 3.48% | $500 |
"""))
        self.assert_rate(self.ks.answer("What is the 6-month certificate APY?"), 3.23, 3.48)
        self.assert_rate(self.ks.answer("What is the dividend rate on the 6-month certificate?"), 3.18, 3.42)

    def test_jumbo_and_standard_are_different_products(self):
        self.ingest("2027-01-05", page("""# Certificate rates

| Term | APY | Minimum Deposit |
|---|---|---|
| 6-month fixed certificate | 3.23% | $500 |
| 6-month fixed jumbo certificate | 3.43% | $100,000 |
"""))
        self.assert_rate(self.ks.answer("What is the 6-month jumbo certificate APY?"), 3.43, 3.23)

    def test_ira_certificate_does_not_use_regular_certificate_rate(self):
        self.ingest("2027-01-05", page("""# Certificate rates

| Term | APY | Minimum Deposit |
|---|---|---|
| 12-month fixed certificate | 3.48% | $500 |
| 12-month IRA certificate | 3.68% | $500 |
"""))
        self.assert_rate(self.ks.answer("What is the 12-month IRA certificate APY?"), 3.68, 3.48)

    def test_savings_balance_tier_not_global_maximum(self):
        self.ingest("2027-01-05", page("""# Share Savings rates

| Balance | Dividend Rate | APY |
|---|---|---|
| $0 - $999.99 | 0.05% | 0.05% |
| $1,000 - $9,999.99 | 0.12% | 0.12% |
| $10,000 and up | 0.22% | 0.22% |
""", "personal/savings", "Savings account rates"))
        self.assert_rate(self.ks.answer("What Share Savings APY do I get with a $5,000 balance?"), 0.12, 0.05, 0.22)

    def test_personal_and_business_card_rates_do_not_mix(self):
        personal = page("# Personal credit cards\n\nPlatinum Visa standard purchase APR: 11.75%\n", "personal/credit-cards", "Personal credit cards")
        business = page("# Business credit cards\n\nBusiness Platinum Visa standard purchase APR: 16.25%\n", "business/credit-cards", "Business credit cards")
        self.ingest("2027-01-05", personal, business)
        self.assert_rate(self.ks.answer("What is the Business Platinum Visa purchase APR?"), 16.25, 11.75)
        self.assert_rate(self.ks.answer("What is the personal Platinum Visa purchase APR?"), 11.75, 16.25)

    def test_introductory_apr_does_not_replace_standard_apr(self):
        self.ingest("2027-01-05", page("# Platinum Visa\n\nStandard purchase APR: 11.75%\n\nIntroductory balance transfer APR: 1.75% for the first 60 days.\n", "personal/credit-cards", "Personal credit cards"))
        self.assert_rate(self.ks.answer("What is the standard purchase APR on Platinum Visa?"), 11.75, 1.75)

    def test_apr_does_not_get_substituted_for_apy(self):
        self.ingest("2027-01-05", certificates("3.23"), page("# Personal loans\n\n36-month personal loan APR: 9.75%\n", "personal/loans/personal-loans", "Personal loans"))
        self.assert_rate(self.ks.answer("What is the 36-month personal loan APR?"), 9.75, 3.23)

    def test_unknown_term_abstains_instead_of_returning_nearest_term(self):
        self.ingest("2027-01-05", certificates("3.23", 6), page("# Certificates\n\n12-month certificate APY: 3.48%\n", "rates/other-certificates"))
        self.assertFalse(self.ks.answer("What is the 60-month jumbo certificate APY?").confident)

    def test_unknown_product_abstains_instead_of_matching_a_rate_keyword(self):
        self.ingest("2027-01-05", certificates("3.23"))
        self.assertFalse(self.ks.answer("What is the interest rate for a spacecraft lease?").confident)

    def test_ambiguous_question_abstains(self):
        self.ingest("2027-01-05", certificates("3.23"), page("# Personal loans\n\n36-month personal loan APR: 9.75%\n", "personal/loans/personal-loans", "Personal loans"))
        self.assertFalse(self.ks.answer("What is the rate?").confident)

    def test_invalid_or_empty_query_does_not_crash(self):
        self.ingest("2027-01-05", certificates("3.23"))
        for query in ("", "   ", None, [], 123):
            with self.subTest(query=query):
                self.assertFalse(self.ks.answer(query).confident)

    def test_invalid_as_of_is_a_controlled_refusal(self):
        self.ingest("2027-01-05", certificates("3.23"))
        for day in ("yesterday", "2027-02-30", ""):
            with self.subTest(day=day):
                self.assertFalse(self.ks.answer("What is the 6-month certificate APY?", as_of=day).confident)

    def test_no_ingested_evidence_abstains(self):
        self.assertFalse(self.ks.answer("What is the 6-month certificate APY?").confident)
        self.assertEqual(self.ks.conflicts(), [])

    def test_sources_refer_to_selected_snapshot_and_exact_original_excerpt(self):
        old = snapshot("2027-01-05", certificates("2.75"))
        new = snapshot("2027-03-05", certificates("3.25"))
        self.ks.ingest(old)
        self.ks.ingest(new)
        latest = self.ks.answer("What is the 6-month certificate APY?")
        historical = self.ks.answer("What is the 6-month certificate APY?", as_of="2027-02-01")
        self.assert_grounded(latest, old, new)
        self.assert_grounded(historical, old, new)
        self.assertTrue(any(s.snapshot_id == new.snapshot_id and "3.25%" in s.quote for s in latest.sources))
        self.assertTrue(any(s.snapshot_id == old.snapshot_id and "2.75%" in s.quote for s in historical.sources))

    def test_repeated_and_paraphrased_queries_are_consistent(self):
        self.ingest("2027-01-05", certificates("3.23"))
        query = "What is the 6-month certificate APY?"
        first = self.ks.answer(query)
        second = self.ks.answer(query)
        paraphrase = self.ks.answer("Current APY on a six month share certificate?")
        self.assertEqual(first, second)
        self.assert_rate(paraphrase, 3.23)
        self.assertEqual(percentages(first.text), percentages(paraphrase.text))


if __name__ == "__main__":
    unittest.main()
