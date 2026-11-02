# 검색 도구 계약 통일·Qwen 기존 로그 확인·출력 지침 정리

기준 커밋: `8e594546ecc3d335111859474bb0593691750bb5`. 이번 작업은 코드 수정·오프라인 모의 회귀·기존 로그 분석이며 **B안 모델·검색을 다시 호출하지 않았다.** 새 JAR는 빌드했으나 실행 중인 평가 서버를 교체하거나 배포하지 않았다.

검색 도구의 필수·선택·기본값을 공통 계약으로 연결했다. 첫 실제 성공 인자는 새 스키마에서도 승인되고, 두 번째 실제 실패 인자는 검색어 누락으로 계속 거부된다. 이 결과가 Qwen이 다음 호출에서 올바른 인자를 생성한다는 보장은 아니다.

## 1. 모델에 제시하는 계약과 서버 검증

이전에는 `SearchPlacesTool`이 모든 필드를 required로 제시했지만 `PlaceSearchCriteriaResolver`는 query 외 필드의 생략을 허용했다. 첫 실제 호출은 이 차이 때문에 서버에서는 성공하면서 제시 스키마에는 맞지 않았다.

새 `SearchPlacesContract`가 모델용 parameters와 서버의 구조·값 검증에 같은 스키마를 제공한다. 공유 schema 객체는 외부에서 변경할 수 없도록 복사해 반환한다. `ToolSchemas` 검증은 현재 서버가 작성하는 스키마의 type·anyOf·required·추가 필드 거부·enum·범위·문자 길이·공백·배열 중복 조건을 처리한다. 모든 JSON Schema 기능을 제공하는 범용 라이브러리로 표시하지 않는다.

| 도구 필드 | 필수 여부 | 생략 | 명시적 null | 값 제한 |
| --- | --- | --- | --- | --- |
| `query` | **필수** | 거부 | 거부 | 공백 아닌 문자열, 최대 2,000 codepoint. 질문에서 서버가 추측하지 않음 |
| `limit` | 선택 | **10** | 거부 | 정수 1~20 |
| `region`, `city`, `category` | 선택 | searchContext 상속 | searchContext 상속 | 지정 시 공백 아닌 문자열, 최대 200 codepoint |
| `exclude_place_ids` | 선택 | 빈 목록 | 빈 목록 | 양의 Long 범위 정수, 중복 불가. context 제외 ID와 합집합 |
| `area` | 선택 | searchContext 상속 | searchContext 상속 | 지정 시 CIRCLE, center.lat/lon, radius_meters 모두 필수 |

area는 위도 -90~90, 경도 -180~180, 반경 500~10,000m다. context도 없으면 해당 필터 제한이 없다. 도구에 지정한 지역·도시·분류·area가 context와 충돌하면 기존과 같이 거부한다. 검색어 없는 `{}`나 API 형태의 `excludePlaceIds`를 도구용 snake_case로 자동 보정하지 않는다. 계획 입력만 있는 기존 검색의 area 상속도 유지했다.

문자열 길이는 JSON Schema와 동일하게 codepoint로 계산하며, 유효 검색 DTO의 길이 검사도 `CodePointLength`로 맞췄다. 보충 문자가 포함된 문자열의 UTF-16 길이 때문에 모델 스키마 승인 후 DTO가 길이를 다르게 거부하는 차이를 방지한다. 검색 순위·벡터·거리 계산·후보/활성 상한·계획 저장 로직은 변경하지 않았다.

실제 생성된 [스키마](fixtures/contract.json)와 [독립 검증 결과](independent-schema-verification.json)를 보존했다. Python `jsonschema` Draft202012Validator와 Java resolver는 실제 호출 인자 2건 및 기술적 인자 회귀 17건에서 모두 같은 승인·거부 결과를 냈다. 이는 19개 새 여행 질문을 평가한 결과가 아니다.

### GPT·Qwen 전략과의 연결

Qwen은 같은 parameters를 그대로 받는다. OpenAI Responses의 `strict=true`는 모든 property가 required인 스키마를 요구하므로, 선택 필드가 있는 검색 도구는 `SchemaMode.OPTIONAL_FIELDS`로 명시하고 wire에서 `strict=false`를 보낸다. 모든 필드가 필수인 기존 도구는 `STRICT`를 유지한다. 이 구분은 기존 공급자 전략 안에서 처리하며 앱 GPT 모델을 임의로 선택하지 않았다. [OpenAI 공식 function calling 문서](https://developers.openai.com/api/docs/guides/function-calling)의 strict 요구사항과 명시적 non-strict 설정을 확인했다.

모델 측 best-effort 인자를 그대로 실행하는 것은 아니다. 검색 도구는 서버의 공통 계약 검증을 통과해야 실행된다. 토큰 예산 가드·동일성 확인·재시도/공급자 fallback 정책은 해제하거나 변경하지 않았다. GPT·Qwen wire 연결은 MockRestServiceServer로만 검사했으며 실제 공급자 API에 요청하지 않았다.

## 2. 실제 호출을 오프라인 회귀로 재생

이전 [실제 실행 보고서](../../b-live-integration-v1/20261102-01/REPORT.md)와 원본 기록은 수정하지 않았다. 그 기록의 provider 인자를 그대로 사용하고, 검색 서비스·LLM 반환값만 모의 처리했다.

| 기존 case ID | 원본 인자와 새 동작 | 모의 검증 |
| --- | --- | --- |
| `PLR-TM-palaces-01` | `{"region":"서울","query":"창경궁","limit":1}` 승인. 선택 필드 생략은 새 스키마에도 적합 | 검색 1회·LLM mock 2턴, 실제 원문 641자·metadata·귀속 보존, 기존 골든셋의 짧은 원문 구간 인용 승인 |
| `PLR-TM-palaces-03` | `query` 없는 원본을 그대로 거부. camelCase 키도 보정하지 않음 | `Search query required`, `TOOL_FAILED`, 검색 서비스 호출 0, LLM mock 1턴, 자동 보충·재시도 없음 |

모의 최종 설명과 부분 인용은 테스트가 공급한 응답이다. Qwen이 새 지침을 실제로 따랐다고 기록하지 않는다. [첫 문항 모의 메시지](fixtures/PLR-TM-palaces-01.mock-turns.jsonl), [실패 문항 모의 메시지](fixtures/PLR-TM-palaces-03.mock-turns.jsonl)는 모두 `mode=MOCK`이며 과거 LIVE 원본이나 실제 native HTTP body로 표시하지 않는다.

최종 선별 모의 회귀는 **JUnit 91개, 실패 0·오류 0·건너뜀 0**이다. [집계·빌드 바인딩](verification.json)과 [JUnit XML](junit/)을 남겼다. 원문·출처·인용·관계/조건 보존, 기존 계획 도구의 Job 동작, 인용 거부, 예산 가드 회귀를 포함하지만 검색 관련도나 실제 생성 품질의 통과 수는 아니다.

검증 과정에서 기존 `@SpringBootTest PlaceSemanticSearchServiceTest` 1건을 잘못 선택했다. 실제 DB 인증 시도가 실패하면서 application context 초기화에서 종료됐고, 테스트 본문의 embedding·검색 호출에는 도달하지 않았다. 이 테스트는 재실행하지 않았으며 [실패 원인과 단계](excluded-integration-test-attempt.json)를 별도로 남겼다. 최종 91개 모의 테스트 통과와 이 실패를 섞어 “모든 시도 통과”라고 표시하지 않는다. 한 번의 Gradle 명령 옵션 순서 오류도 별도로 기록했다.

기존 B 평가 이벤트 파일은 17개 이벤트·모델 호출 3회의 원본과 바이트까지 동일하다. 기존 Ollama log의 `/api/chat` POST도 과거 B 실행 3건뿐이다. 운영 DB에 변경을 반영하거나 실제 B안 검색을 재실행하지 않았다.

새 모의 메시지·JUnit 파일의 Windows CRLF도 원본 그대로 보존했다. 기본 `git diff --check`는 이 CR을 trailing whitespace로 표시했으며, `git -c core.whitespace=cr-at-eol diff --cached --check`는 통과했다. 줄바꿈을 내용 변경으로 처리하거나 기존 동결 파일·manifest를 정규화하지 않았다. 게시 manifest의 해시는 실제 staged blob과도 일치한다.

## 3. Qwen은 전체 GPU 실행이 아니었음

기존 Windows `Ollama/server.log`의 B 실행 로딩 구간과 성능 구간을 읽었다. 모델을 다시 로드하거나 추론·process sampling을 실행하지 않았다. [로그 발췌](ollama-log-excerpt.json)에 원본 파일 경로·내용 해시·원래 행 번호를 보존했다. 실제 GGUF 해시는 이전 호출의 `a3de86cd…`와 일치한다.

| 기존 로그에서 확인한 항목 | 관측값 |
| --- | --- |
| GPU에 적재한 계층 | **1/37**, output layer만 적재 |
| GPU에 적재한 repeating layer | **0개** |
| CUDA0 model buffer | 486.87MiB |
| CUDA_Host model buffer | 4,490.75MiB |
| CPU KV buffer | 1,152.00MiB, 36 layers, context 8,192 |
| CUDA0 compute buffer | 124.00MiB |
| host compute buffer | 40.02MiB |
| CPU threadpool | n_threads=11 |
| 적재 시 장치 여유 | CUDA available 1.2GiB / free 1.7GiB |

따라서 이전 `/api/ps`의 VRAM 약 0.64GB를 “모델 전체 GPU 실행”으로 볼 수 없다. 로그는 대부분의 가중치·KV가 host/CPU 쪽에 있고 GPU에는 출력 계층만 적재됐음을 직접 보여준다. 메모리 fit 로그도 전체 GPU 예상 사용량 5,907MiB와 당시 free 1,700MiB의 불일치를 기록했다. 어떤 다른 프로세스가 GPU 메모리를 사용했는지는 확인하지 않았으며, 해당 프로세스나 GPU 설정을 변경하지 않았다.

이는 CPU 사용 경로·메모리 배치의 확인이다. 당시 CPU 사용률 %나 계층별 실제 실행 시간의 sampling을 얻은 것은 아니므로 해당 수치를 만들지 않는다.

### CPU 리랭킹과 Qwen 생성 지연은 별도

| 이전 실제 단계 | 시간·작업량 | 근거 |
| --- | --- | --- |
| CPU 리랭킹 | 약 112.268초, 30 pairs | 기존 search span |
| 검색 후 Qwen prompt eval | 약 4.765초, 새 처리 1,765토큰 | Ollama task 37 timing |
| 검색 후 Qwen output eval | **235.151초, 1,012토큰, 약 4.30 tokens/s** | Ollama task 37 timing |
| 검색 후 Qwen native total | 약 239.917초 | 같은 task timing |
| Spring에서 본 같은 Qwen 요청 | 약 239.970초 | 기존 모델 영수증·호출 시간 |
| 같은 호출의 토큰 예산 확인 | 약 0.121초 | 기존 가드 countDurationMs |

2,735 입력 토큰 중 cached 970을 제외한 1,765가 로그의 prompt eval과 맞는다. 이 한 번의 Qwen 후속 호출에서는 native total의 약 98%가 출력 토큰 생성이었다. 토크나이저 준비를 호출마다 반복한 지연으로 해석할 근거는 없다. 검색의 CPU 리랭킹 112초는 이 모델 생성 시간에 포함되지 않은 선행 단계다.

같은 요청의 GIN 요약 줄은 `3m50s`라고 표시되어 native 상세 timing·Spring 시간과 차이가 있다. 이 차이를 숨기거나 서로 다른 측정을 합산하지 않으며, 단계 분석에는 상세 task timing과 기존 호출 관측값을 명시해 사용했다. 전체 GPU 대비 인과 효과나 지연 개선 폭을 검증한 것은 아니다.

## 4. 전체 근거와 사용자 출력 분량 분리

`ConversationService`의 기존 시스템 지침에 다음 출력 규칙을 추가했다.

- 단순 장소명 조회: 찾은 장소와 구별되는 특징을 한두 문장으로 설명. 묻지 않은 연혁을 나열하지 않음.
- 복합 질문: 요구 조건별 핵심과 제한·불확실성을 간결하게 설명. 자세한 설명을 요청하면 확장 가능.
- `citations.quote`: 설명의 주장을 뒷받침하는 최소 연속 원문 구간을 정확히 인용. 원문 전체를 기본 인용으로 사용하지 않음.
- 부정·주체·조건·시점·상충을 보존하는 데 필요한 문맥은 유지. 짧게 만들기 위해 제한을 삭제하지 않음.

검색의 전체 original·metadata·귀속·관계·조건·생성 문맥 구분은 그대로 전달한다. 사용자에게 보이는 설명·인용에만 간결한 작성 지침을 적용했다. description 요약이나 원문을 추가 절단하지 않았으며 quote를 서버가 임의 substring으로 줄이는 처리도 없다.

현재는 **작성 지침과 기존 출처/인용 구조 검증**이다. 서버가 설명의 의미나 “최소 인용”을 새 판정 모델·이동 정규식으로 평가하지 않는다. 기존 응답 형식과 최종 설명/인용 최대치, 출력 예약 1,536을 임의로 낮추지 않았다. 길이 지침을 모델이 실제 준수하는지와 의미·조건 보존은 다음 실제 응답으로 확인해야 한다. 출력량이 줄더라도 CPU 중심 실행·토큰당 처리 시간·리랭킹 시간까지 해결된다고 보장하지 않는다.

## 5. 다음 최소 실행 제안 — 아직 실행하지 않음

[실행 제안 JSON](next-execution-proposal.json)에 기존 첫 두 문항만 기록했다. 새 질문·judge·계획 평가를 추가하지 않았다.

| 항목 | 제안 |
| --- | --- |
| 대상 | `qwen3:8b`, context 8,192 / 출력 예약 1,536 유지 |
| 문항 | 기존 `PLR-TM-palaces-01`, `PLR-TM-palaces-03`, 기존 입력·해시 그대로 |
| 반복 | 각 1회, 순차, 재시도 없음 |
| 호출 상한 | Qwen 실제 dispatch **최대 4회**, 검색 백엔드 **최대 2회**, API 요청 최대 2회 |
| 제외 | 계획·judge·GPT·유료 호출, GPU/context 변경, 원문 절단 |
| 첫 문항 확인점 | 유효 검색 인자·원문 유지·실제 설명/인용 길이·단계별 시간 |
| 두 번째 확인점 | 실제 모델이 query와 올바른 필드명을 만드는지. 누락 시 계속 거부하고 중단 |
| 중단 | 첫 실행 오류·인자 오류·예산/동일성 확인 실패·잘못된 인용·상한 초과·관측 누락 |

이는 실패했던 계약과 단순 조회 출력을 확인하는 최소 재검증 제안이다. 기존 제외 조건 문항 `palaces-04`와 반경 문항 `family_parks-04`는 여전히 미실행이며 이 2문항으로 전체 B안 완료를 선언하지 않는다.

새 JAR SHA-256은 [verification.json](verification.json)에 있고 아직 미배포다. 현재 서버와 과거 배포 manifest는 이전 실행을 보존하고 있다. 기존 `run_b.py`는 4문항 전용이므로 이 2문항 제안을 실행하는 명령으로 제시하지 않는다. 범위 확인 후 새 실행 디렉터리·배포 바인딩·선택 범위가 일치하는 수집 경로를 준비해야 하며, 이번 작업에서 기존 수집기나 실행 환경을 덮어쓰지 않았다.

실제 지연 개선치·다음 정상 응답 시간·CPU 점유율은 미확인이다. 로컬 모델/검색 실행이므로 유료 API 비용은 제안에서도 0이나 전력·장비 비용은 산정하지 않았다. 이전 240초를 새 출력 지침으로 해결했다고 가정하지 않는다.
