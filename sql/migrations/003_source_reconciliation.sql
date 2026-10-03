CREATE TABLE IF NOT EXISTS source_reconciliation_comparisons (
    comparison_id VARCHAR PRIMARY KEY,
    comparison_version VARCHAR NOT NULL,
    config_sha256 VARCHAR NOT NULL,
    baseline_source_version VARCHAR NOT NULL,
    newer_source_version VARCHAR NOT NULL,
    baseline_source_sha256 VARCHAR NOT NULL,
    newer_source_sha256 VARCHAR NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS source_reconciliation_diffs (
    diff_id VARCHAR PRIMARY KEY,
    comparison_id VARCHAR NOT NULL,
    state VARCHAR NOT NULL,
    district VARCHAR NOT NULL,
    baseline_product VARCHAR,
    newer_product VARCHAR,
    baseline_row_ids_json VARCHAR NOT NULL,
    newer_row_ids_json VARCHAR NOT NULL,
    baseline_locators_json VARCHAR NOT NULL,
    newer_locators_json VARCHAR NOT NULL,
    conflict_type VARCHAR NOT NULL,
    proposed_status VARCHAR NOT NULL,
    initial_human_review_status VARCHAR NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS source_reconciliation_reviews (
    decision_id VARCHAR PRIMARY KEY,
    diff_id VARCHAR NOT NULL,
    decision VARCHAR NOT NULL,
    resulting_human_review_status VARCHAR NOT NULL,
    reviewer VARCHAR NOT NULL,
    rationale VARCHAR NOT NULL,
    reviewed_at TIMESTAMPTZ NOT NULL,
    supersedes_decision_id VARCHAR
);
