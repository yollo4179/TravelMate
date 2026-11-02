# 평가 검색의 GPU 연결

2026-11-02, 기준 `d26c995d`. 사용자의 GPU 적용 지시에 따라 평가 FastAPI `tm-b-eval-search`만 재생성했다. 현재 임베딩과 리랭커 모두 GPU에 적재됐다. **검색·리랭킹·임베딩 추론 및 Qwen 호출은 0회**이며 속도 개선을 실측했다고 표시하지 않는다.

| 항목 | 변경 전 | 변경 후 확인 |
|---|---|---|
| GPU 연결 | Docker DeviceRequests 없음, CUDA unavailable | Compose `gpus: all`, CUDA available |
| 임베딩 | CPU | 실제 파라미터 `cuda:0`, `torch.float32` |
| 리랭커 | CPU | 실제 파라미터 `cuda:0`, `torch.float32` |
| 리랭커 | BAAI/bge-reranker-v2-m3 | 모델 유지 |
| 임베딩 | BAAI/bge-m3 | 모델 유지 |
| 전략 | cross_encoder_predict | 유지; autocast_fp16으로 전환하지 않음 |
| 리랭커 배치 | 설정 8, predict에 미전달 → 기본값 32 | predict에 8 명시 전달 |
| GPU 메모리 | Qwen 미적재 상태에서 초기 used 0MiB | 두 모델 로드 후 used 4,431MiB, free 1,494MiB |
| Qwen | Ollama `/api/ps`의 적재 목록 비어 있음 | 재적재·추론·강제 GPU 전체 적재 없음 |

현재 실제 `/health` 확인값과 변경 전 확인값은 `before.json`, `after-health.json`에 보존했다. `reranker_inference_count=0`이다. 메모리 값은 로드 후 시점 관측이며 다음 검색의 activation peak나 OOM 부재를 보장하지 않는다. Qwen을 이후 GPU에 올리는 경우 당시 가용량과 실제 적재 계층을 새로 확인해야 한다.

## 적용 방법

기본 CPU 평가 Compose는 보존하고 `Evaluation/environments/b-plan/compose.reranker-gpu.yaml` overlay를 추가했다. 이름은 최초 리랭커 적용 요청에서 시작했으며 최종 설정은 임베딩·리랭커 모두 CUDA다.

```powershell
docker compose --env-file Server/TravelMate/build/b-evaluation/runtime.env -f Evaluation/environments/b-plan/compose.yaml -f Evaluation/environments/b-plan/compose.reranker-gpu.yaml up -d --no-deps --pull never --no-build search
```

기존 `Docker/embedding-entrypoint.py`를 재사용해 장치 환경변수를 실제 모델 생성에 적용한다. HF offline과 읽기 전용 모델 캐시는 유지한다. GPU를 노출하는 것만으로 성공으로 표시하지 않고 실제 파라미터 장치·dtype을 `/health`에서 확인했다. 위 명령은 검색·추론을 요청하지 않는다. 소스 반영 재시작이 필요할 때만 `--force-recreate`를 추가한다.

재생성 전 대기 index/search/result outbox 합과 Spring 미발행 outbox가 모두 0임을 확인했다. 기존 DB·Kafka·Spring·Gemma·Ollama 서비스 설정 및 이전 관측 파일은 덮어쓰지 않았다. 적재된 Qwen이 없었으므로 이번에 언로드 API를 호출할 필요도 없었다. 새 모델 파일 다운로드·새 임베딩 생성도 하지 않았다.

## 배치 전달 수정과 검증

CrossEncoderPredict/InstrumentedPredict/AutocastFp16 세 전략에서 `batch_size`를 받으면서 버리고 있었다. 이를 `model.predict(pairs, batch_size=batch_size)`로 전달하도록 수정했다. CPU 실행 보고서의 `30 pairs / 4 batches`는 설정값 8에 따른 계측 수치였으며 실제 predict의 배치 전달을 증명하지 않았다. 과거 원본 로그·보고서는 수정하지 않고 여기서 차이를 명시한다.

실제 모델을 호출하지 않는 mock 검사 1개가 세 전략 모두 배치 8을 전달하는지 확인했고 통과했다.

```powershell
docker exec tm-b-eval-search python -m unittest discover -s /workspace/embedding-server/tests -p test_reranker_batch_contract.py -v
```

이 수정은 배치 인자 전달 검사이며 GPU 추론 성능 검사가 아니다. 현재 `/health`는 설정/전달 배치 8과 라이브러리 기본 배치 32를 구분해 보여준다.

과거 **112.268초는 CPU 실행 기록**이다. GPU 전환과 배치 전달 수정 이후 처리 시간·순위는 아직 미측정이며, 과거 GPU autocast_fp16 기록과의 동등성도 검증하지 않았다. 다음 승인된 검색에서 임베딩·리랭킹·전체 검색 시간을 각각 관측한다. OpenAI 공급자 변경은 별도 보고서의 준비 단계이며 아직 실행하거나 Spring에 배포하지 않았다.
