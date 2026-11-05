# Submission notes

The submission entry point is `solution.py` at the repository root. It implements
the organizer's `build()`, `ingest(snapshot)`, `answer(question, as_of=None)`, and
`conflicts()` interface without importing anything from the participant kit.
The required path uses Python's standard library and needs no API keys or
network access. An optional CLI mode (`--llm`) uses an OpenAI API key to
interpret question wording; it sends the question only, never snapshot content.
Install with `python -m pip install -r requirements.txt`.

The system retains observed document history and extracts qualified financial
table rows. A historical cutoff first restricts what had actually been observed;
explicit effective dates then determine which claims are eligible. Product,
term, balance, model year, personal/business scope, and APR/APY remain separate.
Product rate tables take precedence over illustrative calculators and dated
promotions. Equal applicable evidence that remains contradictory causes
abstention. Nonfinancial answers come from source excerpts with entity and
topic checks. Every cited excerpt is checked against the original document.

The private snapshots, original archives, assignment PDF, starter, scorer,
practice reference answers, and generated evaluation output are deliberately
excluded from Git. Reviewers supply their own authorized participant kit. See
README.md for the exact evaluation command and docs/architecture.md for the
policy, trade-offs, and limits. The latest official API-free practice score is
0.9329; 94 tests pass, and the public-tree audit passes. A few live `--llm`
spot-checks exercised paraphrase rewriting, clarification, refusal, and
historical lookup; they are not an aggregate accuracy measure. No external
candidate implementation was used.
