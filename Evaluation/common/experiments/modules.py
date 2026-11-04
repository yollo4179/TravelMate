"""Adapters for existing server paths; the evaluation runner never hosts a second LLM."""
from __future__ import annotations

import hashlib
import json
import copy
from typing import Any

from common.execution.control import AttemptStatus, Operation, RunMode
from common.experiments.contracts import (
    CONVERSATION_OPTIONAL_FIELDS,
    CONVERSATION_REQUIRED_FIELDS,
    ConversationRouting,
    ModuleConfig,
    ModuleContext,
    ModuleInput,
    ModuleKind,
    ModuleRegistry,
    select_for_routing,
)
from tracks.search.api_contract import search_body, search_filters, unsupported_conditions
from tracks.search.collect_live import request_search


def http_request(route: str, body: dict[str, Any], server_url: str) -> dict[str, Any]:
    raw = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
    return {"method": "POST", "url": server_url + route, "route": route, "raw_body": raw,
            "body_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest()}


class SearchApiModule:
    def supports(self, kind: ModuleKind) -> bool:
        return kind == ModuleKind.SEARCH_API

    def request(self, supplied: ModuleInput, config: ModuleConfig, server_url: str) -> dict[str, Any]:
        missing = unsupported_conditions(supplied.case["input"]["conditions"])
        if missing:
            raise ValueError(f"Original conditions cannot be represented: {missing}")
        return http_request("/api/places/search", search_body(supplied.case, config.ranking_mode, config.response_limit), server_url)

    async def execute(self, supplied: ModuleInput, config: ModuleConfig, context: ModuleContext) -> dict[str, Any]:
        return await request_search(
            context.client, case=supplied.case, input_sha256=supplied.input_sha256,
            mode=config.ranking_mode, control=context.control, server_url=context.server_url,
            limit=config.response_limit, runtime=context.runtime, access_token=context.access_token,
        )


class ConversationApiModule:
    def supports(self, kind: ModuleKind) -> bool:
        return kind == ModuleKind.CONVERSATION_API

    def request(self, supplied: ModuleInput, config: ModuleConfig, server_url: str) -> dict[str, Any]:
        # Reuse the independent-filter projection; do not invent history or planning inputs.
        conditions = supplied.case["input"]["conditions"]
        missing = unsupported_conditions(conditions)
        if missing:
            raise ValueError(f"Conversation fixture needs an explicit future adapter for: {missing}")
        query = supplied.case["input"]["query"]
        if not isinstance(query, str) or not query.strip() or len(query) > 4000:
            raise ValueError("The full original conversation message must fit the 4000-character server contract")
        filters = search_filters(conditions)
        body = {"message": supplied.case["input"]["query"], "planningRequest": None, "history": [],
                "searchContext": {name: filters[name] for name in ("region", "city", "category", "excludePlaceIds", "area")}}
        if "api_request" in supplied.case:
            body = copy.deepcopy(supplied.case["api_request"])
            if (set(body) - CONVERSATION_OPTIONAL_FIELDS) != CONVERSATION_REQUIRED_FIELDS or body["message"] != query:
                raise ValueError("Explicit conversation inputs must preserve the original message and native envelope")
        request = http_request("/api/v1/conversation/turns", body, server_url)
        request["headers"] = {"Idempotency-Key": supplied.turn_key, "X-Conversation-Id": supplied.conversation_id,
                              "X-Evaluation-Case-Id": supplied.case["case_id"], "X-Evaluation-Input-Sha256": supplied.input_sha256}
        return request

    async def execute(self, supplied: ModuleInput, config: ModuleConfig, context: ModuleContext) -> dict[str, Any]:
        request = self.request(supplied, config, context.server_url)
        async def dispatch() -> dict[str, Any]:
            headers = {"Content-Type": "application/json", **request["headers"]}
            if context.access_token:
                headers["Authorization"] = "Bearer " + context.access_token
            response = await context.client.request("POST", request["url"], content=request["raw_body"].encode("utf-8"), headers=headers)
            return {"status_code": response.status_code, "raw_body": response.text,
                    "server_request_id": response.headers.get("x-request-id")}

        # This envelope is deliberately NOT a fabricated spring_execution_live scoring record.
        record = {"record_source": "conversation_http_experiment", "case_id": supplied.case["case_id"],
                  "input_sha256": supplied.input_sha256, "execution_mode": context.control.settings.mode.value,
                  "execution_status": AttemptStatus.NOT_RUN.value, "http_request": request,
                  "http_response": None, "native_response": None, "contract_checks": None,
                  "quality_status": "not_assessed", "internal_inference_calls": None,
                  "internal_search_calls": None, "input_count_cost_usd": None, "total_billed_cost_usd": None}
        try:
            response = await context.control.execute(Operation.CONVERSATION, supplied.case["case_id"], request, dispatch)
            record["http_response"] = response
            native = json.loads(response["raw_body"])
            record["native_response"] = native
            checks = conversation_checks(
                native,
                config,
                supplied.case.get("expected"),
                ConversationRouting.of(context.runtime or {}),
            )
            record["contract_checks"] = checks
            if response["status_code"] != 200 or not all(checks.values()):
                raise ValueError("Conversation HTTP response did not meet the explicit completion contract")
            record["execution_status"] = AttemptStatus.COMPLETED.value
        except Exception as exception:
            record["execution_status"] = AttemptStatus.FAILED.value
            record["error_type"] = type(exception).__name__
            context.control.stopped = True
        finally:
            receipt = context.control.last_attempt or {}
            record.update(dispatched=receipt.get("dispatched", False), duration_ms=receipt.get("duration_ms"), attempt_observation=receipt)
        if context.control.settings.mode == RunMode.MOCK:
            record["quality_status"] = "mock_regression_only"
        return record


class SingleLlmCompletion:
    def supports(self, routing: ConversationRouting) -> bool:
        return routing == ConversationRouting.SINGLE_LLM_V1

    def checks(self, native: dict[str, Any], expected: dict[str, Any]) -> dict[str, bool]:
        citations = native.get("citations")
        tools = native.get("toolResults")
        return {
            "completed": native.get("termination") == "COMPLETED",
            "message_present": isinstance(native.get("message"), str) and bool(native["message"].strip()),
            "message_source": native.get("messageSource") in expected["message_sources"],
            "one_model_turn": type(native.get("modelTurns")) is int and native["modelTurns"] == 1,
            "executed_tools": isinstance(tools, list) and [item.get("name") for item in tools] == expected["tool_names"],
            "response_type": native.get("type") in expected["response_types"],
            "citations": isinstance(citations, list) and (bool(citations) if expected["citations"] == "REQUIRED"
                                                         else not citations if expected["citations"] == "FORBIDDEN" else True),
        }


class LiliCompletion:
    """LiLi answers the turn with her line at once; branch, tool and job results are scored afterwards."""

    def supports(self, routing: ConversationRouting) -> bool:
        return routing == ConversationRouting.LILI_ROUTER_V1

    def checks(self, native: dict[str, Any], expected: dict[str, Any]) -> dict[str, bool]:
        dialogue = native.get("dialogue")
        return {
            "completed": native.get("termination") == "COMPLETED",
            "message_present": isinstance(native.get("message"), str) and bool(native["message"].strip()),
            "message_source": native.get("messageSource") == "LLM",
            "dialogue_present": isinstance(dialogue, list) and bool(dialogue),
        }


COMPLETION_CONTRACTS = (SingleLlmCompletion(), LiliCompletion())


def conversation_checks(
    native: Any,
    config: ModuleConfig,
    expected: dict[str, Any] | None = None,
    routing: ConversationRouting = ConversationRouting.SINGLE_LLM_V1,
) -> dict[str, bool]:
    if not isinstance(native, dict):
        return {"response_object": False}
    citations = native.get("citations")
    if expected is not None:
        return select_for_routing(COMPLETION_CONTRACTS, routing).checks(native, expected)
    return {
        "completed": native.get("termination") == "COMPLETED",
        "llm_message": native.get("messageSource") == "LLM" and isinstance(native.get("message"), str) and bool(native["message"].strip()),
        "one_model_turn": type(native.get("modelTurns")) is int and native["modelTurns"] == 1,
        "no_additional_tools": native.get("toolResults") == [],
        "response_type": config.expected_response_type is None or native.get("type") == config.expected_response_type,
        "citations_present": isinstance(citations, list) and (bool(citations) or not config.require_citations),
    }


DEFAULT_MODULES = ModuleRegistry((SearchApiModule(), ConversationApiModule()))
