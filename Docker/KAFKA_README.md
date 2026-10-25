# Kafka와 웹 GUI 실행

[Docker 스택](STACK_README.md) · [CQRS 구조도](../docs/architecture/fastapi-place-recommendation.md) · [이벤트 명세](../docs/specifications/fastapi-place-recommendation.md)

Apache Kafka KRaft 브로커와 요청하신 Provectus Kafka UI를 추가한 로컬 개발용 구성입니다. ZooKeeper는 사용하지 않습니다. 기본 앱 스택과 별도로 시작할 수 있으며, 같은 Compose 프로젝트 `docker`를 사용해 기존 Spring·FastAPI 컨테이너와 내부 네트워크를 공유합니다.

## 시작

저장소 루트에서 Docker Desktop을 Linux containers 모드로 실행한 뒤:

```bash
docker compose -p docker -f Docker/docker-compose.kafka.yml up -d --wait
```

브라우저에서 **http://localhost:8989** 를 엽니다. Spring의 기존 8080과 겹치지 않습니다. `travelmate-local-kraft` 클러스터의 Topics에서 `travelmate.place-changes.v1`을 확인할 수 있습니다.

`kafka-init`은 토픽을 만든 뒤 정상 종료하는 일회성 서비스입니다. `Exited (0)`은 실패가 아닙니다. 브로커 healthy와 토픽 초기화 성공 후 UI를 시작합니다. `--wait`는 브로커와 UI의 healthcheck 준비를 기다립니다.

이미 앱 스택을 띄웠다면 같은 프로젝트의 다른 컨테이너가 orphan으로 표시될 수 있습니다. 이 명령은 해당 컨테이너를 삭제하지 않습니다. 기존 PostgreSQL 볼륨이나 앱 설정을 초기화할 필요가 없습니다.

## 연결 주소

| 사용하는 위치 | 주소 |
|---|---|
| 브라우저의 Kafka UI | `http://localhost:8989` |
| 같은 프로젝트의 Spring·FastAPI·UI | `kafka:9092` |
| Windows/Linux 호스트의 클라이언트 | `localhost:29092` |

Kafka의 내부·외부 advertised listener를 구분했습니다. 컨테이너 클라이언트에 localhost를 지정하면 자기 컨테이너를 가리키므로 내부 주소를 사용해야 합니다. KRaft controller 포트는 호스트에 공개하지 않습니다. UI와 외부 Kafka 포트는 로컬 loopback에만 바인딩합니다.

## 상태·로그·종료

```bash
docker compose -p docker -f Docker/docker-compose.kafka.yml ps -a
docker compose -p docker -f Docker/docker-compose.kafka.yml logs --tail 100 kafka kafka-ui kafka-init
docker compose -p docker -f Docker/docker-compose.kafka.yml stop
```

재시작은 같은 `up -d --wait` 명령을 사용합니다. Kafka 로그는 `docker_kafka_data` 볼륨에 보존합니다. `down -v`는 이 Kafka 볼륨을 삭제하므로 메시지를 보존하려면 위 stop을 사용합니다. 기존 앱의 `stack-wait.sh`는 기존 네 서비스를 검사하며 Kafka·UI는 이 Compose의 healthcheck로 확인합니다.

## 로컬 초기값과 운영 설정

- 이미지: `apache/kafka:4.1.1`, `provectuslabs/kafka-ui:v0.7.2`. 재현성을 위해 latest 대신 버전을 지정했습니다.
- 로컬 브로커·controller는 단일 노드, 초기 토픽은 1 partition·replication factor 1입니다. 운영의 장애 내구성이나 처리량 기준으로 확정한 값이 아닙니다.
- `KAFKA_PLACE_TOPIC_PARTITIONS`로 최초 토픽 생성 partition 수를 지정할 수 있습니다. 토픽이 이미 있으면 초기화 작업은 기존 설정을 변경하지 않습니다.
- `KAFKA_UI_PORT`, `KAFKA_EXTERNAL_PORT`로 호스트 포트를 변경할 수 있습니다. 기본값은 8989와 29092입니다.
- 로컬 JVM heap 상한은 Kafka 512MiB, UI 256MiB입니다. 전체 컨테이너 메모리 상한을 의미하지 않으며 운영 자원 설정과 구분합니다.
- UI 클러스터 설정은 Compose 환경변수로 재현합니다. 웹에서 추가한 동적 설정을 영구 배포 설정으로 간주하지 않습니다.

## 현재 구현 범위

이 Compose는 **브로커·토픽·GUI 기반 시설**입니다. Spring Outbox producer, FastAPI consumer·임베딩 작업자, CQRS 테이블 마이그레이션은 [이벤트·DB 명세](../docs/specifications/fastapi-place-recommendation.md)에 정의한 후속 구현입니다. 브로커나 UI가 healthy라는 이유로 관광지 이벤트가 실제로 발행·반영됐다고 판단하지 않습니다.

UI에서 Topics·메시지·consumer group과 lag를 확인할 수 있습니다. 소비자 그룹은 실제 consumer가 연결된 뒤 나타납니다. DB에 작업을 영속 접수한 뒤 offset을 commit하는 설계에서는 Kafka lag와 DB 인덱싱 작업 backlog를 함께 관측해야 합니다. Kafka lag가 0이어도 임베딩 반영이 끝나지 않았을 수 있습니다.

## 검증 기록

2026-10-25 클라우드의 격리된 Compose 프로젝트에서 다음을 확인했습니다. 검증 포트는 기존 서비스와 분리한 18989·39092를 사용했습니다.

- 브로커와 UI healthy, 토픽 초기화 작업 exit 0.
- UI 대시보드 HTML·클러스터 online·초기 토픽 조회 성공.
- 내부 브로커 메시지 발행·소비와 호스트용 advertised listener 접속 성공.
- 컨테이너 강제 재생성 후 기존 메시지 재조회 성공.
- 프록시가 있는 환경에서도 UI healthcheck가 loopback으로 직접 연결.

Windows Docker Desktop 실기기 실행과 앱 producer·consumer의 CQRS 동작 검증은 이 기록에 포함하지 않습니다.
