from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Literal

MetricValue = float | None
NormalizationStatus = Literal["normalized", "review_required"]
ParseStatus = Literal["parsed", "malformed"]
ConfidenceBand = Literal["none", "low", "medium", "high"]
ScoreStatus = Literal["unscored", "partial", "scored"]
CountChange = Literal["baseline", "unchanged", "changed", "unknown"]


@dataclass(frozen=True)
class SourceSpec:
    source_id: str
    name: str
    url: str
    source_date: date
    format: str
    expected_rows: int | None = None
    expected_sections: int | None = None
    expected_sha256: str | None = None


@dataclass(frozen=True)
class FreshnessObservation:
    observation_id: str
    source_kind: str
    discovery_url: str
    source_url: str
    published_or_revised_date: date | None
    retrieval_date: date
    sha256: str | None
    supersedes_2024: bool | None
    row_count: int | None
    product_family_count: int | None
    row_count_change: CountChange
    product_family_count_change: CountChange
    disposition: str
    notes: str


@dataclass(frozen=True)
class SourceFreshnessConfig:
    version: str
    sha256: str
    checked_on: date
    selected_source_id: str
    freshness_status: str
    decision: str
    reason: str
    searched_surfaces: tuple[str, ...]
    observations: tuple[FreshnessObservation, ...]


@dataclass(frozen=True)
class SourceDocument:
    source_id: str
    source_name: str
    source_url: str | None
    source_date: date | None
    ingested_at: datetime
    content_sha256: str
    storage_path: Path
    media_type: str
    raw_text: str


@dataclass(frozen=True)
class ParsedRow:
    row_id: str
    source_id: str
    state: str
    district: str
    product: str
    source_page: int | None
    source_reference: str
    raw_text: str
    parse_status: ParseStatus
    parse_error: str | None
    ingested_at: datetime


@dataclass(frozen=True)
class TaxonomyFamily:
    product_id: str
    canonical_name: str
    category: str | None
    forced_candidate: bool
    aliases: tuple[str, ...]


@dataclass(frozen=True)
class TaxonomyConfig:
    version: str
    sha256: str
    families: tuple[TaxonomyFamily, ...]


@dataclass(frozen=True)
class DimensionConfig:
    name: str
    weight: float
    direction: Literal["positive", "negative"]


@dataclass(frozen=True)
class ScoringConfig:
    version: str
    sha256: str
    dimensions: tuple[DimensionConfig, ...]
    medium_min_coverage: float
    high_min_coverage: float


@dataclass(frozen=True)
class NormalizationDecision:
    normalized_id: str
    row_id: str
    family_id: str
    canonical_name: str
    category: str | None
    forced_candidate: bool
    normalized_name: str
    normalization_status: NormalizationStatus
    normalization_method: str
    normalization_version: str
    model_route: str | None
    observed_alias: str


@dataclass(frozen=True)
class ScoreResult:
    score_id: str
    family_id: str
    component_scores: dict[str, MetricValue]
    missing_metrics: tuple[str, ...]
    raw_score: float | None
    overall_score: float | None
    evidence_coverage: float
    confidence_band: ConfidenceBand
    score_status: ScoreStatus
    score_version: str
    scoring_config_sha256: str
    scored_at: datetime
