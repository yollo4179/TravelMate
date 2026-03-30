# 스프링부트 기반의 서버

## USER (회원 도메인)

### Controller:

<pre>
  POST /api/users/signup (회원가입),
  POST /api/users/login (로그인/JWT 발급),
  GET /api/users/search (검색)
</pre>

### Service: 비밀번호 암호화(BCrypt), 중복 아이디 체크 , 유저 정보 수정 로직.
### DTO: UserJoinRequest, UserLoginResponse, UserSearchResponse.
### Service: 비밀번호 암호화(BCrypt), 중복 아이디 체크, 유저 정보 수정 로직.
### DTO: UserJoinRequest, UserLoginResponse, UserSearchResponse.

### 핵심 기능: 닉네임/이메일/전화번호를 통한 동적 검색 쿼리 구현.
<hr>

## 2. FRIEND (친구 관계 도메인)

### 유저 간의 다대다($N:M$) 관계를 관리하며, '상태(PENDING, ACCEPTED)' 값이 중요합니다
<ol>
<li> Repository: findByFromUserAndStatus, findAllFriendsByUserId 등의 쿼리.</li>
<li> Service: 친구 요청 발송 시 중복 체크, 수락 시 양방향 관계 업데이트 혹은 상태 변경 로직.</li>

<li> Controller: 
  <pre>
    POST /api/friends/request,
    PATCH /api/friends/accept,
    GET /api/friends/list.
  </pre>
</li>
</ol>

## 3. ROOM (여행 방 / 소통 도메인)유저와 계획(Plan)을 연결하는 핵심 매개체입니다.

<ol>
  <li>Repository: 특정 유저가 참여 중인 방 목록 조회 (JOIN 활용).</li>
  <li> Service: 방 생성 시 생성자를 방장(Owner) 권한으로 설정, 방 입장/퇴장 처리.</li>
  <li> Entity 설계: UserRoom이라는 중간 테이블을 두어 유저와 방의 다대다 관계를 일대다($1:N$) 두 개로 해소.</li>
</ol>

## 4. PLAN (여행 계획 도메인)

### 방 내부에서 공유되는 메인 스케줄 데이터입니다.
<ol>
<li> Controller: 
  <pre>
    GET /api/rooms/{roomId}/plans (방별 계획 조회),
    POST /api/plans/share (개인 계획을 방에 공유).
  </pre>
</li>
<li> Service: 계획표 사고팔기 기능을 고려하여 '가격(Price)', '공유 여부(isShared)' 필드 관리 및 소유권 이전 로직.</li>
<li>DTO: PlanDetailResponse, PlanCreateRequest.</li>
</ol>

## 5. MAP_PIN (지도 핀 및 상세 경로)

지리 정보와 블로그 추천, AI 동선 최적화가 포함되는 영역입니다.
<ol>
<li> Repository: findByRoomId (특정 방의 모든 핀 조회).</li>

<li>Service:
  <ol>
    <li>AI 연동: 외부 LLM API나 자체 알고리즘을 호출하여 핀들 사이의 최적 경로 계산.</li>
    <li>블로그 추천: 외부 API(Naver/Google)를 연동하여 핀 좌표 기반 맛집/장소 추천 데이터 가공.</li>
  </ol>
</li>
<li> DTO: PinLocationDTO (위도 $Latitude$, 경도 $Longitude$, 장소명, 메모 포함).</li>
</ol>

## 6. CHAT / RTC (실시간 소통)
<ol>
<li>Controller: @MessageMapping을 이용한 WebSocket 핸들러 (STOMP 프로토콜).</li>
<li>Service: 채팅 메시지 데이터베이스 저장(History), WebRTC 시그널링 서버 역할(방 입장 시 Peer 정보 교환).</li>
<li>Repository: 채팅 내역 조회를 위한 페이징 처리 (ChatRepository).</li>

</ol>
