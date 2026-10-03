from __future__ import annotations

from odop_scanner.config import load_reconciliation, load_source_freshness, load_sources


def test_source_freshness_records_reviewed_supersession_decision() -> None:
    freshness = load_source_freshness()
    _, sources = load_sources()
    selected = next(
        item
        for item in freshness.observations
        if item.observation_id == freshness.selected_source_id
    )
    annual_report = next(
        item
        for item in freshness.observations
        if item.observation_id == "mofpi-annual-report-2024-25"
    )

    assert freshness.freshness_status == "checked_not_assumed_current"
    assert selected.source_url == sources[0].url
    assert selected.sha256 == sources[0].expected_sha256
    assert selected.row_count == 726
    assert annual_report.row_count_change == "unchanged"
    assert annual_report.product_family_count == 137
    assert annual_report.product_family_count_change == "unchanged"
    assert annual_report.supersedes_2024 is False


def test_reconciliation_config_pins_all_three_official_snapshots() -> None:
    config = load_reconciliation()

    assert config.version == "v0.1.0"
    assert len(config.sources) == 3
    assert {source.role for source in config.sources} == {
        "baseline",
        "lok_sabha",
        "annual_report",
    }
    assert all(len(source.expected_sha256) == 64 for source in config.sources)
    annual = next(source for source in config.sources if source.role == "annual_report")
    assert (annual.page_start, annual.page_end) == (255, 274)
    assert annual.expected_malformed_rows == 3
