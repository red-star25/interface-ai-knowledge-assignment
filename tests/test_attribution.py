"""Financial applicability regressions discovered during independent review."""
from __future__ import annotations

import re
import unittest
from types import SimpleNamespace

from solution import build


def system(text, title):
    ks = build()
    ks.ingest(SimpleNamespace(
        snapshot_id="synthetic_2027-01-05", taken_on="2027-01-05", pages=[
            SimpleNamespace(url="https://sample-cu.test/rates", title=title,
                            markdown=text, fetched_at="2027-01-05T12:00:00Z"),
        ],
    ))
    return ks


class AttributionTest(unittest.TestCase):
    def test_unknown_named_checking_product_does_not_use_known_checking(self):
        ks = system("""# Free Checking

| Balance | APY |
|---|---|
| $0 and up | 0.12% |
""", "Free Checking")
        for name in ("Nebula Checking", "nebula checking"):
            with self.subTest(name=name):
                answer = ks.answer(f"What is the APY on the {name} account?")
                self.assertFalse(answer.confident, answer.text)
                self.assertNotIn("0.12%", answer.text)

    def test_unknown_named_certificate_does_not_use_generic_certificate(self):
        ks = system("""# Certificate rates

| Term | APY |
|---|---|
| 6-month certificate | 3.23% |
""", "Certificate rates")
        for name in ("Nebula", "nebula"):
            with self.subTest(name=name):
                answer = ks.answer(f"What APY does the {name} 6-month certificate pay?")
                self.assertFalse(answer.confident, answer.text)
                self.assertNotIn("3.23%", answer.text)

    def test_unpublished_mortgage_program_does_not_use_conventional_rates(self):
        ks = system("""# Home loans

| Program | Rate | APR |
|---|---|---|
| Purchase: 30-Year Fixed Conventional $100,000 or less | 6.11% | 6.21% |
""", "Home loans")
        for program in ("FHA", "VA"):
            with self.subTest(program=program):
                answer = ks.answer(f"What is the 30-year {program} mortgage rate?")
                self.assertFalse(answer.confident, answer.text)
                self.assertNotIn("6.11%", answer.text)

    def test_new_version_corrects_prior_within_page_rate_disagreement(self):
        ks = system("""# Certificate rates

6-month certificate APY: 3.23%

6-month certificate APY: 3.43%
""", "Certificate rates")
        self.assertFalse(ks.answer("What is the 6-month certificate APY?").confident)
        ks.ingest(SimpleNamespace(
            snapshot_id="synthetic_2027-02-05", taken_on="2027-02-05", pages=[
                SimpleNamespace(url="https://sample-cu.test/rates", title="Certificate rates",
                                markdown="# Certificate rates\n\n6-month certificate APY: 3.53%\n",
                                fetched_at="2027-02-05T12:00:00Z"),
            ],
        ))
        answer = ks.answer("What is the 6-month certificate APY?")
        self.assertTrue(answer.confident, answer.text)
        self.assertIn("3.53%", answer.text)
        self.assertNotIn("3.23%", answer.text)
        self.assertNotIn("3.43%", answer.text)
        self.assertTrue(any(s.snapshot_id == "synthetic_2027-02-05" for s in answer.sources))

    def test_deposit_below_jumbo_minimum_cannot_get_jumbo_yield(self):
        ks = system("""# Certificate rates

| Term | APY | Minimum Deposit |
|---|---|---|
| 6-month certificate | 3.23% | $500 |
| 6-month jumbo certificate | 3.43% | $100,000 |
""", "Certificate rates")
        answer = ks.answer("What is the 6-month certificate APY for a $500 deposit?")
        self.assertTrue(answer.confident, answer.text)
        values = {float(n) for n in re.findall(r"(\d+(?:\.\d+)?)\s*%", answer.text)}
        self.assertEqual(values, {3.23}, answer.text)


if __name__ == "__main__":
    unittest.main()
