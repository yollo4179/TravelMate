"""평가 단위와 실행 폴더 기준 로그 경로. 런타임 버전과 무관하게 고정한다.

TestLogPath의 대주제·소주제 순서는 test_logs.TestLogs.ENTRIES와 같아야 한다(불러올 때 검사).
"""
from enum import StrEnum


class EvaluationStage(StrEnum):
        # [평가 단위] 이 순서대로 실행한다. 오프라인 계약 통과는 실제 모델 품질 판정이 아니다.
        TOOL_CALL = "tool_call"                       # 도구 이름·인자·호출 횟수가 요청에 맞는가
        RECOMMENDATION = "recommendation"             # 후보 배열·원문 인용·추천 이유가 근거와 맞는가
        PLAN = "plan"                                 # Job 접수와 초안 내용(필수 장소·순서·체류시간·반경)
        CONVERSATION = "conversation"                 # 여행 외 질문·되묻기·감정 반응


class TestLogPath(StrEnum):
        # [1. 실행 식별] 무엇을 어떤 설정으로 실행했는가. 비밀값·환경 파일 사본은 기록하지 않는다.
        #      (1-1) 실행 설정
        RUN = "run.json"                              # 평가기 커밋·소스 해시, 설정·문항 묶음 해시, 실행 모드, 선택 문항, 진행 상태
        INPUTS = "inputs.jsonl"                       # 문항별 원래 API 요청과 입력 해시. 평가 정답은 넣지 않는다
        #      (1-2) 호출 원장
        ATTEMPTS = "attempts.jsonl"                   # 공통 RunControl이 전송 전에 남기는 호출 시도·상한·MOCK 응답 사용 여부
        #      (1-3) 실행 서버 계약
        SERVER_CONTRACT = "server-contract.json"      # Spring 평가 서버가 보고한 프로필·도구 계약·응답 형식·소스 해시
        SEARCH_CONTRACT = "search-contract.json"      # 검색 서버 /health: 소스 해시·임베딩/리랭커 장치

        # [2. 관측 원본] 실제 요청·응답·이벤트. 채점이나 검수를 고쳐도 다시 쓰지 않는다.
        #      (2-1) 응답
        RECORDS = "records.jsonl"                     # 문항별 HTTP 요청·응답 원문, 서버 requestId, 실행 상태
        #      (2-2) 서버 내부 관측
        EVENTS = "events.jsonl"                       # requestId로 묶은 사전 검색·모델 턴·도구 결과·최종 응답 이벤트

        # [3. 판정] 기계적 계약 검사와 사람의 의미 검수를 분리한다.
        #      (3-1) 기계적 검사
        SCORES = "scores.jsonl"                       # 문항별 자동 검사 결과·관측 호출 수·지연·응답·인용·계획 검사
        #      (3-2) 의미 검수
        REVIEW = "review.csv"                         # 사람이 채우는 기준별 판정표. 응답·제공 원문·기록 해시를 함께 싣는다
        #      (3-3) 요약
        SUMMARY = "summary.json"                      # 단계별 선택·기록·통과 수, 호출 원장 요약, 실패 사유, 미실행 문항
