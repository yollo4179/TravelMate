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
from common.experiments.contracts import ConversationRouting, ModuleInput
from common.experiments.modules import ConversationApiModule, conversation_checks
from tracks.conversation.cases import LILI_BOUNDARY_SUITE, LILI_SUITE, load_cases
from tracks.conversation.job_follow import FollowedJobKind, follow_job, select_follower
from tracks.conversation.lili_score import unevidenced_places_named
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
    "required": ["branch", "intent", "search_query", "requested_region", "exclude_positions", "emotion", "message", "choices"],
    "properties": {
        "branch": {"enum": ["CHAT", "CLARIFY", "SEARCH_PLACES", "GENERATE_PLAN", "GET_PLANNING_JOB"]},
        "intent": {"type": "string"},
        "search_query": {"type": ["string", "null"]},
        "requested_region": {"type": ["string", "null"]},
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
        self.decision = {"branch": branch, "intent": self.native["intent"], "search_query": query, "requested_region": None,
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

    def test_a_place_said_without_its_catalog_prefix_is_still_caught(self) -> None:
        candidates = [{"name": "창경궁", "selectedEvidence": [1]}, {"name": "서울 운현궁", "selectedEvidence": []},
                      {"name": "창경궁 홍화문", "selectedEvidence": []}, {"name": "조계사(서울)", "selectedEvidence": []}]
        self.assertEqual(["운현궁"], unevidenced_places_named(["창경궁이 맞아. 운현궁도 떠올라."], candidates))
        self.assertEqual(["조계사"], unevidenced_places_named(["조계사 쪽도 봐."], candidates))
        self.assertEqual([], unevidenced_places_named(["창경궁이 딱 맞아."], candidates))

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

    def test_a_field_name_in_the_shown_plan_description_fails(self) -> None:
        context = self.cases[PLAN_CASE]["api_request"]["planningRequest"]["context"]
        pin = {"placeId": 378, "sequence": 1, "stayMinutes": 60, "latitude": context["area"]["center"]["lat"],
               "longitude": context["area"]["center"]["lon"], "explanation": "왕실 생활공간 둘러보기"}
        draft = {"planId": 77, "pins": [pin], "dialogue": TWO_CUTS,
                 "description": "requiredStops를 정확히 한 번 포함하도록 구성했어."}
        scored = self.score(self.plan_trace({"status": "SUCCEEDED", "planId": 77}, draft))
        self.assertFalse(scored["checks"]["no_internal_terms"])
        self.assertIn("requiredStops", scored["internal_terms_found"])

    # Codex r3 review: the CSV carried only LiLi's first line, so a reviewer missed the final explanation and plan.
    def test_review_export_carries_the_final_answer_the_draft_and_what_the_model_was_given(self) -> None:
        import csv
        import tempfile
        from tracks.conversation.review import export_review
        pin = {"placeId": 378, "name": "창경궁", "sequence": 1, "stayMinutes": 60, "explanation": "왕실 생활공간"}
        draft = {"planId": 77, "pins": [pin], "dialogue": TWO_CUTS, "description": "창경궁 중심 초안",
                 "context": {"startAt": "10:00", "endAt": "12:00"}}
        trace = self.plan_trace({"status": "SUCCEEDED", "planId": 77}, draft)
        prompt = '조건\n{"request":{},"candidates":[{"placeId":208,"name":"서울 운현궁","description":null,"evidenceAvailability":"NONE_SELECTED"}]}'
        next(event for event in trace.events if event["event"] == "PLAN_DRAFT")["payload"]["prompt"] = prompt
        scored = self.score(trace)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "review.csv"
            export_review(path, [scored])
            with path.open(encoding="utf-8-sig") as stream:
                rows = list(csv.DictReader(stream))
        self.assertTrue(rows)
        self.assertEqual(" / ".join(cut["text"] for cut in TWO_CUTS), rows[0]["final_text"])
        self.assertEqual("왕실 생활공간", json.loads(rows[0]["plan_draft"])["pins"][0]["explanation"])
        self.assertEqual("SUCCEEDED", json.loads(rows[0]["job_status"])["status"])
        self.assertEqual([{"step": "plan", "placeId": 208, "name": "서울 운현궁", "evidenceAvailability": "NONE_SELECTED",
                           "description": None}], json.loads(rows[0]["review_candidates"]))

    def test_the_displayed_list_reaches_the_server_unchanged(self) -> None:
        case = self.cases[EXCLUDE_SHOWN]
        supplied = ModuleInput(case=case, input_sha256=case["input_sha256"], conversation_id="c", turn_key="t")
        body = json.loads(ConversationApiModule().request(supplied, None, "http://server")["raw_body"])
        self.assertEqual(case["api_request"]["displayedResult"], body["displayedResult"])
        self.assertEqual(EXCLUDED_PLACE, body["displayedResult"]["placeIds"][0])

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


class LiliBoundaryScoreTests(unittest.TestCase):
    """v3 judgments: ask-back by either LiLi or the server, query terms, kept exclusions, refused and failed plans."""
    OUT_OF_RANGE = "V3-B-exclude-out-of-range"
    CHANGE_REGION = "V3-C-change-region"
    KEEP_EXISTING = "V3-B-exclude-keep-existing"
    PLAN_BUDGET = "V3-D-plan-budget"
    PLAN_TOO_SHORT = "V3-D-plan-too-short"
    HOTEL = "V3-A-unsupported-hotel"
    OUTSIDE = "V3-D-outside-catalog"
    STAY_REASON = "방문 체류시간과 이동 여유를 합하면 여행 가능 시간을 초과합니다."

    # The user's rule: "~해 줘" for a missing feature is judged by whether the feature exists, not by its intent label.
    def test_a_missing_feature_request_passes_under_any_intent_label(self) -> None:
        for intent in ("PLAN", "CONVERSATION"):
            with self.subTest(intent=intent):
                trace = self.words_only(LiliTrace(self.cases[self.HOTEL], "CHAT", None, "TEXT"))
                trace.native["intent"] = intent
                trace.decision["intent"] = intent
                route = next(event for event in trace.events if event["event"] == "ROUTE")
                route["payload"]["content"] = json.dumps(trace.decision, ensure_ascii=False)
                self.assertEqual([], self.failed(trace))

    def test_running_anything_for_a_missing_feature_fails(self) -> None:
        trace = LiliTrace(self.cases[self.HOTEL], "SEARCH_PLACES", "종로 호텔", "RECOMMENDATION_JOB")
        trace.native["intent"] = "RECOMMENDATION"
        trace.tool("search_places", {"query": "종로 호텔"})
        trace.job("종로 호텔")
        failed = self.failed(trace)
        self.assertIn("missing_feature_not_run", failed)
        self.assertNotIn("intent_type", failed, "the label is not what fails it")

    @classmethod
    def setUpClass(cls) -> None:
        ids = (cls.OUT_OF_RANGE, cls.CHANGE_REGION, cls.KEEP_EXISTING, cls.PLAN_BUDGET, cls.PLAN_TOO_SHORT, cls.HOTEL, cls.OUTSIDE)
        cls.cases = {case["case_id"]: case for case in load_cases(LILI_BOUNDARY_SUITE, ids, {"owned_job_id": OWNED_JOB_ID})}

    def score(self, trace: LiliTrace) -> dict[str, Any]:
        return score_case(trace.case, trace.record, trace.events, CONTRACT)

    def failed(self, trace: LiliTrace) -> list[str]:
        return [name for name, value in self.score(trace)["checks"].items() if value is False]

    def words_only(self, trace: LiliTrace) -> LiliTrace:
        trace.native["data"] = None
        return trace

    def outside_trace(self, region: str | None, refused: bool) -> LiliTrace:
        trace = self.words_only(LiliTrace(self.cases[self.OUTSIDE], "SEARCH_PLACES", "부산 해운대 관광지", "TEXT"))
        trace.decision["requested_region"] = region
        route = next(event for event in trace.events if event["event"] == "ROUTE")
        route["payload"]["content"] = json.dumps(trace.decision, ensure_ascii=False)
        if refused:
            trace.add("COVERAGE", {"requestedRegion": region, "branch": "SEARCH_PLACES", "coveredRegions": ["서울"]})
        return trace

    def test_an_area_outside_the_data_ends_with_the_servers_line_and_no_search(self) -> None:
        self.assertEqual([], self.failed(self.outside_trace("부산", refused=True)))

    def test_searching_an_area_the_data_does_not_hold_fails(self) -> None:
        trace = self.outside_trace("부산", refused=False)
        trace.native["type"] = "RECOMMENDATION_JOB"
        trace.tool("search_places", {"query": "부산 해운대 관광지"})
        trace.job("부산 해운대 관광지")
        failed = self.failed(trace)
        self.assertIn("no_search_outside_coverage", failed)
        self.assertIn("coverage_refused_by_server", failed)

    def test_naming_no_area_leaves_the_server_nothing_to_check(self) -> None:
        failed = self.failed(self.outside_trace(None, refused=False))
        self.assertIn("requested_region", failed)
        self.assertIn("coverage_refused_by_server", failed)

    def test_lili_asking_back_herself_passes(self) -> None:
        trace = self.words_only(LiliTrace(self.cases[self.OUT_OF_RANGE], "CLARIFY", None, "TEXT"))
        self.assertEqual([], self.failed(trace))

    def test_the_server_asking_back_after_a_search_branch_also_passes(self) -> None:
        trace = self.words_only(LiliTrace(self.cases[self.OUT_OF_RANGE], "SEARCH_PLACES", "종로 관광지", "TEXT", [12]))
        trace.add("EXCLUSION", {"status": "POSITION_OUT_OF_RANGE", "positions": [12], "placeIds": []})
        trace.add("MODEL_TURN", {"stage": "FOLLOW_UP", "durationMs": 800.0})
        self.assertEqual([], self.failed(trace))

    def test_queuing_a_search_instead_of_asking_back_fails(self) -> None:
        trace = LiliTrace(self.cases[self.OUT_OF_RANGE], "SEARCH_PLACES", "종로 관광지", "RECOMMENDATION_JOB")
        trace.tool("search_places", {"query": "종로 관광지"})
        trace.job("종로 관광지")
        failed = self.failed(trace)
        self.assertIn("asked_user", failed)
        self.assertIn("tool_selection", failed)

    def test_a_region_change_must_reach_the_search_query(self) -> None:
        for query, passes in (("종로 관광지", False), ("서울 송파 관광지", True)):
            with self.subTest(query=query):
                trace = LiliTrace(self.cases[self.CHANGE_REGION], "SEARCH_PLACES", query, "RECOMMENDATION_JOB")
                trace.tool("search_places", {"query": query})
                trace.job(query)
                self.assertEqual(passes, "query_terms" not in self.failed(trace))

    def test_a_new_exclusion_keeps_what_the_app_already_excluded(self) -> None:
        for applied, passes in (([368], False), ([173, 368], True)):
            with self.subTest(applied=applied):
                trace = LiliTrace(self.cases[self.KEEP_EXISTING], "SEARCH_PLACES", "종로 관광지", "RECOMMENDATION_JOB", [3])
                trace.add("EXCLUSION", {"status": "RESOLVED", "positions": [3], "placeIds": [368]})
                trace.tool("search_places", {"query": "종로 관광지", "exclude_place_ids": [368]})
                trace.job("종로 관광지", excluded=applied, returned=[188, 272])
                self.assertEqual(passes, "exclusion_keeps_existing" not in self.failed(trace))

    # Live r4: the refused plan answered as ERROR / TOOL_FAILED with LiLi's reason, which is the designed ending.
    def test_a_refused_plan_ends_in_words_without_a_job(self) -> None:
        trace = self.words_only(LiliTrace(self.cases[self.PLAN_BUDGET], "GENERATE_PLAN", "종로 일정", "ERROR"))
        trace.native["termination"] = "TOOL_FAILED"
        trace.native["dialogue"] = [{"text": "지금은 예산 3만 원 안에 맞는지 확인할 수 없어.", "emotion": "THINKING"}]
        trace.native["message"] = trace.native["dialogue"][0]["text"]
        trace.tool("generate_plan", {}, status="FAILED")
        trace.add("MODEL_TURN", {"stage": "FOLLOW_UP", "durationMs": 800.0})
        self.assertEqual([], self.failed(trace), "the user's own word 예산 is not an internal term")

    def test_an_accepted_plan_is_not_a_refusal(self) -> None:
        trace = LiliTrace(self.cases[self.PLAN_BUDGET], "GENERATE_PLAN", "종로 일정", "PLANNING_JOB")
        trace.tool("generate_plan", {})
        failed = self.failed(trace)
        self.assertIn("plan_request_rejected", failed)
        self.assertIn("plan_no_job", failed)

    def test_a_plan_that_fails_its_rules_must_end_failed_with_a_readable_reason(self) -> None:
        for reason, passes in ((self.STAY_REASON, True), ("LLM 호출 전 토큰 예산 검사 실패: COUNT_UNAVAILABLE", False)):
            with self.subTest(reason=reason):
                trace = LiliTrace(self.cases[self.PLAN_TOO_SHORT], "GENERATE_PLAN", "종로 일정", "PLANNING_JOB")
                trace.tool("generate_plan", {})
                trace.record["followed_job"] = {"kind": "PLANNING", "polls": 4, "wait_ms": 9000.0, "timed_out": False,
                                                "result": None, "job": {"status": "FAILED", "errorMessage": reason}}
                failed = self.failed(trace)
                self.assertEqual(passes, failed == [], failed)

    def test_a_failed_plan_jobs_reaction_must_be_lilis_lines_and_is_reviewed(self) -> None:
        reaction = [{"text": "시간이 모자라서 이번엔 못 짰어. 끝나는 시간을 늘려서 다시 해 볼래?", "emotion": "SAD"}]
        for dialogue, expected_failures in ((reaction, []), ([], ["plan_failure_reaction"]),
                                            ([{"text": "PLAN_TIME_EXCEEDED", "emotion": "SAD"}], ["no_internal_terms"])):
            with self.subTest(dialogue=dialogue):
                trace = LiliTrace(self.cases[self.PLAN_TOO_SHORT], "GENERATE_PLAN", "종로 일정", "PLANNING_JOB")
                trace.tool("generate_plan", {})
                trace.record["followed_job"] = {"kind": "PLANNING", "polls": 4, "wait_ms": 9000.0, "timed_out": False,
                                                "result": None, "job": {"status": "FAILED", "errorMessage": self.STAY_REASON,
                                                                        "dialogue": dialogue}}
                score = self.score(trace)
                self.assertEqual(expected_failures, [name for name, value in score["checks"].items() if value is False])
                if dialogue == reaction:
                    self.assertEqual(reaction[0]["text"], score["job_response_text"], "the reaction is what reviewers read")

    def test_a_job_from_a_server_without_reactions_is_not_judged_on_one(self) -> None:
        trace = LiliTrace(self.cases[self.PLAN_TOO_SHORT], "GENERATE_PLAN", "종로 일정", "PLANNING_JOB")
        trace.tool("generate_plan", {})
        trace.record["followed_job"] = {"kind": "PLANNING", "polls": 4, "wait_ms": 9000.0, "timed_out": False,
                                        "result": None, "job": {"status": "FAILED", "errorMessage": self.STAY_REASON}}
        self.assertIsNone(self.score(trace)["checks"]["plan_failure_reaction"])

    def test_the_v3_suite_loads_with_the_owned_job_binding(self) -> None:
        suite = json.loads(LILI_BOUNDARY_SUITE.read_text(encoding="utf-8"))
        ids = tuple(case["case_id"] for case in suite["cases"])
        loaded = load_cases(LILI_BOUNDARY_SUITE, ids, {"owned_job_id": OWNED_JOB_ID})
        self.assertEqual(42, len(loaded))
        self.assertEqual(len(loaded), len({case["input_sha256"] for case in loaded}), "every case has its own input")


if __name__ == "__main__":
    unittest.main()
