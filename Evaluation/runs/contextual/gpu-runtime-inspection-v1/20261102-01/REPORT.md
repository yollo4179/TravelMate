# GPU 점유 확인과 사용자 지시에 따른 Gemma 종료

2026-11-02 KST. 코드 기준 `c3cdba7b`. 추가 추론·검색 없이 프로세스·포트·기존 로그·모델 파일 헤더·컨테이너 메타데이터만 확인했다. 최초 점검은 읽기 전용으로 진행했고, 이후 사용자의 명시적 **“젬마 꺼줘”** 지시에 따라 Gemma와 해당 감시 프로세스만 종료했다.

## 확인한 두 llama-server

두 프로세스 모두 Qwen이 아닌 **Gemma 동일 모델의 중복 기동**이었다.

| 항목 | 첫 프로세스 | 두 번째 프로세스 |
| --- | --- | --- |
| PID | 46812 | 23124 |
| 생성 시각 | 12:35:25 | 12:35:29 |
| 실행 파일 | `C:\llm\llama.cpp\llama-server.exe` | 동일 |
| 모델 | `C:\llm\models\gemma-4-E2B-it-Q4_K_M.gguf` | 동일 |
| projector | `C:\llm\models\mmproj-gemma-4-E2B-it-BF16.gguf` | 동일 |
| alias | `google/gemma-4-e2b` | 동일 |
| 명령 옵션 | `-ngl 99 -c 16384 --parallel 4 --host 127.0.0.1 --port 1234` | 동일 |
| 부모 PID | 31980, 점검 시 이미 부재 | 29040, PowerShell `C:\llm\laptop\start-all.ps1` |
| 점검 시 Windows 수신 소켓 | `127.0.0.1:1234` 소유 | 해당 PID 소유 수신 소켓 미관측 |

`C:\llm\logs\start-all-20261102.log`의 6·8행이 각각 위 PID와 대응하는 `llama-server-20261102-123525.log`, `...123529.log`를 연결한다. 두 로그 모두 모델/projector 로드와 1234 listen 메시지를 기록했다. 따라서 두 번째 프로세스를 단순히 모델 로드 실패나 무사용 프로세스로 단정하지 않는다. 실제 점검 시 endpoint 소유자는 첫 PID였고 두 번째의 현재 요청 처리 여부는 확인하지 못했다.

사용 서비스는 시작 스크립트·scheduler.xml 설명에 명시된 **“LLM 배틀” 노트북 텍스트 서버와 EC2 역방향 SSH 터널**이다. scheduler.xml은 `S15P31D105 laptop/start-all.ps1`를 언급한다. 외부 요청을 누가 실제 소비했는지까지 증명한 것은 아니다. 현재 TravelMate의 Ollama 주소 `11434`와 이 서비스의 `1234`는 다르다. 원격 주소·SSH 인증 자료는 게시하지 않는다.

부모 PowerShell의 상위 PID 46292도 후속 조회 시 부재했다. 실제 등록된 ScheduledTask 중 해당 start-all 경로가 action인 항목은 조회되지 않았다. 설치 스크립트에 로그온 자동 시작 등록 방법이 있다는 사실을 현재 활성 작업 등록의 증거로 바꾸지 않는다.

## 수행한 종료와 확인

사용자 지시 후 실행 파일·GGUF 명령을 재확인하고 **46812·23124**, 해당 자동 재시작 감시 PowerShell **29040**만 중지했다. 시작 스크립트 자체는 실행하지 않았다. 이 스크립트는 stale 프로세스 정리와 자동 재기동을 포함하므로 실행하면 다른 프로세스까지 건드릴 수 있기 때문이다.

| 확인 | 종료 전 | 종료 후 |
| --- | --- | --- |
| GPU | RTX 4050 Laptop, total 6,141MiB | 동일 |
| nvidia-smi GPU used | 5,174MiB | 0MiB |
| nvidia-smi GPU free | 751MiB | **5,924MiB, 약 5.79GiB** |
| 해당 Gemma 프로세스 | 2개 | **0개** |
| 1234 수신 | PID 46812 | **없음** |
| Ollama | PID 18452, 11434 | **유지** |
| 평가 Spring | PID 16528, 18080 | **유지** |

직후 CIM 조회에는 종료된 PID가 잠시 남았지만, 후속 Get-Process와 CIM 조회에서 없어졌고 1234 포트와 GPU 점유 해제를 확인했다. nvidia-smi의 프로세스별 메모리는 `[N/A]`여서 5,174MiB를 두 PID에 임의 분배하지 않는다. 표의 total/used/free는 드라이버가 보고한 값을 그대로 기록했으며 합을 맞추기 위해 수정하지 않았다.

Ollama `GET /api/ps`는 `models=[]`였다. Qwen을 이번 작업에서 새로 로드하지 않았다. 영구 시작 설정·작업 등록·원격 터널 설정도 변경하지 않았다. 로그인이나 수동 시작 스크립트 실행으로 서비스가 다시 시작될 가능성을 영구 차단했다고 표시하지 않는다.

## Qwen·임베딩·리랭커의 6GB 메모리 구성

평가 FastAPI `GET /health`는 embedding/reranker 모두 CPU, `cuda_available=false`, 원문 연결 `post-retrieval-field-v1`을 보고했다. 컨테이너 GPU DeviceRequests도 null이다. 기존 검색 모델·정밀도·batch 8을 변경하지 않았다.

캐시의 safetensors **헤더만** 읽고 weight tensor를 로드하거나 forward를 호출하지 않았다.

| 자료 | 확인한 용량·조건 | 의미 |
| --- | --- | --- |
| BGE-M3 safetensors | F32 tensor 2,271,019,008 bytes, 약 2.115GiB | 캐시 revision `9a0624…`의 가중치 payload |
| BGE-M3 다른 캐시 revision | `5617a9…`, float32 config, pytorch_model.bin 2,271,145,830 bytes | 두 revision의 내용이 같다고 가정하지 않음 |
| BGE reranker v2 M3 | F32 tensor 2,271,023,108 bytes, 약 2.115GiB | cache revision `953dc6…`의 가중치 payload |
| 두 BGE의 FP32 weight 합 | 약 **4.23GiB** | activation·CUDA context·workspace 별도 |
| Qwen 이전 fit 로그의 전체 GPU 예상 | **5,907MiB, 약 5.77GiB** | context 8,192에서의 기존 예상값. 이번 새 로드 실측 아님 |

따라서 **현재 FP32 BGE 두 개와 Qwen을 모두 전체 GPU 상주시키는 구성은 6GB에 들어가지 않는다.** 기존 Qwen 예상치와 두 BGE weight만 합쳐도 약 10GiB이며 BGE 실행 workspace는 여기에 추가된다. BGE를 FP16으로 바꾸는 가정에서도 weight 합은 약 2.12GiB이고 Qwen과 합계 약 7.88GiB다. 이것은 dtype 크기에 따른 산술이며 FP16 동작·품질·실제 peak memory를 검증한 결과가 아니다. 정밀도를 실제로 변경하지 않았다.

| 구성 | GPU | CPU | 판단 |
| --- | --- | --- | --- |
| **다음 2문항용 권장** | Qwen의 기존 자동 fit에 따른 부분 적재 | BGE-M3·리랭커 기존 FP32 | 현재 CPU 검색 조건을 유지하고 Gemma 점유만 제거한 상태에서 도구·출력 수정 확인 |
| 추후 검색 지연 별도 실험안 | 리랭커 FP32 + 남은 공간 내 Qwen 부분 적재 | 임베딩 + 더 많은 Qwen 계층 | 리랭커 weight 약 2.12GiB 외 activation 필요. Qwen 여유 감소와 전체 지연 교환관계 미검증 |
| 세 모델 모두 전체 GPU | 세 모델 전부 | 없음 가정 | FP32는 불가. FP16 BGE 가정으로도 부족. 강제하지 않음 |

현재 free 5,924MiB와 기존 Qwen 전체 GPU 예상 5,907MiB의 차이는 고작 약 17MiB다. 그러므로 Gemma 종료만으로 Qwen의 전체 GPU 적재를 보장할 수 없다. Ollama가 기존 fit 정책에서 남기는 여유를 존중하고 CPU 분할을 허용해야 한다. `num_gpu`·`-ngl` 강제 설정이나 context 증가는 적용하지 않았다. 실제 적재 계층 수는 다음 승인된 정상 로드의 로그로 확인해야 하며 지금 미리 만들지 않는다.

호스트 RAM은 total 33,044,884KiB, free 7,721,212KiB(약 7.36GiB)로 관측됐다. 평가 검색 컨테이너는 기존 6GiB 제한이고 docker stats working-set 표시는 약 1.181GiB였다. 이는 파일 캐시·공유/mmap·실제 peak가 구분되는 컨테이너 회계값이며 두 BGE의 weight 합이나 다음 Qwen 적재 peak RAM과 같지 않다. 모델 추가 적재 때의 호스트/컨테이너 peak 여유를 보장하지 않는다. RAM 한도도 변경하지 않았다.

## 기존 2문항 재시험 환경안

`c3cdba7b` 계약·출력 수정의 재시험은 **Gemma가 꺼진 현재 Windows Ollama + 기존 CPU 검색 평가 환경**을 권장한다.

- `qwen3:8b`와 검증한 Windows 상주 토크나이저·템플릿을 유지한다. context 8,192, 출력 예약 1,536, 자동 GPU fit 유지.
- 임베딩·리랭커는 기존 CPU·FP32·batch 8, 동일 corpus·원문·벡터·검색 필터·상한 유지.
- 기존 `palaces-01`, `palaces-03` 각 1회·순차·재시도 없음, Qwen 최대 4회·검색 최대 2회라는 [기존 제안](../../search-tool-contract-output-v1/20261102-01/next-execution-proposal.json)을 유지한다. 이번 작업에서 실행하지 않았다.
- 현재 살아 있는 평가 Spring PID 16528은 수정 전 JAR다. `c3cdba7b` 새 JAR는 이전 작업에서 빌드만 했으며 이번에도 서버를 교체하지 않았다. 실제 실행 전에 새 버전 배포 바인딩과 2문항 수집 범위를 일치시켜야 한다.
- 현재 Qwen은 미적재 상태다. 다음 실행에서 자동 fit 결과·실제 GPU/CPU 배치·단계별 시간을 기록한다. 이전 대비 메모리 경쟁 상태가 다르므로 이를 고정 하드웨어 성능 비교라고 표시하지 않는다.
- CPU 리랭킹 약 112초는 그대로 남을 수 있다. Gemma 종료나 출력 지침 수정이 전체 지연을 해결했다고 주장하지 않는다.

이 점검에서는 추가 모델 추론·검색·judge·유료 호출을 하지 않았고, 모델·context·정밀도·검색 설정·운영 DB를 변경하지 않았다. 기존 서비스 종료 금지 범위는 지켰으며 이후 사용자가 명시적으로 허용한 Gemma 및 그 재시작 감시만 종료했다.
