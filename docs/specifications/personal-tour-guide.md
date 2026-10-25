# 개인화 투어 가이드 상세 명세서

[전체 구조도](../architecture/personal-tour-guide.md) · [문서 목록과 결정표](../README.md) · [FastAPI 추천 API·DB 명세](fastapi-place-recommendation.md)

작성일 2026-10-24. 코드 분석 기준 `a275e49`. 이 문서는 **기존 문서·코드에 연결할 구현 참고안**입니다. 사용자 지정 요구사항, 현재 구현 사실, 신규 계약 제안을 구분합니다. 신규 API·테이블·도구는 아직 적용하지 않았습니다.

2026-10-25 검색 경계 갱신: Spring 원본 → Outbox → Kafka → FastAPI 검색 인덱스의 CQRS 구조로 구체화했습니다. FastAPI는 본문·필터용 복사본으로 검색·리랭킹하고, Spring은 최신 상세 일괄 조회·인증·Context·계획 반영을 담당합니다. [신규 검색 계약](fastapi-place-recommendation.md)은 `f9f09db` 코드와 사용자 선택을 기준으로 작성했습니다. 아래 기존 코드 사실과 새 구현 목표를 구분합니다.

## 1. 요구사항과 확정 범위

| ID | 요구사항 | 근거·상태 |
|---|---|---|
| FR-01 | 기존 의미검색과 계획 Context를 기본으로 확장 | 사용자 지정 |
| FR-02 | 의미검색 → Top-K → 리랭킹 결과로 1개 또는 한 번에 여러 곳을 생성·배정 | 사용자 지정. 생성/배정의 세부 구분은 6장 해석안 |
| FR-03 | 리뷰 질문의 답변·일기를 의미 분석해 취향과 과거 경험을 찾음 | 사용자 지정 |
| FR-04 | 명시적으로 말한 취향은 자동 저장, 추론한 취향은 확인 후 저장 | D-01 사용자 답변으로 확정 |
| FR-05 | 나만의 투어 가이드 여자친구와 텍스트·STT·TTS로 여행 관리 | 사용자 지정 |
| FR-06 | 대화로 만든 계획 변경은 미리보기 후 음성·버튼으로 확정 | D-04 사용자 답변으로 확정 |
| FR-07 | 장소 추가·삭제·배정 등 계획 변경 롤백 | D-02 사용자 답변으로 확정. 기억·일기·사진은 계획 롤백 대상 아님 |
| FR-08 | 실제 카메라에 가이드 아바타를 합성해 함께 촬영 | D-03 사용자 답변으로 확정. 별도 VR 세계 촬영으로 바꾸지 않음 |
| FR-09 | 사진을 여행별 앨범 목록에 저장하고 일기·장소와 연결 | 사용자 지정 |
| FR-10 | FastAPI가 자신의 검색 테이블에서 후보를 조회·리랭킹하고 Spring이 반환 ID로 원본 상세 일괄 조회 | 사용자 지정. [구조도](../architecture/fastapi-place-recommendation.md)·[명세](fastapi-place-recommendation.md) |
| FR-11 | Kafka로 원본 변경 전달, FastAPI가 임베딩·본문·지역·좌표 복사본 저장 | 사용자 선택 확정. 원본과 검색 인덱스 수정 소유권 분리 |

아직 고정하지 않는 항목은 대화·음성·사진·기억의 보관/삭제 정책, 기억 검색 인덱스 도입, Top-K·툴 반복 한도, 제공자·렌더링 엔진입니다. 아래 상태·필드·API 이름과 경계 사례는 구체화를 위한 검토안이며 제품 정책의 최종 승인으로 간주하지 않습니다. 평가 범위·지표·정답 형식은 이 문서에서 새로 지정하지 않습니다.

## 2. 기존 문서와 현재 구현에서 확인한 것

| 영역 | 코드에서 확인한 상태 | 참고할 위치 |
|---|---|---|
| 취향 입력 | 여행별 themes·avoid·pace·partySize·budgetKrw 필드 존재. 장기 프로필 저장·조회는 아님 | [PlanContext](../../Server/TravelMate/src/main/java/com/yollo/TravelMate/domain/plan/data/request/PlanContext.java) |
| 조건 보관 | `plans.context`, `request_payload`, `pins.stay_minutes` 저장 | [ContextPlanRepository](../../Server/TravelMate/src/main/java/com/yollo/TravelMate/domain/plan/repository/ContextPlanRepository.java), [마이그레이션](../../Docker/migrations/20261013_add_planning_context.sql) |
| 과거 계획 | 사용자 소유 계획과 핀 저장·조회 코드 존재. 실제 방문 이력과 동일하지 않음 | [PlanRepository](../../Server/TravelMate/src/main/java/com/yollo/TravelMate/domain/plan/repository/PlanRepository.java) |
| 검색 | 임베딩 → 조건 필터와 Top-K=30 → 리랭킹 → 요청 limit | [PlaceSemanticSearchService](../../Server/TravelMate/src/main/java/com/yollo/TravelMate/domain/place/service/PlaceSemanticSearchService.java) |
| 위치 조건 | SQL에서 좌표와 반경 조건을 Top-K 전에 적용. 도보 경로가 아닌 직선거리 계산 | [PlaceSemanticSearchRepository](../../Server/TravelMate/src/main/java/com/yollo/TravelMate/domain/place/repository/PlaceSemanticSearchRepository.java) |
| 생성 | 새 DRAFT 생성·저장, 후보 ID·중복·필수 장소·체류시간 검사. 일반 일정 편집·롤백은 미구현 | [ContextPlanningService](../../Server/TravelMate/src/main/java/com/yollo/TravelMate/domain/plan/service/ContextPlanningService.java) |
| 생성 한도 | 현재 생성 결과는 1~6개 장소를 허용. 운영시간·실제 이동시간까지 검증하는 상태는 아님 | [ContextPlanResultValidator](../../Server/TravelMate/src/main/java/com/yollo/TravelMate/domain/plan/validator/ContextPlanResultValidator.java) |
| LLM | system/user 문자열 → content 문자열. `tools`, `tool_calls`, tool 결과 누적 계약 없음 | [LlmClient](../../Server/TravelMate/src/main/java/com/yollo/TravelMate/ai/llm/base/LlmClient.java), [OllamaLlmClient](../../Server/TravelMate/src/main/java/com/yollo/TravelMate/ai/llm/derived/OllamaLlmClient.java) |
| AI 대화 저장 | 기존 `chats`는 room_id·user_uid·message 기반 방 채팅 구조. AI role·추론·툴 결과 저장으로 간주할 수 없음 | [기존 스키마](../../Docker/init/01-schema.sql), [영속화 비교안](../../MDs/chat_persistence_options.md) |
| 설계상 툴 | search_places·get_place_details·build_schedule·preview_edit과 PlannerDecision 제안 존재 | [서버 명세 DOCX](../../TravelMate_server_specification.docx) 14~16장 |
| 설계상 변경 | version·변경안·apply API를 제안. 모델에 저장·확정 툴을 노출하지 않음 | 같은 서버 명세 12~15장 |
| 음성 | InputMethod.VOICE enum 존재. 이것만으로 STT/TTS 연결 완료가 아님 | [GeneratePlanRequest](../../Server/TravelMate/src/main/java/com/yollo/TravelMate/domain/plan/data/request/GeneratePlanRequest.java), 서버 명세 20장 |
| 카메라 합성·앨범 | 개인 가이드 아바타와 촬영·앨범 저장 흐름은 신규 요구사항 | 이번 사용자 지정 |

기존 검색 툴 문서의 `PlaceVectorRepository` 등 일부 클래스명은 현재 분리된 Repository보다 오래됐습니다. 연결은 위 현재 코드 기준으로 하고, 문서에 제안된 기능을 현재 구현으로 오인하지 않습니다.

## 3. 역할 분담 제안

| 모듈 | 책임 | 하지 않는 일 |
|---|---|---|
| GuideTurnOrchestrator | 한 사용자 발화의 Context 구성·도구 반복·결과와 작업 ID 관리 | 모델이 반환한 문장을 저장 성공 증거로 사용하지 않음 |
| ContextAssembler | 이번 조건·현재 계획·관련 취향·과거 기록을 구분해 구성 | 과거 취향으로 확정된 여행 조건을 조용히 변경하지 않음 |
| ReviewDiaryAnalyzer | 리뷰·일기의 대상·속성·긍부정·시점·범위·이유와 원문 근거 추출 | 추론을 명시적 취향이라고 자동 승격하지 않음 |
| MemoryService | 출처·사용자·version 검증, 명시 취향 자동 반영, 추론 확인 처리 | 계획 롤백에 맞춰 기억을 함께 되돌리지 않음 |
| HistoryRecallService | 개인 기록에서 이번 질문에 관련된 경험을 검색 | 다른 사용자 자료나 미확인 방문을 실제 경험으로 섞지 않음 |
| ToolRegistry / ToolExecutor | 허용 함수·스키마·호출 범위·호출 결과 식별자 검증 | 임의 함수명·SQL·사용자 UID를 모델에 위임하지 않음 |
| PlaceRecommendationClient / FastAPI RecommendationPipeline | Spring은 한 번 호출하고 FastAPI가 임베딩·검색 복사본 조회·모드별 순위를 처리. Spring이 최신 원본 일괄 조회·버전 확인 | FastAPI가 원본·개인 기억·계획 테이블을 조회·수정하지 않음 |
| OutboxRelay / PlaceIndexConsumer·Worker | 원본과 이벤트 원자 기록 → Kafka → 영속 접수 → 버전 확인 후 검색 복사본·벡터 반영 | Kafka 접수 완료와 검색 반영 완료를 혼동하지 않음 |
| ScheduleBuilder / Validator | 후보 선택 결과로 실제 시간·경로·제약 계산 | LLM이 쓴 이동시간을 계산 결과로 채택하지 않음 |
| PlanMutationService | 미리보기·확정·실제 계획 변경·revision·롤백 | 외부 모델 호출을 긴 DB 트랜잭션 안에서 수행하지 않음 |
| AlbumMediaService | 사용자 소유 앨범·업로드·파일 상태·가이드 설정 연결 | 파일 업로드 성공과 앨범 DB 저장 성공을 혼동하지 않음 |
| Android 공통 상태 | 지도·일정·대화·음성 결과가 같은 planVersion을 표시 | TTS 재생이나 취소만으로 DB 변경을 재실행하지 않음 |

현재 생성 서비스의 기능을 모두 다시 만드는 의미가 아닙니다. 검색·검증·저장 코드를 재사용하고 빠진 인터페이스를 연결하는 구조안입니다.

특히 현재 `ContextPlanningService.generate()`·`create()`는 DRAFT를 실제 저장하므로 새 대화 미리보기 툴에서 그대로 호출하지 않습니다. 기존 API를 유지하면서 후보 조회·계산·검증과 저장을 분리하는 내부 인터페이스가 필요합니다. 미리보기는 현재 계획을 변경하지 않으며 사용자 확정 뒤에만 변경을 적용합니다.

## 4. 논리 데이터 모델 제안

기존 소유자 키 `users.uid`는 VARCHAR(36), `plans.plan_id`, `pins.pin_id`, `places.id`는 BIGINT를 기준으로 연결합니다. 신규 세션·메시지·소스·후보·미디어 식별자는 UUID 사용 제안입니다. 기존 ID를 모델 출력의 이름 문자열로 대체하지 않습니다. 아래는 논리 스키마이며 실행용 DDL이 아닙니다.

| 저장 항목 | 주요 필드 제안 | 참조·검증 |
|---|---|---|
| `guide_profiles` | id, owner_uid, display_name, avatar_asset_id, persona_config JSONB, voice_config JSONB, version | 촬영 시 가이드 설정 version을 기록. 음성·아바타 제공자는 미정 |
| `guide_sessions` | id, owner_uid, plan_id nullable, guide_profile_id, current_focus_place_id, context_version, created_at | 앱의 currentEditingPlan·선택 마커와 연결. 완전한 계획의 원본은 plans |
| `guide_messages` | id, session_id, role, text, input_method, reply_to_message_id, plan_version, created_at | USER/ASSISTANT/TOOL 역할 구분. 시스템 생성문을 사용자 취향 발언으로 분석하지 않음 |
| `tool_executions` | id, turn_id, tool_call_id, tool_name, validated_arguments, result_ref, status, error_code | tool 결과와 실제 plan 변경을 구별. 같은 turn의 assistant 호출과 결과 대응 |
| `memory_sources` | id, owner_uid, source_kind, source_record_id, source_version, created_at | CONVERSATION/REVIEW/DIARY의 실제 원문 위치. 종류에 맞는 기록 하나와 연결 |
| `trip_reviews` | id, owner_uid, plan_id, place_id nullable, question_text, answer_text, question_target, version | 가이드의 질문과 답변을 함께 저장. 장소가 모호하면 확인 전 target 미확정 |
| `diary_entries` | id, owner_uid, plan_id nullable, occurred_at, title, body, version | 작성일과 경험 시각을 구분. 수정 시 분석 대상 version도 구분 |
| `memory_candidates` | id, source_id, source_version, facet, value JSONB, polarity, scope JSONB, evidence_quote, evidence_span, interpretation, status, version | EXPLICIT/INFERRED/AMBIGUOUS 해석 구분. 원문 구절·문자 위치를 재검증 |
| `user_preference_facts` | id, owner_uid, facet, value JSONB, polarity, scope JSONB, status, version, valid_from, supersedes_id | 명시 자동 반영 또는 추론 확인 후 반영한 유효 사실. 숫자 신뢰도만으로 확정하지 않음 |
| `preference_evidence` | preference_id, candidate_id, source_id, source_version, activation_method | AUTO_EXPLICIT / USER_CONFIRMED 등 반영 근거 추적. 여러 근거가 한 취향을 뒷받침할 수 있음 |
| `user_activity_events` | id, owner_uid, event_type, plan_id, place_id, changeset_id, occurred_at, payload JSONB | SEARCHED/ADDED/REMOVED 등 구분. 방문 확인 이벤트는 실제 확인 경로가 있을 때만 생성 |
| 기존 `plans` 확장 | version, current_revision_id, updated_at | 사용자 소유 조건과 현재 계획을 version으로 보호하는 제안 |
| `plan_revisions` | id, plan_id, version, snapshot JSONB, created_at | 순서·핀 ID·placeId·체류시간·조건 등 복원에 필요한 완전한 상태 |
| `plan_changesets` | id, plan_id, base_version, result_version, operations JSONB, before_revision_id, after_revision_id, reverts_changeset_id, actor, idempotency_key | 어느 추가·삭제·배정을 취소하는지 식별. 같은 취소 재요청도 중복 반영 방지 |
| `trip_albums` | id, owner_uid, plan_id nullable, title, created_at | 여행별 앨범 목록과 미분류 앨범 제공 여부는 UI 상세 확정 시 결정 |
| `album_items` | id, album_id, owner_uid, place_id nullable, captured_at, guide_profile_id, guide_version, capture_mode, caption, status | 카메라 합성 사진과 촬영 당시 가이드 설정 연결. 위치 자동 저장 여부는 미정 |
| `media_assets` | id, album_item_id nullable, owner_uid, storage_key, media_type, byte_size, checksum, processing_status | 실제 파일과 미리보기 구분. 파일 저장 방식과 파생 썸네일 생성 위치는 미정 |
| `diary_album_links` | diary_id, album_item_id, ordinal | 본인 일기와 본인 사진만 연결. 사진에 붙인 모델 생성 설명은 사용자 원문과 구별 |

데이터 연결 규칙의 구현안:

- 소유자 검증은 UID 문자열을 받는 것만으로 끝내지 않고 세션→계획→리뷰/일기→사진 참조까지 확인합니다.
- 캐시·벡터 인덱스·요약은 원본 기록 ID와 version을 가집니다. 원문 수정 후 오래된 분석을 현재 취향으로 반영하지 않습니다.
- 원문 삭제 시 연결 취향·요약·임베딩·사진 링크를 어떻게 처리할지는 D-05로 확인해야 합니다. 임의의 보관 기간·자동 삭제 범위를 이 문서에서 지정하지 않습니다.
- 일괄 변경을 하나의 changeset으로 보관하면 한 번에 되돌리기 쉬우며, 항목별 부분 취소 지원 범위는 D-08과 함께 확인할 세부 사항입니다.

## 5. 답변·일기의 의미를 어떻게 분석하고 기억하는가

### 5.1 원문을 해석 가능한 대상으로 연결

리뷰 질문은 대상 여행·placeId·관련 추천 또는 변경안 ID를 함께 저장합니다. 일기는 본문에서 장소명이 나오더라도 현재 여행·명시된 장소 참조를 대조합니다. 대상이 여러 개인 “거기는 별로”를 첫 후보에 임의로 연결하지 않습니다.

가이드가 던질 리뷰 질문과 아래 해석 사례는 검토용 예시이며 정해진 설문이나 점수 체계가 아닙니다.

| 사용자 표현 예시 | 분리할 의미 | 처리 방향 |
|---|---|---|
| “나는 조용한 곳을 좋아해.” | 소음/혼잡 관련 명시 선호, 일반 범위 | 명시 취향 자동 반영. 실제 저장한 해석을 사용자에게 표시 |
| “오늘은 비 와서 실내가 좋아.” | 오늘·날씨라는 제한이 있는 명시 선호 | 이번 범위의 선호로 보관. 평생 실내 선호로 확대하지 않음 |
| “전시는 좋았는데 사람이 많아서 힘들었어.” | 전시에 대한 긍정 경험, 혼잡에 대한 부정 경험 | 경험은 원문대로 기록. 평소 전시 선호·혼잡 회피를 추론했다면 확인 |
| “많이 걸어서 피곤했지만 등산 자체는 좋아.” | 걷기 피로와 등산 선호의 대비 | 부정어만 추출해 ‘등산 싫음’으로 저장하지 않음 |
| “친구는 박물관을 싫어해.” | 발화 주체는 사용자, 선호 주체는 친구 | 사용자 자신의 취향으로 자동 저장하지 않음 |
| “지난번 그 공원 말고 다른 곳.” | 과거 장소 참조와 이번 제외 요청 | 이번 검색 제외에 사용. 공원 전체를 싫어한다고 장기 저장하지 않음 |

명시·추론을 나누는 세부 경계 사례는 구현 전 사용자 검토가 필요합니다. 모델의 설명이나 임의의 confidence 임계값만으로 자동 반영 여부를 결정하지 않는 구조로 제안합니다.

### 5.2 분석 출력 계약 예시

다음은 모델이 만든 분석 후보 예시입니다. 실제 사용자 데이터나 저장 결과가 아닙니다.

```json
{
  "sourceId": "source-example",
  "sourceVersion": 3,
  "candidates": [
    {
      "facet": "crowd_preference",
      "value": "LESS_CROWDED",
      "polarity": "PREFER",
      "scope": {"kind": "GENERAL"},
      "interpretation": "INFERRED",
      "evidenceQuote": "사람이 많아서 힘들었어",
      "proposedQuestion": "앞으로 덜 붐비는 곳을 우선 추천할까요?"
    }
  ]
}
```

서버는 source 소유자와 version, 원문 구절의 실제 존재, 주체·범위·명시성의 검증 결과를 확인합니다. 후보의 원문 문자 위치는 서버가 다시 찾아 기록하는 방식으로 제안합니다. 모델이 붙인 `EXPLICIT` 라벨만 신뢰해 바로 저장하는 계약은 아닙니다.

### 5.3 반영과 수정

- **명시 취향:** 검증 후 자동 반영하고 사용자에게 무엇을 기억했는지 표시합니다. 이미 같은 사실이 있으면 중복 사실을 계속 생성하지 않고 근거를 연결하는 구조안입니다.
- **추론 취향:** 후보와 근거를 보여준 뒤 확인·수정·거절을 받습니다. 미확인 후보는 추천에 사용하는 유효 취향 조회에서 제외합니다.
- **모호함:** 대상·발언 주체·부정 범위를 확인합니다. 추측한 해석을 명시 취향으로 저장하지 않습니다.
- **변경 발언:** “이제는 등산이 좋아”와 일회성 예외를 구분합니다. 어떤 기존 취향을 대체했는지 version과 근거를 남기는 제안입니다.
- **원문 수정:** sourceVersion이 달라지면 진행 중 후보를 재분석 대상으로 두고 오래된 후보 확인을 거부합니다. 이미 활성화한 기억의 수정·삭제 전파는 D-05 확정 후 구현합니다.

### 5.4 기억 조회와 추천 반영

1. 인증 사용자·활성 여행·현재 계획 version을 서버에서 확정합니다.
2. 관련된 유효 구조화 취향을 조회합니다. 추론 미확인·철회·다른 사용자의 기억을 제외합니다.
3. “지난번”, “그때”, “아까”는 세션 메시지·여행 날짜·placeId·변경 이력으로 먼저 좁힙니다.
4. 필요하면 좁힌 개인 리뷰·일기에서 의미 검색합니다. 검색 인덱스 사용 여부는 별도 결정이며, 공개 관광지 인덱스와 개인 기록 조회 범위를 구분합니다.
5. 사용한 기억마다 sourceId·sourceVersion·기억 version을 Context에 포함합니다. 원문 전체를 무조건 프롬프트에 넣지 않습니다.
6. 이번 확정 조건과 과거 취향이 다르면 적용 범위를 구분합니다. 폼의 필수 조건을 모델이 완화하지 않으며 충돌하면 질문합니다.

취향은 추천 순위의 근거가 될 수 있지만 운영시간·거리·예산처럼 사실과 계산이 필요한 값을 만들어내지 않습니다. ‘피하고 싶음’과 ‘절대 제외’의 강도는 사용자 표현과 확정 조건을 확인해 구분해야 하며, 기존 `avoid` 문자열만으로 모든 금지 조건이 구현돼 있다고 간주하지 않습니다.

## 6. 검색·자동 생성·자동 배정 계약 초안

현재 동작: query와 여행별 themes·additionalRequest를 사용해 후보를 검색합니다. 새 생성 작업은 필수 장소와 검색 후보를 병합하고, LLM 선택·검증 후 DRAFT를 저장합니다. 개인 장기 기억은 아직 주입하지 않습니다.

자동 생성·배정 용어의 해석안은 다음과 같습니다. 이 표의 기존 계획 배정·대체 범위를 최종 기능으로 고정하려면 D-08을 확인합니다.

| 요청 형태 | 해석안 | 결과 |
|---|---|---|
| 한 곳 추천 | 조건에 맞는 후보 한 곳을 제시 | 장소 카드와 근거, 저장 전 상태 |
| 한 곳 배정 | 기존 계획의 특정 위치·빈 시간에 장소 하나를 배치 | 추가/대체 미리보기 |
| 일괄 생성 | 여러 후보로 새 계획 초안을 구성 | 계획 초안과 아직 확인되지 않은 조건 |
| 일괄 배정 | 기존 필수 장소·잠금 조건을 유지하며 여러 위치에 배치 | 변경 전후 미리보기 |

공통 흐름 제안:

```text
이번 요청 + 여행 조건 + 필요한 취향·과거 경험
→ 지역·반경·제외·필수 조건 정리
→ Spring 추천 클라이언트가 FastAPI 한 번 호출
→ FastAPI 내부 의미 쿼리 임베딩
→ FastAPI가 조건 필터 후 검색용 복사본 DB Top-K 조회
→ 요청 모드에 따라 같은 후보를 리랭킹
→ 실제 장소 ID·원본 버전·점수를 Spring으로 반환
→ Spring이 최신 원본 상세 일괄 조회·버전 검증·순위 복원
→ 1개 또는 일괄 선택
→ 필요한 상세·실제 경로·시간 검증
→ 변경안과 가이드 설명
→ 음성 또는 버튼 확정
→ 실제 저장 결과와 새 planVersion
```

현재 Top-K=30과 생성 1~6곳은 코드 사실입니다. 새 모드에 같은 한도를 유지할지, 날짜·슬롯·다일 여행까지 지원할지는 지정 전 확장하지 않습니다. 실제 도보 경로·운영정보가 연결되지 않은 현재 단계에서는 검증 완료 일정으로 표시하지 않습니다.

검색 책임 이전의 첫 검증에서는 현행 후보 수·모드·모델·점수를 보존합니다. 공개 검색 응답은 Spring이 기존 DTO로 매핑하며, Kafka 동기화·검색 복사본·권한·필터·실패·trace 계약은 [추천 API·이벤트·DB 명세](fastapi-place-recommendation.md)를 따릅니다.

## 7. 툴 호출은 어떻게 동작하는가

### 7.1 호출·권한 경계

LLM은 JSON 형태의 도구 요청을 출력합니다. Spring의 실행기가 허용된 이름·인수·소유권·이번 요청의 후보 범위를 검증한 후 함수를 호출합니다. 실행 결과를 tool 메시지로 돌려주면 LLM이 다음 정보 요청 또는 최종 제안을 만듭니다.

한 번의 사용자 요청에는 `turnId`, 한 검색에는 `candidateSetId`, 계산한 일정에는 `scheduleId`, 변경안에는 `proposalId`를 발급하는 구조안입니다. ID가 DB에 존재하는지만 확인하지 않고 **이 사용자·세션·요청에서 발급한 ID인지** 검증합니다.

### 7.2 허용할 툴 목록 제안

| 툴 | 모델이 제안하는 인수 | 서버가 주입·검증하는 것 | 반환 |
|---|---|---|---|
| `get_user_preferences` | 필요한 주제·항목 | 인증 UID, 유효 상태·범위, 최소한의 관련 항목 | 취향·근거·version |
| `recall_user_history` | query, 기간/여행/장소 참조 | 본인 소스만, 요청 시간·대상 해석, 미확인 방문 구분 | 과거 사건·원문 근거·sourceVersion |
| `search_places` | semanticQuery, categories, limit | 확정 지역·반경·제외·사용자 Context. 쿼리와 지역 필터 분리 | candidateSetId, 실제 장소·소개·검색 점수 |
| `get_place_details` | placeIds | 현재 후보 또는 현재 계획의 ID인지 확인, 방문일 주입 | 운영·가격·출처·확인 상태 |
| `build_schedule` | 후보 placeIds와 허용된 체류시간 조정 | 출발/도착·날짜·시간·이동수단·필수 장소·잠금 | scheduleId, 방문 순서·계산 결과·문제 |
| `preview_edit` | 허용된 추가·삭제·이동·체류 변경 | planId·expectedVersion·소유권·편집 가능 범위 | proposalId, 차이·scheduleId·경고 |
| `list_user_albums` | 여행·기간·검색 문구 | 본인 앨범과 공개 범위 | 앨범 목록·사진 수·대표 이미지 참조 |
| `get_album_items` | 현재 대화의 albumId·itemIds | 앨범·미디어 소유자와 접근 범위 | 사진 메타데이터와 접근 가능한 미디어 참조 |

기존 서버 명세의 네 툴을 재사용하고 개인 기억·앨범 조회를 확장한 제안입니다. 카메라 실제 촬영은 앱에서 사용자가 수행합니다. 명시 취향 반영은 MemoryService의 정책 처리이며, 모델에 임의의 프로필 쓰기·계획 저장·롤백·파일 삭제 툴을 직접 주지 않는 구조입니다.

툴 입력에서 UID·자유 SQL·임의 파일 경로·전체 시스템 명령을 받지 않습니다. 모델 출력의 내부 필드명과 실제 Ollama wire 필드의 대응은 모델/서버 버전을 확인한 어댑터에서 처리합니다.

### 7.3 대화 메시지를 보존하는 순서

1. 시스템 지침, trusted Context, 사용자 요청, 관련 기억을 구분해 구성합니다.
2. 현재 요청에 허용된 도구 스키마와 함께 모델을 호출합니다.
3. assistant의 `tool_calls` 원본을 보존하고 각각의 호출에 ID를 대응시킵니다.
4. 독립적인 조회만 병렬 실행합니다. 검색 결과가 필요한 상세 조회·배치 계산, version에 의존하는 변경은 순서대로 실행합니다.
5. 결과·실패를 해당 호출의 tool 메시지로 추가합니다. 실패를 빈 성공 결과로 바꾸지 않습니다.
6. 필요한 경우 다음 도구 요청을 처리합니다. 반복·총 호출·시간 한도는 D-06 확정 전 임의로 고정하지 않습니다.
7. 최종 단계에서 허용된 출력 스키마로 PlannerDecision을 받습니다. 이번 요청의 검증된 scheduleId/proposalId인지 다시 확인합니다.
8. 제안과 실제 저장 상태를 분리해 앱에 전달합니다. 사용자 확정 이후에만 계획 변경을 반영합니다.

현재 `generate(systemPrompt, userPrompt)`는 이 대화 기록을 표현할 수 없습니다. 다음과 같이 인터페이스 역할을 분리하는 제안입니다.

```text
LlmClient
  기존 generate(systemPrompt, userPrompt)       기존 JSON 생성 경로 유지
  신규 chat(messages, toolSchemas, outputSpec) tool_calls와 메시지 이력 반환

ToolRegistry
  허용 함수명 → 입력 스키마 → 실행 핸들러

ToolExecutor
  검증된 요청 → 기존 서비스 호출 → typed ToolResult

GuideTurnOrchestrator
  Context 구성 → 모델/도구 반복 → 제안 → 사용자 확정 연결
```

### 7.4 제안과 저장 결과의 출력 예시

ID와 문장은 계약 예시이며 실제 실행 기록이 아닙니다.

```json
{
  "turnId": "turn-example",
  "planId": 120,
  "baseVersion": 7,
  "proposalId": "proposal-example",
  "selectedScheduleId": "schedule-example",
  "phase": "PREVIEW",
  "operations": [{"type": "ADD", "placeId": 378, "afterPinId": 501}],
  "guideMessage": "창경궁을 추가하는 건 어때? 적용할지 확인해 줘.",
  "memoryEvidence": [{"preferenceId": "pref-example", "sourceVersion": 3}]
}
```

실제 반영 응답에는 `phase: APPLIED`, `resultVersion`, `changeSetId`, 실제 적용한 핀과 작업 결과를 반환하는 계약안입니다. 단순히 `guideMessage`에 “추가했어”가 있다고 저장 완료로 판단하지 않습니다. 계획 확정(CONFIRMED)과 변경 적용(APPLIED)도 다른 상태입니다.

## 8. 일정 변경 확정과 롤백

### 8.1 변경 적용

미리보기는 baseVersion과 원문 요청·적용할 operations를 보관합니다. 음성이나 버튼 확정은 동일한 `proposalId + expectedVersion + Idempotency-Key` 적용 API로 연결하는 구조입니다.

- 명확한 요청이어도 대화 기반 변경은 사용자가 변경안을 확인한 뒤 반영합니다.
- “응”, “좋아”라는 음성은 실제로 어느 미리보기를 확인하는지 식별돼야 합니다. 여러 제안이 열려 있거나 계획이 바뀌었으면 다시 묻습니다.
- 서버는 최신 version·소유권·후보·제약을 확인하고, 짧은 트랜잭션으로 plans/pins·revision·changeset·중복 요청 결과를 함께 확정하는 방식으로 제안합니다.
- 모델·경로 API 호출은 트랜잭션 밖에서 처리합니다. 외부 결과가 준비됐어도 version이 바뀌면 재검증하거나 충돌을 반환합니다.
- 저장 성공 후 앱의 지도·일정·대화가 같은 version을 표시합니다. 이벤트 전달 실패가 DB 변경을 중복 수행하게 만들면 안 됩니다. transactional outbox는 전달 보완 선택지이며 도입 확정은 아닙니다.

### 8.2 롤백

사용자가 “아까 추가한 곳 빼 줘”라고 하면 이전 도구 결과의 `changeSetId`와 실제 핀을 찾습니다. 되돌리기 미리보기를 만들고 음성·버튼 확정 후 새 변경으로 적용합니다.

| 상황 | 처리 계약안 |
|---|---|
| 직전 변경 취소 | 해당 changeset의 변경 전 상태 또는 검증된 역연산으로 복원 |
| 일괄 배정 취소 | 저장한 일괄 changeset을 기준으로 되돌릴 내용 표시. 부분 취소 범위는 상세 확인 필요 |
| 이후 다른 편집이 있음 | 현재 version과 비교해 충돌 표시. 과거 snapshot 전체를 덮어써 후속 편집을 잃게 하지 않음 |
| 같은 취소 재전송 | 같은 멱등 키·본문이면 같은 취소 결과. 반복해서 더 오래된 작업을 취소하지 않음 |
| 대상이 여러 개 | 어떤 변경인지 확인 질문 |
| 취향·일기·사진 | 계획 롤백에서 변경하지 않음 |

복원 내용이 과거 revision과 같더라도 새 planVersion을 부여합니다. 이력 삭제로 되돌린 것처럼 꾸미거나 LLM에게 과거 계획을 재생성시키지 않습니다. 취향 수정·삭제는 별도 관리 요청이며 ‘계획 롤백’의 확장으로 구현하지 않습니다.

## 9. 나만의 투어 가이드: STT·TTS

```text
마이크 입력 → STT 인식 문장 확인/수정 → 일반 사용자 메시지
→ 기억 조회와 검색·제안 → 변경안 표시
→ 음성 또는 버튼 확정 → 실제 반영 결과 → 가이드 문장과 TTS
```

- 기존 명세의 음성 인식 문장 확인 흐름을 유지합니다. 부분 인식 이벤트마다 검색·저장을 실행하지 않습니다.
- 텍스트와 음성은 같은 요청·제안·확정 계약을 사용합니다. 음성이라는 이유로 조건이나 소유권 검증을 생략하지 않습니다.
- 발화 페르소나는 가이드 캐릭터 설정입니다. 사실·기억 출처·저장 성공 여부와 분리합니다.
- 미리보기에서는 “넣어볼까?”, 실제 반영 후에는 “추가했어”처럼 상태에 맞게 발화합니다. 반영 실패를 성공 대사로 덮지 않습니다.
- TTS 재생을 끊는 행동과 일정 취소는 다릅니다. 말 끊기만으로 방금 저장한 계획을 되돌리지 않습니다.
- 음성 원본 보관·제공자·기기 내 처리·실시간 전송 방식은 미정입니다. 신규 종속성을 이번 문서에서 선택하지 않습니다.

## 10. 가이드와 함께 찍는 사진·앨범

### 10.1 사용자 흐름

1. 여행·가이드 프로필을 선택하고 카메라 프리뷰를 엽니다.
2. 실제 카메라 화면에 가이드 아바타를 합성합니다. 위치·크기·포즈 등 상세 조작 범위는 엔진 선택 전에 확인합니다.
3. 사용자가 촬영하고 결과를 확인한 뒤 앨범에 저장합니다.
4. 앨범 목록 → 여행별 사진 목록 → 사진 상세에서 촬영일·연결 장소·함께 찍은 가이드를 확인합니다.
5. 사진을 일기·리뷰에 연결하면 사용자가 쓴 글을 기억 분석 대상으로 사용합니다.

요구사항은 카메라 합성입니다. VR 여행 공간·헤드셋·가상 관광지 제작을 함께 구현한다고 해석하지 않습니다. 2D/3D·AR 공간 고정·렌더링 엔진은 미정입니다.

### 10.2 저장 계약안

- 앱 로컬 촬영 상태와 서버 앨범 저장 상태를 구분합니다. 업로드 또는 DB 반영이 실패하면 완료된 서버 사진 목록으로 표시하지 않습니다.
- 사진 파일은 저장소 어댑터에 두고 DB에는 소유자·파일 키·상태·촬영 당시 가이드 설정 version·앨범 연결을 둡니다. 제공자와 업로드 방식은 확정 전입니다.
- 큰 파일 업로드와 DB 트랜잭션은 원자적으로 묶을 수 없으므로 업로드 준비→파일 확인→앨범 항목 확정 상태를 구분하는 제안입니다. 재시도 시 같은 사진이 중복 생성되지 않게 요청 ID를 연결합니다.
- 일기와 사진 연결을 해제하는 것과 사진 파일을 삭제하는 것은 구분합니다. 삭제 전파·원본/합성본 보관 여부는 D-05 확인 후 정합니다.
- 모델이 만든 사진 설명은 사용자 리뷰 원문으로 취급하지 않습니다. 사진을 많이 찍었다는 사실만으로 해당 장소·활동을 좋아한다고 자동 저장하지 않습니다.
- 카메라 권한이 없거나 합성·업로드가 실패하면 해당 상태를 보여주고 기존 텍스트·여행 관리 기능은 유지하는 UX안입니다.

### 10.3 화면 연결 구조안

| 화면 | 입력·표시 | 연결 |
|---|---|---|
| 지도·공통 일정 편집기 | 현재 계획·선택 마커·version·변경 미리보기 | 가이드 대화, 장소 상세, 리뷰, 여행 앨범 |
| 나만의 투어 가이드 | 텍스트·음성 입력, 후보 카드, 변경 확인, TTS | 동일한 계획 상태와 기억 확인 카드 |
| 리뷰 | 가이드 질문·대상 장소·사용자 답변 | 분석 결과와 추론 취향 확인 |
| 여행 일기 | 본문·경험일·여행·사진 선택 | 기억 근거와 앨범 상세 |
| 앨범 목록 | 여행별 제목·대표 사진·개수 | 사진 목록과 새 촬영 |
| 사진 목록·상세 | 촬영일·연결 장소·가이드·저장 상태 | 일기 연결과 카메라 프리뷰 |
| 함께 촬영 | 실제 카메라와 가이드 아바타 합성·촬영 결과 | 선택한 여행 앨범 저장 |

앱이 모든 정보를 한 화면에 노출하는 의미가 아니라, 현재 여행·가이드·선택 장소를 공통 Context로 이어주는 구조입니다. UI 배치와 아바타 포즈 범위는 별도 디자인 결정입니다.

## 11. API 연결 명세 초안

### 11.1 현재 코드에 있는 API

모두 `/api/v1` 접두사입니다. 입력·반환형은 현재 Controller와 DTO가 기준입니다.

| 메서드 | 경로 | 현재 역할 |
|---|---|---|
| POST | `/places/search` | context·query·limit을 받아 장소 후보 반환 |
| POST | `/plans/generations` | 생성 작업 202 접수, jobId 반환 |
| GET | `/planning-jobs/{jobId}` | 작업 상태·결과 planId 조회 |
| POST | `/plans` | 필수 선택 장소로 새 초안 생성. 현재 빈 계획 생성 API가 아님 |
| GET | `/plans/{planId}` | 본인 계획의 Context·장소·체류시간 조회 |

### 11.2 신규 API 제안

아래는 구현 전 계약안입니다. 데이터 수정 요청은 인증 UID·소유권·관련 version을 서버에서 검증합니다. 멱등성과 오류 형식을 현재 계획 작업의 방식과 연결합니다.

| 메서드 | 경로(`/api/v1` 아래) | 입력 핵심 | 반환 핵심 |
|---|---|---|---|
| POST | `/guide-sessions` | planId nullable, guideProfileId | sessionId, 현재 Context |
| GET / PATCH | `/me/guide-profiles/{guideProfileId}` | 가이드 표시·아바타·음성 설정 조회/수정, expectedVersion | 본인 가이드 설정과 version. 프로필 개수·고급 꾸미기 범위는 별도 결정 |
| POST | `/guide-sessions/{sessionId}/turns` | clientMessageId, text, inputMethod, replyTo, expectedPlanVersion | turnId, 응답 또는 작업 참조 |
| GET | `/guide-sessions/{sessionId}/messages` | cursor | USER/ASSISTANT/TOOL 기록과 결과 참조 |
| GET | `/guide-turns/{turnId}` | 본인 turn 참조 | 진행 상태·제안·기억 반영/확인 요청 |
| POST | `/trip-reviews` | planId/placeId, question, answer, 대상 참조 | reviewId, sourceVersion, 분석 참조 |
| GET | `/trip-reviews` | planId/placeId/기간, cursor | 본인 리뷰·질문·답변 목록 |
| POST | `/diary-entries` | planId nullable, 본문, 경험일, albumItemIds | diaryId, sourceVersion, 분석 참조 |
| GET | `/diary-entries` | 여행/기간, cursor | 본인 일기 목록 |
| GET | `/diary-entries/{diaryId}` | 본인 일기 참조 | 본문·version·연결 사진·분석 상태 |
| PATCH | `/diary-entries/{diaryId}` | expectedVersion와 수정 내용 | 새 sourceVersion, 재분석 상태 |
| GET | `/me/preferences` | 주제·범위 | 유효 취향·근거·version |
| GET | `/me/memory-candidates` | 미확인 후보 cursor | 후보·근거·확인 질문 |
| POST | `/me/memory-candidates/{candidateId}/decisions` | expectedCandidateVersion, CONFIRM/EDIT/REJECT, 수정안 | 반영/거절 결과·기억 version |
| PATCH | `/me/preferences/{preferenceId}` | expectedVersion, 사용자 수정 내용 | 새 기억 version. 계획 롤백과 별도 |
| POST | `/plans/{planId}/proposals` | expectedVersion, 사용자 요청, 1개/일괄 대상 | jobId 또는 proposalId |
| GET | `/plans/{planId}/proposals/{proposalId}` | 본인 계획·제안 참조 | 미리보기·차이·경고·baseVersion |
| POST | `/plans/{planId}/proposals/{proposalId}/apply` | expectedVersion, 확인 입력, Idempotency-Key | resultVersion, changeSetId, 실제 결과 |
| POST | `/plans/{planId}/revert-proposals` | expectedVersion, targetChangeSetId | 취소 미리보기 proposalId. 같은 apply 경로로 확정 |
| GET | `/plans/{planId}/changesets` | cursor | 추가·삭제·배정·취소 이력 |
| POST / GET | `/trip-albums` | 제목/planId 또는 cursor | 앨범 생성 또는 목록 |
| GET | `/trip-albums/{albumId}/items` | cursor | 사진 목록·미리보기·촬영 메타데이터 |
| GET | `/trip-albums/{albumId}/items/{itemId}` | 본인 앨범·사진 참조 | 사진 상세·가이드 설정·접근 가능한 파일 참조 |
| POST | `/trip-albums/{albumId}/upload-tickets` | 파일 종류·크기·요청 ID | 사용자·앨범 범위의 업로드 참조. 전송 방식은 저장소 결정 후 확정 |
| POST | `/trip-albums/{albumId}/items` | uploadTicketId, 촬영일, 가이드 ID/version, placeId nullable | 업로드 검증 후 albumItemId·저장 상태 |
| POST | `/diary-entries/{diaryId}/album-links` | expectedVersion, albumItemIds | 본인 일기와 사진 연결 결과 |

API 목록은 필요한 역할을 보여주기 위한 초안입니다. 실시간 전송을 SSE 또는 기존 STOMP 중 하나로 확정하거나, 같은 명령을 양쪽에서 중복 실행하도록 구현한 상태는 아닙니다. 보관·삭제 정책 확인 후 삭제 API와 전파 작업도 별도로 확정합니다.

### 11.3 오류·경합 계약안

| 상황 | 처리 |
|---|---|
| 잘못된 도구 인수·해결되지 않은 대상 | 사용자 확인 또는 구조화 오류. 임의 장소·슬롯으로 대체하지 않음 |
| 다른 사용자 세션·일기·사진 참조 | 접근 거부. tool 실패 결과에 타인 원문을 포함하지 않음 |
| PLAN_VERSION_CONFLICT | 원래 계획 유지, 최신 계획 조회 후 변경안 재생성 |
| SOURCE_VERSION_CONFLICT | 오래된 기억 후보를 반영하지 않고 수정된 원문 재분석 |
| NO_FEASIBLE_SCHEDULE | 조건 충돌 표시. 필수 장소 제거·시간 연장을 몰래 수행하지 않음 |
| 외부 검색·경로·모델 실패 | 오류 종류와 재시도 가능 여부 표시. 거리·시간 0으로 성공 처리하지 않음 |
| 미디어 업로드/확정 실패 | 로컬 촬영·파일 업로드·앨범 완료 상태를 구분 |
| 같은 멱등 키에 다른 본문 | 409 등 충돌. 기존 계획 작업 규칙과 일치시키는 제안 |

## 12. 구조가 맞는지 확인할 시나리오

다음은 요구사항을 점검할 예시이며 평가셋·점수·통과율 기준을 새로 확정한 것이 아닙니다.

| 예시 | 확인할 결과 |
|---|---|
| “나는 조용한 곳을 좋아해” | 근거와 범위를 확인해 명시 취향 자동 저장·저장 내용 표시 |
| 일기에 “혼잡해서 피곤했다” | 사건을 보관하고 일반 취향 추론은 사용자 확인 전 유효 취향으로 쓰지 않음 |
| “지난번 싫었던 곳 빼고 추천해 줘” | 본인 기록과 대상 장소를 확인해 이번 요청에 적용 |
| 계획에 넣었지만 실제 방문하지 않음 | 추가 기록을 방문 완료로 바꾸지 않음 |
| 검색→한 곳 추가→음성 확인 | 후보·미리보기·실제 핀 저장·새 version·발화 내용이 연결 |
| 여러 곳 배정→되돌리기 | 해당 변경의 실제 상태로 복원하고 새 version 생성 |
| 계획 롤백 | 장기 취향·일기·앨범은 그대로 유지 |
| 미리보기 후 다른 기기에서 편집 | 오래된 제안을 바로 반영하지 않고 version 충돌 처리 |
| 가이드와 카메라 합성 사진 저장 | 실제 파일과 앨범 항목·가이드 version이 연결 |
| 사진에 일기를 연결 | 사용자 작성 글을 분석하고 모델 생성 캡션을 취향 원문으로 사용하지 않음 |

## 13. 구현 전에 남은 확인

- 대화·기억·일기·사진·원본 음성의 보관 기간과 삭제 전파 정책.
- 단일/일괄 생성·배정의 적용 단위, 일괄 변경 중 일부 취소 범위, 날짜·슬롯 범위.
- 명시 취향과 추론의 경계 사례, 일회성 조건과 장기 취향의 구분에 대한 사용자 검토.
- 기억 인덱스 도입 여부와 검색 수, 기존 Top-K 유지 여부, 도구 반복·시간 한도.
- STT/TTS 제공자, 아바타 형식·렌더링 엔진, 파일 저장소, 사진 위치 자동 저장 여부.

확인 전에는 해당 값을 임의의 기본 정책으로 고정하거나 실제 사용자 데이터를 이동·삭제하지 않습니다. 문서의 제안 계약을 바탕으로 사용자가 선택한 범위부터 구현 명세와 마이그레이션을 확정합니다.
