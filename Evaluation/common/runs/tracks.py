"""Evaluation views of one agent, not independently deployed LLMs."""
from enum import Enum
from typing import Any


class Track(str, Enum):
    SEARCH = "search"
    TOOL_CALL = "tool_call"
    PLAN = "plan"
    STATE = "state"
    MEMORY = "memory"
    BEHAVIOR = "behavior"
    PERSONA = "persona"
    MESSAGE = "message"
    END_TO_END = "end_to_end"


COMMON_METRICS = {"response_type_accuracy", "envelope_schema_valid", "conversation_id_matches", "server_data_unchanged", "server_type_matches_primary_result"}
TOOL_METRICS = {"tool_name_and_hard_args_accuracy", "tool_precision", "tool_recall", "tool_f1", "tool_argument_schema_valid"}
PLAN_METRICS = {"selection_ids_valid", "required_places_included", "excluded_places_omitted", "selection_relevance_ratio", "selection_count_valid", "server_preserves_selected_ids", "schedule_within_window", "route_cost_ratio", "route_time_consistent"}
STATE_METRICS = {"preview_not_reported_as_applied", "observed_plan_state_preserved", "observed_nonplan_memory_preserved", "confirmation_precedes_apply", "observed_commit_version_matches"}
MEMORY_METRICS = {"inferred_memory_requires_confirmation", "explicit_preference_extraction_correct"}


def matches_track(case: dict[str, Any], track: Track) -> bool:
    if track == Track.END_TO_END:
        return True
    source_track = "message" if track == Track.PERSONA else track.value
    return source_track in case["evaluation_tracks"]


def metric_is_selected(name: str, track: Track) -> bool:
    if track == Track.END_TO_END or name in COMMON_METRICS:
        return True
    names = {
        Track.TOOL_CALL: TOOL_METRICS,
        Track.PLAN: PLAN_METRICS,
        Track.STATE: STATE_METRICS,
        Track.MEMORY: MEMORY_METRICS,
        Track.BEHAVIOR: TOOL_METRICS | STATE_METRICS,
        Track.MESSAGE: TOOL_METRICS,
        Track.PERSONA: set(),
    }
    if track == Track.SEARCH:
        return name.startswith(("top_", "recall_at_", "precision_at_", "f1_at_", "mrr_at_", "map_at_", "ndcg_at_", "judged_at_")) or name == "returned_place_ids_unique"
    if track == Track.MEMORY and name.startswith("memory_"):
        return True
    return name in names.get(track, set())
