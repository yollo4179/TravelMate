# 검색 평가 도구 계약

이 경로는 검색 HTTP 관측과 기존 단일 LLM의 native 도구 관측을 구분한다.
`collect_live.py`와 `collect_holdout.py`는 **장소 검색만** 호출한다.
도구 선택·계획 생성·응답 설명을 실행하거나 성공한 것으로 만들지 않는다.
단일 LLM의 원본 공급자 호출·서버 변환은 기존 `tracks/tool_call/convert_server_trace.py`로 읽는다.

## 원본과 평가용 변환

모든 검색은 `POST /api/places/search`의 독립 계약을 쓴다.
원래 query·region·city·category·exclude_place_ids·area를 각각 query·region·city·category·excludePlaceIds·area로 전달한다.
지역과 반경을 함께 전달할 수 있고, 계획 context나 현재 시각·이동수단을 생성하지 않는다.
누락 검색어를 추정하거나 중복 제외 ID·범위 밖 반경을 자동 보정하지 않는다.
대화 이력 등 표현할 수 없는 조건은 `not_run`으로 보존하고 다음 외부 호출을 중단한다.

`http_request.raw_body`와 SHA-256은 실제 전송 본문이며 인증 헤더는 기록하지 않는다.
`evaluation_projection`은 이 본문에 대한 별도의 평가용 변환이다.
`http_response.raw_body`는 오류 응답·비 JSON도 보존한다.
장소 ID·순위·`evidenceChunks`·원문·출처·장소 귀속·관계·조건은 응답 그대로 남긴다.
설명 문자열로 근거를 대체하거나 자르지 않는다.
`request_id`는 harness attempt ID이며 서버가 반환한 request ID와 혼동하지 않는다.
검색 전용 응답에 없는 turn ID·Job ID·tool_calls·LLM 문장은 생성하지 않는다.

## 실행 설정과 상한

실행 CLI는 `--config`, 새 `--output-dir`, 저장한 `--runtime-record`를 요구한다.
홀드아웃 수집기는 해당 버전의 명시적 `--question-review`도 요구한다.
case 목록은 기존 데이터셋에 있는 ID만 허용하며 전체/무작위 실행 기본값은 없다.
예열·재시도·자동 judge·자동 LangSmith export는 하지 않는다.
한도·실패·미지원 조건이 발생하면 이후 항목은 전송 없이 `not_run`으로 보존한다.

설정은 아래 필드를 모두 명시한다. 아래는 구조 설명이며 승인된 실행 설정이 아니다.
실제 LIVE 모델·문항·횟수·예산을 이 문서에서 선택하지 않는다.

```json
{
  "mode": "MOCK",
  "case_ids": ["PLR-TM-palaces-01"],
  "max_calls": {"search": 2},
  "timeout_seconds": 30,
  "model": null,
  "max_output_tokens": null,
  "parameters": {
    "server_url": "http://evaluation.invalid",
    "ranking_modes": ["SEMANTIC_ONLY", "RERANKED"],
    "response_limit": 20,
    "require_comparable_runtime": false,
    "dataset_manifest_sha256": "<실제 파일의 SHA-256>",
    "runtime_record_sha256": "<실제 파일의 SHA-256>"
  }
}
```

`collect_holdout.py`では parameters に `question_review_sha256`も指定する。
MOCKは`--mock-responses`を必須とし、LIVEは同オプションを拒否する。
モックのJSONは正確な送信要求のcanonical SHA-256から`{"response": ...}`への対応である。
モック戦略は実送信関数を呼ばず、対応がなければ失敗する。
LIVE認証は`--token-env`で指定した環境変数から読む。JWTを勝手に発行したりローカルruntime.envを探したりしない。

試行を`attempts.jsonl`へ送信前に書き、失敗・時間超過も上限を消費する。
既存journalの再利用を拒否するため、プロセス再起動で同じ実行の残予算をリセットできない。
モード・設定ハッシュ・case ID・元要求・元応答・時間・終了状態を残す。
MOCKの計算時間は実検索のレイテンシ集計に入れない。

## 評価対象の一致

`inspect_holdout_runtime.py`は明示した評価用コンテナ・DBを読み取る。
既定の運用コンテナ名に接続しない。
実行には明示設定と`runtime_read`上限が必要で、読み取りコマンドは2回である。
DBのSELECTと、既存health・設定・ソースハッシュ・HFキャッシュの参照だけを取得する。
モデルをimport/ロード/推論せず、環境変数は許可した非秘密設定だけ読む。
`--capture`なら保存JSONのオフライン照合のみ行い、Docker/HTTPを呼ばない。

場所IDだけでなく本文・地域・座標・TourAPI ID・READY状態・ベクトルの次元/保存ハッシュを比較する。
활성 슬롯·원문 청크·문맥·관계·TourAPI 원문도 `--expected-material`의 보존 자료와 전체 해시로 비교한다.
`--expected-runtime`에는 대상 이름과 metadata를 명시한다. 기대 자료를 현재 DB에서 자동 생성해 일치로 만들지 않는다.
모델명·캐시 revision·실제 파라미터 장치·정밀도·실효 배치·코드/환경 설정을 남긴다.
캐시 참조는 로드된 가중치의 동일성이나 벡터 재계산의 증거로 사용하지 않는다.
CPU나 다른 설정은 기능 관측으로 기록하되 동결 GPU 프로토콜과 일치한다고 표시하지 않는다.
기대 자료·테이블·정보가 없으면 실패 또는 미확인으로 남기며 새 자료로 빈칸을 채우지 않는다.

## 채점과 미관측

새 기록은 `search-api-observation-v2`이며 원본 request/response와 attempt의 일치를 검사한다.
LIVE 성공·전체 조건 적용·corpus/검색 자료/설정 대조가 모두 갖춰진 검색만 순위 품질 분모에 포함한다.
MOCK·실패·미실행·미확인 자료/설정은 null과 별도 건수로 표시하고 실제 빈 성공 응답 `[]`와 구분한다.
검색 전용 기록에는 설명 judge를 실행하지 않는다. 기존 native MOCK/DRAFT/Job 처리는 유지한다.
과거 `spring_search_api` 기록에 없는 관측을 보충하지 않으며 명시적인 변환이 필요하다고 채점을 보류한다.
미판정 후보를 확정된 오답이라고 부르지 않는다.

`search-holdout-v1.0.0`과 `v1.0.1`의 질문·protocol·manifest는 보존한 바이트 그대로 유지한다.
질문 검사는 검색 품질 완성을 의미하지 않는다. 계획의 조건 준수·실제 이동시간·최적화는 별도 평가다.
