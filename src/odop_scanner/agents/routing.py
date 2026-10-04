from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from ..config import project_root


class RoutingError(ValueError):
    """The Menta route or project registration cannot be resolved safely."""


@dataclass(frozen=True)
class RoleRouteSpec:
    role: str
    label: str
    requested_profile: str
    model_slot: str
    schema_path: Path
    independence_from: str | None


@dataclass(frozen=True)
class RoutingConfig:
    version: str
    sha256: str
    project_slug: str
    workspace: Path
    live_project_profile: Path
    live_registry: Path
    desired_registry: Path
    runtime_command: str
    timeout_seconds: int
    toolsets: tuple[str, ...]
    reasoning: str
    ignore_workspace_rules: bool
    roles: dict[str, RoleRouteSpec]


@dataclass(frozen=True)
class ResolvedRoute:
    role: str
    label: str
    requested_profile: str
    resolved_profile: str
    provider: str
    model: str
    model_slot: str
    registry_sha256: str
    schema_path: Path
    independence_from: str | None

    @property
    def route(self) -> str:
        return f"hermes-oneshot:{self.provider}/{self.model}"


def _read_yaml(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    value = yaml.safe_load(raw)
    if not isinstance(value, dict):
        raise RoutingError(f"YAML document is not an object: {path}")
    return value, hashlib.sha256(raw).hexdigest()


def _expanded_path(value: object, *, base: Path) -> Path:
    path = Path(str(value)).expanduser()
    return path if path.is_absolute() else (base / path).resolve()


def load_routing_config(path: Path | None = None) -> RoutingConfig:
    config_path = (path or project_root() / "config" / "routing.yaml").resolve()
    document, digest = _read_yaml(config_path)
    version = str(document.get("version", "")).strip()
    project = document.get("project")
    menta = document.get("menta")
    runtime = document.get("runtime")
    role_items = document.get("roles")
    if not version or not all(
        isinstance(value, dict) for value in (project, menta, runtime, role_items)
    ):
        raise RoutingError("routing config requires version, project, menta, runtime, and roles")
    assert isinstance(project, dict)
    assert isinstance(menta, dict)
    assert isinstance(runtime, dict)
    assert isinstance(role_items, dict)

    roles: dict[str, RoleRouteSpec] = {}
    for role, raw in role_items.items():
        if not isinstance(raw, dict):
            raise RoutingError(f"routing role {role} must be an object")
        roles[str(role)] = RoleRouteSpec(
            role=str(role),
            label=str(raw["label"]),
            requested_profile=str(raw["requested_profile"]),
            model_slot=str(raw.get("model_slot", "preferred_model")),
            schema_path=_expanded_path(raw["schema"], base=project_root()),
            independence_from=(
                str(raw["independence_from"]) if raw.get("independence_from") else None
            ),
        )
    required_roles = {"scout", "analyst", "validator", "synthesizer"}
    if set(roles) != required_roles:
        raise RoutingError(f"routing roles must be exactly {sorted(required_roles)}")
    timeout = int(runtime.get("timeout_seconds", 0))
    if timeout < 1:
        raise RoutingError("runtime timeout_seconds must be positive")
    toolsets = tuple(str(value) for value in runtime.get("toolsets", []))
    if not toolsets:
        raise RoutingError("runtime must declare at least one restricted toolset")
    reasoning = str(runtime.get("reasoning", "minimal"))
    if reasoning not in {"none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"}:
        raise RoutingError("runtime reasoning level is invalid")

    return RoutingConfig(
        version=version,
        sha256=digest,
        project_slug=str(project["slug"]),
        workspace=_expanded_path(project["workspace"], base=project_root()),
        live_project_profile=_expanded_path(project["live_profile"], base=project_root()),
        live_registry=_expanded_path(menta["live_registry"], base=project_root()),
        desired_registry=_expanded_path(menta["desired_registry"], base=project_root()),
        runtime_command=str(runtime.get("command", "hermes")),
        timeout_seconds=timeout,
        toolsets=toolsets,
        reasoning=reasoning,
        ignore_workspace_rules=bool(runtime.get("ignore_workspace_rules", True)),
        roles=roles,
    )


class MentaProfileResolver:
    def __init__(self, config: RoutingConfig):
        self.config = config
        self.registry, self.registry_sha256 = _read_yaml(config.live_registry)
        self.project_profile, _ = _read_yaml(config.live_project_profile)
        self._validate_registration()

    def _validate_registration(self) -> None:
        project = self.project_profile.get("project")
        if not isinstance(project, dict) or str(project.get("slug")) != self.config.project_slug:
            raise RoutingError("ODOP live project profile does not resolve to the configured slug")
        registered: set[str] = set(str(value) for value in project.get("required_profiles", []))
        for item in project.get("conditional_profiles", []):
            if isinstance(item, dict) and item.get("profile_id"):
                registered.add(str(item["profile_id"]))
        requested = {spec.requested_profile for spec in self.config.roles.values()}
        missing = requested - registered
        if missing:
            raise RoutingError(f"ODOP project profile is missing roles: {sorted(missing)}")

    def resolve_all(self) -> dict[str, ResolvedRoute]:
        routes = {role: self.resolve(spec) for role, spec in self.config.roles.items()}
        validator = routes["validator"]
        if validator.independence_from is None:
            raise RoutingError("Validator route must declare independence_from")
        assert_independent(routes[validator.independence_from], validator)
        return routes

    def resolve(self, spec: RoleRouteSpec) -> ResolvedRoute:
        profiles = self.registry.get("profiles")
        defaults = self.registry.get("profile_defaults")
        if not isinstance(profiles, dict) or not isinstance(defaults, dict):
            raise RoutingError("live Menta registry has no profiles/defaults")
        profile = profiles.get(spec.requested_profile)
        if not isinstance(profile, dict):
            raise RoutingError(f"Menta profile does not resolve: {spec.requested_profile}")
        default_staffing = defaults.get("staffing")
        profile_staffing = profile.get("staffing")
        if not isinstance(default_staffing, dict):
            default_staffing = {}
        if not isinstance(profile_staffing, dict):
            profile_staffing = {}
        staffing = {**default_staffing, **profile_staffing}
        selected = staffing.get(spec.model_slot)
        if not isinstance(selected, dict):
            raise RoutingError(
                f"Menta profile {spec.requested_profile} has no {spec.model_slot} route"
            )
        provider = str(selected.get("provider", "")).strip()
        model = str(selected.get("model", "")).strip()
        if not provider or not model:
            raise RoutingError(f"Menta route is incomplete for {spec.requested_profile}")
        if not spec.schema_path.is_file():
            raise RoutingError(f"role schema is missing: {spec.schema_path}")
        return ResolvedRoute(
            role=spec.role,
            label=spec.label,
            requested_profile=spec.requested_profile,
            resolved_profile=spec.requested_profile,
            provider=provider,
            model=model,
            model_slot=spec.model_slot,
            registry_sha256=self.registry_sha256,
            schema_path=spec.schema_path,
            independence_from=spec.independence_from,
        )


def assert_independent(producer: ResolvedRoute, validator: ResolvedRoute) -> None:
    if producer.resolved_profile == validator.resolved_profile:
        raise RoutingError("Validator resolved to the producer profile")
    if (producer.provider, producer.model) == (validator.provider, validator.model):
        raise RoutingError("Validator resolved to the producer provider/model")
    if producer.route == validator.route:
        raise RoutingError("Validator resolved to the producer route")
