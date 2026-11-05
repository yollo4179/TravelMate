"""Builds conversation-smoke-v3-holdout: new wordings of the failures that 1d6ad65d was written against.

The v3 cases were read while writing that fix, so passing them again cannot show that it generalizes. These cases ask the
same kinds of things in words the fix never saw. Keep them out of prompts and few-shot examples, or they stop being held out.
Run from the repository root: python Evaluation/datasets/conversation-smoke-v3-holdout/build_cases.py
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
V3_BUILDER = HERE.parent / "conversation-smoke-v3" / "build_cases.py"


def v3_builder():
    # The v3 directory name is not a package name, so its helpers are loaded from the file they are defined in.
    specification = importlib.util.spec_from_file_location("conversation_smoke_v3_builder", V3_BUILDER)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def build() -> dict:
    v3 = v3_builder()
    no_filter = {"region": None, "city": None, "category": None, "excludePlaceIds": [], "area": None}
    ask_back = "ASK_BACK"
    no_other_region = {"id": "state_and_uncertainty",
                       "guidance": "데이터에 없는 지역에서 다시 찾아 주겠다거나 검색 범위를 바꿔 주겠다고 약속하지 않는다."}
    cases = [
        # Outside the catalog (v3: 부산 해운대 with a Seoul filter).
        # Changed with V3-D-outside-catalog (user's decision, 2026-11-05): areas outside the place data get the server's line.
        v3.outside("V3H-outside-jeju", "제주도 성산일출봉 쪽 볼거리 추천해줘.", v3.SEOUL, "제주",
                   "제주 장소는 데이터에 없다고 알리고 서울 결과를 제주 장소처럼 말하지 않는다."),
        v3.outside("V3H-outside-gangneung-no-filter", "강릉 경포대 주변에 가 볼 만한 데 있어?", no_filter, "강원",
                   "강릉 장소는 데이터에 없다고 알리고 다른 지역 결과를 강릉 장소처럼 말하지 않는다."),
        # Planning conditions given in words (v3: conditions answered in a later turn).
        v3.talk("V3H-conditions-first-message", "모레 오후 2시부터 6시까지, 시청역에서 출발해서 덕수궁 근처로 일정 짜줘.",
                "PLAN", "CLARIFY",
                "말로 준 조건만으로는 초안을 만들 수 없으면 앱에서 일정 조건을 입력해 달라고 안내하고, 만들 수 있다고 약속하지 않는다.",
                outcome=ask_back, branches=["CLARIFY", "GENERATE_PLAN"]),
        # A further exclusion on a list that already excludes 173 (v3: "세 번째도 빼 줘").
        v3.search("V3H-exclude-fifth-also", "다섯 번째 것도 추가로 빼고 보여줘.", {**v3.JONGNO, "excludePlaceIds": [173]},
                  "이미 뺀 장소를 유지한 채 다섯 번째 장소를 더 빼고, 끝난 제외를 다시 묻지 않는다.", displayed=v3.AFTER_173,
                  exclusion={"positions": [5], "place_ids": [371]}),
        # Nothing in the catalog matches (v3: 바다 보이는 해수욕장).
        v3.search("V3H-no-match-ski", "종로에서 스키 탈 수 있는 데 추천해줘.", v3.JONGNO,
                  "조건에 맞는 곳을 찾지 못했다고 솔직히 말하고 관련 없는 장소를 맞는 것처럼 소개하지 않는다.",
                  extra=(v3.EVIDENCE_ONLY, no_other_region)),
        # Information the data does not hold (v3: 운영시간·입장료, 주차).
        v3.unsupported(v3.talk("V3H-no-data-wheelchair", "창경궁에서 휠체어 빌릴 수 있어?", None, "CHAT",
                               "휠체어 대여 여부는 확인할 수 없다고 말하고, 찾아서 확인해 주겠다고 약속하지 않는다.",
                               extra=(v3.NO_HOURS, v3.CAPABILITY_ONLY))),
    ]
    return {"schema_version": "conversation-smoke-v3", "cases": cases}


if __name__ == "__main__":
    document = build()
    (HERE / "cases.json").write_bytes((json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    print(len(document["cases"]), "cases")
