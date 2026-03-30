# 스프링부트 기반의 서버

## USER (회원 도메인)

### Controller:

<pre>
  POST /api/users/signup (회원가입),
  POST /api/users/login (로그인/JWT 발급),
  GET /api/users/search (검색)
</pre>

### Service: 비밀번호 암호화(BCrypt), 중복 아이디 체크, 유저 정보 수정 로직.

### DTO: UserJoinRequest, UserLoginResponse, UserSearchResponse.

### 핵심 기능: 닉네임/이메일/전화번호를 통한 동적 검색 쿼리 구현.

## DTO

## TDD (Junit Test)

## Service

## Controller

## Repository
