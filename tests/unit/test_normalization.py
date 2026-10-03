from __future__ import annotations

from datetime import UTC, datetime

from odop_scanner.config import load_taxonomy
from odop_scanner.models import ParsedRow
from odop_scanner.normalization import normalize_rows, normalize_text


def _row(row_id: str, product: str) -> ParsedRow:
    return ParsedRow(
        row_id=row_id,
        source_id="source",
        state="BIHAR",
        district=row_id,
        product=product,
        source_page=1,
        source_reference=f"row:{row_id}",
        raw_text=product,
        parse_status="parsed",
        parse_error=None,
        ingested_at=datetime(2026, 10, 3, tzinfo=UTC),
    )


def test_configured_makhana_aliases_share_product_001() -> None:
    products = ("Makhana", "Fox Nut", "Foxnut", "Makhana (Fox Nut)")
    decisions = normalize_rows(
        tuple(_row(str(index), product) for index, product in enumerate(products)),
        load_taxonomy(),
    )

    assert {decision.family_id for decision in decisions} == {"product-001"}
    assert {decision.canonical_name for decision in decisions} == {"makhana"}
    assert all(decision.normalization_status == "normalized" for decision in decisions)


def test_ambiguous_near_alias_requires_review_without_merging() -> None:
    decision = normalize_rows((_row("1", "Makhanaa"),), load_taxonomy())[0]

    assert decision.normalization_status == "review_required"
    assert decision.family_id != "product-001"
    assert decision.normalization_method.startswith("fuzzy_suggestion:product-001")


def test_ambiguous_unconfigured_source_values_remain_separate() -> None:
    decisions = normalize_rows(
        (
            _row("1", "Apple based product"),
            _row("2", "Apple based products"),
        ),
        load_taxonomy(),
    )

    assert len({decision.family_id for decision in decisions}) == 2
    assert all(decision.normalization_status == "review_required" for decision in decisions)


def test_presentation_normalization_is_deterministic() -> None:
    assert normalize_text("  Fox  Nut – Roasted / Salted ") == "fox nut-roasted/salted"
