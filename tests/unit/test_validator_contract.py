from __future__ import annotations

from copy import deepcopy

import pytest

from odop_scanner.agents.contracts import (
    ContractError,
    assert_validator_repair_preserves_semantics,
    build_role_prompt,
    load_schema,
    parse_structured_response,
    role_validation_errors,
    validate_role_output,
)
from odop_scanner.config import project_root

SCHEMA = load_schema(project_root() / "schemas" / "validator-output.schema.json")
EVIDENCE_IDS = {"known-evidence-id"}


def _valid_artifact() -> dict[str, object]:
    return {
        "contract_version": "validator-output-v1",
        "role": "Validator",
        "product_family_id": "product-001",
        "status": "SUCCESS",
        "verdict": "REJECT",
        "strongest_case_against_promotion": "Demand is not decision-grade.",
        "findings": [
            {
                "finding_id": "vf-1",
                "severity": "high",
                "status": "open",
                "title": "Demand remains unknown",
                "strongest_case": "Listings do not establish demand.",
                "affected_features": ["demand"],
                "evidence_ids": ["known-evidence-id"],
                "recommended_action": "Run a bounded demand test.",
            }
        ],
        "unresolved": ["Demand remains unknown."],
    }


def _errors(artifact: dict[str, object]) -> tuple[str, ...]:
    return role_validation_errors(
        role="validator",
        artifact=artifact,
        schema=SCHEMA,
        product_family_id="product-001",
        evidence_ids=EVIDENCE_IDS,
    )


def test_valid_validator_artifact_passes() -> None:
    validate_role_output(
        role="validator",
        artifact=_valid_artifact(),
        schema=SCHEMA,
        product_family_id="product-001",
        evidence_ids=EVIDENCE_IDS,
    )


@pytest.mark.parametrize(
    "response",
    [
        '{"contract_version":',
        'Here is the JSON: {"contract_version": "validator-output-v1"}',
    ],
)
def test_malformed_json_and_extra_prose_are_rejected(response: str) -> None:
    with pytest.raises(ContractError, match="not JSON"):
        parse_structured_response(response)


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("misspelled_key", "contract_contract_version"),
        ("unknown_top_level", "unknown_top_level"),
        ("invalid_enum", "INVALID"),
        ("unknown_evidence", "unknown evidence"),
        ("missing_required", "required property"),
    ],
)
def test_validator_contract_rejects_invalid_shapes(mutation: str, expected: str) -> None:
    artifact = deepcopy(_valid_artifact())
    if mutation == "misspelled_key":
        artifact["contract_contract_version"] = artifact.pop("contract_version")
    elif mutation == "unknown_top_level":
        artifact["unknown_top_level"] = True
    elif mutation == "invalid_enum":
        artifact["verdict"] = "INVALID"
    elif mutation == "unknown_evidence":
        artifact["findings"][0]["evidence_ids"] = ["unknown-id"]  # type: ignore[index]
    elif mutation == "missing_required":
        artifact.pop("verdict")

    assert any(expected in error for error in _errors(artifact))


def test_validator_prompt_enumerates_exact_keys_enums_and_evidence_ids() -> None:
    prompt = build_role_prompt(
        "Validator",
        SCHEMA,
        {"product_family_id": "product-001"},
        known_evidence_ids=EVIDENCE_IDS,
    )

    assert '"finding_id"' in prompt
    assert '"PASS", "REJECT", "UNKNOWN"' in prompt
    assert '"low", "medium", "high", "critical"' in prompt
    assert '"known-evidence-id"' in prompt
    assert "Unknown keys and unknown evidence IDs cause rejection" in prompt


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("status", "BLOCKED"),
        ("verdict", "PASS"),
        ("product_family_id", "product-002"),
    ],
)
def test_validator_repair_cannot_change_top_level_semantics(
    field: str,
    replacement: str,
) -> None:
    initial = _valid_artifact()
    repaired = deepcopy(initial)
    repaired[field] = replacement

    with pytest.raises(ContractError, match=f"changed semantic field {field}"):
        assert_validator_repair_preserves_semantics(initial, repaired)


def test_validator_repair_rejects_ambiguous_key_normalization() -> None:
    initial = _valid_artifact()
    initial["VERDICT"] = initial["verdict"]

    with pytest.raises(ContractError, match="ambiguous keys for verdict"):
        assert_validator_repair_preserves_semantics(initial, deepcopy(initial))
