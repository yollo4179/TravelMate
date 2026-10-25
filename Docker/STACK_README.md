# TravelMate Docker 개발 스택

기존 PostgreSQL Compose에 Spring Boot, FastAPI embedding, Redis를 더하는 개발용 구성입니다. Java는 Docker 다단계 빌드에서 컴파일하며, 임베딩과 리랭커는 CUDA를 우선 사용하고 사용할 수 없으면 CPU로 전환합니다.

Kafka KRaft 브로커·세 토픽·Kafka UI와 FastAPI 전용 PostgreSQL을 앱 스택과 함께 시작합니다. UI 기본 주소는 `http://localhost:8989`입니다. 관광지 변경 인덱싱과 Kafka 추천 요청·완료 흐름이 앱에 연결됩니다.

## 실행과 상태

저장소 루트에서:

```bash
bash Docker/stack-up.sh
bash Docker/stack-status.sh
bash Docker/stack-wait.sh
python3 Docker/stack-smoke.py
```

스크립트 준비에는 Bash·Docker Compose v2.24 이상·BuildKit이 필요합니다. **기본 실행·상태 확인에는 호스트 Python/JDK가 필요하지 않습니다.** 설정 생성은 `python:3.12-slim-bookworm` 임시 컨테이너에서 수행하며, 준비 확인은 Bash로 처리합니다. 별도 기능 검증인 `stack-smoke.py`를 실행할 때만 호스트 Python3가 필요합니다. 최초 빌드와 BGE-M3 모델 다운로드에는 네트워크와 디스크 공간이 필요합니다.

Windows에서는 Docker Desktop을 Linux containers 모드로 시작한 뒤 Git Bash에서 저장소 루트로 이동해 실행합니다.

```bash
cd /c/ssafy/Travelmate
bash Docker/stack-up.sh && bash Docker/stack-wait.sh
```

Git Bash에서는 Docker에 전달할 호스트 경로를 `cygpath`로 변환하고, `/stack` 같은 컨테이너 경로의 MSYS 자동 변환을 끕니다. `.gitattributes`는 실행 스크립트의 LF 줄바꿈을 유지합니다. Windows 실기기 실행은 별도로 확인해야 합니다. `Python was not found` 메시지를 해결하기 위해 Microsoft Store Python을 설치할 필요는 없습니다.

`stack-up.sh`는 컨테이너 시작까지 수행합니다. `stack-wait.sh`는 기본 600초 동안 앱·Kafka·두 PostgreSQL 등 일곱 서비스를 healthy 상태로 확인하며, 실패하면 nonzero로 종료합니다. `STACK_WAIT_TIMEOUT`으로 대기시간을 조정할 수 있습니다. 모델 다운로드 실패가 무한 재시도로 이어지지 않도록 embedding은 최대 3회 자동 재시작합니다.

일반 시작에서는 기존 이미지를 재사용하고, 누락된 이미지만 빌드합니다. 앱 소스·Dockerfile·라이브러리를 변경한 뒤에는 `bash Docker/stack-up.sh --build`로 다시 빌드하세요. FastAPI 설치는 Docker의 VFS 저장 드라이버에서도 큰 라이브러리 레이어가 불필요하게 여러 번 복제되지 않도록 최종 단일 RUN에 모았습니다.

| 서비스 | 컨테이너 | 접근·헬스체크 |
|---|---|---|
| Spring Boot | travelmate-server | 호스트 8080 → 컨테이너 8080, `/v3/api-docs` HTTP 2xx |
| FastAPI | travelmate-embedding | 호스트 8000 → 컨테이너 8000, `/health`의 status=ok, dim=1024 |
| PostgreSQL/pgvector | travel-postgres | 기존 5432, pg_isready + SQL SELECT 1 |
| Redis | travelmate-redis | Compose 네트워크 내부 6379, redis-cli PING |

Redis의 `ports: !reset []`는 기본 Compose의 호스트 포트 공개를 제거합니다(Compose v2.24 이상 필요). Spring/FastAPI 포트는 기본적으로 호스트 loopback에만 게시합니다. PostgreSQL 포트 공개 범위는 기존 Compose 설정을 따릅니다. `SERVER_PORT`, `EMBEDDING_PORT` 환경변수로 호스트 포트를 바꿀 수 있습니다. 같은 포트에 호스트 Spring/FastAPI를 동시에 실행하지 마세요.

Spring health는 HTTP 서버 준비 상태이며 전체 AI 기능의 성공을 보장하지 않습니다. DB·Redis·모델은 각각 독립적인 healthcheck를 가집니다. Spring은 DB와 Redis가 healthy일 때 시작하며 FastAPI 프로세스 시작만 기다립니다. 모델 다운로드가 막혀도 회원/방 기능은 독립적으로 검증할 수 있습니다. AI를 쓰기 전에는 FastAPI healthy와 실제 `/embed` 성공을 모두 확인해야 합니다.

## 데이터와 설정

- Compose 프로젝트 이름은 `docker`로 고정해 기존 `docker_pgdata`를 재사용합니다. **`down -v`를 실행하면 DB·모델·Redis 데이터가 삭제됩니다.** 정상 종료에는 아래 stop 명령을 사용합니다.
- 모델은 `docker_stack_models`, Redis는 `docker_stack_redis` 볼륨에 보존합니다. BGE-M3 파일은 최초 한 번 다운로드하며 모델·라이브러리 버전 변경 시 캐시 호환성을 확인합니다.
- BGE-M3 revision은 `5617a9f61b028005a4858fdac845db406aefb181`로 고정합니다. 원본 Hugging Face LFS 메타데이터의 SHA-256 `b5e0ce3470abf5ef3831aa1bd5553b486803e83251590ab7ff35a117cf6aad38`을 모델 가중치와 대조한 뒤 서버를 시작합니다. 다른 모델/버전을 쓰려면 해당 원본의 revision·checksum을 검증해 함께 변경합니다.
- `Docker/build/stack`은 기존 `.gitignore`의 build 규칙으로 제외됩니다. runtime.env에는 로컬 JWT 키를 최초 1회 생성하고 파일을 0600으로 보존합니다. 실제 키를 출력하거나 Git에 추가하지 마세요.
- DB는 저장소에 정의된 로컬 개발 계정을 사용합니다. 컨테이너 Spring은 `postgres`, `redis`, `embedding` 서비스 DNS를 사용합니다. 로컬 Redis에는 TLS를 사용하지 않습니다.
- 초기 SQL의 `users.provider_id` 누락은 별도 idempotent ALTER로 로컬 DB에만 보완합니다. 기존 테이블·행을 삭제하거나 초기화하지 않습니다.
- 기존 단독 `travel-redis` 컨테이너는 삭제하지 않습니다. 새 스택 Spring은 영속 볼륨을 가진 `travelmate-redis`를 사용합니다.

## 클라우드 네트워크와 신뢰 저장소

일반 로컬 PC에서는 별도 CA 파일이나 `SSL_CERT_FILE` 설정이 필요하지 않습니다. 임시 설정 컨테이너의 표준 Linux CA 묶음을 로컬 상태 폴더로 복사해 사용합니다. 사내/클라우드 프록시의 별도 신뢰 인증서가 필요한 경우에만 `SSL_CERT_FILE`에 유효한 CA 묶음 경로를 지정하세요. 잘못 지정된 값은 오류로 처리하며 TLS 검증을 끄지 않습니다. 이 파일은 외부 HTTPS 검증용이며 Nginx나 서버 HTTPS 설정이 아닙니다.

빌드는 기존 HTTP(S) 프록시를 사용합니다. 클라우드 프록시 DNS가 컨테이너에서 보이지 않는 경우 스크립트가 현재 프록시의 IP를 build/runtime extra_hosts에 연결합니다. Linux 클라우드에서 프록시가 설정된 경우에만 빌드의 host network를 사용하며, 일반 Docker Desktop 빌드에서는 요구하지 않습니다. egress 정책을 우회하지 않습니다. CA bundle과 Java truststore는 BuildKit secret으로 전달하며 TLS/서명/해시 검증을 끄지 않습니다. 공개 CA 파일만 FastAPI에 읽기 전용 마운트합니다.

Docker 내부 서비스 이름은 대·소문자 `NO_PROXY`/`no_proxy` 양쪽에 명시합니다. 이를 누락하면 내부 `http://embedding:8000` 요청이 클라우드 외부 프록시로 향해 403을 받을 수 있습니다. 외부 모델 다운로드는 기존 프록시를 계속 사용합니다.

BGE-M3 원본 다운로드에는 `huggingface.co`와 대용량 파일 전달 도메인 접근이 필요합니다. 이번 모델 파일에서 `us.aws.cdn.hf.co` redirect를 관찰했으며, 전달 경로에 따라 `cas-bridge.xethub.hf.co`도 사용됩니다. 현재 정책에서 거부된다면 환경 설정에서 해당 도메인을 검토·허용한 후 컨테이너를 다시 시작하세요. 공개 모델을 받기 위한 개인 토큰을 불필요하게 입력하지 마세요. 다른 redirect host가 관찰되면 그 목적지를 확인한 뒤 허용 범위를 추가합니다.

`stack-up.sh`는 기본적으로 NVIDIA GPU가 감지되면 컨테이너에 전달하고, GPU를 연결할 수 없으면 CPU 모드로 스택을 시작합니다. `/health` 응답의 `embedding_device`, `reranker_device`, `cuda_available`, `gpu_name`에서 실제 선택된 장치를 확인할 수 있습니다. GPU를 명시적으로 요청하려면 `--gpu`, CPU 실행을 고정하려면 `--cpu`를 지정합니다. GPU 실행에는 CUDA PyTorch 이미지와 Docker의 NVIDIA GPU 지원이 필요합니다.

## 수동 Compose 명령

먼저 `stack-up.sh`로 로컬 설정을 만든 후:

```bash
export STACK_STATE_DIR="$PWD/Docker/build/stack"
docker compose --project-name docker \
  --env-file "$STACK_STATE_DIR/runtime.env" \
  -f Docker/docker-compose.yml \
  -f Docker/docker-compose.stack.yml \
  -f "$STACK_STATE_DIR/proxy.compose.yml" ps
```

같은 prefix로 `logs --tail 100 server embedding`, `restart server embedding`, `stop`을 사용합니다. 로그를 공유할 때 토큰·대화·환경변수 값이 포함되지 않았는지 확인하세요. `docker compose config`는 런타임 비밀값을 펼칠 수 있으므로 검증에는 `config --quiet`를 사용합니다.

## 기능 검증

```bash
curl -fsS http://127.0.0.1:8080/v3/api-docs -o /tmp/travelmate-openapi.json
curl -fsS http://127.0.0.1:8000/health
curl -fsS -H 'Content-Type: application/json' \
  -d '{"texts":["여행지 산책", "문화유산 관광"]}' \
  http://127.0.0.1:8000/embed -o /tmp/travelmate-embeddings.json
```

각 임베딩은 1024차원이어야 하며 유한한 값과 대략 1인 L2 norm을 확인합니다. FastAPI healthcheck는 모델 로딩 완료를 확인하지만 추론 smoke를 대신하지 않습니다.

`stack-smoke.py`는 실제 BGE-M3 추론·컨테이너 간 서비스 DNS·가입/로그인/JWT/Redis 흐름을 검증합니다. 임시 가입 사용자만 생성하고 해당 DB 행을 정리합니다. 토큰·벡터 원문은 출력하지 않습니다. 간단한 의미 유사도 비교는 기동 검증이며 RAG 품질 벤치마크가 아닙니다.

Kakao/TourAPI 키는 필요할 때 환경 설정으로 주입합니다. 이 구성은 Ollama 모델을 별도 다운로드/기동하지 않습니다. LLM 계획 생성까지 실행하려면 `OLLAMA_BASE_URL`에 실제 접근 가능한 Ollama 서버를 지정하고 모델을 준비해야 합니다. 관광 데이터 수집·RAG 품질 평가도 별도 작업입니다.

## 스크립트 회귀 검증

개발자가 Python3를 사용할 수 있는 환경에서:

```bash
python3 -m unittest discover -s Docker/tests -v
```

CA 기본값·사용자 지정 CA·기존 JWT 유지·프록시 설정·호스트 Python 미호출·공백이 있는 경로·Git Bash 경로 변환 모의·헬스체크 실패 처리를 검증합니다. 모의 테스트가 실제 Windows Docker Desktop 실행 검증을 대신하지는 않습니다.
