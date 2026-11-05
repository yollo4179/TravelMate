"""Load versioned expectations without sending them to the tested model."""
from __future__ import annotations

import copy
from enum import StrEnum
from pathlib import Path
from typing import Any
import uuid

from common.dataset.io import canonical_digest, read_json
from common.experiments.contracts import CONVERSATION_OPTIONAL_FIELDS, CONVERSATION_REQUIRED_FIELDS
from common.paths import DEFAULT_DATASET
from tracks.search.api_contract import search_body, RankingMode
from tracks.search.collect_live import selected_v14_inputs


DEFAULT_SUITE = DEFAULT_DATASET.parent / "conversation-smoke-v1/cases.json"
LILI_SUITE = DEFAULT_DATASET.parent / "conversation-smoke-v2/cases.json"
LILI_BOUNDARY_SUITE = DEFAULT_DATASET.parent / "conversation-smoke-v3/cases.json"
MAX_DISPLAYED_PLACES = 20


class SuiteVersion(StrEnum):
    SINGLE_LLM_V1 = "conversation-smoke-v1"
    LILI_ROUTER_V2 = "conversation-smoke-v2"
    LILI_BOUNDARY_V3 = "conversation-smoke-v3"


class PlanOutcome(StrEnum):
    ACCEPTED = "ACCEPTED"
    DRAFT_COMPLETED = "DRAFT_COMPLETED"
    # The server refuses the request before any job exists, e.g. a budget or a car trip it cannot plan yet.
    REJECTED = "REJECTED"
    # The job is accepted but its draft fails the server's rules, so it must end FAILED with a user-facing reason.
    FAILED = "FAILED"


class TurnOutcome(StrEnum):
    """How a turn must end when that matters more than which branch LiLi chose."""
    # Ends asking the user: LiLi's own CLARIFY or the server's ask-back after she picked a tool branch.
    ASK_BACK = "ASK_BACK"


class Capability(StrEnum):
    """Whether the server has the feature a request asks for; a request for a missing one is judged by that, not its intent label."""
    UNSUPPORTED = "UNSUPPORTED"


LILI_BRANCHES = {"CHAT", "CLARIFY", "SEARCH_PLACES", "GENERATE_PLAN", "GET_PLANNING_JOB"}


class DecisionType(StrEnum):
    ANSWER = "ANSWER"
    CLARIFICATION = "CLARIFICATION"
    TOOL_CALL = "TOOL_CALL"


class ToolType(StrEnum):
    SEARCH_PLACES = "search_places"
    GENERATE_PLAN = "generate_plan"
    GET_PLANNING_JOB = "get_planning_job"


def substitute(document: Any, bindings: dict[str, str]) -> Any:
    if isinstance(document, dict):
        return {key: substitute(value, bindings) for key, value in document.items()}
    if isinstance(document, list):
        return [substitute(value, bindings) for value in document]
    if isinstance(document, str):
        for key, value in bindings.items():
            document = document.replace("${" + key + "}", value)
        if "${" in document:
            raise ValueError("An explicitly selected case requires a missing runtime binding")
    return document


def load_cases(path: Path, selected: tuple[str, ...], bindings: dict[str, str]) -> list[dict[str, Any]]:
    if set(bindings) - {"owned_job_id"}:
        raise ValueError("Unknown runtime binding; only an actual owned_job_id is supported")
    if bindings.get("owned_job_id"):
        uuid.UUID(bindings["owned_job_id"])
    suite = read_json(path)
    SuiteVersion(suite.get("schema_version"))
    index = {case["case_id"]: case for case in suite["cases"]}
    if len(index) != len(suite["cases"]) or not selected or len(set(selected)) != len(selected) or not set(selected) <= index.keys():
        raise ValueError("Select unique, existing conversation cases")
    result = []
    for identifier in selected:
        case = substitute(copy.deepcopy(index[identifier]), bindings)
        expected = case["expected"]
        decision = DecisionType(expected["decision_type"])
        if [ToolType[name].value for name in expected["tool_types"]] != expected["tool_names"]:
            raise ValueError("Tool types must map to their existing native names")
        if (decision == DecisionType.TOOL_CALL) != bool(expected["tool_names"]):
            raise ValueError("Tool expectations conflict with the expected decision")
        if len(expected["tool_names"]) != len(expected["arguments"]):
            raise ValueError("Every expected call requires an explicit argument expectation")
        if case.get("source_case_id"):
            frozen = selected_v14_inputs(DEFAULT_DATASET, (case["source_case_id"],))[0]
            filters = search_body(frozen, RankingMode.RERANKED, 10)
            request = {"message": frozen["input"]["query"], "planningRequest": None, "history": [],
                       "searchContext": {key: filters[key] for key in ("region", "city", "category", "excludePlaceIds", "area")}}
            case.update(input=copy.deepcopy(frozen["input"]), input_sha256=frozen["input_sha256"], api_request=request)
        else:
            request = case["api_request"]
            context = request.get("searchContext") or {}
            conditions = {key: context.get(key) for key in ("region", "city", "category")}
            # Native API input is authoritative. Avoid projecting its area a second time.
            case.update(input={"query": request["message"], "conditions": conditions},
                        input_sha256=canonical_digest({"api_request": request}))
        request = case["api_request"]
        if (set(request) - CONVERSATION_OPTIONAL_FIELDS) != CONVERSATION_REQUIRED_FIELDS:
            raise ValueError("The suite must use the current native conversation request envelope")
        validate_exclusion(request.get("displayedResult"), expected.get("exclusion"))
        if "plan_outcome" in expected:
            PlanOutcome(expected["plan_outcome"])
        if "outcome" in expected:
            TurnOutcome(expected["outcome"])
        if "capability" in expected:
            Capability(expected["capability"])
            if expected.get("intent") is not None or expected["tool_names"]:
                raise ValueError("A request for a missing feature expects no intent label and no tool")
        branches = expected.get("lili_branch")
        if branches is not None and not set([branches] if isinstance(branches, str) else branches) <= LILI_BRANCHES:
            raise ValueError("Expected LiLi branches must be existing branches")
        if "query_terms" in expected and not all(isinstance(term, str) and term.strip() for term in expected["query_terms"]):
            raise ValueError("Query terms must be non-empty words")
        if not isinstance(request["message"], str) or not request["message"].strip() or len(request["message"]) > 4000:
            raise ValueError("The original conversation question must fit the server contract")
        result.append(case)
    return result


def validate_exclusion(displayed: dict[str, Any] | None, exclusion: dict[str, Any] | None) -> None:
    """The expected IDs must be exactly what the positions name in the list the app displayed."""
    if displayed is not None:
        uuid.UUID(displayed["resultId"])
        places = displayed["placeIds"]
        if not 1 <= len(places) <= MAX_DISPLAYED_PLACES or len(set(places)) != len(places) or any(
                type(place) is not int or place <= 0 for place in places):
            raise ValueError("A displayed result is 1..20 distinct positive place IDs in screen order")
    if exclusion is None:
        return
    if displayed is None:
        raise ValueError("An expected exclusion needs the displayed list it refers to")
    positions = exclusion["positions"]
    if not positions or any(type(position) is not int or not 1 <= position <= len(displayed["placeIds"]) for position in positions):
        raise ValueError("Exclusion positions must point inside the displayed list")
    if exclusion["place_ids"] != [displayed["placeIds"][position - 1] for position in positions]:
        raise ValueError("Expected excluded IDs must be the displayed IDs at those positions")
