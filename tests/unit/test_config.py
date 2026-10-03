from __future__ import annotations

from odop_scanner.config import load_source_freshness, load_sources


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
