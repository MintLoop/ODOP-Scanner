from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

# Python 3.9 compatibility: UTC is not available until 3.11
try:
    from datetime import UTC
except ImportError:
    from datetime import timezone

    UTC = timezone.utc  # noqa: UP017 -- Python 3.9 compatibility

import duckdb

from .config import project_root
from .models import (
    DecisionGateConfig,
    DecisionResult,
    EvidenceItem,
    MarketSignal,
    MetricValue,
    NormalizationDecision,
    ParsedRow,
    ReconciliationResult,
    ReviewDecision,
    ScoreResult,
    SourceDocument,
    SourceFreshnessConfig,
    TaxonomyConfig,
    ValidatorFinding,
    ValidatorVerdict,
)
from .normalization import normalize_text

FEATURE_COLUMNS = (
    "demand",
    "competition_gap",
    "margin",
    "search_velocity",
    "social_velocity",
    "supplier_depth",
    "shelf_stability",
    "shipping",
    "brandability",
    "repeat_purchase",
    "regulatory_risk",
)


def default_database_path() -> Path:
    return project_root() / "data" / "odop.duckdb"


def source_set_identifier(connection: duckdb.DuckDBPyConnection) -> str:
    """Return the exact ordered source IDs backing the current database."""

    source_ids = [
        str(record[0])
        for record in connection.execute(
            "SELECT source_id FROM source_documents ORDER BY source_id"
        ).fetchall()
    ]
    return f"source_ids:{json.dumps(source_ids, separators=(',', ':'))}"


def dataset_config_version(
    connection: duckdb.DuckDBPyConnection,
    *,
    include_scores: bool = False,
) -> str:
    """Describe persisted config versions used by the materialized dataset."""

    taxonomy_versions = [
        str(record[0])
        for record in connection.execute(
            "SELECT DISTINCT taxonomy_version FROM product_families ORDER BY taxonomy_version"
        ).fetchall()
    ]
    parts = [f"taxonomy:{','.join(taxonomy_versions) or 'none'}"]
    if include_scores:
        score_versions = [
            str(record[0])
            for record in connection.execute(
                "SELECT DISTINCT score_version FROM opportunity_scores ORDER BY score_version"
            ).fetchall()
        ]
        parts.append(f"scoring:{','.join(score_versions) or 'none'}")
    return ";".join(parts)


def connect_database(path: Path | None = None) -> duckdb.DuckDBPyConnection:
    database_path = (path or default_database_path()).resolve()
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(str(database_path))
    migration_directory = project_root() / "sql" / "migrations"
    for migration_path in sorted(migration_directory.glob("*.sql")):
        connection.execute(migration_path.read_text(encoding="utf-8"))
        connection.execute(
            "INSERT INTO schema_migrations VALUES (?, ?) ON CONFLICT DO NOTHING",
            [migration_path.stem, datetime.now(UTC)],
        )
    return connection


def store_source_freshness(
    connection: duckdb.DuckDBPyConnection,
    freshness: SourceFreshnessConfig,
) -> str:
    check_id = freshness.sha256
    connection.execute(
        """
        INSERT INTO source_freshness_checks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (check_id) DO NOTHING
        """,
        [
            check_id,
            freshness.version,
            freshness.sha256,
            freshness.checked_on,
            freshness.selected_source_id,
            freshness.freshness_status,
            freshness.decision,
            freshness.reason,
            json.dumps(freshness.searched_surfaces),
            datetime.now(UTC),
        ],
    )
    for observation in freshness.observations:
        connection.execute(
            """
            INSERT INTO source_discoveries VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            ) ON CONFLICT (check_id, observation_id) DO NOTHING
            """,
            [
                check_id,
                observation.observation_id,
                observation.source_kind,
                observation.discovery_url,
                observation.source_url,
                observation.published_or_revised_date,
                observation.retrieval_date,
                observation.sha256,
                observation.supersedes_2024,
                observation.row_count,
                observation.product_family_count,
                observation.row_count_change,
                observation.product_family_count_change,
                observation.disposition,
                observation.notes,
            ],
        )
    return check_id


def store_reconciliation(
    connection: duckdb.DuckDBPyConnection,
    result: ReconciliationResult,
) -> int:
    now = datetime.now(UTC)
    connection.execute(
        """
        INSERT INTO source_reconciliation_comparisons VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (comparison_id) DO NOTHING
        """,
        [
            result.comparison_id,
            result.comparison_version,
            result.config_sha256,
            result.baseline_source_version,
            result.newer_source_version,
            result.baseline_source_sha256,
            result.newer_source_sha256,
            now,
        ],
    )
    for diff in result.diffs:
        connection.execute(
            """
            INSERT INTO source_reconciliation_diffs VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            ) ON CONFLICT (diff_id) DO NOTHING
            """,
            [
                diff.diff_id,
                diff.comparison_id,
                diff.state,
                diff.district,
                diff.baseline_product,
                diff.newer_product,
                json.dumps(diff.baseline_row_ids),
                json.dumps(diff.newer_row_ids),
                json.dumps(diff.baseline_locators),
                json.dumps(diff.newer_locators),
                diff.conflict_type,
                diff.proposed_status,
                diff.human_review_status,
                now,
            ],
        )
    return len(result.diffs)


def reconciliation_queue(
    connection: duckdb.DuckDBPyConnection,
    *,
    human_status: str = "pending",
    newer_source_version: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    valid_statuses = {"all", "not_required", "pending", "reviewed", "ambiguous"}
    if human_status not in valid_statuses:
        raise ValueError(f"invalid human review status: {human_status}")
    if limit < 1:
        raise ValueError("queue limit must be at least 1")
    if offset < 0:
        raise ValueError("queue offset cannot be negative")
    records = connection.execute(
        """
        WITH latest_reviews AS (
            SELECT *, row_number() OVER (
                PARTITION BY diff_id ORDER BY reviewed_at DESC, decision_id DESC
            ) AS review_rank
            FROM source_reconciliation_reviews
        ), materialized AS (
            SELECT
                d.diff_id, d.comparison_id, c.comparison_version,
                c.baseline_source_version, c.newer_source_version,
                c.baseline_source_sha256, c.newer_source_sha256,
                d.state, d.district, d.baseline_product, d.newer_product,
                d.baseline_row_ids_json, d.newer_row_ids_json,
                d.baseline_locators_json, d.newer_locators_json,
                d.conflict_type, d.proposed_status,
                coalesce(r.resulting_human_review_status, d.initial_human_review_status)
                    AS human_review_status,
                r.decision, r.reviewer, r.rationale, r.reviewed_at, r.decision_id
            FROM source_reconciliation_diffs d
            JOIN source_reconciliation_comparisons c
                ON c.comparison_id = d.comparison_id
            LEFT JOIN latest_reviews r ON r.diff_id = d.diff_id AND r.review_rank = 1
        )
        SELECT * FROM materialized
        WHERE (? IS NULL OR newer_source_version = ?)
          AND (? = 'all' OR human_review_status = ?)
        ORDER BY newer_source_version, state, district, diff_id
        LIMIT ? OFFSET ?
        """,
        [
            newer_source_version,
            newer_source_version,
            human_status,
            human_status,
            limit,
            offset,
        ],
    ).fetchall()
    fields = (
        "diff_id",
        "comparison_id",
        "comparison_version",
        "baseline_source_version",
        "newer_source_version",
        "baseline_source_sha256",
        "newer_source_sha256",
        "state",
        "district",
        "baseline_product",
        "newer_product",
        "baseline_row_ids",
        "newer_row_ids",
        "baseline_locators",
        "newer_locators",
        "conflict_type",
        "proposed_status",
        "human_review_status",
        "current_decision",
        "reviewer",
        "rationale",
        "reviewed_at",
        "decision_id",
    )
    output: list[dict[str, Any]] = []
    for record in records:
        item = dict(zip(fields, record, strict=True))
        for field in (
            "baseline_row_ids",
            "newer_row_ids",
            "baseline_locators",
            "newer_locators",
        ):
            item[field] = json.loads(item[field])
        item["evidence_locator"] = {
            "baseline": item["baseline_locators"],
            "newer": item["newer_locators"],
        }
        output.append(item)
    return output


def append_reconciliation_review(
    connection: duckdb.DuckDBPyConnection,
    *,
    diff_id: str,
    decision: ReviewDecision,
    reviewer: str,
    rationale: str,
    reviewed_at: datetime | None = None,
) -> str:
    if decision not in {"keep_2024", "accept_newer", "mark_same", "defer_ambiguous"}:
        raise ValueError(f"invalid reconciliation decision: {decision}")
    if not reviewer.strip() or not rationale.strip():
        raise ValueError("reviewer and rationale are required")
    if (
        connection.execute(
            "SELECT 1 FROM source_reconciliation_diffs WHERE diff_id = ?", [diff_id]
        ).fetchone()
        is None
    ):
        raise LookupError(f"unknown reconciliation diff: {diff_id}")
    previous = connection.execute(
        """
        SELECT decision_id FROM source_reconciliation_reviews
        WHERE diff_id = ?
        ORDER BY reviewed_at DESC, decision_id DESC
        LIMIT 1
        """,
        [diff_id],
    ).fetchone()
    resulting_status = "ambiguous" if decision == "defer_ambiguous" else "reviewed"
    decision_id = str(uuid.uuid4())
    connection.execute(
        """
        INSERT INTO source_reconciliation_reviews VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            decision_id,
            diff_id,
            decision,
            resulting_status,
            reviewer.strip(),
            rationale.strip(),
            reviewed_at or datetime.now(UTC),
            str(previous[0]) if previous is not None else None,
        ],
    )
    return decision_id


class ProcessingRun:
    def __init__(
        self,
        connection: duckdb.DuckDBPyConnection,
        operation: str,
        *,
        config_version: str | None = None,
        config_sha256: str | None = None,
        model_route: str | None = None,
        source_identifier: str | None = None,
        input_hash: str | None = None,
    ) -> None:
        self.connection = connection
        self.run_id = str(uuid.uuid4())
        self.connection.execute(
            """
            INSERT INTO processing_runs (
                run_id, operation, started_at, config_version, config_sha256,
                model_route, source_identifier, input_hash, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'running')
            """,
            [
                self.run_id,
                operation,
                datetime.now(UTC),
                config_version,
                config_sha256,
                model_route,
                source_identifier,
                input_hash,
            ],
        )

    def succeed(self, output_reference: str | None = None) -> None:
        self.connection.execute(
            """
            UPDATE processing_runs
            SET ended_at = ?, output_reference = ?, status = 'succeeded'
            WHERE run_id = ?
            """,
            [datetime.now(UTC), output_reference, self.run_id],
        )

    def fail(self, error: BaseException) -> None:
        self.connection.execute(
            """
            UPDATE processing_runs
            SET ended_at = ?, status = 'failed', error_type = ?, error_message = ?
            WHERE run_id = ?
            """,
            [datetime.now(UTC), type(error).__name__, str(error), self.run_id],
        )


def store_ingestion(
    connection: duckdb.DuckDBPyConnection,
    document: SourceDocument,
    rows: Iterable[ParsedRow],
) -> int:
    connection.execute(
        """
        INSERT INTO source_documents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (source_id) DO UPDATE SET
            source_name = excluded.source_name,
            source_url = excluded.source_url,
            source_date = excluded.source_date,
            storage_path = excluded.storage_path,
            media_type = excluded.media_type,
            raw_text = excluded.raw_text
        """,
        [
            document.source_id,
            document.source_name,
            document.source_url,
            document.source_date,
            document.ingested_at,
            document.content_sha256,
            str(document.storage_path),
            document.media_type,
            document.raw_text,
        ],
    )
    materialized = list(rows)
    if materialized:
        connection.executemany(
            """
            INSERT INTO source_rows VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (row_id) DO NOTHING
            """,
            [
                [
                    row.row_id,
                    row.source_id,
                    row.state,
                    row.district,
                    row.product,
                    row.source_page,
                    row.source_reference,
                    row.raw_text,
                    row.parse_status,
                    row.parse_error,
                    row.ingested_at,
                ]
                for row in materialized
            ],
        )
    return len(materialized)


def load_parsed_rows(
    connection: duckdb.DuckDBPyConnection,
    *,
    source_ids: tuple[str, ...] | None = None,
) -> tuple[ParsedRow, ...]:
    source_filter = ""
    parameters: list[str] = []
    if source_ids:
        placeholders = ", ".join("?" for _ in source_ids)
        source_filter = f"AND source_id IN ({placeholders})"
        parameters.extend(source_ids)
    records = connection.execute(
        f"""
        SELECT row_id, source_id, state, district, product, source_page, source_reference,
               raw_text, parse_status, parse_error, ingested_at
        FROM source_rows
        WHERE parse_status = 'parsed'
        {source_filter}
        ORDER BY source_id, source_page, source_reference
        """,
        parameters,
    ).fetchall()
    return tuple(ParsedRow(*record) for record in records)


def store_normalization(
    connection: duckdb.DuckDBPyConnection,
    decisions: Iterable[NormalizationDecision],
    taxonomy: TaxonomyConfig,
) -> int:
    materialized = list(decisions)
    now = datetime.now(UTC)
    configured = {family.product_id: family for family in taxonomy.families}
    for decision in materialized:
        connection.execute(
            """
            INSERT INTO product_families VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (family_id) DO UPDATE SET
                canonical_name = excluded.canonical_name,
                category = excluded.category,
                forced_candidate = excluded.forced_candidate,
                taxonomy_version = excluded.taxonomy_version
            """,
            [
                decision.family_id,
                decision.canonical_name,
                decision.category,
                decision.forced_candidate,
                decision.normalization_version,
                now,
            ],
        )
        connection.execute(
            """
            INSERT INTO normalized_products VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (normalized_id) DO UPDATE SET
                family_id = excluded.family_id,
                normalized_name = excluded.normalized_name,
                normalization_status = excluded.normalization_status,
                normalization_method = excluded.normalization_method,
                normalization_version = excluded.normalization_version,
                model_route = excluded.model_route
            """,
            [
                decision.normalized_id,
                decision.row_id,
                decision.family_id,
                decision.normalized_name,
                decision.normalization_status,
                decision.normalization_method,
                decision.normalization_version,
                decision.model_route,
                now,
            ],
        )
        _store_alias(
            connection,
            decision.family_id,
            decision.observed_alias,
            "observed_source_value",
            now,
        )
        family = configured.get(decision.family_id)
        if family is not None:
            for alias in (family.canonical_name, *family.aliases):
                _store_alias(connection, family.product_id, alias, "configured_taxonomy", now)
    return len(materialized)


def _store_alias(
    connection: duckdb.DuckDBPyConnection,
    family_id: str,
    alias: str,
    source: str,
    created_at: datetime,
) -> None:
    connection.execute(
        """
        INSERT INTO product_aliases VALUES (?, ?, ?, ?, ?)
        ON CONFLICT (family_id, alias_normalized) DO NOTHING
        """,
        [family_id, alias, normalize_text(alias), source, created_at],
    )


def candidate_records(
    connection: duckdb.DuckDBPyConnection,
    *,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    records = connection.execute(
        """
        SELECT
            f.family_id, f.canonical_name, f.category, f.forced_candidate,
            r.state, r.district, r.product, r.source_page, r.source_reference,
            r.raw_text, d.source_name, d.source_url, d.content_sha256, d.ingested_at,
            n.normalization_status, n.normalization_method
        FROM product_families f
        JOIN normalized_products n ON n.family_id = f.family_id
        JOIN source_rows r ON r.row_id = n.row_id
        JOIN source_documents d ON d.source_id = r.source_id
        ORDER BY f.family_id, r.state, r.district, r.source_reference
        """
    ).fetchall()

    by_family: dict[str, dict[str, Any]] = {}
    for record in records:
        (
            family_id,
            canonical_name,
            category,
            forced_candidate,
            state,
            district,
            product,
            source_page,
            source_reference,
            raw_text,
            source_name,
            source_url,
            source_sha256,
            ingested_at,
            normalization_status,
            normalization_method,
        ) = record
        candidate = by_family.setdefault(
            family_id,
            {
                "family_id": family_id,
                "canonical_name": canonical_name,
                "category": category,
                "forced_candidate": bool(forced_candidate),
                "aliases": set(),
                "states": set(),
                "districts": set(),
                "normalization_status": "normalized",
                "normalization_methods": set(),
                "provenance": [],
            },
        )
        candidate["aliases"].add(product)
        candidate["states"].add(state)
        candidate["districts"].add((state, district))
        if normalization_status == "review_required":
            candidate["normalization_status"] = "review_required"
        candidate["normalization_methods"].add(normalization_method)
        candidate["provenance"].append(
            {
                "source_name": source_name,
                "source_url": source_url,
                "source_sha256": source_sha256,
                "ingested_at": ingested_at,
                "state": state,
                "district": district,
                "source_product": product,
                "raw_text": raw_text,
                "page": source_page,
                "reference": source_reference,
            }
        )

    alias_records = connection.execute(
        "SELECT family_id, alias FROM product_aliases ORDER BY family_id, alias_normalized"
    ).fetchall()
    for family_id, alias in alias_records:
        alias_candidate = by_family.get(str(family_id))
        if alias_candidate is None:
            continue
        if str(alias).casefold() != str(alias_candidate["canonical_name"]).casefold():
            alias_candidate["aliases"].add(str(alias))

    candidates: list[dict[str, Any]] = []
    for candidate in by_family.values():
        candidate["aliases"] = sorted(candidate["aliases"], key=str.casefold)
        candidate["states"] = sorted(candidate["states"], key=str.casefold)
        candidate["districts"] = [
            {"state": state, "district": district}
            for state, district in sorted(
                candidate["districts"], key=lambda value: (value[0].casefold(), value[1].casefold())
            )
        ]
        candidate["state_count"] = len(candidate["states"])
        candidate["district_count"] = len(candidate["districts"])
        candidate["normalization_methods"] = sorted(candidate["normalization_methods"])
        candidates.append(candidate)
    candidates.sort(
        key=lambda item: (
            not item["forced_candidate"],
            -int(item["district_count"]),
            str(item["canonical_name"]).casefold(),
        )
    )
    return candidates[:limit] if limit is not None else candidates


def resolve_family_id(connection: duckdb.DuckDBPyConnection, query: str) -> str:
    direct = connection.execute(
        """
        SELECT family_id FROM product_families
        WHERE family_id = ? OR lower(canonical_name) = lower(?)
        LIMIT 1
        """,
        [query, query],
    ).fetchone()
    if direct is not None:
        return str(direct[0])
    alias = connection.execute(
        "SELECT family_id FROM product_aliases WHERE alias_normalized = ? LIMIT 1",
        [normalize_text(query)],
    ).fetchone()
    if alias is not None:
        return str(alias[0])
    raise LookupError(f"unknown product family or alias: {query}")


def get_features(
    connection: duckdb.DuckDBPyConnection,
    family_id: str,
) -> dict[str, MetricValue]:
    record = connection.execute(
        f"SELECT {', '.join(FEATURE_COLUMNS)} FROM feature_values WHERE family_id = ?",
        [family_id],
    ).fetchone()
    if record is None:
        return dict.fromkeys(FEATURE_COLUMNS)
    return dict(zip(FEATURE_COLUMNS, record, strict=True))


def upsert_features(
    connection: duckdb.DuckDBPyConnection,
    family_id: str,
    features: Mapping[str, MetricValue],
    *,
    evidence: Mapping[str, Any] | None = None,
    observed_at: datetime | None = None,
) -> None:
    unknown = set(features) - set(FEATURE_COLUMNS)
    if unknown:
        raise ValueError(f"unknown feature columns: {sorted(unknown)}")
    existing = get_features(connection, family_id)
    existing.update(features)
    values = [existing[name] for name in FEATURE_COLUMNS]
    placeholders = ", ".join("?" for _ in FEATURE_COLUMNS)
    updates = ", ".join(f"{name} = excluded.{name}" for name in FEATURE_COLUMNS)
    connection.execute(
        f"""
        INSERT INTO feature_values (
            family_id, {", ".join(FEATURE_COLUMNS)}, evidence_json, observed_at, updated_at
        ) VALUES (?, {placeholders}, ?, ?, ?)
        ON CONFLICT (family_id) DO UPDATE SET
            {updates},
            evidence_json = excluded.evidence_json,
            observed_at = excluded.observed_at,
            updated_at = excluded.updated_at
        """,
        [
            family_id,
            *values,
            json.dumps(evidence or {}, sort_keys=True),
            observed_at,
            datetime.now(UTC),
        ],
    )


def store_score(connection: duckdb.DuckDBPyConnection, score: ScoreResult) -> None:
    connection.execute(
        """
        INSERT INTO opportunity_scores VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (score_id) DO UPDATE SET scored_at = excluded.scored_at
        """,
        [
            score.score_id,
            score.family_id,
            json.dumps(score.component_scores, sort_keys=True),
            json.dumps(score.missing_metrics),
            score.raw_score,
            score.overall_score,
            score.evidence_coverage,
            score.confidence_band,
            score.score_status,
            score.score_version,
            score.scoring_config_sha256,
            score.scored_at,
        ],
    )


def store_market_evidence(
    connection: duckdb.DuckDBPyConnection,
    evidence: Iterable[EvidenceItem],
    signals: Iterable[MarketSignal],
) -> tuple[int, int]:
    evidence_items = list(evidence)
    market_signals = list(signals)
    now = datetime.now(UTC)
    if evidence_items:
        connection.executemany(
            """
            INSERT INTO evidence_items VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (evidence_id) DO NOTHING
            """,
            [
                [
                    item.evidence_id,
                    item.family_id,
                    item.claim_class,
                    item.source_title,
                    item.source_url,
                    item.source_type,
                    item.locator,
                    item.retrieval_date,
                    item.observed_at,
                    item.collection_method,
                    item.acceptance_state,
                    item.content_sha256,
                    item.notes,
                    json.dumps(item.payload, sort_keys=True),
                    now,
                ]
                for item in evidence_items
            ],
        )
    if market_signals:
        connection.executemany(
            """
            INSERT INTO market_signals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (signal_id) DO NOTHING
            """,
            [
                [
                    signal.signal_id,
                    signal.family_id,
                    signal.metric,
                    signal.value_decimal,
                    signal.value_text,
                    signal.unit,
                    json.dumps(signal.evidence_ids),
                    signal.observed_at,
                    signal.acceptance_state,
                    signal.provider_version,
                    signal.request_hash,
                    now,
                ]
                for signal in market_signals
            ],
        )
    return len(evidence_items), len(market_signals)


def store_validator_findings(
    connection: duckdb.DuckDBPyConnection,
    score_id: str,
    findings: Iterable[ValidatorFinding],
) -> int:
    materialized = list(findings)
    now = datetime.now(UTC)
    if materialized:
        connection.executemany(
            """
            INSERT INTO validator_findings VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (finding_id) DO NOTHING
            """,
            [
                [
                    finding.finding_id,
                    finding.family_id,
                    score_id,
                    finding.severity,
                    finding.status,
                    finding.title,
                    finding.strongest_case,
                    json.dumps(finding.affected_features),
                    json.dumps(finding.evidence_ids),
                    finding.recommended_action,
                    now,
                ]
                for finding in materialized
            ],
        )
    return len(materialized)


def store_decision(
    connection: duckdb.DuckDBPyConnection,
    *,
    family_id: str,
    score_id: str,
    decision: DecisionResult,
    validator_verdict: ValidatorVerdict,
    evidence_packet_sha256: str,
    gate_config: DecisionGateConfig,
) -> str:
    canonical = json.dumps(
        {
            "family_id": family_id,
            "score_id": score_id,
            "gate": decision.gate,
            "validator_verdict": validator_verdict,
            "evidence_packet_sha256": evidence_packet_sha256,
            "gate_config_sha256": gate_config.sha256,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    decision_id = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    connection.execute(
        """
        INSERT INTO decision_records VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (decision_id) DO NOTHING
        """,
        [
            decision_id,
            family_id,
            score_id,
            decision.gate,
            decision.research_only,
            validator_verdict,
            json.dumps(decision.reasons),
            decision.max_recommended_spend_usd,
            evidence_packet_sha256,
            gate_config.sha256,
            datetime.now(UTC),
        ],
    )
    return decision_id


def store_agent_runs(
    connection: duckdb.DuckDBPyConnection,
    family_id: str,
    runs: Iterable[Mapping[str, Any]],
) -> int:
    materialized = list(runs)
    now = datetime.now(UTC)
    for item in materialized:
        connection.execute(
            """
            INSERT INTO agent_runs (
                run_id, family_id, agent, model, route, started_at, ended_at, duration_ms,
                cost_amount, cost_currency, cost_state, output_artifact, status, created_at,
                requested_profile, resolved_profile, provider, service_class, input_tokens,
                output_tokens, token_state, input_sha256, output_sha256, evidence_refs_json,
                error_class, registry_sha256, contract_version
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?
            )
            ON CONFLICT (run_id) DO NOTHING
            """,
            [
                str(item["run_id"]),
                family_id,
                str(item["agent"]),
                item.get("model"),
                item.get("route"),
                item.get("started_at"),
                item.get("ended_at"),
                item.get("duration_ms"),
                item.get("cost_amount"),
                item.get("cost_currency"),
                str(item["cost_state"]),
                item.get("output_artifact"),
                str(item["status"]),
                now,
                item.get("requested_profile"),
                item.get("resolved_profile"),
                item.get("provider"),
                item.get("service_class"),
                item.get("input_tokens"),
                item.get("output_tokens"),
                str(item.get("token_state", "UNKNOWN")),
                item.get("input_sha256"),
                item.get("output_sha256"),
                json.dumps(item.get("evidence_refs", [])),
                item.get("error_class"),
                item.get("registry_sha256"),
                item.get("contract_version"),
            ],
        )
    return len(materialized)


def store_role_chain_run(
    connection: duckdb.DuckDBPyConnection,
    record: Mapping[str, Any],
) -> None:
    connection.execute(
        """
        INSERT INTO role_chain_runs VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        ) ON CONFLICT (chain_run_id) DO NOTHING
        """,
        [
            record["chain_run_id"],
            record["family_id"],
            record["evidence_packet_sha256"],
            record["routing_config_sha256"],
            record.get("registry_sha256"),
            record["started_at"],
            record["ended_at"],
            record["duration_ms"],
            record["run_status"],
            record.get("blocked_reason"),
            record["score_id"],
            record.get("overall_score"),
            record["evidence_coverage"],
            record.get("validator_verdict"),
            record.get("decision_gate"),
            record["validator_independence_verified"],
            record["orchestration_verified"],
            record["accepted_evidence_count"],
            record["populated_metric_count"],
            record["null_metric_count"],
            record.get("total_cost_amount"),
            record.get("cost_currency"),
            record["cost_state"],
            record["artifact_directory"],
            record["benchmark_artifact"],
            datetime.now(UTC),
        ],
    )


def product_record(connection: duckdb.DuckDBPyConnection, family_id: str) -> dict[str, Any]:
    candidate = next(
        (item for item in candidate_records(connection) if item["family_id"] == family_id),
        None,
    )
    if candidate is None:
        raise LookupError(f"unknown family: {family_id}")
    candidate["currently_known_market_metrics"] = get_features(connection, family_id)
    return candidate


def latest_scores(connection: duckdb.DuckDBPyConnection) -> dict[str, dict[str, Any]]:
    records = connection.execute(
        """
        SELECT family_id, component_scores_json, missing_metrics_json, raw_score, overall_score,
               evidence_coverage, confidence_band, score_status, score_version,
               scoring_config_sha256, scored_at
        FROM (
            SELECT *, row_number() OVER (PARTITION BY family_id ORDER BY scored_at DESC) AS row_num
            FROM opportunity_scores
        ) ranked
        WHERE row_num = 1
        """
    ).fetchall()
    result: dict[str, dict[str, Any]] = {}
    for record in records:
        result[str(record[0])] = {
            "component_scores": json.loads(record[1]),
            "missing_metrics": json.loads(record[2]),
            "raw_score": record[3],
            "overall_score": record[4],
            "evidence_coverage": record[5],
            "confidence_band": record[6],
            "score_status": record[7],
            "score_version": record[8],
            "scoring_config_sha256": record[9],
            "scored_at": record[10],
        }
    return result


def report_records(
    connection: duckdb.DuckDBPyConnection,
    *,
    limit: int,
) -> list[dict[str, Any]]:
    scores = latest_scores(connection)
    records: list[dict[str, Any]] = []
    for candidate in candidate_records(connection):
        summary = {key: value for key, value in candidate.items() if key != "provenance"}
        summary["score"] = scores.get(candidate["family_id"])
        records.append(summary)
    records.sort(
        key=lambda item: (
            item["score"] is None,
            -(
                float(item["score"]["overall_score"])
                if item["score"] and item["score"]["overall_score"] is not None
                else -1.0
            ),
            not item["forced_candidate"],
            str(item["canonical_name"]).casefold(),
        )
    )
    return records[:limit]


def score_as_dict(score: ScoreResult) -> dict[str, Any]:
    return asdict(score)
