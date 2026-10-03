# ODOP Scanner v0 architecture

Status: approved baseline; deterministic vertical slice implemented

Date: 2026-10-03

Owner: MintLoop / Ben
Recommendation: **GO for the bounded deterministic spine; BLOCK promotion decisions until the named evidence-source decisions are made.**

## 1. Architecture

### Purpose and decision boundary

ODOP Scanner is a local-first research pipeline that answers one question: which Indian One District
One Product (ODOP) physical products deserve Ben's attention, and why?

It is not a store, purchasing system, supplier-outreach bot, or autonomous business decision-maker.
Python and SQL own identity, metrics, scores, gates, and ranks. Models may extract, classify, challenge,
and explain, but model prose never mutates a numerical score.

The v0 flow is:

```text
versioned source snapshot
  -> lossless source rows
  -> reviewed product-family mappings
  -> 20-25-family pilot cohort (makhana forced in)
  -> typed evidence observations
  -> deterministic features
  -> versioned, confidence-adjusted scores
  -> independent challenge
  -> BUILD / TEST / WATCH / KILL recommendation
  -> concise opportunity card
```

`BUILD` means "eligible for Ben to approve the next research, sampling, or validation step." It does
not authorize a purchase, import, product launch, supplier contact, or public claim.

### Runtime shape

- One Python process and one DuckDB file on one MacBook.
- SQL migrations and frozen typed dataclasses in the current internal slice; validate future external
  adapter contracts with Pydantic or JSON Schema. Use Parquet only where bulk snapshots are useful.
- Content-addressed files for source bytes, evidence payloads, agent inputs, and outputs.
- A CLI is the only v0 product surface. No API server or frontend.
- One writer at a time. DuckDB remains the analytical store until real concurrent-write or multi-user
  demand justifies Postgres.
- Hermes/Menta is the model-routing and attended-work environment; ODOP Scanner is the domain data and
  deterministic decision engine. It must not become a second general agent runtime.

The implemented vertical slice uses versioned TOML rather than YAML and keeps ingestion,
normalization, scoring, and storage as small modules until their interfaces justify package
subdirectories. It applies `overall_score = raw_score * evidence_coverage` while evidence-quality
inputs are absent. Evidence-quality weighting remains a later enrichment-stage extension and must not
be simulated with defaults.

### Proposed repository shape

```text
.
├── AGENT_BRIEF.md
├── AGENT_TRACKER.md
├── PHASE_WORKFLOW.md
├── pyproject.toml
├── config/
│   ├── sources.yaml                 # canonical URLs and expected source invariants
│   ├── taxonomy.yaml                # categories and approved aliases
│   ├── pilot.yaml                   # cohort size, forced inclusions, stratification
│   ├── scoring.v0.yaml              # weights, transforms, freshness, gates
│   └── routing.yaml                 # logical role -> Menta profile/service class
├── schemas/
│   ├── scout-output.schema.json
│   ├── analyst-output.schema.json
│   ├── validator-output.schema.json
│   └── opportunity-card.schema.json
├── sql/migrations/
│   └── 001_initial.sql
├── src/odop_scanner/
│   ├── cli.py
│   ├── db.py
│   ├── models.py
│   ├── ingest/{download.py,pdf.py,reconcile.py}
│   ├── normalize/{rules.py,aliases.py,review.py}
│   ├── enrich/{base.py,manual.py,cache.py}
│   ├── scoring/{features.py,engine.py,gates.py}
│   ├── agents/{contracts.py,runner.py,routing.py}
│   └── cards/{render.py,templates/opportunity.md.j2}
├── data/
│   ├── raw/                         # immutable, untracked source snapshots
│   ├── cache/                       # replaceable provider responses
│   ├── review/                      # versioned human corrections/mappings
│   └── odop.duckdb                  # local, untracked
├── artifacts/
│   ├── cards/
│   └── runs/
└── tests/
    ├── fixtures/
    ├── golden/
    ├── unit/
    ├── contract/
    └── integration/
```

Only documentation, configuration, schemas, SQL, source code, small legal fixtures, and reviewed
overrides belong in Git. Government PDFs, provider payloads, the database, caches, and model outputs do
not.

### Source inspection and ingestion decision

The current MoFPI landing page links a 39-page revised PDF dated 2024-03-13. Its text layer identifies
726 district rows in 35 States/UTs. The Bihar section lists `Makhana (Foxnut)` for Araria, Darbhanga,
Katihar, Madhubani, Saharsa, and Supaul. Page and table boundaries are not clean: wrapped district and
product names occur, and extraction can join a state's `TOTAL` with the next state heading. A later
MoFPI annual report says the 726 districts comprise 137 unique products; that is a reconciliation clue,
not a safe normalization oracle.

Primary sources inspected:

- [MoFPI ODOP landing page](https://www.mofpi.gov.in/en/pmfme/one-district-one-product)
- [Revised 35-State/UT list linked by that page](https://www.mofpi.gov.in/sites/default/files/revised_list_of_odop_for_35_states_13.03.2024_1.pdf)
- [MoFPI ODOP GIS portal](https://odop.mofpi.gov.in/odop/)
- [MoFPI 2024-25 annual report](https://www.mofpi.gov.in/sites/default/files/mofpi_annual_report_2024-25_english_21.08.2025.pdf)

No stable documented machine API was verified for the GIS portal. It is a reconciliation source only
until an endpoint, schema, terms, and change policy are verified. The revised PDF is the v0 source of
record.

A freshness re-check on 2026-10-03 found newer official reconciliation material but no unambiguous
superseding revision. Lok Sabha Question 525, answered 2025-02-06 with data as of 2025-01-31, contains
a complete 726-row annexure. The MoFPI 2024–25 annual report, published 2025-08-21, states 726 districts
and 137 unique products. Its annexure reverts assignments that the 2024 approval memorandum explicitly
revised, while the parliamentary annexure changes labels and some assignments without declaring
supersession. The still-linked 2024 revised PDF therefore remains the v0 source-of-record with status
`checked_not_assumed_current`; both newer documents are reconciliation sources. See
[`docs/source-freshness/2026-10-03.md`](../source-freshness/2026-10-03.md).

Ingestion is therefore a deterministic, reviewable pipeline:

1. Fetch the discovery page and resolve its current download link; do not hard-code only the old pasted
   PDF URL.
2. Save the exact response bytes under their SHA-256. Record requested URL, resolved URL, HTTP metadata,
   retrieval time, media type, source date, and content hash.
3. Extract the text layer with a pinned parser. OCR is a fallback only for pages without usable text and
   records engine, version, page, and bounding boxes.
4. Parse state sections and numbered rows with a state machine. Preserve raw text, page, row ordinal,
   and parser diagnostics before cleaning anything.
5. Reconcile state totals, sequence continuity, the declared 726-row total, and required Bihar makhana
   rows. Quarantine rather than guess on ambiguous row boundaries.
6. Apply reviewed corrections from a small append-only override file keyed by source hash and locator.
   A new PDF hash creates a new source version; it never overwrites the old extract.

### Identity, normalization, and duplicate consolidation

`odop_products` is one row per government district/product assignment. It must never be collapsed into
one row per product. A separate `product_families` table is the canonical analysis identity, and
`product_family_members` records every reviewed membership. This preserves the district evidence while
allowing six Bihar makhana rows to become one candidate family.

Normalization proceeds in increasing-risk order:

1. Unicode, whitespace, punctuation, and case normalization.
2. Deterministic removal of presentation-only phrases such as a consistently recognized `based
   products` suffix, while retaining the exact source value.
3. Exact match against a versioned alias dictionary.
4. Fuzzy/token similarity creates review candidates only; it never merges automatically.
5. A cheap local model may propose a family and category under a strict output schema, but the proposal
   has no authority. Ambiguous merges require review and an append-only decision.

Makhana, foxnut, and fox nut may be proposed as aliases. `Lotus seed` must not be accepted as an alias
without authoritative botanical/product evidence; the terms are often conflated in commerce.

Every family mapping records `normalization_version`, method, confidence class, reviewer, timestamp,
and any superseded mapping. Renaming a family does not delete its history.

### Core data model

The four requested tables remain, but provenance and family identity require supporting tables.

| Table | Purpose and essential fields |
|---|---|
| `source_snapshots` | `id`, requested/resolved URL, source/published date, retrieved time, media type, SHA-256, byte length, storage URI, HTTP metadata, parser version/status |
| `source_rows` | immutable extracted row: snapshot, page/locator, raw text, raw state/district/product, parse status, diagnostics, raw hash |
| `product_families` | stable family id, canonical name, category, lifecycle, normalization version |
| `product_aliases` | family id, alias, locale, evidence/review reference, valid-from/to |
| `odop_products` | requested fields plus `source_row_id`, `product_family_id`, `normalization_status/version`; one district assignment per row |
| `product_family_members` | explicit family-to-source-row mapping and append-only merge/split decision |
| `evidence_items` | evidence id, claim class, source snapshot/payload, canonical URL, locator/query, observation time, retrieval time, hash, collection method, verifier state |
| `market_signals` | requested fields plus typed numeric/text value, provider version, request hash, evidence id, freshness state, acceptance state |
| `feature_values` | product, feature key, raw inputs, normalized 0-100 value, formula/config hash, evidence ids, computed time |
| `opportunity_scores` | requested dimensions plus `raw_opportunity_score`, `confidence_score`, `last_verified_at`, evidence/config/cohort hashes; `overall_score` is the confidence-adjusted rank |
| `validator_findings` | product, score version, affected evidence/features, severity, status, evidence refs, recommended action |
| `agent_runs` | requested fields plus provider, resolved model, profile id, contract version, attempt, token counts, cost value/state, evidence/input/output hashes, error class |
| `decision_records` | score snapshot, validator verdict, BUILD/TEST/WATCH/KILL state, human decision and reason |

Aliases should be normalized rows rather than an opaque array. A JSON `aliases` projection may still be
exposed for the originally requested `odop_products` shape.

The compatibility-facing core fields are explicit:

```text
odop_products
  id, state, district, source_product_name, normalized_name, aliases, category,
  source_url, source_date, provenance_metadata,
  source_row_id, product_family_id, normalization_status, normalization_version

market_signals
  product_family_id, source, metric, value_decimal, value_text, unit, observed_at,
  confidence, evidence_url, evidence_id, provider_version, request_hash, acceptance_state

opportunity_scores
  product_family_id,
  demand_score, competition_gap_score, margin_score,
  social_velocity_score, search_velocity_score, supplier_score,
  shelf_stability_score, brandability_score, repeat_purchase_score, shipping_score,
  familiarity_score, regulatory_risk,
  raw_opportunity_score, evidence_coverage, confidence_score, overall_score,
  score_version, scoring_config_hash, evidence_cut_id, last_verified_at, scored_at

agent_runs
  run_id, product_family_id, agent, profile_id, provider, model, route,
  started_at, ended_at, duration_ms, attempt, token_input, token_output,
  cost_amount, cost_currency, cost_state,
  input_hash, output_artifact, output_hash, status, error_class, created_at
```

Signals and scores attach to a product family, not one district assignment. If an external consumer
requires the requested name `product_id`, a view aliases `product_family_id AS product_id`; the storage
schema does not overload district-row identity. `market_signals.confidence` is computed from evidence
metadata and configuration, never copied from a model's self-reported confidence.

### Evidence and provenance contract

Claim classes follow the existing Menta vocabulary:

- `HYPOTHESIS`: unverified assertion.
- `INFERENCE`: deterministic or model-assisted derivation with cited premises.
- `OBSERVATION`: present in retrieved bytes or an executed measurement.
- `VERIFIED_FINDING`: observation independently checked against its evidence.

Rules:

- A URL is not evidence by itself. Every accepted signal points to retained bytes or a reproducible
  query/export, a locator, retrieval metadata, and a hash.
- Search snippets, model memory, and model confidence are not accepted market signals.
- Raw evidence outranks derived values. Every feature stores the exact signal IDs and config hash that
  produced it.
- Human manual entry is allowed only with `collection_method=MANUAL`, actor, date, and an attached
  source artifact or explicit `UNVERIFIED` status.
- Corrections supersede; they do not rewrite history.
- Agent inputs and outputs are hashed and retained as artifacts, but private reasoning is not requested
  or stored.
- A scoring run is reproducible from an immutable evidence cut plus config and code versions.

### Enrichment interfaces

Providers are adapters, not scoring logic. The Python boundary is conceptually:

```python
class SignalProvider(Protocol):
    provider_id: str
    provider_version: str

    def collect(self, request: SignalRequest) -> ProviderResult: ...
```

`SignalRequest` contains product family, aliases, geography, metric keys, and `as_of`. `ProviderResult`
contains typed observations, raw-payload references, query metadata, and exactly one terminal status:
`OK`, `NO_DATA`, `RETRYABLE_ERROR`, `PERMANENT_ERROR`, or `BLOCKED_TERMS`.

The first adapter is `manual`, which imports reviewed CSV/JSON exports. This allows the makhana slice to
work without brittle scraping. Later adapters can cover search, marketplace, social, supplier, carrier,
and regulatory sources after access and terms are chosen. An adapter may collect evidence; it may not
normalize a score.

### Deterministic scoring

All weights, breakpoints, risk penalties, freshness windows, minimum-source rules, hard blockers, and
decision thresholds live in `config/scoring.v0.yaml`. The file is schema-validated and hashed into every
score row. Code contains generic transform functions, not product-specific weights.

Every dimension is computed only from accepted `market_signals`. The initial feature contract is:

| Dimension | Required raw evidence | Deterministic calculation |
|---|---|---|
| US demand | US monthly query volume and/or an approved US retail demand proxy | configured log/piecewise transforms, then configured weighted mean |
| Search growth | timestamped weekly/monthly search series | 12-month year-over-year change plus robust trend slope, mapped by config |
| Social growth | approved platform/export post or view series and distinct-creator counts | 90-day growth and creator breadth; null if no compliant source |
| Competition gap | reproducible marketplace query snapshot: listing count, top-N review distribution, brand share | configured inverse-saturation components; demand is scored separately so low demand cannot masquerade as a gap |
| Margin potential | observed retail price, supplier quote, MOQ, freight/duty, fulfillment/referral fees, returns allowance | landed contribution dollars and gross-margin percent under named scenarios |
| Supplier availability/concentration | verified supplier entities, locations, quote dates, certifications, MOQ | count/diversity/MOQ transforms; concentration uses HHI or configured equivalent |
| Shelf stability | manufacturer specification, label, COA, or other authoritative product-form evidence | months, storage regime, and refrigeration requirement mapped by config |
| Shipping friendliness | packaged weight/dimensions, dimensional weight, fragility, cold-chain/hazmat flags, rate card | deterministic per-unit shipping burden and penalties |
| Familiarity / education burden | generic-product query share and mainstream retailer presence from reproducible snapshots | configured familiarity index; education burden is its inverse |
| Brandability | top-N brand HHI, generic/unbranded share, and evidence-backed format/packaging differentiation checklist | low-weight experimental rubric; checklist values require evidence and cannot be filled by model intuition |
| Repeat purchase | pack size, serving size, recurring-purchase availability, and observed subscription/reorder proxy | consumption-window and recurring-availability transforms |
| Regulatory/import risk | cited checklist against applicable FDA, USDA/APHIS, CBP/USITC, labeling, and claim requirements for the exact product form/origin | configured severity sum plus explicit hard blockers; professional/human review required |

Regulatory evidence starts from official sources such as [FDA food imports](https://www.fda.gov/importing-food-products-united-states),
[FDA human-food imports](https://www.fda.gov/industry/importing-fda-regulated-products/importing-human-foods),
and [USDA APHIS plant-product imports](https://www.aphis.usda.gov/plant-imports). A model must not infer
that a commodity is admissible. Exact product form, origin, tariff classification, FSVP responsibility,
label, and APHIS/ACIR status remain evidence requirements and may require a broker or counsel.

Scoring math:

```text
dimension_score[d] = weighted_mean(configured transforms of accepted feature inputs)
raw_opportunity_score = weighted_mean(non-null dimension scores, using configured weights)
evidence_coverage = sum(weight of adequately evidenced dimensions) / sum(all dimension weights)
evidence_quality = weighted_mean(source reliability * freshness * independence * completeness)
confidence_score = 100 * evidence_coverage * evidence_quality
overall_score = raw_opportunity_score * confidence_score / 100
```

All values are bounded to 0-100. Regulatory risk is stored as risk (higher is worse) and is inverted or
subtracted exactly once by the configured formula. A missing dimension is `NULL`, never zero and never a
model estimate. It contributes no evidence coverage, so missing evidence lowers confidence and promotion
eligibility as well as `overall_score`. `last_verified_at` is the oldest verification timestamp among
evidence used by all required, present dimensions; it is null if no full required evidence cut exists.

Initial BUILD/TEST/WATCH/KILL thresholds must be present in configuration before operational ranking.
Until the 20-25-product pilot is calibrated, thresholds are marked provisional and cards are
`RESEARCH_ONLY`. The rule order is:

1. A verified configured hard blocker can produce `KILL`.
2. Insufficient coverage, confidence, freshness, or unresolved critical validator finding forbids
   `BUILD`; the result is `TEST` or `WATCH` with named gaps.
3. Only an `overall_score` above the configured threshold, all evidence gates passing, and an independent
   validator `PASS` can produce `BUILD`.
4. Ben records the final decision. No state triggers an external action.

Makhana's forced-pilot flag bypasses candidate selection only. It bypasses no evidence, risk, validation,
or promotion gate.

### Agent contracts and Menta/Hermes routing

Agent roles are task contracts mapped onto the existing Menta profile registry, not four new autonomous
services.

| ODOP role | Existing profile/route intent | Contract output | Forbidden authority |
|---|---|---|---|
| Scout | `research.analyst`; fast local challenger for triage, stronger local route only for promoted ambiguity | source/query log, claim candidates, observations, evidence refs, gaps | scores, family merges, verified claims |
| Normalization helper | `build.bounded-worker` | one schema-conformant family/category proposal | automatic ambiguous merge |
| Market Analyst | `biz.strategy-finance` with deterministic code as the numerical oracle | signal-to-feature mapping, units, assumptions, anomalies | direct score or rank writes |
| Validator | `assure.evidence` plus Python recomputation; `legal.compliance` only when warranted | challenge findings, affected evidence/features, PASS/REJECT/UNKNOWN | editing evidence, features, or scores |
| Synthesizer | `product.strategy-ux` or configured narrative route | concise card that copies an immutable score snapshot and cites evidence IDs | new facts, changed numbers, final decision |

Current Menta profile defaults are configuration evidence, not permanent model choices. The resolver must
record the observed provider/model/route. Validator independence requires a different profile and model
from the producer; the route config must reject a resolved collision rather than silently accept it.
On 2026-10-03 the desired and live agent-profile registries had the same SHA-256, while the desired and
live Hermes config files had different hashes. ODOP must therefore trust resolved run telemetry, not
assume that the desired config describes the live route.

The eventual Hermes-Menta project profile should require `exec.project-lead`, `research.analyst`,
`biz.strategy-finance`, `assure.evidence`, and `assure.formula`; conditionally add
`build.bounded-worker`, `legal.compliance`, `growth.seo-content`, and `product.strategy-ux` for the stages
shown above. Its workspace is this repository, autonomy ceiling is L2, and explicit approval gates cover
outreach, purchasing, importing, publication, deployment, and any decision-driving score-config change.
Runs remain attended/manual because the inspected Menta architecture does not claim an enforced
unattended durable-worker bridge.

Every output is validated against JSON Schema/Pydantic. Score fields are absent from Scout, Analyst, and
Validator contracts; unknown fields are rejected. If a validator finds a bad numeric premise, a new or
corrected signal is admitted and Python recomputes a new score version.

Flagship/cloud review is not required for v0. It is eligible only for already promoted top-five
candidates, by explicit human choice, after its Menta route and cost/provenance behavior are verified.

### Agent and cost observability

`agent_runs` records:

- run/product/stage and Menta profile;
- requested and resolved provider, model, route, and service class;
- prompt/contract/config/input/output hashes;
- start/end/duration, attempt, retry ancestry, and terminal state;
- input/output token counts when reported, plus whether counts are measured or estimated;
- cost amount/currency with state `MEASURED`, `ESTIMATED`, `NONE`, or `UNKNOWN`;
- output artifact and evidence references.

This is compatible with the intent of Menta's route telemetry and dogfood run receipt. It does not
import archived A30/A32 modules or claim that the current Hermes CLI exposes every field. An
`AgentRunner` adapter should capture what the runtime actually reports and leave unavailable values
`UNKNOWN`.

### Caching and reproducibility

- Raw sources/evidence are content-addressed and immutable. Retain them while any score/card references
  them.
- Provider request cache key: provider id/version + canonical request JSON + credential-free account
  scope + terms-safe locale. Response hash is recorded separately.
- Cache TTL is per metric in config. Evidence freshness is independent of cache TTL.
- Scoring never performs network access. It operates on an explicit `evidence_cut_id`.
- Agent result cache key: role contract version + route/model + prompt/input/config/evidence hashes.
- A changed source, alias map, formula, weight, or evidence item creates a new derived version; it does
  not edit a prior run.
- Cache misses and `NO_DATA` are observable. Stale data is not silently substituted.

### Retry and error strategy

| Failure | Action |
|---|---|
| HTTP 429/5xx/timeout | bounded exponential backoff with jitter, maximum three attempts and a total wall-clock budget |
| HTTP 4xx auth/terms/config | permanent failure; no retry; surface required action |
| Source hash changed | ingest a new snapshot and require reconciliation |
| PDF/table parse ambiguity | alternate deterministic parser once, then quarantine for human review |
| Schema-invalid model output | one repair attempt with validation errors, then fail the run |
| Agent timeout/runtime failure | one same-route retry only if idempotent; any escalation is explicit and recorded |
| Missing market evidence | `NO_DATA`; lower coverage/confidence; continue other dimensions |
| Invalid unit/range/provenance | reject the signal; never coerce silently |
| Partial product enrichment | persist successful observations, mark incomplete, and forbid BUILD if gates fail |

All commands use an idempotency key derived from operation, product/source identity, evidence cut, and
config hash. Runs are restartable at stage boundaries. Errors are typed (`TRANSIENT`, `AUTH`, `TERMS`,
`PARSE`, `SCHEMA`, `VALIDATION`, `PERSISTENCE`, `UNKNOWN`) and retained with attempt history.

### Testing strategy

- Unit tests for text normalization, row parsing, aliases, units, transforms, confidence, and gates.
- Regression fixtures for observed PDF pathologies: wrapped products/districts, page-boundary joins, and
  `TOTAL 335. BIHAR`-style extraction.
- Golden reconciliation against an available official snapshot: 726 rows, 35 sections, state totals,
  and six Bihar `Makhana (Foxnut)` assignments. A changed official hash requires deliberate fixture
  review rather than an automatic golden update.
- Contract tests for each enrichment adapter using retained legal fixtures; no live network in the
  default test suite.
- Golden score vectors independently hand-calculated from synthetic evidence.
- Property tests: scores remain in range; adding missingness cannot increase coverage/confidence;
  increasing a risk input cannot improve the result; reordering evidence cannot change a score.
- Agent-contract tests that reject unknown fields, invented evidence IDs, and attempted score writes.
- Integration test: small source fixture -> two makhana district rows -> one family -> manual evidence
  -> score snapshot -> validator finding -> card.
- Optional marked test for the full official PDF and optional marked live-provider smoke tests.
- Idempotency, retry, stale-cache, corrupt-artifact, and interrupted-run tests.

## 2. Reused existing components

### Reuse as contracts or patterns

- Hermes-Menta `registry/agent-profiles/registry.yaml`: stable profile IDs, producer/validator separation,
  model-route evidence, and tool ceilings.
- Hermes-Menta project-profile convention: named workspace, L2 ceiling, explicit approval gates, and
  required/conditional validators.
- Menta dogfood run receipt and manual durable-work loop: bounded run, verification, artifact, verdict,
  and human gate.
- Menta evidence vocabulary and route-telemetry field names: claim classes, input/output hashes,
  attempts, timing, usage/cost state, and no silent success.
- Fridgy patterns: content-addressed document storage, typed stage I/O, append-only ledger, deterministic
  `model:none` stages, provider seam, bounded schema repair, typed retry classification, and idempotency
  keys.
- Menta Media pattern: a project-owned CLI/environment behind a thin Hermes adapter if ODOP later needs
  first-class Hermes tools.

### Do not couple directly

- Hermes-Menta is configuration/governance, not an importable product framework.
- The A30/A32 Python implementation inspected in `~/.hermes/archive/2026-09` is archived and is not a
  supported dependency.
- Fridgy is TypeScript and product-specific. Reuse its proven design boundaries, not copied runtime code.
- Menta Media's plugin is media-specific. A Hermes plugin is deferred until the ODOP CLI is stable.

## 3. New components required

- ODOP source manifest, snapshotter, PDF row parser, reconciliation report, and reviewed override format.
- Product-family/alias taxonomy with merge/split history.
- DuckDB schema, migrations, and repository layer.
- Manual evidence importer plus typed provider interface/cache.
- Deterministic feature, confidence, scoring, and promotion-gate engine.
- ODOP-specific agent contracts and a thin Menta/Hermes runner adapter.
- A Hermes-Menta `odop-scanner` project profile and dogfood registry entry, added only when Ben approves
  the cross-repository onboarding change.
- Validator findings, decision records, and Markdown opportunity-card renderer.
- Makhana fixture/evidence packet and end-to-end acceptance test.

## 4. Explicit MVP boundaries

In v0:

- ingest and reconcile one official ODOP source version;
- normalize all rows into reviewed product families;
- select only 20-25 pilot families, always including makhana;
- enrich only those candidates and deeply analyze at most five;
- produce local ranked reports and opportunity cards;
- keep Ben as final decision-maker.

Not in v0:

- storefront, public SaaS/API, frontend/dashboard, auth, customer accounts, mobile app;
- payments, ads, supplier outreach, ordering, import filing, or other external automation;
- unattended agents, daemon, scheduler, distributed queue, vector database, or new workflow framework;
- autonomous health, regulatory, tariff, margin, or sourcing conclusions;
- hundreds of deep enrichments before the pilot proves source economics.

## 5. Risks and unknowns

1. This directory was empty and was not a Git repository on inspection. No branch can be created until
   Git is initialized and a base commit exists.
2. The authoritative update cadence and supersession policy for the PDF/GIS portal are undocumented in
   the inspected sources.
3. The ministry's reported 137 unique products may use a taxonomy not published as machine-readable
   data. It is a reconciliation target, not a forced family count.
4. Makhana's exact commercial forms and botanical terminology need authoritative mapping. Raw seed,
   popped/roasted snack, flavored snack, and ingredient formats have different economics and controls.
5. Search-volume, marketplace, social, and supplier sources, access, terms, quotas, and budgets are not
   chosen. Defaulting to scraping would be an architectural error.
6. Margin cannot be decision-grade without current quotes, MOQ, product form, duties, freight, fees,
   losses, and returns assumptions.
7. Exact FDA/FSVP, USDA/APHIS ACIR, labeling, customs, and tariff treatment depends on product form,
   origin, process, claims, and importer arrangement. Professional review may be required.
8. Brandability and repeat-purchase proxies need pilot calibration against real outcomes; keep their
   weights low and provisional.
9. The current supported programmatic Hermes output/telemetry surface has not been verified, and the
   live Hermes config hash differs from the desired Hermes-Menta config hash. Missing route, usage, or
   cost data must remain `UNKNOWN` rather than being inferred from the desired file.
10. No successful flagship route or price/quality threshold was established in the inspected Menta
    records. Do not claim a flagship advantage or automate escalation.

## 6. Proposed implementation order

1. Initialize Git, make the documentation baseline commit, and create
   `feat/odop-opportunity-scanner`.
2. Add Python packaging, source/scoring config schemas, DuckDB migration, and provenance models.
3. Implement source snapshot -> parse -> reconcile, including the official-PDF optional golden test.
4. Implement product families, aliases, review overrides, and the six-row makhana consolidation.
5. Implement manual evidence import, deterministic features/confidence/score, and a card renderer.
6. Complete the makhana vertical slice. It may correctly end as `TEST: evidence gaps`; do not fabricate
   enough evidence to make it BUILD.
7. Add the runner adapter and the four agent contracts; prove validator independence and run telemetry.
8. Select a stratified 20-25-family pilot, choose compliant providers, and measure coverage/cost.
9. Calibrate provisional weights/thresholds, run the pilot, and deeply validate only the top five.
10. Decide from observed bottlenecks whether Postgres, a Hermes plugin, schedules, or any UI is justified.

## 7. Files expected to change

This architecture pass creates:

- `AGENT_BRIEF.md`
- `AGENT_TRACKER.md`
- `PHASE_WORKFLOW.md`
- `docs/architecture/ODOP_SCANNER_V0.md`

The first implementation slice is expected to add the repository shape listed above, beginning with
`pyproject.toml`, `config/`, `sql/migrations/001_initial.sql`, `src/odop_scanner/`, and focused tests.

After the local CLI and contracts exist, onboarding is expected to change
`/Users/ben/Desktop/Mintloop/Infra/Hermes-Menta/registry/project-profiles/odop-scanner.yaml` and the
Hermes-Menta dogfood project registry. Those cross-repository edits are not part of this architecture
pass.

No ADR was added in this pass because this project had no repository history or existing ADR convention.
The present document is the proposed architecture record; it can be renamed to `ADR-0001` after the
repository convention is established.

## 8. GO / BLOCKED recommendation

**GO** for repository bootstrap and the source -> rows -> family -> makhana card vertical slice. The
design fits one MacBook, preserves provenance, scales from 25 to hundreds by adding evidence rows rather
than changing architecture, and introduces no distributed infrastructure.

**BLOCKED** for operational ranking, `BUILD` promotion, importing, or spending decisions until market
data sources/terms, scoring calibration, exact makhana product form, and regulatory/import evidence are
resolved. These blocks do not prevent the deterministic spine or an honest evidence-gap card.
