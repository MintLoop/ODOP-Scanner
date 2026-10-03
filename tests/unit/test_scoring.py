from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from odop_scanner.config import load_scoring
from odop_scanner.scoring import calculate_score


def test_missing_evidence_is_not_replaced_with_neutral_values() -> None:
    result = calculate_score("product-001", {}, load_scoring())

    assert result.raw_score is None
    assert result.overall_score is None
    assert result.evidence_coverage == 0
    assert result.confidence_band == "none"
    assert result.score_status == "unscored"
    assert len(result.missing_metrics) == 11


def test_weighted_evidence_coverage_and_score_are_reproducible() -> None:
    config = load_scoring()
    when = datetime(2026, 10, 3, tzinfo=UTC)
    first = calculate_score("product-001", {"demand": 80.0}, config, scored_at=when)
    second = calculate_score("product-001", {"demand": 80.0}, config, scored_at=when)

    assert first == second
    assert first.raw_score == 80.0
    assert first.evidence_coverage == 14.0
    assert first.overall_score == 11.2
    assert first.confidence_band == "low"


def test_regulatory_risk_is_a_negative_dimension() -> None:
    config = load_scoring()
    low_risk = calculate_score("product-001", {"regulatory_risk": 0.0}, config)
    high_risk = calculate_score("product-001", {"regulatory_risk": 100.0}, config)

    assert low_risk.raw_score == 100.0
    assert high_risk.raw_score == 0.0
    assert low_risk.overall_score is not None
    assert high_risk.overall_score is not None
    assert low_risk.overall_score > high_risk.overall_score


def test_score_rejects_out_of_range_values() -> None:
    with pytest.raises(ValueError, match="between 0 and 100"):
        calculate_score("product-001", {"demand": 101.0}, load_scoring())


def test_config_version_and_hash_are_part_of_result(tmp_path: Path) -> None:
    original = Path("config/scoring.v0.toml").read_text(encoding="utf-8")
    changed_path = tmp_path / "scoring.toml"
    changed_path.write_text(
        original.replace('version = "v0.1.0"', 'version = "v0.2.0"'), encoding="utf-8"
    )
    changed = load_scoring(changed_path)
    result = calculate_score("product-001", {"demand": 50.0}, changed)

    assert result.score_version == "v0.2.0"
    assert result.scoring_config_sha256 == changed.sha256
    assert changed.sha256 != load_scoring().sha256
