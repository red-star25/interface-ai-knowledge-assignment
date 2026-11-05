"""The optional LLM may normalize wording, but cannot supply facts or citations."""
from __future__ import annotations

import json
import unittest
from unittest.mock import patch
from urllib.error import URLError

from knowledge.llm import OpenAIQuestionInterpreter, QueryInterpretation
from knowledge.system import KnowledgeSystem


class FakeResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.payload


class FakeInterpreter:
    def __init__(self, interpretation):
        self.interpretation = interpretation
        self.calls = []

    def interpret(self, question):
        self.calls.append(question)
        return self.interpretation


class LLMIntegrationTest(unittest.TestCase):
    def test_responses_api_sends_only_question_and_returns_structured_rewrite(self):
        output = {"decision": "rewrite", "rewritten_question": "6-month certificate APY"}
        response = FakeResponse({
            "status": "completed",
            "output": [{"type": "message", "content": [{
                "type": "output_text", "text": json.dumps(output),
            }]}],
        })
        client = OpenAIQuestionInterpreter("test-key", "test-model")
        with patch("knowledge.llm.urlopen", return_value=response) as send:
            interpretation = client.interpret("What's the yield for a half-year term deposit?")
        request = send.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(interpretation, QueryInterpretation("rewrite", "6-month certificate APY"))
        self.assertEqual(client.last_status, "rewrite")
        self.assertEqual(payload["input"], "What's the yield for a half-year term deposit?")
        self.assertNotIn("snapshot", json.dumps(payload).lower())
        self.assertFalse(payload["store"])

    def test_ambiguous_or_failed_interpretation_returns_no_rewrite(self):
        output = {"decision": "clarify", "rewritten_question": ""}
        response = FakeResponse({
            "status": "completed",
            "output": [{"type": "message", "content": [{
                "type": "output_text", "text": json.dumps(output),
            }]}],
        })
        client = OpenAIQuestionInterpreter("test-key", "test-model")
        with patch("knowledge.llm.urlopen", return_value=response):
            self.assertEqual(client.interpret("What should I do with my money?"), QueryInterpretation("clarify"))
            self.assertEqual(client.last_status, "clarify")
        with patch("knowledge.llm.urlopen", side_effect=URLError("offline")):
            self.assertIsNone(client.interpret("What's the yield?"))
            self.assertEqual(client.last_status, "network_error")

    def test_rewrite_cannot_add_a_product_the_question_did_not_name(self):
        output = {"decision": "rewrite", "rewritten_question": "What would I earn in a savings account for 6 months?"}
        response = FakeResponse({
            "status": "completed",
            "output": [{"type": "message", "content": [{
                "type": "output_text", "text": json.dumps(output),
            }]}],
        })
        client = OpenAIQuestionInterpreter("test-key", "test-model")
        with patch("knowledge.llm.urlopen", return_value=response):
            interpretation = client.interpret("What would I earn by parking my cash for half a year?")
        self.assertEqual(interpretation, QueryInterpretation("clarify"))
        self.assertEqual(client.last_status, "clarify_scope_mismatch")

    def test_rewrite_cannot_invent_an_amount_for_balance_tier_selection(self):
        output = {"decision": "rewrite", "rewritten_question": "What APY does a $100,000 certificate earn?"}
        response = FakeResponse({
            "status": "completed",
            "output": [{"type": "message", "content": [{
                "type": "output_text", "text": json.dumps(output),
            }]}],
        })
        client = OpenAIQuestionInterpreter("test-key", "test-model")
        with patch("knowledge.llm.urlopen", return_value=response):
            interpretation = client.interpret("What APY does a certificate earn?")
        self.assertEqual(interpretation, QueryInterpretation("clarify"))
        self.assertEqual(client.last_status, "clarify_scope_mismatch")

    def test_interpreted_query_prevents_false_positive_and_answer_stays_grounded(self):
        interpreter = FakeInterpreter(QueryInterpretation("rewrite", "What is the 6-month certificate APY?"))
        system = KnowledgeSystem(query_interpreter=interpreter)
        system.ingest(type("Snapshot", (), {
            "snapshot_id": "synthetic", "taken_on": "2027-01-05", "pages": [type("Page", (), {
                "url": "https://sample-cu.test/certificates", "title": "Certificate rates",
                "markdown": "# Certificate rates\n\n6-month certificate APY: 3.23%\n",
                "fetched_at": "2027-01-05",
            })()],
        })())
        answer = system.answer("What would I earn by parking my cash for half a year?")
        self.assertTrue(answer.confident, answer.text)
        self.assertIn("3.23%", answer.text)
        self.assertTrue(answer.sources)
        self.assertIn(answer.sources[0].quote, system._documents[("synthetic", answer.sources[0].url)].markdown)
        self.assertEqual(interpreter.calls, ["What would I earn by parking my cash for half a year?"])

    def test_conflicts_remain_deterministic_after_question_interpretation(self):
        interpreter = FakeInterpreter(QueryInterpretation("rewrite", "What is the 6-month certificate APY?"))
        system = KnowledgeSystem(query_interpreter=interpreter)
        pages = [
            type("Page", (), {"url": "https://sample-cu.test/certificates", "title": "Certificate rates",
                              "markdown": "# Certificate rates\n\n6-month certificate APY: 3.23%\n", "fetched_at": "2027-01-05"})(),
            type("Page", (), {"url": "https://sample-cu.test/other-certificate-rates", "title": "Certificate rates",
                              "markdown": "# Certificate rates\n\n6-month certificate APY: 3.48%\n", "fetched_at": "2027-01-05"})(),
        ]
        system.ingest(type("Snapshot", (), {"snapshot_id": "synthetic", "taken_on": "2027-01-05", "pages": pages})())
        answer = system.answer("What is the 6-month certificate APY?")
        self.assertFalse(answer.confident)
        self.assertEqual(interpreter.calls, ["What is the 6-month certificate APY?"])

    def test_ambiguous_interpretation_declines_instead_of_using_keyword_match(self):
        interpreter = FakeInterpreter(QueryInterpretation("clarify"))
        system = KnowledgeSystem(query_interpreter=interpreter)
        system.ingest(type("Snapshot", (), {
            "snapshot_id": "synthetic", "taken_on": "2027-01-05", "pages": [type("Page", (), {
                "url": "https://sample-cu.test/certificates", "title": "Certificate rates",
                "markdown": "# Certificate rates\n\n6-month certificate APY: 3.23%\n",
                "fetched_at": "2027-01-05",
            })()],
        })())
        answer = system.answer("What would I earn by parking my cash for half a year?")
        self.assertFalse(answer.confident)
        self.assertIn("clarify", answer.text.lower())


if __name__ == "__main__":
    unittest.main()
