from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest

from odop_scanner.cli import main
from odop_scanner.config import load_scoring, load_taxonomy
from odop_scanner.normalization import normalize_rows
from odop_scanner.scoring import calculate_score
from odop_scanner.storage import (
    candidate_records,
    get_features,
    load_parsed_rows,
    product_record,
    store_normalization,
)
from tests.conftest import stored_bihar_fixture


def test_makhana_product_001_end_to_end(
    database: duckdb.DuckDBPyConnection,
    bihar_fixture: Path,
    tmp_path: Path,
) -> None:
    stored_bihar_fixture(database, bihar_fixture, tmp_path / "raw")
    decisions = normalize_rows(load_parsed_rows(database), load_taxonomy())
    store_normalization(database, decisions, load_taxonomy())

    candidate = candidate_records(database, limit=1)[0]
    assert candidate["family_id"] == "product-001"
    assert candidate["canonical_name"] == "makhana"
    assert {"Makhana (Foxnut)", "fox nut", "foxnut"}.issubset(candidate["aliases"])
    assert candidate["district_count"] == 6
    assert candidate["normalization_status"] == "normalized"
    assert len(candidate["provenance"]) == 6

    features = get_features(database, "product-001")
    score = calculate_score("product-001", features, load_scoring())
    assert score.overall_score is None
    assert score.evidence_coverage == 0
    assert score.confidence_band == "none"
    assert len(score.missing_metrics) == 11

    product = product_record(database, "product-001")
    assert all(value is None for value in product["currently_known_market_metrics"].values())


def test_duplicate_districts_do_not_inflate_candidate_count(
    database: duckdb.DuckDBPyConnection,
    tmp_path: Path,
) -> None:
    csv_path = tmp_path / "duplicates.csv"
    csv_path.write_text(
        "state,district,product\nBIHAR,Araria,Makhana\nBIHAR,Araria,Foxnut\n",
        encoding="utf-8",
    )
    from odop_scanner.ingestion import ingest_path
    from odop_scanner.storage import store_ingestion

    result = ingest_path(
        csv_path,
        source_name="duplicate fixture",
        source_url=None,
        source_date=None,
        raw_directory=tmp_path / "raw",
    )
    store_ingestion(database, result.document, result.rows)
    taxonomy = load_taxonomy()
    store_normalization(database, normalize_rows(load_parsed_rows(database), taxonomy), taxonomy)

    candidate = candidate_records(database, limit=1)[0]
    assert candidate["family_id"] == "product-001"
    assert candidate["district_count"] == 1
    assert len(candidate["provenance"]) == 2


def test_cli_smoke_for_makhana(
    bihar_fixture: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database = tmp_path / "cli.duckdb"
    common = ["--db", str(database), "--raw-dir", str(tmp_path / "raw")]
    assert main([*common, "freshness"]) == 0
    freshness_output = json.loads(capsys.readouterr().out)
    assert freshness_output["freshness_status"] == "checked_not_assumed_current"
    assert main([*common, "ingest", "--source", str(bihar_fixture)]) == 0
    capsys.readouterr()
    assert main([*common, "normalize"]) == 0
    capsys.readouterr()
    assert main([*common, "score", "foxnut"]) == 0

    captured = capsys.readouterr()
    output = json.loads(captured.out)
    assert output["score"]["score_status"] == "unscored"
    assert output["product"]["canonical_name"] == "makhana"
    assert main([*common, "candidates", "--limit", "1"]) == 0
    capsys.readouterr()
    assert main([*common, "report", "--top", "1"]) == 0
    capsys.readouterr()

    connection = duckdb.connect(str(database), read_only=True)
    runs = connection.execute(
        """
        SELECT operation, started_at, config_version, model_route, source_identifier, status
        FROM processing_runs
        ORDER BY started_at
        """
    ).fetchall()
    connection.close()

    assert [run[0] for run in runs] == [
        "freshness",
        "ingest",
        "normalize",
        "score",
        "candidates",
        "report",
    ]
    assert all(run[1] is not None for run in runs)
    assert all(run[2] is not None for run in runs)
    assert all(run[3] is None for run in runs)
    assert all(run[4] for run in runs)
    assert all(run[5] == "succeeded" for run in runs)

    connection = duckdb.connect(str(database), read_only=True)
    discovery_count = connection.execute("SELECT count(*) FROM source_discoveries").fetchone()
    connection.close()
    assert discovery_count == (4,)


def test_canonical_source_hash_change_fails_closed(
    bihar_fixture: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database = tmp_path / "hash-guard.duckdb"
    exit_code = main(
        [
            "--db",
            str(database),
            "--raw-dir",
            str(tmp_path / "raw"),
            "ingest",
            "--source",
            str(bihar_fixture),
            "--source-url",
            "https://www.mofpi.gov.in/sites/default/files/"
            "revised_list_of_odop_for_35_states_13.03.2024_1.pdf",
        ]
    )

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert output["status"] == "failed"
    assert "canonical source hash changed" in output["error"]
