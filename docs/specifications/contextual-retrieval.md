# 공통 장소 청크·문맥 생성·검색 DB 명세

문서 버전: 12 · 갱신: 2026-11-01

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
| [v4_contextual_prompt.py](../../embedding-server/app/contextual/prompts/v4_contextual_prompt.py) | `contextual-source-spans-v4`: 구간 주제 우선·인접 관찰 차용 금지·장소/시설 귀속을 강화한 실험 지시문. 기본값은 계속 v2 |
| [v5_contextual_prompt.py](../../embedding-server/app/contextual/prompts/v5_contextual_prompt.py) | `contextual-source-spans-v5`: 코드가 추출한 `span.chunk_text`를 직접 읽는 선택 지시문. 명시적 청크 입력 필수. 22구간 검수에서 주제 대체 감소와 귀속 회귀가 함께 확인돼 기본값으로 채택하지 않음 |
| [v6_contextual_prompt.py](../../embedding-server/app/contextual/prompts/v6_contextual_prompt.py) | `contextual-observation-relations-v6`: 관찰 종류와 장소 역할을 분리하고 출발지·도착지·이동 조건을 보존하는 선택 계약. 새 문장/문단 분할·명시적 입력·출력 스키마가 필요하며 기본값은 계속 v2 |
| [v7_contextual_prompt.py](../../embedding-server/app/contextual/prompts/v7_contextual_prompt.py) | `contextual-independent-relations-v7`: 관찰 종류·subject와 독립적인 primary/supporting 관계 및 정확한 이동 근거를 보존하는 선택 계약. 실제 2건 검수에서 위치·귀속 오류가 남음, 기본값은 계속 v2 |

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

v4 비교는 기존 v2 요청을 복사해 지시문만 바꾸고, 근거 수를 2개로 고정한 별도 실험 B다.
원문·분할·모델 선택·effort·8192 출력 한도·스키마·도구·검증 규칙은 동일하다.
v4의 mentioned·view_target·빈 귀속 처리도 기존 검증 버전 v2를 그대로 사용한다.
[생성·검수·검색 실측 기록](../../Evaluation/runs/contextual/prompt-grounding-v1/20261031-01/REPORT.md)에서
관측한 문맥 오류 감소와 검색 지표 불변을 구분한다. 프롬프트나 검색 기본값을 이 결과로 바꾸지 않는다.

`GenerationBaseline.write_report(..., output_directory=...)`로 비교 보고서 저장 위치를 별도 지정할 수 있다.
지정하지 않으면 기존 응답 폴더 아래 `comparisons/`를 사용한다. 요청·원본·해시·검증 내용은 바뀌지 않는다.
Windows에서 원본 아카이브 아래의 깊은 경로가 파일 길이 제한을 넘으면 짧은 별도 위치를 사용한다.

### 명시적 청크 입력과 후속 분할 준비

입력 계약은 프롬프트·응답 스키마·검증 버전과 따로 구분한다.

| `input_version` | 전달 형태 | 기본 여부 |
|---|---|---|
| `source-offsets-v1` | 문서 전체와 `source_id/start/end` | 기존 기본값, 과거 기록의 필드 생략도 이 버전 |
| `source-explicit-chunks-v2` | 위 정보와 코드가 계산한 각 `span.chunk_text` | 명시적으로 선택 |

청크 문자열은 보존 원문의 `source.text[start:end]`이며 정규화·공백 제거·모델 재작성 없이 전달한다.
오프셋은 계속 Unicode 코드포인트 기준이며 emoji·CRLF·결합 문자도 그대로 유지한다.
응답에 청크 원문을 다시 쓰게 하지 않고, 기존 응답 스키마·역할 검증·분할·청크 ID 계약을 유지한다.
새 입력의 기록·캐시·무료 재검증에는 `input_version`을 보존한다. 기존 기록의 요청·해시는 바꾸지 않는다.

비교는 다음처럼 나눈다. 한 번에 v4 위치 기반 입력→v5 명시적 입력으로 바꾸면 입력과 지시문이 함께 바뀐 비교다.

1. **입력 형식만 비교:** 저장 v4 위치 입력→v4 명시적 입력. 지시문·모델·effort·한도·스키마·원문·분할을 고정한다.
   `InputFormatComparison`은 청크 원문 추가만 허용하고 `comparison_kind=input-format-only`로 기록한다.
   v4의 위치를 찾아 읽는 지시 자체는 이 단계에 남으므로, 명시적 원문을 우선 읽는 v5의 효과까지 검증한 것은 아니다.
2. **명시적 입력에서 지시문만 비교:** 보존된 v4 명시적 입력 응답이 생긴 뒤 같은 입력을 v5에 사용한다.
   기존 `GenerationBaseline`의 지시문 외 필드 동일 검증을 그대로 적용한다. v5에는 명시적 입력을 필수로 요구한다.
3. **분할 비교:** 입력·선택 지시문을 고정한 별도 실험 C로 진행한다. 이전 청크의 문맥·장소 역할을 새 구간에 복사하지 않는다.

입력 형식 비교의 대조군은 현재 응답 검증 버전이어야 한다. 과거 검증 버전 기록은 먼저 무료 재검증하고 비교한다.
`--baseline-record`에 `--input-version source-explicit-chunks-v2`를 주면 입력 비교로 분리한다.
`--comparison-output`으로 두 비교 방식 모두 짧은 보고서 폴더를 지정할 수 있다.
실행 명령과 유료 호출 여부는 [평가 트랙 안내](../../Evaluation/tracks/contextual/README.md#명시적-원문-입력과-분할-후보-준비)에 적었다.

`span_inputs.py`는 저장 v4 요청의 명시적 원문 입력과 구조 기반 분할 **후보**를 API·DB 호출 없이 별도 폴더에 준비한다.
후보는 기존 청크 내부의 문단·생략 구분선·제목·문장 구분을 사용하고, 원문 offset·부모 구간·별도 후보 분할 버전을 보존한다.
여러 장소를 의미적으로 판별한 운영 분할기가 아니며 모든 후보의 `indexable=false`다.
기존 부모 경계에서 잘린 문장을 복원하지 않고, 매우 짧은 후보·주어 생략·장소당 활성 20개 상한의 누락도 해결하지 않는다.
준비 단계에서 실제 9개 기록의 입력 22구간 보존·후보 136개·원본 36개 파일 해시를 확인했으며 생성·색인·검색 품질은 새로 측정하지 않았다.
[준비·검증 기록](../../Evaluation/runs/contextual/span-inputs-v1/20261101-01/REPORT.md)에 범위를 구분했다.

후속 실제 생성 검수는 **v4 위치 입력→v5 명시적 입력**의 두 필드 변경을
`comparison_kind=explicit-input-and-instructions`로 별도 기록한다. 앞의 입력 형식 전용·지시문 전용 비교와 섞지 않는다.
`span_generation.py prepare`는 기존 요청과 대조한 실행 계획을 쓰고, `generate --execute`만 최대 9회 유료 호출한다.
요청·원본 해시 검증 후 지정 키 파일을 직접 읽으며, 실패·모델 불일치 시 뒤의 호출을 중단한다.
기존 전송 시도나 완료/중단 요약이 있으면 자동 재실행하지 않는다. 오류 응답 진단에는 키를 제거한 제한된 본문만 남긴다.
실제 요청·모델·검증 버전·비용을 감사하고, 문맥 의미 검수는 별도 파일에 기록한다.

새 응답 9개·동일 22구간 검수에서 인접 청크 주제 대체는 2→0, 다른 장소 경관의 대상 subject 귀속 회귀는 0→1이었다.
이는 한 번의 개발 표본 검수다. 입력 추가만의 효과나 이전 오류의 원인을 분리해 입증하지 않았고 검색은 재실행하지 않았다.
분할·색인·기본값은 유지했다. [실제 문맥 검수 기록](../../Evaluation/runs/contextual/span-grounding-v1/20261101-01/REPORT.md)을 참고한다.

### 관찰 단위 분할과 이동 관계: v6 보존 계약

`source-span-v1`은 기존 800자·줄바꿈 분할이며 기본값을 유지한다.
선택 버전 `sentence-paragraph-v2`는 보존 본문 전체의 문장 종결·문단·제목·구분선 경계를 사용한다.
장소 이름의 개수는 분리 조건이 아니다. 한 문장에 있는 A→B 이동은 한 구간에 그대로 남긴다.
블로그의 단순 시각적 줄바꿈을 모두 자르지 않으며, 800자보다 긴 구간에 경계가 없으면 임의 절단하지 않고 준비 단계에서 거부한다.
이 휴리스틱이 모든 관찰·주제 경계를 정확히 찾는 것은 아니다. 같은 문장에 여러 관찰이 섞인 경우 귀속 보류·검수가 필요하다.

새 구간은 정규화 없이 원문을 정확히 재현하며 `source_id/source_version/start/end/splitter_version`을 보존한다.
`splitter_version`을 요청·기록·캐시·청크 UUID·DB 저장·무료 재검증까지 전달한다.
경계가 우연히 같아도 분할 버전이 다르면 chunk_id가 다르며, 기존 버전의 ID와 해시는 그대로다.
이전 청크의 문맥·역할을 새 구간에 복사하지 않고 Sonar에게 각 구간을 새로 판정하게 한다.

v6는 기존 출력 필드에 다음을 **별도 스키마**로 추가한다. v1~v5 스키마는 바꾸지 않는다.

- `content_kind`: `landscape | facility | movement | other`. 시설·이용, 경관, 이동 등 내용 종류다.
- `place_refs[].role`: 기존 `subject | mentioned | view_target`. subject는 핵심 장소이며 내용 종류가 아니다.
- `relations[]`: 이동의 `origin`, `destination`, `conditions`. 다른 내용은 빈 배열이다.
- 각 endpoint의 `place_id`는 제공된 기존 ID 또는 `null`, `name`은 알려진 ID일 때 등록 이름과 일치해야 한다.
- 이동 조건은 `stairs | distance | duration | other`와 현재 구간의 정확한 `quote`를 저장한다.
  조건 인용이 원문에 있다는 검사가 의미 분류·방향까지 보증하지는 않는다.

```json
{
  "content_kind": "movement",
  "place_refs": [{"place_id": 101, "role": "subject"}, {"place_id": 202, "role": "subject"}],
  "relations": [{"origin": {"place_id": 101, "name": "A공원"},
                 "destination": {"place_id": 202, "name": "B공원"},
                 "conditions": [{"kind": "stairs", "quote": "계단을 내려가"}]}]
}
```

위 ID는 계약 설명용이다. 이동의 등록된 양끝은 핵심 참가자로서 subject가 될 수 있다.
이는 경관·시설을 양쪽 장소에 귀속한다는 뜻이 아니다. 경관은 그 관찰 장소에, 주차는 해당 시설 장소에만 연결한다.
등록되지 않은 출발지·도착지는 이름과 `null` ID로 보존하며 다른 장소의 ID를 대신 쓰지 않는다.
알려진 endpoint가 하나도 없거나 구체적 이동 관계를 확정하지 못하면 원문·문맥은 남기고 검색을 보류한다.
거리·시간·계단만으로 ‘쉽다·평탄하다·안전하다’를 만들지 않는다.

v6 요청은 `fast`·8192 출력 한도·`tools=[]`로 별도 고정했다. 이번 검수에서 바뀐 것은 분할·지시문·출력 스키마·처리 버전이므로
프롬프트만 바꾼 비교나 분할만의 효과로 표시하지 않는다.

### 관찰 검증·검수 후 적용: v6 보존 계약

v6의 새 기록은 `contextual-validation-v3`를 사용한다. v1~v5의 기존 처리 버전은 바꾸지 않는다.
전체 출력 스키마와 source/span의 누락·중복·변조는 응답 검증 오류다.
그 검사를 통과한 뒤 미등록 ID·관계 ID/명칭 불일치·현재 구간에 없는 조건 인용 등은 **해당 구간만**
`invalid_attribution`으로 격리한다. `validation_error`·원래 역할·관계·문맥·원문을 보존하고 정상 구간은 처리한다.
미등록 ID는 제공한 기존 장소 목록 밖의 ID를 뜻한다. 생성기가 운영 DB 전체를 조회한 결과로 해석하지 않는다.
`content_kind=movement`이지만 구체적 관계가 없으면 `unresolved_movement`로 보존하고 검색에서 보류한다.
스키마 통과와 의미 정확성은 별개다. v2 기록을 v3처럼 해석하지 않으며 받은 응답은 명시적 무료 재검증으로 새 기록을 만든다.

새 분할 또는 관계 계약의 DB 적용에는 `contextual-approval-v1` 검수 목록이 필수다.
요청 해시와 원본 4개 파일 해시에 묶인 `approved_chunk_ids`만 적용하며 오류·보류 구간은 승인할 수 없다.
같은 이동 청크의 모든 핵심 참가자 귀속을 승인하는 의미다. 검수자는 에이전트일 수 있으며 사람 검수로 가장하지 않는다.
승인 0개이면 기존 번들·활성 청크를 바꾸지 않고 종료한다. 승인된 청크에도 기존 장소별 20개·원문 중복 제거·출처 순회 선택을 적용한다.

`generate --splitter-version sentence-paragraph-v2 --input-version source-explicit-chunks-v2 --prompt-version contextual-observation-relations-v6`
는 새 계약의 선택 실행이다. `--execute` 없이는 미리보기다. 기존 `--baseline-record`의 프롬프트 전용 비교로 분할·스키마 변경을 통과시키지 않는다.
`review`는 검수 후 명시한 ID 목록을 기록하고, `selection`은 DB 없이 선택·미선택 사유를 출력한다.
`apply --review <검수파일>`은 기존대로 명시적 DB 적용이다. 이번 실험에서 apply는 실행하지 않았다.

[실제 P08·P09 검수](../../Evaluation/runs/contextual/observation-spans-v1/20261101-01/REPORT.md)는 57구간·유료 2회·US$0.02041이다.
자동 귀속은 고정 회귀 5개 중 4개 통과이며 P09 경관 오류가 남았다. 검수에서 승인하지 않은 뒤 선택 근거는 5개를 만족했다.
이는 자동 판정 5/5나 검색 성능 개선을 뜻하지 않는다. 운영 기본값은 유지한다.

### 핵심·보조 관계의 독립 보존: v7 선택 계약

v6의 제한을 바꾸는 새 계약은 `contextual-independent-relations-v7`와 `contextual-validation-v4`다.
기존 v1~v6 지시문·스키마·저장 기록은 그대로 읽으며 중요도를 임의로 채우지 않는다. 기본값은 계속 v2다.
입력·분할은 명시적 원문과 `sentence-paragraph-v2`를 유지한다. 스키마 변경을 프롬프트 전용 비교로 통과시키지 않는다.

`content_kind`는 주된 관찰의 종류이며 관계의 허용 조건이 아니다. 경관·시설·기타 청크에도 이동 관계를 둘 수 있다.
각 관계에는 `type=movement`, `importance=primary|supporting`, `origin/destination/conditions`, `evidence`가 필요하다.
primary는 핵심 관계, supporting은 주된 관찰에 덧붙은 보조 관계다. 둘 다 이동 검색에 사용하며 자동 점수 가중치는 없다.
관계의 알려진 endpoint는 place_refs에 실제 역할로 보존하지만 subject와 같도록 강제하지 않는다.

합성 예시 `A공원은 야경이 아름답고, 관람 후 B공원으로 걸어갈 수 있다.`는 한 청크로 보존한다.
A=subject, B=mentioned, content_kind=landscape이며 A→B 관계는 supporting이다.
관계의 `evidence={start,end,quote}`는 같은 원문 내 절대 Unicode 위치와 정확한 이동 절을 가리킨다.
현재 청크 밖의 위치·변경된 인용·미등록 ID·등록 명칭 불일치·그 관계 근거 밖의 조건 인용은 해당 구간을 검증에서 격리한다.
정확한 인용 검사만으로 모델이 이동 방향·주요도·의미 범위를 맞췄다고 보증하지 않으므로 검수 승인도 유지한다.

DB의 `place_active_chunks.role`은 기존 `subject`와 새 `relation_endpoint`를 구분한다. 모델의 place_refs 역할을 바꾸지 않는다.
A에는 subject 슬롯, B에는 relation_endpoint 슬롯이 같은 chunk/context를 참조한다. 원문·청크를 두 개로 나누거나 복제하지 않는다.
DB trigger는 subject 슬롯에 명시적 subject를, relation_endpoint 슬롯에 독립 관계의 실제 참가자와 장소 참조를 요구한다.
명확한 관계만 있고 subject가 없는 청크도 알려진 endpoint가 있으면 관계 전용 후보가 될 수 있다.
알려진 endpoint도 subject도 없으면 귀속 보류로 보존한다.

chunk-only의 일반 검색과 명시적 경관·시설 검색은 subject 슬롯과 해당 관찰의 주체만 사용한다.
chunk-and-relation-v1의 필터 없는 일반 검색은 양쪽 활성 슬롯의 관계 인용도 조회한다. 전체 청크 벡터는 subject 슬롯에만 허용한다.
명시적 이동 검색은 두 슬롯을 조회하고 관계 endpoint로 방향을 제한한다.
관계 검색에는 청크의 content_kind가 movement일 필요가 없다. 후보와 복수 근거 확장에 같은 필터를 적용한다.
이동 리랭킹 입력과 결과 description은 일치한 관계의 정확한 evidence.quote를 사용한다.
응답 evidence에는 원문 전체·place_refs를 보존하고 `retrieval_scope=relation`, `matched_relations`, `search_text`로 사용 범위를 표시한다.
따라서 보존용 전체 원문을 목적지의 경관·시설 근거로 해석하지 않아야 한다.
목적지의 기본 장소 벡터도 출발지의 혼합 관찰을 재사용하지 않고 목적지 자체의 subject 근거 또는 기본 장소 설명에서 고른다.
위 v7 초기 경로에서 관계 후보를 찾던 벡터는 전체 청크의 문맥+원문이었다. 후속 선택형 관계 인용 벡터와 일반 검색 통합은 아래 절에 구분해 기록한다.

apply의 상태·지문 검사와 재색인 대상은 승인 청크의 subject 및 알려진 관계 endpoint의 합집합이다.
단순 mentioned만 있는 장소는 계속 적용 대상이 아니다. 관계 endpoint는 실제 쓰기 대상이므로 삭제·재색인 대기 상태이면 원자 적용을 중단한다.
검수 승인 0개는 기존 번들을 변경하지 않는다. 승인한 한 청크의 관찰·관계를 함께 승인하며 관계별 부분 승인은 지원하지 않는다.
장소별 20개 상한을 관찰·관계 슬롯이 함께 사용한다. 최신 번들 교체 정책도 유지하므로 유지할 전체 자료를 함께 적용해야 한다.

이 변경의 SQL 파일과 Docker 초기화 사본은 함께 수정했지만 이번에는 DB에 실행하지 않았다.
운영 적용에는 해당 스키마 갱신·명시적 검수·재색인이 필요하며 기존 벡터가 자동 갱신되지 않는다.
[코드 회귀·호환 검증 기록](../../Evaluation/runs/contextual/supporting-relations-v1/20261101-01/REPORT.md)에
합성 A/B 사례와 실제 보존 파일 검증을 기록했다. 유료 호출·DB 조회/쓰기·실제 검색 성능 실행은 0회다.

### 관계 인용의 서버 위치 계산: v8 선택 계약

신규 `contextual-server-evidence-v8`은 v7의 역할·주체·핵심/보조 관계를 유지하면서 relation.evidence를 `{"quote": "정확한 원문"}`만 받는다.
관계 위치의 start/end는 모델이 반환하지 않으며 출력 스키마도 이를 허용하지 않는다. 청크 자체의 source_id/start/end는 기존 서버 분할 좌표를 복사한다.
서버는 **현재 청크 안에서** 인용을 정확히 검색한다. 한 곳이면 `source_start = chunk.start + local_start`, `source_end = source_start + len(quote)`로 계산한다.
0곳은 `quote_not_found`, 여러 곳(겹친 중복 포함)은 `quote_ambiguous`, 공백만 있으면 `quote_empty`로 보류한다.
공백·줄바꿈·Unicode를 정규화하지 않고, 다른 청크에서 찾거나 유사 문장으로 고치지 않으며, 모델의 옛 위치를 사용해 중복을 해소하지 않는다.

검증은 `contextual-validation-v5`, 계산 규칙은 `relation-quote-exact-unique-v1`이다. 보존 원문 Unicode 코드포인트·끝 제외 기준이다.
처리 record의 `evidence_grounding[]`에 출처·청크 범위·관계 순번·quote·status·계산 규칙·모델 원래 `model_evidence`·서버 `server_span`을 기록한다.
저장·검색용 SearchChunk.relations에는 서버가 계산한 evidence.start/end/quote를 넣고 참가자·역할·조건 검증을 계속 수행한다.
아카이브 재로딩은 계산 내역까지 보존 응답으로 재검증한다. 관계가 보류되면 현재는 부모 청크 전체를 제외하며 관찰만 살리는 정책은 추가하지 않았다.

v1~v7 지시문·스키마와 v7 기본 검증 v4는 보존한다. 기존 v7은 다음처럼 **단일 응답에 v5를 명시**해야 재계산한다. 원본 4개 파일은 보존하고 새 폴더에 처리 record를 만든다.

```powershell
python -X utf8 -m app.contextual.cli revalidate --record "기존/record.json" --output "별도/재처리폴더" --validation-version contextual-validation-v5
```

`--validation-version`의 디렉터리 일괄 재처리는 지원하지 않으며 오류를 반환한다. v7→v8은 출력 스키마도 바뀌므로 프롬프트 전용 비교에서 거부한다.
새 생성 요청 준비는 기존 generate에 `--prompt-version contextual-server-evidence-v8 --input-version source-explicit-chunks-v2 --splitter-version sentence-paragraph-v2`를 지정한다.
기본값 v2는 유지한다. 이번에는 새 v8 유료 생성·DB 반영·검색을 실행하지 않았다.

[서버 위치 계산·실제 두 응답 재처리 기록](../../Evaluation/runs/contextual/v8-server-evidence-v1/20261101-01/REPORT.md):
CONTROL `[16:35]`→`[15:35]`, P09 `[263:283]`→`[264:282]`로 복구했다. 원본 45개 보존 해시를 확인했고 추가 호출은 0회다.
이 결과는 정확한 인용의 위치 오류 방지이며, 의미 귀속·Top-30·활성 20개 제한·검색 성능 개선은 별도다.

### 역할에 따른 자동 보존·검색 제외

v1~v5의 새 응답 및 명시적으로 재검증한 응답은 `contextual-validation-v2`를 사용한다. 사람이 역할을 다시 분류하지 않는다.
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
아래 적용 대상 설명은 v1~v6의 subject 전용 계약이다. v7의 독립 관계는 위 별도 계약을 따른다.
여러 장소가 있는 응답에서도 해당 장소의 subject 근거가 없으면 그 장소의 번들을 교체하거나 재색인하지 않는다.
DB 행 잠금·READY/최신 버전·기본정보 지문 검사도 실제 적용할 subject 장소에만 수행한다.
참고 장소의 삭제·재색인 대기·기본정보 변경은 정상 subject의 적용을 막지 않으며,
입력에 없는 장소 ID나 역할 불일치 등 보존 응답 검증은 계속 모든 참조에 적용한다.
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
`apply`는 스키마/보존 응답/원문/offset을 재검증하고 적용할 subject 장소와 v7 독립 관계 endpoint의 DB 기본정보를 확인한다.
여러 주체 장소 적용은 ID 순으로 잠그고 원자 저장한다.
같은 번들 재적용은 `ALREADY_APPLIED`; 새 번들은 `REINDEX_QUEUED`. 후자는 검색 반영 완료를 의미하지 않는다.
기존 장소별 imported bundle은 최신 적용본으로 교체되며 이전 원문/청크/문맥은 삭제하지 않는다.
누적할 자료는 새 입력 번들에 기존 유지 자료도 함께 넣는다. 단순 언급 장소는 활성화하지 않는다. v7의 명확한 관계 endpoint는 subject 승격 없이 관계 역할로 활성화한다.

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
`failed`는 개별 응답 재검증 실패 수이며 비교 완료 여부를 뜻하지 않는다.
`expected_comparisons`·`completed_comparisons`·`comparison_complete`로 기대한 비교 쌍의 완료 여부를 별도로 기록한다.
v1·v2 한쪽 원본이 입력 폴더 밖에 있거나 원본/응답 파일이 없으면 `missing_comparison_partners`에
양쪽 요청 해시·누락된 쪽·원래 비교 보고서를 기록한다. 원본 재검증이나 비교 보고서 생성 실패는 `comparison_errors`에 남긴다.
`--paired-only`에서 비교가 0쌍이거나 일부라도 미완료이면 개별 응답의 `failed=0`이어도 종료 코드 1을 반환한다.
이미 재검증한 파생 기록의 비교 보고서는 원본 비교 쌍 집계에서 제외하므로 같은 폴더를 재처리해도 기대 쌍 수가 늘지 않는다.
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
| place_active_chunks | 장소별 1..20 slot, chunk/context FK, subject/독립 관계 endpoint 역할 구분 trigger |
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

`CONTEXTUAL_RERANK_EVIDENCE_PER_PLACE=1`이 기본값이며 위 단일 근거 경로를 유지한다.
`2`·`3`을 명시하면 같은 Top-30 장소 후보에 한해서 subject 근거를 cosine 순으로 추가 조회한다.
장소별 `chunk_id + context_version` 중복을 제거하고 각 문맥+원문을 별도 쌍으로 리랭킹한다.
장소 점수는 최고 근거 점수이며 합산하지 않는다. 동점이면 기존 후보 순서를 유지한다.
설정은 Docker Compose와 stack bootstrap이 전달한다. source.env에서 설정을 제거하면 이전 실행값도 제거해 기본값으로 돌아간다.
이 값은 API 요청의 사용자 입력으로 받지 않는다. 범위 밖 설정은 시작 단계에서 거부한다.

복수 근거 경로는 요청당 최대 90쌍·토크나이저가 실제로 절단한 뒤의 총 32,768토큰을 상한으로 둔다.
한도를 넘으면 모델을 호출하기 전에 명시적으로 실패하며 근거를 몰래 삭제하거나 다른 검색 방식으로 바꾸지 않는다.
모델별 입력 길이 제한·배치·정밀도는 기존 설정을 따른다. 후보 조회 이후 원본 버전·대표 활성 근거가 바뀌어도 실패 처리한다.
`SEMANTIC_ONLY`에는 복수 근거 조회나 토큰 예산 검사를 적용하지 않는다.

복수 근거의 반환 장소는 한 번만 나오며 `description`은 최고 점수 근거의 문맥+원문이다.
장소의 `semantic_score`는 원래 장소 후보의 대표 cosine score를 유지한다.
`evidence_chunks`는 리랭킹 점수 순이며 각 근거에 `rerank_score`·`semantic_score`를 추가한다.
`rerank_score`는 사실 확률이 아니다. 추가된 근거에도 생성 오류가 있을 수 있으므로 복수 반환을 사실 검증으로 해석하지 않는다.
Spring은 JSON의 기존 필드를 직접 읽고 원본 완료 JSON도 보존하므로 앱 DTO 변경은 없다.

[근거 1·2·3개 실측](../../Evaluation/runs/contextual/multi-evidence-v1/20261031-01/REPORT.md)은
한 장소·고정 26문항에서 수행한 격리 실험이다. 이 결과로 기본값이나 운영 서버를 변경하지 않았다.
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

### 이동 근거 직접 벡터 후보 검색: 선택 실험 v1

`CONTEXTUAL_RELATION_RETRIEVAL=chunk-only`가 기본값이다. `chunk-and-relation-v1`을 명시하면 기존 활성 청크 전체 벡터와 별도로 독립 이동 관계의 **정확한 evidence.quote**를 BGE-M3로 임베딩한다.
예상 질문을 생성하지 않고, 미선택 청크를 활성화하지 않는다. 기존 v6처럼 정확한 관계 인용이 없는 자료에는 별도 인용을 만들지 않으며 기존 전체 벡터 경로를 유지한다.

추가 테이블 `retrieval_relation_embeddings`의 키는 `chunk_id + context_version + relation_index + representation_version`이다.
`representation_version=relation-quote-vector-v1`, 원문 evidence JSON, `VECTOR(1024)`, embedding_model을 보존한다. context FK와 HNSW cosine 인덱스를 둔다.
trigger는 해당 순번의 type=movement, importance=primary/supporting, evidence 동일성·청크 안 위치·실제 원문 substring 일치를 검사한다.
색인 작업자는 기존 전체/대표 벡터와 함께 추가 벡터를 추론하고, 기존 버전·스냅샷·청크 세대 CAS 성공 트랜잭션 안에서만 저장한다. 선택되지 않은 청크의 관계 벡터는 추가 생성하지 않는다.

추가 경로는 observation 필터가 없는 일반 의미 검색에서도 사용한다. 질의 임베딩을 추가 호출하지 않고 같은 벡터를 전체 청크와 관계 인용에 사용한다.
일반 검색은 출발지·도착지·비중을 제한하지 않는다. 전체 청크 표현은 subject 슬롯만 사용하고 관계 인용은 일치하는 양쪽 endpoint 슬롯에서 사용할 수 있다.
명시적 observation 필터가 있으면 기존 범위를 유지한다. 이동 조건의 참가자·방향·결과 endpoint·비중을 **개별 relation_index에도 먼저 적용**하고, 경관·시설 조건에 관계 후보를 섞지 않는다.
같은 청크의 전체 벡터와 조건에 맞는 관계 벡터 중 최고 cosine, 같은 장소의 활성 청크 중 최고 cosine을 선택한다. 합산하지 않고 장소 중복 제거 후 Top-30을 유지한다.
후보와 추가 근거 조회에 동일한 규칙을 사용한다. 관계 벡터가 선택되면 evidence에 `retrieval_path=relation`, `retrieved_relation_index`를 넣고 그 관계의 실제 인용으로만 리랭킹한다.
일반 검색의 추가 근거에서는 같은 청크의 전체 표현과 관계별 인용을 별도 근거로 취급한다. 중복 키는 chunk_id/context_version/retrieval_path/relation_index이며 동일 표현만 제거한다.
근거 수는 기존 설정(기본 1, 선택 2·3)과 전체 쌍·토큰 예산 안에서 제한한다. 복합 질문에 두 근거가 항상 보장되는 것은 아니다.
같은 청크여도 후보 검색 뒤 선택 표현이 바뀌면 재검증에서 거부한다. 결과의 보존 원문·place_refs는 변경하지 않으며 relation 범위와 matched_relations로 실제 사용 범위를 표시한다.
다른 장소의 경관을 목적지에 공유하거나 예상 질문을 추천 인용으로 사용하지 않는다. 경관·시설·필터 없는 기존 검색은 그대로다.

Compose/stack bootstrap은 이 설정을 전달하고 허용하지 않은 값은 거부한다. source.env에서 제거하면 이전 실행값도 제거해 chunk-only로 복귀한다.
기존 데이터는 설정만 바꿔도 추가 벡터가 생성되지 않는다. 검수된 표본에 스키마 적용·기존 명세의 재색인 작업 등록이 필요하며, 번들 재적용의 ALREADY_APPLIED와 구분한다.
이번 작업은 운영 DB 적용·운영 설정 변경·배포를 하지 않았다. 추가 벡터가 저장돼도 검색은 place_active_chunks를 통하므로 기존 장소별 20개 상한을 우회하지 않는다.

[고정 비교 기록](../../Evaluation/runs/contextual/relation-vector-retrieval-v1/20261101-01/REPORT.md):
같은 검수 자료·활성 슬롯·후보 30·근거 2에서 보조 이동 근거가 Top-30 탈락→후보 1위·리랭킹 1위로 바뀌었다. B의 선택 순서 44번째 근거는 활성 20개 밖이어서 두 방식 모두 검색되지 않았다.
기존 임베딩 58개를 재사용하고 인용 4개만 추가 임베딩했다. 누락된 질의·원문 점수 9개만 추가 리랭킹했으며 Sonar 유료 호출은 0회다.
작은 감독·합성 스트레스 실험이므로 일반 검색·전체 지연 개선을 입증하지 않는다. 기본값·활성 상한·귀속 정책은 유지한다. 활성 상한 의미 변경은 별도 결정이다.

### 연결 질문의 대표 근거와 결과 보류

검색·리랭킹 이후, 최종 limit 적용 전에 `contextual/evidence_quality.py`를 실행한다.
명시적 이동 필터 또는 제한된 한국어 연결 표현으로 판별한 질문이 대상이며, 검색 경로 선택이나 후보 순위 계산에는 사용하지 않는다.
명시적 비이동 observation 조건과 인식하지 못한 일반 질문은 `evidence_quality_scope=not_assessed`로 기존 응답을 유지한다.
이 정책은 chunk-only 설정에서도 실행된다. 기본 검색 설정 유지가 연결 질문의 응답 동작 유지까지 뜻하지는 않는다.

선택된 원문 근거의 독립 movement relation에서 정확한 인용·위치를 검증한다. `connection_statements.py`의 전략 레지스트리는
명시적인 성공·차단 표현·미판정을 구분한다. 범용 의미 함의 판정기가 아니며, 추측·조건부 표현은 보수적으로 미판정한다.
도보 조건이 없는 질문은 차량·도보를 함께 허용한다. 차량 연결 문장의 도보 금지를 전체 연결 차단으로 취급하지 않는다.
대표는 기존 선택 근거 중 조건에 맞는 긍정 기록에서 고르고 장소의 기존 점수·상대 순서는 유지한다.
낮은 점수 자체를 보류 기준으로 삼지 않는다. 대표 점수는 `representative_rerank_score`로 장소 점수와 분리한다.

연결 근거 없음·긍정 기록 없음·미판정·이동수단 불일치·활성 스냅샷 변경·질문 조건 미해결을 서로 다른 사유로 보류한다.
보류는 장소가 실제로 연결되지 않았다는 판정이 아니다. 추가 검색 없이 현재 선택 근거로 추천 조건을 뒷받침하지 못했다는 뜻이다.
선택 근거 수는 늘리지 않으며, 활성 문맥에만 있고 선택·리랭킹하지 않은 긍정 기록을 대표로 올리지 않는다.

별도 SQL 1회로 후보들의 기존 활성 subject/relation_endpoint 슬롯만 읽어 차단 기록을 대조한다. 활성 20개 밖은 읽지 않는다.
동일한 방향의 동일 endpoint 관계에서 겹치는 이동수단의 차단 기록을 함께 보존한다. 이동수단 미상도 충돌 가능성을 표시한다.
동일 place_id의 이름 표기가 달라도 대조하며, 역방향·다른 목적지의 차단은 같은 관계의 충돌로 합치지 않는다.
게시일을 방문일·재개통일로 간주하지 않는다. 현재 통행 상태는 항상 `unverified`이며 시점 미상 충돌을 대표 설명에 표시한다.
원문·출처·귀속·비중·방향·계단/차단 등의 조건은 유지한다.

결과에는 장소별 `evidence_assessment`, 전체 `withheld_count`, `withheld_results`, `evidence_quality_scope`와 경고가 추가된다.
Spring은 변경된 description과 원본 완료 JSON을 보존한다. 보류 사유·구조화 근거를 표시하는 새 UI는 추가하지 않았다.
기본 근거 1개에서 차단 근거만 선택되면 활성 문맥에 성공 기록이 있어도 보류될 수 있다.
관계 인용이 없는 구버전 자료도 연결 질문에서 보류될 수 있다. 복합 질문은 연결 차원만 검사하며 경관 등 모든 조건의 충족을 보증하지 않는다.

[저장 결과 재생·코드 회귀·한계](../../Evaluation/runs/contextual/evidence-quality-policy-v1/20261101-01/REPORT.md)

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

같은 날 후속 검토에서 참고 장소의 DB 상태가 subject 적용을 막는 경우와 비교 상대 누락에도 CLI가 성공하는 경우를 재현했다.
DB 검사는 subject 장소로 한정하고, 일괄 비교에는 기대/완료 쌍 수·누락 상대·완료 여부·오류에 따른 종료 코드를 추가했다.
보완 후 임베딩 서버 전체 테스트는 47개 통과·환경 미설정 통합 테스트 11개 skip이다.
참고 장소의 삭제·재색인 대기·정보 변경, subject 자체의 잘못된 상태, 폴더 밖 v1·누락된 v2·양쪽 원본 누락,
비교 0쌍·파트너 재검증 실패·비교 보고서 생성 실패·파생 기록이 있는 폴더 재실행을 회귀 테스트로 확인했다.
로컬 보존 응답 18건을 다시 처리한 결과 기대 9쌍·완료 9쌍·`comparison_complete=true`, 누락 상대·비교 오류는 0건이었다.
원본 72개 파일 해시 불일치와 추가 API 호출은 모두 0이며, 실제 DB 반영·재색인·검색 성능 평가는 실행하지 않았다.


## v7 실제 통합 검증 후속 결과

[PostgreSQL·Sonar·검색 실행 기록](../../Evaluation/runs/contextual/v7-integration-v1/20261101-01/REPORT.md)에서
새 역할·trigger·방향 SQL의 실제 PostgreSQL 통합을 통과했다. 최종 전체 회귀 109개 통과·1개 skip이다.
실제 Sonar 2건은 US$0.01287이며 통제 원문의 supporting 판정·인용은 맞았지만 시작 위치 1자 오류로 청크가 제외됐다.
P09의 다른 공원 귀속 오류도 남아 기본값을 유지한다.

12개 고정 검색과 2개 감독 진단은 기존 BGE·리랭커와 격리 DB에서 실행했다. 위치만 맞춘 감독 사례는
도보 금지 합성 방해 자료 40개 사이에서 벡터 41위로 Top-30 밖이었지만 41개를 리랭킹하면 1위였다.
B에서는 입력 순서의 활성 후보 44개 중 해당 근거가 44번째여서 활성 20개에 들지 못했다.
이는 단계별 손실 재현이며 감독 진단을 모델 자동 성공으로 세거나 운영 상한을 변경하지 않았다.
운영 DB 적용·배포는 없었고, 관계 위치 계산·관계 후보 검색·활성 선택 개선은 다음 구현 대상이다.
