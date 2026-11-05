"""Boundary types mirror the official contract without importing the private kit."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Source:
    url: str
    snapshot_id: Optional[str] = None
    quote: Optional[str] = None


@dataclass
class Answer:
    text: str
    sources: list[Source] = field(default_factory=list)
    confident: bool = True
    conflict_note: Optional[str] = None

    def __str__(self) -> str:
        """A human-readable answer is its text, without provenance metadata."""
        return self.text


@dataclass
class Conflict:
    topic: str
    values: list[str]
    sources: list[Source]
    resolution: Optional[str] = None
    reason: Optional[str] = None


@dataclass(frozen=True)
class Document:
    url: str
    title: str
    markdown: str
    snapshot_id: str
    taken_on: str
    fetched_at: str

    def source(self, quote: str) -> Source:
        if quote not in self.markdown:
            raise ValueError("Citation quote must occur in the original document")
        return Source(self.url, self.snapshot_id, quote)


def abstain(reason: str = "The supplied evidence does not establish that.") -> Answer:
    return Answer("I don't know. " + reason, confident=False)
