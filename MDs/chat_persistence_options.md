# 채팅 기록 저장/불러오기 아키텍처 결정 문서

> **목적**: Travel AI 앱의 AI 채팅(ChatScreen)에서 채팅 기록을 영속화(persist)하는 방식에 대해 Firebase vs 대안들을 비교하고, 프로젝트 방향성에 맞는 최적의 선택을 정리한다.
> **대상**: Map ↔ Chat 간 Context(`currentEditingPlan`, `currentFocusMarkerId`) 동기화와 함께 고려해야 하는 아키텍처 결정.

**작성일**: 2026-07-12  
**버전**: v1.0  
**관련 문서**: `travel_app_screen_structure.md` (v1.1)

---

## 1. 현재 상황 요약

- **주요 기술 스택**: Spring Boot (또는 FastAPI), Android (Jetpack Compose), 자체 호스팅 LLM (Ollama/vLLM + Qwen/DeepSeek), PGVector (PostgreSQL), KakaoMap
- **채팅의 핵심 요구사항**:
  - Context 유지 (현재 수정중인 계획, 선택된 마커)
  - Tool calling + RAG 연동
  - Map ↔ Chat 간 실시간/양방향 동기화 (`currentEditingPlan` 등)
  - 채팅 기록 저장 및 불러오기 (세션 간 유지)
- **포트폴리오 목표**: 기술적 일관성, 자체 호스팅 강조, 데이터 주권, 면접 스토리텔링

---

## 2. Firebase Firestore 도입 시 Pros & Cons

| 항목                        | Pros                                      | Cons                                              | 점수 (5점 만점) |
|-----------------------------|-------------------------------------------|---------------------------------------------------|-----------------|
| **구현 속도**               | 매우 빠름 (SDK + 실시간 구독 간단)         | -                                                 | 5               |
| **실시간 동기화**           | 최고 수준 (Firestore 실시간 리스너)        | -                                                 | 5               |
| **오프라인 지원**           | 좋음 (오프라인 persistence)                | -                                                 | 4               |
| **기술 스택 일관성**        | -                                         | 기존 스택(Spring Boot + PGVector)과 완전 이질적   | 2               |
| **포트폴리오 스토리텔링**   | -                                         | "왜 채팅 기록만 Firebase인가?" 질문 받기 쉬움     | 2               |
| **데이터 프라이버시**       | -                                         | Google 서버에 여행 계획/선호도 데이터 저장        | 2               |
| **Context 동기화 복잡도**   | -                                         | `currentEditingPlan` 등 추가 매핑 작업 필요       | 3               |
| **비용 (초기~중간 규모)**   | 무료 티어 충분                            | 스케일업 시 유료 전환 가능성                      | 4               |
| **전체 추천도**             | 빠른 MVP 데모용                           | 프로젝트 방향성과 맞지 않음                       | **2.8**         |

**결론**: Firebase는 **구현 속도**에서는 압도적이지만, **기술 일관성**과 **포트폴리오 메시지**에서 큰 마이너스 요인이다.

---

## 3. 대안 비교 (추천 순위)

| 순위 | 방식                              | 기술 스택 일관성 | 구현 난이도 | 오프라인 | 실시간 동기화 | 프라이버시 | 포트폴리오 적합도 | 추천 상황 |
|------|-----------------------------------|------------------|-------------|----------|---------------|------------|-------------------|-----------|
| **1** | **PostgreSQL + Spring Boot** (기존 백엔드) | ★★★★★           | 중간        | 중간     | 중상 (WebSocket) | ★★★★★     | ★★★★★            | **기본 추천** |
| **2** | **Room (Android 로컬 DB)**        | ★★★★☆           | 낮음        | ★★★★★    | 없음         | ★★★★★     | ★★★★☆            | 오프라인 우선, 빠른 구현 |
| **3** | **Supabase** (Postgres 기반)      | ★★★★☆           | 낮음~중간   | 좋음     | 좋음         | ★★★★☆     | ★★★★☆            | Firebase 대안으로 고려 |
| **4** | **Firebase Firestore**            | ★★☆☆☆           | 매우 낮음   | 좋음     | 최고         | ★★☆☆☆     | ★★☆☆☆            | 멀티 디바이스 실시간이 필수일 때만 |
| 5    | SQLite + 커스텀 동기화            | ★★★☆☆           | 높음        | 최고     | 직접 구현    | 최고       | ★★★☆☆            | 비추천 |

### 1순위 추천: PostgreSQL + Spring Boot (기존 백엔드 활용)

**이유**:
- 기존에 이미 PGVector를 사용 중이므로 채팅 기록 테이블을 같은 DB에 추가하면 완벽한 일관성 유지
- RAG 데이터(장소, 리뷰, 가이드)와 채팅 기록을 함께 관리 가능
- `currentEditingPlan`, `currentFocusMarkerId` 등의 Context를 DB에 저장하고 API로 제공하기 용이
- Spring Boot에서 이미 보안, 인증, 트랜잭션 등을 처리하고 있음
- 포트폴리오에서 "전체 시스템을 내가 통제한다"는 메시지를 일관되게 전달 가능

**간단한 테이블 설계 예시**:
```sql
CREATE TABLE chat_sessions (
    id UUID PRIMARY KEY,
    user_id VARCHAR(255),
    created_at TIMESTAMP,
    last_updated_at TIMESTAMP,
    current_focus_marker_id VARCHAR(255),
    current_editing_plan JSONB   -- 현재 수정중인 계획 정보 저장
);

CREATE TABLE chat_messages (
    id UUID PRIMARY KEY,
    session_id UUID REFERENCES chat_sessions(id),
    role VARCHAR(20),           -- 'user' 또는 'assistant'
    content TEXT,
    metadata JSONB,             -- tool_calls, sources, focus_marker 등
    created_at TIMESTAMP
);
```

**Android 쪽**:
- Retrofit으로 채팅 기록 조회/저장 API 호출
- Room을 로컬 캐시로 병행 사용 (오프라인 지원 강화)

### 2순위 추천: Room (로컬 전용)

**이유**:
- 구현이 가장 빠르고 간단
- 완전 오프라인 지원
- Context 상태(`currentEditingPlan` 등)도 함께 저장하기 매우 용이
- Firebase처럼 외부 의존성 추가하지 않음

**단점**:
- 기기 변경 시 채팅 기록 이관이 어려움 (필요 시 수동 export/import)
- 실시간 멀티 디바이스 동기화 불가능

**적합한 경우**:
- "일단 동작하는 데모"를 빠르게 만들고 싶을 때
- 오프라인 경험을 강조하고 싶을 때

### 3순위: Supabase (Postgres + Realtime)

Firebase와 비슷한 개발 경험을 제공하면서 **Postgres 기반**이라는 점에서 기존 스택과 더 잘 맞음.  
실시간 기능이 필요하다면 Firebase 대신 Supabase를 고려할 만함.

---

## 4. 최종 추천

| 당신의 우선순위                          | 추천 방식                     | 비고 |
|------------------------------------------|-------------------------------|------|
| 기술 스택 일관성 + 포트폴리오 퀄리티 최우선 | **PostgreSQL + Spring Boot** | 강력 추천 |
| 구현 속도 + 오프라인 지원 최우선         | **Room**                      | 빠른 데모용 |
| 멀티 디바이스 실시간 동기화가 정말 필요  | **Supabase** 또는 Firebase    | 마지막 선택지 |
| 아무거나 빠르게 하고 싶다                | Firebase                      | 비추천 (이유 위에 명시) |

**내 결론**:  
현재 프로젝트의 방향성과 포트폴리오 목표를 고려하면 **PostgreSQL + Spring Boot**를 사용하는 것이 가장 바람직합니다.  
Firebase는 "구현이 빠르다"는 장점 외에는 대부분의 면에서 불리합니다.

---

## 5. 다음 단계 제안

1. **채팅 기록 테이블 설계** (PostgreSQL)
2. **Spring Boot API** 명세 작성 (`GET /chats`, `POST /chats/{sessionId}/messages` 등)
3. **Android**:
   - Retrofit 인터페이스 정의
   - Room Entity + DAO (로컬 캐시용)
   - ViewModel에서 Context(`currentEditingPlan`)와 함께 채팅 기록 관리
4. Context 동기화 로직 문서화 (`currentEditingPlan` 변경 시 DB 업데이트 + Chat/Map 반영)

---

**추가로 원하는 내용**:
- PostgreSQL 테이블 상세 스키마 + 인덱스 제안
- Spring Boot Repository + Service 코드 스켈레톤
- Android Room + Retrofit 하이브리드 구현 예시
- Context(`currentEditingPlan`) 저장 전략 상세

필요한 부분 말씀해주세요. 바로 정리해드리겠습니다.