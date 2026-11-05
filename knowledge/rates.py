"""Table-backed financial facts with separate observation and effective dates.

Parsing is driven by column labels and product context, never evaluation IDs.
Values remain attached to the exact table from which they were read.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Optional
from urllib.parse import urlsplit

from .models import Answer, Conflict, Document, Source, abstain
from .text import clean, normalize, parse_date, tokens


PERCENT = re.compile(r"\d+(?:\.\d+)?\s*%")
TERM = re.compile(r"\b(\d+)\s*[- ]?\s*(months?|mos?|years?|yrs?)\b", re.I)
DATE = r"(?:\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4}|[A-Z][a-z]+\s+\d{1,2},?\s+\d{4})"
EFFECTIVE = re.compile(r"(?:effective(?:\s+as\s+of)?|as\s+of)[,: ]+(" + DATE + r")", re.I)
EXPIRES = re.compile(r"(?:offer\s+ended|expires?|ends?|valid\s+(?:until|through))[ :]+(" + DATE + r")", re.I)


def _term(text: str) -> Optional[int]:
    match = TERM.search(normalize(text))
    if not match:
        return None
    return int(match[1]) * (12 if match[2].startswith(("y", "yr")) else 1)


def _numbers(text: str) -> list[Decimal]:
    return [Decimal(x.replace(",", "")) for x in re.findall(r"\d[\d,]*(?:\.\d+)?", text)]


def _money(text: str) -> list[Decimal]:
    values = []
    for match in re.finditer(r"\$\s*(\d[\d,]*(?:\.\d+)?)\s*([km])?", normalize(text)):
        values.append(Decimal(match[1].replace(",", "")) * {"k": 1000, "m": 1000000, None: 1}[match[2]])
    return values


def _metric(header: str) -> Optional[str]:
    h = normalize(header)
    suffix = " intro" if "1st 6" in h or "intro" in h else " after promo" if "after" in h and "promot" in h else ""
    if "apy" in h or "annual percentage yield" in h:
        return "APY" + suffix
    if "apr" in h or "annual percentage rate" in h:
        return "APR" + suffix
    if "dividend" in h:
        return "dividend rate" + suffix
    if h in ("rate", "interest rate"):
        return "rate" + suffix
    return None


def _value_key(value: str) -> tuple[Decimal, ...]:
    return tuple(Decimal(x.strip().rstrip("%")) for x in PERCENT.findall(value))


def _name(text: str) -> str:
    n = normalize(text)
    n = re.sub(r"\b(?:account|accounts)\b", "", n)
    n = re.sub(r"\b(?:rates?|rate sheet)\s*$", "", n)
    return re.sub(r"\s+", " ", n).strip()


@dataclass(frozen=True)
class RateRow:
    product: str
    category: str
    label: str
    term: Optional[int]
    balance: str
    model_years: str
    purpose: str
    special: bool
    jumbo: bool
    business: bool
    metrics: tuple[tuple[str, str], ...]
    minimum: str
    effective_on: Optional[str]
    expires_on: Optional[str]
    authority: int
    doc: Document
    quote: str
    conditions: tuple[str, ...] = ()

    @property
    def key(self) -> tuple:
        balance = (tuple(_numbers(self.balance)), bool(re.search(r"\+|and up|or more|and above", normalize(self.balance))))
        return (self.product, self.term, balance, self.model_years,
                self.purpose, self.special, self.jumbo, self.business)

    def source(self) -> Source:
        return self.doc.source(self.quote)


def _identity(label: str, context: str, headers: list[str], cells: list[str], doc: Document) -> dict:
    text = normalize(label + " " + context)
    raw_product = label
    category = "deposit"
    term = _term(label)
    purpose = ""
    model_years = ""
    balance = ""
    business = "business" in text or "/business" in doc.url
    special = "special" in text
    jumbo = "jumbo" in text
    h = [normalize(x) for x in headers]
    if "certificate" in text or re.search(r"\bira\b|\broth\b|traditional:", text):
        category = "certificate"
        product = "certificate"
        if "roth" in text:
            product = "roth ira"
        elif "traditional" in text:
            product = "traditional ira"
        elif "ira" in text:
            product = "ira"
        if term is None:
            term = _term(" ".join(cells))
    elif "model year" in text:
        category = "auto" if "auto" in text or "motorcycle" in text else "recreational"
        product = "auto motorcycle loan" if category == "auto" else _name(context)
        model_years = normalize(label)
        term = _term(" ".join(cells))
    elif "conventional" in text or ("mortgage" in text and "relief" not in text):
        category = "mortgage"
        product = "mortgage"
        purpose = "refinance" if "refinance" in text else "purchase"
        amounts = _money(label)
        balance = str(amounts[0]) if amounts else ""
    elif "visa" in text or "credit card" in text:
        category = "card"
        product = "business " if business else ""
        product += "platinum visa" if "platinum" in text else "rewards visa" if "rewards" in text else _name(label)
        special = "intro" in normalize(label) or "balance transfer" in normalize(label)
    elif "heloc" in text or "home equity line" in text:
        category, product = "heloc", "home equity line of credit"
    elif "home equity" in text:
        category, product = "home equity", "home equity loan"
    elif "personal loan" in text:
        category, product = "personal", "personal loan"
    elif "home improvement" in text:
        category, product = "home improvement", "home improvement loan"
    elif any(x in text for x in ("boat", " rv ", "snowmobile", "jet ski", "atv")):
        category, product = "recreational", _name(context)
    else:
        product = _name(raw_product)
        if h and (h[0].startswith("balance") or h[0] in ("term", "loan amount", "loan type")):
            product = _name(context)
    for header, cell in zip(h, cells):
        if header == "term":
            term = _term(cell)
        if header.startswith("balance") or header == "loan amount":
            if category == "auto" and _term(cell) is not None:
                term = _term(cell)
            else:
                balance = clean(cell)
        if header == "loan program" and "model year" in normalize(cell):
            model_years = normalize(cell)
    if category in ("home equity", "home improvement", "personal", "recreational") and term is None:
        term = _term(label)
    if business and not product.startswith("business ") and category == "deposit":
        product = "business " + product
    return dict(product=product, category=category, label=clean(label), term=term,
                balance=balance, model_years=model_years, purpose=purpose,
                special=special, jumbo=jumbo, business=business)


def _context(lines: list[str], start: int) -> str:
    """The nearest product heading may be plain text in converted Markdown."""
    for line in reversed(lines[max(0, start - 30):start]):
        s = clean(line)
        if not s or len(s) > 100 or line.lstrip().startswith(("|", "[", "!", "- ")):
            continue
        if re.match(r"^\d+(?!st\b|nd\b|rd\b|th\b)[A-Za-z]", s):
            continue
        if any(w in normalize(s) for w in ("effective", "subject", "fees", "apy =", "apply", "see details")):
            continue
        return s
    return ""


class RateKnowledge:
    def __init__(self) -> None:
        self.rows: list[RateRow] = []

    def ingest(self, doc: Document) -> None:
        path = urlsplit(doc.url).path.lower()
        calculator = "calculator" in path or "calculator" in doc.title.lower()
        lines = doc.markdown.splitlines(keepends=True)
        i = 0
        while i < len(lines):
            if not lines[i].lstrip().startswith("|"):
                i += 1
                continue
            start = i
            table = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                table.append(lines[i])
                i += 1
            if len(table) < 3:
                continue
            headers = [clean(c) for c in table[0].strip().strip("|").split("|")]
            metrics = [(n, _metric(h)) for n, h in enumerate(headers)]
            metrics = [(n, m) for n, m in metrics if m]
            if not metrics:
                continue
            context = _context(lines, start) or doc.title.split("|")[0]
            quote = "".join(table).rstrip("\r\n")
            tail = "".join(lines[i:i + 12]).split("\n|", 1)[0]
            effective = EFFECTIVE.search(clean(tail))
            if effective is None:
                effective = EFFECTIVE.search(clean("".join(lines[max(0, start - 6):start])))
            effective_on = parse_date(effective[1]) if effective else None
            expire = EXPIRES.search(clean(tail))
            expires_on = parse_date(expire[1]) if expire else None
            authority = 0 if calculator else 1 if any(x in path for x in ("/learn/", "/newsroom/", "-lp", "guidance", "mortgage-refi")) else 2
            conditions = []
            if any("as low as" in normalize(h) for h in headers):
                conditions.append("as low as")
            if "subject to approval" in normalize(tail):
                conditions.append("subject to approval")
            earning = re.search(r"To earn dividends[^.]+\.", clean(tail), re.I)
            if earning:
                conditions.append(earning[0])
            if conditions and ("subject to approval" in conditions or earning):
                quote = ("".join(table) + tail).rstrip("\r\n")
            for raw in table[2:]:
                cells = [clean(c) for c in raw.strip().strip("|").split("|")]
                if len(cells) != len(headers):
                    continue
                values = []
                for n, metric in metrics:
                    found = PERCENT.findall(cells[n])
                    if found:
                        # Converted pages occasionally have deposit column
                        # headings pasted over a loan table. An explicit APR
                        # or APY unit on the value is stronger than that label.
                        unit = re.search(r"\b(APR|APY)\b", cells[n], re.I)
                        if unit:
                            metric = unit[1].upper()
                        values.append((metric, " - ".join(x.replace(" ", "") for x in found)))
                if not values:
                    continue
                label = cells[0]
                if normalize(headers[0]) in ("term", "balance", "balance tier", "loan amount", "loan type", "card type"):
                    if normalize(label) in ("standard", "variable interest rate"):
                        label = context
                elif "visa" in normalize(headers[0]):
                    context = headers[0]
                    label = context
                ident = _identity(label, context, headers, cells, doc)
                if ident["category"] == "deposit" and "checking" in ident["product"] and not ident["product"].endswith("checking"):
                    # A slogan is not enough to name a balance-only table.
                    # Retain the raw document, but do not invent an entity.
                    continue
                if ident["category"] == "deposit" and not any(x in ident["product"] for x in ("saving", "checking", "market", "investor", "achieve", "hsa")):
                    continue
                if ident["category"] == "auto" and not ident["model_years"]:
                    continue
                minimum_headers = [(n, normalize(h)) for n, h in enumerate(headers)
                                   if re.search(r"\bmin\.?|minimum", normalize(h))]
                minimum = next((cells[n] for n, h in minimum_headers if "open" in h or "deposit" in h), "")
                if not minimum:
                    minimum = next((cells[n] for n, h in minimum_headers if "earn" in h), "")
                self.rows.append(RateRow(**ident, metrics=tuple(values), minimum=minimum,
                                         effective_on=effective_on, expires_on=expires_on,
                                         authority=authority, doc=doc, quote=quote, conditions=tuple(conditions)))
        # Short labelled prose is also a legitimate financial disclosure. Avoid
        # extracting the numerous illustrative loan/calculator examples.
        for line_number, raw in enumerate(doc.markdown.splitlines()):
            if len(raw) > 500 or raw.lstrip().startswith("|"):
                continue
            s = clean(raw)
            if len(s) > 240:
                continue
            match = re.search(r"(.+?)\s+(APY|APR)\s*:?\s*(\d+(?:\.\d+)?%)", s, re.I)
            if not match:
                continue
            if any(x in normalize(s) for x in ("example", "if you borrow", "illustrat")):
                continue
            label = match[1]
            context = _context(lines, line_number) or doc.title
            if not any(word in normalize(label + " " + context) for word in ("certificate", "savings", "loan", "visa")):
                continue
            ident = _identity(label, context, ["Product", match[2]], [label, match[3]], doc)
            expire = EXPIRES.search(s)
            effective = EFFECTIVE.search(s)
            if effective is None:
                preceding = clean("".join(lines[max(0, line_number - 4):line_number]))
                effective = EFFECTIVE.search(preceding)
            self.rows.append(RateRow(**ident, metrics=((match[2].upper(), match[3]),), minimum="",
                                     effective_on=parse_date(effective[1]) if effective else None,
                                     expires_on=parse_date(expire[1]) if expire else None,
                                     authority=0 if calculator else 1 if "promo" in normalize(doc.title + doc.url) else 2,
                                     doc=doc, quote=raw))

    @staticmethod
    def _rank(row: RateRow) -> tuple:
        return (row.authority, row.effective_on or "0000-00-00")

    @staticmethod
    def _source_specificity(row: RateRow) -> int:
        path = urlsplit(row.doc.url).path.lower()
        if row.category == "mortgage":
            return 3 if re.search(r"/home-loans/?$", path) else 0
        if row.category == "auto":
            return sum(word in path for word in ("auto", "motorcycle"))
        if row.category == "card":
            return 2 if "credit-cards" in path else 0
        if row.category == "certificate":
            return 2 if ("retirement" in path if "ira" in row.product else "savings-account" in path) else 0
        return sum(word in path for word in tokens(row.product) - {"business", "loan"})

    def _eligible(self, cutoff: str) -> list[RateRow]:
        # Keep the last observed version of each fact per URL. Missing rows do
        # not establish cancellation, so they retain their original provenance.
        by_source = {}
        for row in self.rows:
            if row.doc.taken_on > cutoff or (row.effective_on and row.effective_on > cutoff):
                continue
            if row.expires_on and row.expires_on < cutoff:
                continue
            for metric, value in row.metrics:
                fact = replace(row, metrics=((metric, value),))
                key = (row.doc.url, row.key, metric)
                old = by_source.get(key)
                if old is None or row.doc.taken_on > old[0]:
                    by_source[key] = (row.doc.taken_on, [fact])
                elif row.doc.taken_on == old[0] and _value_key(value) not in {_value_key(r.metrics[0][1]) for r in old[1]}:
                    # Keep ties only within this latest observed version;
                    # an explicit later correction replaces the whole tie.
                    old[1].append(fact)
        return [fact for _, facts in by_source.values() for fact in facts]

    def _select(self, rows: list[RateRow]) -> tuple[list[RateRow], bool]:
        groups = {}
        for row in rows:
            for metric, value in row.metrics:
                groups.setdefault((row.key, metric), []).append(replace(row, metrics=((metric, value),)))
        winners = []
        unresolved = False
        for group in groups.values():
            rank = max(self._rank(r) for r in group)
            if rank[0] == 0:
                # Calculator inputs/examples are useful contradiction
                # evidence, but cannot establish an operative rate alone.
                continue
            best = [r for r in group if self._rank(r) == rank]
            metric_values = {}
            for row in best:
                for metric, value in row.metrics:
                    metric_values.setdefault(metric, set()).add(_value_key(value))
            if any(len(values) > 1 for values in metric_values.values()):
                unresolved = True
                continue
            # Stable citation choice among identical copies; primary product
            # pages are more useful to members than aggregate tables.
            best.sort(key=lambda r: (-self._source_specificity(r), urlsplit(r.doc.url).path.rstrip("/") in ("/rates", "/business-rates"), r.doc.url))
            winners.append(best[0])
        merged = {}
        for row in winners:
            source_key = (row.key, row.doc.url, row.doc.snapshot_id, row.quote)
            if source_key in merged:
                merged[source_key] = replace(row, metrics=merged[source_key].metrics + row.metrics)
            else:
                merged[source_key] = row
        return list(merged.values()), unresolved

    def _match(self, question: str, cutoff: str) -> tuple[list[RateRow], bool]:
        q = normalize(question)
        rows = self._eligible(cutoff)
        # An unfamiliar named product must not fall back to a generic rate.
        # Qualifier words are interpreted only when grounded in the corpus or
        # ordinary financial grammar; a made-up name remains unsupported.
        known = set()
        for row in rows:
            known.update(tokens(row.product + " " + row.label + " " + row.doc.title))
        ordinary = {"on", "for", "the", "a", "an", "your", "my", "our", "any", "all", "standard", "regular",
                    "fixed", "jumbo", "special", "business", "personal", "ira", "roth", "traditional", "current",
                    "highest", "month", "months", "year", "years", "cd", "term", "share", "does", "is", "of"}
        for match in re.finditer(r"\b([a-z][a-z'-]*)\s+(?:(?:\d+[- ]month|fixed|jumbo|special)\s+)*(checking|savings|certificate|visa)\b", q):
            descriptor = match[1].removesuffix("'s")
            if descriptor not in known and descriptor not in ordinary:
                return [], False
        category = None
        if any(x in q for x in ("certificate", "\bcd\b")) or re.search(r"\bcds?\b", q):
            category = "certificate"
        elif any(x in q for x in ("credit card", "visa")):
            category = "card"
        elif any(x in q for x in ("mortgage", "home loan", "construction loan", "7/1", "arm ", "adjustable")):
            category = "mortgage"
        elif any(x in q for x in ("auto loan", "car loan", "vehicle", "motorcycle")):
            category = "auto"
        elif "personal loan" in q or "unsecured loan" in q:
            category = "personal"
        elif "heloc" in q or "home equity line" in q:
            category = "heloc"
        elif "home equity" in q:
            category = "home equity"
        elif "home improvement" in q:
            category = "home improvement"
        elif any(x in q for x in ("boat", "rv loan", "atv", "snowmobile", "jet ski")):
            category = "recreational"
        if category:
            rows = [r for r in rows if r.category == category]
        else:
            rows = [r for r in rows if r.category == "deposit"]
            # Entity names are discovered from data, with a few ordinary
            # financial naming variants rather than institution-specific IDs.
            products = {r.product for r in rows}
            aliases = {p: {p, p.replace("1st", "first"), p.replace("you name it", "you-name-it"),
                           p.replace("investor's", "investors"), p.replace("-", " "),
                           p.removesuffix(" money market")} for p in products}
            matched = [p for p, names in aliases.items() if any(name and re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", _name(q)) for name in names)]
            if not matched:
                generic = {"savings", "checking", "business", "money", "market", "account", "accounts"}
                matched = [p for p in products if (tokens(p) - generic) and (tokens(p) - generic) <= tokens(q)]
            if not matched and "checking" in q:
                matched = [p for p in products if "checking" in p]
            elif not matched and "savings" in q:
                matched = [p for p in products if p == "share savings"]
            rows = [r for r in rows if r.product in matched]
        business = "business" in q
        if category != "card" or business or any(x in q for x in ("personal", "platinum", "rewards")):
            rows = [r for r in rows if r.business == business]
        if category == "certificate":
            ira = "ira" in q or "roth" in q or "traditional" in q
            rows = [r for r in rows if (r.product != "certificate") == ira]
            for tag in ("roth", "traditional"):
                if tag in q:
                    rows = [r for r in rows if tag in r.product]
            if "jumbo" in q:
                rows = [r for r in rows if r.jumbo]
            elif "regular" in q or "standard" in q:
                rows = [r for r in rows if not r.jumbo]
            if "special" in q:
                rows = [r for r in rows if r.special]
            # An old promotion's disappearance does not establish that it
            # ended. Its present applicability is unknown, so current catalog
            # answers use the most recently observed special table. Requests
            # for the omitted term abstain; historical evidence is untouched.
            specials = [r for r in self._eligible(cutoff) if r.category == "certificate" and r.special
                        and r.product in {x.product for x in rows}]
            if specials:
                latest_special = max(r.doc.taken_on for r in specials)
                rows = [r for r in rows if not r.special or r.doc.taken_on == latest_special]
        if category == "card":
            for tag in ("platinum", "rewards"):
                if tag in q:
                    rows = [r for r in rows if tag in r.product]
            intro = "intro" in q or "balance transfer" in q
            rows = [r for r in rows if r.special == intro]
        if category == "mortgage":
            if any(x in q for x in ("construction", "adjustable", "arm", "7/1", "5/1")):
                rows = []
            elif "refinanc" in q:
                rows = [r for r in rows if r.purpose == "refinance"]
            else:
                rows = [r for r in rows if r.purpose == "purchase"]
            for subtype in ("fha", "va", "usda", "jumbo", "conventional", "fixed", "balloon"):
                if re.search(r"\b" + subtype + r"\b", q):
                    rows = [r for r in rows if re.search(r"\b" + subtype + r"\b", normalize(r.label))]
        term = _term(q)
        if term is not None:
            rows = [r for r in rows if r.term == term]
        years = re.findall(r"\b(?:19|20)\d{2}\b", q)
        if category == "auto" and years:
            year = int(years[0])
            def includes(row: RateRow) -> bool:
                found = re.search(r"((?:19|20)\d{2})(?:\s*-\s*(\d{2,4}))?", row.model_years)
                if not found:
                    return False
                lo = int(found[1]); hi = int(found[2]) if found[2] else lo
                if hi < 100:
                    hi += lo // 100 * 100
                return year <= lo if "older" in row.model_years else min(lo, hi) <= year <= max(lo, hi)
            rows = [r for r in rows if includes(r)]
        if category == "auto" and rows:
            # A model-year generation can change the interval boundaries.
            # Once the query's year is known, overlapping old ranges must not
            # supply additional stale rates for the same repayment term.
            latest_for_term = {}
            for row in rows:
                key = (row.product, row.term, row.business)
                latest_for_term[key] = max(latest_for_term.get(key, (0, "")), self._rank(row))
            rows = [r for r in rows if self._rank(r) == latest_for_term[(r.product, r.term, r.business)]]
        amounts = _money(q)
        if amounts:
            amount = amounts[0]
            if category == "mortgage":
                ceilings = [r for r in rows if r.balance and Decimal(r.balance) >= amount]
                if ceilings:
                    ceiling = min(Decimal(r.balance) for r in ceilings)
                    rows = [r for r in ceilings if Decimal(r.balance) == ceiling]
                else:
                    rows = []
            else:
                def balance_match(row: RateRow) -> bool:
                    if category == "certificate" and row.minimum:
                        minimum = _money(row.minimum)
                        if minimum and amount < minimum[0]:
                            return False
                    ns = _numbers(row.balance)
                    if not ns:
                        return True
                    if re.search(r"\+|and up|or more|and above", normalize(row.balance)):
                        return amount >= ns[0]
                    return ns[0] <= amount <= ns[-1]
                rows = [r for r in rows if balance_match(r)]
        desired = "APR" if "apr" in q else "dividend" if "dividend" in q else "APY" if "apy" in q or category == "certificate" else None
        if desired:
            rows = [replace(r, metrics=tuple((m, v) for m, v in r.metrics if m.startswith(desired))) for r in rows]
            rows = [r for r in rows if r.metrics]
        selected, unresolved = self._select(rows)
        if any(x in q for x in ("highest", "maximum", "top out")) and selected:
            vals = [Decimal(PERCENT.search(dict(r.metrics).get("APY", "0%"))[0][:-1]) for r in selected]
            selected = [r for r, value in zip(selected, vals) if value == max(vals)]
        return selected, unresolved

    def answer(self, question: str, cutoff: str) -> Optional[Answer]:
        q = normalize(question)
        if not re.search(r"\b(?:rates?|apys?|aprs?|yield|interest|dividend)\b", q):
            return None
        if any(x in q for x in ("url", "link", "website", "where can i see")):
            return None
        rows, unresolved = self._match(question, cutoff)
        if unresolved:
            return abstain("Equally applicable financial disclosures disagree.")
        if not rows:
            return abstain("No applicable published rate is established by the supplied snapshots.")
        parts = []
        sources = []
        seen = set()
        rows.sort(key=lambda r: (r.business, r.product, not r.special, r.term or 0, r.jumbo,
                                 _numbers(r.balance)[0] if _numbers(r.balance) else Decimal(0)))
        for row in rows:
            metrics = list(row.metrics)
            if "apr" in q:
                metrics = [(m, v) for m, v in metrics if m.startswith("APR")]
            elif "dividend" in q:
                metrics = [(m, v) for m, v in metrics if m.startswith("dividend")]
            elif "apy" in q or row.category == "certificate":
                metrics = [(m, v) for m, v in metrics if m.startswith("APY")]
            elif row.category == "mortgage":
                metrics = [(m, v) for m, v in metrics if m in ("rate", "APR")]
            if not metrics:
                continue
            label = row.product.title()
            if row.category == "certificate":
                label = f"{row.term}-month " if row.term else ""
                label += row.product.title() + (" Special" if row.special else "") + (" Jumbo" if row.jumbo else "")
            elif row.category in ("auto", "personal", "home equity", "home improvement", "recreational"):
                label += (f", {row.term} months" if row.term else "")
            elif row.category == "mortgage":
                label = f"{(row.term or 0) // 12}-year {row.purpose} mortgage"
            if row.balance:
                balance = "$" + format(Decimal(row.balance), ",") + " or less" if row.category == "mortgage" else row.balance
                label += ", " + balance
            if row.model_years:
                label += ", " + row.model_years
            valtext = "; ".join(value + " " + metric for metric, value in metrics)
            if row.minimum and row.category == "certificate":
                valtext += "; minimum " + row.minimum
            if row.conditions:
                valtext += " (" + "; ".join(condition.rstrip(".") for condition in row.conditions) + ")"
            parts.append(label + ": " + valtext + ".")
            source = row.source()
            key = (source.url, source.snapshot_id, source.quote)
            if key not in seen:
                sources.append(source)
                seen.add(key)
        if not parts:
            return abstain("The requested rate measure is not published for that product.")
        keys = {r.key for r in rows}
        historical_values = {}
        for row in self.rows:
            if row.key in keys and row.doc.taken_on <= cutoff:
                for metric, value in row.metrics:
                    historical_values.setdefault((row.key, metric), set()).add(value)
        note = ("Other observed values were superseded by the applicable disclosure table and effective date."
                if any(len(v) > 1 for v in historical_values.values()) else None)
        return Answer(" ".join(parts), sources, conflict_note=note)

    def conflicts(self) -> list[Conflict]:
        grouped = {}
        for row in self.rows:
            for metric, value in row.metrics:
                grouped.setdefault((row.key, metric), []).append((row, value))
        cutoff = max((r.doc.taken_on for r in self.rows), default="0000-00-00")
        result = []
        current, unresolved = self._select(self._eligible(cutoff))
        current_by_key = {(r.key, metric): (r, value) for r in current for metric, value in r.metrics}
        for (key, metric), facts in sorted(grouped.items(), key=lambda item: str(item[0])):
            canonical_values = {}
            for row, value in sorted(facts, key=lambda item: item[0].doc.taken_on):
                canonical_values[_value_key(value)] = value
            values = sorted(canonical_values.values())
            if len(values) < 2:
                continue
            selected = current_by_key.get((key, metric))
            winner = selected[0] if selected else None
            resolution = selected[1] if selected else None
            sources = []
            for value in values:
                row = max((r for r, v in facts if _value_key(v) == _value_key(value)), key=lambda r: (r.doc.taken_on, r.doc.url))
                sources.append(row.source())
            row = facts[-1][0]
            label = row.product + (f" {row.term}-month" if row.term else "")
            label += (" jumbo" if row.jumbo else "") + (" special" if row.special else "")
            label += (" " + row.balance if row.balance else "") + (" " + row.model_years if row.model_years else "")
            result.append(Conflict(label + " " + metric, values, sources, resolution,
                                   "Compared the same product, term and tier; current applicable disclosure tables take precedence over marketing, then the latest explicit effective date. Historical changes are retained."
                                   if winner else "Applicable disclosures disagree without a defensible winner."))
        # Model-year bands can be redrawn between captures. Compare only the
        # concrete intersection, so e.g. different vehicle years never become
        # a false conflict merely because they have different APRs.
        by_year = {}
        for row in self.rows:
            if row.category != "auto":
                continue
            match = re.search(r"((?:19|20)\d{2})\s*-\s*(\d{2,4})", row.model_years)
            if not match:
                continue
            low, high = int(match[1]), int(match[2])
            if high < 100:
                high += low // 100 * 100
            if abs(high - low) > 20:
                continue
            for year in range(min(low, high), max(low, high) + 1):
                for metric, value in row.metrics:
                    by_year.setdefault((row.term, year, row.business, metric), []).append((row, value))
        for (term, year, business, metric), facts in sorted(by_year.items(), key=lambda item: str(item[0])):
            if len({row.model_years for row, _ in facts}) < 2:
                continue
            canonical = {}
            for row, value in sorted(facts, key=lambda item: item[0].doc.taken_on):
                canonical[_value_key(value)] = value
            if len(canonical) < 2:
                continue
            values = list(canonical.values())
            current_rows, uncertain = self._match(f"{'business ' if business else ''}auto loan {term} months {year} vehicle {metric}", cutoff)
            current_values = {v for row in current_rows for m, v in row.metrics if m == metric}
            resolution = next(iter(current_values)) if len(current_values) == 1 and not uncertain else None
            sources = []
            for value in values:
                matching = [row for row, v in facts if _value_key(v) == _value_key(value)]
                representative = max(matching, key=lambda row: (row.authority, row.doc.taken_on, self._source_specificity(row), row.doc.url))
                sources.append(representative.source())
                calculator_claims = [row for row in matching if row.authority == 0 and row.doc.url != representative.doc.url]
                if calculator_claims:
                    sources.append(max(calculator_claims, key=lambda row: (row.doc.taken_on, row.doc.url)).source())
            result.append(Conflict(f"Auto loan {term}-month model year {year} {metric}", values, sources,
                                   resolution, "The model-year bands overlap for this vehicle year; operative tables and their effective dates resolve the competing rates."))
        return result

    def changes(self, question: str, start: str, end: str) -> Optional[Answer]:
        old, old_uncertain = self._match(question, start)
        new, new_uncertain = self._match(question, end)
        if not old or not new or old_uncertain or new_uncertain:
            return abstain("Both requested periods need unambiguous financial evidence.")
        old_map = {r.key: r for r in old}
        parts, sources = [], []
        for row in new:
            prior = old_map.get(row.key)
            if prior is None:
                continue
            for metric, value in row.metrics:
                before = dict(prior.metrics).get(metric)
                if before and _value_key(before) != _value_key(value):
                    parts.append(f"{row.label} {metric}: {before} as of {start}; {value} as of {end}.")
                    sources.extend((prior.source(), row.source()))
        if not parts:
            return Answer("No changed value is established for the same product and qualifiers in the two periods.",
                          [old[0].source(), new[0].source()])
        return Answer(" ".join(parts), sources)
