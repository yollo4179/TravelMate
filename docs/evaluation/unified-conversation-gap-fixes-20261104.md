# 요구 사항 미충족·부분 항목 수정과 모바일 전환 확인

[공통 파이프라인 구현 기록](unified-conversation-implementation-20261104.md)의 후속 작업이다.
그 구현을 요구 사항과 대조해 미충족·부분으로 판정한 항목을 고쳤다.

- 기준: `develop` `2ed8e2d6`. 이 문서와 함께 목적별 커밋으로 `develop`에 반영했다. 2026-10-25~11-01에 만들어져 Git에 추적되지 않은 평가 실행 원본 1,689개는 포함하지 않았다.
- 실제 모델(OpenAI) 호출, 실제 DB 적용, 재색인, 배포는 모두 0회다.
- 사용자 결정에 따라 유료 실측(#14·#15)과 ONDEVICE TTS(#16)는 보류했다.
- 9번 "장소의 청크는 15~20개"는 **장소마다 활성 청크 15~20개**로 해석하기로 사용자가 확인했다.

## 1. 변경 내용

| 요구 | 이전 판정 | 변경 |
|---|---|---|
| 로그: 값마다 기록 내용 주석 | 미충족 | `Evaluation/tracks/conversation/log_types.py`의 모든 Enum 값에 무엇을 기록하는지 주석을 달았다 |
| 로그: 람다도 같은 구조 | 부분 | `test_logs.py`를 대주제 3개(실행 식별·관측 원본·판정)와 소주제까지 Enum과 같은 순서로 맞췄다. 순서·누락·중복이 다르면 불러올 때 실패한다 |
| 로그: 모든 경로가 구조를 거침 | 미충족 | `score.py` 재채점 CLI가 파일명을 직접 쓰지 않고 `TestLogs.path`·`TestLogs.write`를 쓴다 |
| #1 평가·운영 동일 | 부분 | 평가 프로필이 대화 호출 상한을 덮어쓰지 않는다. 두 환경 모두 모델 6턴·도구 8회다. 실험 설정 값과 서버가 보고한 값이 다르면 대화 요청 전에 중단한다 |
| #9 장소별 15~20개 | 부분 | 상한 20은 유지했다. `MIN_TARGET_ACTIVE_CHUNKS=15`를 두고 `cli coverage`로 15개 미만 장소를 나열한다. 색인할 때 활성 청크 수와 미달 여부를 관측값으로 남긴다. 부족분을 복제·생성하지 않는다 |
| #10 2~3줄 근거 | 사실상 미충족 | `cli excerpts`로 검수한 인용 파일을 청크로 만들고, `--apply`로 `retrieval_excerpt_bundles`에 저장해 재색인을 요청한다. 색인할 때 생성 청크에 **더해진다.** 인용은 기본 200자(약 2~3줄)까지만 받고, 더 길면 `held_excerpts`로 보류한다 |
| #11 주차·후기·설명·체험 | 부분 | 관점 이름(`[주차]` 등)이 임베딩 문장에 들어간다. 관점별로 돌아가며 고르는 `aspect-source-round-robin-v2`를 추가했지만 **기본은 기존 `source-round-robin-v1`이다** |
| #13 하드코딩 | 부분 | 아래 표 |
| #17 계획에도 감정 | 부분 | `draft_plan_v1`에 `emotion`을 필수로 넣었다(Enum에서 생성). `plans.character_emotion`에 저장하고 DRAFT 응답의 감정으로 쓴다. 값이 없는 이전 초안만 기본값 EXCITED를 쓴다 |
| UI 지도 | 부분 | Vue 클라이언트에 카카오 지도(반경 원·끌기 핀·후보 마커)를 추가했다. 키가 없으면 좌표 보기로 바뀐다. 모바일 전환으로 중복이 됐다(5절) |
| 이미지 감정 | 거의 충족 | SAD 설명을 실제 이미지("선 채로")에 맞췄다. 헷갈리는 쌍(EXCITED/CONCERNED, HAPPY/GUIDING)의 구분점을 설명에 넣었다. PNG와 해시는 바꾸지 않았다 |
| 계획 감정: 기존 생성 경로 | 커밋 전 검토에서 발견 | 허용 감정 목록을 공용 계획 프롬프트(`PlanPrompts.PLANNER_SYSTEM`)로 옮겼다. 이전에는 문맥 계획 경로만 목록을 받아, 기존 `PlanGenerationService` 경로의 모델이 예시 필드만 보고 자유 문장을 쓰면 Enum 변환에서 계획 전체가 실패할 수 있었다 |
| AGENTS.md 규칙 | 커밋 전 검토에서 발견 | 검수 묶음 적용 결과 문자열을 `BundleApplyStatus` Enum으로 바꿨다. 매개변수가 많은 신규 선언·호출은 한 줄에 하나씩 쓰고, DRAFT 응답은 빌더로 만든다. Vue의 반경 범위 객체는 `reactive()`로 관리한다 |

### #13 하드코딩 제거

| 위치 | 이전 | 변경 |
|---|---|---|
| `PlaceConversationEvidence.java` | `"\n사용자 선호 테마: "` 문구를 Java에 직접 씀 | `conversation/queries/v1-theme-hint.txt` 리소스로 옮겼다. 채점(`score.py`)도 같은 파일을 읽는다 |
| `v2-grounded-system.txt` | 의도·답변 종류·감정·도구 이름·작업 상태 목록을 손으로 씀 | `{{token}}`을 `PromptVocabulary`가 Enum에서 채운다. 모르는 토큰이면 서버 시작 때 실패한다 |
| 반경 500~10000 | 서버 세 곳(요청 검증·계획 조건·도구 스키마)과 클라이언트 두 곳에 따로 있음 | 서버 `SearchRadius` 한 곳에서 정의하고 options 응답(`radiusMeters`)으로 내려준다 |
| `HomeView.vue` | 기본 좌표·반경·간격 숫자 | `searchDefaults.js` 상수로 옮겼다. 최소·최대는 서버 값을 쓴다 |
| `ReviewedExcerptModule` | `content_kind="other"` | `ContentKind.OTHER` Enum |
| AUTO 제외 의도 목록 | 스키마·검증에서 각자 필터 | `ConversationIntent.finalValues()` 하나를 공유한다 |

## 2. 적용할 때 필요한 작업

1. **DB 마이그레이션.** 이미 만든 개발·평가 DB에는 직접 적용해야 한다. 적용 전에 새 서버를 띄우면 초안 저장·조회가 컬럼 없음으로 실패한다.
   `psql ... -f Docker/migrations/20261104_add_plan_character_emotion.sql`
   새로 만드는 Docker DB는 `docker-compose.yml`과 `stack-up.sh`가 자동으로 적용한다.
2. `retrieval_excerpt_bundles`는 검색 서버가 시작할 때 `schema.sql`로 만든다. 별도 작업은 필요 없다.
3. 평가 서버의 `.env.evaluation.json`에서 `EVAL_MAX_MODEL_TURNS`·`EVAL_MAX_TOOL_CALLS`는 더 이상 쓰지 않는다.
4. 변경된 Spring·검색 소스로 두 서버를 다시 빌드·기동해야 평가의 소스 해시 검사를 통과한다.

## 3. 검증 결과

| 대상 | 결과 |
|---|---|
커밋 직전 최종 작업 트리에서 다시 실행한 결과다. 오프라인 MOCK·재채점·Docker 스크립트는 커밋 전 검토 수정 이전에 실행한 결과이며 다시 실행하지 않았다.

| 대상 | 결과 |
|---|---|
| 평가 Python | `test_conversation_plan`·`quality`·`registry`·`module_experiments` 50개 통과(`PYTHONUTF8=1`) |
| 오프라인 MOCK | tool_call·recommendation·plan·conversation 4단계 모두 `collected`, 실패 없음 |
| 기존 기록 재채점 | `20261104-offline-01`을 다시 채점하면 `scores.jsonl`·`review.csv`가 바이트 단위로 같다 |
| Java 전체 | 로컬 Docker 스택을 켠 상태에서 425개 중 423개 통과(첫 커밋만 적용한 상태에서도 같은 2개만 실패). 실패 2개는 환경 문제다. `RedisConnectionTest`는 스택 구성(`docker-compose.stack.yml`의 `ports: !reset []`)이 Redis를 호스트에 열지 않아서, `PlanGenerationTest` END_TO_END는 기존 계획 경로의 실제 검색 후보가 없어서(`PLAN_NO_CANDIDATES`) 실패했다. 새 `ConversationVocabularyContractTest` 5개 통과. Docker를 끈 상태에서는 Spring 컨텍스트 테스트 14개가 DB 연결 거부로 실패한다 |
| 외부 호출 | 전체 Java 테스트에 포함된 기존 통합 테스트가 Kakao 로컬 키워드 검색과 TourAPI 관광지 조회를 실제로 호출했다. TourAPI 결과는 모두 기존 데이터라 저장 0건이다. OpenAI 키가 설정돼 있지 않고, 계획 생성 테스트는 후보가 없어 모델 호출 전에 끝났으므로 모델 호출은 0회다 |
| 클라이언트(Vue) | 계약 테스트 8/8, ESLint·Prettier 통과, Vite 빌드 성공. Chromium 브라우저 테스트는 Playwright가 없어 미실행 |
| 임베딩 서버 | 183개 중 오류 2개, 32개는 DB가 없어 건너뜀(`PYTHONUTF8=1`). 오류 2개는 이 PC에 `torch`·`asyncpg`가 없어 테스트 모듈을 불러오지 못한 것이다. 새 테스트를 포함한 관련 15개는 통과 |
| Docker 스크립트 | 14개 오류는 변경 전후 동일(Linux 셸 필요) |

## 4. 남은 것

- **검수 데이터 0건.** #10·#11은 경로만 연결됐다. 실제 검수 파일 작성, `--apply`, 재색인, 품질 비교가 필요하다.
- **#12:** 기존 자동 생성 청크의 관계 재검수는 사람 작업으로 남았다.
- **#9:** 원문이 부족한 장소는 수집이 필요하다. `cli coverage`를 실제 DB에서 아직 실행하지 않았다.
- **관점별 선택 v2:** 품질 비교 전이라 기본값으로 켜지 않았다.
- **남은 하드코딩:**
  - 계획 프롬프트 본문(`PlanPrompts.java`, `ContextPlanPromptFactory.java`)이 아직 Java 문자열이다.
  - Vue의 의도 목록은 서버와 따로 있다. 다만 서버 값과 다르면 화면에 오류를 띄운다.
  - 검색 서버 SQL의 문서 상태 `'READY'`는 기존 코드 전반에서 문자열로 쓰며 Enum으로 바꾸지 않았다.
- **오프라인 기록:** `offline-fixtures.json`의 `promptSha256`은 Enum 값을 채운 v2 프롬프트의 해시(`1e643482…`)로 갱신했다. 이미 만든 `20261104-offline-01` 기록의 서버 계약에는 이전 원문 해시가 남아 있으며 수정하지 않았다.
- **보류(사용자 결정):** #14·#15 유료 실측, #16 TTS.
  - 상한이 운영과 같아져서 실측 때 문항당 모델 호출이 최대 6번까지 가능하다. 비용은 예산 원장이 막는다.

## 5. 모바일(Android) 전환 확인 사항

사용자가 클라이언트를 모바일로 하기로 했다. 확인한 현재 상태는 다음과 같다. 코드는 아직 바꾸지 않았다.

- `Android/`는 Kotlin, Jetpack Compose, Hilt, Retrofit 네이티브 앱이다. `compileSdk` 36이고, 이 PC에 Android SDK `android-36`이 있다.
- 이미 있는 것:
  - 로그인(카카오·네이버·구글), 장소 검색, 일정 생성 화면.
  - `common/components/MapContent.kt`가 카카오 벡터맵 SDK로 지도·핀·장소·반경을 그린다. **Vue에 추가한 카카오 지도는 이와 겹친다.**
- 없는 것:
  - 대화 API(`/api/v1/conversation/turns`, `/options`) 연동.
  - 대화 화면.
  - LiLi 감정 이미지.
  - 응답 계약(`intent`·`emotion`·`items`·`citations`) DTO.
- 전환 시 할 일(미착수):
  1. Retrofit `ConversationApi`와 요청·응답 DTO. `Idempotency-Key`·`X-Conversation-Id` 헤더를 보내고 options의 의도·감정·반경으로 검증한다.
  2. LiLi 이미지. 복사본을 만들지 않고 Gradle `sourceSets`의 assets 경로로 `Resouces/Images/LiLi`를 쓴다. `catalog.json`으로 감정과 이미지를 연결한다.
  3. Compose 대화 화면. `MDs/travel_app_screen_structure.md`대로 지도의 기준 핀·반경·수정 중 계획과 상태를 공유한다.
  4. #16 TTS. WASM은 웹 기술이라 Android에서는 네이티브 on-device 엔진과 모델 파일(BIN)로 다시 정해야 한다.
- 결정할 것: Vue 클라이언트를 개발·평가용으로 남길지, 지도 부분을 되돌릴지.
- **보안:** `Android/app/client_secret_*.json`(Google OAuth)이 Git에 추적되고 있다. 키 재발급, 추적 해제, 이력 정리가 필요하다. 내용은 이 문서에 옮기지 않았다.

## 6. 작업 중 발견한 기존 문제

- 공유 소스 228개가 이 작업 폴더에서 CRLF다. Git에는 LF로 저장돼 있어 Windows와 Linux의 소스 해시가 달라질 수 있다.
  - 이 때문에 `v1-grounded-system.txt` 해시 검사(`ConversationModulesTest`)가 실패했다. 내용이 HEAD와 같은 파일이라 다시 체크아웃해 LF로 맞췄고, 검사는 통과한다.
- Windows 기본 인코딩(cp949)에서는 UTF-8 기록을 인코딩 지정 없이 읽는 Python 테스트가 실패한다. `PYTHONUTF8=1`로 실행한다.
- 클라이언트 `package-lock.json`이 `package.json`과 맞지 않아 `npm ci`가 거부된다. 검증에는 lock 파일을 바꾸지 않는 설치를 썼다.

## 7. 새로 만든 파일

- `Server/.../conversation/data/ConversationAnswerKind.java`
- `Server/.../conversation/pipeline/PromptTemplates.java`
- `Server/.../conversation/pipeline/PromptVocabulary.java`
- `Server/.../place/data/request/SearchRadius.java`
- `Server/TravelMate/src/main/resources/conversation/queries/v1-theme-hint.txt`
- `Server/TravelMate/src/test/java/com/yollo/TravelMate/ConversationVocabularyContractTest.java`
- `Docker/migrations/20261104_add_plan_character_emotion.sql`
- `embedding-server/app/contextual/selection.py`
- `embedding-server/tests/test_excerpt_aspects_and_coverage.py`
- `Client/travel-mate-frontend/src/conversation/searchDefaults.js`
- `Client/travel-mate-frontend/src/conversation/kakaoMap.js`
- `Client/travel-mate-frontend/src/conversation/KakaoRangeMap.vue`
