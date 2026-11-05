# Technical briefing

**End to end.** The harness passes dated snapshots. We retain their documents,
parse financial rows with their headings and columns, and index prose evidence.
A query establishes a historical cutoff, identifies its product and attribute,
selects applicable evidence, and emits a concise answer with original sources.

**What “true now” means.** It means the latest supplied website state. First
exclude documents not observed by the cutoff. Then consider explicit effective
dates, article publication dates, product scope, and expired offers. A crawl
timestamp does not make an old press release current. Missing a row in a later
pull does not, by itself, discontinue it.

**Conflicts.** Compare the same product, term, tier, and metric. APY and dividend
rate are different attributes. A current operative rate table beats a stale
calculator, as the assignment explicitly requires. We use effective dates to
resolve applicable updates; tied contradictory sources can force refusal.
The conflict report includes historical changes, evidence, and the reason for
each supported resolution. Prose conflict coverage is limited.

**Citations.** Values come from source rows or excerpts. URLs and snapshot IDs
come from ingestion. Before returning an answer, the coordinator confirms that
every quoted excerpt exists in that exact observed document. This prevents
fabricated provenance; tests still need to check that the quote entails the
answer, because substring validity alone is insufficient.

**Refusal.** We decline when the product or period is unsupported, the requested
attribute is absent, or equally applicable evidence remains contradictory.
We do not substitute another product's rate or extrapolate beyond the dataset.

**Why this architecture.** The financial tables have reusable structure. A local
deterministic approach makes qualifiers and temporal choices inspectable,
requires no secrets, and avoids sending assignment data to a model service.
The trade-off is lower recall for unfamiliar wording or layouts. Embeddings
could help retrieval; they would not replace temporal and conflict policies.

**Evaluation.** Explain the unchanged official practice result alongside the
synthetic policy tests and selftest conflict score. Distinguish measured repeat
consistency from general semantic consistency, and public performance from
unknown hidden-test performance. See `docs/evaluation.md` for actual results
and reference-answer discrepancies.

**Scaling.** Move immutable documents and qualified observations to a database,
use stable entity IDs and content hashes, add incremental ingestion, and build
separate sparse/semantic indexes over eligible evidence. Cache by query,
cutoff, and corpus revision. Preserve both observation and effective time.

**Banking deployment.** Replace inferred website authority with an approved
source registry and owner review. Add explicit validity periods, verified
supersession notices, access controls, audit records, data retention rules,
monitoring, adjudication workflows, and reviewed escalation paths. Evaluate
real member paraphrases and adversarial evidence before widening coverage.
The current submission makes no production-readiness claim.
