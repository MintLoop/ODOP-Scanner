from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal

MetricValue = float | None
NormalizationStatus = Literal["normalized", "review_required"]
ParseStatus = Literal["parsed", "malformed"]
ConfidenceBand = Literal["none", "low", "medium", "high"]
ScoreStatus = Literal["unscored", "partial", "scored"]
CountChange = Literal["baseline", "unchanged", "changed", "unknown"]
ReconciliationStatus = Literal["same", "changed", "added", "removed", "ambiguous"]
HumanReviewStatus = Literal["not_required", "pending", "reviewed", "ambiguous"]
ReviewDecision = Literal["keep_2024", "accept_newer", "mark_same", "defer_ambiguous"]
ClaimClass = Literal["HYPOTHESIS", "INFERENCE", "OBSERVATION", "VERIFIED_FINDING"]
AcceptanceState = Literal["accepted", "unverified", "rejected"]
ValidatorVerdict = Literal["PASS", "REJECT", "UNKNOWN"]
DecisionGate = Literal["BUILD", "TEST", "WATCH", "KILL"]


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
class ReconciliationSourceSpec:
    source_version: str
    role: Literal["baseline", "lok_sabha", "annual_report"]
    name: str
    url: str
    source_date: date
    expected_sha256: str
    expected_rows: int
    expected_malformed_rows: int
    page_start: int | None = None
    page_end: int | None = None


@dataclass(frozen=True)
class ReconciliationConfig:
    version: str
    sha256: str
    baseline_source_version: str
    sources: tuple[ReconciliationSourceSpec, ...]


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
class ReconciliationDataset:
    source_version: str
    document: SourceDocument
    rows: tuple[ParsedRow, ...]


@dataclass(frozen=True)
class ReconciliationDiff:
    diff_id: str
    comparison_id: str
    comparison_version: str
    baseline_source_version: str
    newer_source_version: str
    baseline_source_sha256: str
    newer_source_sha256: str
    state: str
    district: str
    baseline_product: str | None
    newer_product: str | None
    baseline_row_ids: tuple[str, ...]
    newer_row_ids: tuple[str, ...]
    baseline_locators: tuple[str, ...]
    newer_locators: tuple[str, ...]
    conflict_type: str
    proposed_status: ReconciliationStatus
    human_review_status: HumanReviewStatus


@dataclass(frozen=True)
class ReconciliationResult:
    comparison_id: str
    comparison_version: str
    config_sha256: str
    baseline_source_version: str
    newer_source_version: str
    baseline_source_sha256: str
    newer_source_sha256: str
    diffs: tuple[ReconciliationDiff, ...]


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


@dataclass(frozen=True)
class EvidenceItem:
    evidence_id: str
    family_id: str
    claim_class: ClaimClass
    source_title: str
    source_url: str
    source_type: str
    locator: str
    retrieval_date: date
    observed_at: date | None
    collection_method: str
    acceptance_state: AcceptanceState
    content_sha256: str
    notes: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class MarketSignal:
    signal_id: str
    family_id: str
    metric: str
    value_decimal: float | None
    value_text: str | None
    unit: str | None
    evidence_ids: tuple[str, ...]
    observed_at: date
    acceptance_state: AcceptanceState
    provider_version: str
    request_hash: str


@dataclass(frozen=True)
class EconomicsScenario:
    name: str
    units_per_order: int
    retail_price_usd: float
    factory_cost_per_unit_usd: float
    packaging_per_unit_usd: float
    freight_per_unit_usd: float
    duty_per_unit_usd: float
    import_overhead_per_unit_usd: float
    fulfillment_per_order_usd: float
    payment_rate: float
    payment_fixed_usd: float
    evidence_ids: tuple[str, ...]
    assumption_notes: tuple[str, ...]


@dataclass(frozen=True)
class EconomicsResult:
    name: str
    units_per_order: int
    retail_price_usd: float
    landed_cogs_per_unit_usd: float
    landed_cogs_per_order_usd: float
    gross_margin_percent: float
    fulfillment_per_order_usd: float
    payment_fees_usd: float
    contribution_before_cac_usd: float
    contribution_margin_percent: float
    break_even_cac_usd: float


@dataclass(frozen=True)
class ValidatorFinding:
    finding_id: str
    family_id: str
    severity: Literal["low", "medium", "high", "critical"]
    status: Literal["open", "resolved"]
    title: str
    strongest_case: str
    affected_features: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    recommended_action: str


@dataclass(frozen=True)
class DecisionGateConfig:
    version: str
    sha256: str
    research_only: bool
    build_min_overall_score: float
    build_min_evidence_coverage: float
    build_confidence_bands: tuple[ConfidenceBand, ...]
    max_test_spend_usd: float


@dataclass(frozen=True)
class DecisionResult:
    gate: DecisionGate
    research_only: bool
    reasons: tuple[str, ...]
    max_recommended_spend_usd: float
