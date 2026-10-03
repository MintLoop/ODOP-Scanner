from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any

from .config import (
    load_scoring,
    load_source_freshness,
    load_sources,
    load_taxonomy,
    project_root,
)
from .ingestion import download_source, ingest_path
from .normalization import normalize_rows
from .scoring import calculate_score
from .storage import (
    ProcessingRun,
    candidate_records,
    connect_database,
    dataset_config_version,
    default_database_path,
    get_features,
    load_parsed_rows,
    product_record,
    report_records,
    resolve_family_id,
    score_as_dict,
    source_set_identifier,
    store_ingestion,
    store_normalization,
    store_score,
    store_source_freshness,
)


def _json_default(value: object) -> str:
    if isinstance(value, (date, Path)):
        return str(value)
    return str(value)


def _print(payload: Any) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False, default=_json_default, sort_keys=True))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="odop", description="Deterministic ODOP Scanner v0")
    parser.add_argument("--db", type=Path, default=default_database_path())
    parser.add_argument("--raw-dir", type=Path, default=project_root() / "data" / "raw")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest = subparsers.add_parser("ingest", help="ingest an official PDF or structured fixture")
    ingest.add_argument("--source", help="local path or URL; defaults to the configured MoFPI PDF")
    ingest.add_argument("--source-name")
    ingest.add_argument("--source-url", help="canonical URL when --source is a local snapshot")
    ingest.add_argument("--source-date", type=date.fromisoformat)

    subparsers.add_parser(
        "freshness", help="show and persist the reviewed official-source freshness manifest"
    )

    normalize = subparsers.add_parser(
        "normalize", help="normalize parsed rows into product families"
    )
    normalize.add_argument("--taxonomy", type=Path)

    candidates = subparsers.add_parser(
        "candidates", help="show the deterministic candidate dataset"
    )
    candidates.add_argument("--limit", type=int, default=25)

    score = subparsers.add_parser("score", help="score one product family or alias")
    score.add_argument("product")
    score.add_argument("--config", type=Path)

    report = subparsers.add_parser("report", help="show the latest ranked score records")
    report.add_argument("--top", type=int, default=10)

    return parser


def _ingest(args: argparse.Namespace) -> dict[str, Any]:
    source_config_version, sources = load_sources()
    freshness = load_source_freshness()
    configured = sources[0]
    uses_configured_source = args.source is None
    source = str(configured.url if uses_configured_source else args.source)
    source_name = str(
        args.source_name or (configured.name if uses_configured_source else Path(source).name)
    )
    source_url = args.source_url or (source if source.startswith(("http://", "https://")) else None)
    source_date = args.source_date or (configured.source_date if uses_configured_source else None)

    connection = connect_database(args.db)
    run = ProcessingRun(
        connection,
        "ingest",
        config_version=source_config_version,
        source_identifier=source,
    )
    try:
        if source.startswith(("http://", "https://")):
            with tempfile.TemporaryDirectory(prefix="odop-ingest-") as temporary:
                local_path = Path(temporary) / Path(source).name
                download_source(source, local_path)
                result = ingest_path(
                    local_path,
                    source_name=source_name,
                    source_url=source_url,
                    source_date=source_date,
                    raw_directory=args.raw_dir,
                )
        else:
            result = ingest_path(
                Path(source),
                source_name=source_name,
                source_url=source_url,
                source_date=source_date,
                raw_directory=args.raw_dir,
            )
        freshness_output: dict[str, Any] | None = None
        if source_url == configured.url:
            if (
                configured.expected_sha256 is not None
                and result.document.content_sha256 != configured.expected_sha256
            ):
                raise ValueError(
                    "canonical source hash changed: "
                    f"expected {configured.expected_sha256}, got {result.document.content_sha256}"
                )
            if (
                configured.expected_rows is not None
                and len(result.rows) != configured.expected_rows
            ):
                raise ValueError(
                    "canonical source row count changed: "
                    f"expected {configured.expected_rows}, got {len(result.rows)}"
                )
            selected = next(
                item
                for item in freshness.observations
                if item.observation_id == freshness.selected_source_id
            )
            if selected.source_url != configured.url:
                raise ValueError("freshness selection does not match configured canonical source")
            if (
                configured.expected_sha256 is not None
                and selected.sha256 != configured.expected_sha256
            ):
                raise ValueError(
                    "freshness selection hash does not match configured canonical source"
                )
            check_id = store_source_freshness(connection, freshness)
            freshness_output = {
                "check_id": check_id,
                "checked_on": freshness.checked_on,
                "freshness_status": freshness.freshness_status,
                "decision": freshness.decision,
                "selected_source_id": freshness.selected_source_id,
            }
        store_ingestion(connection, result.document, result.rows)
        parsed_count = sum(row.parse_status == "parsed" for row in result.rows)
        malformed = [asdict(row) for row in result.rows if row.parse_status == "malformed"]
        output = {
            "run_id": run.run_id,
            "source_id": result.document.source_id,
            "source_name": result.document.source_name,
            "source_url": result.document.source_url,
            "source_date": result.document.source_date,
            "content_sha256": result.document.content_sha256,
            "stored_at": result.document.storage_path,
            "row_count": len(result.rows),
            "parsed_count": parsed_count,
            "malformed_count": len(malformed),
            "malformed_records": malformed,
            "freshness": freshness_output,
        }
        run.succeed(f"source:{result.document.source_id}")
        return output
    except BaseException as error:
        run.fail(error)
        raise
    finally:
        connection.close()


def _freshness(args: argparse.Namespace) -> dict[str, Any]:
    freshness = load_source_freshness()
    selected = next(
        item
        for item in freshness.observations
        if item.observation_id == freshness.selected_source_id
    )
    connection = connect_database(args.db)
    run = ProcessingRun(
        connection,
        "freshness",
        config_version=freshness.version,
        config_sha256=freshness.sha256,
        source_identifier=selected.source_url,
    )
    try:
        check_id = store_source_freshness(connection, freshness)
        output = asdict(freshness)
        output["check_id"] = check_id
        output["run_id"] = run.run_id
        run.succeed(f"freshness:{check_id}")
        return output
    except BaseException as error:
        run.fail(error)
        raise
    finally:
        connection.close()


def _normalize(args: argparse.Namespace) -> dict[str, Any]:
    taxonomy = load_taxonomy(args.taxonomy)
    connection = connect_database(args.db)
    rows = load_parsed_rows(connection)
    input_hash = hashlib.sha256("".join(row.row_id for row in rows).encode()).hexdigest()
    run = ProcessingRun(
        connection,
        "normalize",
        config_version=taxonomy.version,
        config_sha256=taxonomy.sha256,
        source_identifier=source_set_identifier(connection),
        input_hash=input_hash,
    )
    try:
        decisions = normalize_rows(rows, taxonomy)
        store_normalization(connection, decisions, taxonomy)
        output = {
            "run_id": run.run_id,
            "taxonomy_version": taxonomy.version,
            "taxonomy_sha256": taxonomy.sha256,
            "normalized_count": len(decisions),
            "review_required_count": sum(
                decision.normalization_status == "review_required" for decision in decisions
            ),
            "family_count": len({decision.family_id for decision in decisions}),
            "model_route": None,
        }
        run.succeed("table:normalized_products")
        return output
    except BaseException as error:
        run.fail(error)
        raise
    finally:
        connection.close()


def _candidates(args: argparse.Namespace) -> dict[str, Any]:
    if args.limit < 1:
        raise ValueError("--limit must be at least 1")
    connection = connect_database(args.db)
    run = ProcessingRun(
        connection,
        "candidates",
        config_version=dataset_config_version(connection),
        source_identifier=source_set_identifier(connection),
    )
    try:
        records = candidate_records(connection, limit=args.limit)
        output = {"run_id": run.run_id, "candidate_count": len(records), "candidates": records}
        run.succeed("stdout:candidate_dataset")
        return output
    except BaseException as error:
        run.fail(error)
        raise
    finally:
        connection.close()


def _score(args: argparse.Namespace) -> dict[str, Any]:
    config = load_scoring(args.config)
    connection = connect_database(args.db)
    run = ProcessingRun(
        connection,
        "score",
        config_version=config.version,
        config_sha256=config.sha256,
        source_identifier=source_set_identifier(connection),
        input_hash=hashlib.sha256(args.product.encode()).hexdigest(),
    )
    try:
        family_id = resolve_family_id(connection, args.product)
        features = get_features(connection, family_id)
        score = calculate_score(family_id, features, config)
        store_score(connection, score)
        product = product_record(connection, family_id)
        output = {
            "run_id": run.run_id,
            "product": product,
            "score": score_as_dict(score),
        }
        run.succeed(f"score:{score.score_id}")
        return output
    except BaseException as error:
        run.fail(error)
        raise
    finally:
        connection.close()


def _report(args: argparse.Namespace) -> dict[str, Any]:
    if args.top < 1:
        raise ValueError("--top must be at least 1")
    connection = connect_database(args.db)
    run = ProcessingRun(
        connection,
        "report",
        config_version=dataset_config_version(connection, include_scores=True),
        source_identifier=source_set_identifier(connection),
    )
    try:
        records = report_records(connection, limit=args.top)
        output = {"run_id": run.run_id, "result_count": len(records), "results": records}
        run.succeed("stdout:ranked_report")
        return output
    except BaseException as error:
        run.fail(error)
        raise
    finally:
        connection.close()


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    handlers = {
        "ingest": _ingest,
        "freshness": _freshness,
        "normalize": _normalize,
        "candidates": _candidates,
        "score": _score,
        "report": _report,
    }
    try:
        _print(handlers[args.command](args))
        return 0
    except Exception as error:
        _print({"status": "failed", "error_type": type(error).__name__, "error": str(error)})
        return 1


if __name__ == "__main__":
    sys.exit(main())
