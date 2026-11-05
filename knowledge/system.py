"""Coordinate evidence ingestion, historical cutoffs, and grounded answers."""
from __future__ import annotations

import calendar
import re
from datetime import date
from typing import Optional, Protocol

from knowledge.llm import QueryInterpretation
from knowledge.models import Answer, Conflict, Document, abstain
from knowledge.text import parse_date


class QueryInterpreter(Protocol):
    """Optional language interpreter; it must never provide answer facts."""

    def interpret(self, question: str) -> Optional[QueryInterpretation]: ...


def question_date(question: str) -> Optional[str]:
    """Only infer dates explicitly introduced as an as-of/history request."""
    m = re.search(r"\bas (?:of|at)\s+(\d{4}-\d{2}-\d{2})", question, re.I)
    if m:
        return m.group(1)
    m = re.search(r"\b(?:as of|back in|in)\s+([A-Za-z]+)\s+(\d{4})\b", question, re.I)
    if m and re.search(r"\b(was|were|as of|back in|historical)\b", question, re.I):
        first = parse_date(f"{m[1]} 1, {m[2]}")
        if first:
            d = date.fromisoformat(first)
            return d.replace(day=calendar.monthrange(d.year, d.month)[1]).isoformat()
    return None


def comparison_dates(question: str, latest: str) -> Optional[tuple[str, str]]:
    if not re.search(r"\b(changed?|changes|compare|comparison|difference|increase|decrease)\b", question, re.I):
        return None
    days = re.findall(r"\b\d{4}-\d{2}-\d{2}\b", question)
    if not days:
        for month, year in re.findall(r"\b([A-Za-z]+)\s+(\d{4})\b", question):
            first = parse_date(f"{month} 1, {year}")
            if first:
                d = date.fromisoformat(first)
                days.append(d.replace(day=calendar.monthrange(d.year, d.month)[1]).isoformat())
    if len(days) >= 2:
        return days[0], days[1]
    if len(days) == 1 and re.search(r"\bsince\b", question, re.I):
        return days[0], latest
    return None


class KnowledgeSystem:
    """In-memory history with deterministic, citation-checked query dispatch.

    The public snapshot date defines observability. Extractors separately use
    effective/publication dates for the claims inside each observed document.
    """

    def __init__(self, query_interpreter: Optional[QueryInterpreter] = None) -> None:
        from knowledge.content import ContentKnowledge
        from knowledge.rates import RateKnowledge

        self.rates = RateKnowledge()
        self.content = ContentKnowledge()
        self._snapshots: dict[str, str] = {}
        self._documents: dict[tuple[str, str], Document] = {}
        self._first: Optional[str] = None
        self._latest: Optional[str] = None
        self.query_interpreter = query_interpreter

    def ingest(self, snapshot) -> None:
        """Validate a pull before mutating state; accept official duck types."""
        sid = snapshot.snapshot_id
        taken_on = date.fromisoformat(snapshot.taken_on).isoformat()
        if not isinstance(sid, str) or not sid:
            raise ValueError("snapshot_id must be a nonempty string")
        if sid in self._snapshots:
            raise ValueError("A snapshot_id may only be ingested once")
        if self._latest and taken_on < self._latest:
            raise ValueError("Snapshots must be ingested in chronological order")
        documents = []
        seen = set()
        for page in snapshot.pages:
            if not isinstance(page.url, str) or not re.match(r"https?://[^/\s]+", page.url):
                raise ValueError("Each page needs an absolute HTTP(S) source URL")
            if page.url in seen:
                raise ValueError("Duplicate source URL inside a snapshot")
            if not isinstance(page.markdown, str):
                raise ValueError("Page markdown must be a string")
            seen.add(page.url)
            documents.append(Document(page.url, page.title or "", page.markdown,
                                      sid, taken_on, page.fetched_at))
        for doc in documents:
            self.rates.ingest(doc)
            self.content.ingest(doc)
            self._documents[(sid, doc.url)] = doc
        self._snapshots[sid] = taken_on
        self._first = self._first or taken_on
        self._latest = taken_on

    def _validate_sources(self, answer: Answer, cutoff: str) -> Answer:
        """Reject an answer if any citation lacks observed, verbatim evidence."""
        if answer.confident and not answer.sources:
            return abstain("There is no verifiable supporting source.")
        for source in answer.sources:
            doc = self._documents.get((source.snapshot_id, source.url))
            if not doc or doc.taken_on > cutoff or not source.quote or source.quote not in doc.markdown:
                return abstain("The supporting evidence could not be verified.")
        return answer

    def answer(self, question: str, as_of: Optional[str] = None) -> Answer:
        if not isinstance(question, str) or not question.strip():
            return abstain("Please provide a nonempty question.")
        if len(question) > 10000:
            return abstain("Please shorten the question.")
        if not self._latest:
            return abstain("No snapshots have been ingested.")
        comparison = comparison_dates(question, self._latest)
        requested = as_of if as_of is not None else (None if comparison else question_date(question))
        if requested is not None:
            try:
                if not isinstance(requested, str):
                    raise ValueError("Invalid date")
                cutoff = date.fromisoformat(requested).isoformat()
            except ValueError:
                return abstain("Use an ISO calendar date for as_of.")
            if cutoff < self._first:
                return abstain("That date precedes the available snapshots.")
            if cutoff > self._latest:
                return abstain("That date is later than the available snapshots.")
        else:
            cutoff = self._latest
        if comparison:
            start, end = comparison
            try:
                start = date.fromisoformat(start).isoformat()
                end = date.fromisoformat(end).isoformat()
            except ValueError:
                return abstain("Use valid calendar dates for the comparison.")
            if not self._first <= start <= end <= cutoff:
                return abstain("Both comparison dates must be within the available evidence period.")
            answer = self.rates.changes(question.strip(), start, end)
            return self._validate_sources(answer or abstain(), end)
        original_question = question.strip()
        lookup_question = original_question
        if self.query_interpreter is not None:
            interpretation = self.query_interpreter.interpret(original_question)
            if interpretation is not None:
                if interpretation.decision == "clarify":
                    return abstain("Please clarify which product or information you mean.")
                if interpretation.decision == "rewrite" and interpretation.rewritten_question:
                    # Keep the original words as well so explicit qualifiers
                    # remain visible to the deterministic selector.
                    lookup_question += "\n" + interpretation.rewritten_question
        answer = self.rates.answer(lookup_question, cutoff)
        if answer is None:
            answer = self.content.answer(lookup_question, cutoff)
        if answer is None:
            answer = abstain()
        return self._validate_sources(answer, cutoff)

    def conflicts(self) -> list[Conflict]:
        """Expose source-grounded disagreements without fabricating resolutions."""
        reports = self.rates.conflicts() + self.content.conflicts()
        for report in reports:
            for source in report.sources:
                doc = self._documents.get((source.snapshot_id, source.url))
                if not doc or not source.quote or source.quote not in doc.markdown:
                    raise ValueError("Conflict report contains an unverifiable source")
        return reports
