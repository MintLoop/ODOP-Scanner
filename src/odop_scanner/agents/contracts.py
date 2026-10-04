from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from ..opportunity import FEATURE_NAMES


class ContractError(ValueError):
    """A role artifact is not valid for its declared contract."""


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_value(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def load_schema(path: Path) -> dict[str, Any]:
    schema = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(schema, dict):
        raise ContractError(f"schema is not an object: {path}")
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as error:
        raise ContractError(f"invalid JSON Schema {path}: {error.message}") from error
    return schema


def parse_structured_response(response: str) -> dict[str, Any]:
    text = response.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) < 3 or lines[-1].strip() != "```":
            raise ContractError("structured response has an unterminated code fence")
        if lines[0].strip() not in {"```", "```json"}:
            raise ContractError("structured response uses an unsupported code fence")
        text = "\n".join(lines[1:-1]).strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError as error:
        raise ContractError(f"structured response is not JSON: {error.msg}") from error
    if not isinstance(value, dict):
        raise ContractError("structured response must be one JSON object")
    return value


def validate_role_output(
    *,
    role: str,
    artifact: Mapping[str, Any],
    schema: Mapping[str, Any],
    product_family_id: str,
    evidence_ids: set[str],
    feature_states: Mapping[str, str] | None = None,
    scenario_names: tuple[str, ...] = (),
    deterministic_snapshot: Mapping[str, Any] | None = None,
) -> None:
    errors = role_validation_errors(
        role=role,
        artifact=artifact,
        schema=schema,
        product_family_id=product_family_id,
        evidence_ids=evidence_ids,
        feature_states=feature_states,
        scenario_names=scenario_names,
        deterministic_snapshot=deterministic_snapshot,
    )
    if errors:
        raise ContractError(" | ".join(errors))


def role_validation_errors(
    *,
    role: str,
    artifact: Mapping[str, Any],
    schema: Mapping[str, Any],
    product_family_id: str,
    evidence_ids: set[str],
    feature_states: Mapping[str, str] | None = None,
    scenario_names: tuple[str, ...] = (),
    deterministic_snapshot: Mapping[str, Any] | None = None,
) -> tuple[str, ...]:
    schema_errors = sorted(
        Draft202012Validator(schema).iter_errors(dict(artifact)),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if schema_errors:
        return tuple(
            f"{role} schema violation at "
            f"{'.'.join(str(part) for part in error.absolute_path) or '<root>'}: "
            f"{error.message}"
            for error in schema_errors
        )
    try:
        if artifact["product_family_id"] != product_family_id:
            raise ContractError(f"{role} output targets the wrong product family")
        if artifact["status"] != "SUCCESS":
            raise ContractError(f"{role} returned BLOCKED")

        if role == "scout":
            _validate_scout(artifact, evidence_ids)
        elif role == "analyst":
            _validate_analyst(
                artifact,
                evidence_ids,
                feature_states or {},
                scenario_names,
            )
        elif role == "validator":
            _validate_validator(artifact, evidence_ids)
        elif role == "synthesizer":
            if deterministic_snapshot is None:
                raise ContractError("Synthesizer validation requires a deterministic snapshot")
            _validate_synthesizer(artifact, evidence_ids, deterministic_snapshot)
        else:
            raise ContractError(f"unknown role contract: {role}")
    except ContractError as error:
        return (str(error),)
    return ()


def _validate_scout(artifact: Mapping[str, Any], evidence_ids: set[str]) -> None:
    assessments = artifact["evidence_assessment"]
    assessed_ids = [str(item["evidence_id"]) for item in assessments]
    if len(assessed_ids) != len(set(assessed_ids)):
        raise ContractError("Scout assessed an evidence item more than once")
    if set(assessed_ids) != evidence_ids:
        raise ContractError("Scout must assess every input evidence item exactly once")

    buckets = {
        "ACCEPTED": set(str(value) for value in artifact["accepted_evidence_ids"]),
        "REJECTED": set(str(value) for value in artifact["rejected_evidence_ids"]),
        "UNVERIFIED": set(str(value) for value in artifact["unverified_evidence_ids"]),
    }
    if set().union(*buckets.values()) != evidence_ids:
        raise ContractError("Scout disposition lists must cover every evidence item")
    if any(
        left & right
        for index, left in enumerate(buckets.values())
        for right in list(buckets.values())[index + 1 :]
    ):
        raise ContractError("Scout disposition lists must be disjoint")
    for item in assessments:
        if str(item["evidence_id"]) not in buckets[str(item["disposition"])]:
            raise ContractError("Scout assessment and disposition lists disagree")


def _validate_analyst(
    artifact: Mapping[str, Any],
    evidence_ids: set[str],
    feature_states: Mapping[str, str],
    scenario_names: tuple[str, ...],
) -> None:
    if set(feature_states) != FEATURE_NAMES:
        raise ContractError("deterministic feature state is incomplete")
    mapping = artifact["metric_mapping"]
    for name in FEATURE_NAMES:
        item = mapping[name]
        if item["state"] != feature_states[name]:
            raise ContractError(f"Analyst attempted to change deterministic state for {name}")
        references = {str(value) for value in item["evidence_ids"]}
        if not references.issubset(evidence_ids):
            raise ContractError(f"Analyst metric {name} cites unknown evidence")
        missing_reason = item["missing_reason"]
        if item["state"] == "MISSING" and not str(missing_reason or "").strip():
            raise ContractError(f"Analyst metric {name} requires a missing reason")
        if item["state"] == "POPULATED" and missing_reason not in {None, ""}:
            raise ContractError(f"Analyst metric {name} cannot be populated and missing")
    observed_names = tuple(
        str(value) for value in artifact["economics_interpretation"]["scenario_names"]
    )
    if observed_names != scenario_names:
        raise ContractError("Analyst changed the deterministic economics scenario set")


def _validate_validator(artifact: Mapping[str, Any], evidence_ids: set[str]) -> None:
    finding_ids: set[str] = set()
    open_high_or_critical = False
    for finding in artifact["findings"]:
        finding_id = str(finding["finding_id"])
        if finding_id in finding_ids:
            raise ContractError("Validator finding IDs must be unique")
        finding_ids.add(finding_id)
        references = {str(value) for value in finding["evidence_ids"]}
        if not references.issubset(evidence_ids):
            raise ContractError(f"Validator finding {finding_id} cites unknown evidence")
        if finding["status"] == "open" and finding["severity"] in {"high", "critical"}:
            open_high_or_critical = True
    if artifact["verdict"] == "PASS" and open_high_or_critical:
        raise ContractError("Validator cannot PASS with an open high or critical finding")


def _validate_synthesizer(
    artifact: Mapping[str, Any],
    evidence_ids: set[str],
    deterministic_snapshot: Mapping[str, Any],
) -> None:
    narratives = [
        artifact["executive_summary"],
        *artifact["sections"].values(),
        artifact["strongest_case_against"],
    ]
    for narrative in narratives:
        references = {str(value) for value in narrative["evidence_ids"]}
        if not references.issubset(evidence_ids):
            raise ContractError("Synthesizer narrative cites unknown evidence")
    if dict(artifact["deterministic_snapshot"]) != dict(deterministic_snapshot):
        raise ContractError("Synthesizer changed the deterministic snapshot")


def build_role_prompt(
    role: str,
    schema: Mapping[str, Any],
    payload: Mapping[str, Any],
    *,
    known_evidence_ids: set[str] | None = None,
) -> str:
    properties = schema.get("properties", {})
    exact_keys = list(properties) if isinstance(properties, Mapping) else []
    constants = {
        key: value["const"]
        for key, value in properties.items()
        if isinstance(value, Mapping) and "const" in value
    }
    validator_instructions = ""
    if role == "Validator":
        findings = properties.get("findings", {}) if isinstance(properties, Mapping) else {}
        items = findings.get("items", {}) if isinstance(findings, Mapping) else {}
        finding_properties = items.get("properties", {}) if isinstance(items, Mapping) else {}
        finding_keys = list(finding_properties) if isinstance(finding_properties, Mapping) else []
        allowed_ids = sorted(known_evidence_ids or set())
        validator_instructions = (
            "VALIDATOR-SPECIFIC CONTRACT\n"
            f"Exact finding keys: {json.dumps(finding_keys)}.\n"
            'Allowed verdicts: ["PASS", "REJECT", "UNKNOWN"].\n'
            'Allowed severities: ["low", "medium", "high", "critical"].\n'
            'Allowed finding statuses: ["open", "resolved"].\n'
            f"Exact evidence IDs allowed for citation: {json.dumps(allowed_ids)}.\n"
            "Every evidence_ids value must be copied byte-for-byte from that allowed list. "
            "Unknown keys and unknown evidence IDs cause rejection. If evidence is insufficient, "
            "use UNKNOWN; never fabricate or approximate an ID.\n\n"
        )
    return (
        f"You are the ODOP {role} in a separately dispatched Hermes/Menta role-chain replay.\n"
        "This is a replay of existing evidence, not a research run. Do not browse, call tools, "
        "or add facts. Use only the JSON input below. Unknowns must remain unknown.\n"
        "Return exactly one JSON object that validates against the supplied JSON Schema. "
        "Do not use Markdown fences or add commentary. Never invent an evidence ID. "
        "Copy every key spelling exactly; do not prefix, suffix, rename, or duplicate keys.\n"
        f"The exact permitted top-level keys are: {json.dumps(exact_keys)}.\n"
        f"Required constant values are: {json.dumps(constants, sort_keys=True)}.\n"
        "Before responding, verify that no other top-level key is present and all cited evidence "
        "IDs occur verbatim in the input.\n\n"
        f"{validator_instructions}"
        f"OUTPUT_SCHEMA\n{json.dumps(schema, ensure_ascii=False, sort_keys=True)}\n\n"
        f"INPUT\n{json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)}\n"
    )


def build_validator_repair_prompt(
    *,
    schema: Mapping[str, Any],
    payload: Mapping[str, Any],
    invalid_response: str,
    validation_errors: tuple[str, ...],
    known_evidence_ids: set[str],
) -> str:
    base = build_role_prompt(
        "Validator",
        schema,
        payload,
        known_evidence_ids=known_evidence_ids,
    )
    return (
        "This is the one permitted schema-repair pass for the SAME Validator route and model.\n"
        "Repair syntax and schema-key spelling only. Return corrected JSON only.\n"
        "Do not change the verdict, any finding ID, severity, status, affected feature, "
        "evidence ID, recommendation, or substantive finding text. Do not add or delete "
        "findings. Do not replace "
        "an unknown evidence ID with a guessed or similar ID.\n\n"
        f"VALIDATION_ERRORS\n{json.dumps(validation_errors, ensure_ascii=False)}\n\n"
        f"INVALID_RESPONSE\n{invalid_response}\n\n"
        f"ORIGINAL_CONTRACT_AND_INPUT\n{base}"
    )


def assert_validator_repair_preserves_semantics(
    initial_artifact: Mapping[str, Any] | None,
    repaired_artifact: Mapping[str, Any],
) -> None:
    if initial_artifact is None:
        return
    for key in (
        "contract_version",
        "role",
        "product_family_id",
        "status",
        "verdict",
        "strongest_case_against_promotion",
        "unresolved",
    ):
        initial = _value_for_normalized_key(initial_artifact, key)
        if initial is not _MISSING and initial != repaired_artifact.get(key):
            raise ContractError(f"Validator repair changed semantic field {key}")

    initial_findings = _value_for_normalized_key(initial_artifact, "findings")
    if not isinstance(initial_findings, list):
        return
    repaired_findings = repaired_artifact.get("findings")
    if not isinstance(repaired_findings, list) or len(initial_findings) != len(repaired_findings):
        raise ContractError("Validator repair added or deleted findings")
    semantic_keys = (
        "finding_id",
        "severity",
        "status",
        "title",
        "strongest_case",
        "affected_features",
        "evidence_ids",
        "recommended_action",
    )
    for index, (initial_finding, repaired_finding) in enumerate(
        zip(initial_findings, repaired_findings, strict=True)
    ):
        if not isinstance(initial_finding, Mapping) or not isinstance(repaired_finding, Mapping):
            raise ContractError("Validator repair changed the findings structure")
        for key in semantic_keys:
            initial = _value_for_normalized_key(initial_finding, key)
            if initial is not _MISSING and initial != repaired_finding.get(key):
                raise ContractError(
                    f"Validator repair changed finding {index} semantic field {key}"
                )


_MISSING = object()


def _value_for_normalized_key(value: Mapping[str, Any], canonical: str) -> object:
    normalized = "".join(character for character in canonical.lower() if character.isalnum())
    matches = [
        nested
        for key, nested in value.items()
        if "".join(character for character in str(key).lower() if character.isalnum()) == normalized
    ]
    if len(matches) > 1:
        raise ContractError(f"Validator repair source has ambiguous keys for {canonical}")
    return matches[0] if matches else _MISSING
