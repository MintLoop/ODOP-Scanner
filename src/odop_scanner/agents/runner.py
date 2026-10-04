from __future__ import annotations

import hashlib
import json
import subprocess
import time
import uuid
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, cast

from ..config import load_decision_gates, load_scoring, project_root
from ..models import ValidatorFinding, ValidatorVerdict
from ..opportunity import (
    decide_gate,
    load_evidence_packet,
    packet_evidence,
    packet_features,
    packet_signals,
)
from ..scoring import calculate_score
from ..storage import (
    connect_database,
    score_as_dict,
    store_agent_runs,
    store_decision,
    store_market_evidence,
    store_role_chain_run,
    store_score,
    store_validator_findings,
    upsert_features,
)
from .contracts import (
    ContractError,
    build_role_prompt,
    load_schema,
    parse_structured_response,
    sha256_value,
    validate_role_output,
)
from .routing import (
    MentaProfileResolver,
    ResolvedRoute,
    RoutingConfig,
    RoutingError,
    assert_independent,
    load_routing_config,
)


class RoleChainError(RuntimeError):
    """The routed replay cannot be certified as an operational role chain."""


@dataclass(frozen=True)
class RuntimeExecution:
    stdout: str
    stderr: str
    usage: Mapping[str, Any]
    started_at: datetime
    ended_at: datetime
    duration_ms: int
    returncode: int
    timed_out: bool = False


class RoleExecutor(Protocol):
    def check_project(self, config: RoutingConfig) -> str: ...

    def execute(
        self,
        *,
        route: ResolvedRoute,
        prompt: str,
        usage_path: Path,
        config: RoutingConfig,
    ) -> RuntimeExecution: ...


class HermesExecutor:
    """Invoke one isolated Hermes process per role and read its native usage receipt."""

    def check_project(self, config: RoutingConfig) -> str:
        try:
            result = subprocess.run(
                [config.runtime_command, "project", "show", config.project_slug],
                cwd=config.workspace,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise RoutingError(f"Hermes project lookup failed: {error}") from error
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise RoutingError(
                f"Hermes project {config.project_slug!r} is not registered: {detail}"
            )
        output = result.stdout.strip()
        if str(config.workspace.resolve()) not in output:
            raise RoutingError("Hermes project registration does not point at this workspace")
        return output

    def execute(
        self,
        *,
        route: ResolvedRoute,
        prompt: str,
        usage_path: Path,
        config: RoutingConfig,
    ) -> RuntimeExecution:
        usage_path.parent.mkdir(parents=True, exist_ok=True)
        started_at = datetime.now(UTC)
        started = time.monotonic()
        command = [
            config.runtime_command,
            "-z",
            prompt,
            "--usage-file",
            str(usage_path),
            "--provider",
            route.provider,
            "--model",
            route.model,
            "--toolsets",
            ",".join(config.toolsets),
            "--reasoning",
            config.reasoning,
            "--in",
            str(config.workspace),
        ]
        if config.ignore_workspace_rules:
            command.append("--ignore-rules")
        try:
            result = subprocess.run(
                command,
                cwd=config.workspace,
                capture_output=True,
                text=True,
                timeout=config.timeout_seconds,
                check=False,
            )
            stdout = result.stdout
            stderr = result.stderr
            returncode = result.returncode
            timed_out = False
        except subprocess.TimeoutExpired as error:
            stdout = _decoded_output(error.stdout)
            stderr = _decoded_output(error.stderr)
            returncode = 124
            timed_out = True
        except OSError as error:
            stdout = ""
            stderr = str(error)
            returncode = 127
            timed_out = False
        ended_at = datetime.now(UTC)
        duration_ms = round((time.monotonic() - started) * 1000)
        usage = _read_usage(usage_path)
        return RuntimeExecution(
            stdout=stdout,
            stderr=stderr,
            usage=usage,
            started_at=started_at,
            ended_at=ended_at,
            duration_ms=duration_ms,
            returncode=returncode,
            timed_out=timed_out,
        )


def _decoded_output(value: str | bytes | None) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value or ""


def _read_usage(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


class RoleChainRunner:
    def __init__(self, executor: RoleExecutor | None = None):
        self.executor = executor or HermesExecutor()

    def run(
        self,
        *,
        product: str,
        evidence_path: Path,
        database_path: Path,
        routing_path: Path | None = None,
        output_directory: Path | None = None,
    ) -> dict[str, Any]:
        packet = load_evidence_packet(evidence_path)
        family_id = str(packet["product_family_id"])
        if product not in {family_id, str(packet["product_name"])}:
            raise ValueError("requested product does not match the replay evidence packet")

        started_at = datetime.now(UTC)
        monotonic_start = time.monotonic()
        chain_run_id = f"{family_id}-{started_at.strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
        artifact_directory = (
            output_directory or project_root() / "dogfood" / "runs" / chain_run_id
        ).resolve()
        artifact_directory.mkdir(parents=True, exist_ok=False)
        packet_hash = hashlib.sha256(evidence_path.read_bytes()).hexdigest()

        scoring_config = load_scoring()
        gate_config = load_decision_gates()
        features = packet_features(packet)
        score_before = calculate_score(family_id, features, scoring_config)
        known_evidence_ids = {
            str(item["evidence_id"]) for item in cast(list[dict[str, Any]], packet["evidence"])
        }
        feature_states = {
            name: "POPULATED" if value is not None else "MISSING"
            for name, value in features.items()
        }
        scenario_names = tuple(
            str(item["name"])
            for item in cast(dict[str, list[dict[str, Any]]], packet["economics"])["scenarios"]
        )
        accepted_count = sum(
            item["acceptance_state"] == "accepted"
            for item in cast(list[dict[str, Any]], packet["evidence"])
        )
        populated_count = sum(value is not None for value in features.values())

        connection = connect_database(database_path)
        receipts: list[dict[str, Any]] = []
        artifacts: dict[str, dict[str, Any]] = {}
        routes: dict[str, ResolvedRoute] = {}
        config: RoutingConfig | None = None
        registry_sha256: str | None = None
        validator_verdict: ValidatorVerdict | None = None
        decision = None
        blocked_reason: str | None = None
        independence_verified = False
        orchestration_verified = False
        benchmark_path = artifact_directory / "benchmark.json"

        try:
            store_market_evidence(connection, packet_evidence(packet), packet_signals(packet))
            upsert_features(
                connection,
                family_id,
                features,
                evidence=cast(dict[str, Any], packet["normalized_features"]),
            )
            store_score(connection, score_before)

            config = load_routing_config(routing_path)
            self.executor.check_project(config)
            resolver = MentaProfileResolver(config)
            registry_sha256 = resolver.registry_sha256
            routes = resolver.resolve_all()

            scout_payload = {
                "product_family_id": family_id,
                "product_name": packet["product_name"],
                "scope": packet["scope"],
                "evidence": _compact_evidence(packet),
                "signals": packet["signals"],
                "existing_feature_gaps": {
                    name: item["missing_reason"]
                    for name, item in cast(
                        dict[str, dict[str, Any]], packet["normalized_features"]
                    ).items()
                    if item["value"] is None
                },
            }
            artifacts["scout"] = self._run_stage(
                role="scout",
                route=routes["scout"],
                payload=scout_payload,
                packet=packet,
                config=config,
                artifact_directory=artifact_directory,
                chain_run_id=chain_run_id,
                family_id=family_id,
                known_evidence_ids=known_evidence_ids,
                receipts=receipts,
                connection=connection,
            )

            analyst_payload = {
                "product_family_id": family_id,
                "scout_output": artifacts["scout"],
                "evidence": _compact_evidence(packet),
                "signals": packet["signals"],
                "normalized_features": packet["normalized_features"],
                "economics": packet["economics"],
                "constraint": "Interpret only; deterministic feature values are immutable.",
            }
            artifacts["analyst"] = self._run_stage(
                role="analyst",
                route=routes["analyst"],
                payload=analyst_payload,
                packet=packet,
                config=config,
                artifact_directory=artifact_directory,
                chain_run_id=chain_run_id,
                family_id=family_id,
                known_evidence_ids=known_evidence_ids,
                receipts=receipts,
                connection=connection,
                feature_states=feature_states,
                scenario_names=scenario_names,
            )

            validator_payload = {
                "product_family_id": family_id,
                "scout_output": artifacts["scout"],
                "analyst_output": artifacts["analyst"],
                "evidence_index": _evidence_index(packet),
                "signals": packet["signals"],
                "normalized_features": packet["normalized_features"],
                "economics": packet["economics"],
                "deterministic_score": score_as_dict(score_before),
                "constraint": "Audit independently; do not assume producer conclusions are true.",
            }
            artifacts["validator"] = self._run_stage(
                role="validator",
                route=routes["validator"],
                payload=validator_payload,
                packet=packet,
                config=config,
                artifact_directory=artifact_directory,
                chain_run_id=chain_run_id,
                family_id=family_id,
                known_evidence_ids=known_evidence_ids,
                receipts=receipts,
                connection=connection,
            )
            independence_verified = _verify_observed_independence(
                routes["analyst"],
                routes["validator"],
                receipts,
            )

            validator_verdict = cast(ValidatorVerdict, artifacts["validator"]["verdict"])
            findings = _findings_from_artifact(family_id, artifacts["validator"])
            store_validator_findings(connection, score_before.score_id, findings)
            unresolved_critical = tuple(
                finding.finding_id
                for finding in findings
                if finding.severity == "critical" and finding.status == "open"
            )
            decision = decide_gate(
                score_before,
                gate_config,
                validator_verdict=validator_verdict,
                verified_hard_blockers=tuple(
                    str(value)
                    for value in cast(dict[str, Any], packet["card"])["verified_hard_blockers"]
                ),
                unresolved_critical_findings=unresolved_critical,
                proposed_test_spend_usd=float(
                    cast(dict[str, Any], packet["card"])["max_recommended_spend_usd"]
                ),
            )
            snapshot = {
                "score_id": score_before.score_id,
                "overall_score": score_before.overall_score,
                "evidence_coverage": score_before.evidence_coverage,
                "confidence_band": score_before.confidence_band,
                "validator_outcome": validator_verdict,
                "decision_gate": decision.gate,
                "max_recommended_spend_usd": decision.max_recommended_spend_usd,
            }
            synthesizer_payload = {
                "product_family_id": family_id,
                "product_name": packet["product_name"],
                "scout_output": artifacts["scout"],
                "analyst_output": artifacts["analyst"],
                "validator_output": artifacts["validator"],
                "evidence_index": _evidence_index(packet),
                "economics": packet["economics"],
                "deterministic_snapshot": snapshot,
                "constraint": "Narrate only; repeat the deterministic snapshot exactly.",
            }
            artifacts["synthesizer"] = self._run_stage(
                role="synthesizer",
                route=routes["synthesizer"],
                payload=synthesizer_payload,
                packet=packet,
                config=config,
                artifact_directory=artifact_directory,
                chain_run_id=chain_run_id,
                family_id=family_id,
                known_evidence_ids=known_evidence_ids,
                receipts=receipts,
                connection=connection,
                deterministic_snapshot=snapshot,
            )

            score_after = calculate_score(family_id, packet_features(packet), scoring_config)
            _assert_score_unchanged(score_before, score_after)
            decision_after = decide_gate(
                score_after,
                gate_config,
                validator_verdict=validator_verdict,
                verified_hard_blockers=tuple(
                    str(value)
                    for value in cast(dict[str, Any], packet["card"])["verified_hard_blockers"]
                ),
                unresolved_critical_findings=unresolved_critical,
                proposed_test_spend_usd=float(
                    cast(dict[str, Any], packet["card"])["max_recommended_spend_usd"]
                ),
            )
            if decision_after != decision:
                raise RoleChainError("deterministic decision changed across the role chain")
            store_decision(
                connection,
                family_id=family_id,
                score_id=score_before.score_id,
                decision=decision,
                validator_verdict=validator_verdict,
                evidence_packet_sha256=packet_hash,
                gate_config=gate_config,
            )
            card_path = artifact_directory / "opportunity-card.md"
            card_path.write_text(
                _render_routed_card(packet, artifacts["synthesizer"], snapshot),
                encoding="utf-8",
            )
            orchestration_verified = True
        except (ContractError, RoleChainError, RoutingError, ValueError) as error:
            blocked_reason = f"{type(error).__name__}: {error}"
        except Exception as error:  # Runtime and persistence failures must fail closed too.
            blocked_reason = f"{type(error).__name__}: {error}"

        ended_at = datetime.now(UTC)
        duration_ms = round((time.monotonic() - monotonic_start) * 1000)
        cost = _aggregate_cost(receipts)
        benchmark = _benchmark(
            chain_run_id=chain_run_id,
            packet=packet,
            packet_hash=packet_hash,
            config=config,
            registry_sha256=registry_sha256,
            started_at=started_at,
            ended_at=ended_at,
            duration_ms=duration_ms,
            score=score_before,
            decision=decision,
            validator_verdict=validator_verdict,
            artifacts=artifacts,
            receipts=receipts,
            routes=routes,
            accepted_count=accepted_count,
            populated_count=populated_count,
            independence_verified=independence_verified,
            orchestration_verified=orchestration_verified,
            blocked_reason=blocked_reason,
            cost=cost,
            artifact_directory=artifact_directory,
        )
        benchmark_path.write_text(
            json.dumps(benchmark, indent=2, ensure_ascii=False, sort_keys=True, default=str) + "\n",
            encoding="utf-8",
        )
        try:
            store_role_chain_run(
                connection,
                {
                    "chain_run_id": chain_run_id,
                    "family_id": family_id,
                    "evidence_packet_sha256": packet_hash,
                    "routing_config_sha256": config.sha256 if config else "UNRESOLVED",
                    "registry_sha256": registry_sha256,
                    "started_at": started_at,
                    "ended_at": ended_at,
                    "duration_ms": duration_ms,
                    "run_status": benchmark["status"],
                    "blocked_reason": blocked_reason,
                    "score_id": score_before.score_id,
                    "overall_score": score_before.overall_score,
                    "evidence_coverage": score_before.evidence_coverage,
                    "validator_verdict": validator_verdict,
                    "decision_gate": decision.gate if decision else None,
                    "validator_independence_verified": independence_verified,
                    "orchestration_verified": orchestration_verified,
                    "accepted_evidence_count": accepted_count,
                    "populated_metric_count": populated_count,
                    "null_metric_count": len(features) - populated_count,
                    "total_cost_amount": cost["amount"],
                    "cost_currency": cost["currency"],
                    "cost_state": cost["state"],
                    "artifact_directory": str(artifact_directory),
                    "benchmark_artifact": str(benchmark_path),
                },
            )
        finally:
            connection.close()
        return {
            "status": benchmark["status"],
            "chain_run_id": chain_run_id,
            "blocked_reason": blocked_reason,
            "score": score_as_dict(score_before),
            "validator_verdict": validator_verdict,
            "decision": asdict(decision) if decision else None,
            "validator_independence_verified": independence_verified,
            "orchestration_verified": orchestration_verified,
            "role_run_count": len(receipts),
            "benchmark": str(benchmark_path),
            "artifact_directory": str(artifact_directory),
        }

    def _run_stage(
        self,
        *,
        role: str,
        route: ResolvedRoute,
        payload: Mapping[str, Any],
        packet: Mapping[str, Any],
        config: RoutingConfig,
        artifact_directory: Path,
        chain_run_id: str,
        family_id: str,
        known_evidence_ids: set[str],
        receipts: list[dict[str, Any]],
        connection: Any,
        feature_states: Mapping[str, str] | None = None,
        scenario_names: tuple[str, ...] = (),
        deterministic_snapshot: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        schema = load_schema(route.schema_path)
        input_path = artifact_directory / f"{role}.input.json"
        output_path = artifact_directory / f"{role}.output.json"
        raw_path = artifact_directory / f"{role}.raw.txt"
        usage_path = artifact_directory / f"{role}.usage.json"
        input_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True, default=str) + "\n",
            encoding="utf-8",
        )
        prompt = build_role_prompt(route.label, schema, payload)
        try:
            execution = self.executor.execute(
                route=route,
                prompt=prompt,
                usage_path=usage_path,
                config=config,
            )
        except Exception as execution_error:
            now = datetime.now(UTC)
            receipt = _receipt(
                chain_run_id=chain_run_id,
                role=role,
                route=route,
                execution=RuntimeExecution("", str(execution_error), {}, now, now, 0, 127),
                prompt=prompt,
                artifact=None,
                output_path=None,
                evidence_ids=known_evidence_ids,
                error=execution_error,
            )
            receipts.append(receipt)
            store_agent_runs(connection, family_id, [receipt])
            raise RoleChainError(
                f"{route.label} execution failed: {execution_error}"
            ) from execution_error

        raw_path.write_text(execution.stdout, encoding="utf-8")
        validation_error: Exception | None = None
        artifact: dict[str, Any] | None = None
        try:
            if execution.returncode != 0:
                detail = execution.stderr.strip() or f"exit {execution.returncode}"
                raise RoleChainError(f"{route.label} runtime failed: {detail}")
            if execution.usage.get("completed") is False:
                raise RoleChainError(f"{route.label} runtime receipt is incomplete")
            if not execution.stdout.strip():
                raise ContractError(f"{route.label} output artifact is missing")
            artifact = parse_structured_response(execution.stdout)
            validate_role_output(
                role=role,
                artifact=artifact,
                schema=schema,
                product_family_id=family_id,
                evidence_ids=known_evidence_ids,
                feature_states=feature_states,
                scenario_names=scenario_names,
                deterministic_snapshot=deterministic_snapshot,
            )
            output_path.write_text(
                json.dumps(artifact, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        except Exception as caught:
            validation_error = caught

        receipt = _receipt(
            chain_run_id=chain_run_id,
            role=role,
            route=route,
            execution=execution,
            prompt=prompt,
            artifact=artifact if validation_error is None else None,
            output_path=output_path if validation_error is None else None,
            evidence_ids=known_evidence_ids,
            error=validation_error,
        )
        receipts.append(receipt)
        store_agent_runs(connection, family_id, [receipt])
        if validation_error is not None:
            raise validation_error
        assert artifact is not None
        return artifact


def _receipt(
    *,
    chain_run_id: str,
    role: str,
    route: ResolvedRoute,
    execution: RuntimeExecution,
    prompt: str,
    artifact: Mapping[str, Any] | None,
    output_path: Path | None,
    evidence_ids: set[str],
    error: Exception | None,
) -> dict[str, Any]:
    usage = execution.usage
    actual_provider = _known_string(usage.get("provider"))
    actual_model = _known_string(usage.get("model"))
    service_class = _known_string(usage.get("service_tier")) or "UNKNOWN"
    input_tokens = _known_int(usage.get("input_tokens"))
    output_tokens = _known_int(usage.get("output_tokens"))
    reported_amount = _known_float(usage.get("estimated_cost_usd"))
    reported_cost_status = str(usage.get("cost_status", "unknown")).lower()
    cost_is_known = reported_cost_status in {"known", "estimated", "measured"}
    amount = reported_amount if cost_is_known else None
    cost_state = "ESTIMATED" if amount is not None else "UNKNOWN"
    references = _collect_evidence_refs(artifact, evidence_ids) if artifact else []
    return {
        "run_id": f"{chain_run_id}-{role}",
        "agent": route.label,
        "model": actual_model,
        "route": (
            f"hermes-oneshot:{actual_provider}/{actual_model}"
            if actual_provider and actual_model
            else None
        ),
        "started_at": execution.started_at,
        "ended_at": execution.ended_at,
        "duration_ms": execution.duration_ms,
        "cost_amount": amount,
        "cost_currency": "USD" if amount is not None else None,
        "cost_state": cost_state,
        "output_artifact": str(output_path) if output_path else None,
        "status": "succeeded" if error is None else "failed",
        "requested_profile": route.requested_profile,
        "resolved_profile": route.resolved_profile,
        "provider": actual_provider,
        "service_class": service_class,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "token_state": (
            "MEASURED" if input_tokens is not None and output_tokens is not None else "UNKNOWN"
        ),
        "input_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "output_sha256": sha256_value(artifact) if artifact else None,
        "evidence_refs": references,
        "error_class": type(error).__name__ if error else None,
        "registry_sha256": route.registry_sha256,
        "contract_version": artifact.get("contract_version") if artifact else None,
        "runtime": {
            "returncode": execution.returncode,
            "timed_out": execution.timed_out,
            "completed": usage.get("completed", "UNKNOWN"),
            "partial": usage.get("partial", "UNKNOWN"),
            "interrupted": usage.get("interrupted", "UNKNOWN"),
            "turn_exit_reason": usage.get("turn_exit_reason", "UNKNOWN"),
            "api_calls": usage.get("api_calls", "UNKNOWN"),
            "tool_calls": usage.get("tool_calls", "UNKNOWN"),
            "session_id": usage.get("session_id", "UNKNOWN"),
            "cost_status": usage.get("cost_status", "UNKNOWN"),
            "cost_source": usage.get("cost_source", "UNKNOWN"),
        },
        "requested_route": f"hermes-oneshot:{route.provider}/{route.model}",
    }


def _verify_observed_independence(
    analyst_route: ResolvedRoute,
    validator_route: ResolvedRoute,
    receipts: list[dict[str, Any]],
) -> bool:
    assert_independent(analyst_route, validator_route)
    by_agent = {str(item["agent"]): item for item in receipts}
    analyst = by_agent.get(analyst_route.label)
    validator = by_agent.get(validator_route.label)
    if analyst is None or validator is None:
        raise RoleChainError("Validator independence lacks producer/validator receipts")
    analyst_observed = (analyst.get("provider"), analyst.get("model"))
    validator_observed = (validator.get("provider"), validator.get("model"))
    if None in analyst_observed or None in validator_observed:
        raise RoleChainError("Validator independence cannot be proven from runtime telemetry")
    if analyst_observed == validator_observed:
        raise RoleChainError("Validator executed on the producer provider/model")
    if analyst.get("resolved_profile") == validator.get("resolved_profile"):
        raise RoleChainError("Validator executed under the producer profile")
    return True


def _findings_from_artifact(
    family_id: str, artifact: Mapping[str, Any]
) -> tuple[ValidatorFinding, ...]:
    return tuple(
        ValidatorFinding(
            finding_id=str(item["finding_id"]),
            family_id=family_id,
            severity=item["severity"],
            status=item["status"],
            title=str(item["title"]),
            strongest_case=str(item["strongest_case"]),
            affected_features=tuple(str(value) for value in item["affected_features"]),
            evidence_ids=tuple(str(value) for value in item["evidence_ids"]),
            recommended_action=str(item["recommended_action"]),
        )
        for item in artifact["findings"]
    )


def _assert_score_unchanged(before: Any, after: Any) -> None:
    fields = (
        "score_id",
        "component_scores",
        "missing_metrics",
        "raw_score",
        "overall_score",
        "evidence_coverage",
        "confidence_band",
        "score_status",
        "score_version",
        "scoring_config_sha256",
    )
    if any(getattr(before, field) != getattr(after, field) for field in fields):
        raise RoleChainError("deterministic score changed across the narrative role chain")


def _aggregate_cost(receipts: list[dict[str, Any]]) -> dict[str, Any]:
    if not receipts or any(item["cost_state"] == "UNKNOWN" for item in receipts):
        return {"amount": None, "currency": None, "state": "UNKNOWN"}
    return {
        "amount": round(sum(float(item["cost_amount"]) for item in receipts), 8),
        "currency": "USD",
        "state": "ESTIMATED",
    }


def _benchmark(
    *,
    chain_run_id: str,
    packet: Mapping[str, Any],
    packet_hash: str,
    config: RoutingConfig | None,
    registry_sha256: str | None,
    started_at: datetime,
    ended_at: datetime,
    duration_ms: int,
    score: Any,
    decision: Any,
    validator_verdict: ValidatorVerdict | None,
    artifacts: Mapping[str, Mapping[str, Any]],
    receipts: list[dict[str, Any]],
    routes: Mapping[str, ResolvedRoute],
    accepted_count: int,
    populated_count: int,
    independence_verified: bool,
    orchestration_verified: bool,
    blocked_reason: str | None,
    cost: Mapping[str, Any],
    artifact_directory: Path,
) -> dict[str, Any]:
    role_receipts = [
        {**item, "started_at": str(item["started_at"]), "ended_at": str(item["ended_at"])}
        for item in receipts
    ]
    model_calls = sum(
        value for item in receipts if isinstance((value := item["runtime"].get("api_calls")), int)
    )
    all_model_calls_known = bool(receipts) and all(
        isinstance(item["runtime"].get("api_calls"), int) for item in receipts
    )
    tool_call_values = [item["runtime"].get("tool_calls") for item in receipts]
    all_tool_calls_known = bool(receipts) and all(
        isinstance(value, int) for value in tool_call_values
    )
    control_gate = "TEST"
    status = "GO" if orchestration_verified and blocked_reason is None else "BLOCKED"
    return {
        "benchmark_version": "odop-role-chain-benchmark-v1",
        "chain_run_id": chain_run_id,
        "status": status,
        "blocked_reason": blocked_reason,
        "product_family_id": packet["product_family_id"],
        "evidence_packet_sha256": packet_hash,
        "routing_config_sha256": config.sha256 if config else "UNRESOLVED",
        "registry_sha256": registry_sha256 or "UNRESOLVED",
        "started_at": str(started_at),
        "ended_at": str(ended_at),
        "duration_ms": duration_ms,
        "model_call_count": model_calls if all_model_calls_known else "UNKNOWN",
        "tool_call_count": sum(cast(list[int], tool_call_values))
        if all_tool_calls_known
        else "UNKNOWN",
        "cost": dict(cost),
        "validator_independence_verified": independence_verified,
        "orchestration_verified": orchestration_verified,
        "routing": {
            role: {
                "requested_profile": route.requested_profile,
                "resolved_profile": route.resolved_profile,
                "requested_provider": route.provider,
                "requested_model": route.model,
                "model_slot": route.model_slot,
            }
            for role, route in routes.items()
        },
        "roles": role_receipts,
        "results": {
            "accepted_evidence_count": accepted_count,
            "scout_accepted_evidence_count": (
                len(artifacts["scout"]["accepted_evidence_ids"]) if "scout" in artifacts else None
            ),
            "populated_metric_count": populated_count,
            "null_metric_count": len(score.component_scores) - populated_count,
            "score": score_as_dict(score),
            "validator_verdict": validator_verdict,
            "validator_findings": (
                artifacts["validator"].get("findings") if "validator" in artifacts else None
            ),
            "decision": asdict(decision) if decision else None,
        },
        "control_comparison": {
            "control": {
                "source": "Product #001 evidence packet and deterministic v1 replay",
                "execution_class": "control/Codex-authored recorded role receipts",
                "score_status": "unscored",
                "overall_score": None,
                "evidence_coverage": 0.0,
                "decision_gate": control_gate,
            },
            "routed_replay": {
                "execution_class": "separately dispatched Hermes/Menta runtime roles",
                "score_status": score.score_status,
                "overall_score": score.overall_score,
                "evidence_coverage": score.evidence_coverage,
                "decision_gate": decision.gate if decision else None,
            },
            "deterministic_result_unchanged": bool(
                decision
                and score.score_status == "unscored"
                and score.overall_score is None
                and score.evidence_coverage == 0.0
                and decision.gate == control_gate
            ),
            "quality_claim": "No superiority claim; deterministic invariants only.",
        },
        "artifacts": {
            "directory": str(artifact_directory),
            "validated_role_outputs": {
                role: str(artifact_directory / f"{role}.output.json") for role in artifacts
            },
        },
    }


def _render_routed_card(
    packet: Mapping[str, Any],
    synthesizer: Mapping[str, Any],
    snapshot: Mapping[str, Any],
) -> str:
    lines = [
        f"# {str(packet['product_name']).upper()}",
        "",
        "**Artifact class:** Hermes/Menta routed replay narrative",
        "",
        f"**Decision gate:** {snapshot['decision_gate']}",
        "",
        str(synthesizer["executive_summary"]["text"]),
        "",
    ]
    headings = {
        "market": "Market",
        "demand": "Demand",
        "competition": "Competition",
        "supply": "Supply",
        "economics": "Economics",
        "regulatory_friction": "Regulatory friction",
        "product": "Product",
        "brandability": "Brandability",
        "content_potential": "Content potential",
    }
    for key, heading in headings.items():
        section = synthesizer["sections"][key]
        lines.extend(
            [
                f"## {heading}",
                "",
                str(section["text"]),
                "",
                f"Evidence: {', '.join(section['evidence_ids']) or 'none'}",
                "",
            ]
        )
    score_label = snapshot["overall_score"] if snapshot["overall_score"] is not None else "unscored"
    lines.extend(
        [
            "## Deterministic result",
            "",
            f"- Score: {score_label}",
            f"- Evidence coverage: {snapshot['evidence_coverage']:.1f}%",
            f"- Validator: {snapshot['validator_outcome']}",
            f"- Gate: {snapshot['decision_gate']}",
            f"- Maximum spend: ${snapshot['max_recommended_spend_usd']:.2f}",
            f"- Score snapshot: `{snapshot['score_id']}`",
            "",
            "## Strongest case against",
            "",
            str(synthesizer["strongest_case_against"]["text"]),
            "",
            "## Top 5 unknowns",
            "",
        ]
    )
    lines.extend(f"{index}. {value}" for index, value in enumerate(synthesizer["top_unknowns"], 1))
    lines.extend(["", "## Top 5 risks", ""])
    lines.extend(f"{index}. {value}" for index, value in enumerate(synthesizer["top_risks"], 1))
    lines.extend(
        [
            "",
            "## Next experiment",
            "",
            str(synthesizer["cheapest_next_experiment"]),
            "",
            "## Evidence index",
            "",
        ]
    )
    for item in packet["evidence"]:
        lines.append(
            f"- `{item['evidence_id']}` — [{item['source_title']}]({item['source_url']}) "
            f"({item['acceptance_state']})"
        )
    lines.extend(["", "_Narrative roles did not write score inputs or gate outputs._", ""])
    return "\n".join(lines)


def _collect_evidence_refs(value: object, known: set[str]) -> list[str]:
    found: set[str] = set()

    def visit(item: object) -> None:
        if isinstance(item, str) and item in known:
            found.add(item)
        elif isinstance(item, Mapping):
            for nested in item.values():
                visit(nested)
        elif isinstance(item, list):
            for nested in item:
                visit(nested)

    visit(value)
    return sorted(found)


def _compact_evidence(packet: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Keep every reviewed fact while removing transport-only citation metadata."""

    fields = (
        "evidence_id",
        "claim_class",
        "acceptance_state",
        "source_title",
        "observed_at",
        "notes",
        "payload",
    )
    return [
        {field: item.get(field) for field in fields}
        for item in cast(list[dict[str, Any]], packet["evidence"])
    ]


def _evidence_index(packet: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "evidence_id": item["evidence_id"],
            "acceptance_state": item["acceptance_state"],
            "source_title": item["source_title"],
            "source_url": item["source_url"],
        }
        for item in cast(list[dict[str, Any]], packet["evidence"])
    ]


def _known_string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text and text.upper() != "UNKNOWN" else None


def _known_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _known_float(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None
