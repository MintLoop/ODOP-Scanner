from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb
import pytest
import yaml

from odop_scanner.agents.contracts import ContractError, load_schema, validate_role_output
from odop_scanner.agents.routing import (
    MentaProfileResolver,
    RoutingError,
    load_routing_config,
)
from odop_scanner.agents.runner import RoleChainRunner, RuntimeExecution
from odop_scanner.config import load_decision_gates, load_scoring, project_root
from odop_scanner.opportunity import decide_gate, load_evidence_packet, packet_features
from odop_scanner.scoring import calculate_score

EVIDENCE_PATH = project_root() / "evidence" / "makhana" / "makhana.evidence.v1.json"


@dataclass
class FakeExecutor:
    outputs: dict[str, Any]
    missing_role: str | None = None
    invalid_role: str | None = None
    unknown_telemetry: bool = False
    project_error: bool = False
    calls: list[str] = field(default_factory=list)

    def check_project(self, config: Any) -> str:
        if self.project_error:
            raise RoutingError("fixture project registration is missing")
        return f"slug={config.project_slug} workspace={config.workspace}"

    def execute(
        self, *, route: Any, prompt: str, usage_path: Path, config: Any
    ) -> RuntimeExecution:
        del prompt, usage_path, config
        started = datetime(2026, 10, 4, tzinfo=UTC)
        call_name = route.role
        if route.role == "validator" and "validator" in self.calls:
            call_name = "validator_repair"
        self.calls.append(call_name)
        response = self.outputs.get(call_name, self.outputs[route.role])
        stdout = response if isinstance(response, str) else json.dumps(response)
        if route.role == self.missing_role:
            stdout = ""
        elif route.role == self.invalid_role:
            stdout = json.dumps({"invalid": True})
        usage: dict[str, Any] = {}
        if not self.unknown_telemetry:
            usage = {
                "provider": route.provider,
                "model": route.model,
                "service_tier": "local",
                "input_tokens": 101,
                "output_tokens": 37,
                "estimated_cost_usd": 0.0,
                "cost_status": "estimated",
                "cost_source": "fixture",
                "api_calls": 1,
                "tool_calls": 0,
                "session_id": f"session-{route.role}",
                "completed": True,
                "partial": False,
                "interrupted": False,
                "turn_exit_reason": "final",
            }
        return RuntimeExecution(
            stdout=stdout,
            stderr="",
            usage=usage,
            started_at=started,
            ended_at=started + timedelta(milliseconds=25),
            duration_ms=25,
            returncode=0,
        )


def _routing_fixture(tmp_path: Path) -> Path:
    registry = {
        "profile_defaults": {
            "staffing": {
                "preferred_model": {"provider": "local", "model": "default"},
                "challenger_model": {"provider": "local", "model": "challenger"},
            }
        },
        "profiles": {
            "research.analyst": {
                "staffing": {"preferred_model": {"provider": "local", "model": "scout-model"}}
            },
            "biz.strategy-finance": {
                "staffing": {"preferred_model": {"provider": "local", "model": "analyst-model"}}
            },
            "assure.evidence": {
                "staffing": {"challenger_model": {"provider": "local", "model": "validator-model"}}
            },
            "product.strategy-ux": {
                "staffing": {"preferred_model": {"provider": "local", "model": "synth-model"}}
            },
        },
    }
    registry_path = tmp_path / "registry.yaml"
    registry_path.write_text(yaml.safe_dump(registry), encoding="utf-8")
    profile = {
        "project": {
            "slug": "odop-scanner",
            "required_profiles": [
                "research.analyst",
                "biz.strategy-finance",
                "assure.evidence",
                "product.strategy-ux",
            ],
            "conditional_profiles": [],
        }
    }
    profile_path = tmp_path / "odop-scanner.yaml"
    profile_path.write_text(yaml.safe_dump(profile), encoding="utf-8")
    config = {
        "version": "test-routing-v1",
        "project": {
            "slug": "odop-scanner",
            "workspace": str(project_root()),
            "live_profile": str(profile_path),
        },
        "menta": {
            "live_registry": str(registry_path),
            "desired_registry": str(registry_path),
        },
        "runtime": {
            "command": "hermes",
            "timeout_seconds": 5,
            "toolsets": ["todo"],
            "reasoning": "minimal",
            "ignore_workspace_rules": True,
        },
        "roles": {
            "scout": {
                "label": "Scout",
                "requested_profile": "research.analyst",
                "model_slot": "preferred_model",
                "schema": str(project_root() / "schemas" / "scout-output.schema.json"),
            },
            "analyst": {
                "label": "Market Analyst",
                "requested_profile": "biz.strategy-finance",
                "model_slot": "preferred_model",
                "schema": str(project_root() / "schemas" / "analyst-output.schema.json"),
            },
            "validator": {
                "label": "Validator",
                "requested_profile": "assure.evidence",
                "model_slot": "challenger_model",
                "schema": str(project_root() / "schemas" / "validator-output.schema.json"),
                "independence_from": "analyst",
            },
            "synthesizer": {
                "label": "Synthesizer",
                "requested_profile": "product.strategy-ux",
                "model_slot": "preferred_model",
                "schema": str(project_root() / "schemas" / "synthesizer-output.schema.json"),
            },
        },
    }
    config_path = tmp_path / "routing.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    return config_path


def _valid_outputs() -> dict[str, dict[str, Any]]:
    packet = load_evidence_packet(EVIDENCE_PATH)
    family_id = str(packet["product_family_id"])
    evidence = packet["evidence"]
    evidence_ids = [str(item["evidence_id"]) for item in evidence]
    buckets = {
        state.upper(): [
            str(item["evidence_id"]) for item in evidence if item["acceptance_state"] == state
        ]
        for state in ("accepted", "rejected", "unverified")
    }
    features = packet_features(packet)
    score = calculate_score(family_id, features, load_scoring())
    decision = decide_gate(
        score,
        load_decision_gates(),
        validator_verdict="REJECT",
        verified_hard_blockers=(),
        unresolved_critical_findings=(),
        proposed_test_spend_usd=150.0,
    )
    snapshot = {
        "score_id": score.score_id,
        "overall_score": score.overall_score,
        "evidence_coverage": score.evidence_coverage,
        "confidence_band": score.confidence_band,
        "validator_outcome": "REJECT",
        "decision_gate": decision.gate,
        "max_recommended_spend_usd": decision.max_recommended_spend_usd,
    }
    narrative = {"text": "Existing evidence leaves the opportunity unscored.", "evidence_ids": []}
    return {
        "scout": {
            "contract_version": "scout-output-v1",
            "role": "Scout",
            "product_family_id": family_id,
            "status": "SUCCESS",
            "summary": "Existing evidence was inventoried without new research.",
            "evidence_assessment": [
                {
                    "evidence_id": str(item["evidence_id"]),
                    "disposition": str(item["acceptance_state"]).upper(),
                    "rationale": "Disposition preserved from the evidence packet.",
                }
                for item in evidence
            ],
            "accepted_evidence_ids": buckets["ACCEPTED"],
            "rejected_evidence_ids": buckets["REJECTED"],
            "unverified_evidence_ids": buckets["UNVERIFIED"],
            "missing_evidence": ["No decision-grade demand measurement."],
            "unresolved_factual_gaps": ["Repeat purchase is unknown."],
        },
        "analyst": {
            "contract_version": "analyst-output-v1",
            "role": "Market Analyst",
            "product_family_id": family_id,
            "status": "SUCCESS",
            "summary": "All deterministic score inputs remain missing.",
            "metric_mapping": {
                name: {
                    "state": "MISSING",
                    "evidence_ids": [],
                    "interpretation": "Context exists but does not satisfy the metric formula.",
                    "missing_reason": packet["normalized_features"][name]["missing_reason"],
                }
                for name in features
            },
            "assumptions": ["Economics are sensitivity scenarios, not quotes."],
            "economics_interpretation": {
                "scenario_names": [item["name"] for item in packet["economics"]["scenarios"]],
                "interpretation": "Scenario outputs are conditional only.",
                "limitations": ["No supplier quote was collected."],
            },
            "unresolved": ["Demand and repeat purchase remain unmeasured."],
        },
        "validator": {
            "contract_version": "validator-output-v1",
            "role": "Validator",
            "product_family_id": family_id,
            "status": "SUCCESS",
            "verdict": "REJECT",
            "strongest_case_against_promotion": "No scoring metric is populated.",
            "findings": [
                {
                    "finding_id": "routed-vf-1",
                    "severity": "high",
                    "status": "open",
                    "title": "No decision-grade demand evidence",
                    "strongest_case": "Listings do not establish velocity or repeat purchase.",
                    "affected_features": ["demand", "repeat_purchase"],
                    "evidence_ids": [evidence_ids[0]],
                    "recommended_action": "Run a bounded demand experiment.",
                }
            ],
            "unresolved": ["Demand remains unknown."],
        },
        "synthesizer": {
            "contract_version": "synthesizer-output-v1",
            "role": "Synthesizer",
            "product_family_id": family_id,
            "status": "SUCCESS",
            "executive_summary": narrative,
            "sections": {
                name: narrative
                for name in (
                    "market",
                    "demand",
                    "competition",
                    "supply",
                    "economics",
                    "regulatory_friction",
                    "product",
                    "brandability",
                    "content_potential",
                )
            },
            "strongest_case_against": narrative,
            "top_unknowns": [f"Unknown {index}" for index in range(1, 6)],
            "top_risks": [f"Risk {index}" for index in range(1, 6)],
            "cheapest_next_experiment": "Run the existing capped $150 test.",
            "deterministic_snapshot": snapshot,
        },
    }


def _run(tmp_path: Path, executor: FakeExecutor) -> tuple[dict[str, Any], Path]:
    database_path = tmp_path / "role-chain.duckdb"
    output = RoleChainRunner(executor).run(
        product="product-001",
        evidence_path=EVIDENCE_PATH,
        database_path=database_path,
        routing_path=_routing_fixture(tmp_path),
        output_directory=tmp_path / "artifacts",
    )
    return output, database_path


def test_role_chain_replay_persists_distinct_runs_and_preserves_score(tmp_path: Path) -> None:
    output, database_path = _run(tmp_path, FakeExecutor(_valid_outputs()))

    assert output["status"] == "GO"
    assert output["orchestration_verified"] is True
    assert output["validator_independence_verified"] is True
    assert output["score"]["score_status"] == "unscored"
    assert output["score"]["overall_score"] is None
    assert output["score"]["evidence_coverage"] == 0.0
    assert output["decision"]["gate"] == "TEST"

    benchmark = json.loads(Path(output["benchmark"]).read_text(encoding="utf-8"))
    assert benchmark["model_call_count"] == 4
    assert benchmark["tool_call_count"] == 0
    assert benchmark["control_comparison"]["deterministic_result_unchanged"] is True
    assert {item["requested_profile"] for item in benchmark["roles"]} == {
        "research.analyst",
        "biz.strategy-finance",
        "assure.evidence",
        "product.strategy-ux",
    }
    assert len({item["run_id"] for item in benchmark["roles"]}) == 4

    connection = duckdb.connect(str(database_path), read_only=True)
    runs = connection.execute(
        "SELECT agent, status, provider, model, input_tokens, output_tokens FROM agent_runs"
    ).fetchall()
    chain = connection.execute(
        "SELECT run_status, orchestration_verified, validator_independence_verified "
        "FROM role_chain_runs"
    ).fetchone()
    connection.close()
    assert len(runs) == 4
    assert all(item[1] == "succeeded" for item in runs)
    assert chain == ("GO", True, True)


@pytest.mark.parametrize(
    ("executor", "expected"),
    [
        (FakeExecutor(_valid_outputs(), missing_role="scout"), "output artifact is missing"),
        (FakeExecutor(_valid_outputs(), invalid_role="scout"), "schema violation"),
        (FakeExecutor(_valid_outputs(), project_error=True), "project registration is missing"),
    ],
)
def test_role_chain_failure_modes_block(
    tmp_path: Path, executor: FakeExecutor, expected: str
) -> None:
    output, database_path = _run(tmp_path, executor)

    assert output["status"] == "BLOCKED"
    assert output["orchestration_verified"] is False
    assert expected in output["blocked_reason"]
    connection = duckdb.connect(str(database_path), read_only=True)
    assert connection.execute("SELECT run_status FROM role_chain_runs").fetchone() == ("BLOCKED",)
    connection.close()


def test_unknown_runtime_telemetry_cannot_establish_validator_independence(
    tmp_path: Path,
) -> None:
    output, database_path = _run(tmp_path, FakeExecutor(_valid_outputs(), unknown_telemetry=True))

    assert output["status"] == "BLOCKED"
    assert output["role_run_count"] == 3
    assert output["validator_independence_verified"] is False
    assert "cannot be proven from runtime telemetry" in output["blocked_reason"]
    connection = duckdb.connect(str(database_path), read_only=True)
    receipt = connection.execute(
        "SELECT model, provider, token_state, cost_state FROM agent_runs LIMIT 1"
    ).fetchone()
    connection.close()
    assert receipt == (None, None, "UNKNOWN", "UNKNOWN")


def test_validator_cannot_pass_with_open_critical_finding() -> None:
    artifact = _valid_outputs()["validator"]
    artifact["verdict"] = "PASS"
    artifact["findings"][0]["severity"] = "critical"
    evidence_ids = {
        str(item["evidence_id"]) for item in load_evidence_packet(EVIDENCE_PATH)["evidence"]
    }

    with pytest.raises(ContractError, match="cannot PASS"):
        validate_role_output(
            role="validator",
            artifact=artifact,
            schema=load_schema(project_root() / "schemas" / "validator-output.schema.json"),
            product_family_id="product-001",
            evidence_ids=evidence_ids,
        )


def test_profile_resolution_rejects_analyst_validator_model_collision(tmp_path: Path) -> None:
    config_path = _routing_fixture(tmp_path)
    config_document = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    registry_path = Path(config_document["menta"]["live_registry"])
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    registry["profiles"]["assure.evidence"]["staffing"]["challenger_model"] = {
        "provider": "local",
        "model": "analyst-model",
    }
    registry_path.write_text(yaml.safe_dump(registry), encoding="utf-8")

    with pytest.raises(RoutingError, match="producer provider/model"):
        MentaProfileResolver(load_routing_config(config_path)).resolve_all()


def test_validator_one_pass_repair_succeeds_before_synthesizer_dispatch(
    tmp_path: Path,
) -> None:
    outputs = _valid_outputs()
    valid_validator = deepcopy(outputs["validator"])
    invalid_validator = deepcopy(valid_validator)
    invalid_validator["contract_contract_version"] = invalid_validator.pop("contract_version")
    outputs["validator"] = invalid_validator
    outputs["validator_repair"] = valid_validator
    executor = FakeExecutor(outputs)

    output, database_path = _run(tmp_path, executor)

    assert output["status"] == "GO"
    assert executor.calls == ["scout", "analyst", "validator", "validator_repair", "synthesizer"]
    benchmark = json.loads(Path(output["benchmark"]).read_text(encoding="utf-8"))
    assert benchmark["validator_repair"]["used"] is True
    assert benchmark["validator_repair"]["repair_validation_result"] == "ACCEPTED"
    assert benchmark["validator_repair"]["initial_validation_errors"]
    assert benchmark["validator_independence_verified"] is True
    assert benchmark["control_comparison"]["deterministic_result_unchanged"] is True
    assert Path(output["artifact_directory"], "validator.output.json").is_file()
    assert Path(output["artifact_directory"], "synthesizer.output.json").is_file()

    connection = duckdb.connect(str(database_path), read_only=True)
    validator_runs = connection.execute(
        "SELECT agent, status FROM agent_runs WHERE agent LIKE 'Validator%' ORDER BY started_at"
    ).fetchall()
    connection.close()
    assert validator_runs == [("Validator", "failed"), ("Validator Repair", "succeeded")]


def test_validator_repair_failure_is_bounded_and_blocks_synthesizer(tmp_path: Path) -> None:
    outputs = _valid_outputs()
    invalid_validator = deepcopy(outputs["validator"])
    invalid_validator["unknown_top_level"] = True
    outputs["validator"] = invalid_validator
    outputs["validator_repair"] = invalid_validator
    executor = FakeExecutor(outputs)

    output, _ = _run(tmp_path, executor)

    assert output["status"] == "BLOCKED"
    assert executor.calls == ["scout", "analyst", "validator", "validator_repair"]
    assert executor.calls.count("validator_repair") == 1
    assert "Validator repair failed after one attempt" in output["blocked_reason"]
    artifact_directory = Path(output["artifact_directory"])
    assert (artifact_directory / "validator.initial.validation-errors.json").is_file()
    assert (artifact_directory / "validator.repair.validation-errors.json").is_file()
    assert not (artifact_directory / "synthesizer.input.json").exists()


def test_validator_repair_cannot_change_unknown_evidence_id(tmp_path: Path) -> None:
    outputs = _valid_outputs()
    invalid_validator = deepcopy(outputs["validator"])
    invalid_validator["findings"][0]["evidence_ids"] = ["unknown-evidence-id"]
    outputs["validator"] = invalid_validator
    outputs["validator_repair"] = deepcopy(_valid_outputs()["validator"])
    executor = FakeExecutor(outputs)

    output, _ = _run(tmp_path, executor)

    assert output["status"] == "BLOCKED"
    assert "changed finding 0 semantic field evidence_ids" in output["blocked_reason"]
    assert executor.calls.count("validator_repair") == 1
    assert "synthesizer" not in executor.calls


def test_malformed_validator_json_can_use_one_repair_attempt(tmp_path: Path) -> None:
    outputs: dict[str, Any] = _valid_outputs()
    outputs["validator"] = '{"contract_version":'
    outputs["validator_repair"] = deepcopy(_valid_outputs()["validator"])
    executor = FakeExecutor(outputs)

    output, _ = _run(tmp_path, executor)

    assert output["status"] == "GO"
    assert executor.calls.count("validator_repair") == 1
    assert executor.calls[-1] == "synthesizer"
