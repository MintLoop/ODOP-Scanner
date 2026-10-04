from __future__ import annotations

import hashlib
import tomllib
from datetime import date
from pathlib import Path
from typing import Any, Literal, cast

from .models import (
    ConfidenceBand,
    CountChange,
    DecisionGateConfig,
    DimensionConfig,
    FreshnessObservation,
    ReconciliationConfig,
    ReconciliationSourceSpec,
    ScoringConfig,
    SourceFreshnessConfig,
    SourceSpec,
    TaxonomyConfig,
    TaxonomyFamily,
)


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def config_path(name: str) -> Path:
    return project_root() / "config" / name


def _read_toml(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    return tomllib.loads(raw.decode("utf-8")), hashlib.sha256(raw).hexdigest()


def load_sources(path: Path | None = None) -> tuple[str, tuple[SourceSpec, ...]]:
    document, _ = _read_toml(path or config_path("sources.toml"))
    version = str(document.get("version", "")).strip()
    if not version:
        raise ValueError("source configuration requires a non-empty version")
    specs: list[SourceSpec] = []
    for item in document.get("sources", []):
        specs.append(
            SourceSpec(
                source_id=str(item["id"]),
                name=str(item["name"]),
                url=str(item["url"]),
                source_date=date.fromisoformat(str(item["source_date"])),
                format=str(item["format"]),
                expected_rows=int(item["expected_rows"]) if "expected_rows" in item else None,
                expected_sections=(
                    int(item["expected_sections"]) if "expected_sections" in item else None
                ),
                expected_sha256=(
                    str(item["expected_sha256"]) if item.get("expected_sha256") else None
                ),
            )
        )
    if not specs:
        raise ValueError("source configuration must declare at least one source")
    return version, tuple(specs)


def load_source_freshness(path: Path | None = None) -> SourceFreshnessConfig:
    document, digest = _read_toml(path or config_path("source_freshness.toml"))
    version = str(document.get("version", "")).strip()
    selection = document.get("selection", {})
    if not version or not selection:
        raise ValueError("source freshness configuration requires version and selection")

    observations: list[FreshnessObservation] = []
    valid_changes = {"baseline", "unchanged", "changed", "unknown"}
    for item in document.get("observations", []):
        row_change = str(item["row_count_change"])
        family_change = str(item["product_family_count_change"])
        if row_change not in valid_changes or family_change not in valid_changes:
            raise ValueError("freshness count changes must be baseline/unchanged/changed/unknown")
        observations.append(
            FreshnessObservation(
                observation_id=str(item["id"]),
                source_kind=str(item["source_kind"]),
                discovery_url=str(item["discovery_url"]),
                source_url=str(item["source_url"]),
                published_or_revised_date=(
                    date.fromisoformat(str(item["published_or_revised_date"]))
                    if item.get("published_or_revised_date")
                    else None
                ),
                retrieval_date=date.fromisoformat(str(item["retrieval_date"])),
                sha256=str(item["sha256"]) if item.get("sha256") else None,
                supersedes_2024=(
                    bool(item["supersedes_2024"]) if "supersedes_2024" in item else None
                ),
                row_count=int(item["row_count"]) if "row_count" in item else None,
                product_family_count=(
                    int(item["product_family_count"]) if "product_family_count" in item else None
                ),
                row_count_change=cast(CountChange, row_change),
                product_family_count_change=cast(CountChange, family_change),
                disposition=str(item["disposition"]),
                notes=str(item.get("notes", "")),
            )
        )
    if not observations:
        raise ValueError("source freshness configuration requires observations")

    selected_source_id = str(selection["selected_source_id"])
    if selected_source_id not in {item.observation_id for item in observations}:
        raise ValueError("selected freshness source must reference an observation")
    return SourceFreshnessConfig(
        version=version,
        sha256=digest,
        checked_on=date.fromisoformat(str(selection["checked_on"])),
        selected_source_id=selected_source_id,
        freshness_status=str(selection["freshness_status"]),
        decision=str(selection["decision"]),
        reason=str(selection["reason"]),
        searched_surfaces=tuple(str(value) for value in selection.get("searched_surfaces", [])),
        observations=tuple(observations),
    )


def load_reconciliation(path: Path | None = None) -> ReconciliationConfig:
    document, digest = _read_toml(path or config_path("reconciliation.v0.toml"))
    version = str(document.get("version", "")).strip()
    baseline_source_version = str(document.get("baseline_source_version", "")).strip()
    if not version or not baseline_source_version:
        raise ValueError("reconciliation configuration requires version and baseline source")

    valid_roles = {"baseline", "lok_sabha", "annual_report"}
    sources: list[ReconciliationSourceSpec] = []
    for item in document.get("sources", []):
        role = str(item["role"])
        if role not in valid_roles:
            raise ValueError(f"invalid reconciliation source role: {role}")
        sources.append(
            ReconciliationSourceSpec(
                source_version=str(item["source_version"]),
                role=cast(Literal["baseline", "lok_sabha", "annual_report"], role),
                name=str(item["name"]),
                url=str(item["url"]),
                source_date=date.fromisoformat(str(item["source_date"])),
                expected_sha256=str(item["expected_sha256"]),
                expected_rows=int(item["expected_rows"]),
                expected_malformed_rows=int(item.get("expected_malformed_rows", 0)),
                page_start=int(item["page_start"]) if "page_start" in item else None,
                page_end=int(item["page_end"]) if "page_end" in item else None,
            )
        )
    if len(sources) != 3 or {source.role for source in sources} != valid_roles:
        raise ValueError("reconciliation requires baseline, lok_sabha, and annual_report sources")
    if baseline_source_version not in {source.source_version for source in sources}:
        raise ValueError("reconciliation baseline must reference a configured source")
    if (
        next(source.role for source in sources if source.source_version == baseline_source_version)
        != "baseline"
    ):
        raise ValueError("reconciliation baseline source must have the baseline role")
    return ReconciliationConfig(
        version=version,
        sha256=digest,
        baseline_source_version=baseline_source_version,
        sources=tuple(sources),
    )


def load_taxonomy(path: Path | None = None) -> TaxonomyConfig:
    document, digest = _read_toml(path or config_path("taxonomy.toml"))
    version = str(document.get("version", "")).strip()
    if not version:
        raise ValueError("taxonomy configuration requires a non-empty version")
    families: list[TaxonomyFamily] = []
    product_ids: set[str] = set()
    canonical_names: set[str] = set()
    for item in document.get("families", []):
        product_id = str(item["product_id"]).strip()
        canonical_name = str(item["canonical_name"]).strip()
        if product_id in product_ids or canonical_name.casefold() in canonical_names:
            raise ValueError(f"duplicate taxonomy family: {product_id}/{canonical_name}")
        product_ids.add(product_id)
        canonical_names.add(canonical_name.casefold())
        families.append(
            TaxonomyFamily(
                product_id=product_id,
                canonical_name=canonical_name,
                category=str(item["category"]) if item.get("category") else None,
                forced_candidate=bool(item.get("forced_candidate", False)),
                aliases=tuple(str(alias) for alias in item.get("aliases", [])),
            )
        )
    return TaxonomyConfig(version=version, sha256=digest, families=tuple(families))


def load_scoring(path: Path | None = None) -> ScoringConfig:
    document, digest = _read_toml(path or config_path("scoring.v0.toml"))
    version = str(document.get("version", "")).strip()
    if not version:
        raise ValueError("scoring configuration requires a non-empty version")

    dimensions: list[DimensionConfig] = []
    for name, item in document.get("dimensions", {}).items():
        weight = float(item["weight"])
        direction = str(item["direction"])
        if weight <= 0:
            raise ValueError(f"dimension {name} weight must be positive")
        if direction not in {"positive", "negative"}:
            raise ValueError(f"dimension {name} has invalid direction {direction!r}")
        dimensions.append(
            DimensionConfig(
                name=str(name),
                weight=weight,
                direction=cast(Literal["positive", "negative"], direction),
            )
        )
    if not dimensions:
        raise ValueError("scoring configuration must declare dimensions")

    confidence = document.get("confidence", {})
    medium = float(confidence["medium_min_coverage"])
    high = float(confidence["high_min_coverage"])
    if not 0 <= medium <= high <= 1:
        raise ValueError("confidence coverage thresholds must satisfy 0 <= medium <= high <= 1")

    return ScoringConfig(
        version=version,
        sha256=digest,
        dimensions=tuple(dimensions),
        medium_min_coverage=medium,
        high_min_coverage=high,
    )


def load_decision_gates(path: Path | None = None) -> DecisionGateConfig:
    document, digest = _read_toml(path or config_path("decision_gates.v0.toml"))
    version = str(document.get("version", "")).strip()
    if not version:
        raise ValueError("decision gate configuration requires a non-empty version")
    build = document.get("build", {})
    test = document.get("test", {})
    bands = tuple(str(value) for value in build.get("allowed_confidence_bands", []))
    valid_bands = {"none", "low", "medium", "high"}
    if not bands or not set(bands).issubset(valid_bands):
        raise ValueError("decision gate confidence bands are invalid")
    min_score = float(build["min_overall_score"])
    min_coverage = float(build["min_evidence_coverage"])
    max_spend = float(test["max_spend_usd"])
    if not 0 <= min_score <= 100 or not 0 <= min_coverage <= 100:
        raise ValueError("decision gate score and coverage thresholds must be between 0 and 100")
    if max_spend < 0:
        raise ValueError("decision gate test spend cannot be negative")
    return DecisionGateConfig(
        version=version,
        sha256=digest,
        research_only=bool(document.get("research_only", True)),
        build_min_overall_score=min_score,
        build_min_evidence_coverage=min_coverage,
        build_confidence_bands=cast(tuple[ConfidenceBand, ...], bands),
        max_test_spend_usd=max_spend,
    )
