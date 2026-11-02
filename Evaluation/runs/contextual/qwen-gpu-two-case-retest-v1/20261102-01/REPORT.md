# Qwen GPU 자동 분할·수정 계약 재시험 — 첫 문항 인자 오류로 중단

2026-11-02 14:26 KST. 지정한 기존 2문항 중 **첫 문항에서 허용되지 않은 `searchContext` 도구 인자를 생성해 중단**했다. Qwen 실제 호출 **1회**, 실제 검색 **0회**, 재시도 **0회**다. 두 번째 문항은 실행하지 않았다. GPU 적재와 짧은 도구 출력의 속도는 관측했지만 근거를 받은 최종 설명·인용의 품질과 길이는 확인하지 못했다.

애플리케이션 JAR는 `c3cdba7b186179ef5ac24c35d3f16dac5486ea30`의 계약·출력 지침 수정 버전이다. GPU 여유 확보와 계약/출력 프롬프트 변경이 함께 적용된 진단이며 어느 하나의 독립적인 개선 효과로 표시하지 않는다.

## 실행 환경과 범위

| 항목 | 실제 설정·확인 |
| --- | --- |
| Spring | Windows 평가 프로세스 PID **10480**, `127.0.0.1:18080` |
| 새 JAR SHA-256 | `59093ddf4c46458a22aad0570be50c33106f6c41d9add97e893f122942ffd2f7` |
| 새 runtime | `Server/TravelMate/build/b-evaluation-gpu-retest` |
| Qwen | `qwen3:8b`, Q4_K_M, Ollama 0.40.13, think=false |
| 입력/출력 예산 | context **8,192**, 출력 예약 **1,536**, 정확 계산 가드 유지 |
| GPU | RTX 4050 Laptop 6GB, 자동 fit. 전체 적재 강제·context 증가는 없음 |
| 시작 전 GPU | used 0MiB / free **5,924MiB**, Qwen 미적재 `models=[]` |
| 임베딩·리랭커 | 기존 평가 FastAPI **CPU**, GPU 경쟁 없음. 검색 설정·모델·정밀도·batch 변경 없음 |
| 데이터 | 평가 DB의 장소 449개·원문·기존 벡터가 snapshot과 동일, 대기 작업 0 |
| 도구·루프 | SEARCH_PLACES만, 요청당 모델 2회·도구 1회, 실패 시 STOP |
| 승인 배치 | 기존 palaces-01·palaces-03, 각 1회·순차·Qwen 최대 4회·검색 최대 2회·재시도 없음 |

Gemma 종료는 [앞선 GPU 점검 기록](../../gpu-runtime-inspection-v1/20261102-01/REPORT.md)에 별도로 남겼다. 이번에는 사용자가 지시한 평가 Spring 교체만 수행했다. 원래 평가 PID 16528과 그 관리 하위 프로세스를 경로 확인 후 종료하고 새 JAR을 별도 runtime에서 시작했다. 이전 JAR·properties·관측 파일과 기존 운영 환경은 덮어쓰지 않았다.

새 JAR·소스 253개 파일의 바인딩은 [deployment.json](deployment.json), 실제 실행 PID/명령·선별 설정은 [running-spring-verification.json](raw/running-spring-verification.json), corpus/대기 작업 확인은 [database-verification-before.json](raw/database-verification-before.json)에 있다. 사용자 자격증명·DB 암호·JWT는 게시하지 않는다.

기존 수집기에 `gpu-two`라는 고정 프로필을 추가했다. 원래 4문항 프로필은 유지했고 두 문항의 기존 입력 해시를 다시 대조했다. 실패한 모델 dispatch도 실제 호출 수로 집계하고, 도구 시도 수와 실제 검색 수를 구분한다. 이전 완료 DB 행을 대기 작업으로 잘못 세지 않도록 unpublished outbox와 PENDING/RUNNING 작업만 검사한다. 과거 행은 삭제하지 않았다.

수집·준비 모의 회귀 **15개 통과** 후 실제 실행했다. 애플리케이션의 이전 91개 모의 통과 기록은 새 모델의 품질 통과로 사용하지 않았다.

실제로 한 번 실행한 명령:

```powershell
C:/ssafy/Travelmate/.venv-ragas/Scripts/python.exe -X utf8 Server/TravelMate/build/gpu-diagnostic-run-once.py --execute
```

이 감독 스크립트는 실행/출력 디렉터리가 이미 있으면 재실행을 거부한다. 기존 [collector 소스 snapshot](raw/executed-collector.py.txt)과 [실행 감독 스크립트 snapshot](raw/executed-supervisor.py.txt)을 보존했다. 감독 스크립트는 고정 `gpu-two` 실행과 함께 GPU·`/api/ps` 메타데이터만 수집한다. 메타데이터 GET을 모델 추론이나 검색으로 세지 않는다. 이 명령을 다시 실행하지 않았다.

## 도구 인자 실패와 중단

`PLR-TM-palaces-01`: **“창경궁을 찾아줘.”**

실제 Qwen 도구 선택은 `search_places`로 적합했고 query와 region도 맞았다. 그러나 다음처럼 API request 문맥인 `searchContext`를 도구 인자 안에 추가했다.

```json
{
  "query": "창경궁",
  "region": "서울",
  "searchContext": {
    "area": null,
    "category": null,
    "city": null,
    "excludePlaceIds": [],
    "region": "서울"
  }
}
```

도구 스키마는 `query`만 필수이고 나머지 정의된 필드는 선택이다. `searchContext`는 정의된 도구 필드가 아니며 `additionalProperties=false`이므로 서버가 **`Unknown tool argument: $.searchContext`**로 거부했다. Python의 독립 JSON Schema 검사도 같은 추가 필드 위반을 확인했다. 옵션 필드 생략 문제와 새 추가 필드 위반은 구분한다.

서버는 미지의 필드를 제거하거나 query를 다시 생성해 실행하지 않았다. **HTTP 200이지만 `type=ERROR`, `termination=TOOL_FAILED`, `messageSource=SERVER_FALLBACK`**다. 공급자 응답 수신 성공 `MODEL_CALL SUCCEEDED`는 도구 실행/질문 처리 성공을 뜻하지 않는다.

| 기존 case ID | 상태 | 실제 Qwen | 실제 검색 |
| --- | --- | ---: | ---: |
| `PLR-TM-palaces-01` | TOOL_FAILED — 추가 필드 거부 | 1 | 0 |
| `PLR-TM-palaces-03` | NOT_RUN_STOP_POLICY | 0 | 0 |

도구 시도는 1건이지만 검색 전 validation 실패라 검색 백엔드 요청은 0건이다. [평가 DB 감사](raw/database-audit.json)에는 과거 13:11 실행의 요청 `90132657-52cf-4b07-8b10-2e46baf11482` 1행만 있고 새 요청은 없다. 계획 Job도 0개다.

원본 [요청](raw/PLR-TM-palaces-01.request.json)·[응답](raw/PLR-TM-palaces-01.response.json)·[provider/app 도구 호출 이벤트](raw/events.jsonl)를 보존했다. 기존 변환기를 오프라인으로 적용한 [평가 기록](raw/records-all-observed.jsonl)은 `LIVE`, `recorded_not_scored`, 모든 observation coverage=false다. 실패나 미실행 항목을 성공으로 투영하지 않았다.

## GPU 실제 적재와 메모리

시작 전 로그 byte offset 이후의 [Ollama 원본 로그](raw/ollama-delta.log)를 수집했다. 모델 identity·템플릿·토크나이저는 기존 핀과 같았다.

| 항목 | 이번 실제 관측 |
| --- | ---: |
| GPU 적재 | **24/37 layers**: output layer + repeating 23개 |
| GPU 밖에 남은 repeating layers | 13개 |
| CUDA0 model buffer | 3,136.49MiB |
| CUDA_Host model buffer | 1,841.14MiB |
| CUDA0 KV buffer | 736.00MiB |
| CPU KV buffer | 416.00MiB |
| CUDA0 compute buffer | 124.00MiB |
| host compute buffer | 40.02MiB |
| CPU threadpool | 11 threads |
| 응답 직후 `/api/ps size_vram` | 4,190,623,498 bytes |
| 응답 직후 nvidia-smi | used 4,127MiB / free 1,798MiB |

이전 GPU 압박 상황의 **1/37 → 24/37**로 적재 계층은 늘었지만 **전체 GPU 실행은 아니다.** 두 메모리 관측 도구는 집계 범위가 다르므로 값을 맞춰 수정하지 않았다. [시작 전](raw/before.json)·[응답 후](raw/after.json)·[주기 메타데이터](raw/samples.jsonl)는 시점 관측이며 sampling 간격 사이의 실제 peak를 보장하지 않는다.

## 처리 시간·토큰·출력 길이

| 단계·사용량 | 실제 관측 |
| --- | ---: |
| 정확 입력 계산 / 실제 prompt_eval_count | **1,385 / 1,385 tokens** |
| 입력 + 출력 예약 / context | 2,921 / 8,192 |
| 원문 포함 후속 호출 | **없음** — 검색 전 실패 |
| 공급자 출력 | **62 tokens**, 도구 호출 인자 출력 |
| native prompt eval | 1,435.79ms / 1,385 tokens / **964.63 tokens/s** |
| native output eval | 3,927.81ms / 62 tokens / **15.53 tokens/s** |
| native total | 5,363.60ms |
| cold native server start | 로그상 약 3.52초 |
| Spring에서 측정한 모델 요청 | **9,923.841ms** |
| 가드의 토큰 확인 | 36.4325ms |
| 도구 validation | 3.4573ms |
| CPU 임베딩·후보 검색·리랭킹 | **미실행 / 시간 미관측** |
| API 전체 | **10,401.8681ms** |

토큰당 처리량은 native 로그가 보고한 값을 그대로 사용했다. cold load와 native 처리 시간·네트워크/서버 관측 구간은 서로 다른 측정이므로 단순 합이나 차이로 새로운 단계 시간을 만들지 않는다. 상주 계산기는 새 Spring 시작 때 초기화 1회, 약 5.73초였고 이 초기화는 API 요청 전이다. 요청마다 재로딩한 것이 아니다.

raw 도구 인자 JSON은 **122 codepoint**다. LLM이 최종 설명을 작성한 호출은 없으며 서버 실패 안내가 42 codepoint다. citations는 비어 있다. 이를 “설명 567자 → 42자”, “인용 632자 → 0자”의 간결화 성공으로 세지 않는다. 최종 설명·인용 길이와 의미 품질은 **미평가**다.

## 해석과 남은 한계

- 실제로 확인한 것은 GPU 적재 확대와 짧은 tool-call 출력의 15.53 tokens/s, 그리고 새 인자 오류다. **실사용 도구 호출 신뢰성 문제는 남아 있다.** 모델 선택 자체·query는 맞았지만 허용 스키마를 지키지 못했다.
- 이전 240초는 원문을 받은 뒤의 1,012토큰 설명·인용 생성이었다. 이번에는 그 단계에 도달하지 않았다. 따라서 “240초 → 10초로 답변 개선”이라고 표시하지 않는다.
- 이전 초기 tool-call은 입력 974·출력 35토큰이고, 이번은 입력 1,385·출력 62토큰이다. GPU 배치뿐 아니라 계약 설명·출력 지침·생성 인자 내용도 다르다. 단일 원인의 배속이나 통제된 GPU benchmark로 판정하지 않는다.
- CPU 검색은 설정을 유지했지만 이번에 호출하지 않았다. 이전 CPU 리랭킹 약 112초가 해소됐다는 관측은 없다. 검색 관련도·선택 근거·원문 전달·근거 기반 설명도 이번 실행에서는 미관측이다.
- 재시도·자동 인자 보정·다른 질문·두 번째 문항·계획·judge·유료 호출을 실행하지 않았다. 실패 후 애플리케이션 코드를 고쳐 성공시키는 추가 실행도 하지 않았다.
- API 공급자 전략은 유지했다. 앱 GPT 모델을 임의 선택하거나 API 비용·품질 비교를 수행하지 않았다. 이번 기록만으로 Qwen의 실제 여행 설명 속도나 API 대비 품질 결론을 낼 수 없다.

구조화 판정과 단계 값은 [assessment.json](assessment.json)에 있다. 기존 두 문항의 재시험은 첫 오류 중단 규칙에 따라 부분 결과로 종료했으며, 전체 2문항 또는 전체 B안 4문항의 완료로 표시하지 않는다.
