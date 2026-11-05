# Verified evaluation

Measured locally on November 5, 2026. No external model judge, API, or live
website was used. The organizer's scorer and reference files were unchanged.
Raw outputs remain in the ignored local `results/` directory because they
contain source text. No hidden evaluation set or real-data conflict gold was
available.

## Official practice evaluation

```bash
python3 harness/run_eval.py --submission . \
  --eval eval/public_eval.jsonl --out results/final
```

| Metric reported by scorer | Result |
|---|---:|
| Questions | 40 |
| Weighted QA score | 0.9306 |
| Final score | 0.9306 |
| Stale-value trap hits | 0 |
| Runtime errors | 0 |
| Consistency score | 1.0 |
| Repeat checks | 20 |
| Paraphrase groups | 20 |
| Speed score | 1.0 |
| Query p50 / p95 / maximum | 0.03 / 0.05 / 0.06 seconds |
| Ingestion | 12.0 seconds |
| Ingestion over limit | False |

The public run does not measure the conflict pillar. The scorer renormalizes
the remaining weights, and multiplies consistency/speed by accuracy. Most
public paraphrase groups have one member, so this consistency figure is weaker
evidence than a broad paraphrase benchmark. Original synthetic paraphrase tests
provide additional coverage.

| Category | Questions | Mean item score |
|---|---:|---:|
| Branch information | 6 | 0.95 |
| Conflict resolution questions | 3 | 1.00 |
| Current values | 3 | 1.00 |
| Entity attribution | 4 | 0.9625 |
| List completeness | 4 | 0.75 |
| Required refusal | 3 | 1.00 |
| Stale traps | 7 | 0.9786 |
| Historical as-of | 4 | 0.75 |
| Tier disambiguation | 6 | 1.00 |

Counting the generated per-question records: 34 full-credit answers, four
partial-credit answers, two zero-credit items, and four abstentions. Every
confident answer has a verified source excerpt. These are counts derived from
the actual output, not additional scorer metrics.

The supplied starter baseline scored **0.0930**, with zero runtime errors.

## All remaining deductions

| Public case | Outcome and cause | Decision |
|---|---|---|
| `dup-054` | Correct routing value, but the scorer expects a different source URL than the operational contact page cited | Retain the source that supports the answer; URL-only matching undercredits this citation |
| `dup-064`, `dup-066` | Correct supported schedules cited to branch-specific announcements, outside the scorer's expected URL list | Label these published branch examples, preserve branch variation, and avoid claiming live hours |
| `dup-008` | Correct rate destination extracted from a different supporting page than the expected citation URL | Cite the page containing the actual link rather than fabricating a citation to the destination |
| `dup-005` | Complete certificate listing receives zero: `must_include` is empty, so the deterministic scorer assigns zero correctness | Preserve the scorer; the no-judge maximum is 62.5/64.5 = 0.9690 even with otherwise perfect answers |
| `dup-088` | “Last year” relative to the latest 2026 snapshot requires a 2025 VTO-usage count; the reference instead targets a 2023 report | Abstain: workforce totals and total volunteer hours do not establish the requested count |

The first four cases have correctness 1.0 and item score 0.85 because source
credit is missing. The two zero-credit items have the causes above. We did not
change reference answers, hardcode case IDs into runtime code, or substitute
older facts to improve the score.

Additional reference prose is not uniformly reliable: its general mortgage
description mentions a shorter-term rate inconsistent with the latest supplied
table. The implementation follows the source table. That discrepancy does not
affect the required numeric target for that public item.

## Organizer's synthetic selftest

```bash
python3 harness/run_eval.py --submission . \
  --snapshots harness/selftest/snapshots \
  --eval harness/selftest/eval.jsonl \
  --conflicts-gold harness/selftest/conflicts_gold.json \
  --out results/selftest
```

All five questions scored full credit. QA, final score, consistency, and speed
were **1.0**. One submitted conflict matched the one gold conflict, with
precision, recall, F1, and resolution accuracy all **1.0**. This is a small
synthetic contract check, not measured real-data conflict recall.

## Original tests and local compatibility

**86 original tests pass**, using synthetic institutions, dates, amounts, and
source text. They do not import the private harness or embed its reference
answers. Coverage includes:

- Observation cutoffs, increases/decreases, future effective dates, expired
  promotions, omitted pages and metrics, corrections, and date comparisons.
- Same-authority unresolved rate/fee contradictions, calculator evidence,
  numeric equivalence, and provenance on conflict resolutions.
- Product names, personal/business and IRA scope, mortgage subtypes, APR/APY,
  term and balance tiers, vehicle years, and certificate deposit minimums.
- Routing attribution, unknown branches/cards, membership geography, complete
  wallet lists, reporting-year refusal, recommendation filtering, and FAQ retention.
- Fee effective dates, future replacements, customer scope, and waivers.
- Loader paths, escaping ZIP/manifest paths and symlinks, malformed ingestion,
  exact citation excerpts, deterministic repeats, and standalone operation.

The suite ran successfully on local **Python 3.9.6, 3.12.14, and 3.14.7**.
Python 3.11 was not installed locally; CI is configured for 3.9, 3.11, and 3.13,
but no remote CI run is claimed. Syntax/bytecode compilation and source import
review also passed.

## Local performance benchmark

```bash
python3 scripts/benchmark.py --snapshots snapshots_zip \
  --questions eval/public_eval.jsonl --repeat 3
```

Python 3.14.7, five snapshots, 3,294 page observations, 120 query calls:

| Measurement | Result |
|---|---:|
| ZIP loading | 0.0827 seconds |
| Ingestion | 12.2464 seconds |
| Median / p95 query | 30.382 / 48.993 milliseconds |
| Maximum query | 99.610 milliseconds |
| Process peak resident memory | 366.34 MiB |
| External API calls | 0 |

These unrounded timings are a separate local benchmark, not additional official
scorer metrics. The memory figure includes all historical documents, passages,
token sets, indexes, and loaded snapshots. Sharing vocabulary strings reduced
peak memory from an observed 511.69 MiB without changing token equality.
Retaining every passage is convenient at this scale but has a real memory cost;
a larger deployment should persist documents and index eligible versions
incrementally. Performance depends on the host and workload.

## Limits and residual risks

The deterministic parsers have bounded language and layout coverage. Financial
extraction focuses on labeled tables and short labeled disclosures. Complex
prose may be missed. Fee equivalence requires matching normalized labels and
customer scope; paraphrased duplicates and mixed per-section effective dates
inside one document remain limited. Prose uses latest-document versions rather
than complete claim-level bitemporal modeling. Unfamiliar ambiguity should cause
refusal, but this finite test suite cannot prove correct applicability for every
possible question. Conflict enumeration is not exhaustive for arbitrary prose,
and real-data precision/recall are unknown.
