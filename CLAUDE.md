# TravelMate

## Project Overview

여행 계획 협업 플랫폼. 유저가 방(Room)을 만들어 친구를 초대하고, 실시간 채팅/영상통화(WebRTC)를 하며 지도 위에 핀을 찍어 함께 여행 계획을 세울 수 있는 서비스.

SSAFY 프로젝트로, Server(Spring Boot) + Client(Vue.js) + Android(Kotlin) + Database(PostgreSQL) 4개 모듈로 구성된 모노레포.

## Architecture

```
TravelMate/
├── Server/TravelMate/     # Spring Boot 3.5 백엔드 (Java 17)
├── Client/travel-mate-frontend/  # Vue 3 + Vite 프론트엔드
├── Android/               # Kotlin + Jetpack Compose 안드로이드 앱
└── DataBase/              # SQL 스키마 (database.sql)
```

## Tech Stack

### Backend (Server/TravelMate/)
- **Framework**: Spring Boot 3.5.13, Java 17
- **ORM**: Spring Data JPA (Hibernate)
- **DB**: PostgreSQL (localhost:5432/TravelMate, user: ssafy)
- **Auth**: Spring Security + OAuth2 (Google, Kakao, Naver) + JWT (jjwt 0.11.5)
- **Cache**: Redis (Upstash, SSL)
- **WebSocket**: Spring WebSocket + STOMP
- **API Docs**: Swagger (springdoc-openapi 2.8.9)
- **Build**: Gradle
- **Port**: 8080

### Frontend (Client/travel-mate-frontend/)
- **Framework**: Vue 3.5 + Vite 8
- **State**: Pinia 3
- **Router**: vue-router 5
- **HTTP**: Axios
- **WebSocket**: @stomp/stompjs + sockjs-client
- **UI**: Bootstrap 5 + Bootstrap Icons
- **Lint**: ESLint + oxlint + Prettier
- **Node**: ^20.19.0 || >=22.12.0

### Android (Android/)
- **Language**: Kotlin
- **UI**: Jetpack Compose
- **Network**: Retrofit
- **Local DB**: Room
- **Package**: com.ssafy.travelmate

## Server Domain Structure

서버는 도메인 기반 패키지 구조 (com.yollo.TravelMate.domain.*):

| Domain | Description |
|--------|-------------|
| `auth` | OAuth2 로그인 (Google/Kakao/Naver), JWT 토큰 발급 |
| `user` | 회원 CRUD, 친구(Friendship) 관리 |
| `room` | 여행 방 CRUD, 방-유저 연결(RoomUser), 채팅(Chat) |
| `plan` | 여행 계획(Plan), 지도 핀(Pin) |
| `signaling` | WebRTC 시그널링 (STOMP 기반) |
| `session` | RTC 세션 관리 |
| `kakao` | 카카오 프로필 조회 |
| `kakaoApi/place` | 카카오 로컬 API 장소 검색 |

각 도메인은 `controller / service / repository / entity / dto` 레이어로 구성.

### Cross-cutting

| Package | Description |
|---------|-------------|
| `config` | CORS, Redis, Swagger, WebSocket 설정 |
| `jwt` | SecurityConfig, JwtTokenProvider, JwtAuthenticationFilter |
| `redis` | RedisService, RedisKeyType |
| `exceptions` | GlobalExceptionHandler, ErrorCode enum, ErrorCodeException |
| `cookies` | CookieUtil |
| `util/managers` | OauthManager |

## DB Schema (PostgreSQL)

핵심 테이블: `users`, `friendships`, `rooms`, `room_user`, `plans`, `pins`, `chats`
- DDL은 `DataBase/database.sql` 참조
- JPA ddl-auto=update 사용 (개발 환경)

## Commands

### Server
```bash
cd Server/TravelMate
./gradlew bootRun          # 서버 실행 (localhost:8080)
./gradlew test             # 테스트 실행
./gradlew build            # 빌드
```

### Client
```bash
cd Client/travel-mate-frontend
npm install                # 의존성 설치
npm run dev                # 개발 서버 실행
npm run build              # 프로덕션 빌드
npm run lint               # ESLint + oxlint 실행
npm run format             # Prettier 포맷팅
```

### Android
Android Studio에서 `Android/` 디렉토리를 열어 빌드/실행.

## Conventions

- Server DTO 패턴: `request/`, `response/`, `internal/`, `external/` 하위 패키지로 분리
- Service는 인터페이스 + Impl 패턴 사용 (e.g., `RoomService` / `RoomServiceImpl`)
- Frontend Services: `src/Services/` 디렉토리에 API 호출 로직 분리
- Frontend Stores: `src/piniaStores/` 디렉토리에 Pinia 스토어
- Lombok 사용 (compileOnly)
- 서버 로깅 레벨: com.yollo 패키지는 DEBUG

## API Documentation

서버 실행 후 Swagger UI 접근: `http://localhost:8080/swagger-ui/index.html`

## Important Notes

- `application.properties`에 JWT secret, Redis 비밀번호 등 민감 정보가 하드코딩되어 있음. 프로덕션 배포 시 환경변수로 분리 필요.
- OAuth2 클라이언트 시크릿 파일이 Android 프로젝트에 포함되어 있으므로 주의.
- WebRTC 시그널링은 STOMP over WebSocket 방식으로 구현.
