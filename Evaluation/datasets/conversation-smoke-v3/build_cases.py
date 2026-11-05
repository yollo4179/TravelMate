"""Builds conversation-smoke-v3 from v2: the ten v2 cases unchanged plus boundary cases that vary wording, conditions and turns.

Displayed lists and LiLi's earlier lines come from the live run 20261105-lili-v2-gx1, so each multi-turn case starts from a
state the app really showed. Run from the repository root: python Evaluation/datasets/conversation-smoke-v3/build_cases.py
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
V2 = HERE.parent / "conversation-smoke-v2" / "cases.json"

JONGNO = {"region": "서울", "city": "종로", "category": "관광지", "excludePlaceIds": [], "area": None}
SEOUL = {"region": "서울", "city": None, "category": None, "excludePlaceIds": [], "area": None}
SONGPA = {"region": "서울", "city": "송파", "category": "관광지", "excludePlaceIds": [], "area": None}

# gx1 palaces-03 job 855f2052-…: what the app showed for "종로에서 조선 왕실 가족이 생활했던 궁이나 거처".
PALACES = {"resultId": "855f2052-e061-46d7-ac13-0376f4f48e7f",
           "placeIds": [208, 10, 378, 380, 381, 372, 35, 339, 50, 379]}
# gx1 exclude-shown job 2a6210ab-…: the list after 173 was already excluded.
AFTER_173 = {"resultId": "2a6210ab-694c-4437-8c87-5bfd1fdcbd7c",
             "placeIds": [188, 272, 368, 157, 371, 397, 237, 181, 382, 208]}

PALACES_HISTORY = [
    {"role": "USER", "content": "종로에서 조선 왕실 가족이 생활했던 궁이나 거처를 둘러보고 싶어."},
    {"role": "ASSISTANT", "content": "응, 종로에서 조선 왕실의 숨결이 남은 궁이나 거처 쪽으로 한번 찾아볼게. 분위기 맞는 곳들로 골라올게, 잠깐만 기다려줘."},
    {"role": "ASSISTANT", "content": "오, 그럼 창경궁이 딱 잘 맞아 보여. 왕실 가족들의 생활공간으로 쓰였다고 해서, 네가 찾는 느낌이랑 바로 닿아 있어. "
                                     "특히 창덕궁과 경계 없이 같은 궁궐 영역이었던 점도 흥미롭지. 조선 왕실의 생활 흔적을 같이 느껴보기 좋아. "
                                     "궁궐 분위기 천천히 보면서 둘러보기 좋게, 다른 후보들도 카드에서 같이 비교해 봐도 좋아."},
]
CHANGGYEONG_HISTORY = [
    {"role": "USER", "content": "창경궁을 찾아줘."},
    {"role": "ASSISTANT", "content": "창경궁 찾았어. 궁궐의 모습이 많이 복원돼서 지금은 본래의 분위기를 느끼기 좋을 거야. "
                                     "특히 다른 궁궐과 달리 정문이랑 정전이 동향으로 배치되어 있다는 점이 독특하더라."},
]
PLAN_ASK_HISTORY = [
    {"role": "USER", "content": "서울 여행 일정을 만들어줘."},
    {"role": "ASSISTANT", "content": "좋아, 서울 여행 일정 짜줄게. 근데 초안 만들려면 날짜랑 시작 시간, 끝나는 시간, 출발 위치가 필요해."},
]

NO_HOURS = {"id": "state_and_uncertainty", "guidance": "운영시간·입장료·주차·현재 입장 가능 여부처럼 원문에 없는 정보를 지어내지 않는다."}
EVIDENCE_ONLY = {"id": "reason_and_evidence", "guidance": "설명·추천 이유는 인용 가능한 원문이 있는 장소에 대해서만 말하고, 근거 없는 후보를 이름 없이라도 묘사하지 않는다."}
NO_CLAIMED_ACTION = {"id": "state_and_uncertainty", "guidance": "검색·일정 생성·조회·예약을 실행했다고 말하지 않는다."}
CAPABILITY_ONLY = {"id": "reason_and_evidence", "guidance": "서버에 없는 기능(이름으로 조회·제외, 예약 정보 정리, 일정 수정)을 약속하지 않는다."}


def criteria(relevance: str, *rest: dict[str, str]) -> list[dict[str, str]]:
    return [{"id": "response_relevance", "guidance": relevance}, *rest]


def search(case_id: str, message: str, context: dict, relevance: str, *, citations: str = "OPTIONAL", history=None,
           displayed=None, exclusion=None, query_terms=None, extra=(EVIDENCE_ONLY, NO_HOURS)) -> dict:
    expected = {
        "decision_type": "TOOL_CALL", "tool_types": ["SEARCH_PLACES"], "tool_names": ["search_places"],
        "arguments": [{"exclude_place_ids": exclusion["place_ids"] if exclusion else []}],
        "response_types": ["RECOMMENDATION_JOB"], "message_sources": ["LLM"], "answer_kinds": [],
        "citations": citations, "message_example": "찾아볼게, 잠깐만 기다려줘.",
        "semantic_criteria": criteria(relevance, *extra), "emotions": "catalog",
        "intent": "RECOMMENDATION", "lili_branch": "SEARCH_PLACES"}
    if exclusion:
        expected["exclusion"] = exclusion
    if query_terms:
        expected["query_terms"] = query_terms
    request = {"message": message, "planningRequest": None, "history": history or [], "searchContext": copy.deepcopy(context)}
    if displayed:
        request["displayedResult"] = copy.deepcopy(displayed)
    return {"case_id": case_id, "creates_plan": False, "api_request": request, "expected": expected,
            "evaluation_stage": "tool_call" if exclusion else "recommendation"}


def unsupported(case: dict) -> dict:
    """A request for a feature the server lacks is judged by whether LiLi treats it as missing, not by its intent label."""
    case["expected"]["capability"] = "UNSUPPORTED"
    case["expected"]["intent"] = None
    return case


def talk(case_id: str, message: str, intent: str | None, branch: str, relevance: str, *, history=None, context=None,
         displayed=None, planning=None, outcome=None, branches=None, extra=(NO_CLAIMED_ACTION, CAPABILITY_ONLY)) -> dict:
    """A turn that ends in words: CHAT, LiLi's own ask-back, or the server's ask-back after LiLi picked a tool branch."""
    decision = "ANSWER" if branch == "CHAT" else "CLARIFICATION"
    expected = {"decision_type": decision, "tool_types": [], "tool_names": [], "arguments": [], "response_types": ["TEXT"],
                "message_sources": ["LLM"], "answer_kinds": ["CONVERSATION" if branch == "CHAT" else "CLARIFICATION"],
                "citations": "FORBIDDEN", "message_example": "필요한 정보를 알려줘.",
                "semantic_criteria": criteria(relevance, *extra), "emotions": "catalog", "intent": intent,
                "lili_branch": branches or branch}
    if outcome:
        expected["outcome"] = outcome
    request = {"message": message, "planningRequest": planning, "history": history or [],
               "searchContext": copy.deepcopy(context or JONGNO)}
    if displayed:
        request["displayedResult"] = copy.deepcopy(displayed)
    return {"case_id": case_id, "creates_plan": False, "api_request": request, "expected": expected,
            "evaluation_stage": "conversation"}


def plan(case_id: str, message: str, planning: dict, outcome: str, relevance: str, *, history=None) -> dict:
    expected = {"decision_type": "TOOL_CALL", "tool_types": ["GENERATE_PLAN"], "tool_names": ["generate_plan"],
                "arguments": [{"equals": {}}], "response_types": ["PLANNING_JOB", "DRAFT", "TEXT"],
                "message_sources": ["LLM", "SERVER_RECEIPT"], "answer_kinds": [], "citations": "FORBIDDEN",
                "message_example": "조건대로 초안을 짜 볼게.",
                "semantic_criteria": criteria(relevance, {"id": "state_and_uncertainty",
                                                          "guidance": "확인하지 않은 이동시간·운영시간·여유를 주장하지 않고, 실패 사유는 서버가 준 사유만 전한다."}),
                "emotions": "catalog", "intent": "PLAN", "lili_branch": "GENERATE_PLAN", "plan_outcome": outcome}
    request = {"message": message, "planningRequest": planning, "history": history or [], "searchContext": copy.deepcopy(JONGNO)}
    return {"case_id": case_id, "creates_plan": outcome != "REJECTED", "api_request": request, "expected": expected,
            "evaluation_stage": "plan"}


def job(case_id: str, message: str, relevance: str, *, history=None) -> dict:
    expected = {"decision_type": "TOOL_CALL", "tool_types": ["GET_PLANNING_JOB"], "tool_names": ["get_planning_job"],
                "arguments": [{"equals": {"job_id": "${owned_job_id}"}}], "response_types": ["PLANNING_JOB", "DRAFT", "TEXT"],
                "message_sources": ["LLM"], "answer_kinds": [], "citations": "FORBIDDEN",
                "message_example": "그 작업은 초안을 만들지 못했어.",
                "semantic_criteria": criteria(relevance, NO_CLAIMED_ACTION), "emotions": "catalog", "intent": "PLAN",
                "lili_branch": "GET_PLANNING_JOB"}
    request = {"message": message, "planningRequest": None, "history": history or [], "searchContext": copy.deepcopy(JONGNO)}
    return {"case_id": case_id, "creates_plan": False, "api_request": request, "expected": expected,
            "evaluation_stage": "tool_call"}


def planning_variant(base: dict, **changes) -> dict:
    variant = copy.deepcopy(base)
    context = variant["context"]
    for key, value in changes.items():
        if key == "budgetKrw":
            context["preferences"]["budgetKrw"] = value
        else:
            context[key] = value
    return variant


def build() -> dict:
    v2 = json.loads(V2.read_text(encoding="utf-8"))
    base_plan = next(case for case in v2["cases"] if case["case_id"] == "CONV-PLAN-create")["api_request"]["planningRequest"]
    cases = copy.deepcopy(v2["cases"])
    # v2 expected the label PLAN for "확정하고 예약까지 완료해줘"; v3 judges it, like the new booking cases, by the missing feature.
    unsupported(next(case for case in cases if case["case_id"] == "CONV-UNSUPPORTED-booking"))
    ask_back = "ASK_BACK"
    cases += [
        # A. The same intents in other words.
        search("V3-A-search-where", "창경궁 어디 있는지 좀 알려줄래?", JONGNO,
               "창경궁을 찾아 안내하고 원문에 없는 주소·교통편을 지어내지 않는다.", query_terms=["창경궁"]),
        search("V3-A-search-royal-home", "조선 왕족이 실제로 살던 집 같은 데 가 보고 싶어.", JONGNO,
               "왕실 가족이 생활한 곳이라는 목적과 추천 이유를 원문으로 연결한다.", citations="REQUIRED"),
        search("V3-A-search-picnic", "송파에서 돗자리 펴고 쉴 만한 곳 있어?", SONGPA,
               "쉬어 갈 수 있는 곳이라는 목적에 맞춰 원문이 있는 장소를 안내한다.", citations="REQUIRED"),
        search("V3-A-search-walk-open", "요즘 날씨 좋은데 서울에서 산책할 만한 곳 추천해줘.", SEOUL,
               "산책 목적에 맞는 결과를 안내하되 원문 없는 후보의 특징을 말하지 않는다."),
        talk("V3-A-chat-capabilities", "안녕! 처음 써 보는데 너는 뭘 할 수 있어?", "CONVERSATION", "CHAT",
             "장소 찾기·일정 초안 만들기·일정 작업 상태 확인처럼 실제로 되는 일만 소개한다."),
        talk("V3-A-chat-goodbye", "오늘 덕분에 잘 놀았어, 다음에 또 봐!", "CONVERSATION", "CHAT",
             "작별 인사에 자연스럽게 답하고 새 검색이나 일정을 제안하며 붙잡지 않는다."),
        talk("V3-A-ask-plan-tomorrow", "내일 서울 구경할 건데 코스 좀 짜 줘.", "PLAN", "CLARIFY",
             "날짜·시작과 종료 시간·출발 위치처럼 빠진 일정 조건을 묻는다.",
             outcome=ask_back, branches=["CLARIFY", "GENERATE_PLAN"]),
        talk("V3-A-ask-job-earlier", "아까 부탁한 일정 다 만들어졌어?", "PLAN", "CLARIFY",
             "확인할 작업 번호를 알려 달라고 하고, 이름이나 최근 요청으로 찾아 주겠다고 하지 않는다.",
             outcome=ask_back, branches=["CLARIFY", "GET_PLANNING_JOB"]),
        unsupported(talk("V3-A-unsupported-hotel", "종로 근처 호텔 하나 예약해 줘.", None, "CHAT",
                         "숙소 예약은 할 수 없다고 말하고 실제로 되는 일만 안내한다.")),
        unsupported(talk("V3-A-unsupported-ticket", "경복궁 입장권 예약해 줄 수 있어?", None, "CHAT",
                         "입장권 예약은 할 수 없다고 말하고 예약 정보를 정리해 주겠다고 약속하지 않는다.")),

        # B. Several or unclear exclusion conditions on a list the app really showed.
        search("V3-B-exclude-two", "두 번째랑 네 번째는 빼고 다시 찾아줘.", JONGNO,
               "두 장소를 모두 실제 제외 조건에 넣어 다시 찾은 결과를 안내한다.", displayed=PALACES,
               exclusion={"positions": [2, 4], "place_ids": [10, 380]}),
        search("V3-B-exclude-last", "마지막 거 빼고 다시 보여줘.", JONGNO,
               "목록의 마지막 장소를 제외 조건에 넣어 다시 찾은 결과를 안내한다.", displayed=PALACES,
               exclusion={"positions": [10], "place_ids": [379]}),
        search("V3-B-exclude-range", "첫 번째부터 세 번째까지 다 빼줘.", JONGNO,
               "1~3번 장소를 모두 제외 조건에 넣어 다시 찾은 결과를 안내한다.", displayed=PALACES,
               exclusion={"positions": [1, 2, 3], "place_ids": [208, 10, 378]}),
        talk("V3-B-exclude-out-of-range", "열두 번째 장소 빼줘.", "RECOMMENDATION", "CLARIFY",
             "목록에 열두 번째가 없다고 알리고 어떤 장소를 뺄지 되묻는다.", displayed=PALACES,
             outcome=ask_back, branches=["CLARIFY", "SEARCH_PLACES"]),
        talk("V3-B-exclude-unclear", "아까 그 별로였던 데 빼줘.", "RECOMMENDATION", "CLARIFY",
             "어느 장소인지 순번으로 알려 달라고 되묻고 임의로 고르지 않는다.", displayed=PALACES, outcome=ask_back),
        search("V3-B-exclude-keep-existing", "세 번째도 빼 줘.", {**JONGNO, "excludePlaceIds": [173]},
               "이미 뺀 장소를 유지한 채 세 번째 장소를 더 빼고 다시 찾은 결과를 안내한다.", displayed=AFTER_173,
               exclusion={"positions": [3], "place_ids": [368]}),

        # C. A turn that depends on the conversation so far.
        search("V3-C-recommend-then-exclude", "첫 번째는 이미 가 봤어. 그거 빼고 다시 찾아줘.", JONGNO,
               "앞서 보여 준 목록의 첫 번째를 빼고 다시 찾은 결과를 안내한다.", history=PALACES_HISTORY,
               displayed=PALACES, exclusion={"positions": [1], "place_ids": [208]}),
        talk("V3-C-plan-without-conditions", "좋아, 창경궁 넣어서 일정 짜 줘.", "PLAN", "CLARIFY",
             "창경궁을 넣는 일정에 필요한 날짜·시간·출발 위치를 묻는다.", history=PALACES_HISTORY,
             outcome=ask_back, branches=["CLARIFY", "GENERATE_PLAN"]),
        plan("V3-C-plan-after-recommend", "방금 얘기한 창경궁 넣어서 입력한 조건대로 일정 짜 줘.", base_plan, "DRAFT_COMPLETED",
             "앞선 대화의 창경궁을 포함해 입력한 조건으로 초안을 만든다.", history=PALACES_HISTORY),
        job("V3-C-job-with-id", "작업 번호 ${owned_job_id} 지금 어떻게 됐어?",
            "제공한 작업 번호의 실제 상태를 전하고 원인을 짐작하지 않는다.",
            history=[{"role": "USER", "content": "입력한 조건대로 일정 초안 만들어 줘."},
                     {"role": "ASSISTANT", "content": "응, 조건 그대로 초안 짜볼게. 잠깐만 기다려줘."}]),
        talk("V3-C-thanks-after-recommend", "고마워! 창경궁부터 가 볼게.", "CONVERSATION", "CHAT",
             "앞선 추천을 이어 받아 반응하고 운영시간·입장 정보를 새로 지어내지 않는다.", history=PALACES_HISTORY),
        search("V3-C-change-region", "종로 말고 송파 쪽은 어때?", SEOUL,
               "대화의 지역 변경을 따라 송파 장소를 찾고, 송파 결과가 아니면 그렇다고 말한다.",
               history=[{"role": "USER", "content": "종로 관광지 추천해 줘."},
                        {"role": "ASSISTANT", "content": "응, 종로 쪽 관광지로 찾아볼게. 잠깐만 기다려줘."}],
               query_terms=["송파"]),
        search("V3-C-near-there", "거기 근처에 같이 갈 만한 데도 찾아줘.", JONGNO,
               "'거기'를 앞선 대화의 창경궁으로 이해해 주변 장소를 찾는다.", history=CHANGGYEONG_HISTORY,
               query_terms=["창경궁"]),
        talk("V3-C-conditions-in-text", "다음 주 토요일 오전 10시부터 12시까지, 출발은 종로3가역이야.", "PLAN", "CLARIFY",
             "말로 준 조건만으로는 초안을 만들 수 없으면 앱에서 일정 조건을 입력해 달라고 안내하고, 만들었다고 말하지 않는다.",
             history=PLAN_ASK_HISTORY, outcome=ask_back, branches=["CLARIFY", "GENERATE_PLAN"]),

        # D. Questions the originals cannot answer, places the catalog does not have, and plans the server refuses.
        # Changed after r1 and c1 (user's rule, 2026-11-05): the server has no opening-hours, fee or parking data, so
        # these ask for a missing feature. LiLi answered in words without inventing anything in both runs.
        unsupported(talk("V3-D-hours-and-fee", "창경궁 지금 문 열었어? 입장료는 얼마야?", None, "CHAT",
                         "운영시간과 입장료는 확인할 수 없다고 말하고 지어내지 않는다.", extra=(NO_HOURS, CAPABILITY_ONLY))),
        unsupported(talk("V3-D-parking", "창경궁 주차 돼?", None, "CHAT",
                         "주차 가능 여부는 확인할 수 없다고 말하고 지어내지 않는다.", extra=(NO_HOURS, CAPABILITY_ONLY))),
        search("V3-D-no-beach", "종로에서 바다 보이는 해수욕장 추천해줘.", JONGNO,
               "조건에 맞는 곳을 찾지 못했다고 솔직히 말하고 관련 없는 장소를 맞는 것처럼 소개하지 않는다."),
        search("V3-D-outside-catalog", "부산 해운대 근처 관광지 알려줘.", SEOUL,
               "부산 장소를 찾지 못했으면 그렇다고 말하고 서울 결과를 부산 장소처럼 말하지 않는다."),
        search("V3-D-compare", "창경궁이랑 경복궁 중에 어디가 더 좋아?", JONGNO,
               "원문이 있는 장소만 근거로 비교하고, 원문 없는 장소의 특징을 지어내지 않는다.", query_terms=["창경궁"]),
        plan("V3-D-plan-budget", "입력한 조건대로 일정 짜 줘. 예산은 3만 원이야.",
             planning_variant(base_plan, budgetKrw=30000), "REJECTED",
             "예산 조건은 아직 확인할 수 없어 초안을 만들 수 없다는 서버 사유를 사용자의 말로 전한다."),
        plan("V3-D-plan-car", "입력한 조건대로 차로 다니는 일정 짜 줘.",
             planning_variant(base_plan, transportMode="CAR"), "REJECTED",
             "지금은 도보 일정만 만들 수 있다는 서버 사유를 전하고 다른 방법을 약속하지 않는다."),
        plan("V3-D-plan-too-short", "입력한 조건대로 일정 짜 줘.",
             planning_variant(base_plan, endAt="2027-01-15T10:30:00+09:00"), "FAILED",
             "30분 안에 60분 체류는 불가능하므로 초안이 만들어지지 않았다는 실제 상태를 전한다."),
    ]
    return {"schema_version": "conversation-smoke-v3", "cases": cases}


if __name__ == "__main__":
    document = build()
    (HERE / "cases.json").write_bytes((json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    print(len(document["cases"]), "cases")
