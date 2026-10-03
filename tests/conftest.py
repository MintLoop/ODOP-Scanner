from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pytest

from odop_scanner.config import project_root
from odop_scanner.ingestion import IngestionResult, ingest_path
from odop_scanner.storage import connect_database, store_ingestion


@pytest.fixture
def bihar_fixture() -> Path:
    return project_root() / "tests" / "fixtures" / "odop_bihar_excerpt.txt"


@pytest.fixture
def database(tmp_path: Path) -> Iterator[duckdb.DuckDBPyConnection]:
    connection = connect_database(tmp_path / "test.duckdb")
    yield connection
    connection.close()


def ingest_bihar_fixture(path: Path, raw_directory: Path) -> IngestionResult:
    return ingest_path(
        path,
        source_name="MoFPI ODOP test excerpt",
        source_url="https://example.invalid/odop.pdf",
        source_date=datetime(2024, 3, 13, tzinfo=UTC).date(),
        raw_directory=raw_directory,
        ingested_at=datetime(2026, 10, 3, tzinfo=UTC),
    )


def stored_bihar_fixture(
    connection: duckdb.DuckDBPyConnection,
    path: Path,
    raw_directory: Path,
) -> IngestionResult:
    result = ingest_bihar_fixture(path, raw_directory)
    store_ingestion(connection, result.document, result.rows)
    return result
