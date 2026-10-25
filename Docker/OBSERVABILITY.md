# 검색 요청 LangSmith 추적

검색 요청은 OpenTelemetry trace로 기록하고 LangSmith의 `travelmate-search-observability` 프로젝트에 전송합니다. Spring 서버와 FastAPI는 W3C `traceparent`로 연결되므로 API 요청과 임베딩·DB·리랭킹 하위 작업이 한 trace에 나타납니다.

## Span 구성

아래는 기존 HTTP 호출 경로의 trace입니다. 현재 CQRS/Kafka 검색 경로와 리랭커 상세 계측은 [RERANKING_DIAGNOSTICS.md](RERANKING_DIAGNOSTICS.md)를 참고하세요.

```text
travelmate.search                 Spring 검색 API 전체
├── embedding.http                Spring → FastAPI 호출 왕복시간
│   └── POST /embed               FastAPI 임베딩 endpoint 처리시간
│       └── embedding.model_inference
├── database.pgvector_search      PostgreSQL 벡터 검색시간
└── reranking.http                Spring → FastAPI 호출 왕복시간
    └── POST /rerank              FastAPI 리랭킹 endpoint 처리시간
        └── reranking.model_inference
```

`embedding.http`와 `reranking.http`에는 서비스 간 호출과 네트워크 왕복이 포함됩니다. FastAPI 처리 span과 비교하면 모델 처리시간을 분리해 볼 수 있습니다. 두 시간의 차이는 네트워크 외에도 서버 대기와 직렬화 비용을 포함하므로 순수 네트워크 시간으로 단정할 수 없습니다. DB span은 SQL 실행 전체를 측정합니다. 전체 API span에는 검색 처리와 응답 작성이 포함됩니다.

## 실행 설정

저장소 루트 `.env`의 `LANGCHAIN_API_KEY`를 Docker 런타임 환경으로 전달합니다. 키 값은 이미지에 포함되지 않고, 추적 입력에도 저장하지 않습니다. 계측 코드를 바꾼 뒤 이미지를 다시 빌드하고 서비스를 재시작합니다.

```bash
bash Docker/stack-up.sh --build
bash Docker/stack-wait.sh
```

`LANGSMITH_PROJECT`를 지정하면 프로젝트 이름을 바꿀 수 있습니다. 기본 프로젝트는 `travelmate-search-observability`입니다. `LANGSMITH_ENDPOINT`의 기본값은 `https://api.smith.langchain.com`입니다.

## 로컬 GPU 리랭킹

임베딩과 리랭커는 CUDA를 우선 선택하며, CUDA를 사용할 수 없으면 CPU로 전환합니다. 기본 실행은 호스트의 NVIDIA GPU를 감지해 컨테이너에 전달하고, GPU 연결에 실패하면 CPU로 재시도합니다.

```bash
bash Docker/stack-up.sh --build
bash Docker/stack-wait.sh
```

`/health` 응답은 모델별 선택 장치와 GPU 이름을 표시합니다. LangSmith의 `embedding.model_inference`와 `reranking.model_inference` span에도 실제 장치가 기록되며, span 길이로 각 모델의 추론 시간을 비교할 수 있습니다. `bash Docker/stack-up.sh --build --gpu`는 GPU 연결을 강제하고, `bash Docker/stack-up.sh --build --cpu`는 CPU 실행을 고정합니다.

LLM은 Spring 컨테이너가 별도로 실행 중인 Ollama 서버에 요청합니다. Ollama가 서버의 GPU를 자동 선택하며, 실제 할당은 Ollama가 실행되는 서버에서 `ollama ps`의 `PROCESSOR` 열로 확인합니다.

현재 CQRS 검색 span에는 검색어와 필터, 모델·장치, 후보 개수와 단계별 시간이 기록됩니다. 리랭커에는 입력 본문의 길이와 해시도 기록합니다. 장소 설명 전문과 임베딩 벡터는 trace에 기록하지 않습니다.
