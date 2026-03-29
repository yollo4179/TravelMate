# Travel-Mate

# 기능 설명
- 회원가입을 통해서 유저를 등록합니다. 
- 유저는 여러 명의 친구를 둘 수 있으며 전화번호, 이메일 혹은 닉네임을 통해서 검색하고 친구 추가 요청을 할 수있습니다.
- 유저는 자신만의 계획표를 작성할 수 있고 방에 공유할 수 있습니다. ( 여행 계획표를 사고 팔수 있는 시스템도 구현 가능하면 구현 예정)  
- 메인화면에서는 키워드 검색 및 카테고리 필터링을 통해 원하는 방을 서치할 수 있습니다.
- 한 유저는 여러 개의 방에 참여하고 종속될 수 있으며 방에서는 다른 유저와 함께 여행 계획을 짤 수 있습니다.
- 방에는 채팅 및 영상, 음성 통화 기능이 제공됩니다. 
- 방에는 지도 기능이 있어 핀을 꽂을 수 있고 핀을 핀 주변의 할만한 것들 등 자동으로 동선을 짜주는 AI 기능 혹은 관련 블로그 추천 기능이 활용될 수 있습니다.
- 각 핀은 local location plan detail로서 해당 장소에서의 상세 계획을 팀원들과 함께 작성 할 수 있습니다. (local 지역 plan 추천 서비스)  
- 방에서는 자신의 계획일정을 공유할 수 있습니다.


# Step 1: 기본 인프라 구축 (Spring Boot + Vue.js 연동, DB 설계)

## DB 설계 

### 1. 전체 DB 구조 (핵심 엔티티)

<pre>
유저, 친구 관계, 친구들과 함께 여행을 계획하고 소통하기위한 Room을 효과적으로 관리하기위해
크게 6개의 도메인으로 나눠서 진행하였습니다.   
</pre>
<ol>
    <li>USER (회원)</li>
    <li>FRIEND (친구)</li>
    <li>ROOM (여행 방 / 채팅방)</li>
    <li>PLAN (여행 계획)</li>
    <li>MAP_PIN (지도 핀)</li>
    <li>CHAT / RTC (채팅 + WebRTC 보조)</li>
</ol>


### 📊 ER Diagram
![ERD](./TravelMate_ERD.drawio.svg)


### Spring Boot 세팅 및 설계

### TDD 설계 및 테스트 

### vue.js 연동

# Step 2: WebRTC를 이용한 통신 시스템 구현 (음성 +영상 +CHAT)

### Signaling Server(WebSocket) ,stun/turn 미디어 서버 (openVidu or Kurento)

### Step 3: 실시간 채팅 및 공유 지도 (Stomp/WebSocket 활용)
 - 화상 통화 중 같은 지도를 보고 핀을 찍는 동기화 작업.

# Step 4: 여행 플랜 추천 로직 및 외부 API 연동(AI)
### 공공데이터포털(TourAPI), 네이버/카카오 지도 API 연동 및 비용 산정 알고리즘 구현.




<table>
  <thead>
    <tr>
      <th>구분</th>
      <th>기술 Stack</th>
      <th>비고</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>Frontend</td>
      <td>Vue 3, Pinia, TailwindCSS</td>
      <td>상태 관리 및 UI</td>
    </tr>
    <tr>
      <td>Communication</td>
      <td>WebRTC, Socket.io or SockJS</td>
      <td>실시간 화상 및 시그널링</td>
    </tr>
    <tr>
      <td>Messaging</td>
      <td>Spring WebSocket (STOMP)</td>
      <td>실시간 채팅 및 지도 핀 동기화</td>
    </tr>
    <tr>
      <td>Map API</td>
      <td>Kakao Maps / Google Maps API</td>
      <td>장소 검색 및 좌표 추출</td>
    </tr>
    <tr>
      <td>Recommendation</td>
      <td>TourAPI 4.0, 자체 비용 계산 Logic</td>
      <td>지역별 플랜 데이터 수급</td>
    </tr>
  </tbody>
</table>


여행 계획 시스템을 만들거야 . WEBRTC 기반의 디스코드 like한 영상통화 + 채팅서비스 +지도에 찍으면 해당지역에서 할수 있는 지역플랜 제공(추천) +지역검색해서 전역적인 플랜 + 비용에 따른 플랜을 제공(추천) 비용 기준 추천 + 인기 많은 나라+국내 여행 플랜 제공 전체적인 구조(dto,DAO 데이터 베이스)+ 전반적인 순서를 좀 잡아줘( webRTC 빨리 하고 싶긴 함) vue.js+ springboot를 위주로 할거다 데이터 베이스 우선 설계하려고해 1. 일당 유저는 회원가입을 수행해야 하고, 닉네임이나 이메일 전화번호로 목록으로 부터 친구를 추가할 수 있다 한 유저는 여러 개의 여행 PLAN 방에 속해 있어야 해 친구를 추천해서 방에 초대할 수 있고 방은 비밀번호가 있을 수도 없을 수도 있다. 한 방에는 여러 유저가 속해 있고 채팅과 여러 명이서 영상 통화가 가능해. 방은 MAIN화면에서 SEARCHBAR를 통해서 검색어 혹은 관련 카테고리 필터로 통해서 필터링을 거쳐서 관련된 방만 렌더링한다. 각 방에서는 채팅 기능 , 영상 및 음성 통화 기능 , 포함한다. 지도 핀 매핑이 가능하고 핀은 모든 유저가 건드릴 수 있으며 핀은 플랜 메모지를 가지고 해당 장소에서의 상세 플랜을 작성 할 수 있고 해당 지역의 유명도 및 추천 동선을 AI로 해결하게 하고 싶다... 한 유저는 여러 여행 계획표를 세울 수 있어 방에 공유가 가능하다. 이런 애플리케이션을 작성하려고 해 . 이 내용을 모두 학습해 우선 스프링 부트와 SQL의 연동작업 부터 하고 싶어 데이터를 어떻게 짜면 좋을까? DB 테이블 구조 작성해줘