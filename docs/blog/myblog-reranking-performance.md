---
layout: travelmate-article
title: 리랭킹 성능 개선
summary: LangSmith로 리랭킹 검색의 느린 구간을 찾고, 리랭커의 배치 크기와 연산 정밀도를 바꿔 리랭커 연산 시간을 평균 7.35초에서 0.52초로 줄였습니다.
travelmate_styles: true
asset_version: '20261027-1'
theme_color: '#eaf7ff'
nav_context: TRAVELMATE / EVALUATION 03
footer_label: TRAVELMATE / DEVELOPMENT RECORD
article_kicker: EVALUATION 03
toc_items:
  - id: summary
    title: 한눈에 보기
  - id: terms
    title: 용어 정리
  - id: problem
    title: 느려진 리랭킹 검색
  - id: bottleneck
    title: 느린 구간 찾기
  - id: why
    title: 배치와 정밀도를 바꾼 이유
  - id: experiment
    title: 설정별 결과 해석
  - id: quality
    title: 순위 품질 확인
  - id: code
    title: 관련 코드
  - id: result
    title: 검색 API 적용 결과
---

## 한눈에 보기
{: #summary }

- **문제** 리랭킹 검색이 평균 8.398초, 느린 요청은 28초 넘게 걸렸다.
- **원인** LangSmith span을 보니 그중 7.347초, 약 88%가 리랭커 연산이었다.
- **조치** 리랭커의 배치 크기를 32에서 8로, 연산 정밀도를 FP32에서 FP16 autocast로 바꿨다.
- **결과** 리랭커 연산이 평균 0.524초, p95 0.756초로 줄었고 검색 품질 지표는 그대로였다.

## 먼저 용어를 정리한다
{: #terms }

| 용어 | 뜻 | 이 글에서 |
| --- | --- | --- |
| 리랭커 | 질문과 장소 설명을 한 쌍으로 모델에 넣어 관련도 점수를 다시 계산하는 모델(Cross-Encoder) | `BAAI/bge-reranker-v2-m3`. 질문 하나에 후보 30쌍을 계산한다. |
| 배치 크기 (batch size) | GPU에 한 번에 넣어 계산하는 입력 쌍의 개수 | 8·16·32. 배치 8이면 30쌍을 8·8·8·6개로 네 번 나눠 계산한다. |
| 패딩 (padding) | 한 배치 안의 입력 길이를 가장 긴 입력에 맞추려고 채우는 빈 토큰 | 배치가 클수록 늘어나며, 모델은 빈 토큰까지 계산한다. |
| FP32 | 숫자 하나를 32비트로 표현하는 부동소수점. PyTorch의 기본 정밀도 | 모델 가중치와 기본 연산 |
| FP16 | 숫자 하나를 16비트로 표현하는 부동소수점. 크기가 절반이고 GPU Tensor Core로 빠르게 계산한다 | 행렬 곱 같은 무거운 연산 |
| autocast | PyTorch가 연산마다 FP16으로 해도 되는 것만 골라 FP16으로 실행하는 혼합 정밀도 기능 | 가중치는 FP32로 둔 채 계산만 FP16으로 한다. 가중치 자체를 낮은 비트로 바꾸는 양자화와는 다르다. |
| p50 · p95 | 응답 시간을 짧은 순으로 세웠을 때 50%와 95% 지점의 값 | p95는 느린 5% 요청이 시작되는 경계다. |
| 예열 (warm-up) | 첫 실행의 GPU 초기화 시간을 측정에서 빼려고 미리 몇 번 실행하는 것 | 설정마다 두 번 |
| CUDA 동기화 | GPU 작업이 끝날 때까지 CPU가 기다리게 하는 것. 시간을 정확히 잴 수 있지만 자주 하면 느려진다 | 진단 모드는 리랭커 내부 단계마다 동기화한다. |
| trace · span | 요청 하나(trace)를 단계별 구간(span)으로 나눠 기록한 것 | LangSmith에서 구간별 시간을 확인했다. |

설정 이름 `FP16 · 배치 8`은 FP16 autocast로 계산하고 배치 크기를 8로 둔 설정이다. 뒤의 숫자 8은 정밀도가 아니라 배치 크기다.

## 리랭킹을 붙이자 검색이 8초 넘게 걸렸다
{: #problem }

TravelMate의 장소 검색은 임베딩 모델 `BAAI/bge-m3`로 pgvector에서 후보 30개를 찾고, 리랭커가 질문과 장소 설명을 함께 읽어 순서를 다시 정한다. [골든 데이터셋으로 평가]({{ '/projects/travelmate/evaluation/ragas-golden-dataset/' | relative_url }})해 보니 리랭킹은 Top-1 정확도를 83.3%에서 88.3%로, NDCG@10을 0.850에서 0.907로 높였다.

문제는 속도였다. 제외 장소나 대화 맥락이 필요한 문항까지 포함한 80문항을 Spring → Kafka → FastAPI 검색 API로 호출하자, 리랭킹 검색은 평균 8.398초가 걸렸고 느린 요청은 28초를 넘겼다.

| 검색 API 응답 · 80건 | 의미 검색 | 리랭킹 |
| --- | ---: | ---: |
| 평균 | 0.978초 | 8.398초 |
| p50 | 1.004초 | 5.532초 |
| p95 | 1.523초 | 28.682초 |

## LangSmith span으로 느린 구간을 찾았다
{: #bottleneck }

검색 요청마다 OpenTelemetry span을 LangSmith로 보내고 있었기 때문에 요청 하나를 단계별로 나눠 볼 수 있었다. 리랭킹 요청 80개의 span을 집계했다. 아래 단계는 위 단계 안에 포함된 시간이다.

| 구간 · 리랭킹 요청 80건 | 평균 | p50 | p95 |
| --- | ---: | ---: | ---: |
| 검색 요청 전체 | 8.394초 | 5.528초 | 28.680초 |
| 처리 파이프라인 | 7.435초 | 4.644초 | 27.667초 |
| └ 질의 임베딩 | 0.070초 | 0.051초 | 0.140초 |
| └ pgvector 검색 | 0.005초 | 0.004초 | 0.013초 |
| └ 리랭커 연산 | 7.347초 | 4.546초 | 27.617초 |

검색 요청 평균 8.394초 가운데 7.347초, 약 88%가 리랭커 연산이었다. 질의 임베딩과 벡터 검색은 합쳐도 0.1초가 되지 않았다. 줄여야 할 곳은 리랭커였다.

이때 리랭커는 내부 단계를 자세히 보려고 CUDA 동기화를 넣은 진단 모드(FP32·배치 32)로 동작하고 있었다. 동기화 비용이 섞여 있을 수 있어서, 설정을 바꾼 효과는 같은 입력을 고정한 실험으로 따로 비교했다.

## 배치 크기와 정밀도를 바꾼 이유
{: #why }

### 배치 크기 설정이 전략까지 전달되지 않았다

먼저 배치 크기를 조정하려고 코드를 보니, 환경 변수 `RERANK_BATCH_SIZE`를 바꿔도 일반 실행 전략에는 반영되지 않는 구조였다. 전략이 `batch_size`를 인자로 받고도 버린 뒤 `model.predict(pairs)`를 호출해, sentence-transformers의 기본값 32로만 계산하고 있었다.

```python
# 수정 전: 전달받은 batch_size를 버리고 기본값 32로 계산
def execute(self, model, query, texts, batch_size, span):
    del batch_size
    pairs = [[query, text] for text in texts]
    scores = model.predict(pairs)
```

전략 세 개 모두 `batch_size`를 `predict`에 넘기도록 고친 뒤에야 배치 크기를 실험할 수 있었다. 후보는 최대 30개이므로 배치 32는 30쌍을 한 번에 넣는다는 뜻이다.

### 큰 배치는 패딩이 늘어난다

한 배치 안의 입력은 가장 긴 입력 길이에 맞춰 패딩된다. 장소 설명은 짧은 것과 긴 것의 차이가 커서, 30쌍을 한 번에 넣으면 짧은 설명도 가장 긴 설명 길이만큼 계산한다. 실험 중 모델에 실제로 들어간 텐서를 기록해 질문 하나당 평균 토큰 수를 셌다.

| 배치 크기 | 배치 구성(후보 30개) | 실제 토큰 | 패딩 포함 계산 토큰 | 패딩 비율 |
| ---: | --- | ---: | ---: | ---: |
| 8 | 8·8·8·6 | 7,028 | 9,102 | 29% |
| 16 | 16·14 | 7,028 | 11,536 | 64% |
| 32 | 30 | 7,028 | 15,987 | 125% |

배치 32에서는 실제 내용보다 빈 토큰을 더 많이 계산했다. 배치를 작게 나누면 한 번에 맞춰야 하는 길이 차이가 줄어 계산량이 줄어든다.

### FP16은 같은 계산을 더 가볍게 한다

FP16은 숫자 크기가 FP32의 절반이고, RTX 4050의 Tensor Core로 행렬 곱을 빠르게 계산할 수 있다. 먼저 한 질의(`서울 카페`, 후보 30개, 배치 32)로 시험했을 때 FP16 autocast는 FP32보다 3.08배 빨랐고 순위는 그대로였다. 배치와 정밀도는 서로 다른 비용을 줄이므로 두 값을 조합해 비교하기로 했다.

## 설정별 결과를 해석했다
{: #experiment }

리랭커 앞 단계의 변동을 없애기 위해 60문항의 질문과 후보 30개의 ID·순서·본문을 한 번 수집해 고정했다. 모델, 후보 수, 토큰 길이 제한은 그대로 두고 정밀도 2가지와 배치 3가지를 조합한 6개 설정을 실행했다. 각 설정은 첫 문항으로 두 번 예열한 뒤 60문항을 한 번씩 측정했고, 문항마다 설정의 실행 순서를 바꿨다. GPU는 NVIDIA GeForce RTX 4050 Laptop GPU다.

| 리랭커 설정 · 60문항 | 평균 | p50 | p95 | 최대 |
| --- | ---: | ---: | ---: | ---: |
| FP32 · 배치 32 (기준) | 13.728초 | 14.792초 | 24.258초 | 38.818초 |
| FP32 · 배치 16 | 2.760초 | 1.915초 | 12.395초 | 18.067초 |
| FP32 · 배치 8 | 1.527초 | 1.547초 | 2.187초 | 2.653초 |
| FP16 · 배치 32 | 1.530초 | 0.832초 | 3.559초 | 11.027초 |
| FP16 · 배치 16 | 0.656초 | 0.636초 | 0.865초 | 1.176초 |
| **FP16 · 배치 8** | **0.547초** | **0.527초** | **0.717초** | **0.874초** |

아래 실행 화면은 2026년 10월 26일 실행한 결과를 다음 날 LangSmith에서 캡처한 것이다. 이미지를 누르면 원본 크기로 보고 화살표로 다음 화면으로 넘어갈 수 있다.

### FP32 · 배치 32: 기준 설정

질문 하나에 평균 13.728초, 가장 느린 질문은 38.818초가 걸렸다. 30쌍을 한 번에 넣어 패딩이 실제 토큰보다 많았고, 한 질문이 다음 질문을 기다리게 할 만큼 느렸다. 실제 서비스의 진단 모드도 배치 32였으므로 이 설정을 모든 비교의 기준으로 삼았다.

### FP32 · 배치 16과 8: 배치만 줄였을 때

정밀도는 그대로 두고 배치만 줄였다. 배치 8의 평균은 1.527초로 기준보다 약 9배 짧아졌다. 계산한 토큰은 15,987개에서 9,102개로 1.8배 줄었는데 시간은 9배 줄었다. 트랜스포머의 어텐션 계산량은 입력 길이의 제곱에 비례해 늘어나기 때문에, 가장 긴 입력에 맞춰 커진 배치를 한 번에 계산하는 부담이 토큰 수 차이보다 크게 나타났다고 해석했다.

배치 16은 p50이 1.915초로 배치 8과 큰 차이가 없었지만 p95가 12.395초였다. 긴 설명이 몰린 질문에서 다시 크게 느려졌다. FP32에서 배치만 바꿨을 때는 배치 16과 8 모두 60문항의 전체 순위가 기준과 같았다.

### FP16 · 배치 32: 정밀도만 바꿨을 때

<figure class="travelmate-shot" data-media-gallery="reranker-langsmith">
  <a href="{{ '/assets/images/projects/travelmate/evaluation/langsmith-fp16-batch32.png' | relative_url }}" aria-label="FP16 배치 32 실행 화면 크게 보기">
    <img src="{{ '/assets/images/projects/travelmate/evaluation/langsmith-fp16-batch32.png' | relative_url }}" alt="LangSmith의 FP16 autocast 배치 32 실행 결과. 60문항, 평균 1530.273ms, p50 832.204ms, p95 3559.439ms, 최대 11027.408ms" width="727" height="1523" loading="lazy">
  </a>
  <figcaption><strong>FP16 · 배치 32</strong> · 평균 1,530.273ms, p50 832.204ms, p95 3,559.439ms, 최대 11,027.408ms</figcaption>
</figure>

배치는 32로 두고 FP16 autocast만 적용했다. 평균은 13.728초에서 1.530초로 약 9배 줄어 FP32·배치 8과 거의 같아졌다. 하지만 p50은 0.832초인데 p95는 3.559초, 최대는 11.027초였다. 대부분의 질문은 빨라졌지만 긴 설명이 섞인 질문에서는 큰 배치의 패딩 부담이 그대로 남아 꼬리 지연이 컸다. 정밀도만으로는 부족하고 배치도 함께 줄여야 한다는 뜻이다.

### FP16 · 배치 16: 꼬리 지연이 사라지기 시작했다

<figure class="travelmate-shot" data-media-gallery="reranker-langsmith">
  <a href="{{ '/assets/images/projects/travelmate/evaluation/langsmith-fp16-batch16.png' | relative_url }}" aria-label="FP16 배치 16 실행 화면 크게 보기">
    <img src="{{ '/assets/images/projects/travelmate/evaluation/langsmith-fp16-batch16.png' | relative_url }}" alt="LangSmith의 FP16 autocast 배치 16 실행 결과. 60문항, 평균 655.566ms, p50 636.271ms, p95 864.989ms, 최대 1176.324ms" width="1039" height="1459" loading="lazy">
  </a>
  <figcaption><strong>FP16 · 배치 16</strong> · 평균 655.566ms, p50 636.271ms, p95 864.989ms, 최대 1,176.324ms</figcaption>
</figure>

배치를 16으로 줄이자 p95가 3.559초에서 0.865초로 내려갔다. 평균과 p95의 차이가 0.2초 정도로 좁아져, 질문마다 응답 시간이 고르게 나왔다. 가장 느린 질문도 1.176초였다.

### FP16 · 배치 8: 가장 빠르고 안정적이었다

<figure class="travelmate-shot" data-media-gallery="reranker-langsmith">
  <a href="{{ '/assets/images/projects/travelmate/evaluation/langsmith-fp16-batch8.png' | relative_url }}" aria-label="FP16 배치 8 실행 화면 크게 보기">
    <img src="{{ '/assets/images/projects/travelmate/evaluation/langsmith-fp16-batch8.png' | relative_url }}" alt="LangSmith의 FP16 autocast 배치 8 실행 결과. 60문항, 평균 546.555ms, p50 527.418ms, p95 716.743ms, Top-1 0.8833, NDCG@10 0.9066" width="720" height="1504" loading="lazy">
  </a>
  <figcaption><strong>FP16 · 배치 8</strong> · 평균 546.555ms, p50 527.418ms, p95 716.743ms, 최대 874.077ms</figcaption>
</figure>

평균 0.547초, p95 0.717초로 여섯 설정 중 가장 빨랐다. 기준인 FP32·배치 32보다 평균이 약 25배 짧고, 가장 느린 질문도 1초를 넘지 않았다. 설정은 품질 기준을 통과한 것 가운데 p95가 가장 낮은 것을 고르도록 실험 코드에 정해 두었고, 그 규칙에 따라 이 설정이 선택됐다. 같은 화면의 Feedback에는 Top-1 0.8833, NDCG@10 0.9066이 함께 기록됐다.

### 반복 측정: 한 번의 결과가 아닌지 확인했다

<figure class="travelmate-shot" data-media-gallery="reranker-langsmith">
  <a href="{{ '/assets/images/projects/travelmate/evaluation/langsmith-batch-summary.png' | relative_url }}" aria-label="리랭커 설정 비교 요약 화면 크게 보기">
    <img src="{{ '/assets/images/projects/travelmate/evaluation/langsmith-batch-summary.png' | relative_url }}" alt="LangSmith의 리랭커 설정 비교 요약. 기준 FP32 배치 32, RTX 4050 Laptop GPU, BAAI/bge-reranker-v2-m3, 파라미터 float32, 60문항, 12문항 반복 측정에서 FP16 배치 8 평균 579.818ms, p50 542.771ms, p95 851.454ms" width="728" height="1518" loading="lazy">
  </a>
  <figcaption><strong>비교 요약 · 12문항 반복</strong> · FP16 · 배치 8 평균 579.818ms, p50 542.771ms, p95 851.454ms</figcaption>
</figure>

60문항을 한 번씩 잰 결과만으로는 우연히 빠르게 나왔을 수 있다. 그래서 입력 길이 순으로 고르게 고른 12문항을 FP32·배치 8과 FP16·배치 8로 세 번씩, 실행 순서를 번갈아 가며 다시 측정했다.

| 12문항 × 3회 | 평균 | p50 | p95 |
| --- | ---: | ---: | ---: |
| FP32 · 배치 8 | 1.549초 | 1.426초 | 2.357초 |
| FP16 · 배치 8 | 0.580초 | 0.543초 | 0.851초 |

같은 배치 8에서 FP16은 FP32보다 평균 약 2.7배 빨랐고, 60문항 측정과 비슷한 수준을 유지했다.

## 빨라진 만큼 순위가 달라지지 않았는지 확인했다
{: #quality }

FP16은 계산 오차가 생기므로 점수와 순위가 바뀔 수 있다. 그래서 설정마다 문항별 순위 지표 15개(Top-1, Hit@5·10, Recall·Precision·F1·MAP·MRR·NDCG의 @5·@10)를 기준 설정과 비교했다. 여섯 설정 모두 패딩을 뺀 입력 토큰이 같았고, 지표가 떨어진 문항은 하나도 없었다. 평균 Top-1은 88.33%, NDCG@10은 0.9066으로 모두 같았다.

| 설정 | 최대 점수 차이 | 전체 순위가 같은 문항 |
| --- | ---: | ---: |
| FP32 · 배치 16 | 0.000002 | 60 / 60 |
| FP32 · 배치 8 | 0.000005 | 60 / 60 |
| FP16 · 배치 32 | 0.001309 | 44 / 60 |
| FP16 · 배치 16 | 0.001309 | 46 / 60 |
| FP16 · 배치 8 | 0.001902 | 41 / 60 |

FP32는 배치를 바꿔도 점수 차이가 0.00001 미만이라 순위가 완전히 같았다. FP16은 점수가 최대 0.0019 달라져, 점수가 거의 같은 후보끼리 순서가 바뀐 문항이 생겼다. FP16·배치 8에서는 19문항의 일부 후보 순서가 바뀌었지만, 판정된 정답 장소의 순위 지표에는 영향이 없었다.

## 관련 코드
{: #code }

코드는 검색 서버의 리랭커 실행 전략(`embedding-server/app/reranking/`)과 고정 입력 실험(`Evaluation/tracks/search/batch_experiment.py`)으로 나뉜다. 항목을 누르면 코드를 펼쳐 볼 수 있다.

<details class="sql-evidence">
  <summary>실행 전략을 Enum과 레지스트리로 고른다</summary>
  <div class="sql-evidence__content" markdown="1">

리랭커 실행 방식은 전략 클래스로 나누고, 각 전략이 `is_applicable`로 자신이 선택됐는지 판단한다. 레지스트리는 정확히 하나의 전략만 골라 반환한다.

```python
# embedding-server/app/reranking/strategies/base.py
class RerankingStrategyType(StrEnum):
    CROSS_ENCODER_PREDICT = "cross_encoder_predict"
    INSTRUMENTED_PREDICT = "instrumented_predict"
    AUTOCAST_FP16 = "autocast_fp16"
    MANUAL_DIAGNOSTIC = "manual_diagnostic"


class RerankingStrategyRegistry:
    def resolve(self, strategy_type: RerankingStrategyType) -> RerankingStrategy:
        applicable_strategies = [
            strategy for strategy in self.strategies
            if strategy.is_applicable(strategy_type)
        ]
        if len(applicable_strategies) != 1:
            raise ValueError(...)
        return applicable_strategies[0]
```

서버는 환경 변수로 전략과 배치 크기를 읽는다. `RERANK_EXECUTION_STRATEGY`가 있으면 그 전략을, 없으면 진단 여부에 따라 진단 모드나 기본 `predict`를 쓴다.

```python
# embedding-server/app/reranker.py
RERANK_BATCH_SIZE = max(1, int(os.getenv("RERANK_BATCH_SIZE", "32")))

@staticmethod
def _resolve_strategy_type() -> RerankingStrategyType:
    if RERANK_EXECUTION_STRATEGY:
        return RerankingStrategyType(RERANK_EXECUTION_STRATEGY)
    if RERANK_DIAGNOSTICS_ENABLED:
        return RerankingStrategyType.MANUAL_DIAGNOSTIC
    return RerankingStrategyType.CROSS_ENCODER_PREDICT
```

  </div>
</details>

<details class="sql-evidence">
  <summary>FP16 autocast 전략</summary>
  <div class="sql-evidence__content" markdown="1">

모델은 FP32로 불러 둔 채, `predict` 호출만 `torch.autocast` 안에서 실행한다. CUDA가 없으면 autocast를 끄고 FP32로 계산한다.

```python
# embedding-server/app/reranking/strategies/predict.py
class AutocastFp16CrossEncoderPredictStrategy(RerankingStrategy):
    strategy_type = RerankingStrategyType.AUTOCAST_FP16

    def execute(self, model, query, texts, batch_size, span) -> list[float]:
        pairs = [[query, text] for text in texts]
        use_cuda = str(model.device).startswith("cuda") and torch.cuda.is_available()
        device_type = torch.device(model.device).type
        with torch.autocast(
            device_type=device_type,
            dtype=torch.float16,
            enabled=use_cuda,
        ):
            scores = model.predict(
                pairs,
                batch_size=batch_size,
            )
        span.set_attribute("reranking.autocast.enabled", use_cuda)
        return scores.tolist()
```

  </div>
</details>

<details class="sql-evidence">
  <summary>여섯 설정과 고정 입력</summary>
  <div class="sql-evidence__content" markdown="1">

두 전략과 세 배치 크기를 조합해 설정 6개를 만들고, FP32·배치 32를 기준으로 둔다.

```python
# Evaluation/tracks/search/batch_experiment.py
BASELINE = BatchSetting(RerankingStrategyType.CROSS_ENCODER_PREDICT, 32)
SETTINGS = tuple(
    BatchSetting(strategy, batch_size)
    for strategy in (RerankingStrategyType.CROSS_ENCODER_PREDICT, RerankingStrategyType.AUTOCAST_FP16)
    for batch_size in (8, 16, 32)
)
```

`FixedCandidateCollector`는 문항마다 질의를 임베딩해 pgvector에서 후보 30개를 한 번만 가져오고, 질문·후보 ID·본문을 `frozen_candidates.jsonl`에 저장한다. 이후 모든 설정은 이 파일의 같은 입력으로 실행한다.

  </div>
</details>

<details class="sql-evidence">
  <summary>시간 측정과 입력 검사</summary>
  <div class="sql-evidence__content" markdown="1">

GPU 연산은 비동기라 끝나기 전에 시간이 찍힐 수 있다. 그래서 측정 구간의 시작과 끝에서만 CUDA 동기화를 하고 그 사이 시간을 잰다. 동시에 모델에 들어간 텐서를 가로채 실제 배치 크기, 패딩 길이, 쌍별 토큰 해시를 기록한다.

```python
with capture_preprocessing() as captured:
    torch.cuda.synchronize()
    started_at = time.perf_counter()
    scores = strategy.execute(
        reranker.model,
        frozen["query"],
        frozen["texts"],
        setting.batch_size,
        span,
    )
    torch.cuda.synchronize()
    elapsed_ms = (time.perf_counter() - started_at) * 1000
signature = input_signature(captured)
```

설정 실행 순서는 문항마다 한 칸씩 돌려 특정 설정이 항상 먼저 실행되지 않게 했다.

```python
for index, query in enumerate(frozen):
    offset = index % len(SETTINGS)
    rotated = SETTINGS[offset:] + SETTINGS[:offset]
    for setting in rotated:
        rows.append(runner.execute(query, setting, ExperimentPhase.SCREENING, 0))
```

  </div>
</details>

<details class="sql-evidence">
  <summary>품질 기준과 설정 선택</summary>
  <div class="sql-evidence__content" markdown="1">

설정마다 기준 설정과 문항별 지표를 비교해, 하나라도 떨어진 문항이 있거나 입력 토큰이 다르면 탈락시킨다. 남은 설정 중 p95가 가장 낮고, 같으면 p50이 낮은 설정을 고른다.

```python
"quality_gate_passed": not token_mismatches and not any(degradations.values()),

eligible = [setting for setting in SETTINGS if summaries[setting.name]["quality_gate_passed"]]
selected = min(
    eligible,
    key=lambda setting: (summaries[setting.name]["latency"]["p95_ms"], summaries[setting.name]["latency"]["p50_ms"]),
)
```

순위 지표는 `Evaluation/common/metrics/ranking.py`에서 계산한다. NDCG는 사람이 매긴 0~3점 관련도를 `2^점수 − 1`의 이득으로 써서, 3점 장소가 위에 있을수록 높은 값을 준다.

  </div>
</details>

## 검색 API에 적용해 다시 측정했다
{: #result }

선택한 설정을 검색 서버 환경 변수로 적용했다.

```dotenv
RERANK_EXECUTION_STRATEGY=autocast_fp16
RERANK_BATCH_SIZE=8
RERANK_DIAGNOSTICS_ENABLED=false
```

같은 80문항을 다시 호출하자 요청 80개가 모두 HTTP 200으로 응답했다. LangSmith의 리랭커 span 80개에도 `autocast_fp16`, 배치 8, CUDA FP16 autocast 설정이 기록됐다.

| 리랭킹 요청 · 80건 | 적용 전 · 진단 모드 FP32 · 배치 32 | 적용 후 · FP16 · 배치 8 |
| --- | ---: | ---: |
| 리랭커 연산 평균 | 7.347초 | **0.524초** |
| 리랭커 연산 p50 | 4.546초 | **0.558초** |
| 리랭커 연산 p95 | 27.617초 | **0.756초** |
| 검색 API 평균 | 8.398초 | 1.607초 |
| 검색 API p95 | 28.682초 | 2.015초 |

리랭커 연산은 평균 7.347초에서 0.524초로, p95는 27.617초에서 0.756초로 줄었다. 고정 입력 실험의 FP16·배치 8 결과(평균 0.547초, p95 0.717초)와 거의 같은 값이 실제 서비스 요청에서도 나왔다. 조건을 모두 표현할 수 있는 60문항의 품질 지표는 적용 전과 같았다.

적용 후 검색 API는 평균 1.607초였다. 이 가운데 처리 파이프라인은 0.577초이고, 나머지 약 1.0초는 Spring과 FastAPI 사이의 Kafka 메시지 전달과 대기 시간이다. 의미 검색만 쓸 때 평균 1.011초가 걸리는 것도 대부분 이 구간 때문이다. 전송 방식은 서비스 상황에 맞춰 고를 부분으로, 사용자가 적고 빠른 응답이 중요하면 Kafka 대신 gRPC로 직접 호출할 수 있다. 그래서 리랭커 개선은 전송 구간을 뺀 리랭커 연산 시간으로 판단했다. 이 전송 구간의 비용은 [AI 서버와 Spring 서버의 역할 분리]({{ '/projects/travelmate/architecture/ai-spring-responsibilities/' | relative_url }})에서 구조와 함께 정리했다.

모든 측정은 2026년 10월 26일 로컬 Docker로 실행한 Spring·Kafka·FastAPI와 RTX 4050 Laptop GPU에서 진행했다.
