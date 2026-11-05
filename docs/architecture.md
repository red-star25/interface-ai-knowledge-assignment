# Architecture decisions

## 1. Local structured evidence with extractive retrieval

The problem is selecting applicable evidence from conflicting website versions,
not generating fluent financial advice. We considered raw keyword retrieval,
BM25/hybrid retrieval with embeddings, an LLM-based RAG pipeline, and structured
fact extraction. The starter's paragraph overlap baseline demonstrates why
unqualified raw retrieval is insufficient. The corpus's financial rates are
Markdown tables with reusable schemas, so we chose deterministic row extraction
and evidence selection, with extractive retrieval for prose.

The required path stays local, reproducible, inexpensive, and easy to inspect.
An embedding index could improve paraphrase recall, but cannot decide whether a
rate is current or belongs to the right tier. The assignment allows an LLM for
language understanding, so the CLI also has an opt-in query interpreter. In
that mode it sends the user's question, but not the snapshot content, to the
Responses API and asks whether to rewrite, clarify, or use the original wording.
The model cannot produce facts or citations. The program rejects rewrites that
add or drop a recognized product family or key qualifier, or introduce a
recognized numeric dollar amount. These checks cover defined patterns, not all
possible semantic changes. Deterministic retrieval still selects dated
evidence, resolves conflicts, validates citations, and decides whether it
supports an answer. API errors fall back to deterministic lookup on the
original question, which can still misread unfamiliar wording. This may improve
paraphrase coverage while keeping the official `build()` contract
self-contained and API-free. The cost is optional credentials, API latency, account charges, and
remaining risk that a rewrite misunderstands intent. Ambiguous interpretations
should be declined. Neither parser handles every page layout, arbitrary
calculation, or unrestricted multi-hop question.

## 2. Observation time and claim time

Each document retains its original URL, title, raw Markdown, snapshot ID,
official snapshot date, and fetched timestamp. Filesystem modification times
are never consulted. Queries first restrict evidence to snapshots observed on
or before the requested date. Effective dates belong to claims; publication
dates belong to articles. A document observed later cannot retroactively leak
into a historical answer, even if it claims an earlier effective date.

We retain history in memory rather than overwriting it or adding a database.
The supplied corpus is small enough that an external store has little benefit.
Keeping claim qualifiers and evidence references is more valuable than a graph
database for this scale. Persistence would require content-hash versioning,
schema migrations, and careful protection of derived indexes.

Omission does not prove discontinuation. Financial rows and individual metrics
can retain their last observation when a later pull omits them; a missing fee
page can also carry forward. Citations keep their earlier snapshot. Prose uses
the latest observed version of each document, so omitted prose passages are
not automatically retained as active claims. Promotional certificate catalogs
need additional caution: only the latest observed catalog supplies current
specials. A special absent from it has unknown applicability; history remains
available, and absence is never reported as discontinuation. This matches the
organizer's fee carry-forward selftest without asserting indefinite validity
for unconfirmed promotions.
Explicit future effective dates are not active early; expired promotions are
not current rates. An explicit `as_of` outside the observed date range abstains.
Without `as_of`, “current” means the latest supplied snapshot, not today's live
website. Embedded ISO dates following “as of/as at” and historical named-month
requests are supported. Named months use month-end, which may fall beyond the
available data and cause refusal. Comparisons support two ISO dates or named
month/year periods, plus “since” a supported date. Arbitrary relative financial
periods and bare-year history requests are not parsed.

## 3. Qualified facts and conflict policy

Financial rows preserve product identity, account/loan family, term, tier,
amount, vehicle year range, and named columns. Dividend rate, APY, and APR are
distinct attributes. Introductory and standard pricing and personal/business
and IRA/non-IRA products must not be merged. Multiple tiers can be returned
with labels when the user has not supplied the qualifier.

The official assignment explicitly identifies current product rate pages as
authoritative over stale affordability calculators. This justifies prioritizing
operative tables over illustrative examples and archived marketing. Within an
applicable source class, explicit effective dates guide selection. More precisely:
enforce the observation cutoff and effective/expiry eligibility, keep the latest
observation per source and qualified metric, then compare source class and
explicit effective date. A newer crawl of a different URL alone does not break
a tie. Product URL specificity selects a useful citation among numerically
identical winners; it does not override a contradictory value. A later crawl
alone does not rejuvenate an old article. Equally
applicable conflicting evidence remains unresolved rather than using URL order
or the highest rate as a tie breaker.

`conflicts()` reports disagreements and observed changes for matching qualified
attributes, including sources and a resolution reason when one is supported.
Different terms, tiers, or rate columns are not contradictions. This automated
catalog is useful but not an exhaustive contradiction detector for arbitrary
prose; no real-data conflict gold was supplied publicly.

## 4. Grounded answers and abstention

Answer values originate in parsed rows or original prose. Domain intent rules
select an evidence family; they do not map practice questions to answer strings.
No runtime component reads the evaluation file. Source objects are built from
the observed URL and snapshot, with a verbatim excerpt. The coordinator checks
that each excerpt exists in that exact document and predates the cutoff.
Table evidence retains raw row/header context where possible. Exact substring
validation proves provenance, not semantic entailment; synthetic tests also
check that the selected excerpt contains the selected value and qualifiers.

Empty/invalid questions, unknown entities, unsupported attributes, unavailable
dates, and unresolved contradictions produce `confident=False` and “I don't
know.” Missing evidence never becomes a negative product claim. Relative
reporting periods are anchored to the snapshot date, not an old article's year.
Conservative refusal sacrifices recall to avoid presenting unsupported amounts
as current. Multi-step arithmetic and arbitrary cross-document inference are
not promised.

## 5. Contract and validation boundaries

The root entry point returns dataclass-shaped values matching the official
contract. The scorer explicitly supports these without requiring its own
module to be imported. The system can therefore run from a clean public clone
without redistributing the private kit. The CLI and benchmark use the same
engine. The local input loader reads manifests or ZIPs, checks paths, and never
extracts archives or uses live URLs.

Validation has three separate roles: original synthetic tests exercise policy,
the unchanged official scorer measures practice performance, and repository
auditing checks public data hygiene. The scorer's URL match is less strict than
our excerpt checks. Speed and repeat consistency do not establish correctness.
The optional external LLM judge is disabled. Query interpretation is also off
unless the CLI receives `--llm`; synthetic tests mock its API response. The
five supplied snapshot datasets are never sent by this integration.

## Requirement map

| Official requirement | Implementation | Verification |
|---|---|---|
| Exact three-method contract | `solution.py`, `knowledge/system.py`, `models.py` | Official scorer and standalone import |
| Dated sequential ingestion | `system.py`, `io.py` | Synthetic history, ordering, and input tests |
| Current and historical answers | Qualified row history and dated prose | Cutoff, future-effective, and omission tests |
| Correct product/tier/metric | Structured rate selectors | Term, balance, IRA, jumbo, card, APR/APY tests |
| Contradictions and resolutions | `rates.py` and `content.py` | Synthetic conflicts and organizer selftest |
| Grounded citations | `Document.source`, coordinator validation | Exact source/snapshot/excerpt tests |
| Honest refusal | `confident=False` policy | Unknown and conflicting evidence tests |
| Installation and runtime | Standard library, root entry point, CLI | Fresh-environment run and compile checks |
| Data protection | `.gitignore`, Git tree/history scanner | Local tracked-file/history audit |
