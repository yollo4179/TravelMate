"""Typed module selection and explicit, bounded experiment configuration."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
import re
from typing import Any, Protocol, TypeVar
from urllib.parse import urlsplit

from common.dataset.io import canonical_digest, digest, read_json
from common.execution.control import ExecutionSettings, Operation, RunMode
from tracks.search.api_contract import RankingMode


class ModuleKind(StrEnum):
    SEARCH_API = "SEARCH_API"
    CONVERSATION_API = "CONVERSATION_API"


@dataclass(frozen=True, kw_only=True)
class ModuleConfig:
    identifier: str
    kind: ModuleKind
    ranking_mode: RankingMode | None
    response_limit: int | None
    expected_response_type: str | None
    require_citations: bool
    # Backend settings are references, not silently applied client-side overrides.
    backend_profile: dict[str, Any]

    @classmethod
    def load(cls, document: dict[str, Any]) -> ModuleConfig:
        required = {"id", "module", "ranking_mode", "response_limit", "expected_response_type", "require_citations", "backend_profile"}
        if set(document) != required or not re.fullmatch(r"[A-Za-z0-9_-]+", document["id"]):
            raise ValueError("Each variant needs the documented fields and a simple unique ID")
        kind = ModuleKind(document["module"])
        ranking = RankingMode(document["ranking_mode"]) if document["ranking_mode"] is not None else None
        if (kind == ModuleKind.SEARCH_API) != (ranking is not None):
            raise ValueError("Only SEARCH_API explicitly selects a ranking mode")
        limit = document["response_limit"]
        if kind == ModuleKind.SEARCH_API and (type(limit) is not int or not 1 <= limit <= 20):
            raise ValueError("Search response_limit must be within 1..20")
        if kind == ModuleKind.CONVERSATION_API and limit is not None:
            raise ValueError("Conversation response_limit is server-owned; use null rather than an ignored override")
        expected = document["expected_response_type"]
        if expected not in (None, "TEXT", "PLACES", "PLANNING_JOB", "DRAFT", "ERROR"):
            raise ValueError("Unknown expected native response type")
        if type(document["require_citations"]) is not bool or not isinstance(document["backend_profile"], dict):
            raise ValueError("Explicit citation policy and backend profile are required")
        if kind == ModuleKind.SEARCH_API and (expected is not None or document["require_citations"]):
            raise ValueError("Search-only collection has no generated response type or citations")
        return cls(identifier=document["id"], kind=kind, ranking_mode=ranking, response_limit=limit,
                   expected_response_type=expected, require_citations=document["require_citations"],
                   backend_profile=document["backend_profile"])


@dataclass(frozen=True, kw_only=True)
class ExperimentConfig:
    source: Path
    dataset: Path
    dataset_manifest_sha256: str
    execution: ExecutionSettings
    variants: tuple[ModuleConfig, ...]
    server_url: str
    token_env: str
    runtime_record: Path
    runtime_sha256: str
    fixtures: Path | None
    configuration_sha256: str

    @classmethod
    def load(cls, path: Path) -> ExperimentConfig:
        source = path.resolve()
        document = read_json(source)
        required = {"schema_version", "dataset", "dataset_manifest_sha256", "execution", "variants", "server_url", "token_env", "runtime_record", "runtime_sha256", "fixtures"}
        if set(document) != required or document["schema_version"] != "module-experiment-v1":
            raise ValueError("Unknown experiment contract or fields")
        configuration_hash = digest(source)
        execution = ExecutionSettings.from_document(document["execution"], configuration_sha256=configuration_hash)
        # A server conversation already searches and calls its model. Do not add a second search/model here.
        if set(execution.max_calls) - {Operation.SEARCH, Operation.CONVERSATION} or execution.parameters:
            raise ValueError("This runner accepts search/conversation caps only and no hidden transport parameters")
        if execution.model is not None or execution.max_output_tokens is not None:
            raise ValueError("Provider settings belong to the server profile, not an ignored runner override")
        variants = tuple(ModuleConfig.load(item) for item in document["variants"])
        if not variants or len({item.identifier for item in variants}) != len(variants):
            raise ValueError("Select nonempty variants with unique IDs")
        parsed = urlsplit(document["server_url"])
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ("", "/"):
            raise ValueError("server_url must be an explicit credential-free origin")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", document["token_env"]):
            raise ValueError("token_env names an environment variable, never its secret value")
        def resolve(value: str) -> Path:
            return (source.parent / value).resolve()
        fixtures = resolve(document["fixtures"]) if document["fixtures"] is not None else None
        if (execution.mode == RunMode.MOCK) != (fixtures is not None):
            raise ValueError("MOCK requires fixtures; LIVE forbids fixtures")
        runtime_record = resolve(document["runtime_record"])
        if digest(runtime_record) != document["runtime_sha256"]:
            raise ValueError("Runtime record hash differs from the explicit configuration")
        # The one active server cannot simultaneously run two different model/prompt/evidence profiles.
        if len({canonical_digest(item.backend_profile) for item in variants}) != 1:
            raise ValueError("One invocation uses one backend profile; change settings on the same server between runs")
        return cls(source=source, dataset=resolve(document["dataset"]), dataset_manifest_sha256=document["dataset_manifest_sha256"], execution=execution, variants=variants,
                   server_url=document["server_url"].rstrip("/"), token_env=document["token_env"],
                   runtime_record=runtime_record, runtime_sha256=document["runtime_sha256"], fixtures=fixtures,
                   configuration_sha256=configuration_hash)


@dataclass(kw_only=True)
class ModuleInput:
    case: dict[str, Any]
    input_sha256: str
    conversation_id: str
    turn_key: str


# Native conversation request fields a case may add to the required envelope; anything else is rejected.
CONVERSATION_OPTIONAL_FIELDS = frozenset({"intentHint", "displayedResult"})
CONVERSATION_REQUIRED_FIELDS = frozenset({"message", "planningRequest", "history", "searchContext"})


class ConversationRouting(StrEnum):
    SINGLE_LLM_V1 = "SINGLE_LLM_V1"
    LILI_ROUTER_V1 = "LILI_ROUTER_V1"

    @classmethod
    def of(cls, server_contract: dict[str, Any]) -> ConversationRouting:
        # Contracts recorded before routing was selectable all came from the single-LLM loop.
        return cls(server_contract.get("routing") or cls.SINGLE_LLM_V1)


class RoutingStrategy(Protocol):
    def supports(self, routing: ConversationRouting) -> bool: ...


RoutingStrategyType = TypeVar("RoutingStrategyType", bound=RoutingStrategy)


def select_for_routing(
    strategies: tuple[RoutingStrategyType, ...],
    routing: ConversationRouting,
) -> RoutingStrategyType:
    matching = [strategy for strategy in strategies if strategy.supports(routing)]
    if len(matching) != 1:
        raise ValueError(f"Exactly one implementation must support {routing}; found {len(matching)}")
    return matching[0]


@dataclass(kw_only=True)
class ModuleContext:
    server_url: str
    runtime: dict[str, Any]
    control: Any
    client: Any = None
    access_token: str | None = None


class EvaluationModule(Protocol):
    def supports(self, kind: ModuleKind) -> bool: ...

    def request(self, supplied: ModuleInput, config: ModuleConfig, server_url: str) -> dict[str, Any]: ...

    async def execute(self, supplied: ModuleInput, config: ModuleConfig, context: ModuleContext) -> dict[str, Any]: ...


class ModuleRegistry:
    def __init__(self, modules: tuple[EvaluationModule, ...]) -> None:
        self.modules = modules

    def select(self, kind: ModuleKind) -> EvaluationModule:
        matching = [module for module in self.modules if module.supports(kind)]
        if len(matching) != 1:
            raise ValueError(f"Exactly one implementation must support {kind}; found {len(matching)}")
        return matching[0]
