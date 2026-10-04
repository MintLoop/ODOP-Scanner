from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from odop_scanner.config import load_decision_gates, load_scoring
from odop_scanner.models import EconomicsScenario, EvidenceItem, MarketSignal
from odop_scanner.opportunity import calculate_economics, decide_gate, load_evidence_packet
from odop_scanner.scoring import calculate_score
from odop_scanner.storage import connect_database, store_market_evidence


def test_economics_calculates_landed_cost_contribution_and_break_even_cac() -> None:
    result = calculate_economics(
        EconomicsScenario(
            name="BASE",
            units_per_order=4,
            retail_price_usd=27.96,
            factory_cost_per_unit_usd=1.10,
            packaging_per_unit_usd=0.40,
            freight_per_unit_usd=0.30,
            duty_per_unit_usd=0.31,
            import_overhead_per_unit_usd=0.14,
            fulfillment_per_order_usd=8.00,
            payment_rate=0.029,
            payment_fixed_usd=0.30,
            evidence_ids=("ev-1",),
            assumption_notes=("sensitivity assumption",),
        )
    )

    assert result.landed_cogs_per_unit_usd == 2.25
    assert result.landed_cogs_per_order_usd == 9.00
    assert result.payment_fees_usd == 1.11
    assert result.contribution_before_cac_usd == 9.85
    assert result.break_even_cac_usd == 9.85
    assert result.contribution_margin_percent == 35.2


def test_missing_evidence_with_cheap_experiment_is_test_not_build() -> None:
    score = calculate_score(
        "product-001", {}, load_scoring(), scored_at=datetime(2026, 10, 3, tzinfo=UTC)
    )
    decision = decide_gate(
        score,
        load_decision_gates(),
        validator_verdict="REJECT",
        verified_hard_blockers=(),
        unresolved_critical_findings=("vf-1",),
        proposed_test_spend_usd=150.0,
    )

    assert decision.gate == "TEST"
    assert decision.research_only is True
    assert decision.max_recommended_spend_usd == 150.0
    assert any("coverage" in reason for reason in decision.reasons)


def test_verified_hard_blocker_kills_before_score_gate() -> None:
    score = calculate_score("product-001", {}, load_scoring())
    decision = decide_gate(
        score,
        load_decision_gates(),
        validator_verdict="UNKNOWN",
        verified_hard_blockers=("inadmissible product form",),
        unresolved_critical_findings=(),
        proposed_test_spend_usd=25.0,
    )

    assert decision.gate == "KILL"
    assert decision.max_recommended_spend_usd == 0.0


def test_numeric_feature_requires_formula_and_evidence(tmp_path: Path) -> None:
    feature_names = [dimension.name for dimension in load_scoring().dimensions]
    packet = {
        "version": "test-v1",
        "product_family_id": "product-001",
        "product_name": "makhana",
        "retrieval_date": "2026-10-03",
        "scope": {},
        "evidence": [],
        "signals": [],
        "normalized_features": {
            name: {
                "value": 50.0 if name == "demand" else None,
                "formula_version": None,
                "evidence_ids": [],
                "missing_reason": "" if name == "demand" else "not measured",
            }
            for name in feature_names
        },
        "economics": {"basis": "test", "scenarios": []},
        "card": {},
        "agent_runs": [],
    }
    path = tmp_path / "packet.json"
    path.write_text(json.dumps(packet), encoding="utf-8")

    with pytest.raises(ValueError, match="requires a formula version"):
        load_evidence_packet(path)


def test_market_evidence_and_signal_are_persisted(tmp_path: Path) -> None:
    connection = connect_database(tmp_path / "evidence.duckdb")
    evidence = EvidenceItem(
        evidence_id="ev-1",
        family_id="product-001",
        claim_class="OBSERVATION",
        source_title="Example",
        source_url="https://example.com/evidence",
        source_type="test",
        locator="line 1",
        retrieval_date=date(2026, 10, 3),
        observed_at=date(2026, 10, 3),
        collection_method="fixture",
        acceptance_state="accepted",
        content_sha256="abc",
        notes="",
        payload={"count": 1},
    )
    signal = MarketSignal(
        signal_id="signal-1",
        family_id="product-001",
        metric="listing_count",
        value_decimal=1.0,
        value_text=None,
        unit="listings",
        evidence_ids=("ev-1",),
        observed_at=date(2026, 10, 3),
        acceptance_state="accepted",
        provider_version="fixture-v1",
        request_hash="request-1",
    )

    assert store_market_evidence(connection, (evidence,), (signal,)) == (1, 1)
    assert connection.execute("SELECT count(*) FROM evidence_items").fetchone() == (1,)
    assert connection.execute("SELECT count(*) FROM market_signals").fetchone() == (1,)
    connection.close()
