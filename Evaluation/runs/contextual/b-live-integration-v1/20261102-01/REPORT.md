# B안 최초 실제 연결 실행 — 두 번째 문항 오류로 중단

2026-11-02 KST, 실행 소스 커밋 `aea9d343524b71a79866168af243e9140a14a7ca`.

승인된 4문항을 순차 실행하던 중 첫 문항은 완료했고, 두 번째 문항은 Qwen이 검색 도구의 필수 `query`를 누락해 실패했다. **첫 실행 오류 중단 조건을 적용해 나머지 2문항은 실행하지 않았다. 재시도는 없다.** 전체 4문항 검증 완료나 검색·설명 품질의 일반적인 통과를 주장하지 않는다.

실제 Qwen 호출은 **3회/상한 8회**, 검색 백엔드 실행은 **1회/상한 4회**다. 검색 도구 실행 시도는 2건이지만 두 번째는 인자 검증에서 거부되어 Kafka·검색 DB로 전달되지 않았다. 계획 Job·judge·GPT·유료 호출은 0회다. 실행 이후 한도 변경, 원문 절단, 코드 수정, 추가 검색은 하지 않았다.

## 실행 범위와 환경

- 기존 [B안 실행 범위](../../runtime-qwen-independent-search-v1/20261102-01/execution-scope-proposal.json)의 4문항·입력 해시·각 1회 조건을 그대로 사용했다. 새 문항이나 반복을 추가하지 않았다.
- Windows Spring `127.0.0.1:18080` → 전용 Kafka → 평가 FastAPI·검색 DB 경로로 실행했다. 원래 실행 환경과 운영 DB에 요청하지 않았다.
- 공급자 `QWEN`, 모델 `qwen3:8b`, `think=false`, context 8,192, 출력 예약 1,536을 유지했다. 도구는 `SEARCH_PLACES`만 등록되고 요청당 모델 2회·도구 1회, 도구 실패 시 `STOP`이다.
- 검색은 기존 장소 벡터와 Top-30 후보를 사용한다. 기존 관계 검색·장소별 근거 상한·활성 상한을 변경하지 않았다. 보존된 TourAPI 설명은 후보 검색 후 원문 근거로 연결한다. 새 청크 임베딩이나 recall 개선 실험이 아니다.
- 임베딩·리랭킹은 CPU이며 평가 검색 컨테이너는 CPU 2개·메모리 6GiB 제한이다. 리랭커는 `BAAI/bge-reranker-v2-m3`, `cross_encoder_predict`, batch 8이다.
- Qwen의 [Ollama 메타데이터](raw/ollama-residency.json)는 `llamacpp`, Q4_K_M, context 8,192와 `size_vram=640543621`을 보고했다. **검색 CPU 실행과 전체 요청의 CPU-only 실행은 구분한다.** Qwen 전체가 CPU-only였다고 단정하지 않는다. 기존 GPU 지연·순위와 직접 비교하지 않는다.
- [실행 바인딩](runtime-binding.json)에 JAR 해시·DB·토픽을 기록했다. 준비 당시 배포 manifest의 base commit은 `b80aa78b`지만, 실제 배포 소스 251개 파일의 해시가 실행 커밋의 파일과 모두 일치한다. 준비 manifest의 과거 `no_actual_B_execution` 표시는 당시 준비 상태이며 이번 실행 상태를 뜻하지 않는다.

실제로 한 번 실행한 명령은 다음과 같다. 이미 종료된 배치이며 같은 환경에서 다시 실행하지 않았다.

```powershell
C:/ssafy/Travelmate/.venv-ragas/Scripts/python.exe -X utf8 Evaluation/environments/b-plan/run_b.py --runtime Server/TravelMate/build/b-evaluation --output Server/TravelMate/build/b-live-first --execute
```

## 문항별 판정

| 순서·기존 case ID | 도구 선택·인자 | 검색 관련도 | 근거 전달 | 설명의 근거 일치 |
| --- | --- | --- | --- | --- |
| 1. `PLR-TM-palaces-01` | 검색 선택 적합. 서버는 인자를 승인했으나 제시된 스키마의 필수 필드 일부 누락 | 창경궁 378이 반환 1위, 기존 qrel 관련도 3/3 | TourAPI 원문 641자와 출처·귀속·해시 보존 | 전달 원문에 근거한 설명과 인용 확인. 단일 긍정 사례 범위 |
| 2. `PLR-TM-palaces-03` | 검색 선택은 적합. `query` 누락으로 `INVALID_TOOL_CALL` | 미관측: 검색 미실행 | 미관측 | 미관측: 서버 실패 안내만 반환 |
| 3. `PLR-TM-palaces-04` | 중단 정책으로 미실행 | 미관측 | 미관측 | 미관측 |
| 4. `PLR-TM-family_parks-04` | 중단 정책으로 미실행 | 미관측 | 미관측 | 미관측 |

구조화된 판정은 [assessment.json](assessment.json)에 있다. 기존 골든셋의 장소 관련도와 관측 원문을 대조한 기록 검토이며 별도 judge 모델은 실행하지 않았다.

### 첫 문항: “창경궁을 찾아줘.”

Qwen의 원본 도구 인자:

```json
{"region":"서울","query":"창경궁","limit":1}
```

검색어를 장소명으로 줄인 것은 이 문항의 의도와 일치한다. 실제 적용 필터는 `region=서울`, `city/category/area=null`, `exclude_place_ids=[]`이며 `RERANKED`로 검색했다. 후보 30개 중 반환 1개이고, 반환 순위 1위는 창경궁이다. 장소 semantic score는 `0.6240623817406676`, rerank score는 `0.9998594522476196`이다. 이 점수를 정답 확률로 해석하지 않는다.

다만 `SearchPlacesTool.definition()`은 `ToolSchemas.object()`를 사용해 모든 property를 required로 제시한다. 이 원본 호출은 `city`, `category`, `exclude_place_ids`, `area`를 누락했다. 현재 `PlaceSearchCriteriaResolver`는 이러한 누락에 기본값·searchContext를 적용하므로 실행에 성공했다. **서버 실행 승인과 제시 스키마 준수는 같지 않으며, 이 문항의 인자를 완전한 스키마 준수로 판정하지 않는다.** 스키마와 서버 허용 범위의 차이는 후속 검토 대상이다. 이번 실행에서는 이를 수정하지 않았다.

실제 전달된 근거는 다음과 같다.

| 항목 | 관측값 |
| --- | --- |
| 장소 / TourAPI content ID | `378` / `126511` |
| 원문 종류 / snapshot | `tourapi`, `places.description` / `1.4.0` |
| 원문 길이·범위 | Unicode codepoint 641개, `[0, 641)` |
| 내용 SHA-256 | `12706ec5165ca2f48e2846d995b745959c1546a73a1511507ad2fe81adb97a72` |
| source ID | `f9778e87-11f5-5d07-83fa-33e8350a3a40` |
| chunk ID | `bf9df996-8689-5216-80e3-0a315752721f` |
| 귀속 | `place_refs=[{"role":"subject","place_id":378}]` |
| 생성 보충 문맥 | `{}`. 관계·리뷰·수집 시각·출처 URL을 만들어 추가하지 않음 |
| 벡터 대응 | `NOT_EMBEDDED`, semantic score의 범위는 `place_candidate` |

동결 corpus → 검색 DB 결과의 `evidence_chunks` → Spring 공개 결과 → LLM용 `selectedEvidence.original` → 최종 공개 data의 원문이 모두 동일했다. description 요약은 400자로 잘리지만 별도 original은 641자 전체를 유지했다. 검색 후보를 새 원문 청크의 벡터로 찾았다는 의미는 아니다.

LLM에 전달한 원문·metadata·귀속은 실제 `TOOL_RESULT.modelData`에서 추출한 [llm-delivered-evidence.json](llm-delivered-evidence.json)에 보존했다. 후속 호출의 전체 입력 SHA-256·정확 토큰 계산·실제 사용량은 [model-calls.json](model-calls.json)에 있다. **공급자로 나간 전체 native HTTP body 자체를 별도 캡처한 것은 아니다.** 추출 파일을 별도의 wire 캡처로 표시하지 않는다.

최종 설명은 성종·대비·수강궁·왕실 가족 생활공간·소실과 중건·동향 배치 등 전달 원문의 내용을 창경궁에 귀속해 설명했다. 실제 [최종 응답](raw/PLR-TM-palaces-01.response.json)에 출처 인용 1개가 있고, quote 632자는 전달 원문 안의 정확한 부분 문자열이다. 장소 ID·evidence ID·source ID도 전달한 근거와 일치한다. 관측 답변에서 다른 장소로 귀속하거나 원문에 없는 장소 사실을 추가한 사례는 발견하지 못했다.

이 문항에는 상충·부정 근거가 없으므로 그 처리 품질은 검증하지 못했다. 답변의 “현재의 모습” 표현은 동결 설명의 역사 서술을 재서술한 것이며 현재 운영·통행·시설 상태를 확인한 결과가 아니다. 단순 장소 조회에 설명 567자와 원문 대부분의 인용을 생성한 점은 응답 길이·지연 측면의 한계다.

### 두 번째 문항: “종로에서 조선 왕실 가족이 생활했던 궁이나 거처를 둘러보고 싶어.”

Qwen의 실제 원본 인자:

```json
{"excludePlaceIds":[],"area":null,"region":"서울","city":"종로","category":null}
```

모델은 검색 도구를 선택했지만 `query`를 넣지 않았다. 서버는 `Search query required`를 기록하고 `INVALID_TOOL_CALL`로 거부했다. 최종 `termination=TOOL_FAILED`, `messageSource=SERVER_FALLBACK`이며 HTTP status는 200이다. **HTTP 200을 작업 성공으로 집계하지 않는다.**

코드와 원본 인자를 대조하면 `excludePlaceIds`도 도구 계약의 `exclude_place_ids`와 다르고, 제시 스키마의 `limit`도 누락했다. 실제로 먼저 발생한 오류는 `query` 누락이다. 나머지는 오프라인 계약 대조 결과이며 추가 호출로 확인한 오류가 아니다. 입력 searchContext와 유사한 형태를 출력했지만 이 한 번의 관측으로 모델 내부 원인을 단정할 수는 없다.

이 실패는 근거 부족 응답이나 검색 백엔드 장애가 아니다. 모델이 생성한 도구 인자의 오류를 서버가 검색 전에 차단한 것이다. 실제 검색 결과·원문·LLM 설명이 없으므로 관련도나 근거 충실도에 성공·실패 점수를 만들어 넣지 않는다. [실패 응답](raw/PLR-TM-palaces-03.response.json)과 [원본 이벤트](raw/events.jsonl)를 그대로 보존했다.

## 실제 토큰·호출·지연

상주 계산기는 세 호출 모두 같은 session/PID에서 초기화 1회 상태로 동작했다. 시작 시 초기화 `5838.545ms`는 이번 요청별 계산 시간과 구분한다. 세 호출의 정확 계산값은 Ollama의 실제 `prompt_eval_count`와 모두 같았다.

| 문항·모델 턴 | 정확 입력 / 실제 입력 | 출력 예약 | 입력+예약 / context | 실제 출력 | 가드 내 계산 시간 | 실제 모델 요청 시간 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| palaces-01 · 1 | 974 / 974 | 1,536 | 2,510 / 8,192 | 35 | 89.165ms | 16.872초 |
| palaces-01 · 2, 검색 결과 누적 후 | 2,735 / 2,735 | 1,536 | 4,271 / 8,192 | 1,012 | 120.932ms | 239.970초 |
| palaces-03 · 1 | 997 / 997 | 1,536 | 2,533 / 8,192 | 44 | 55.450ms | 7.206초 |

입력 사용량 합 4,706, 출력 사용량 합 1,091은 실제 호출 영수증 합계다. 누적 대화가 재전달되므로 고유 문서 토큰 수와 같지 않다. cached input은 합 1,893으로 보고됐으며 reasoning 사용량은 세 영수증 모두 null이다. `think=false` 설정을 근거로 누락된 사용량을 실제 0으로 바꾸지 않았다. 유료 외부 호출은 없고 로컬 전력·장비 비용은 측정하지 않았다.

첫 문항의 단계별 관측은 [stages.json](stages.json), 모델 호출별 전체 기록은 [model-calls.json](model-calls.json)에 있다. 아래 검색 단계 시간은 span 구간이다. 중첩 구간이므로 합산해 전체 시간으로 만들지 않는다.

| 단계 | 관측 시간 |
| --- | ---: |
| worker queue span | 36.648ms |
| query embedding, CPU | 4.396초 |
| 장소 벡터 후보 DB 조회 | 49.655ms |
| contextual evidence DB 조회 | 6.230ms |
| 리랭킹, CPU · 30 pairs · 4 batches | 112.268초 |
| 검색 worker pipeline 전체 | 116.878초 |
| Spring Kafka roundtrip | 117.662초 |
| 검색 도구 전체 | 117.776초 |
| 첫 문항 API 전체 | **375.335초** |
| 두 번째 문항 API 전체 | **7.292초**, 인자 검증 실패로 종료 |

리랭킹은 모델 로드 후 첫 실제 inference로 기록됐고 warmup은 하지 않았다. 두 번째 Qwen 호출은 기존 240초 read timeout에 매우 가까운 시간에 응답했지만 실제 영수증과 완료 응답이 존재하므로 timeout 실패로 기록하지 않는다. 한 번의 지연으로 일반 지연 분포나 기존 GPU 대비 성능을 주장하지 않는다.

## 호출 수와 평가 기록의 무결성

- [collector run.json](raw/run.json)의 `completed_validated_model_calls=2`는 첫 **완료 문항**의 호출 수다. 실패 문항의 Qwen 1회까지 포함한 실제 dispatch 수는 원본 `MODEL_CALL FINISHED`를 감사한 **3회**다. 두 값을 혼동하지 않는다.
- [평가 DB 감사](raw/database-audit.json): Spring 검색 요청 1행·검색 DB 요청 1행, 검색 worker `attempt_count=1`, 결과 1행, 계획 Job 0개, 장소 인덱싱 Job 0개다. 두 번째 인자 오류는 검색 DB 요청을 만들지 않았다.
- 원본 이벤트 17개는 모두 `LIVE`다. API 요청·응답, 실제 provider tool calls, 앱 tool call ID, 실제 도구 결과, 최종 응답·종료 사유를 보존했다. 인증 헤더·JWT·DB 자격증명은 게시하지 않는다.
- [records.jsonl](raw/records.jsonl)은 배치 중 첫 완료 문항까지 작성된 원본이다. 중단 뒤 새 모델·검색 없이 기존 변환기를 실행해 실패 문항도 포함한 [records-all-observed.jsonl](raw/records-all-observed.jsonl)을 별도로 만들었다. 기존 파일을 덮어쓰지 않았다.
- 실패 문항의 변환 기록은 observation coverage가 모두 false다. 첫 문항도 native 인자와 동결 도구 계약이 달라 `tool_call=false`이며, 기존 검색 설정과의 비교 가능성을 인증하지 않아 `search=false`다. 원본을 legacy 계약에 맞게 고치지 않고 별도 projection은 `PROJECTED_NOT_SCORED`로 유지했다.
- 첫 문항의 기존 장소 판정표는 반환 장소의 관련도를 해석하는 데만 사용했다. 모델이 `limit=1`을 택했으며 전체 후보의 ID·개별 점수·순위 목록은 현재 런타임에서 보존하지 않는다. 후보 수·리랭킹 입력 지문·반환 1위는 관측됐지만 Top-5/10 지표나 전체 candidate recall 점수는 계산하지 않았다.
- 원본 OTLP [runtime-traces.jsonl](raw/runtime-traces.jsonl)에는 준비 때부터의 health span도 포함된다. 파생 단계 파일은 실행 시작 이후 검색 관련 span만 선택했다. Spring·worker·queue의 trace ID가 하나로 이어지지 않아 전역 parent-child trace 연결을 완료했다고 표시하지 않는다. DB 요청 ID·동일 query·단일 검색 요청·시간 구간으로 이번 검색을 대조했다.
- [verification.json](verification.json)의 17개 항목은 저장된 실제 기록에 대한 오프라인 무결성 검사다. 4문항의 의미 품질 통과 수나 새 JUnit 테스트 수가 아니다. 원문·내용 해시·귀속·인용·예산·실제 호출 수·중단 상태와 raw 복사의 바이트 일치를 확인했다.

## 남은 한계

1. **4문항 실행 미완료:** 제외·단청 부정 조건과 500m 반경 문항은 중단으로 미실행이다. 올림픽공원피크닉장 원문 연결의 실제 B안 동작은 이번 결과로 확인하지 못했다.
2. **도구 인자 신뢰성:** 필수 query 누락과 camelCase/snake_case 혼용을 관측했다. 첫 문항에서도 제시 스키마와 서버의 누락 허용 범위가 달랐다. 실행 결과를 성공으로 만들기 위한 사후 보정·재호출은 하지 않았다.
3. **지연:** 첫 문항의 CPU 검색에 약 118초, 근거를 받은 최종 Qwen 응답에 약 240초가 걸렸다. 토크나이저 초기화 반복이 원인이라고 볼 기록은 없다. 설명 길이와 인용 길이도 함께 검토할 필요가 있다.
4. **의미 품질 범위:** 긍정 원문 1건의 전달과 설명 일치는 확인했다. 부정 반전·상충 무시·다른 장소 귀속을 일반적으로 해결했다고 주장하지 않는다. 시점이 없는 snapshot 설명은 현재 사실 확인을 대신하지 않는다.
5. **관측·평가 범위:** 전체 provider wire body와 전체 후보 순위는 미보존이다. native·projection·수동 기록 판정을 분리했으며, 기존 GPU와의 순위·지연 비교 점수는 없다. 계획·수정·확정·롤백·실제 이동시간·동선 최적화도 이번 검증 대상이 아니다.

이번 커밋은 실제 실행 산출물·오프라인 판정·한계 기록만 추가한다. 동결 골든셋·manifest·기존 보고서·애플리케이션 코드를 수정하지 않는다. 사용자 로컬 미커밋 수집기도 덮어쓰지 않는다. 다음 실행은 이번 실패와 계약·지연 문제를 검토한 후 별도 범위를 정해야 하며, 남은 문항을 자동으로 이어 실행하지 않았다.
