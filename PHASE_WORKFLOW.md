# ODOP Scanner phase workflow

Each phase ends at a gate. A failed gate creates a tracked issue or evidence gap; it does not trigger a
larger redesign or an unrecorded workaround.

## Phase 0 — architecture and evidence boundary

Status: complete for proposal; awaiting Ben's acceptance.

Outputs:

- architecture, data, score, provenance, agent, caching, retry, and test contracts;
- explicit reuse boundaries for Hermes-Menta, Fridgy, and Menta Media;
- MVP boundaries and unknowns.

Gate:

- one MacBook is sufficient;
- no model owns a number;
- every accepted number can name evidence, formula/config version, and time;
- weak evidence cannot produce BUILD;
- makhana has a complete designed route.

## Phase 1 — repository and deterministic data spine

Outputs:

- initialized Git repository and `feat/odop-opportunity-scanner` branch;
- Python package, locked dependencies, configuration schemas, DuckDB migration;
- content-addressed artifact store and typed run/error records.

Gate:

- clean install and unit-test command on the MacBook;
- migration is repeatable and forward-only;
- a rerun with the same input/config is idempotent;
- raw bytes and credentials cannot be committed accidentally.

## Phase 2 — official ODOP ingestion

Outputs:

- source discovery and immutable revised-PDF snapshot;
- deterministic PDF extraction/parser and reconciliation report;
- reviewed override mechanism for ambiguous rows.

Gate:

- all source rows retain snapshot hash and locator;
- state totals and serial sequences reconcile;
- the available official snapshot yields 726 district rows across 35 state/UT sections;
- parser ambiguity is quarantined, not guessed;
- the six Bihar makhana assignments are present.

## Phase 3 — normalization and family identity

Outputs:

- product families, aliases, categories, membership decisions, and merge/split history;
- deterministic normalization before any model-assisted proposal;
- reviewed makhana family mapping.

Gate:

- district rows remain lossless;
- equivalent products can be consolidated across districts;
- fuzzy/model matches never auto-merge;
- a source or taxonomy change creates a new version without rewriting history.

## Phase 4 — Product #001 vertical slice

Outputs:

- reviewed manual evidence adapter and makhana evidence packet;
- deterministic feature/confidence/score engine;
- validator contract and opportunity-card renderer.

Gate:

- every numeric makhana value has accepted evidence;
- unsupported dimensions are null and lower coverage/confidence;
- a score is reproducible from its evidence cut and config hash;
- validator findings cannot write scores;
- the card reports an honest state, including `TEST: evidence gaps` when appropriate.

## Phase 5 — pilot cohort of 20-25 families

Outputs:

- deterministic, stratified cohort selection with makhana forced in;
- chosen compliant enrichment providers or reviewed manual exports;
- provider contract tests, cache/freshness behavior, and run/cost receipts.

Gate:

- no unapproved scraping or terms ambiguity;
- partial provider failure degrades one metric/product, not the whole run;
- observed route/model, duration, usage, cost state, and artifacts are queryable;
- provisional scoring transforms and thresholds are declared in config.

## Phase 6 — rank and deep-analyze at most five

Outputs:

- versioned pilot ranking;
- independent challenge packets for only the promoted top five plus makhana if not already present;
- concise BUILD/TEST/WATCH/KILL cards for Ben.

Gate:

- no BUILD without coverage, confidence, freshness, validator, and hard-risk gates;
- margin scenarios include quotes, MOQ, landed costs, fees, and assumptions;
- regulatory findings identify exact product form and official sources;
- a human decision record closes each card.

## Phase 7 — evaluate, do not automatically expand

Use observed pilot pain to decide whether to add providers, Postgres, a Hermes plugin, scheduling, or a
small report UI. None is a default follow-on.

Expansion from 25 to hundreds is allowed when ingestion/family coverage is sound and provider economics
are measured. Deep analysis remains gated; the architecture scales by adding evidence and runs, not by
changing the score contract.

## Cross-phase stop conditions

Stop and mark BLOCKED when:

- source authority or row identity cannot be reconciled;
- a provider cannot be used within its terms;
- a numeric feature lacks a reproducible evidence path;
- model output would be the only numerical oracle;
- validator independence cannot be enforced;
- a requested action crosses into outreach, purchasing, importing, publication, or deployment without
  Ben's explicit approval.
