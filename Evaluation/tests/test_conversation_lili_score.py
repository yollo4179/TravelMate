"""LiLi routing scorer: the router decides with no evidence, the server runs the tool and the job answers with cuts."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tracks.conversation.cases import DEFAULT_SUITE, load_cases
from tracks.conversation.score import score_case

SEARCH_CASE = "PLR-TM-palaces-01"
JOB_CASE = "CONV-JOB-owned"
OWNED_JOB_ID = "6f1fe6ee-1af2-4ea1-8d1f-d29f48cb1268"
EMOTIONS = ["NEUTRAL", "HAPPY", "EXCITED"]
CUT_SCHEMA = {
    "type": "array",
    "minItems": 2,
    "maxItems": 4,
    "items": {
        "type": "object",
        "additionalProperties": False,
        "required": ["text", "emotion"],
        "properties": {"text": {"type": "string"}, "emotion": {"enum": EMOTIONS}},
    },
}
ROUTER_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["branch", "intent", "search_query", "emotion", "message", "choices"],
    "properties": {
        "branch": {"enum": ["CHAT", "CLARIFY", "SEARCH_PLACES", "GENERATE_PLAN", "GET_PLANNING_JOB"]},
        "intent": {"type": "string"},
        "search_query": {"type": ["string", "null"]},
        "emotion": {"enum": EMOTIONS},
        "message": {"type": "string"},
        "choices": {"type": "array", "maxItems": 3},
    },
}
CONTRACT = {
    "routing": "LILI_ROUTER_V1",
    "provider": "OPENAI",
    "model": "gpt-5.4-mini-2026-03-17",
    "answer_schema": {"properties": {"emotion": {"enum": EMOTIONS}}},
    "lili": {"router_schema": ROUTER_SCHEMA, "recommendation_schema": {"properties": {"dialogue": CUT_SCHEMA}}},
}
QUOTE = "경복궁은 조선의 법궁이다."


class LiliTrace:
    """Builds one bound LIVE trace so each test can break exactly one rule."""

    def __init__(self, case: dict[str, Any], branch: str, query: str | None, native_type: str) -> None:
        self.case = case
        self.request_id = "request-" + case["case_id"]
        body = json.dumps({"message": case["api_request"]["message"]}, ensure_ascii=False)
        headers = {"Idempotency-Key": "turn-1", "X-Conversation-Id": "conversation-1"}
        cut = {"text": "좋아, 바로 찾아볼게!", "emotion": "EXCITED"}
        self.native = {"requestId": self.request_id, "turnId": "turn-1", "conversationId": "conversation-1",
                       "type": native_type, "intent": case["expected"].get("intent"), "messageSource": "LLM",
                       "message": cut["text"], "emotion": cut["emotion"], "dialogue": [cut], "choices": [],
                       "termination": "COMPLETED", "data": {"jobId": "11111111-2222-3333-4444-555555555555"}}
        self.record = {"case_id": case["case_id"], "execution_mode": "LIVE", "native_response": self.native,
                       "http_request": {"raw_body": body, "body_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
                                        "headers": headers}}
        self.decision = {"branch": branch, "intent": self.native["intent"], "search_query": query,
                         "emotion": cut["emotion"], "message": cut["text"], "choices": []}
        self.events: list[dict[str, Any]] = []
        self.add("API_REQUEST", {"bodySha256": self.record["http_request"]["body_sha256"], "rawBody": body}, "REQUEST")
        self.add("ROUTE", {"stage": "ROUTER", "durationMs": 900.0,
                           "content": json.dumps(self.decision, ensure_ascii=False)})
        self.add("API_RESPONSE", {"httpStatus": 200, "response": self.native}, "REQUEST")
        self.add("TURN_RESULT", self.native)

    def add(self, event: str, payload: dict[str, Any], phase: str = "CONVERSATION") -> None:
        self.events.append({"eventId": f"event-{len(self.events)}", "requestId": self.request_id,
                            "caseId": self.case["case_id"], "inputSha256": self.case["input_sha256"],
                            "mode": "LIVE", "phase": phase, "event": event, "payload": payload})

    def tool(self, name: str, arguments: dict[str, Any]) -> None:
        self.add("TOOL_RESULT", {"initiator": "LILI", "durationMs": 3.0,
                                 "result": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)}})

    def job(self, query: str, cuts: int = 2) -> None:
        evidence = {"evidenceId": "ev-1", "original": {"source_id": "src-1", "chunk_text": QUOTE + " 근정전이 있다."}}
        self.add("EVIDENCE_PREPARATION", {"query": query, "durationMs": 2500.0,
                                          "modelData": {"candidates": [{"placeId": 311, "selectedEvidence": [evidence]}]}},
                 "RECOMMENDATION_GENERATION")
        dialogue = [{"text": "경복궁 어때?", "emotion": "HAPPY"}, {"text": "카드에 정리해 뒀어.", "emotion": "NEUTRAL"}]
        self.record["recommendation_job"] = {"status": "SUCCEEDED", "result": {
            "type": "PLACES", "messageSource": "LLM", "termination": "COMPLETED", "dialogue": dialogue[:cuts],
            "citations": [{"evidenceId": "ev-1", "placeId": 311, "sourceId": "src-1", "quote": QUOTE}]}}


class LiliScoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        bindings = {"owned_job_id": OWNED_JOB_ID}
        cls.cases = {case["case_id"]: case for case in load_cases(DEFAULT_SUITE, [SEARCH_CASE, JOB_CASE], bindings)}

    def search_trace(self) -> LiliTrace:
        trace = LiliTrace(self.cases[SEARCH_CASE], "SEARCH_PLACES", "서울 고궁 산책", "RECOMMENDATION_JOB")
        trace.tool("search_places", {"query": "서울 고궁 산책"})
        trace.job("서울 고궁 산책")
        return trace

    def score(self, trace: LiliTrace) -> dict[str, Any]:
        return score_case(trace.case, trace.record, trace.events, CONTRACT)

    def test_search_branch_with_job_cuts_and_member_citation_passes(self) -> None:
        scored = self.score(self.search_trace())
        failed = [name for name, value in scored["checks"].items() if value is False]
        self.assertEqual([], failed)
        self.assertEqual("passed", scored["automated_status"])
        self.assertIn("router_line_no_place_facts", [item["id"] for item in scored["semantic_criteria"]])

    def test_evidence_before_lili_decides_fails(self) -> None:
        trace = self.search_trace()
        trace.add("EVIDENCE_PREPARATION", {"query": trace.case["api_request"]["message"], "modelData": {}})
        self.assertFalse(self.score(trace)["checks"]["no_evidence_before_lili"])

    def test_job_retrieval_with_another_query_fails(self) -> None:
        trace = LiliTrace(self.cases[SEARCH_CASE], "SEARCH_PLACES", "서울 고궁 산책", "RECOMMENDATION_JOB")
        trace.tool("search_places", {"query": "서울 고궁 산책"})
        trace.job(trace.case["api_request"]["message"])
        self.assertFalse(self.score(trace)["checks"]["job_query_is_lili_query"])

    def test_single_cut_job_dialogue_fails(self) -> None:
        trace = LiliTrace(self.cases[SEARCH_CASE], "SEARCH_PLACES", "서울 고궁 산책", "RECOMMENDATION_JOB")
        trace.tool("search_places", {"query": "서울 고궁 산책"})
        trace.job("서울 고궁 산책", cuts=1)
        self.assertFalse(self.score(trace)["checks"]["job_dialogue_cuts"])

    def test_citation_outside_supplied_evidence_fails(self) -> None:
        trace = self.search_trace()
        trace.record["recommendation_job"]["result"]["citations"][0]["quote"] = "주차장이 넓다."
        self.assertFalse(self.score(trace)["checks"]["job_citation_membership"])

    def test_wrong_branch_and_choices_outside_clarify_fail(self) -> None:
        trace = LiliTrace(self.cases[SEARCH_CASE], "CHAT", None, "TEXT")
        trace.native["choices"] = ["궁궐", "시장"]
        checks = self.score(trace)["checks"]
        self.assertFalse(checks["lili_branch"])
        self.assertFalse(checks["tool_selection"])
        self.assertFalse(checks["choices_only_when_clarifying"])

    def test_job_lookup_requires_the_id_the_user_wrote(self) -> None:
        case = self.cases[JOB_CASE]
        trace = LiliTrace(case, "GET_PLANNING_JOB", None, "PLANNING_JOB")
        trace.tool("get_planning_job", {"job_id": OWNED_JOB_ID})
        self.assertTrue(self.score(trace)["checks"]["tool_arguments"])
        wrong = LiliTrace(case, "GET_PLANNING_JOB", None, "PLANNING_JOB")
        wrong.tool("get_planning_job", {"job_id": "00000000-0000-0000-0000-000000000000"})
        self.assertFalse(self.score(wrong)["checks"]["tool_arguments"])

    def test_tool_not_run_by_server_fails(self) -> None:
        trace = self.search_trace()
        tool_event = next(event for event in trace.events if event["event"] == "TOOL_RESULT")
        tool_event["payload"] = {**copy.deepcopy(tool_event["payload"]), "initiator": "MODEL"}
        self.assertFalse(self.score(trace)["checks"]["tools_run_by_server"])


if __name__ == "__main__":
    unittest.main()
