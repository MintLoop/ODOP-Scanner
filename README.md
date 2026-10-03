# ODOP Scanner

ODOP Scanner is a local-first, deterministic pipeline for turning the official Indian One District
One Product list into product-family candidates. The current vertical slice ingests source documents,
preserves row provenance, normalizes product names, groups exact/approved aliases, and calculates
versioned scores without inventing missing market evidence.

Makhana / foxnut is the forced Product #001 dogfood record. Forced inclusion affects candidate
selection only; it does not bypass evidence or scoring rules.

## What is implemented

```text
official PDF, text, CSV, or JSON
  -> immutable content-addressed source snapshot
  -> provenance-bearing source rows
  -> deterministic normalization and reviewed alias taxonomy
  -> product families with district-level provenance
  -> candidate dataset
  -> pure configured scoring function
  -> evidence coverage and confidence band
  -> JSON CLI/report output and processing-run receipts
```

Internet market enrichment, scraping, supplier outreach, and autonomous decisions are deliberately
out of scope.

## Setup

Python 3.12 through 3.14 and [`uv`](https://docs.astral.sh/uv/) are supported.

```bash
uv sync --all-groups
```

The package is installed into `.venv`. Run the module directly or use the installed `odop` command:

```bash
.venv/bin/python -m odop_scanner --help
.venv/bin/odop --help
```

## Runbook

Global options such as `--db` and `--raw-dir` come before the subcommand.

Inspect and persist the reviewed source-freshness decision, then ingest the configured MoFPI source of
record:

```bash
.venv/bin/python -m odop_scanner freshness
.venv/bin/python -m odop_scanner ingest
```

The default URL and source invariants live in [`config/sources.toml`](config/sources.toml). To ingest a
local official snapshot while preserving its canonical URL and publication date:

```bash
.venv/bin/python -m odop_scanner ingest \
  --source /path/to/odop.pdf \
  --source-name "MoFPI Revised List of ODOP for 35 States/UTs" \
  --source-url "https://www.mofpi.gov.in/sites/default/files/revised_list_of_odop_for_35_states_13.03.2024_1.pdf" \
  --source-date 2024-03-13
```

The live official-source review is recorded in
[`config/source_freshness.toml`](config/source_freshness.toml) and
[`docs/source-freshness/2026-10-03.md`](docs/source-freshness/2026-10-03.md). The 2024 PDF is explicitly
marked `checked_not_assumed_current`: it remains v0 source-of-record because MoFPI's live ODOP page
still links it as the approved revised list and newer official publications conflict without declaring
supersession. Canonical ingestion fails closed if its SHA-256 or 726-row invariant changes.

### Deterministic source reconciliation

Compare the pinned 2024 source against the two newer official annexures. If local files are omitted,
the command downloads the three configured official URLs; local snapshots remain hash-validated:

```bash
.venv/bin/python -m odop_scanner reconcile \
  --baseline /path/to/revised-2024.pdf \
  --lok-sabha /path/to/lok-sabha-525.pdf \
  --annual-report /path/to/annual-report-2024-25.pdf
```

The comparison configuration, expected hashes, row counts, annexure page range, and parser quarantine
count live in [`config/reconciliation.v0.toml`](config/reconciliation.v0.toml). Comparison IDs and row
diff IDs are content-derived, so rerunning identical inputs is idempotent. Only punctuation, casing,
spacing, separators, and layout hyphenation are normalized; values such as `Kiwi based Products` and
`Kiwi` remain different and require review.

Inspect pending conflicts and append a review decision:

```bash
.venv/bin/python -m odop_scanner reconciliation-queue \
  --human-status pending --limit 25 --offset 0

.venv/bin/python -m odop_scanner reconciliation-review DIFF_ID \
  --decision keep_2024 \
  --reviewer "Ben" \
  --rationale "Retain the approved memorandum pending authoritative clarification."
```

Review decisions are append-only. Later decisions point to the decision they supersede; they never
rewrite source rows, diffs, or the configured 2024 source-of-record. Available decisions are
`keep_2024`, `accept_newer`, `mark_same`, and `defer_ambiguous`. Even `accept_newer` records only a
review outcome—it does not automatically supersede the canonical source.

Normalize, inspect candidates, score Makhana, and produce a report:

```bash
.venv/bin/python -m odop_scanner normalize
.venv/bin/python -m odop_scanner candidates --limit 25
.venv/bin/python -m odop_scanner score makhana
.venv/bin/python -m odop_scanner score foxnut
.venv/bin/python -m odop_scanner report --top 10
```

By default, the DuckDB database is `data/odop.duckdb` and immutable source snapshots are placed under
`data/raw/`. Both are intentionally ignored by Git. Re-running ingestion is idempotent for identical
source bytes because source and row IDs are content-derived.

For a disposable run, provide explicit locations:

```bash
.venv/bin/python -m odop_scanner \
  --db /tmp/odop-smoke.duckdb \
  --raw-dir /tmp/odop-smoke-raw \
  ingest --source /path/to/odop.pdf
```

## Normalization behavior

Deterministic rules normalize Unicode, whitespace, case, punctuation spacing, dashes, and separators.
Exact source values remain stored unchanged. Approved aliases are versioned in
[`config/taxonomy.toml`](config/taxonomy.toml).

Exact normalized matches may merge automatically. Fuzzy matches and optional model suggestions never
merge automatically: they remain separate families with `normalization_status = review_required`.
No model route is enabled in this slice.

## Scoring and evidence coverage

[`config/scoring.v0.toml`](config/scoring.v0.toml) versions the eleven dimensions, their weights, the
positive/negative direction, and confidence thresholds. Inputs must already be normalized to 0–100.
Missing inputs remain `null`.

```text
raw score = weighted mean of available dimensions
evidence coverage = available dimension weight / total expected weight
overall score = raw score * evidence coverage
```

Regulatory risk is represented as risk, so the scoring engine inverts it exactly once. With no market
evidence, Makhana is honestly `unscored`: its overall score is `null`, evidence coverage is `0`, and
confidence is `none`.

## Reproducibility and provenance

The database retains source-discovery and supersession records plus the source name, URL, publication
date, ingestion timestamp, SHA-256, immutable
snapshot path, full extracted text, raw row text, page, row reference, original state/district/product,
normalization version/method, scoring config hash, and processing success or failure. Processing runs
also record their source set and model route when one is used.

The forward-only schema migrations are in [`sql/migrations/`](sql/migrations/). The broader approved
design and phase boundaries are in
[`docs/architecture/ODOP_SCANNER_V0.md`](docs/architecture/ODOP_SCANNER_V0.md) and
[`PHASE_WORKFLOW.md`](PHASE_WORKFLOW.md).

## Validation

```bash
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy
.venv/bin/pytest -q
```

Tests cover ingestion, malformed rows, aliases, ambiguous normalization, duplicate districts,
deterministic scoring, missing evidence, weighted coverage, config versioning, regulatory penalties,
run receipts, source reconciliation statuses, append-only reviews, source-version isolation, and the
Makhana Product #001 slice.
