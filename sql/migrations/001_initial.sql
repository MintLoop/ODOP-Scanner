CREATE TABLE IF NOT EXISTS schema_migrations (
    version VARCHAR PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS source_documents (
    source_id VARCHAR PRIMARY KEY,
    source_name VARCHAR NOT NULL,
    source_url VARCHAR,
    source_date DATE,
    ingested_at TIMESTAMPTZ NOT NULL,
    content_sha256 VARCHAR NOT NULL,
    storage_path VARCHAR NOT NULL,
    media_type VARCHAR NOT NULL,
    raw_text VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS source_rows (
    row_id VARCHAR PRIMARY KEY,
    source_id VARCHAR NOT NULL,
    state VARCHAR NOT NULL,
    district VARCHAR NOT NULL,
    product VARCHAR NOT NULL,
    source_page INTEGER,
    source_reference VARCHAR NOT NULL,
    raw_text VARCHAR NOT NULL,
    parse_status VARCHAR NOT NULL,
    parse_error VARCHAR,
    ingested_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS product_families (
    family_id VARCHAR PRIMARY KEY,
    canonical_name VARCHAR NOT NULL UNIQUE,
    category VARCHAR,
    forced_candidate BOOLEAN NOT NULL DEFAULT FALSE,
    taxonomy_version VARCHAR NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS normalized_products (
    normalized_id VARCHAR PRIMARY KEY,
    row_id VARCHAR NOT NULL UNIQUE,
    family_id VARCHAR,
    normalized_name VARCHAR NOT NULL,
    normalization_status VARCHAR NOT NULL,
    normalization_method VARCHAR NOT NULL,
    normalization_version VARCHAR NOT NULL,
    model_route VARCHAR,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS product_aliases (
    family_id VARCHAR NOT NULL,
    alias VARCHAR NOT NULL,
    alias_normalized VARCHAR NOT NULL,
    source VARCHAR NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (family_id, alias_normalized)
);

CREATE TABLE IF NOT EXISTS feature_values (
    family_id VARCHAR PRIMARY KEY,
    demand DOUBLE,
    competition_gap DOUBLE,
    margin DOUBLE,
    search_velocity DOUBLE,
    social_velocity DOUBLE,
    supplier_depth DOUBLE,
    shelf_stability DOUBLE,
    shipping DOUBLE,
    brandability DOUBLE,
    repeat_purchase DOUBLE,
    regulatory_risk DOUBLE,
    evidence_json VARCHAR NOT NULL DEFAULT '{}',
    observed_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS opportunity_scores (
    score_id VARCHAR PRIMARY KEY,
    family_id VARCHAR NOT NULL,
    component_scores_json VARCHAR NOT NULL,
    missing_metrics_json VARCHAR NOT NULL,
    raw_score DOUBLE,
    overall_score DOUBLE,
    evidence_coverage DOUBLE NOT NULL,
    confidence_band VARCHAR NOT NULL,
    score_status VARCHAR NOT NULL,
    score_version VARCHAR NOT NULL,
    scoring_config_sha256 VARCHAR NOT NULL,
    scored_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS processing_runs (
    run_id VARCHAR PRIMARY KEY,
    operation VARCHAR NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    ended_at TIMESTAMPTZ,
    config_version VARCHAR,
    config_sha256 VARCHAR,
    model_route VARCHAR,
    source_identifier VARCHAR,
    input_hash VARCHAR,
    output_reference VARCHAR,
    status VARCHAR NOT NULL,
    error_type VARCHAR,
    error_message VARCHAR
);

CREATE VIEW IF NOT EXISTS candidate_dataset AS
SELECT
    f.family_id,
    f.canonical_name,
    f.category,
    f.forced_candidate,
    COUNT(DISTINCT r.state) AS state_count,
    COUNT(DISTINCT (r.state, r.district)) AS district_count,
    string_agg(DISTINCT r.state, ', ' ORDER BY r.state) AS states,
    string_agg(DISTINCT r.district, ', ' ORDER BY r.district) AS districts
FROM product_families f
JOIN normalized_products n ON n.family_id = f.family_id
JOIN source_rows r ON r.row_id = n.row_id
GROUP BY f.family_id, f.canonical_name, f.category, f.forced_candidate;
