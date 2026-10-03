# Agent brief

## Mission

Build ODOP Scanner as an internal MintLoop product-intelligence pipeline. It turns official Indian
One District One Product source rows into reviewed product families, structured US-market evidence,
deterministic scores, independent challenges, and concise opportunity cards.

The primary question is: **which products deserve Ben's attention, and why?**

Makhana / foxnut from Bihar is Product #001 and must traverse every implemented stage. Its forced
inclusion never bypasses evidence or promotion gates.

## Current phase

The approved deterministic vertical slice is implemented on `feat/odop-opportunity-scanner`. It covers
official-source ingestion through candidate/report output, including the Makhana Product #001 dogfood
path. The canonical proposal remains
[`docs/architecture/ODOP_SCANNER_V0.md`](docs/architecture/ODOP_SCANNER_V0.md), and the gated delivery
sequence is in [`PHASE_WORKFLOW.md`](PHASE_WORKFLOW.md).

The next slice must remain bounded. Do not begin broad market enrichment or scraping until its source,
terms, evidence, and feature contracts are approved. Unknown metrics remain `null`; the current Makhana
result is intentionally unscored with zero evidence coverage.

## Non-negotiable rules

- Preserve original bytes, raw extracted rows, locators, hashes, retrieval time, and source date.
- Re-run and record official-source discovery before promoting a canonical snapshot. A source is never
  called current merely because it remains configured; unresolved newer-source conflicts are explicit.
- Keep district assignments separate from canonical product families.
- Python/SQL calculate every feature, confidence value, score, gate, and rank.
- Weights and thresholds live in validated configuration, never embedded in prompts or business logic.
- Missing evidence lowers coverage/confidence and can never be filled by model intuition.
- Agents may gather, classify, map, challenge, and summarize. They may not write scores.
- A producer is not its own validator. Validator profile and resolved model must both be independent.
- Preserve failed attempts and partial evidence; do not report silent success.
- Store evidence, decisions, critiques, and receipts, not private chain-of-thought.
- Ben alone authorizes purchases, outreach, importing, publication, deployment, or other external action.

## Operating posture

- Local-first, Python-heavy, DuckDB first.
- One process and one writer; no service or distributed queue in v0.
- CLI before API or UI.
- Manual evidence imports are preferable to unapproved scraping.
- Reuse Hermes/Menta profiles, route vocabulary, and attended durable-work practices.
- Do not import archived A30/A32 implementation or copy Fridgy's TypeScript runtime.
- No LangChain, CrewAI, vector database, autonomous purchasing, or premature frontend.

## Required agent contracts

- Scout: evidence candidates and source/query logs only.
- Market Analyst: typed evidence-to-feature mappings and explicit assumptions only.
- Validator: adversarial findings, affected evidence/features, and PASS/REJECT/UNKNOWN only.
- Synthesizer: an opportunity card copied from an immutable score snapshot with evidence IDs.

Any output containing an unauthorized score or unknown field fails schema validation.

## Definition of a valid Product #001 slice

1. An immutable official-source snapshot exists.
2. The Bihar rows are parsed with page/row provenance.
3. The six makhana district assignments map to one reviewed family without losing district identity.
4. Any numeric feature traces to accepted evidence and a versioned formula.
5. Missing evidence is visible and lowers confidence.
6. Validator findings cannot mutate the score; corrections cause a new score version.
7. A Markdown card is produced even if the honest recommendation is `TEST: evidence gaps`.

## Git

The active implementation branch is `feat/odop-opportunity-scanner`. Preserve unrelated work and do
not add generated DuckDB files, raw source documents, caches, or run artifacts to Git.
