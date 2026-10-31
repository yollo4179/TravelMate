# 공통 장소 청크·문맥 생성·검색 DB 명세

문서 버전: 2 · 갱신: 2026-10-31

[계획서](../plans/contextual-retrieval.md) · [구조도](../architecture/contextual-retrieval.md) · [기존 웹 수집](place-review-enrichment.md)

## 공통 계약

`source_type`: `tourapi | blog_post | review | web_excerpt`.
웹 검색 도구가 확보한 snippet은 원래 글이 블로그여도 전체 리뷰 본문으로 가장하지 않고 `web_excerpt`로 보존한다.
사용자가 제공한 실제 블로그/리뷰 본문은 해당 유형과 실제 `capture_scope`로 넣는다.
TourAPI는 현재 Kafka가 전달한 description 필드를 보존하며, 공급자의 원본 전체 JSON을 조회했다고 주장하지 않는다.

```json
{
  "chunk_id": "UUIDv5",
  "source_id": "UUIDv5",
  "source_version": "SHA-256(title + preserved text)",
  "source_type": "review",
  "title": "방문 후기",
  "chunk_text": "평일에는 벤치에서 다리가 보였다. 주말에는 혼잡했다.",
  "context_text": "공원 방문기에서 평일 조망과 주말 혼잡을 비교하는 부분이다.",
  "source_span": {"start": 0, "end": 33, "unit": "unicode_codepoint"},
  "place_refs": [{"place_id": 394, "role": "subject"}, {"place_id": 395, "role": "view_target"}],
  "entities": [{"name": "대상 공원", "place_id": 394, "role": "subject"}],
  "hypothetical_questions": [],
  "generation": {"provider": "perplexity", "model": "실제 응답 model", "response_id": "응답 ID", "prompt_version": "contextual-source-spans-v2"}
}
```

위 JSON은 구조 예시이며 실제 offset은 코드가 보존 원문으로 계산한다. 임베딩 문자열은
`context_text + "\n\n" + chunk_text`. 제목·JSON 문법·질문·URL을 무조건 임베딩 본문에 추가하지 않는다.
UUIDv5는 모든 출처에서 같은 namespace와 source/version/span/splitter 키를 사용한다.
동일 원문 재수집은 ID를 재사용하고, 내용/제목/경계 변경은 새 ID가 된다. 문맥만 바뀌면 chunk_id를 유지하고
context_version을 갱신한다. 이전 문맥도 남긴다. 수집 타임스탬프는 내용 버전에 넣지 않는다.
source_id는 출처 유형·URL 또는 TourAPI 콘텐츠 ID·필드명으로 결정한다. 출처 없는 생성 요약을 원문으로 받지 않는다.

## 생성 파이프라인

프롬프트는 파일명 앞의 버전으로 구분한다. 실행 코드는 프롬프트 레지스트리에서 버전을 선택한다.

| 파일 | 버전·역할 |
|---|---|
| [v1_contextual_prompt.py](../../embedding-server/app/contextual/prompts/v1_contextual_prompt.py) | `contextual-source-spans-v1`: 기존 지시문 그대로 보존 |
| [v2_contextual_prompt.py](../../embedding-server/app/contextual/prompts/v2_contextual_prompt.py) | `contextual-source-spans-v2`: 새 생성의 기본값, 구간 중심 문맥·시설별 귀속·방문 조건 보존 |
| [v3_contextual_prompt.py](../../embedding-server/app/contextual/prompts/v3_contextual_prompt.py) | `contextual-source-spans-v3`: 명시적으로 선택하는 후속 지시문. 단순 언급·조망 대상과 불명확한 귀속을 구분하며 이번 v1·v2 비교에는 사용하지 않음 |

v2는 보통 1~2문장을 권장하지만 필요한 구분·부정·조건을 생략하도록 강제하지 않는다. 600자 상한은 유지한다.
**동일 문서의 청크 밖 배경도 장소 식별·지시 대상·배경 이해에 필요하면 허용한다.**
현재 구간의 주제를 앞뒤 구간의 주차·시설·역사 설명으로 대체하거나 다른 출처의 관찰을 가져오지 않는다.
시설별 상태, 관찰/의견/전언/개선 제안, 게시일/방문일을 구분하며 낡음과 더러움을 동일시하지 않는다.
귀속이 명확한 구간만 subject를 지정한다. 불명확한 구간은 `place_refs=[]`와 `entities=[]`를 **함께** 반환해야 한다.
v2 검증기는 둘 중 entities만 남긴 응답과 비어 있지 않은 `hypothetical_questions`를 거부한다.
예상 질문은 v2에서 생성하지 않으며, 이 형식 검사가 장소 귀속의 의미 정확성을 보증하는 것은 아니다.

기존 실행 기록은 그 기록의 `prompt_version`으로 요청·응답·해시를 재검증한다. 새 기본값이 v2여도 v1 기록과 캐시는 유지된다.
프롬프트나 검증 규칙을 변경할 때 기존 버전 파일을 덮어쓰지 않고 새 버전을 등록한다.
생성 지시문은 `prompt_version`, 응답 처리 규칙은 별도의 `validation_version`으로 구분한다.
이 필드가 없는 기존 기록에는 이전의 엄격한 subject 필수 검증을 그대로 적용한다.

### 역할에 따른 자동 보존·검색 제외

새 응답 및 명시적으로 재검증한 응답은 `contextual-validation-v2`를 사용한다. 사람이 역할을 다시 분류하지 않는다.
원문 구간·스키마·등록된 장소 ID·참조 중복·엔티티 역할 일치·문맥 길이를 먼저 검증한 뒤 다음처럼 분기한다.

| 반환 역할 | 자동 처리 |
|---|---|
| `subject` 있음 | 검색 후보 `chunks`에 저장. 각 장소의 subject 근거로만 활성화 |
| `mentioned`·`view_target`만 있음 | `excluded_chunks`에 원문·문맥·역할·엔티티와 `exclusion_reason=no_subject`를 보존. 검색 후보에서 제외 |
| 귀속 배열이 모두 비어 있음 | 같은 필드에 `exclusion_reason=unattributed`로 보존. 검색 후보에서 제외 |
| 없는 장소 ID·잘못된 원문 위치·역할 불일치 등 | 계속 검증 오류로 처리. subject 없는 구간도 검증을 우회하지 않음 |

subject 없는 정상 구간 때문에 같은 응답의 유효한 구간까지 실패시키지 않는다.
모든 구간이 검색 제외 대상이면 `status=COLLECTED`, `chunks=[]`로 처리 완료한다.
`apply`는 이 경우 `NO_INDEXABLE_CHUNKS`를 반환하고 기존 번들·활성 청크·세대·재색인 작업을 변경하지 않는다.
여러 장소가 있는 응답에서도 해당 장소의 subject 근거가 없으면 그 장소의 번들을 교체하거나 재색인하지 않는다.
검색 제외 자료는 파일 아카이브에 남으며 검색용 DB 청크로 승격하지 않는다.

v1·v2 비교 양쪽에 **같은 응답 처리 버전**을 적용해야 한다. 요청 설정 검증은 그대로 유지한다.
새 처리 버전은 요청 아카이브 해시와 청크 생성 메타데이터에 포함돼 이전 캐시·기록과 구분된다.
비교 보고서의 `validation_versions_match`가 false인 결과는 같은 처리 조건의 비교로 해석하지 않는다.
v1·v2 프롬프트 파일 및 기존 응답 원본을 덮어쓰지 않는다.
v3는 명확한 단순 언급에 mentioned를 허용하고, 귀속 자체가 불명확할 때만 두 배열을 비우도록 지시한다.

로컬 splitter가 보존 문서의 최대 800자 구간을 정한다. Agent에는 전체 원문과 각 구간을 함께 제공한다.
Agent는 원문을 다시 쓰지 않고 구간별 짧은 문맥·장소 역할·엔티티를 생성한다. v1의 기존 선택적 질문은 보존한다.
반환된 모든 source_id와 offset은 요청 목록에 정확히 한 번 있어야 한다.
없는 장소 ID와 엔티티 역할 불일치는 적용을 거부한다. v2에서 대상 장소를 알 수 없는 구간은 두 배열을 비우게 하며,
응답 원본에는 남기고 색인에서는 제외한다. 모델의 역할·문맥 의미 판정은 자동적인 사실 검증이나 사람 검수를 대신하지 않는다.

800자는 현재 분할 설정이며 보편적인 최적 토큰 수를 뜻하지 않는다. 한글 글자 수와 토큰 수는 고정 비율이 아니다.
길이 조정은 실제 임베딩·리랭커 토크나이저로 쿼리/문맥/원문 입력과 잘림을 측정한 뒤 별도 실험한다.

공식 SDK의 `/v1/responses`, `response_format.json_schema`, `preset`/`provider/model` 규격을 사용한다.
기본 `sonar-pro`는 원문 문맥 작성용이며 Sora 같은 영상 모델을 사용하지 않는다.
새 생성 명령은 이미 확보한 텍스트만 사용하므로 tools=[]이고, 웹 수집은 기존 enrichment CLI의 web_search/fetch_url을 사용한다.
기존 record의 동일 URL에 여러 도구 발췌문이 있으면 가장 긴 발췌문을 생성 입력으로 쓰고 나머지는
source metadata의 provider_excerpts에 전부 보존한다. 전체 페이지나 서로 다른 작성 시점의 완전한 원문 버전을 확보했다고 간주하지 않는다.
`--execute` 없이 실제 API 요청을 하지 않는다. 명시적 refresh 외에는 동일 요청 캐시를 재사용한다.
429·인증 오류를 자동 재시도하지 않으며 API 키는 아카이브/로그에 기록하지 않는다.

## 입력과 실행

입력 파일의 `places`는 **기존 검색 DB에서 가져온 필드 전체**와 같아야 한다. 기본정보가 바뀐 뒤에는 다시 수집한다.

```json
{
  "places": [{"place_id": 394, "name": "테스트 공원", "description": "공식 장소 설명"}],
  "sources": [{"source_type": "review", "title": "방문 후기", "text": "평일에는 조용했다. 주말에는 혼잡했다.",
    "metadata": {"source_url": "https://example.org/review/1", "capture_scope": "excerpt", "published_at": null, "visited_at": null}}]
}
```

```bash
cd embedding-server
# 미리보기만: 키가 없어도 원문과 요청을 보존한다.
python -m app.contextual.cli generate --input /path/to/sources.json --output ../LocationReview
# 실제 문맥 생성: API 키는 환경 또는 --env-file로만 공급한다.
python -m app.contextual.cli --env-file ../.env generate --input /path/to/sources.json --output ../LocationReview --execute
# 기존 Agent 수집 record에서 TourAPI 설명과 반환된 원문 조각을 가져올 수도 있다.
python -m app.contextual.cli generate --from-record /path/to/record.json --output ../LocationReview --execute
# 새 명령이 출력한 record 경로를 사용한다. DATABASE_URL은 FastAPI 검색 DB이다.
python -m app.contextual.cli apply --record /path/to/LocationReview/394_테스트공원/requests/HASH/RUN/record.json
```

`--preset` 또는 `--model`로 교체할 수 있다. 둘을 같이 지정하지 않는다.
최초 생성 모델·계정 지원·비용은 실제 계정으로 작은 표본을 실행해 확인한다.
`apply`는 스키마/보존 응답/원문/offset/장소 기본정보를 재검증한다. 여러 장소 적용은 ID 순으로 잠그고 원자 저장한다.
같은 번들 재적용은 `ALREADY_APPLIED`; 새 번들은 `REINDEX_QUEUED`. 후자는 검색 반영 완료를 의미하지 않는다.
기존 장소별 imported bundle은 최신 적용본으로 교체되며 이전 원문/청크/문맥은 삭제하지 않는다.
누적할 자료는 새 입력 번들에 기존 유지 자료도 함께 넣는다. 언급 장소는 그 번들의 청크로 활성화하지 않는다.

## 같은 입력으로 프롬프트 비교

`--prompt-version contextual-source-spans-v1` 또는 `contextual-source-spans-v2`로 지정한다.
기존 **문맥 생성** 실행의 `record.json`을 `--baseline-record`에 주면 보존된 원문·분할·요청 스키마·모델/프리셋을 재사용한다.
웹 수집 record를 가져오는 `--from-record`와 구분한다. baseline 실행은 환경의 모델/프리셋 값을 사용하지 않으며,
`--model`/`--preset`을 함께 지정하면 거부한다. 요청은 instructions를 제외하고 기존 요청과 같아야 한다.

```bash
# embedding-server에서 실행. 유료 호출 없이 v2 요청과 비교 조건을 확인한다.
python -m app.contextual.cli generate --baseline-record /path/to/v1/record.json --prompt-version contextual-source-spans-v2 --output ../LocationReview
# 동일 명령에 --execute를 붙이면 저장 원문으로 새 문맥을 생성한다. 새 웹 검색은 하지 않는다.
```

`record.json` 옆의 `comparisons/<baseline_hash>.json`에 기준 실행, 입력/설정 일치, 실제 응답 모델 일치를 기록한다.
미리보기나 응답 모델이 없는 경우 `actual_model_match`는 null이다. 동일 프리셋이어도 공급자의 실제 모델이 다르면 false이며,
이를 프롬프트만 바꾼 품질 비교로 해석하지 않는다. `semantic_quality_evaluated=false`는 문맥 품질을 자동 채점하지 않았다는 뜻이다.
모델이 같아도 추론의 비결정성은 남는다. 두 실행의 원문 귀속·주제·조건 보존을 대조해야 개선 여부를 판단할 수 있다.
요청 버전별 캐시를 재사용하며, 원본/응답은 덮어쓰지 않는다. 비교 기록 생성은 DB 적용이나 자동 재시도를 수행하지 않는다.
표준 v1 검증은 엄격하게 유지한다. 별도 로컬 배치의 요청은 자동으로 표준 v1로 인정하지 않으며 아래의 명시적 프로필을 사용한다.
외부 `semantic-review.json`의 임의 판정은 아직 자동 반영하지 않는다. 그 파일의 표시만으로 기존 subject 청크가 제외되지는 않는다.

### 로컬 Sonar 실행 9개를 재사용하는 비교

2026-10-30에 보존된 9개 실행은 추가 지시문과 요청 설정이 모두 같다.
[v1_local_2d365e87c12314cb.json](../../embedding-server/app/contextual/profiles/v1_local_2d365e87c12314cb.json)에
당시 **input을 제외한 요청 전체**를 등록했다. 설정 지문은
`2d365e87c12314cb64278e024c8d794438d6f0f65a136ed06794c3c11a34186f`이다.

| 비교 항목 | A: 보존된 로컬 실행 | B: 새 문맥 생성 |
|---|---|---|
| 지시문 | 표준 v1 + 당시 로컬 추가 지시문 | 등록된 v2 지시문 |
| 모델 | `perplexity/sonar` | 동일 |
| effort / 출력 한도 | `fast` / `8192` | 동일 |
| 원문·분할 | 저장된 `input` 문자열 | 공백·이스케이프까지 그대로 복사 |
| 스키마 | 당시 `response_format` | 그대로 복사 |
| 도구 / 비동기 응답 옵션 | `tools=[]` / `background=false` | 동일 |

이는 **로컬 v1 프로필 → v2 비교**다. 표준 v1의 결과라고 표시하지 않는다.
스키마는 빈 `place_refs`·`entities`를 허용하며, 엔티티 이름은 청담도로공원, 최대 1개,
예상 질문은 0개로 제한되어 있다. 따라서 이번 비교에는 스키마 수정이 필요하지 않다.
이 장소에 맞춰진 프로필을 다른 장소의 일반 생성 기본값으로 사용하지 않는다.

```bash
# embedding-server에서 실행. 압축을 푼 원본의 record.json 경로를 지정한다.
# 이 명령은 키 없이도 실행되는 미리보기이며 과금 호출이 없다.
python -m app.contextual.cli generate --baseline-record "/path/to/original/record.json" --baseline-profile v1_local_2d365e87c12314cb --prompt-version contextual-source-spans-v2 --output ../LocationReview
```

원본 실행마다 위 명령을 적용한다. 실제 생성을 원할 때만 `--execute`를 추가하고 환경변수 또는
`python -m app.contextual.cli --env-file ../.env generate ...`로 키를 공급한다.
기존 A 실행 9개는 다시 호출하지 않는다. 이 프로필은 웹 검색을 하지 않고 보존 원문으로 문맥만 생성한다.

검증 순서는 등록 프로필·요청 해시 → 원문/장소/분할과 input 대조 → 저장 스키마와 응답 검증 → 저장 청크 대조다.
기존 `record.prompt_version`·요청 해시·4개 원본 파일을 고쳐 통과시키지 않는다.
프로필을 생략하거나 등록 설정과 다른 로컬 요청은 거부한다. 임의 JSON 파일을 프로필로 받아 검증을 우회하지 않는다.

새 B 기록은 `prompt_version=contextual-source-spans-v2`와 `request_profile_id`를 함께 보존한다.
새 요청 해시와 청크 `generation`에도 프로필을 연결해 표준 v2 기록·캐시와 구분한다.
새 기록은 일반 `load_record`/`apply` 경로에서 같은 프로필로 재검증할 수 있다. 비교 명령 자체는 DB를 변경하지 않는다.
비교 보고서에는 `unchanged_request_fields`, `instructions_changed`, 양쪽 프로필 및 실제 응답 모델을 기록한다.
캐시를 재사용하면 같은 비교 보고서도 재사용하며, 다른 내용으로 덮어쓰지 않는다.

9개 요청·응답, 원문 구간 22개, 장소에 연결된 청크 15개와 manifest의 원본 파일 해시 36개를 확인했다.
지시문만 바뀐 v2 요청 9개를 미리보기로 생성했다. 유료 API 호출·DB 반영·실제 문맥/검색 품질 평가는 하지 않았다.
7개 빈 귀속 구간과 기존 문제 청크의 품질 판정은 이 구조 검증으로 확정되지 않는다.

## DB 변경과 기존 데이터 이행

### 저장 응답의 무과금 일괄 재검증

```bash
# 디렉터리를 지정하면 요청별 최초 보존 응답을 선택해 v1·v2 모두 같은 새 규칙으로 처리한다.
python -X utf8 -m app.contextual.cli revalidate --record /path/to/requests --baseline-profile v1_local_2d365e87c12314cb --paired-only --output ../LocationReview

# 개별 기록도 같은 명령으로 처리할 수 있다.
python -X utf8 -m app.contextual.cli revalidate --record /path/to/record.json --baseline-profile v1_local_2d365e87c12314cb --output ../LocationReview
```

`revalidate`는 API 키·HTTP 클라이언트·DB 연결 없이 실행한다. 이미 처리 버전이 기록된 파생 자료와
응답 본문이 없는 HTTP 실패·미리보기는 일괄 처리에서 제외한다.
`--paired-only`는 기존 비교 보고서로 연결된 요청만 선택한다. 같은 폴더의 다른 과거 실행은 대상에서 제외하고
`out_of_scope_request_hashes`에 남긴다. 이 옵션을 생략하면 원본 응답 전체를 검증하고 유효하지 않은 기록은 실패로 보고한다.
재시도 중 성공한 결과만 고르지 않고 요청별로 가장 먼저 보존된 응답을 사용하며, 선택 기준과 실행 수를 보고서에 남긴다.
기존 입력·요청 해시·등록 프로필·저장 스키마를 검증하고, 새 디렉터리에 원문·요청·응답 파일을 바이트 그대로 복사한다.
원래 `record.json`도 덮어쓰지 않으며 새 기록의 `revalidated_from.file_sha256`에 원본 네 파일의 해시를 보존한다.
파생 기록은 `api_calls=0`이고 원래 과금 usage를 중복 집계하지 않는다.
같은 요청의 새 처리 버전 캐시에 연결하므로 후속 생성 명령도 명시적 refresh 없이는 재검증 결과를 재사용한다.
기존 비교 보고서가 연결된 양쪽 기록을 모두 재검증하면 같은 처리 버전의 비교 보고서도 새로 생성한다.
일괄 결과는 `revalidation-batches/<UUID>/report.json`에 남긴다. 검증 오류는 실패로 기록하고 CLI는 종료 코드 1을 반환한다.
이 명령은 구조·역할 처리 검증이며 생성 의미 품질이나 검색 성능 평가가 아니다.

### DB 적용

실제 SQL은 [03-contextual-chunks.sql](../../Docker/search-init/03-contextual-chunks.sql)이다.
runtime `ensure_schema`도 같은 SQL을 멱등 적용한다. FastAPI 전용 DB에만 실행한다.

| 테이블/필드 | 목적 |
|---|---|
| retrieval_source_versions | source_id + source_version PK, 보존 문서·출처·날짜·capture_scope |
| retrieval_chunks | 전역 chunk_id PK, 원문 offset·원문 청크·source FK |
| retrieval_chunk_contexts | chunk_id + context_version PK, 문맥·장소 역할·질문·생성 모델·BGE-M3 벡터 |
| retrieval_chunk_bundles | 기존 장소별 불변 입력 manifest, 기본정보 지문·적용 순서 |
| place_active_chunks | 장소별 1..20 slot, chunk/context FK, subject 역할 강제 trigger |
| place_embeddings.chunk_generation | 추론 중 새 번들 적용을 감지하는 optimistic version |

활성 slot PK와 범위 CHECK가 동시 쓰기에도 20개를 보장한다. 같은 청크의 한 장소 내 중복 활성화는 UNIQUE로 막는다.
모든 원문을 저장한 다음 출처 round-robin·동일 텍스트 중복 제거로 활성 집합을 고른다.
초과 자료는 DB/파일에 남는다. 임베딩은 활성 청크에만 계산하고, 조건을 지우거나 20개를 억지로 만들지 않는다.
문맥/원문/번들은 보존하며 이전 활성 링크만 원자 교체한다.

배포 시 DB 백업 → 새 코드/스키마 → 작은 장소 집합 재색인 → 전체 배치 순으로 적용한다.
기존 READY 행은 청크가 생기기 전 기존 벡터를 사용한다. 다음 SQL은 **검색 DB에서**
기존 장소 재색인 작업을 등록하는 운영 예시다. 먼저 WHERE에 place_id 범위를 넣어 표본으로 실행한다.

```sql
INSERT INTO place_index_jobs(job_id,event_id,place_id,source_version,payload)
SELECT gen_random_uuid(), event_id, place_id, source_version,
       jsonb_build_object('event_id',event_id,'event_type','PLACE_UPSERTED',
           'place_id',place_id,'source_version',source_version,'source',source)
FROM (
  SELECT p.place_id,p.source_version,gen_random_uuid() AS event_id,
    jsonb_build_object('place_id',p.place_id,'name',p.name,'description',p.description,
      'region',p.region,'city',p.city,'category',p.category,'source_category',p.source_category,
      'latitude',p.latitude,'longitude',p.longitude,'tour_content_id',p.tour_content_id,
      'image_url',p.image_url,'homepage_url',p.homepage_url) AS source
  FROM place_embeddings p
  WHERE p.document_status='READY' AND p.source_version=p.latest_seen_version
    AND NOT EXISTS (SELECT 1 FROM place_index_jobs j WHERE j.place_id=p.place_id AND j.status IN ('PENDING','RUNNING'))
) pending;
```

원본 버전/보강 스냅샷/청크 세대가 추론 중 바뀌면 작업은 SUPERSEDED이고 활성 링크를 건드리지 않는다.
삭제된 장소·아직 원본 인덱싱이 끝나지 않은 장소는 검색에서 제외한다. 이전 원문은 감사용으로 보존한다.

## 조회·리랭킹·추적

각 장소의 subject 활성 청크 중 쿼리와 가장 가까운 원문 근거 하나를 선택한다.
장소 점수는 그 청크의 cosine score이며 청크 수나 리뷰 수로 합산하지 않는다. 기존 장소 Top-K와 반환 limit은 유지한다.
리랭커에는 선택된 짧은 문맥+원문을 전달한다. BGE-M3 및 기존 BGE reranker의 모델·실행 전략·정밀도는 변경하지 않는다.
Kafka 결과 각 장소의 `evidence_chunks`에 chunk_id·원문·문맥·source_span·버전·역할·생성 모델·출처 metadata가 추가된다.
원시 벡터는 반환하지 않는다. Spring은 원본 완료 JSON을 보존하며, 앱용 DTO에 출처 카드가 추가된 것은 아니다.
BM25 결합과 가상 질문 벡터 색인은 이번 변경에 포함하지 않는다.

```text
LocationReview/<place_id>_<안전한 장소명>/
  requests/<request_hash>/<run_uuid>/
    sources.json / request.json / raw_response.json / record.json
  references/<hash>-<run>.json      # 다중 장소 원문 공유 시 다른 장소의 추적 포인터
  index-inputs/<manifest_hash>.json # TourAPI·기존 보강을 포함한 모든 후보 청크와 원문
```

기존 웹 수집 record도 `/enrichment-data/LocationReview/<place_id>_<장소명>/requests/` 아래에 보존한다.
Docker 작업자의 LOCATION_REVIEW_DIR는 `/enrichment-data/LocationReview`, 로컬 기본은 `LocationReview`이다.
위치 이름에서 경로 구분자를 제거하며 실제 원문 아카이브는 Git에 자동 커밋하지 않는다.
읽을 수 없는 원문/변조된 응답/보존 실패는 조용히 무시하지 않고 실패한다.

## 검증 실행

```bash
python -m unittest discover -s embedding-server/tests -v
python -m unittest discover -s Docker/tests -v
```

DB 테스트는 `ENRICHMENT_TEST_DATABASE_URL`에 별도 테스트 PostgreSQL DSN을 지정해야 한다.
각 테스트는 고유 스키마만 만들고 제거한다. 운영 DB를 지정하지 않는다.
`CONTEXTUAL_MODEL_TEST_URL`에 실행 중인 기존 임베딩 서버의 base URL을 지정하면
실제 BGE-M3 임베딩 → 청크 조회 → 기존 reranker 의미 순서도 검증한다.
두 변수가 없을 때 해당 통합 테스트는 skip이며 통과로 간주하지 않는다.
구현 검증에서는 별도 테스트 DB와 기존 모델 서버로 검색 테스트 31개, Docker 테스트 11개가 통과했다.
실제 Perplexity 인증·모델 가용성·과금·생성 문맥 품질은 API 키 부재로 검증하지 않았다.

2026-10-30 프롬프트 버전 변경 검증에서는 contextual 테스트 13개가 통과했고 DB/실제 모델 테스트 5개는 환경 미설정으로 skip했다.
v1 아카이브 재검증, 버전별 캐시, 귀속 불명확 응답 보존, 비교 요청 고정과 실제 모델 불일치를 모의 HTTP로 확인했다.
유료 API 재실행·실제 문맥 개선 평가·DB 적용은 수행하지 않았다.

같은 날 로컬 프로필 호환을 추가한 뒤에는 `test_contextual*.py` 21개가 통과했고 통합 테스트 5개는 skip했다.
추가 8개는 명시적 프로필 선택, 설정/해시 변조 거부, 원문 문자열 보존, 저장 스키마 강제,
빈 귀속 보존, 실제 모델 불일치 표시, 캐시/비교 기록 재사용, 키 없는 CLI 미리보기를 확인한다.
실제 첨부 기록 9개에 대해서도 CLI 미리보기를 수행하고 실행 전후 36개 원본 파일 해시가 같은지 확인했다.

2026-10-31 역할 자동 분기 변경은 임베딩 서버 전체 테스트 41개가 통과했고 환경 미설정 통합 테스트 11개는 skip했다.
문맥 생성 관련으로는 29개 통과·5개 skip이며, subject 없는 구간의 선행 검증·제외 사유·원본 보존,
색인 후보 0개일 때 DB 미접근, 여러 장소 중 subject 장소만 재색인, 무과금 일괄 처리·캐시 재사용을 확인했다.
실제 DB/모델 통합 환경에서 이 변경을 재검증한 것은 아니다.

기존 비교 보고서로 연결된 v1 9건·v2 9건을 같은 `contextual-validation-v2`로 재검증했다.
양쪽 원문 구간은 각각 22개이며 v1은 검색 후보 15개·제외 7개, v2는 검색 후보 17개·제외 5개다.
기존 v2 실패 3건도 단순 언급 구간만 제외하고 유효 구간을 처리했다.
원본 72개 파일과 복사본 54개의 해시 일치, 비교 9쌍의 입력·설정·실제 모델·검증 버전 일치를 확인했다.
같은 폴더의 비교 대상 외 과거 요청 2개는 별도 목록에 남기고 대상에서 제외했다.
API 재호출은 0회이며 DB 적용·재색인·검색 성능 평가는 수행하지 않았다.
검색 후보 개수 차이는 장소 귀속의 의미 정확도나 검색 품질 개선을 입증하는 지표가 아니다.
후속 프롬프트 v3는 등록만 했으며 실제 생성 품질은 평가하지 않았다.
