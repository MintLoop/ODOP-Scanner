from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any, cast

from .models import (
    AcceptanceState,
    ClaimClass,
    DecisionGateConfig,
    DecisionResult,
    EconomicsResult,
    EconomicsScenario,
    EvidenceItem,
    MarketSignal,
    MetricValue,
    ScoreResult,
    ValidatorFinding,
    ValidatorVerdict,
)

PACKET_KEYS = {
    "version",
    "product_family_id",
    "product_name",
    "retrieval_date",
    "scope",
    "evidence",
    "signals",
    "normalized_features",
    "economics",
    "card",
    "agent_runs",
}
FEATURE_NAMES = {
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
}
CLAIM_CLASSES = {"HYPOTHESIS", "INFERENCE", "OBSERVATION", "VERIFIED_FINDING"}
ACCEPTANCE_STATES = {"accepted", "unverified", "rejected"}
CARD_KEYS = {
    "executive_summary",
    "market",
    "demand",
    "competition",
    "supply",
    "regulatory_friction",
    "product",
    "brandability",
    "content_potential",
    "top_unknowns",
    "top_risks",
    "cheapest_next_experiment",
    "max_recommended_spend_usd",
    "verified_hard_blockers",
}


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def load_evidence_packet(path: Path) -> dict[str, Any]:
    packet = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(packet, dict):
        raise ValueError("evidence packet must be a JSON object")
    unknown = set(packet) - PACKET_KEYS
    missing = PACKET_KEYS - set(packet)
    if unknown or missing:
        raise ValueError(
            f"evidence packet fields differ from contract; missing={sorted(missing)}, "
            f"unknown={sorted(unknown)}"
        )
    if (
        not str(packet["version"]).strip()
        or not str(packet["product_family_id"]).strip()
        or not str(packet["product_name"]).strip()
    ):
        raise ValueError("evidence packet requires version, product_family_id, and product_name")
    date.fromisoformat(str(packet["retrieval_date"]))
    if not isinstance(packet["scope"], dict):
        raise ValueError("scope must be an object")
    _validate_packet_ids(packet)
    _validate_features(packet)
    _validate_economics(packet)
    _validate_card(packet)
    _validate_agent_runs(packet)
    return packet


def _validate_packet_ids(packet: Mapping[str, Any]) -> None:
    evidence = packet["evidence"]
    signals = packet["signals"]
    if not isinstance(evidence, list) or not isinstance(signals, list):
        raise ValueError("evidence and signals must be arrays")
    evidence_ids = [str(item["evidence_id"]) for item in evidence]
    signal_ids = [str(item["signal_id"]) for item in signals]
    if len(evidence_ids) != len(set(evidence_ids)):
        raise ValueError("evidence IDs must be unique")
    if len(signal_ids) != len(set(signal_ids)):
        raise ValueError("signal IDs must be unique")
    known_evidence = set(evidence_ids)
    for item in evidence:
        if not str(item["source_url"]).startswith("https://"):
            raise ValueError("evidence source URLs must use https")
        if item["claim_class"] not in CLAIM_CLASSES:
            raise ValueError(f"evidence {item['evidence_id']} has an invalid claim class")
        if item["acceptance_state"] not in ACCEPTANCE_STATES:
            raise ValueError(f"evidence {item['evidence_id']} has an invalid acceptance state")
        if not isinstance(item.get("payload"), dict):
            raise ValueError(f"evidence {item['evidence_id']} payload must be an object")
        date.fromisoformat(str(item["retrieval_date"]))
    for signal in signals:
        referenced = {str(value) for value in signal.get("evidence_ids", [])}
        if not referenced or not referenced.issubset(known_evidence):
            raise ValueError(f"signal {signal['signal_id']} has missing evidence references")
        if signal["acceptance_state"] not in ACCEPTANCE_STATES:
            raise ValueError(f"signal {signal['signal_id']} has an invalid acceptance state")
        if signal.get("value_decimal") is None and signal.get("value_text") is None:
            raise ValueError(f"signal {signal['signal_id']} requires a value")
        date.fromisoformat(str(signal["observed_at"]))


def _validate_features(packet: Mapping[str, Any]) -> None:
    features = packet["normalized_features"]
    if not isinstance(features, dict) or set(features) != FEATURE_NAMES:
        raise ValueError("normalized_features must declare exactly the configured feature names")
    known_evidence = {str(item["evidence_id"]) for item in packet["evidence"]}
    for name, item in features.items():
        if not isinstance(item, dict) or set(item) != {
            "value",
            "formula_version",
            "evidence_ids",
            "missing_reason",
        }:
            raise ValueError(f"feature {name} does not match the feature contract")
        value = item["value"]
        if value is None:
            if not str(item["missing_reason"]).strip():
                raise ValueError(f"missing feature {name} requires a reason")
            if item["formula_version"] is not None or item["evidence_ids"]:
                raise ValueError(f"missing feature {name} cannot claim a formula or evidence cut")
            continue
        numeric = float(value)
        if not 0 <= numeric <= 100:
            raise ValueError(f"feature {name} must be between 0 and 100")
        if not str(item["formula_version"] or "").strip():
            raise ValueError(f"numeric feature {name} requires a formula version")
        references = {str(value) for value in item["evidence_ids"]}
        if not references or not references.issubset(known_evidence):
            raise ValueError(f"numeric feature {name} requires known evidence IDs")


def _validate_economics(packet: Mapping[str, Any]) -> None:
    economics = packet["economics"]
    if not isinstance(economics, dict) or set(economics) != {"basis", "scenarios"}:
        raise ValueError("economics must declare basis and scenarios")
    if not str(economics["basis"]).strip() or not isinstance(economics["scenarios"], list):
        raise ValueError("economics requires a basis and scenario array")
    known_evidence = {str(item["evidence_id"]) for item in packet["evidence"]}
    names: set[str] = set()
    for scenario in economics["scenarios"]:
        name = str(scenario["name"])
        if name in names:
            raise ValueError("economics scenario names must be unique")
        names.add(name)
        references = {str(value) for value in scenario["evidence_ids"]}
        if not references or not references.issubset(known_evidence):
            raise ValueError(f"economics scenario {name} requires known evidence IDs")
        if not scenario["assumption_notes"]:
            raise ValueError(f"economics scenario {name} requires assumption notes")


def _validate_card(packet: Mapping[str, Any]) -> None:
    card = packet["card"]
    if not isinstance(card, dict) or set(card) != CARD_KEYS:
        raise ValueError("card fields differ from contract")
    for key in ("top_unknowns", "top_risks"):
        values = card[key]
        if (
            not isinstance(values, list)
            or len(values) != 5
            or not all(str(value).strip() for value in values)
        ):
            raise ValueError(f"card {key} must contain exactly five non-empty values")
    if float(card["max_recommended_spend_usd"]) < 0:
        raise ValueError("card maximum recommended spend cannot be negative")


def _validate_agent_runs(packet: Mapping[str, Any]) -> None:
    runs = packet["agent_runs"]
    if not isinstance(runs, list):
        raise ValueError("agent_runs must be an array")
    run_ids = [str(item["run_id"]) for item in runs]
    if len(run_ids) != len(set(run_ids)):
        raise ValueError("agent run IDs must be unique")
    for item in runs:
        if item["cost_state"] not in {"KNOWN", "NONE", "UNKNOWN"}:
            raise ValueError(f"agent run {item['run_id']} has an invalid cost state")
        if item["status"] not in {"succeeded", "failed", "partial"}:
            raise ValueError(f"agent run {item['run_id']} has an invalid status")


def packet_features(packet: Mapping[str, Any]) -> dict[str, MetricValue]:
    return {
        name: (float(item["value"]) if item["value"] is not None else None)
        for name, item in packet["normalized_features"].items()
    }


def packet_evidence(packet: Mapping[str, Any]) -> tuple[EvidenceItem, ...]:
    family_id = str(packet["product_family_id"])
    items: list[EvidenceItem] = []
    for raw in packet["evidence"]:
        payload = cast(dict[str, Any], raw.get("payload", {}))
        supplied_hash = str(raw.get("content_sha256", ""))
        items.append(
            EvidenceItem(
                evidence_id=str(raw["evidence_id"]),
                family_id=family_id,
                claim_class=cast(ClaimClass, str(raw["claim_class"])),
                source_title=str(raw["source_title"]),
                source_url=str(raw["source_url"]),
                source_type=str(raw["source_type"]),
                locator=str(raw["locator"]),
                retrieval_date=date.fromisoformat(str(raw["retrieval_date"])),
                observed_at=(
                    date.fromisoformat(str(raw["observed_at"])) if raw.get("observed_at") else None
                ),
                collection_method=str(raw["collection_method"]),
                acceptance_state=cast(AcceptanceState, str(raw["acceptance_state"])),
                content_sha256=supplied_hash or _canonical_hash(payload),
                notes=str(raw.get("notes", "")),
                payload=payload,
            )
        )
    return tuple(items)


def packet_signals(packet: Mapping[str, Any]) -> tuple[MarketSignal, ...]:
    family_id = str(packet["product_family_id"])
    signals: list[MarketSignal] = []
    for raw in packet["signals"]:
        request = raw.get("request", {})
        signals.append(
            MarketSignal(
                signal_id=str(raw["signal_id"]),
                family_id=family_id,
                metric=str(raw["metric"]),
                value_decimal=(
                    float(raw["value_decimal"]) if raw.get("value_decimal") is not None else None
                ),
                value_text=str(raw["value_text"]) if raw.get("value_text") is not None else None,
                unit=str(raw["unit"]) if raw.get("unit") is not None else None,
                evidence_ids=tuple(str(value) for value in raw["evidence_ids"]),
                observed_at=date.fromisoformat(str(raw["observed_at"])),
                acceptance_state=cast(AcceptanceState, str(raw["acceptance_state"])),
                provider_version=str(raw["provider_version"]),
                request_hash=str(raw.get("request_hash") or _canonical_hash(request)),
            )
        )
    return tuple(signals)


def calculate_economics(scenario: EconomicsScenario) -> EconomicsResult:
    if scenario.units_per_order < 1 or scenario.retail_price_usd <= 0:
        raise ValueError("economics scenario requires positive units and retail price")
    monetary_values = (
        scenario.factory_cost_per_unit_usd,
        scenario.packaging_per_unit_usd,
        scenario.freight_per_unit_usd,
        scenario.duty_per_unit_usd,
        scenario.import_overhead_per_unit_usd,
        scenario.fulfillment_per_order_usd,
        scenario.payment_fixed_usd,
    )
    if any(value < 0 for value in monetary_values) or not 0 <= scenario.payment_rate <= 1:
        raise ValueError("economics costs must be non-negative and payment_rate must be 0-1")
    landed_unit = sum(monetary_values[:5])
    landed_order = landed_unit * scenario.units_per_order
    payment_fees = scenario.retail_price_usd * scenario.payment_rate + scenario.payment_fixed_usd
    contribution = (
        scenario.retail_price_usd - landed_order - scenario.fulfillment_per_order_usd - payment_fees
    )
    gross_margin = (scenario.retail_price_usd - landed_order) / scenario.retail_price_usd * 100
    contribution_margin = contribution / scenario.retail_price_usd * 100
    return EconomicsResult(
        name=scenario.name,
        units_per_order=scenario.units_per_order,
        retail_price_usd=round(scenario.retail_price_usd, 2),
        landed_cogs_per_unit_usd=round(landed_unit, 2),
        landed_cogs_per_order_usd=round(landed_order, 2),
        gross_margin_percent=round(gross_margin, 1),
        fulfillment_per_order_usd=round(scenario.fulfillment_per_order_usd, 2),
        payment_fees_usd=round(payment_fees, 2),
        contribution_before_cac_usd=round(contribution, 2),
        contribution_margin_percent=round(contribution_margin, 1),
        break_even_cac_usd=round(max(0.0, contribution), 2),
    )


def packet_economics(packet: Mapping[str, Any]) -> tuple[EconomicsResult, ...]:
    results: list[EconomicsResult] = []
    for raw in packet["economics"]["scenarios"]:
        results.append(
            calculate_economics(
                EconomicsScenario(
                    name=str(raw["name"]),
                    units_per_order=int(raw["units_per_order"]),
                    retail_price_usd=float(raw["retail_price_usd"]),
                    factory_cost_per_unit_usd=float(raw["factory_cost_per_unit_usd"]),
                    packaging_per_unit_usd=float(raw["packaging_per_unit_usd"]),
                    freight_per_unit_usd=float(raw["freight_per_unit_usd"]),
                    duty_per_unit_usd=float(raw["duty_per_unit_usd"]),
                    import_overhead_per_unit_usd=float(raw["import_overhead_per_unit_usd"]),
                    fulfillment_per_order_usd=float(raw["fulfillment_per_order_usd"]),
                    payment_rate=float(raw["payment_rate"]),
                    payment_fixed_usd=float(raw["payment_fixed_usd"]),
                    evidence_ids=tuple(str(value) for value in raw["evidence_ids"]),
                    assumption_notes=tuple(str(value) for value in raw["assumption_notes"]),
                )
            )
        )
    return tuple(results)


def load_validator_packet(path: Path, known_evidence_ids: set[str]) -> dict[str, Any]:
    packet = json.loads(path.read_text(encoding="utf-8"))
    required = {"version", "product_family_id", "verdict", "findings", "agent_run"}
    if not isinstance(packet, dict) or set(packet) != required:
        raise ValueError("validator packet fields differ from contract")
    if packet["verdict"] not in {"PASS", "REJECT", "UNKNOWN"}:
        raise ValueError("validator verdict must be PASS, REJECT, or UNKNOWN")
    finding_ids: set[str] = set()
    for finding in packet["findings"]:
        finding_id = str(finding["finding_id"])
        if finding_id in finding_ids:
            raise ValueError("validator finding IDs must be unique")
        finding_ids.add(finding_id)
        if finding["severity"] not in {"low", "medium", "high", "critical"}:
            raise ValueError(f"validator finding {finding_id} has invalid severity")
        if finding["status"] not in {"open", "resolved"}:
            raise ValueError(f"validator finding {finding_id} has invalid status")
        affected = {str(value) for value in finding["affected_features"]}
        if not affected or not affected.issubset(FEATURE_NAMES):
            raise ValueError(f"validator finding {finding_id} has invalid affected features")
        references = {str(value) for value in finding["evidence_ids"]}
        if not references or not references.issubset(known_evidence_ids):
            raise ValueError(f"validator finding {finding_id} cites unknown evidence")
    return packet


def validator_findings(packet: Mapping[str, Any]) -> tuple[ValidatorFinding, ...]:
    family_id = str(packet["product_family_id"])
    return tuple(
        ValidatorFinding(
            finding_id=str(raw["finding_id"]),
            family_id=family_id,
            severity=raw["severity"],
            status=raw["status"],
            title=str(raw["title"]),
            strongest_case=str(raw["strongest_case"]),
            affected_features=tuple(str(value) for value in raw["affected_features"]),
            evidence_ids=tuple(str(value) for value in raw["evidence_ids"]),
            recommended_action=str(raw["recommended_action"]),
        )
        for raw in packet["findings"]
    )


def decide_gate(
    score: ScoreResult,
    config: DecisionGateConfig,
    *,
    validator_verdict: ValidatorVerdict,
    verified_hard_blockers: tuple[str, ...],
    unresolved_critical_findings: tuple[str, ...],
    proposed_test_spend_usd: float,
) -> DecisionResult:
    if proposed_test_spend_usd < 0:
        raise ValueError("proposed test spend cannot be negative")
    if verified_hard_blockers:
        return DecisionResult(
            gate="KILL",
            research_only=config.research_only,
            reasons=tuple(f"verified hard blocker: {value}" for value in verified_hard_blockers),
            max_recommended_spend_usd=0.0,
        )
    build_reasons: list[str] = []
    if score.overall_score is None or score.overall_score < config.build_min_overall_score:
        build_reasons.append("overall score is absent or below the BUILD threshold")
    if score.evidence_coverage < config.build_min_evidence_coverage:
        build_reasons.append("evidence coverage is below the BUILD threshold")
    if score.confidence_band not in config.build_confidence_bands:
        build_reasons.append("confidence band does not permit BUILD")
    if validator_verdict != "PASS":
        build_reasons.append("independent validator did not PASS")
    if unresolved_critical_findings:
        build_reasons.append("critical validator findings remain open")
    if not build_reasons:
        return DecisionResult(
            gate="BUILD",
            research_only=config.research_only,
            reasons=("all configured BUILD gates passed",),
            max_recommended_spend_usd=proposed_test_spend_usd,
        )
    if proposed_test_spend_usd <= config.max_test_spend_usd:
        return DecisionResult(
            gate="TEST",
            research_only=config.research_only,
            reasons=tuple(build_reasons),
            max_recommended_spend_usd=round(proposed_test_spend_usd, 2),
        )
    return DecisionResult(
        gate="WATCH",
        research_only=config.research_only,
        reasons=tuple(build_reasons)
        + ("the proposed experiment exceeds the configured TEST spend ceiling",),
        max_recommended_spend_usd=0.0,
    )


def render_opportunity_card(
    packet: Mapping[str, Any],
    score: ScoreResult,
    economics: tuple[EconomicsResult, ...],
    validator_packet: Mapping[str, Any],
    decision: DecisionResult,
) -> str:
    card = packet["card"]
    title = str(packet["product_name"]).upper()
    lines = [
        f"# {title}",
        "",
        f"**Decision gate:** {decision.gate}",
        "",
        f"**Gate basis:** {'; '.join(decision.reasons)}.",
        "",
        str(card["executive_summary"]),
        "",
    ]
    for heading, key in (
        ("Market", "market"),
        ("Demand", "demand"),
        ("Competition", "competition"),
        ("Supply", "supply"),
        ("Regulatory friction", "regulatory_friction"),
        ("Product", "product"),
        ("Brandability", "brandability"),
        ("Content potential", "content_potential"),
    ):
        lines.extend([f"## {heading}", "", str(card[key]), ""])
    lines.extend(
        [
            "## Economics",
            "",
            f"Basis: {packet['economics']['basis']}",
            "",
            "| Scenario | Revenue | Landed COGS/unit | Landed COGS/order | Gross margin | "
            "Fulfillment | Payment fees | Contribution before CAC | Break-even CAC |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for result in economics:
        lines.append(
            f"| {result.name} | {_money(result.retail_price_usd)} | "
            f"{_money(result.landed_cogs_per_unit_usd)} | "
            f"{_money(result.landed_cogs_per_order_usd)} | "
            f"{result.gross_margin_percent:.1f}% | "
            f"{_money(result.fulfillment_per_order_usd)} | "
            f"{_money(result.payment_fees_usd)} | "
            f"{_money(result.contribution_before_cac_usd)} | "
            f"{_money(result.break_even_cac_usd)} |"
        )
    lines.extend(
        [
            "",
            "These are sensitivity scenarios, not supplier quotes. They are excluded from the "
            "margin score.",
            "",
            "## Deterministic score",
            "",
            "- Opportunity score: **"
            f"{score.overall_score if score.overall_score is not None else 'unscored'}**",
            f"- Evidence coverage: **{score.evidence_coverage:.1f}%**",
            "- Coverage counts accepted numeric scoring inputs, not collected source count.",
            f"- Confidence: **{score.confidence_band}**",
            f"- Missing metrics: {', '.join(score.missing_metrics) or 'none'}",
            f"- Score snapshot: `{score.score_id}`",
            f"- Validator verdict: **{validator_packet['verdict']}**",
            "",
            "## Strongest case against launch",
            "",
        ]
    )
    for finding in validator_packet["findings"]:
        lines.append(f"- **{finding['title']}:** {finding['strongest_case']}")
    lines.extend(["", "## Top 5 unknowns", ""])
    lines.extend(f"{index}. {value}" for index, value in enumerate(card["top_unknowns"], 1))
    lines.extend(["", "## Top 5 risks", ""])
    lines.extend(f"{index}. {value}" for index, value in enumerate(card["top_risks"], 1))
    lines.extend(
        [
            "",
            "## Next gate",
            "",
            f"- Cheapest next experiment: {card['cheapest_next_experiment']}",
            f"- Maximum recommended spend: **${decision.max_recommended_spend_usd:.2f}**",
            "- No bulk inventory, supplier outreach, importing, publication, or launch is "
            "authorized by this card.",
            "",
            "## Evidence index",
            "",
        ]
    )
    for item in packet["evidence"]:
        lines.append(
            f"- `{item['evidence_id']}` — [{item['source_title']}]({item['source_url']}) "
            f"({item['acceptance_state']}; retrieved {item['retrieval_date']})"
        )
    lines.extend(
        [
            "",
            f"_Evidence packet `{packet['version']}`; scoring config `{score.score_version}`; "
            f"gate config is research-only: {str(decision.research_only).lower()}._",
            "",
        ]
    )
    return "\n".join(lines)


def _money(value: float) -> str:
    prefix = "-" if value < 0 else ""
    return f"{prefix}${abs(value):.2f}"


def economics_as_dict(results: tuple[EconomicsResult, ...]) -> list[dict[str, Any]]:
    return [asdict(result) for result in results]
