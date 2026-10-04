CREATE TABLE IF NOT EXISTS evidence_items (
    evidence_id VARCHAR PRIMARY KEY,
    family_id VARCHAR NOT NULL,
    claim_class VARCHAR NOT NULL,
    source_title VARCHAR NOT NULL,
    source_url VARCHAR NOT NULL,
    source_type VARCHAR NOT NULL,
    locator VARCHAR NOT NULL,
    retrieval_date DATE NOT NULL,
    observed_at DATE,
    collection_method VARCHAR NOT NULL,
    acceptance_state VARCHAR NOT NULL,
    content_sha256 VARCHAR NOT NULL,
    notes VARCHAR NOT NULL,
    payload_json VARCHAR NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS market_signals (
    signal_id VARCHAR PRIMARY KEY,
    family_id VARCHAR NOT NULL,
    metric VARCHAR NOT NULL,
    value_decimal DOUBLE,
    value_text VARCHAR,
    unit VARCHAR,
    evidence_ids_json VARCHAR NOT NULL,
    observed_at DATE NOT NULL,
    acceptance_state VARCHAR NOT NULL,
    provider_version VARCHAR NOT NULL,
    request_hash VARCHAR NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS validator_findings (
    finding_id VARCHAR PRIMARY KEY,
    family_id VARCHAR NOT NULL,
    score_id VARCHAR NOT NULL,
    severity VARCHAR NOT NULL,
    finding_status VARCHAR NOT NULL,
    title VARCHAR NOT NULL,
    strongest_case VARCHAR NOT NULL,
    affected_features_json VARCHAR NOT NULL,
    evidence_ids_json VARCHAR NOT NULL,
    recommended_action VARCHAR NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS decision_records (
    decision_id VARCHAR PRIMARY KEY,
    family_id VARCHAR NOT NULL,
    score_id VARCHAR NOT NULL,
    gate VARCHAR NOT NULL,
    research_only BOOLEAN NOT NULL,
    validator_verdict VARCHAR NOT NULL,
    reasons_json VARCHAR NOT NULL,
    max_recommended_spend_usd DOUBLE NOT NULL,
    evidence_packet_sha256 VARCHAR NOT NULL,
    gate_config_sha256 VARCHAR NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_runs (
    run_id VARCHAR PRIMARY KEY,
    family_id VARCHAR NOT NULL,
    agent VARCHAR NOT NULL,
    model VARCHAR,
    route VARCHAR,
    started_at TIMESTAMPTZ,
    ended_at TIMESTAMPTZ,
    duration_ms BIGINT,
    cost_amount DOUBLE,
    cost_currency VARCHAR,
    cost_state VARCHAR NOT NULL,
    output_artifact VARCHAR,
    status VARCHAR NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);
