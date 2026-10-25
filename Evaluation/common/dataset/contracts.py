"""Server envelope and tool contracts; these do not implement application endpoints."""
from __future__ import annotations

from enum import Enum
from typing import Any


class ResponseType(str, Enum):
    PLACES = "PLACES"
    PLAN = "PLAN"
    PLAN_DIFF = "PLAN_DIFF"
    CLARIFICATION = "CLARIFICATION"
    TEXT = "TEXT"


class ToolName(str, Enum):
    SEARCH = "search_places"
    CREATE_PLAN = "create_plan"
    MODIFY_PLAN = "modify_plan"
    CLARIFY = "ask_clarification"
    RECALL_MEMORY = "recall_memory"


class ExecutionStatus(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    MISSING = "missing"
    NOT_EVALUATED = "not_evaluated"
    NOT_RUN = "not_run"


MISSING_FIELD_LABELS = {
    "reference_place": "기준 장소",
    "distance_range": "원하는 거리 범위",
    "walking_range": "도보 거리 또는 시간",
    "origin": "출발 위치",
    "fitness_level": "체력 수준",
    "duration": "원하는 산행 시간",
    "origin_region": "출발 지역",
    "activity_type": "원하는 체험 종류",
    "residency": "성동구 거주 여부",
    "local_affiliation": "관내 학교 재학 또는 직장 재직 여부",
    "facility_type": "원하는 시설 종류",
    "excluded_place": "제외할 장소",
    "era": "관심 시대",
    "walking_route": "도보 경로 정보",
    "start_at": "여행 시작 시각",
    "end_at": "여행 종료 시각",
    "target_changeset": "되돌릴 계획 변경",
}

MISSING_FIELD_ALIASES = {
    **{label: identifier for identifier, label in MISSING_FIELD_LABELS.items()},
    "기준 성당": "reference_place", "기준 유적": "reference_place",
    "기준 공방": "reference_place", "기준 스파": "reference_place",
    "기준 한옥마을": "reference_place", "거리 범위": "distance_range",
    "현재 위치": "origin",
}


TOOL_RESPONSE_TYPES = {
    ToolName.SEARCH: ResponseType.PLACES,
    ToolName.CREATE_PLAN: ResponseType.PLAN,
    ToolName.MODIFY_PLAN: ResponseType.PLAN_DIFF,
    ToolName.CLARIFY: ResponseType.CLARIFICATION,
}

ENVELOPE_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["type", "message", "data", "conversationId"],
    "properties": {
        "type": {"enum": [kind.value for kind in ResponseType]},
        "message": {"type": "string", "minLength": 1},
        "data": {},
        "conversationId": {"type": "string", "minLength": 1},
    },
    "additionalProperties": False,
    "allOf": [
        {
            "if": {"properties": {"type": {"const": "PLACES"}}},
            "then": {"properties": {"data": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["placeId", "name"],
                    "properties": {
                        "placeId": {"type": "integer"},
                        "name": {"type": "string", "minLength": 1},
                    },
                },
            }}},
        },
        {
            "if": {"properties": {"type": {"const": "PLAN"}}},
            "then": {"properties": {"data": {
                "type": "object",
                "required": ["stops", "applied"],
                "properties": {
                    "stops": {"type": "array", "minItems": 1, "maxItems": 6, "items": {
                        "type": "object", "required": ["placeId"],
                        "properties": {
                            "placeId": {"type": "integer"},
                            "sequence": {"type": "integer", "minimum": 1},
                            "stayMinutes": {"type": "number", "minimum": 0},
                            "arrivalAt": {"type": "string"}, "departureAt": {"type": "string"},
                        },
                    }},
                    "applied": {"type": "boolean"},
                    "planId": {"type": ["string", "integer"]},
                    "version": {"type": "integer", "minimum": 1},
                    "proposalId": {"type": "string"},
                },
                "allOf": [{
                    "if": {"properties": {"applied": {"const": True}}},
                    "then": {"required": ["planId", "version"]},
                    "else": {"required": ["proposalId"]},
                }],
            }}},
        },
        {
            "if": {"properties": {"type": {"const": "PLAN_DIFF"}}},
            "then": {"properties": {"data": {
                "type": "object",
                "required": ["planId", "baseVersion", "changes", "applied"],
                "properties": {
                    "planId": {"type": ["string", "integer"]},
                    "baseVersion": {"type": "integer", "minimum": 1},
                    "changes": {"type": "array", "minItems": 1, "items": {
                        "type": "object", "required": ["operation"],
                        "properties": {"operation": {"enum": ["replace", "remove", "add", "reorder"]}},
                    }},
                    "applied": {"type": "boolean"},
                    "proposalId": {"type": "string"},
                    "version": {"type": "integer", "minimum": 1},
                },
                "allOf": [{
                    "if": {"properties": {"applied": {"const": True}}},
                    "then": {"required": ["version"]},
                    "else": {"required": ["proposalId"]},
                }],
            }}},
        },
        {
            "if": {"properties": {"type": {"const": "CLARIFICATION"}}},
            "then": {"properties": {"data": {
                "type": "object",
                "required": ["missing"],
                "properties": {"missing": {
                    "type": "array", "minItems": 1,
                    "items": {"type": "string", "minLength": 1},
                }},
            }}},
        },
        {
            "if": {"properties": {"type": {"const": "TEXT"}}},
            "then": {"properties": {"data": {"type": "null"}}},
        },
    ],
}

TOOL_CONTRACTS: dict[str, Any] = {
    "implementation_status": "evaluation_design_contract; not a claim that production tools exist",
    "llm_owns": ["message", "tool choice", "validated tool arguments", "place selection"],
    "server_owns": ["type", "data", "conversationId", "order", "time", "route", "persistence"],
    "tools": {
        ToolName.SEARCH.value: {
            "response_type": ResponseType.PLACES.value,
            "arguments": ["query", "region", "city", "exclude_place_ids", "area"],
            "effect": "read_only",
        },
        ToolName.CREATE_PLAN.value: {
            "response_type": ResponseType.PLAN.value,
            "arguments": ["place_ids", "start_at", "end_at", "origin", "transport"],
            "effect": "preview; server schedules selected IDs using trusted route/time inputs",
            "existing_design_mapping": "build_schedule plus plan preview; not direct DRAFT persistence",
        },
        ToolName.MODIFY_PLAN.value: {
            "response_type": ResponseType.PLAN_DIFF.value,
            "arguments": ["plan_id", "operation", "target_place_id", "new_place_id"],
            "effect": "preview; commit belongs to the confirmed backend flow",
        },
        ToolName.CLARIFY.value: {
            "response_type": ResponseType.CLARIFICATION.value,
            "arguments": ["missing"],
            "effect": "read_only clarification",
        },
        ToolName.RECALL_MEMORY.value: {
            "response_type": None,
            "arguments": ["query"],
            "effect": "owner-scoped read; internal evidence does not override the user task's public response type",
        },
    },
    "primary_result_policy": "Use the server-selected primary artifact of the user task, not blindly the last successful tool.",
    "confirmation_policy": "Preview before voice/button confirmation; report applied only after a successful server receipt.",
    "clarification_field_labels": MISSING_FIELD_LABELS,
    "routing_policy": "PostGIS stores spatial data; trusted route costs and a code optimizer determine order/time. Straight-line distance is not a road travel-time oracle.",
}

TOOL_ARGUMENT_SCHEMAS: dict[str, dict[str, Any]] = {
    ToolName.SEARCH.value: {
        "type": "object", "required": ["query"],
        "properties": {
            "query": {"type": "string", "minLength": 1},
            "region": {"type": ["string", "null"]}, "city": {"type": ["string", "null"]},
            "exclude_place_ids": {"type": "array", "uniqueItems": True, "items": {"type": "integer"}},
            "area": {"type": ["object", "null"]},
        }, "additionalProperties": False,
    },
    ToolName.CREATE_PLAN.value: {
        "type": "object", "required": ["place_ids", "start_at", "end_at", "origin", "transport"],
        "properties": {
            "place_ids": {"type": "array", "minItems": 1, "maxItems": 6, "uniqueItems": True, "items": {"type": "integer"}},
            "start_at": {"type": "string"}, "end_at": {"type": "string"},
            "origin": {"type": "object", "required": ["lat", "lon"], "properties": {
                "lat": {"type": "number", "minimum": -90, "maximum": 90},
                "lon": {"type": "number", "minimum": -180, "maximum": 180},
            }, "additionalProperties": False},
            "transport": {"enum": ["WALK", "CAR"]},
        }, "additionalProperties": False,
    },
    ToolName.MODIFY_PLAN.value: {
        "type": "object", "required": ["plan_id", "operation"],
        "properties": {
            "plan_id": {"type": ["string", "integer"]},
            "operation": {"enum": ["replace", "remove", "add", "reorder"]},
            "target_place_id": {"type": "integer"}, "new_place_id": {"type": "integer"},
        },
        "allOf": [
            {"if": {"properties": {"operation": {"const": "replace"}}}, "then": {"required": ["target_place_id", "new_place_id"]}},
            {"if": {"properties": {"operation": {"enum": ["remove", "reorder"]}}}, "then": {"required": ["target_place_id"]}},
            {"if": {"properties": {"operation": {"const": "add"}}}, "then": {"required": ["new_place_id"]}},
        ],
        "additionalProperties": False,
    },
    ToolName.CLARIFY.value: {
        "type": "object", "required": ["missing"],
        "properties": {"missing": {"type": "array", "minItems": 1, "uniqueItems": True, "items": {"type": "string", "enum": list(MISSING_FIELD_LABELS)}}},
        "additionalProperties": False,
    },
    ToolName.RECALL_MEMORY.value: {
        "type": "object", "required": ["query"],
        "properties": {"query": {"type": "string", "minLength": 1}},
        "additionalProperties": False,
    },
}
