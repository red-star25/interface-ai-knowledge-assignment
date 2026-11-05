"""Extractive content answering with dated evidence and conservative entity checks.

No answer values live in this module. Specialized intents select source passages;
all names, amounts, dates, links and schedules are read from ingested documents.
"""
from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional
from urllib.parse import urlsplit

from .models import Answer, Conflict, Document, abstain
from .text import clean, normalize, parse_date, tokens

_DATE = re.compile(r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?) \d{1,2}, \d{4}\b", re.I)
_STOP = set("a an and are as at be been by can could do does for from give has have how i in is it me my of on or our please provide say tell that the their there these they this to us was we what when where which who will with would you your now current currently dupaco account accounts bank banking credit union get know like information about all any only than more most same still today".split())
_SYNONYMS = {"cd": "certificate", "cds": "certificate", "certificates": "certificate", "hours": "hour", "branches": "branch", "locations": "location", "fees": "fee", "cost": "fee", "charge": "fee", "costs": "fee", "students": "student", "university": "student", "college": "student", "eligible": "eligibility", "eligibility": "eligibility", "rates": "rate", "loans": "loan", "cards": "card", "wallets": "wallet", "recognition": "recognize", "recognized": "recognize", "received": "receive", "repayment": "repay", "flexibility": "flexible"}


def _terms(value: str) -> set[str]:
    return {_SYNONYMS.get(t, t) for t in tokens(value) if t not in _STOP and len(t) > 1}


def _published(doc: Document) -> Optional[str]:
    """Article dates precede the H1; recommendation-card dates are not dates of it."""
    first_heading = re.search(r"^# ", doc.markdown, re.M)
    prefix = doc.markdown[:first_heading.start()] if first_heading else doc.markdown[:350]
    match = _DATE.search(prefix)
    return parse_date(match.group()) if match else None


def _authority(doc: Document) -> int:
    path = urlsplit(doc.url).path.lower()
    if re.search(r"/(tag|author)/", path) or "campaignid=" in doc.url.lower():
        return 0
    if "/learn/blog/" in path or "/business/resources/" in path:
        return 1
    if "/newsroom/" in path:
        return 2
    return 3


@dataclass(frozen=True)
class Passage:
    doc: Document
    raw: str
    heading: str
    text: str
    words: frozenset[str]
    published: Optional[str]

    @property
    def context(self) -> str:
        return normalize(self.heading + " " + self.doc.title + " " + self.text)

_FEE_VALUE = re.compile(r"\$\s*\d[\d,]*(?:\.\d+)?|\d+(?:\.\d+)?\s*%|\bat no charge\b|\bno charge\b|\bfree\b", re.I)


def _effective_fee_date(doc: Document) -> Optional[str]:
    # File names and crawl dates are not effective dates. Only a labelled date
    # in the actual schedule establishes future eligibility or supersession.
    for match in re.finditer(r"\beffective(?:\s+(?:as of|date|on))?\s*[:=-]?\s*([^\n]{1,70})", clean(doc.markdown[:1500]), re.I):
        value = match[1]
        date_match = _DATE.search(value) or re.search(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}/\d{2,4}\b", value)
        if date_match:
            parsed = parse_date(date_match.group())
            if parsed:
                return parsed
    return None


def _fee_value(value: str) -> str:
    text = normalize(value).replace(",", "").replace(" ", "")
    if text in {"free", "nocharge", "atnocharge"}:
        return "free"
    number = re.search(r"\d+(?:\.\d+)?", text)
    unit = "$" if "$" in text else "%"
    return unit + format(Decimal(number.group()).normalize(), "f")


def _fee_scope(value: str) -> tuple[str, ...]:
    text = normalize(value)
    scope = []
    if re.search(r"\bbusiness\b|\bcommercial\b", text):
        scope.append("business")
    elif re.search(r"\bconsumer\b|\bpersonal\b", text):
        scope.append("consumer")
    if re.search(r"\bnon[- ]?members?\b", text):
        scope.append("nonmember")
    elif re.search(r"\bmembers?\s+only\b|\bfor members?\b", text):
        scope.append("member")
    return tuple(scope)


@dataclass(frozen=True)
class FeeClaim:
    doc: Document
    raw: str
    text: str
    label: str
    scope: tuple[str, ...]
    values: tuple[str, ...]
    effective: Optional[str]
    words: frozenset[str]
    heading: str

    @property
    def key(self) -> tuple[str, tuple[str, ...]]:
        return self.label, self.scope


class ContentKnowledge:
    def __init__(self) -> None:
        self._versions: dict[str, list[Document]] = defaultdict(list)
        self._passages: dict[tuple[str, str], list[Passage]] = {}
        self._cache: dict[str, list[Passage]] = {}
        self._context_words: dict[tuple[str, str], frozenset[str]] = {}
        self._title_words: dict[tuple[str, str, str], frozenset[str]] = {}
        self._fee_claims: dict[tuple[str, str], list[FeeClaim]] = {}

    def ingest(self, doc: Document) -> None:
        self._versions[doc.url.rstrip("/")].append(doc)
        self._versions[doc.url.rstrip("/")].sort(key=lambda d: (d.taken_on, d.snapshot_id))
        self._passages[(doc.url, doc.snapshot_id)] = self._split(doc)
        self._fee_claims[(doc.url, doc.snapshot_id)] = self._parse_fees(doc, self._passages[(doc.url, doc.snapshot_id)])
        self._context_words[(doc.url, doc.snapshot_id)] = frozenset(_terms(doc.title + " " + doc.markdown[:5000]))
        for p in self._passages[(doc.url, doc.snapshot_id)]:
            key = (doc.url, doc.snapshot_id, p.heading)
            if key not in self._title_words:
                self._title_words[key] = frozenset(_terms(doc.title + " " + p.heading))
        self._cache.clear()

    @staticmethod
    def _split(doc: Document) -> list[Passage]:
        passages = []
        headings: dict[int, str] = {}
        skip = False
        published = _published(doc)
        for match in re.finditer(r"\S[^\n]*(?:\n(?!\s*\n)[^\n]*)*", doc.markdown):
            raw = match.group().strip()
            heading = re.match(r"^(#{1,6})\s+(.+)", raw)
            if not heading and re.fullmatch(r"\*\*[A-Za-z][A-Za-z /-]{1,60}\*\*", raw):
                heading = re.match(r"^(#{1,6})\s+(.+)", "#### " + clean(raw))
            if heading:
                level, title = len(heading[1]), clean(heading[2])
                if re.search(r"handpicked|related (?:articles|posts)|you may also", title, re.I):
                    skip = True
                    continue
                if skip and level <= 3 and re.search(r"frequently asked|fine print|questions.*answers|disclosure|faq", title, re.I):
                    skip = False
                if skip:
                    continue
                headings = {k: v for k, v in headings.items() if k < level}
                headings[level] = title
                continue
            if skip or not raw or re.match(r"^(?:!\[|\[!\[|✕|\* \* \*|[\-*]{3,}\s*$)", raw):
                continue
            text = clean(raw)
            if len(text) < 10 or text in {"Previous", "Next", "Loading locations..."} or text.endswith("Cancel"):
                continue
            context = " > ".join(headings.values())
            passages.append(Passage(doc, raw, context, text, frozenset(_terms(text + " " + context)), published))
        return passages

    def _active(self, cutoff: str) -> list[Passage]:
        if cutoff in self._cache:
            return self._cache[cutoff]
        result = []
        for versions in self._versions.values():
            eligible = [d for d in versions if d.taken_on <= cutoff]
            if not eligible:
                continue
            doc = eligible[-1]
            publication = _published(doc)
            if publication and publication > cutoff:
                continue
            result.extend(self._passages[(doc.url, doc.snapshot_id)])
        self._cache[cutoff] = result
        return result

    @staticmethod
    def _make(passages: list[Passage], texts: Optional[list[str]] = None, note: Optional[str] = None) -> Answer:
        selected, seen = [], set()
        for p in passages:
            key = (p.doc.url, p.doc.snapshot_id, p.raw)
            if key not in seen:
                seen.add(key)
                selected.append(p)
        return Answer(" ".join(texts if texts is not None else [p.text for p in selected]), [p.doc.source(p.raw) for p in selected], conflict_note=note)

    def _search(self, question: str, passages: list[Passage], limit: int = 10) -> list[Passage]:
        query = _terms(question)
        if not query:
            return []
        df = Counter(w for p in passages for w in p.words if w in query)
        n = len(passages)
        scored = []
        for p in passages:
            overlap = query & p.words
            if not overlap or _authority(p.doc) == 0:
                continue
            score = sum(math.log(1 + n / (1 + df[w])) for w in overlap)
            title_overlap = query & self._title_words[(p.doc.url, p.doc.snapshot_id, p.heading)]
            score += 0.65 * sum(math.log(1 + n / (1 + df[w])) for w in title_overlap)
            score *= (0.7 + 0.3 * len(overlap) / len(query))
            score *= 1 + 0.08 * _authority(p.doc)
            score /= 1 + max(0, len(p.text) - 600) / 1800
            scored.append((score, p))
        scored.sort(key=lambda x: (-x[0], -_authority(x[1].doc), x[1].doc.url, x[1].raw))
        return [p for _, p in scored[:limit]]

    def answer(self, question: str, cutoff: str) -> Optional[Answer]:
        q = normalize(question)
        passages = self._active(cutoff)
        if not passages:
            return None
        # These handlers describe information types; returned values are source text.
        if "routing" in q:
            return self._routing(question, passages)
        if re.search(r"\b(link|url|online|website)\b", q) and re.search(r"\b(join|become|locator|branch|certificate|cd|rate)\b", q):
            linked = self._link(question, passages)
            if linked:
                return linked
        if re.search(r"volunteer|\bvto\b", q):
            return self._volunteer(q, passages, cutoff)
        if re.search(r"how many.*(?:branch|location)|number of.*branch", q):
            return self._branch_count(passages)
        if "forbes" in q:
            return self._award(q, passages)
        if re.search(r"lobby|drive[- ]?(?:up|through)|branch.*hours|hours.*branch", q):
            return self._hours(question, passages)
        if re.search(r"branch|hy-vee|hy vee", q):
            branch = self._branch(question, passages, cutoff)
            if branch:
                return branch
        if re.search(r"(?:eligible|eligibility|who).*\b(?:member|join)|who can join|membership requirements", q):
            return self._membership(passages)
        if re.search(r"(?:update|change).*\b(?:contact|address|phone|email)", q):
            return self._contact(passages, question)
        if re.search(r"wallet|mobile payment|apple pay|google pay|samsung pay", q):
            direct = [p for p in passages if _authority(p.doc) == 3 and re.search(r"Apple Pay.*Google Pay.*Samsung Pay|Apple Pay.*Samsung Pay.*Google Pay", p.text) and re.search(r"(?:debit|credit|Dupaco) cards", p.text, re.I)]
            if direct and re.search(r"add|compatible|work|use|which|can i", q):
                return self._make([min(direct, key=lambda p: len(p.text))])
            return self._extract(question, passages, anchor=r"mobile (?:payment|wallet)|apple pay|google pay|samsung pay", multiple=True)
        if re.search(r"student|university|college", q) and re.search(r"loan|flexib|fund|borrow|repay", q):
            return self._student(question, passages)
        if re.search(r"\b(fee|fees|cost|charge|charges|replacement)\b", q) and not re.search(r"interest|\bapr\b|\bapy\b", q):
            fee = self._fee(question, passages, cutoff)
            if fee:
                return fee
            return abstain("No applicable published fee is established for the requested service and date.")
        if re.search(r"\b(rate|rates|apr|apy|dividend|interest)\b", q):
            return None
        return self._extract(question, passages)

    def _routing(self, question: str, passages: list[Passage]) -> Optional[Answer]:
        found = [(p, re.search(r"routing(?:\s+(?:transit|aba))?\s*(?:number|#)?\s*[:#-]?\s*(\d{9})", p.text, re.I)) for p in passages]
        named = _terms(question) - {"routing", "number", "repeat", "aba", "transit"}
        found = [(p, m) for p, m in found if m and (not named or named <= _terms(p.doc.title + " " + p.text))]
        if not named and found:
            highest = max(_authority(p.doc) for p, _ in found)
            found = [(p, m) for p, m in found if _authority(p.doc) == highest]
        if not found:
            return None
        values = {m[1] for _, m in found}
        if len(values) > 1:
            return abstain("The routing-number sources disagree.")
        p, m = max(found, key=lambda x: (_authority(x[0].doc), x[0].doc.taken_on))
        return self._make([p], ["Routing number: " + m[1] + "."])

    def _link(self, question: str, passages: list[Passage]) -> Optional[Answer]:
        q = normalize(question)
        if re.search(r"join|become.*member", q):
            goal = r"join|become.*member"
        elif re.search(r"locator|branch|atm", q):
            goal = r"branch|atm|location"
        elif re.search(r"certificate|\bcd\b", q):
            goal = r"certificate.*rate|rate.*certificate|savings.*rate"
        else:
            return None
        candidates = []
        for p in passages:
            if _authority(p.doc) < 3:
                continue
            for link in re.finditer(r"\[([^]\n]+)\]\((https?://[^\s)]+)\)", p.raw):
                label, url = clean(link[1]), link[2]
                applicable = re.search(goal, label, re.I)
                if "certificate" in goal and "rate" in normalize(label) and "certificate" in p.context:
                    applicable = True
                if applicable:
                    score = len(_terms(question) & _terms(label))
                    if "rate" in q and "rate" in normalize(label):
                        score += 2
                    if "#rates" in url and "rate" in q:
                        score += 1
                    if re.search(r"join|become.*member", q) and urlsplit(url).hostname != urlsplit(p.doc.url).hostname:
                        score += 2
                    candidates.append((score, p, label, url))
        if not candidates:
            return None
        candidates.sort(key=lambda x: (-x[0], x[1].doc.url, x[3]))
        _, p, label, url = candidates[0]
        return self._make([p], [f"{label}: {url}"])

    def _branch_count(self, passages: list[Passage]) -> Optional[Answer]:
        candidates = []
        for p in passages:
            match = re.search(r"\b(\d+)\s+(?:full-service\s+)?branch\s+(?:office\s+)?locations\b", p.text, re.I)
            if match:
                candidates.append((p.published or "", p.doc.taken_on, p, match[1]))
        if not candidates:
            return None
        latest = max(c[0] for c in candidates)
        current = [c for c in candidates if c[0] == latest]
        values = {c[3] for c in current}
        if len(values) != 1:
            return abstain("Equally dated sources give different branch counts.")
        p, value = current[0][2:]
        note = None
        if any(c[3] != value for c in candidates):
            note = "Older dated organization descriptions report different counts; the newest dated description supplies this count."
        return self._make([p], [f"The newest dated organization description reports {value} branch office locations."], note)

    def _award(self, q: str, passages: list[Passage]) -> Optional[Answer]:
        candidates = []
        for p in passages:
            if "forbes" not in p.text.lower() or not re.search(r"forbes", p.doc.title, re.I):
                continue
            if re.search(r"credit union|best.in.state|recognition|recognize", q) and "small employer" in p.doc.title.lower():
                continue
            if re.search(r"recogniz|named|ranked|time|year in a row", p.text, re.I):
                candidates.append(p)
        if not candidates:
            return None
        candidates.sort(key=lambda p: (p.published or "", len(_terms(q) & p.words)), reverse=True)
        newest = candidates[0].published
        same = [p for p in candidates if p.published == newest]
        best = max(same, key=lambda p: bool(re.search(r"(?:first|second|third|fourth|fifth|sixth|\d+)(?:\s+time|\s+year)", p.text, re.I)))
        return self._make([best])

    def _volunteer(self, q: str, passages: list[Passage], cutoff: str) -> Optional[Answer]:
        years = re.findall(r"\b(?:19|20)\d{2}\b", q)
        year = str(int(cutoff[:4]) - 1) if "last year" in q else (years[-1] if years else None)
        candidates = []
        for p in passages:
            if not re.search(r"volunteer time off|\bvto\b", p.text, re.I):
                continue
            if re.search(r"\d+.{0,30}employees.{0,35}(?:used|utilized)|(?:used|utilized).{0,35}\d+.{0,15}employees", p.text, re.I):
                if year and year not in p.text:
                    continue
                candidates.append(p)
        if not candidates:
            return abstain("No employee Volunteer Time Off count for the requested year is established in the supplied evidence.")
        candidates.sort(key=lambda p: (p.published or "", p.doc.taken_on), reverse=True)
        return self._make([candidates[0]])

    def _hours(self, question: str, passages: list[Passage]) -> Optional[Answer]:
        q = normalize(question)
        drive = bool(re.search(r"drive|drive-through", q))
        kind = r"drive.up|drive.through" if drive else r"lobby"
        specific = re.search(r"\b(?:the|for|at)\s+([a-z][a-z\s'-]{2,35}?)\s+branch", q)
        specific_words = _terms(specific[1]) if specific else set()
        specific_words -= {"general", "all", "same", "dupaco", "address", "lobby", "hour"}
        docs = {p.doc.url: p.doc for p in passages}
        candidates = []
        for doc in docs.values():
            if specific_words and not specific_words <= self._context_words[(doc.url, doc.snapshot_id)]:
                continue
            label_pattern = r"(?:^|\n)(?:\*\*(?:" + kind + r")(?: hours)?\*\*|#{1,6}\s+(?:" + kind + r")(?: hours)?[^\n]*)[^\S\n]*"
            for label in re.finditer(label_pattern, doc.markdown, re.I):
                after = doc.markdown[label.end():]
                lines = list(re.finditer(r"[^\n]+", after))
                schedule = []
                for line in lines:
                    if re.match(r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|Mon\b|Tue\b|Wed\b|Thu\b|Fri\b|Sat\b|Sun\b)", line.group(), re.I):
                        schedule.append(line)
                    else:
                        break
                if not schedule:
                    continue
                raw = after[schedule[0].start():schedule[-1].end()]
                candidates.append(Passage(doc, raw, clean(doc.title) + " " + ("Drive-up" if drive else "Lobby"), clean(raw), frozenset(_terms(raw)), _published(doc)))
        if not candidates:
            return abstain("A supported schedule for that branch is not available.")
        candidates.sort(key=lambda p: (_authority(p.doc), len(re.findall(r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)", p.raw)), p.published or ""), reverse=True)
        chosen = [candidates[0]]
        prefix = "Drive-up" if drive else "Lobby"
        texts = [f"{prefix} schedule published for {chosen[0].doc.title}: {chosen[0].text}"]
        if not specific_words:
            texts.insert(0, f"{prefix} schedules vary by branch.")
            if re.search(r"all|same", q):
                different = next((p for p in candidates[1:] if p.text != chosen[0].text), None)
                if different:
                    chosen.append(different)
                    texts.append("Another published branch schedule is: " + different.text)
            texts.append("Which branch would you like checked?")
        return self._make(chosen, texts)

    def _branch(self, question: str, passages: list[Passage], cutoff: str) -> Optional[Answer]:
        q = normalize(question)
        # Branch identifiers must occur in the same source as the evidence.
        entity = re.search(r"\b(?:the|of|for|at)\s+([a-z][a-z\s'-]{1,35}?)\s+branch", q)
        entity_words = _terms(entity[1]) if entity else set()
        entity_words -= {"address", "lobby", "hour", "general", "same", "all"}
        if re.search(r"hy[- ]vee", q):
            entity_words = {"hy", "vee"}
        if not entity_words:
            return None
        candidates = [p for p in passages if entity_words <= self._context_words[(p.doc.url, p.doc.snapshot_id)]]
        if not candidates:
            return abstain("The supplied evidence does not establish that branch's details.")
        if re.search(r"address|where.*located|location of", q):
            addresses = [p for p in candidates if re.search(r"\b\d{2,6}\s+\w+.{0,70}\b(?:IA|IL|WI|Iowa|Illinois|Wisconsin)\b.{0,15}\b\d{5}\b", p.text)]
            # Locator sections have a generic heading but an address includes city.
            named = [p for p in addresses if entity_words & _terms(p.text)]
            if named:
                addresses = named
            if addresses:
                best = min(addresses, key=lambda p: (len(p.text), -_authority(p.doc)))
                return self._make([best])
            return abstain("A supported street address for that branch is not available.")
        if re.search(r"close|closed|open|full.service|where.*go", q):
            matches = [p for p in candidates if re.search(r"(?:will close|closure|full.service branches|same services)", p.text, re.I)]
            if not matches:
                return None
            if re.search(r"full.service|where.*go", q):
                matches = [p for p in matches if re.search(r"same services|full.service branches", p.text, re.I)]
            else:
                matches = [p for p in matches if re.search(r"(?:will close|closed).{0,60}\d{4}", p.text, re.I)] or matches
            if matches:
                matches.sort(key=lambda p: (p.published or "", bool(re.search(r"same services|branches at", p.text, re.I)), -len(p.text)), reverse=True)
                p = matches[0]
                text = p.text
                event = _DATE.search(text)
                if event and parse_date(event.group()) and parse_date(event.group()) <= cutoff and re.search(r"still open|open today", q):
                    text = "The source scheduled closure for " + event.group() + ". " + text
                return self._make([p], [text])
        return None

    def _membership(self, passages: list[Passage]) -> Optional[Answer]:
        eligible = [p for p in passages if _authority(p.doc) == 3 and re.search(r"eligible.*join|who can join|who.*eligible", p.heading, re.I)]
        selected = [p for p in eligible if re.search(r"live or work|immediate family|belong to|open.*savings", p.text, re.I)]
        if not selected:
            return None
        # The location qualifier can be in an earlier section on the same page.
        doc = selected[0].doc
        geography = [p for p in passages if p.doc is doc and p not in selected and re.search(r"charter area (?:covers|includes)|(?:covers|includes).*counties|you can find us in", p.text, re.I)]
        return self._make(selected[:4] + geography[:1])

    def _contact(self, passages: list[Passage], question: str) -> Optional[Answer]:
        field = r"contact information" if "contact" in normalize(question) else r"contact information|mailing address|phone number|email address"
        direct = [p for p in passages if _authority(p.doc) == 3 and re.search(r"(?:update|change)(?:\s+(?:your|my|the))?\s+(?:" + field + r")", p.text, re.I)]
        if direct:
            return self._make([min(direct, key=lambda p: len(p.text))])
        contact = [p for p in passages if _authority(p.doc) == 3 and re.search(r"specific account question|general questions", p.text, re.I) and re.search(r"\d{3}-\d{3}-\d{4}", p.text)]
        if contact:
            p = min(contact, key=lambda p: len(p.text))
            phone = re.search(r"\d{3}-\d{3}-\d{4}", p.text)
            return self._make([p], ["For help updating contact information, call the credit union at " + phone.group() + "."])

        return None

    def _student(self, question: str, passages: list[Passage]) -> Optional[Answer]:
        selected = [p for p in passages if _authority(p.doc) == 3 and "student loan" in normalize(p.doc.title + " " + p.heading)]
        if not selected:
            return None
        q = normalize(question)
        if re.search(r"flexib|options|new university", q):
            relevant = [p for p in selected if re.search(r"flexible|origination|defer full|no prepayment", p.text, re.I)]
            if relevant:
                return self._make(relevant[:4], ["Student loans and refinancing: "] + [p.text for p in relevant[:4]])
        return self._extract(question, selected, anchor=r"student")

    @staticmethod
    def _parse_fees(doc: Document, passages: list[Passage]) -> list[FeeClaim]:
        result = []
        effective = _effective_fee_date(doc)
        for p in passages:
            section = p.heading
            lines = list(re.finditer(r"[^\n]+", p.raw))
            for index, line in enumerate(lines):
                raw = line.group()
                text = clean(raw)
                amounts = list(_FEE_VALUE.finditer(text))
                if not amounts:
                    if len(text) < 85 and re.search(r"services|charges|fees|consumer|business|members", text, re.I):
                        section = text
                    continue
                context = section + " " + doc.title
                if not re.search(r"fee|charge|replacement", context + " " + text, re.I):
                    continue
                # A row and its immediately following waiver form one claim.
                # The exact contiguous span remains verifiable in the source.
                if index + 1 < len(lines):
                    following = clean(lines[index + 1].group())
                    if re.match(r"(?:waived|\*?you will not|free if|except|waiver)", following, re.I):
                        raw = p.raw[line.start():lines[index + 1].end()]
                        text = clean(raw)
                        amounts = list(_FEE_VALUE.finditer(text))
                label = normalize(_FEE_VALUE.sub("AMOUNT", text))
                label = re.sub(r"[|:*]", " ", label)
                label = re.sub(r"\s+", " ", label).strip(" .")
                values = tuple(_fee_value(m.group()) for m in amounts)
                scope = _fee_scope(section + " " + text)
                result.append(FeeClaim(doc, raw, text, label, scope, values, effective, frozenset(_terms(text + " " + section)), section))
        return result

    def _active_fees(self, passages: list[Passage], cutoff: str) -> list[FeeClaim]:
        result = []
        for versions in self._versions.values():
            # A future-effective replacement at the same URL does not erase the
            # previously observed schedule before its effective date arrives.
            eligible = []
            for doc in versions:
                if doc.taken_on > cutoff or (_published(doc) and _published(doc) > cutoff):
                    continue
                claims = [f for f in self._fee_claims[(doc.url, doc.snapshot_id)] if not f.effective or f.effective <= cutoff]
                if claims:
                    eligible.append((doc, claims))
            if eligible:
                result.extend(eligible[-1][1])
        return result

    @staticmethod
    def _resolve_fee(claims: list[FeeClaim]) -> tuple[list[FeeClaim], Optional[str]]:
        authority = max(_authority(f.doc) for f in claims)
        current = [f for f in claims if _authority(f.doc) == authority]
        explicit = [f.effective for f in current if f.effective]
        if explicit:
            latest = max(explicit)
            current = [f for f in current if f.effective == latest]
        else:
            # A dated article may update another dated article. An undated
            # official schedule is not assigned an invented effective date.
            publications = [_published(f.doc) for f in current]
            if all(publications):
                latest = max(publications)
                current = [f for f in current if _published(f.doc) == latest]
        values = {f.values for f in current}
        if len(values) > 1:
            return current, "Equally applicable fee schedules disagree and no dated supersession resolves them."
        current.sort(key=lambda f: (f.doc.url, f.raw))
        return current[:1], None

    def _fee(self, question: str, passages: list[Passage], cutoff: str) -> Optional[Answer]:
        query = _terms(question) - {"fee", "pay", "much", "what", "replacement"}
        candidates = self._active_fees(passages, cutoff)
        requested_scope = set(_fee_scope(question))
        if requested_scope:
            candidates = [f for f in candidates if not set(f.scope) - requested_scope and (not f.scope or set(f.scope) <= requested_scope)]
        named = re.search(r"(?:the|for|on)\s+([A-Z][A-Za-z'-]+(?:\s+[A-Z][A-Za-z'-]+)*)\s+(?:(?:debit|credit)\s+)?(?:card|account|loan|branch)", question)
        if named:
            entity = _terms(named[1])
            candidates = [f for f in candidates if entity <= _terms(f.doc.title + " " + f.heading + " " + f.text)]
            if not candidates:
                return abstain("The requested product's fee is not established by the evidence.")
        scored = [(len(query & f.words), len(query & _terms(f.text)), f) for f in candidates]
        scored = [r for r in scored if r[0] >= min(2, len(query)) and r[1] > 0]
        if not scored:
            return None
        best = max((r[0], r[1]) for r in scored)
        applicable = [f for a, b, f in scored if (a, b) == best]
        grouped: dict[tuple[str, tuple[str, ...]], list[FeeClaim]] = defaultdict(list)
        for f in applicable:
            grouped[f.key].append(f)
        # Lexical similarity does not prove two differently-labelled fees are
        # the same charge. Require one matching label (scopes may differ).
        labels = {key[0] for key in grouped}
        if len(labels) > 1:
            return abstain("More than one fee matches; the supplied evidence needs a more specific fee or account qualifier.")
        chosen = []
        for claims in grouped.values():
            winners, problem = self._resolve_fee(claims)
            if problem:
                return Answer("I don't know. " + problem, [f.doc.source(f.raw) for f in winners], confident=False, conflict_note=problem)
            chosen.extend(winners)
        chosen.sort(key=lambda f: (f.scope, f.doc.url))
        text = " ".join((" / ".join(f.scope).capitalize() + ": " if f.scope else "") + f.text for f in chosen)
        return Answer(text, [f.doc.source(f.raw) for f in chosen])

    def _fee_conflicts(self, passages: list[Passage], cutoff: str) -> list[Conflict]:
        groups: dict[tuple[str, tuple[str, ...]], list[FeeClaim]] = defaultdict(list)
        for f in self._active_fees(passages, cutoff):
            groups[f.key].append(f)
        result = []
        for (label, scope), claims in sorted(groups.items()):
            if len({f.values for f in claims}) < 2:
                continue
            winners, problem = self._resolve_fee(claims)
            values = sorted({" / ".join(f.values) for f in claims})
            sources = []
            seen = set()
            for f in claims:
                if f.values not in seen:
                    seen.add(f.values)
                    sources.append(f.doc.source(f.raw))
            resolution = None if problem else " / ".join(winners[0].values)
            reason = problem or "Prefer the applicable official schedule, then its newest explicit effective date; retain differing customer scopes separately."
            result.append(Conflict("Fee: " + label + (" (" + "/".join(scope) + ")" if scope else ""), values, sources, resolution, reason))
        return result

    def _extract(self, question: str, passages: list[Passage], anchor: Optional[str] = None, multiple: bool = False) -> Optional[Answer]:
        ranked = self._search(question, passages, limit=12)
        query = _terms(question)
        if anchor:
            ranked = [p for p in ranked if re.search(anchor, p.context, re.I)]
        if not ranked:
            return None
        top = ranked[0]
        if len(query & top.words) < min(2, len(query)):
            return None
        # Unknown named products must not borrow a nearby product's facts.
        named = re.search(r"(?:for|about|on|the)\s+([A-Z][A-Za-z'-]+(?:\s+[A-Z][A-Za-z'-]+){0,3})\s+(?:account|loan|branch|card)", question)
        if named and not _terms(named[1]) <= _terms(top.doc.title + " " + top.heading + " " + top.text):
            return abstain("The requested product is not established by the retrieved evidence.")
        if multiple:
            direct = [p for p in ranked if _authority(p.doc) == 3 and re.search(r"Apple Pay.*Google Pay.*Samsung Pay|Apple Pay.*Samsung Pay.*Google Pay", p.text)]
            if direct:
                return self._make([min(direct, key=lambda p: len(p.text))])
        # Free extraction must match all meaningful query nouns reasonably well.
        if len(query) >= 4 and len(query & top.words) / len(query) < 0.45:
            return None
        return self._make([top])

    def conflicts(self) -> list[Conflict]:
        # Organization counts are dated revisions, retaining all competing values
        # and their provenance, rather than comparing arbitrary numbers in prose.
        if not self._versions:
            return []
        cutoff = max(d.taken_on for docs in self._versions.values() for d in docs)
        passages = self._active(cutoff)
        candidates = []
        for p in passages:
            match = re.search(r"\b(\d+)\s+branch office locations\b", p.text, re.I)
            if match and p.published:
                candidates.append((p, match[1]))
        fees = self._fee_conflicts(passages, cutoff)
        if len({v for _, v in candidates}) < 2:
            return fees
        candidates.sort(key=lambda pair: (pair[0].published or "", pair[0].doc.url))
        chosen = {}
        for p, value in candidates:
            chosen[value] = p
        latest, winner = candidates[-1]
        return fees + [Conflict("Branch office locations (dated organization descriptions)", list(chosen), [p.doc.source(p.raw) for p in chosen.values()], winner, "Use the newest publication date for a changing organization count; crawl timestamps do not make old articles current.")]
