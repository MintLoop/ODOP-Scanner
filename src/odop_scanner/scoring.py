from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime

from .models import ConfidenceBand, MetricValue, ScoreResult, ScoreStatus, ScoringConfig


def _validate_metric(name: str, value: MetricValue) -> None:
    if value is not None and not 0 <= value <= 100:
        raise ValueError(f"metric {name} must be null or between 0 and 100, got {value}")


def calculate_score(
    family_id: str,
    features: Mapping[str, MetricValue],
    config: ScoringConfig,
    *,
    scored_at: datetime | None = None,
) -> ScoreResult:
    """Calculate a reproducible score without filling missing evidence.

    Feature values are already-normalized 0-100 inputs. Negative dimensions such as regulatory risk
    are inverted exactly once. The overall score is the available-metric raw score multiplied by
    weighted evidence coverage; absent metrics can never act as neutral defaults.
    """

    expected_names = {dimension.name for dimension in config.dimensions}
    unknown = set(features) - expected_names
    if unknown:
        raise ValueError(f"unknown scoring metrics: {sorted(unknown)}")

    components: dict[str, MetricValue] = {}
    expected_weight = sum(dimension.weight for dimension in config.dimensions)
    available_weight = 0.0
    contribution_total = 0.0

    for dimension in config.dimensions:
        value = features.get(dimension.name)
        _validate_metric(dimension.name, value)
        components[dimension.name] = value
        if value is None:
            continue
        available_weight += dimension.weight
        contribution = 100.0 - value if dimension.direction == "negative" else value
        contribution_total += contribution * dimension.weight

    coverage_fraction = available_weight / expected_weight
    evidence_coverage = round(coverage_fraction * 100.0, 4)
    missing = tuple(d.name for d in config.dimensions if components[d.name] is None)

    if available_weight == 0:
        raw_score = None
        overall_score = None
        confidence_band: ConfidenceBand = "none"
        status: ScoreStatus = "unscored"
    else:
        raw_score = round(contribution_total / available_weight, 4)
        overall_score = round(raw_score * coverage_fraction, 4)
        if coverage_fraction >= config.high_min_coverage:
            confidence_band = "high"
        elif coverage_fraction >= config.medium_min_coverage:
            confidence_band = "medium"
        else:
            confidence_band = "low"
        status = "scored" if not missing else "partial"

    canonical_input = json.dumps(
        {
            "family_id": family_id,
            "components": components,
            "config_sha256": config.sha256,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    score_id = hashlib.sha256(canonical_input.encode("utf-8")).hexdigest()

    return ScoreResult(
        score_id=score_id,
        family_id=family_id,
        component_scores=components,
        missing_metrics=missing,
        raw_score=raw_score,
        overall_score=overall_score,
        evidence_coverage=evidence_coverage,
        confidence_band=confidence_band,
        score_status=status,
        score_version=config.version,
        scoring_config_sha256=config.sha256,
        scored_at=scored_at or datetime.now(UTC),
    )
