"""LiLi routing scorer: the router decides with no evidence, the server runs the tool and the job answers with cuts."""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.execution.control import RunMode
from common.experiments.contracts import ConversationRouting
from common.experiments.modules import conversation_checks
from tracks.conversation.cases import LILI_SUITE, load_cases
from tracks.conversation.job_follow import FollowedJobKind, follow_job, select_follower
from tracks.conversation.score import score_case

SEARCH_CASE = "PLR-TM-palaces-01"
JOB_CASE = "CONV-JOB-owned"
EXCLUDE_SHOWN = "CONV-SEARCH-exclude-shown"
EXCLUDE_UNSEEN = "CONV-SEARCH-exclude-first"
PLAN_CASE = "CONV-PLAN-create"
OWNED_JOB_ID = "6f1fe6ee-1af2-4ea1-8d1f-d29f48cb1268"
EXCLUDED_PLACE = 173
EMOTIONS = ["NEUTRAL", "HAPPY", "EXCITED", "GUIDING", "THINKING"]
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
    "required": ["branch", "intent", "search_query", "exclude_positions", "emotion", "message", "choices"],
    "properties": {
        "branch": {"enum": ["CHAT", "CLARIFY", "SEARCH_PLACES", "GENERATE_PLAN", "GET_PLANNING_JOB"]},
        "intent": {"type": "string"},
        "search_query": {"type": ["string", "null"]},
        "exclude_positions": {"type": "array", "items": {"type": "integer", "minimum": 1, "maximum": 20}},
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
TWO_CUTS = [{"text": "이번엔 이쪽 어때?", "emotion": "HAPPY"}, {"text": "카드에 정리해 뒀어.", "emotion": "NEUTRAL"}]


class LiliTrace:
    """Builds one bound LIVE trace so each test can break exactly one rule."""

    def __init__(self, case: dict[str, Any], branch: str, query: str | None, native_type: str,
                 positions: list[int] | None = None) -> None:
        self.case = case
        self.request_id = "request-" + case["case_id"]
        body = json.dumps(case["api_request"], ensure_ascii=False)
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
                         "exclude_positions": positions or [], "emotion": cut["emotion"], "message": cut["text"], "choices": []}
        self.events: list[dict[str, Any]] = []
        self.add("API_REQUEST", {"bodySha256": self.record["http_request"]["body_sha256"], "rawBody": body}, "REQUEST")
        self.add("ROUTE", {"stage": "ROUTER", "durationMs": 900.0, "content": json.dumps(self.decision, ensure_ascii=False)})
        self.add("API_RESPONSE", {"httpStatus": 200, "response": self.native}, "REQUEST")
        self.add("TURN_RESULT", self.native)

    def add(self, event: str, payload: dict[str, Any], phase: str = "CONVERSATION") -> None:
        self.events.append({"eventId": f"event-{len(self.events)}", "requestId": self.request_id,
                            "caseId": self.case["case_id"], "inputSha256": self.case["input_sha256"],
                            "mode": "LIVE", "phase": phase, "event": event, "payload": payload})

    def tool(self, name: str, arguments: dict[str, Any], status: str = "SUCCEEDED") -> None:
        self.add("TOOL_RESULT", {"initiator": "LILI", "durationMs": 3.0, "result": {
            "name": name, "status": status, "arguments": json.dumps(arguments, ensure_ascii=False)}})

    def job(self, query: str, cuts: list[dict[str, str]] | None = None, excluded: list[int] | None = None,
            returned: list[int] | None = None) -> None:
        evidence = {"evidenceId": "ev-1", "original": {"source_id": "src-1", "chunk_text": QUOTE + " 근정전이 있다."}}
        candidates = [{"placeId": 311, "name": "경복궁", "selectedEvidence": [evidence]},
                      {"placeId": 10, "name": "운현궁", "selectedEvidence": []}]
        criteria = {"query": query, "excludePlaceIds": excluded or []}
        self.add("EVIDENCE_PREPARATION", {"query": query, "durationMs": 2500.0,
                                          "modelData": {"searchCriteria": criteria, "candidates": candidates}},
                 "RECOMMENDATION_GENERATION")
        places = [{"placeId": identifier} for identifier in (returned or [311, 10])]
        self.record["followed_job"] = {"kind": "RECOMMENDATION", "polls": 3, "wait_ms": 6000.0, "timed_out": False,
                                       "result": None, "job": {"status": "SUCCEEDED", "result": {
            "type": "PLACES", "messageSource": "LLM", "termination": "COMPLETED", "data": places,
            "dialogue": TWO_CUTS if cuts is None else cuts,
            "citations": [{"evidenceId": "ev-1", "placeId": 311, "sourceId": "src-1", "quote": QUOTE}]}}}


class LiliScoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ids = (SEARCH_CASE, JOB_CASE, EXCLUDE_SHOWN, EXCLUDE_UNSEEN, PLAN_CASE)
        cls.cases = {case["case_id"]: case for case in load_cases(LILI_SUITE, ids, {"owned_job_id": OWNED_JOB_ID})}

    def search_trace(self, cuts: list[dict[str, str]] | None = None) -> LiliTrace:
        trace = LiliTrace(self.cases[SEARCH_CASE], "SEARCH_PLACES", "서울 창경궁", "RECOMMENDATION_JOB")
        trace.tool("search_places", {"query": "서울 창경궁"})
        trace.job("서울 창경궁", cuts)
        return trace

    def exclusion_trace(self, resolved: list[int], applied: list[int], returned: list[int]) -> LiliTrace:
        trace = LiliTrace(self.cases[EXCLUDE_SHOWN], "SEARCH_PLACES", "종로 관광지", "RECOMMENDATION_JOB", [1])
        trace.add("EXCLUSION", {"status": "RESOLVED", "positions": [1], "placeIds": resolved,
                                "resultId": "fc4a7e8f-6fa7-46d6-9254-542ef2d7c342"})
        trace.tool("search_places", {"query": "종로 관광지", "exclude_place_ids": resolved})
        trace.job("종로 관광지", excluded=applied, returned=returned)
        return trace

    def plan_trace(self, job: dict[str, Any], draft: dict[str, Any] | None, timed_out: bool = False) -> LiliTrace:
        trace = LiliTrace(self.cases[PLAN_CASE], "GENERATE_PLAN", "종로 창경궁 일정", "PLANNING_JOB")
        trace.tool("generate_plan", {})
        trace.add("PLAN_DRAFT", {"status": job["status"], "output": "{...}", "candidateIds": [378],
                                 "failureType": None if job["status"] == "SUCCEEDED" else "ResponseStatusException",
                                 "failureMessage": job.get("errorMessage")}, "PLAN_GENERATION")
        trace.record["followed_job"] = {"kind": "PLANNING", "job": job, "result": draft, "polls": 12,
                                        "wait_ms": 36000.0, "timed_out": timed_out}
        return trace

    def score(self, trace: LiliTrace) -> dict[str, Any]:
        return score_case(trace.case, trace.record, trace.events, CONTRACT)

    def failed(self, trace: LiliTrace) -> list[str]:
        return [name for name, value in self.score(trace)["checks"].items() if value is False]

    def test_search_branch_with_job_cuts_and_member_citation_passes(self) -> None:
        scored = self.score(self.search_trace())
        self.assertEqual([], [name for name, value in scored["checks"].items() if value is False])
        self.assertEqual("passed", scored["automated_status"])
        self.assertIn("router_line_no_place_facts", [item["id"] for item in scored["semantic_criteria"]])

    def test_evidence_before_lili_decides_fails(self) -> None:
        trace = self.search_trace()
        trace.add("EVIDENCE_PREPARATION", {"query": trace.case["api_request"]["message"], "modelData": {}})
        self.assertIn("no_evidence_before_lili", self.failed(trace))

    def test_job_retrieval_with_another_query_fails(self) -> None:
        trace = LiliTrace(self.cases[SEARCH_CASE], "SEARCH_PLACES", "서울 창경궁", "RECOMMENDATION_JOB")
        trace.tool("search_places", {"query": "서울 창경궁"})
        trace.job(trace.case["api_request"]["message"])
        self.assertIn("job_query_is_lili_query", self.failed(trace))

    def test_single_cut_job_dialogue_fails(self) -> None:
        self.assertIn("job_dialogue_cuts", self.failed(self.search_trace(TWO_CUTS[:1])))

    def test_citation_outside_supplied_evidence_fails(self) -> None:
        trace = self.search_trace()
        trace.record["followed_job"]["job"]["result"]["citations"][0]["quote"] = "주차장이 넓다."
        self.assertIn("job_citation_membership", self.failed(trace))

    def test_naming_a_candidate_without_evidence_fails(self) -> None:
        cuts = [{"text": "경복궁 좋아. 운현궁도 조용하고 사적인 느낌이야.", "emotion": "HAPPY"}, TWO_CUTS[1]]
        self.assertIn("job_dialogue_no_unevidenced_places", self.failed(self.search_trace(cuts)))

    def test_internal_codes_in_any_line_fail(self) -> None:
        trace = LiliTrace(self.cases[JOB_CASE], "GET_PLANNING_JOB", None, "PLANNING_JOB")
        trace.native["dialogue"] = [{"text": "앗, 서버가 JOB_ID_NOT_FOUND라고 알려줬어.", "emotion": "THINKING"}]
        trace.native["message"] = trace.native["dialogue"][0]["text"]
        trace.tool("get_planning_job", {"job_id": OWNED_JOB_ID})
        scored = self.score(trace)
        self.assertFalse(scored["checks"]["no_internal_terms"])
        self.assertIn("JOB_ID_NOT_FOUND", scored["internal_terms_found"])

    def test_wrong_branch_and_choices_outside_clarify_fail(self) -> None:
        trace = LiliTrace(self.cases[SEARCH_CASE], "CHAT", None, "TEXT")
        trace.native["choices"] = ["궁궐", "시장"]
        failed = self.failed(trace)
        self.assertTrue({"lili_branch", "tool_selection", "choices_only_when_clarifying"} <= set(failed))

    def test_job_lookup_requires_the_id_the_user_wrote(self) -> None:
        trace = LiliTrace(self.cases[JOB_CASE], "GET_PLANNING_JOB", None, "PLANNING_JOB")
        trace.tool("get_planning_job", {"job_id": OWNED_JOB_ID})
        self.assertTrue(self.score(trace)["checks"]["tool_arguments"])
        wrong = LiliTrace(self.cases[JOB_CASE], "GET_PLANNING_JOB", None, "PLANNING_JOB")
        wrong.tool("get_planning_job", {"job_id": "00000000-0000-0000-0000-000000000000"})
        self.assertIn("tool_arguments", self.failed(wrong))

    def test_tool_not_run_by_server_fails(self) -> None:
        trace = self.search_trace()
        tool_event = next(event for event in trace.events if event["event"] == "TOOL_RESULT")
        tool_event["payload"] = {**copy.deepcopy(tool_event["payload"]), "initiator": "MODEL"}
        self.assertIn("tools_run_by_server", self.failed(trace))

    def test_exclusion_passes_only_when_position_id_filter_and_result_all_agree(self) -> None:
        scored = self.score(self.exclusion_trace([EXCLUDED_PLACE], [EXCLUDED_PLACE], [188, 272]))
        self.assertEqual([], [name for name, value in scored["checks"].items() if value is False])
        for check in ("exclusion_positions", "exclusion_resolved", "exclusion_filter_applied", "exclusion_absent_from_result"):
            self.assertTrue(scored["checks"][check], check)

    def test_exclusion_that_never_reached_the_search_filter_fails(self) -> None:
        self.assertIn("exclusion_filter_applied", self.failed(self.exclusion_trace([EXCLUDED_PLACE], [], [188])))

    def test_excluded_place_still_returned_fails(self) -> None:
        self.assertIn("exclusion_absent_from_result", self.failed(self.exclusion_trace([EXCLUDED_PLACE], [EXCLUDED_PLACE], [EXCLUDED_PLACE, 188])))

    def test_another_place_resolved_for_the_position_fails(self) -> None:
        failed = self.failed(self.exclusion_trace([188], [188], [272]))
        self.assertIn("exclusion_resolved", failed)
        self.assertIn("tool_arguments", failed)

    def test_exclusion_without_a_displayed_list_must_ask_back(self) -> None:
        asked = LiliTrace(self.cases[EXCLUDE_UNSEEN], "CLARIFY", None, "TEXT")
        asked.native["choices"] = ["이름으로 말하기", "목록 다시 보기"]
        self.assertEqual("passed", self.score(asked)["automated_status"])
        searched = LiliTrace(self.cases[EXCLUDE_UNSEEN], "SEARCH_PLACES", "종로 관광지", "RECOMMENDATION_JOB", [1])
        searched.tool("search_places", {"query": "종로 관광지"})
        self.assertTrue({"lili_branch", "tool_selection"} <= set(self.failed(searched)))

    def test_accepted_plan_whose_job_failed_is_not_a_completed_draft(self) -> None:
        job = {"status": "FAILED", "planId": None, "errorMessage": "방문 체류시간이 여행 가능 시간을 초과합니다."}
        scored = self.score(self.plan_trace(job, None))
        self.assertTrue(scored["checks"]["plan_job_accepted"])
        self.assertFalse(scored["checks"]["plan_job_succeeded"])
        self.assertFalse(scored["checks"]["plan_draft_retrieved"])
        self.assertEqual("failed", scored["automated_status"])
        self.assertEqual({"plan_accepted": True, "plan_draft_completed": False}, scored["stage_results"])
        self.assertEqual("방문 체류시간이 여행 가능 시간을 초과합니다.", scored["plan_generation"][0]["failureMessage"])

    def test_plan_still_running_at_the_time_limit_is_not_complete(self) -> None:
        scored = self.score(self.plan_trace({"status": "RUNNING", "planId": None}, None, timed_out=True))
        self.assertFalse(scored["checks"]["plan_job_succeeded"])

    def test_retrieved_draft_with_cuts_completes_the_plan(self) -> None:
        context = self.cases[PLAN_CASE]["api_request"]["planningRequest"]["context"]
        pin = {"placeId": 378, "sequence": 1, "stayMinutes": 60, "latitude": context["area"]["center"]["lat"],
               "longitude": context["area"]["center"]["lon"]}
        draft = {"planId": 77, "pins": [pin], "dialogue": TWO_CUTS}
        scored = self.score(self.plan_trace({"status": "SUCCEEDED", "planId": 77}, draft))
        self.assertEqual([], [name for name, value in scored["checks"].items() if value is False])
        self.assertEqual({"plan_accepted": True, "plan_draft_completed": True}, scored["stage_results"])

    def test_queued_search_turn_meets_the_lili_completion_contract_only(self) -> None:
        trace = self.search_trace()
        expected = trace.case["expected"]
        lili = conversation_checks(trace.native, None, expected, ConversationRouting.LILI_ROUTER_V1)
        self.assertTrue(all(lili.values()))
        self.assertFalse(all(conversation_checks(trace.native, None, expected).values()))
        silent = {**trace.native, "dialogue": []}
        self.assertFalse(conversation_checks(silent, None, expected, ConversationRouting.LILI_ROUTER_V1)["dialogue_present"])


class JobFollowTests(unittest.TestCase):
    class Control:
        def __init__(self, bodies: list[tuple[str, dict[str, Any]]]) -> None:
            self.bodies = bodies
            self.urls: list[str] = []

        async def execute(self, operation: Any, case_id: str, request: dict[str, Any], call: Any) -> dict[str, Any]:
            self.urls.append(request["url"])
            expected_path, body = self.bodies.pop(0)
            assert expected_path in request["url"], request["url"]
            return {"status_code": 200, "raw_body": json.dumps(body)}

    def follow(self, native: dict[str, Any], case: dict[str, Any], control: "JobFollowTests.Control") -> dict[str, Any]:
        context = SimpleNamespace(server_url="http://server", client=None, access_token="token")
        settings = SimpleNamespace(mode=RunMode.LIVE)
        return asyncio.run(follow_job({"native_response": native}, case, context, control, settings))

    def test_plan_creation_follows_the_job_and_then_reads_the_draft(self) -> None:
        job_id = "11111111-2222-3333-4444-555555555555"
        control = self.Control([("/api/v1/planning-jobs/" + job_id, {"status": "SUCCEEDED", "planId": 77}),
                                ("/api/v1/plans/77", {"planId": 77, "pins": []})])
        record = self.follow({"type": "PLANNING_JOB", "data": {"jobId": job_id}},
                             {"case_id": PLAN_CASE, "creates_plan": True}, control)
        followed = record["followed_job"]
        self.assertEqual(FollowedJobKind.PLANNING.value, followed["kind"])
        self.assertEqual(77, followed["result"]["planId"])
        self.assertFalse(followed["timed_out"])

    def test_a_failed_plan_job_reads_no_draft(self) -> None:
        job_id = "11111111-2222-3333-4444-555555555555"
        control = self.Control([("/api/v1/planning-jobs/" + job_id, {"status": "FAILED", "planId": None})])
        record = self.follow({"type": "PLANNING_JOB", "data": {"jobId": job_id}},
                             {"case_id": PLAN_CASE, "creates_plan": True}, control)
        self.assertIsNone(record["followed_job"]["result"])
        self.assertEqual(1, len(control.urls))

    def test_a_job_lookup_turn_is_not_followed_as_a_new_plan(self) -> None:
        self.assertIsNone(select_follower({"type": "PLANNING_JOB"}, {"case_id": JOB_CASE, "creates_plan": False}))
        self.assertIsNone(select_follower({"type": "TEXT"}, {"case_id": SEARCH_CASE}))


if __name__ == "__main__":
    unittest.main()
