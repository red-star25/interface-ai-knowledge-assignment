"""Original nonfinancial grounding cases through the public submission API."""
from __future__ import annotations

import unittest
from types import SimpleNamespace

from solution import build


def page(text, path="contact", title="Cedar Credit Union contact"):
    return SimpleNamespace(
        url="https://cedar-cu.test/" + path,
        title=title,
        markdown=text,
        fetched_at="2027-06-05T12:00:00Z",
    )


class ContentTest(unittest.TestCase):
    def setUp(self):
        self.ks = build()
        self.documents = {}

    def ingest(self, *pages, day="2027-06-05"):
        sid = "synthetic_" + day
        self.ks.ingest(SimpleNamespace(snapshot_id=sid, taken_on=day, pages=list(pages)))
        self.documents.update({(sid, p.url): p.markdown for p in pages})

    def assert_grounded(self, answer):
        self.assertTrue(answer.confident, answer.text)
        self.assertTrue(answer.sources)
        for source in answer.sources:
            self.assertIn((source.snapshot_id, source.url), self.documents)
            self.assertTrue(source.quote)
            self.assertIn(source.quote, self.documents[source.snapshot_id, source.url])

    def test_routing_number_in_prose_is_cited(self):
        self.ingest(page("# Routing information\n\nCedar Credit Union routing number: 135792468.\n"))
        answer = self.ks.answer("What is Cedar Credit Union's routing number?")
        self.assert_grounded(answer)
        self.assertIn("135792468", answer.text)

    def test_routing_number_cites_all_current_pages_that_confirm_the_value(self):
        contact = page("# Routing information\n\nCedar Credit Union routing number: 135792468.\n")
        business = page("# Cash management\n\nUse our routing number (135792468) for incoming funds.\n",
                        "business/cash-management", "Cedar Credit Union cash management")
        self.ingest(contact, business)
        answer = self.ks.answer("What is Cedar Credit Union's routing number?")
        self.assert_grounded(answer)
        self.assertEqual({source.url for source in answer.sources}, {contact.url, business.url})

    def test_other_institutions_routing_number_is_not_ours(self):
        self.ingest(page("# Visiting financial institutions\n\nFor a transfer to Birch Bank, use its routing number: 246813579.\n", "learn/blog/transfers", "Transfers to Birch Bank"))
        answer = self.ks.answer("What is Cedar Credit Union's routing number?")
        self.assertFalse(answer.confident, answer.text)
        self.assertNotIn("246813579", answer.text)

    def test_unrelated_institution_does_not_create_a_false_routing_conflict(self):
        own = page("# Routing information\n\nCedar Credit Union routing number: 135792468.\n")
        other = page("April 2, 2025\n\n# Transfers to Birch Bank\n\nBirch Bank routing number: 246813579.\n", "learn/blog/transfers", "Transfers to Birch Bank")
        self.ingest(own, other)
        answer = self.ks.answer("What is Cedar Credit Union's routing number?")
        self.assert_grounded(answer)
        self.assertIn("135792468", answer.text)
        self.assertNotIn("246813579", answer.text)

    def test_membership_retains_live_or_work_and_geographic_conditions(self):
        self.ingest(page("""# Membership

Our charter area covers designated counties in Oregon and Washington.

## Who is eligible to join?

You may join if you live or work in our charter area.

Immediate family members of existing members may also join.
""", "membership", "Membership at Cedar Credit Union"))
        answer = self.ks.answer("Who is eligible to become a member?")
        self.assert_grounded(answer)
        for required in ("live or work", "Oregon", "Washington"):
            self.assertIn(required, answer.text)

    def test_unknown_branch_does_not_borrow_known_branch_schedule(self):
        self.ingest(page("# Harbor Branch\n\n## Lobby hours\n\nMonday-Friday: 9 a.m.-4 p.m.\n", title="Harbor Branch"))
        answer = self.ks.answer("What are the lobby hours for the Nebula Branch?")
        self.assertFalse(answer.confident, answer.text)
        self.assertNotIn("9 a.m.", answer.text)

    def test_contact_schedule_beats_dated_historical_article_for_same_branch(self):
        current = page("# Harbor Branch\n\n## Lobby hours\n\nMonday-Friday: 9 a.m.-4 p.m.\n", title="Harbor Branch")
        historical = page("April 2, 2025\n\n# Harbor Branch opening celebration\n\n## Lobby hours\n\nMonday-Friday: 7 a.m.-7 p.m.\n", "newsroom/harbor-opening", "Harbor Branch opening celebration")
        self.ingest(current, historical)
        answer = self.ks.answer("What are the lobby hours for the Harbor Branch?")
        self.assert_grounded(answer)
        self.assertIn("9 a.m.", answer.text)
        self.assertNotIn("7 a.m.", answer.text)
        self.assertTrue(any(s.url == current.url for s in answer.sources))

    def test_historical_contact_schedule_uses_requested_snapshot(self):
        self.ingest(page("# Harbor Branch\n\n## Lobby hours\n\nMonday-Friday: 8 a.m.-4 p.m.\n", title="Harbor Branch"), day="2027-01-05")
        self.ingest(page("# Harbor Branch\n\n## Lobby hours\n\nMonday-Friday: 9 a.m.-4 p.m.\n", title="Harbor Branch"))
        answer = self.ks.answer("What were the lobby hours for the Harbor Branch?", as_of="2027-02-01")
        self.assert_grounded(answer)
        self.assertIn("8 a.m.", answer.text)
        self.assertNotIn("9 a.m.", answer.text)

    def test_handpicked_content_is_excluded_but_following_faq_is_retained(self):
        self.ingest(page("""# Checking account

Online account access is included.

## Handpicked for you

Paper statements are free with an unrelated business promotion.

## Frequently asked questions

Paper statement fee: $2.75 per month.
""", "personal/checking", "Checking account FAQ"))
        answer = self.ks.answer("What is the paper statement fee?")
        self.assert_grounded(answer)
        self.assertIn("$2.75", answer.text)
        self.assertNotIn("free", answer.text.lower())

    def test_handpicked_recommendation_does_not_establish_named_product(self):
        self.ingest(page("""# Checking account

Members can use online account access.

## Handpicked for you

Nebula Checking account includes free paper statements.
""", "personal/checking", "Checking account"))
        answer = self.ks.answer("Are paper statements free for the Nebula Checking account?")
        self.assertFalse(answer.confident, answer.text)

    def test_last_year_requires_a_report_for_that_year(self):
        self.ingest(page("April 2, 2026\n\n# Community report\n\nIn 2025, 182 employees used Volunteer Time Off.\n", "newsroom/community-2025", "Community report"))
        answer = self.ks.answer("How many employees used Volunteer Time Off last year?")
        self.assertFalse(answer.confident, answer.text)
        self.assertNotIn("182", answer.text)

    def test_explicit_report_year_is_supported_even_if_not_current_year(self):
        self.ingest(page("April 2, 2026\n\n# Community report\n\nIn 2025, 182 employees used Volunteer Time Off.\n", "newsroom/community-2025", "Community report"))
        answer = self.ks.answer("How many employees used Volunteer Time Off in 2025?")
        self.assert_grounded(answer)
        self.assertIn("182", answer.text)
        self.assertIn("2025", answer.text)

    def test_mobile_wallet_list_is_complete_and_grounded(self):
        self.ingest(page("# Mobile wallets\n\nAdd your eligible debit and credit cards to Apple Pay, Google Pay, or Samsung Pay.\n", "personal/mobile-wallets", "Mobile wallets"))
        answer = self.ks.answer("Can I add my debit and credit cards to a mobile wallet?")
        self.assert_grounded(answer)
        for wallet in ("Apple Pay", "Google Pay", "Samsung Pay"):
            self.assertIn(wallet, answer.text)

    def test_fee_answer_retains_waiver_in_same_passage(self):
        self.ingest(page("# Fees\n\nLost debit card replacement fee: $4.75; waived for members under age 18.\n", "fees", "Fee schedule"))
        answer = self.ks.answer("How much is a lost debit card replacement?")
        self.assert_grounded(answer)
        self.assertIn("$4.75", answer.text)
        self.assertIn("waived", answer.text)
        self.assertIn("18", answer.text)

    def test_absent_named_card_does_not_borrow_generic_card_fee(self):
        self.ingest(page("# Debit card fees\n\nStandard debit card replacement fee: $4.75.\n", "fees", "Debit card fee schedule"))
        answer = self.ks.answer("What is the replacement fee for the Nebula debit card?")
        self.assertFalse(answer.confident, answer.text)
        self.assertNotIn("$4.75", answer.text)

    def test_branch_closure_event_keeps_source_date(self):
        self.ingest(page("April 2, 2027\n\n# Pine Branch service update\n\nThe Pine Branch will close May 31, 2027.\n\nMembers can obtain the same services at our Harbor and Meadow full-service branches.\n", "newsroom/pine-update", "Pine Branch service update"))
        answer = self.ks.answer("When will the Pine Branch close?")
        self.assert_grounded(answer)
        self.assertIn("May 31, 2027", answer.text)

    def test_branch_closure_alternative_services_stay_with_correct_branch(self):
        self.ingest(page("April 2, 2027\n\n# Pine Branch service update\n\nThe Pine Branch will close May 31, 2027.\n\nMembers can obtain the same services at our Harbor and Meadow full-service branches.\n", "newsroom/pine-update", "Pine Branch service update"))
        answer = self.ks.answer("Where can the Pine Branch members go for full-service banking?")
        self.assert_grounded(answer)
        self.assertIn("Harbor", answer.text)
        self.assertIn("Meadow", answer.text)


if __name__ == "__main__":
    unittest.main()
