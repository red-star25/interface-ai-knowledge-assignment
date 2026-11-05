"""Illustrative data may expose conflicts but cannot establish a current rate."""
import unittest

from solution import build
from test_system import page, snapshot, percentages


class CalculatorTest(unittest.TestCase):
    @staticmethod
    def operative():
        return page("""# Auto loans

| Loan Program | Term | APR (As Low As) |
|---|---|---|
| 2026-29 Model Year | 60 Months | 5.17% |
""", "personal/auto-loans", "Auto loans")

    @staticmethod
    def calculator():
        return page("""# Vehicle affordability calculator

Auto & Motorcycle Loans

| Loan Program | Term | APR |
|---|---|---|
| 2026-29 Model Year | 60 Months | 5.12% |
""", "calculators/vehicle-affordability", "Vehicle affordability calculator")

    def test_operative_rate_wins_and_calculator_disagreement_is_retained(self):
        ks = build()
        ks.ingest(snapshot("2027-01-05", self.operative(), self.calculator()))
        answer = ks.answer("What is the 60-month auto loan APR for a 2028 vehicle?")
        self.assertTrue(answer.confident, answer.text)
        self.assertEqual(percentages(answer.text), {5.17})
        conflicts = ks.conflicts()
        self.assertTrue(any({5.12, 5.17} <= percentages(" ".join(c.values)) for c in conflicts))
        self.assertTrue(any(5.17 in percentages(c.resolution or "") for c in conflicts))

    def test_calculator_alone_does_not_establish_an_offered_rate(self):
        ks = build()
        ks.ingest(snapshot("2027-01-05", self.calculator()))
        answer = ks.answer("What is the 60-month auto loan APR for a 2028 vehicle?")
        self.assertFalse(answer.confident, answer.text)

    def test_numerically_equal_renderings_are_not_a_change(self):
        ks = build()
        ks.ingest(snapshot("2027-01-05", page("# Certificates\n\n6-month certificate APY: 3.50%\n")))
        ks.ingest(snapshot("2027-03-05", page("# Certificates\n\n6-month certificate APY: 3.5%\n")))
        answer = ks.answer("How did the 6-month certificate APY change between 2027-01-05 and 2027-03-05?")
        self.assertTrue(answer.confident, answer.text)
        self.assertIn("no changed value", answer.text.lower())
        self.assertEqual(ks.conflicts(), [])


if __name__ == "__main__":
    unittest.main()
