"""Typed log groups and stable relative paths, independent of runtime versions."""
from enum import StrEnum


class EvaluationStage(StrEnum):
        # Run these units in order; an offline contract pass is not a live quality verdict.
        TOOL_CALL = "tool_call"
        RECOMMENDATION = "recommendation"
        PLAN = "plan"
        CONVERSATION = "conversation"


class TestLogPath(StrEnum):
        # Execution identity and limits: no credentials or environment file copies.
        RUN = "run.json"
        ATTEMPTS = "attempts.jsonl"
        INPUTS = "inputs.jsonl"
        SEARCH_CONTRACT = "search-contract.json"
        SERVER_CONTRACT = "server-contract.json"

        # Actual input/output and events: preserved independently of score/review revisions.
        RECORDS = "records.jsonl"
        EVENTS = "events.jsonl"

        # Contract checks and semantic judgments remain separate.
        SCORES = "scores.jsonl"
        REVIEW = "review.csv"
        SUMMARY = "summary.json"
