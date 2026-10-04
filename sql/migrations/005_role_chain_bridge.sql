ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS requested_profile VARCHAR;
ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS resolved_profile VARCHAR;
ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS provider VARCHAR;
ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS service_class VARCHAR;
ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS input_tokens BIGINT;
ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS output_tokens BIGINT;
ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS token_state VARCHAR;
ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS input_sha256 VARCHAR;
ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS output_sha256 VARCHAR;
ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS evidence_refs_json VARCHAR;
ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS error_class VARCHAR;
ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS registry_sha256 VARCHAR;
ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS contract_version VARCHAR;

CREATE TABLE IF NOT EXISTS role_chain_runs (
    chain_run_id VARCHAR PRIMARY KEY,
    family_id VARCHAR NOT NULL,
    evidence_packet_sha256 VARCHAR NOT NULL,
    routing_config_sha256 VARCHAR NOT NULL,
    registry_sha256 VARCHAR,
    started_at TIMESTAMPTZ NOT NULL,
    ended_at TIMESTAMPTZ NOT NULL,
    duration_ms BIGINT NOT NULL,
    run_status VARCHAR NOT NULL,
    blocked_reason VARCHAR,
    score_id VARCHAR NOT NULL,
    overall_score DOUBLE,
    evidence_coverage DOUBLE NOT NULL,
    validator_verdict VARCHAR,
    decision_gate VARCHAR,
    validator_independence_verified BOOLEAN NOT NULL,
    orchestration_verified BOOLEAN NOT NULL,
    accepted_evidence_count INTEGER NOT NULL,
    populated_metric_count INTEGER NOT NULL,
    null_metric_count INTEGER NOT NULL,
    total_cost_amount DOUBLE,
    cost_currency VARCHAR,
    cost_state VARCHAR NOT NULL,
    artifact_directory VARCHAR NOT NULL,
    benchmark_artifact VARCHAR NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);
