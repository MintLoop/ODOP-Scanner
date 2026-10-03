# Agent tracker

## 2026-10-03 — deterministic official-source reconciliation

Status: complete; all conflicts quarantined for review, with no automatic supersession.

- Added a versioned reconciliation manifest that pins the 2024 revised list, Lok Sabha Question 525,
  and the 2024–25 Annual Report by URL, date, SHA-256, expected row count, and annexure page range.
- Added deterministic district identity and product-text comparison. It normalizes presentation only;
  it does not merge semantic product families or treat wording changes as equivalent.
- Added content-derived comparison/diff IDs, source hashes, row IDs, PDF page/row locators, raw product
  values, proposed status, and human-review status to the reconciliation ledger.
- Added a pending review queue and append-only decisions (`keep_2024`, `accept_newer`, `mark_same`,
  `defer_ambiguous`). Decisions retain a supersession chain and never mutate the canonical source.
- Quarantined three annual-report layout rows as ambiguous: Aurangabad, Banka, and Papum Pare (Capital
  Complex). No inferred repair was applied.
- Reconciliation-source rows are isolated from normalization; after all three snapshots are stored,
  the candidate pipeline still consumes only the 726-row canonical 2024 source.

### Reproducible comparison result

| Newer source | Same | Changed | Added | Removed | Ambiguous | Conflicts |
|---|---:|---:|---:|---:|---:|---:|
| Lok Sabha Question 525 | 452 | 273 | 1 | 1 | 0 | 275 |
| Annual Report 2024–25 | 702 | 21 | 0 | 3 | 3 | 27 |
| **Total** | **1,154** | **294** | **1** | **4** | **3** | **302** |

The Lok Sabha added/removed pair is the literal `Tumkuru` / `Tumakuru` district-label difference. It
remains pending rather than being auto-aliased. Annual-report malformed rows generate explicit
ambiguous records while their unmatched 2024 districts remain visible as removed, so no evidence is
silently paired or discarded.

All six Bihar Makhana assignments—Araria, Darbhanga, Katihar, Madhubani, Saharsa, and Supaul—are
`same` in both newer sources: 12/12 comparisons unchanged, with source hashes and PDF locators stored.

Validation passes Ruff formatting/linting, strict mypy, and 25 pytest cases. Repeating the real
three-source run produced the same two comparison IDs and 1,456 stored row-level diffs without
duplicates.

## 2026-10-03 — official-source freshness review

Status: complete; 2024 revised PDF retained as an explicitly freshness-checked v0 source-of-record.

- Re-checked the live MoFPI ODOP page, GIS portal, parliamentary Q&A catalogs, annual-report catalog,
  and announcements archive.
- The live ODOP page still links only the 2024-03-13 revised 726-district PDF.
- Recorded and hashed the newer 2025-02-06 Lok Sabha Question 525 annexure. It reports 726 approved
  districts as of 2025-01-31 but does not state a unique-product count or declare supersession.
- Recorded and hashed the 2024–25 annual report published 2025-08-21. It reports 726 districts and 137
  unique products—both unchanged—but its annexure conflicts with revisions explicitly approved in the
  2024 memorandum.
- Did not scrape the GIS portal because no stable documented or appropriately inspectable export/API
  endpoint was verified.
- Added a machine-readable freshness manifest, DuckDB discovery records, a `freshness` CLI command,
  canonical SHA/row-count fail-closed guards, and parser coverage for multiple table layouts.
- Validation now passes Ruff, strict mypy, and 18 pytest cases.

## 2026-10-03 — deterministic vertical slice implemented

Status: implementation and validation complete; broad market enrichment intentionally not started.

### Delivered

- Added a Python 3.12–3.14 package, locked dependencies, DuckDB migration, and JSON CLI.
- Added official PDF layout ingestion plus text, CSV, and JSON fixture adapters.
- Preserved content-addressed source bytes, extracted document text, raw row text, source metadata,
  page/row references, original values, and ingestion timestamps.
- Added deterministic normalization with a versioned taxonomy, exact alias merges, fuzzy review flags,
  and a review-only optional model interface.
- Added product families that retain every state/district assignment and source provenance.
- Added versioned eleven-dimension scoring configuration, a pure scoring engine, negative regulatory
  handling, missing-value preservation, weighted evidence coverage, and confidence bands.
- Added processing-run receipts for timestamps, configuration, source set, optional model route, input
  identity, output reference, and success/failure.
- Added Makhana as forced `product-001` with approved foxnut aliases.
- Added tests and a runbook.

### Validation evidence

- Official MoFPI PDF SHA-256:
  `bd37a47206a44ff0c2357da566a3e2f8aed69c065c81eb3418c117186f803613`.
- Parsed all 726 official rows with zero malformed rows in the smoke run.
- Deterministic normalization produced 250 conservative families; 146 assignments across 26
  near-match families are `review_required` and remain separate unless approved in taxonomy.
- Product #001 retained six Bihar districts: Araria, Darbhanga, Katihar, Madhubani, Saharsa, Supaul.
- Makhana has no fabricated market metrics: score `null`, evidence coverage `0%`, confidence `none`.
- Ruff formatting/linting, strict mypy, and the then-current 15 pytest cases passed.

### Known boundary

The current source adapter uses the configured official PDF URL directly; discovery-page resolution,
source change alerts, reviewed semantic-family expansion, manual evidence import, and market evidence
providers are later slices. No market scraping or enrichment was added.

## 2026-10-03 — v0 architecture baseline

Status: documentation complete; bounded implementation recommended.

### Inspected

- The ODOP Scanner directory was empty and was not a Git repository.
- The MoFPI ODOP landing page, its current revised 2024-03-13 39-page PDF, the GIS portal, and the
  Ministry's 2024-25 annual report.
- The revised PDF's extraction shape, including wrapped rows and page/state boundary joins.
- Bihar's six district assignments for `Makhana (Foxnut)`.
- Hermes-Menta's canonical architecture, routing, agent profiles, project profiles, dogfood loop, run
  receipt, execution-profile records, and evidence policy.
- The desired and live agent-profile registries match by SHA-256; the desired and live Hermes config
  files do not, so observed route telemetry must outrank assumed configuration.
- The archived A30 provenance and A32 telemetry implementations, confirming their current code is not a
  supported project dependency.
- Fridgy's content-addressed ingestion, typed pipeline stages, ledger, idempotency, LLM provider seam,
  schema repair, and retry taxonomy.
- Menta Media's thin Hermes-plugin-to-project-CLI isolation pattern and local ADR convention.

### Decisions recorded

- DuckDB plus immutable files; Postgres only when concurrency is demonstrated.
- Revised official PDF as v0 source of record; GIS portal as secondary reconciliation only.
- District assignments and product families are separate entities.
- Deterministic scores are confidence-adjusted and config-versioned.
- Manual evidence import is the first enrichment adapter.
- Logical ODOP roles map to existing Menta profiles; no second general agent runtime.
- No frontend, API service, vector database, scheduler, autonomous external action, or major code in this
  phase.
- No ADR file yet because this project had no Git/repository convention; the architecture proposal is
  the provisional record.

### Files created

- `AGENT_BRIEF.md`
- `AGENT_TRACKER.md`
- `PHASE_WORKFLOW.md`
- `docs/architecture/ODOP_SCANNER_V0.md`

### Blocking unknowns before operational ranking

- compliant search, marketplace, social, and supplier sources and their costs;
- exact makhana product form and authoritative terminology;
- quotes, MOQ, landed cost, duties, fees, and shipping evidence;
- product-form-specific FDA/FSVP, USDA/APHIS, labeling, customs, and tariff treatment;
- calibrated feature transforms, weights, and BUILD/TEST/WATCH/KILL thresholds;
- verified supported Hermes structured-output/telemetry surface;
- any real flagship route quality/cost advantage.

### Next recommended action

Ben reviews the architecture boundary. If accepted: initialize Git, make the documentation baseline
commit, create `feat/odop-opportunity-scanner`, and implement Phase 1 followed by the makhana vertical
slice. The first card is allowed to conclude `TEST: evidence gaps`; filling gaps with fabricated numbers
is not an acceptance criterion.
