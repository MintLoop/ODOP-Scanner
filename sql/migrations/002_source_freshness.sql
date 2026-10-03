CREATE TABLE IF NOT EXISTS source_freshness_checks (
    check_id VARCHAR PRIMARY KEY,
    config_version VARCHAR NOT NULL,
    config_sha256 VARCHAR NOT NULL,
    checked_on DATE NOT NULL,
    selected_source_id VARCHAR NOT NULL,
    freshness_status VARCHAR NOT NULL,
    decision VARCHAR NOT NULL,
    reason VARCHAR NOT NULL,
    searched_surfaces_json VARCHAR NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS source_discoveries (
    check_id VARCHAR NOT NULL,
    observation_id VARCHAR NOT NULL,
    source_kind VARCHAR NOT NULL,
    discovery_url VARCHAR NOT NULL,
    source_url VARCHAR NOT NULL,
    published_or_revised_date DATE,
    retrieval_date DATE NOT NULL,
    sha256 VARCHAR,
    supersedes_2024 BOOLEAN,
    row_count INTEGER,
    product_family_count INTEGER,
    row_count_change VARCHAR NOT NULL,
    product_family_count_change VARCHAR NOT NULL,
    disposition VARCHAR NOT NULL,
    notes VARCHAR NOT NULL,
    PRIMARY KEY (check_id, observation_id)
);
