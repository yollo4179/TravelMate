# 동결 TourAPI 설명을 원문 근거로 연결

2026-11-02 KST · 기준 `b80aa78bb32633ddb7189d68aaf76981c4eb0bdc`. **데이터 연결을 구현하고 평가 환경에서 준비·모의 검증까지 마쳤다. 실제 B안·검색·모델 호출은 하지 않았다.** 기존 source DB·동결 데이터·이전 보고서는 보존했다.

## 해결 방식

기존 장소 벡터로 후보를 찾은 뒤, 기존 활성 근거가 없는 후보에 동결 `places.description`을 원문으로 붙인다. 새 문서를 벡터 검색하는 경로가 아니다. 기존 벡터와 원문 필드가 같은 임베딩 입력이라는 주장을 하지 않으며 **새 임베딩 대상 0개·계산 0회**다. 원문은 `NOT_EMBEDDED`, 유사도 점수 범위는 `place_candidate`로 전달한다. 후보 검색 순위·Top-30·활성 20개·API 최대 20·거리 조건은 유지한다.

| 장소 | 장소 ID | TourAPI content ID | 보존 원문 길이 | UTF-8 내용 SHA256 |
|---|---:|---|---:|---|
| 올림픽공원피크닉장 | 311 | 2761797 | 300자 | `9f46743363c9fc0da00c22738781193fcae6f5674bd6cfb6444a17c5f9d1420d` |
| 창경궁 | 378 | 126511 | 641자 | `12706ec5165ca2f48e2846d995b745959c1546a73a1511507ad2fe81adb97a72` |

v1.4.0의 `source/snapshot.json`·`generated/corpus.json` 두 파일의 설명과 content ID가 일치하며 `tour_api_raw`에 같은 ID가 있음을 확인했다. snapshot 버전·snapshot/corpus/manifest 파일 SHA256·장소 ID·content ID·장소 지문·원문 내용 해시를 함께 보존했다. `source_version`은 제목/원문 버전이며 `content_sha256`은 원문 문자열의 UTF-8 해시로 구분한다.

원문은 **동결 DB 설명 필드 전체**다. TourAPI 원본 HTTP 응답의 overview와 가공된 DB description이 같은 문자열이라고 주장하지 않는다. 이 설명의 출처 유형은 `tourapi`이며 방문자 리뷰가 아니다. 출처 URL·수집/게시 시각을 만들지 않았다. 생성 문맥·질문·관계·분류 태그도 추가하지 않았다. 제목은 실제 장소명, 주체는 해당 장소 ID다.

## 연결 경로와 범위

1. `place_original_field_evidence`에 두 원문 필드를 등록한다. 이 테이블에는 embedding 컬럼이 없다. 기존 active chunk 8개와 장소 벡터 449개는 변경하지 않았다.
2. 후보/추가 근거 조회 후 별도 attachment 단계가 원문을 읽는다. 현재 장소의 source_version/latest_seen_version·원문·content ID·지문이 달라지면 오래된 원문을 붙이지 않는다. 문서 해시·주체·종류가 변조되면 실패한다.
3. 기존 리뷰/관계 근거가 있으면 교체하거나 근거 수를 늘리지 않는다. 명시적인 observation 필터에는 종류를 분류하지 않은 원문을 적합하다고 추정해 붙이지 않는다.
4. 리랭킹 pair는 원문 그대로를 사용한다. generated context를 덧붙이지 않는다. 실제 리랭커는 이번에 호출하지 않았다.
5. Kafka 결과의 evidence_chunks → Spring 파서/결과/응답 DTO → search_places 결과 → 기존 단일 LLM의 누적 도구 결과 메시지로 원문·metadata·귀속을 전달한다. 생성 보충 문맥 객체는 비어 있다.

기본 모드는 `disabled`다. 평가 Compose만 `PRESERVED_ORIGINAL_EVIDENCE=post-retrieval-field-v1`을 사용한다. 기존 결과 직렬화 코드를 모델 로드와 무관한 공통 함수로 분리했고 실제 워커와 모의 검증 모두 그 함수를 사용한다. 이동 전용 정규식·별도 판정 LLM·새 리뷰 수집은 추가하지 않았다.

## 모의 검증과 실제 환경 확인

평가 DB에서 원문 결합 SQL은 실제로 실행했지만, 입력 후보와 점수는 모의 값이다. 기존 B안의 query embedding·후보 검색·리랭킹·대화 API를 실행한 것이 아니다. [모의 Kafka 결과](mock-kafka-result.json)의 0.5 점수와 순위 1/2는 transport fixture이며 검색 품질 점수가 아니다.

그 결과를 Spring 테스트 리소스로 받아 실제 Kafka 소비 파서에 전달하고, 검색 응답 DTO와 실제 검색 도구 처리기를 거쳐 **모의 LLM의 두 번째 호출 입력**을 확인했다. [모의 LLM 입력](mock-llm-input.json)은 mode=MOCK다. 창경궁의 description 요약은 400자 이내여도 selectedEvidence.original에는 641자가 온전히 남았다. 원문 해시·snapshot·place/content ID가 유지되고, 다른 장소의 인용으로 허용되지 않는지 검사했다. 설명 의미를 모델이 올바르게 이해했다는 판정은 아니다.

- Java **43개 통과**, 실패/오류/건너뜀 0: 새 원문 전체 파이프라인 1, 기존 근거 7, 대화 도구 24, 토큰 예산 11.
- Python **50개 통과·11개 건너뜀**, 실패/오류 0: 원문 5, 일반 검색 계약 7, 기존 contextual 13(+DB 5 skip), enrichment 12(+DB 6 skip), 환경 준비/모의 수집 13. 건너뛴 실제 DB/모델 검사를 통과로 세지 않았다.
- 별도로 평가 DB의 실제 원문 결합/선택과 공통 Kafka 직렬화 2건을 모의 점수로 확인했다. 새 평가 문항을 만들거나 기존 네 문항을 실행하지 않았다.
- Windows 오프라인 JAR 빌드 후 평가 Spring만 새 JAR로 재시작했다. 기존 snapshot/JAR는 보존했고 별도 deployment.json에 새 JAR·소스 해시를 기록했다. 상주 계산기 READY와 FastAPI health의 적용 모드를 확인했다.
- 기존 source DB 두 개와 평가 DB의 **449건 장소/벡터 해시 불변**, active chunk 8개 불변, 신규 원문 필드 2개, 대기 작업/outbox 0개다. [검증 기록](verification.json).

[원문·provenance](evidence.json) · [임베딩 대응/모의 점수 구분](inventory.json) · [테스트 집계](tests.json) · 같은 디렉터리의 JUnit XML.

## 실행과 남은 한계

준비 재현·실행 위치·포트·실제 B안 명령은 [환경 안내](../../../../environments/b-plan/README.md)에 있다. 현재 데이터 누락에 따른 준비 차단은 해소됐으며 아래 **비실행 검사**의 blocker 목록은 비어 있다.

```powershell
C:/ssafy/Travelmate/.venv-ragas/Scripts/python.exe -X utf8 Evaluation/environments/b-plan/run_b.py --runtime Server/TravelMate/build/b-evaluation
```

이번에는 `--execute`를 실행하지 않았다. **실제 B안·LLM 추론·검색·질문 임베딩·문서 임베딩·리랭킹 계산·웹 수집·유료 호출은 모두 0회**다. 향후 실행 범위도 기존 네 문항 각 1회·Qwen 최대 8회·검색 최대 4회·재시도 0·계획 Job/judge 0회를 유지한다.

이 연결은 Top-30 밖의 장소를 새로 찾아오지 않는다. 등록 대상은 두 장소뿐이며 다른 장소의 근거가 모두 준비됐다는 뜻이 아니다. 실제 검색 결과에서 무엇이 선택되는지, 추가된 전체 원문의 실제 입력 예산, LLM의 부정·과거·조건 해석과 답변 품질은 다음 실제 실행에서 관측해야 한다. 서버의 호출별 전체 입력/출력 예약 가드는 유지했다.

CPU cross_encoder_predict는 기존 GPU autocast_fp16과 다르다. 이번 통과는 기능/데이터 연결 검증이며 기존 순위·점수·지연과의 비교 결과가 아니다. `ranking_scores_comparable=false`를 유지한다. 계획·수정·확정·롤백·이동시간·동선 최적화의 검증 범위도 늘리지 않았다.
