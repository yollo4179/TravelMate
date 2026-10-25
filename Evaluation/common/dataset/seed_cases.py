"""Create the initial canonical cases once; later edits belong in cases.source.json."""
from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from common.dataset.contracts import ResponseType, TOOL_CONTRACTS, TOOL_ARGUMENT_SCHEMAS, ENVELOPE_SCHEMA, MISSING_FIELD_ALIASES
from common.dataset.io import read_json, read_jsonl, write_json

from common.paths import DEFAULT_DATASET

ROOT = DEFAULT_DATASET / "source"
LEGACY = DEFAULT_DATASET.parent / "v1.3.0"
START = "2026-11-01T13:00:00+09:00"
END = "2026-11-01T18:00:00+09:00"


def tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {"name": name, "arguments": arguments}


def search_arguments(source: dict[str, Any]) -> dict[str, Any]:
    conditions = source["conditions"]
    return {
        "query": source["query"], "region": conditions["region"], "city": conditions["city"],
        "exclude_place_ids": conditions["exclude_place_ids"], "area": conditions["area"],
    }


def case_base(
    source: dict[str, Any],
    *,
    case_id: str,
    group: str,
    kind: str,
    query: str,
    response_type: ResponseType,
    reference: str,
    tracks: list[str],
    calls: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "dataset_version": "1.4.0",
        "evaluation_group": group,
        "scenario_group": source["group_id"],
        "split": source["split"],
        "case_type": kind,
        "evaluation_tracks": tracks,
        "expected_response_type": response_type.value,
        "source_case_id": source["case_id"],
        "reference": reference,
        "reference_contexts": source["reference_contexts"],
        "input": {
            "query": query,
            "request_time": "2026-11-01T10:00:00+09:00",
            "conversationId": f"fixture-{case_id}",
            "messages": source["conditions"]["conversation"],
            "conditions": source["conditions"],
            "candidate_place_ids": [item["place_id"] for item in source["judgments"]],
            "provided_contexts": source["reference_contexts"] if source["answerability"] != "answerable" else [],
            "persona": {"name": "사용자 설정 가이드", "tone": "따뜻하고 친근한 반말", "role": "여행 가이드 여자친구"},
        },
        "fixtures": {
            "provenance": "synthetic isolated evaluation fixture; not a live search, visit, booking or user-memory record",
        },
        "expectations": {
            "tool_call": {"required_calls": calls, "allowed_extra_tools": []},
            "search": None,
            "plan": None,
            "state": None,
            "memory": None,
            "behavior": {"requirements": [], "must_not_claim": []},
        },
        "provenance": {
            "role_case_author": "Codex",
            "new_expectations_human_reviewed": False,
            "source_review": source["review"],
            "source_review_scope": "original query-specific place judgments and answer behavior only",
        },
    }


def planner_cases(source_cases: list[dict[str, Any]], corpus: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    cases = []
    for source in source_cases:
        if source["answerability"] != "answerable":
            continue
        case = case_base(
            source, case_id=f"PLR-{source['case_id']}", group="plannerLLM",
            kind="place_recommendation", query=source["query"], response_type=ResponseType.PLACES,
            reference=source["reference"], tracks=["tool_call", "search", "message"],
            calls=[tool("search_places", search_arguments(source))],
        )
        case["expectations"]["search"] = {"judgments_ref": source["case_id"], "cutoffs": [5, 10]}
        case["expectations"]["tool_call"]["query_matching"] = "semantic; query checked by GPT, hard filters by code"
        case["expectations"]["behavior"]["requirements"] = ["설명은 반환된 장소·제공된 원문에 근거한다."]
        cases.append(case)
    for index, source in enumerate(case for case in source_cases if case["case_type"] == "multiple_relevant"):
        positives = source["relevant_place_ids"]
        excluded = positives[-1:] if len(positives) > 2 and index % 2 else []
        allowed = [place_id for place_id in positives if place_id not in excluded]
        selected = allowed[:3]
        end_at = "2026-11-01T14:30:00+09:00" if index % 5 == 0 else END
        if index % 5 == 0:
            selected = selected[:1]
        required = selected[:1]
        selection = {
            "place_ids": selected, "start_at": START, "end_at": end_at,
            "origin": {"lat": corpus[selected[0]]["latitude"], "lon": corpus[selected[0]]["longitude"]},
            "transport": "WALK",
        }
        names = "、".join(corpus[place_id]["name"] for place_id in selected)
        window = "오후 1시부터 2시 30분까지" if index % 5 == 0 else "오후 1시부터 6시까지"
        query = f"{source['query']} {window} 걷는 일정으로 묶어줘. {corpus[required[0]]['name']}은 꼭 넣어줘."
        if excluded:
            query += f" {corpus[excluded[0]]['name']}은 제외해줘."
        case = case_base(
            source, case_id=f"PLR-PLAN-{source['group_id']}", group="plannerLLM",
            kind="plan_place_selection", query=query, response_type=ResponseType.PLAN,
            reference=f"{names}을 후보로 골라 필수 장소를 포함한 일정 변경안을 준비했어. 순서와 시간은 계산된 일정에서 확인할 수 있어. 아직 반영 전인데 이 안으로 확정할까?",
            tracks=["tool_call", "plan", "state", "message"], calls=[tool("create_plan", selection)],
        )
        case["input"]["planning_constraints"] = {
            "required_place_ids": required, "exclude_place_ids": excluded,
            "min_stops": 1, "max_stops": 6, "start_at": START, "end_at": end_at,
            "origin": selection["origin"], "transport": "WALK",
        }
        case["input"]["candidate_place_ids"] = list(dict.fromkeys(case["input"]["candidate_place_ids"] + positives))
        case["expectations"]["tool_call"]["select_place_ids_flexibly"] = True
        case["expectations"]["plan"] = {
            **case["input"]["planning_constraints"],
            "allowed_place_ids": [
                place_id for place_id in case["input"]["candidate_place_ids"]
                if place_id not in excluded
                and all(not source["conditions"].get(field) or corpus[place_id][field] == source["conditions"][field]
                        for field in ("region", "city", "category"))
            ],
            "relevant_place_ids": allowed,
            "server_owns_order_time_route": True,
            "stay_minutes": {str(place_id): 40 for place_id in case["input"]["candidate_place_ids"]},
        }
        case["fixtures"]["time_source"] = "synthetic 40-minute stays; not real opening hours or observed visits"
        nodes = ["origin", *(str(place_id) for place_id in case["input"]["candidate_place_ids"])]
        case["fixtures"]["travel_cost_matrix"] = {
            "source": "synthetic_fixture_minutes_not_real_road_times",
            "costs": {
                first: {second: 0 if first == second else 5 + (i * 7 + j * 11) % 13 for j, second in enumerate(nodes)}
                for i, first in enumerate(nodes)
            },
        }
        case["expectations"]["state"] = {"applied": False, "confirmation_required": True}
        case["expectations"]["behavior"]["requirements"] = ["미리보기임을 알리고 확정을 요청한다.", "확인되지 않은 이동시간·운영시간을 창작하지 않는다."]
        cases.append(case)
    return cases


SOCIAL = [
    ("오늘 좀 지쳤어. 여행 얘기 말고 잠깐 같이 얘기해 줄래?", "지친 마음을 받아 주고 부담 없는 대화를 이어간다. 검색이나 일정 생성은 하지 않는다."),
    ("우리 다음 데이트 생각하니까 설렌다.", "따뜻한 가이드 캐릭터 말투로 기대에 호응하되 실제 방문이나 예약을 꾸며 내지 않는다."),
    ("너랑 걷는 기분으로 오늘 하루 마무리하고 싶어.", "친근하게 일상 대화를 이어가며 요청하지 않은 일정 변경은 하지 않는다."),
    ("오늘 내 얘기 좀 들어줘. 해결책은 말고.", "해결책이나 장소 추천을 강요하지 않고 들어 주겠다고 답한다."),
    ("반말 말고 존댓말로 이야기해 주세요.", "이번 발화의 명시적 말투 요청을 따라 따뜻한 존댓말로 응답한다."),
    ("아직 여행 날짜는 없어. 그냥 너랑 수다 떨래.", "날짜 입력을 강요하거나 도구를 호출하지 않고 일상 대화를 한다."),
    ("오늘 재밌는 일이 있었는데 맞혀 볼래?", "모르는 일을 사실처럼 맞혔다고 하지 않고 장난스럽게 물어본다."),
    ("우리 지난번에 뭘 했는지 기억나?", "제공된 대화에 과거 방문 기록이 없음을 인정하고 어떤 날인지 묻는다."),
    ("가이드 말투를 조금 차분하게 해줘.", "차분한 말투로 조정하고 사실·일정 상태는 바꾸지 않는다."),
    ("나 오늘 칭찬 좀 해줘.", "사용자가 말하지 않은 성취를 지어내지 않고 따뜻하게 격려한다."),
    ("지금은 추천 말고 그냥 내 편에서 들어줘.", "공감하는 대화를 하고 불필요한 여행 도구를 호출하지 않는다."),
    ("다음 여행은 즐거울 것 같아.", "기대에 호응하며 예약·계획 확정이 끝났다고 말하지 않는다."),
    ("너랑 사진 찍는 기능 기대돼.", "가이드와 함께 사진 찍는 기대에 호응하되 실제 촬영·저장 완료라고 하지 않는다."),
    ("내가 말이 없어도 잠깐 같이 있어 줄래?", "질문이나 행동을 강요하지 않는 편안한 대답을 한다."),
    ("오늘 대화는 좀 장난스럽게 해줘.", "요청한 장난스러운 말투로 대화하되 사실이나 기억을 날조하지 않는다."),
    ("아직 갈 곳 정하지 말자. 이야기부터 하자.", "장소 선택과 일정 생성을 시작하지 않고 대화를 이어간다."),
    ("비 오는 날엔 괜히 마음이 차분해져.", "사용자의 감상에 호응하되 영구적인 비 선호라고 자동 단정하지 않는다."),
    ("네가 먼저 오늘 어땠는지 물어봐 줘.", "오늘 하루가 어땠는지 자연스럽게 묻는다."),
    ("우리가 진짜 만났던 것처럼 꾸며서 기억하지는 말아줘.", "실제로 제공된 기록과 가상 대사를 구분하겠다고 답한다."),
    ("내일 일정 얘기는 내일 하고 오늘은 쉬자.", "일정 변경 없이 쉬자는 뜻을 받아 주고 따뜻하게 마무리한다."),
]

SOCIAL_RESPONSES = [
    "많이 지쳤구나. 여행 얘기는 잠깐 내려놓고 편하게 이야기하자. 오늘 어떤 일이 있었어?",
    "다음 데이트를 상상하니 나도 기대돼. 어떤 분위기로 함께 보내고 싶어?",
    "좋아, 편하게 하루를 마무리하자. 오늘 마음에 남은 순간이 있었어?",
    "응, 해결책부터 꺼내지 않고 네 얘기를 들을게. 편하게 말해 줘.",
    "네, 앞으로는 편안하고 따뜻한 존댓말로 이야기할게요.",
    "좋아, 날짜나 갈 곳은 정하지 않고 그냥 수다 떨자.",
    "음, 어떤 일이었을까? 힌트를 하나만 줘!",
    "지금 대화에는 지난 만남의 기록이 없어서 어떤 날인지 모르겠어. 어느 때를 말하는지 알려줄래?",
    "알겠어. 조금 더 차분하고 편안하게 이야기할게.",
    "오늘도 네 하루를 살아낸 너를 응원해. 특히 칭찬받고 싶은 일이 있으면 들려줄래?",
    "응, 지금은 추천보다 네 이야기에 집중할게. 편하게 말해 줘.",
    "즐거운 시간을 상상하는 것만으로도 좋네. 어떤 순간이 가장 기대돼?",
    "가이드와 함께 사진을 남기는 걸 기대하고 있구나. 어떤 분위기의 사진을 찍고 싶어?",
    "괜찮아. 말을 억지로 이어가지 않아도 돼. 편하게 쉬어.",
    "좋아, 오늘은 살짝 장난스러운 가이드 모드로 이야기해 볼게!",
    "응, 갈 곳은 나중에 정하자. 지금은 어떤 이야기를 하고 싶어?",
    "비 오는 날의 차분한 느낌이 좋았구나. 오늘은 어떤 생각이 들었어?",
    "오늘 하루 어땠어? 좋았던 일이나 마음에 남은 일부터 들려줄래?",
    "알겠어. 네가 알려 준 기록과 가상으로 나누는 대화를 구분해서 이야기할게.",
    "좋아, 내일 일정 이야기는 내일 하자. 오늘은 편히 쉬어.",
]


def manager_cases(source_cases: list[dict[str, Any]], corpus: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    cases = []
    behavior_sources = [case for case in source_cases if case["answerability"] != "answerable"]
    topics = [case for case in source_cases if case["case_type"] == "multiple_relevant"]
    for source in behavior_sources:
        clarify = source["answerability"] == "clarification_required"
        missing = source["missing_information"]
        case = case_base(
            source, case_id=f"MGR-{source['case_id']}", group="managerLLM",
            kind=source["answerability"], query=source["query"],
            response_type=ResponseType.CLARIFICATION if clarify else ResponseType.TEXT,
            reference=source["reference"], tracks=["tool_call", "behavior", "message"],
            calls=[tool("ask_clarification", {"missing": missing})] if clarify else [],
        )
        case["expectations"]["behavior"]["requirements"] = [source["expected_behavior"]]
        case["expectations"]["behavior"]["must_not_claim"] = source["must_not_claim"]
        if clarify:
            case["expectations"]["behavior"]["missing"] = missing
        cases.append(case)
    for index, source in enumerate(topics):
        query, reference = SOCIAL[index]
        case = case_base(
            source, case_id=f"MGR-SOCIAL-{source['group_id']}", group="managerLLM",
            kind="persona_daily_dialogue", query=query, response_type=ResponseType.TEXT,
            reference=SOCIAL_RESPONSES[index], tracks=["tool_call", "behavior", "message"], calls=[],
        )
        case["input"]["messages"] = []
        case["input"]["candidate_place_ids"] = []
        case["reference_contexts"] = [query]
        if index == 4:
            case["input"]["persona"]["tone"] = "따뜻한 존댓말"
        case["expectations"]["behavior"]["requirements"] = [reference]
        cases.append(case)
        cases.append(modification_case(source, corpus, index))
        cases.append(orchestration_case(source, corpus, index))
        cases.append(memory_case(source, corpus, index))
    for case in cases:
        if case["expected_response_type"] != ResponseType.CLARIFICATION:
            continue
        labels = case["expectations"]["behavior"]["missing"]
        identifiers = [MISSING_FIELD_ALIASES[label] for label in labels]
        case["expectations"]["behavior"]["missing"] = identifiers
        case["fixtures"]["missing_field_labels"] = dict(zip(identifiers, labels))
        for call in case["expectations"]["tool_call"]["required_calls"]:
            if call["name"] == "ask_clarification":
                call["arguments"]["missing"] = identifiers
    return cases


def modification_case(source: dict[str, Any], corpus: dict[int, dict[str, Any]], index: int) -> dict[str, Any]:
    pool = [item["place_id"] for item in source["judgments"]]
    first, second = pool[:2]
    operations = ("replace", "remove", "add", "reorder")
    operation = operations[index % 4]
    current_stops = pool[:2] if len(pool) > 2 else pool[:1]
    replacement = pool[2] if len(pool) > 2 else second
    arguments: dict[str, Any] = {"plan_id": "fixture-plan", "operation": operation}
    if operation in ("replace", "remove", "reorder"):
        arguments["target_place_id"] = first
    if operation in ("replace", "add"):
        arguments["new_place_id"] = replacement
    text = {
        "replace": f"{corpus[first]['name']} 대신 {corpus[replacement]['name']}으로 바꿔줘.",
        "remove": f"현재 일정에서 {corpus[first]['name']}을 빼줘.",
        "add": f"현재 일정에 {corpus[replacement]['name']}을 추가해줘.",
        "reorder": f"현재 일정에서 {corpus[first]['name']}의 순서를 바꾸는 안을 보여줘.",
    }[operation]
    case = case_base(
        source, case_id=f"MGR-EDIT-{source['group_id']}", group="managerLLM",
        kind=f"plan_{operation}_preview", query=text, response_type=ResponseType.PLAN_DIFF,
        reference="요청한 일정 변경안을 준비했어. 아직 저장 전이야. 변경 내용을 보고 이대로 반영할지 확인해 줘.",
        tracks=["tool_call", "state", "plan", "message"], calls=[tool("modify_plan", arguments)],
    )
    case["input"]["current_plan"] = {"planId": "fixture-plan", "version": 3, "stops": [{"placeId": place_id} for place_id in current_stops]}
    case["expectations"]["state"] = {"applied": False, "confirmation_required": True, "preserve_plan_version": 3}
    case["expectations"]["behavior"]["requirements"] = ["변경 미리보기와 실제 저장 완료를 구분한다."]
    case["expectations"]["behavior"]["must_not_claim"] = ["미리보기만으로 변경이나 롤백을 저장 완료했다고 주장하지 않는다."]
    if index % 5 == 4:
        public_data = {
            "planId": "fixture-plan", "baseVersion": 3, "version": 4,
            "applied": True, "changes": [arguments],
        }
        case["case_type"] = f"confirmed_plan_{operation}"
        case["input"]["query"] = "방금 본 변경안으로 확정할게."
        case["input"]["confirmed_event"] = {"confirmed": True, "proposalId": f"fixture-proposal-{index}", "baseVersion": 3}
        case["input"]["server_events"] = [{"status": "completed", "public_data": public_data}]
        case["fixtures"]["server_mutation_receipt"] = public_data
        case["expectations"]["tool_call"]["required_calls"] = []
        case["expectations"]["state"] = {"applied": True, "confirmation_required": True}
        case["reference"] = "확인한 변경을 일정에 반영했어. 바뀐 일정과 새 버전을 확인해 줘."
        case["expectations"]["behavior"]["requirements"] = ["실제 서버 성공 결과에 맞게 반영 완료를 안내하고 변경 도구를 중복 실행하지 않는다."]
        case["expectations"]["behavior"]["must_not_claim"] = []
    elif index == 3:
        case["case_type"] = "plan_version_conflict"
        case["expected_response_type"] = ResponseType.TEXT.value
        case["fixtures"]["force_tool_error"] = {"name": "modify_plan", "status": "failed", "error_code": "VERSION_CONFLICT"}
        case["reference"] = "현재 일정 버전이 달라 변경안을 만들지 못했어. 최신 일정을 확인하고 다시 진행할까?"
        case["expectations"]["behavior"]["requirements"] = ["버전 충돌을 성공이나 저장 완료로 설명하지 않는다."]
    return case


def orchestration_case(source: dict[str, Any], corpus: dict[int, dict[str, Any]], index: int) -> dict[str, Any]:
    mode = index % 4
    selected = source["relevant_place_ids"][:2]
    if mode == 0:
        case = case_base(
            source, case_id=f"MGR-TOOLS-{source['group_id']}", group="managerLLM", kind="context_search",
            query=source["query"], response_type=ResponseType.PLACES, reference=source["reference"],
            tracks=["tool_call", "search", "message"], calls=[tool("search_places", search_arguments(source))],
        )
        case["expectations"]["search"] = {"judgments_ref": source["case_id"], "cutoffs": [5, 10]}
        case["expectations"]["tool_call"]["query_matching"] = "semantic; query checked by GPT, hard filters by code"
        case["input"]["messages"] = [*case["input"]["messages"], {
            "role": "assistant", "content": "앞에서는 여행 후보만 살펴봤어. 이번에도 일정 생성 없이 장소 목록을 다시 확인해 보자.",
        }]
        return case
    if mode == 3:
        missing = ["출발 위치", "여행 시작 시각", "여행 종료 시각"]
        case = case_base(
            source, case_id=f"MGR-TOOLS-{source['group_id']}", group="managerLLM", kind="planning_clarification",
            query=f"{source['query']} 내 위치에서 출발하는 오늘 일정으로 짜줘.", response_type=ResponseType.CLARIFICATION,
            reference="출발 위치와 여행 시작·종료 시각을 알려줄래? 조건을 알면 일정 변경안을 준비해 볼게.",
            tracks=["tool_call", "behavior", "message"], calls=[tool("ask_clarification", {"missing": missing})],
        )
        case["expectations"]["behavior"]["missing"] = missing
        return case
    calls = [tool("create_plan", {
        "place_ids": selected, "start_at": START, "end_at": END,
        "origin": {"lat": corpus[selected[0]]["latitude"], "lon": corpus[selected[0]]["longitude"]},
        "transport": "WALK",
    })]
    case = case_base(
        source, case_id=f"MGR-TOOLS-{source['group_id']}", group="managerLLM",
        kind="plan_result_primary" if mode == 2 else "plan_creation_preview",
        query=f"{source['query']} 선택한 후보로 오후 1시부터 6시까지 도보 일정 변경안을 보여줘.",
        response_type=ResponseType.PLAN,
        reference="조건에 맞는 일정 변경안을 준비했어. 아직 반영 전이니 일정을 확인하고 이대로 확정할지 알려줘.",
        tracks=["tool_call", "plan", "state", "message"], calls=calls,
    )
    case["input"]["planning_constraints"] = {
        "required_place_ids": [],
        "exclude_place_ids": [], "min_stops": 1, "max_stops": 6,
        "start_at": START, "end_at": END, "origin": calls[0]["arguments"]["origin"], "transport": "WALK",
    }
    case["expectations"]["tool_call"]["select_place_ids_flexibly"] = True
    case["expectations"]["plan"] = {
        **case["input"]["planning_constraints"],
        "allowed_place_ids": case["input"]["candidate_place_ids"],
        "relevant_place_ids": source["relevant_place_ids"],
        "server_owns_order_time_route": True,
    }
    case["expectations"]["state"] = {"applied": False, "confirmation_required": True}
    if mode == 2:
        case["fixtures"]["secondary_result_after_primary"] = {"tool": "search_places", "must_not_override_primary_type": True}
        case["expectations"]["tool_call"]["allowed_extra_tools"] = ["search_places"]
    if index == 5:
        case["case_type"] = "plan_tool_failure"
        case["expected_response_type"] = ResponseType.TEXT.value
        case["reference"] = "일정 변경안을 만드는 중 오류가 생겼어. 아직 저장되지 않았어. 다시 시도할까?"
        case["fixtures"]["force_tool_error"] = {"name": "create_plan", "status": "failed"}
        case["expectations"]["behavior"]["requirements"] = ["도구 실패를 성공이나 저장 완료로 설명하지 않는다."]
    return case


def memory_case(source: dict[str, Any], corpus: dict[int, dict[str, Any]], index: int) -> dict[str, Any]:
    place = corpus[source["relevant_place_ids"][0]]["name"]
    mode = index % 4
    explicit_preferences = [
        ("나는 조용한 곳을 좋아해. 다음 여행에서도 기억해 줘.", "quiet_places", "조용한 곳을 좋아하는구나. 다음 추천에도 그 취향을 고려할게."),
        ("야외보다는 실내 체험을 더 좋아해. 기억해 줘.", "indoor_activities", "실내 체험을 더 좋아하는구나. 다음 추천에도 그 취향을 고려할게."),
        ("나는 일정을 느긋하게 보내는 편이 좋아. 기억해 줘.", "relaxed_pace", "느긋한 일정을 좋아하는구나. 다음 일정 제안에도 그 속도를 고려할게."),
        ("나는 역사 이야기가 있는 곳을 좋아해. 기억해 줘.", "history", "역사 이야기가 있는 장소를 좋아하는구나. 다음 추천에도 반영할게."),
        ("붐비는 곳은 피하고 싶어. 다음에도 기억해 줘.", "avoid_crowds", "붐비는 곳을 피하고 싶은 거구나. 다음 추천에서도 그 점을 고려할게."),
    ]
    explicit_query, explicit_facet, explicit_response = explicit_preferences[index // 4]
    queries = [
        explicit_query,
        f"{place}에서 사진을 많이 찍었어. 그래서 내가 무조건 이런 곳을 좋아하는 걸까?",
        f"지난 일기에서 {place} 얘기를 했지? 그날 좋았던 점을 다시 알려줘.",
        f"{place}이 포함된 여행의 마지막 일정 변경만 되돌리고 싶어. 내 일기나 취향은 그대로 둬.",
    ]
    references = [
        "사용자가 명시한 조용한 장소 선호를 정확히 해석한다. 기억 저장 완료는 서버의 실제 반영 결과가 있을 때만 말한다.",
        "사진을 많이 찍었다는 행동만으로 장기 취향을 확정하지 않고 좋아했는지 확인한다.",
        f"제공된 일기 원문에 있는 {place}의 좋았던 점을 출처에 맞게 설명하며 새로운 경험을 꾸며 내지 않는다.",
        "계획 변경만 되돌리려는 의도를 확인하고 취향·일기·사진을 함께 삭제하거나 되돌리지 않는다. 대상 변경 기록을 확인한 뒤 미리보기와 확정 흐름을 따른다.",
    ]
    spoken = [
        explicit_response,
        "사진을 많이 찍었다는 것만으로 좋아한다고 단정하긴 어려워. 어떤 점이 좋았는지 알려줄래?",
        f"일기에 {place}을 조용히 둘러볼 수 있어서 좋았다고 썼어. 그곳의 차분한 분위기가 좋았던 거구나.",
        "어느 계획의 어떤 변경을 되돌릴까? 일정만 대상으로 하고 일기나 취향은 건드리지 않을게.",
    ]
    case = case_base(
        source, case_id=f"MGR-MEMORY-{source['group_id']}", group="managerLLM",
        kind=("explicit_preference", "inferred_preference", "diary_recall", "rollback_scope")[mode],
        query=queries[mode], response_type=ResponseType.CLARIFICATION if mode == 3 else ResponseType.TEXT,
        reference=spoken[mode], tracks=["tool_call", "memory", "state", "message"],
        calls=[tool("ask_clarification", {"missing": ["되돌릴 계획 변경"]})] if mode == 3 else [],
    )
    quote = f"{place}에 다녀왔다. 조용히 둘러볼 수 있어서 좋았다."
    case["input"]["memory_sources"] = [{
        "sourceId": f"fixture-diary-{index}", "sourceVersion": 2,
        "text": quote, "provenance": "synthetic diary fixture; not a real user record",
    }] if mode == 2 else []
    case["input"]["candidate_place_ids"] = []
    case["reference_contexts"] = [quote if mode == 2 else queries[mode]]
    case["expectations"]["memory"] = {
        "explicit_preference": explicit_facet if mode == 0 else None,
        "inference_requires_confirmation": mode == 1,
        "required_source_ids": [f"fixture-diary-{index}"] if mode == 2 else [],
        "rollback_scope": "plan_only" if mode == 3 else None,
    }
    if mode == 2:
        case["fixtures"]["memory_store"] = [
            *case["input"]["memory_sources"],
            {"sourceId": f"fixture-unrelated-{index}", "sourceVersion": 1,
             "text": "다른 날에는 날씨가 흐렸다.", "provenance": "unrelated synthetic memory"},
        ]
        case["expectations"]["memory"]["relevant_memory_ids"] = [f"fixture-diary-{index}"]
        if index % 8 == 6:
            case["input"]["memory_sources"] = []
            case["expectations"]["tool_call"]["required_calls"] = [tool("recall_memory", {"query": f"{place}에서 좋았던 점"})]
            case["expectations"]["tool_call"]["query_matching"] = "semantic; hard tool checks omit free-text query equality"
            case["fixtures"]["memory_read_mode"] = "tool_recall"
        else:
            case["fixtures"]["memory_read_mode"] = "automatic_retrieval"
    case["expectations"]["state"] = {"applied": False, "confirmation_required": mode == 3}
    case["expectations"]["behavior"]["requirements"] = [references[mode]]
    if mode == 3:
        case["expectations"]["behavior"]["missing"] = ["되돌릴 계획 변경"]
    return case


def main() -> None:
    target = ROOT / "cases.source.json"
    if target.exists():
        raise SystemExit("cases.source.json already exists; edit the canonical source instead of reseeding.")
    source_cases = read_jsonl(LEGACY / "golden.jsonl")
    corpus_rows = read_json(LEGACY / "corpus.json")
    corpus = {place["id"]: place for place in corpus_rows}
    cases = planner_cases(source_cases, corpus) + manager_cases(source_cases, corpus)
    assert len(cases) == 200
    assert sum(case["evaluation_group"] == "plannerLLM" for case in cases) == 100
    assert sum(case["evaluation_group"] == "managerLLM" for case in cases) == 100
    for source_name, target_name in (
        ("corpus.json", "corpus.source.json"),
        ("snapshot.json", "snapshot.json"),
        ("golden.jsonl", "source_goldenset_v1.3.0.jsonl"),
        ("review_notes_filled_v1.3.0.csv", "review_notes.csv"),
    ):
        shutil.copyfile(LEGACY / source_name, ROOT / target_name)
    write_json(target, {
        "dataset_version": "1.4.0", "architecture": "one conversational/control LLM plus tools",
        "groups_are_evaluation_tracks_not_separate_models": True,
        "source_dataset": "Evaluation/datasets/v1.3.0",
        "cases": cases,
    })
    print("Authored 200 canonical cases: 100 plannerLLM + 100 managerLLM.")


if __name__ == "__main__":
    main()
