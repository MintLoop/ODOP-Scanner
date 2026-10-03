from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from odop_scanner.ingestion import ingest_path, parse_official_layout_pages
from tests.conftest import ingest_bihar_fixture


def test_ingests_bihar_rows_with_raw_provenance(bihar_fixture: Path, tmp_path: Path) -> None:
    result = ingest_bihar_fixture(bihar_fixture, tmp_path / "raw")

    assert len(result.rows) == 6
    assert {row.district for row in result.rows} == {
        "Araria",
        "Darbhanga",
        "Katihar",
        "Madhubani",
        "Saharsa",
        "Supaul",
    }
    assert all(row.product == "Makhana (Foxnut)" for row in result.rows)
    assert all(row.source_page == 1 for row in result.rows)
    assert all("Makhana (Foxnut)" in row.raw_text for row in result.rows)
    assert result.document.storage_path.read_text(encoding="utf-8").startswith("     5. BIHAR")


def test_malformed_record_is_retained_and_flagged(tmp_path: Path) -> None:
    page = """
     5. BIHAR
 Sl. No.         District                      ODOP
 1               Araria                        Makhana (Foxnut)
 2               Missing Product
 TOTAL                                         2
"""
    rows = parse_official_layout_pages(
        [page], source_id="source", ingested_at=datetime(2026, 10, 3, tzinfo=UTC)
    )

    assert len(rows) == 2
    assert rows[0].parse_status == "parsed"
    assert rows[1].parse_status == "malformed"
    assert rows[1].district == "Missing Product"
    assert rows[1].product == ""
    assert rows[1].parse_error == "product missing"


def test_unbalanced_columns_are_quarantined_as_malformed() -> None:
    page = """
 2. ARUNACHAL PRADESH
 Sl. No.          District                               ODOP
 23               Papum Pare (Capital                    Turmeric Complex)
"""
    rows = parse_official_layout_pages(
        [page], source_id="source", ingested_at=datetime(2026, 10, 3, tzinfo=UTC)
    )

    assert rows[0].parse_status == "malformed"
    assert rows[0].parse_error == (
        "district parentheses unbalanced; product parentheses unbalanced"
    )


def test_product_column_updates_for_each_state_section() -> None:
    page = """
 1. FIRST STATE
 Sl. No.          District                               ODOP
 1                Alpha                                  Apple
 2. SECOND STATE
 Sl. No.     District                 ODOP
 1           Beta                     Banana
"""
    rows = parse_official_layout_pages(
        [page], source_id="source", ingested_at=datetime(2026, 10, 3, tzinfo=UTC)
    )

    assert [(row.state, row.district, row.product) for row in rows] == [
        ("FIRST STATE", "Alpha", "Apple"),
        ("SECOND STATE", "Beta", "Banana"),
    ]


def test_layout_parser_retains_pdf_page_number_and_shifted_product_continuation() -> None:
    page = """
 5. BIHAR
 Sl. No.          District                               ODOP
 7                Bhojpur                                Indian traditional Sweets (Khurma/
                                                       Belgrami)
 8                Buxar                                  Papdi
 257
"""
    rows = parse_official_layout_pages(
        [page],
        source_id="source",
        ingested_at=datetime(2026, 10, 3, tzinfo=UTC),
        page_number_offset=256,
    )

    assert rows[0].source_page == 257
    assert rows[0].source_reference == "page:257;state:BIHAR;row:7"
    assert rows[0].district == "Bhojpur"
    assert rows[0].product == "Indian traditional Sweets (Khurma/ Belgrami)"
    assert rows[1].district == "Buxar"
    assert rows[1].product == "Papdi"


def test_csv_requires_expected_headers(tmp_path: Path) -> None:
    path = tmp_path / "bad.csv"
    path.write_text("province,place,item\nBihar,Araria,Makhana\n", encoding="utf-8")

    try:
        ingest_path(
            path,
            source_name="bad",
            source_url=None,
            source_date=None,
            raw_directory=tmp_path / "raw",
        )
    except ValueError as error:
        assert "state, district, and product" in str(error)
    else:
        raise AssertionError("malformed CSV headers should fail")
