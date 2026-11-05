"""Small normalization helpers; raw source text is retained separately."""
from __future__ import annotations

import html
import re
import sys
import unicodedata
from datetime import datetime
from typing import Optional


def clean(text: str) -> str:
    text = html.unescape(html.unescape(text))
    text = re.sub(r"!\[[^\]]*\]\([^\n]*?\)", " ", text)
    text = re.sub(r"\[([^\]]+)\]\([^\s)]+(?:\s+\"[^\"]*\")?\)", r"\1", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("\\r\\n", " ").replace("\\", " ")
    return re.sub(r"\s+", " ", text.replace("**", "").replace("_", "")).strip(" #*|")


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", clean(text)).lower()
    text = text.translate(str.maketrans({"–": "-", "—": "-", "’": "'", "‑": "-"}))
    return re.sub(r"\s+", " ", text)


def parse_date(value: str) -> Optional[str]:
    value = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", value.strip())
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%B %d, %Y", "%b %d, %Y", "%B %d %Y", "%b %d %Y"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def tokens(text: str) -> set[str]:
    # Every historical passage retains a token set. Share repeated vocabulary
    # strings across observations instead of allocating a copy per passage.
    return {sys.intern(word) for word in re.findall(r"[a-z0-9]+", normalize(text))}
