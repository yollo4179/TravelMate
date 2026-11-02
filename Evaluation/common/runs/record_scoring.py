"""Select one record contract without coercing HTTP evidence into an agent response."""
from __future__ import annotations

from typing import Any, Protocol

from common.observability.search_records import is_search_api_record, search_record_error
from common.runs.tracks import Track
from tracks.end_to_end.score import evaluate_record
from tracks.search.score_ranking import score_search_api_record


class RecordScorer(Protocol):
    def supports(self, record: dict[str, Any]) -> bool: ...

    def validate(self, case: dict[str, Any], record: dict[str, Any], track: Track) -> str | None: ...

    def score(self, case: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]: ...


class SearchApiScorer:
    def supports(self, record: dict[str, Any]) -> bool:
        return is_search_api_record(record)

    def validate(self, case: dict[str, Any], record: dict[str, Any], track: Track) -> str | None:
        if track != Track.SEARCH:
            return "direct_search_does_not_observe_agent_or_plan_quality"
        return search_record_error(case, record)

    def score(self, case: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
        return score_search_api_record(case, record)


class AgentScorer:
    def supports(self, record: dict[str, Any]) -> bool:
        return not is_search_api_record(record)

    def validate(self, case: dict[str, Any], record: dict[str, Any], track: Track) -> str | None:
        if not isinstance(record.get("tool_calls"), list) or "response" not in record:
            return "record_requires_response_and_explicit_tool_calls_array"
        return None

    def score(self, case: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
        return evaluate_record(case, record)


SCORERS: tuple[RecordScorer, ...] = (SearchApiScorer(), AgentScorer())


def scorer_for(record: dict[str, Any]) -> RecordScorer:
    matching = [scorer for scorer in SCORERS if scorer.supports(record)]
    if len(matching) != 1:
        raise ValueError("Exactly one record scorer must support the original observation")
    return matching[0]
