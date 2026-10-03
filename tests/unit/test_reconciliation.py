from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import duckdb

from odop_scanner.models import ParsedRow, ReconciliationDataset, SourceDocument
from odop_scanner.reconciliation import MAKHANA_DISTRICTS, makhana_checks, reconcile_datasets
from odop_scanner.storage import (
    append_reconciliation_review,
    reconciliation_queue,
    store_reconciliation,
)

NOW = datetime(2026, 10, 3, tzinfo=UTC)


def _row(
    source_id: str,
    row_number: int,
    state: str,
    district: str,
    product: str,
    *,
    parsed: bool = True,
) -> ParsedRow:
    return ParsedRow(
        row_id=f"{source_id}-row-{row_number}",
        source_id=source_id,
        state=state,
        district=district,
        product=product,
        source_page=row_number,
        source_reference=f"page:{row_number};state:{state};row:{row_number}",
        raw_text=f"{district} | {product}",
        parse_status="parsed" if parsed else "malformed",
        parse_error=None if parsed else "product missing",
        ingested_at=NOW,
    )


def _dataset(
    source_version: str,
    source_hash: str,
    rows: tuple[ParsedRow, ...],
) -> ReconciliationDataset:
    document = SourceDocument(
        source_id=source_hash,
        source_name=source_version,
        source_url=f"https://example.invalid/{source_version}.pdf",
        source_date=date(2025, 1, 1),
        ingested_at=NOW,
        content_sha256=source_hash,
        storage_path=Path(f"/tmp/{source_version}.pdf"),
        media_type="application/pdf",
        raw_text="fixture",
    )
    return ReconciliationDataset(source_version, document, rows)


def test_reconciliation_distinguishes_all_statuses_and_preserves_evidence() -> None:
    baseline = _dataset(
        "baseline-2024",
        "baseline-hash",
        (
            _row("base", 1, "BIHAR", "Alpha", "Makhana (Foxnut)"),
            _row("base", 2, "BIHAR", "Beta", "Mango"),
            _row("base", 3, "BIHAR", "Gamma", "Ginger"),
            _row("base", 4, "BIHAR", "Duplicate", "Apple"),
            _row("base", 5, "BIHAR", "Duplicate", "Banana"),
        ),
    )
    newer = _dataset(
        "newer-2025",
        "newer-hash",
        (
            _row("new", 11, "BIHAR", "Alpha", "Makhana / Foxnut"),
            _row("new", 12, "BIHAR", "Beta", "Banana"),
            _row("new", 13, "BIHAR", "Delta", "Rice"),
            _row("new", 14, "BIHAR", "Duplicate", "Apple"),
            _row("new", 15, "BIHAR", "Unreadable product", "", parsed=False),
        ),
    )

    result = reconcile_datasets(
        baseline,
        newer,
        comparison_version="v0-test",
        config_sha256="config-hash",
    )
    by_district = {diff.district: diff for diff in result.diffs}

    assert by_district["Alpha"].proposed_status == "same"
    assert by_district["Beta"].proposed_status == "changed"
    assert by_district["Gamma"].proposed_status == "removed"
    assert by_district["Delta"].proposed_status == "added"
    assert by_district["Duplicate"].proposed_status == "ambiguous"
    assert by_district["Unreadable product"].proposed_status == "ambiguous"
    assert by_district["Alpha"].human_review_status == "not_required"
    assert by_district["Beta"].human_review_status == "pending"
    assert by_district["Beta"].baseline_source_sha256 == "baseline-hash"
    assert by_district["Beta"].newer_source_sha256 == "newer-hash"
    assert by_district["Beta"].baseline_locators == ("page:2;state:BIHAR;row:2",)
    assert by_district["Beta"].newer_locators == ("page:12;state:BIHAR;row:12",)

    repeated = reconcile_datasets(
        baseline,
        newer,
        comparison_version="v0-test",
        config_sha256="config-hash",
    )
    assert repeated.comparison_id == result.comparison_id
    assert [diff.diff_id for diff in repeated.diffs] == [diff.diff_id for diff in result.diffs]


def test_append_only_review_decisions_never_mutate_original_diff(
    database: duckdb.DuckDBPyConnection,
) -> None:
    baseline = _dataset(
        "baseline-2024",
        "baseline-hash",
        (_row("base", 1, "BIHAR", "Beta", "Mango"),),
    )
    newer = _dataset(
        "newer-2025",
        "newer-hash",
        (_row("new", 1, "BIHAR", "Beta", "Banana"),),
    )
    result = reconcile_datasets(
        baseline,
        newer,
        comparison_version="v0-test",
        config_sha256="config-hash",
    )
    store_reconciliation(database, result)
    diff_id = result.diffs[0].diff_id

    first_id = append_reconciliation_review(
        database,
        diff_id=diff_id,
        decision="keep_2024",
        reviewer="reviewer@example.test",
        rationale="Retain the approved memorandum pending clarification.",
        reviewed_at=NOW,
    )
    second_id = append_reconciliation_review(
        database,
        diff_id=diff_id,
        decision="defer_ambiguous",
        reviewer="reviewer@example.test",
        rationale="Conflicting official evidence remains unresolved.",
        reviewed_at=NOW + timedelta(seconds=1),
    )

    queue = reconciliation_queue(database, human_status="ambiguous")
    assert len(queue) == 1
    assert queue[0]["current_decision"] == "defer_ambiguous"
    assert queue[0]["baseline_product"] == "Mango"
    assert queue[0]["newer_product"] == "Banana"
    assert queue[0]["evidence_locator"]["baseline"] == ["page:1;state:BIHAR;row:1"]
    decisions = database.execute(
        """
        SELECT decision_id, supersedes_decision_id
        FROM source_reconciliation_reviews
        WHERE diff_id = ? ORDER BY reviewed_at
        """,
        [diff_id],
    ).fetchall()
    assert decisions == [(first_id, None), (second_id, first_id)]
    original = database.execute(
        "SELECT proposed_status, initial_human_review_status FROM source_reconciliation_diffs"
    ).fetchone()
    assert original == ("changed", "pending")


def test_all_six_makhana_assignments_are_checked_across_versions() -> None:
    baseline_rows = tuple(
        _row("base", index, "BIHAR", district, "Makhana (Foxnut)")
        for index, district in enumerate(MAKHANA_DISTRICTS, 1)
    )
    newer_rows = tuple(
        _row("new", index + 10, "BIHAR", district, "Makhana (Foxnut)")
        for index, district in enumerate(MAKHANA_DISTRICTS, 1)
    )
    result = reconcile_datasets(
        _dataset("baseline-2024", "baseline-hash", baseline_rows),
        _dataset("newer-2025", "newer-hash", newer_rows),
        comparison_version="v0-test",
        config_sha256="config-hash",
    )

    checks = makhana_checks([result])
    assert len(checks) == 6
    assert {check["district"] for check in checks} == set(MAKHANA_DISTRICTS)
    assert all(check["proposed_status"] == "same" for check in checks)
