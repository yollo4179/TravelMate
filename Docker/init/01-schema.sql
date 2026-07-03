ALTER USER ssafy WITH PASSWORD 'ssafy';

CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS places (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name            VARCHAR(200) NOT NULL,
    description     TEXT,
    region          VARCHAR(100),          -- 광역 필터 (경기, 서울...)
    city            VARCHAR(50),           -- 세부 도시 필터 (가평, 수원...) 
    category        VARCHAR(50),           -- 카테고리 필터(참조용)
    source_category VARCHAR(50),           -- 원본 카테고리 (kakao, 메인)    
    latitude        DOUBLE PRECISION,
    longitude       DOUBLE PRECISION,
    kakao_place_id  VARCHAR(100) UNIQUE,   -- 중복 방지 (ON CONFLICT용)
    embedding       vector(1024),          -- bge-m3
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_places_region    ON places (region);
CREATE INDEX IF NOT EXISTS idx_places_city      ON places (city);
CREATE INDEX IF NOT EXISTS idx_places_category  ON places (category);
CREATE INDEX IF NOT EXISTS idx_places_embedding ON places USING hnsw (embedding vector_cosine_ops);

-- 벡터 유사도 검색용 HNSW 인덱스
-- vector_cosine_ops = 코사인 유사도 기준 (임베딩 검색에 일반적)
-- 수천, 수만 개의 장소 벡터 중에서 나와 가장 유사한 코사인 유사도를 가진 장소 Top-K를 빠르게 찾아내기 위함
CREATE INDEX IF NOT EXISTS idx_place_embedding
    ON places USING hnsw (embedding vector_cosine_ops);
---------------------------------------------------목적 - 서울에 있는 관광지 중에서 남산타워와 비슷한 곳이 있으면 추천해줘 - 유사도 TOP -K 개 추출----

-- 1. 유저 테이블
DROP TABLE IF EXISTS users CASCADE;
CREATE TABLE IF NOT EXISTS users (
    uid VARCHAR(36) PRIMARY KEY,           -- 기본키 (PK)
    user_id VARCHAR(255) NOT NULL UNIQUE,  -- 유저 아이디 (NOT NULL, UNIQUE)
    email VARCHAR(255) NOT NULL UNIQUE,    -- 이메일 (NOT NULL, UNIQUE)
    password VARCHAR(255),                 -- 비밀번호 (소셜 로그인 시 NULL 가능)
    nickname VARCHAR(255) NOT NULL UNIQUE, -- 닉네임 (NOT NULL, UNIQUE)
    phone_number VARCHAR(255),             -- 전화번호 (NULL 가능)
    profile_img_url VARCHAR(255),          -- 프로필 이미지 (NULL 가능)
    role VARCHAR(255),                     -- 권한 (USER, ADMIN 등)
    status VARCHAR(255) NOT NULL,          -- 상태 (ACTIVE, QUIT 등)
    provider VARCHAR(255) NOT NULL,        -- 로그인 제공자 (KAKAO, NAVER 등)
    created_at TIMESTAMP WITHOUT TIME ZONE, -- 생성일
    updated_at TIMESTAMP WITHOUT TIME ZONE  -- 수정일
);
-- 2. 친구 테이블
DROP TABLE IF EXISTS friendships CASCADE;
CREATE TABLE friendships (
    friendship_id BIGSERIAL PRIMARY KEY,
    user_uid  VARCHAR(36) NOT NULL,      -- 나
    friend_uid  VARCHAR(36) NOT NULL,    -- 친구
    status VARCHAR(20) CHECK (status IN ('PENDING', 'ACCEPTED', 'REJECTED')) DEFAULT 'PENDING',
    FOREIGN KEY (user_uid) REFERENCES users(uid),
    FOREIGN KEY (friend_uid) REFERENCES users(uid)
);

-- 3. 방 테이블
DROP TABLE IF EXISTS rooms CASCADE;
CREATE TABLE rooms (
    room_id BIGSERIAL PRIMARY KEY,
    title VARCHAR(100) NOT NULL,  -- 방제
    description TEXT,             -- 방 설명
    category VARCHAR(50),         -- 방 필터링용
    pass VARCHAR(100),            -- null이면 공개방, 존재하면 비밀방
    is_private BOOLEAN DEFAULT FALSE,
    host_uid  VARCHAR(36) NOT NULL,      -- 방장
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (host_uid) REFERENCES users(uid)
);

-- 4. 방-유저 연결 테이블
DROP TABLE IF EXISTS room_user CASCADE;
CREATE TABLE room_user (
    participant_id BIGSERIAL PRIMARY KEY,
    room_id BIGINT NOT NULL,
    user_uid  VARCHAR(36) NOT NULL,
    role_as VARCHAR(10) CHECK (role_as IN ('ADMIN', 'USER')) DEFAULT 'USER',
    status VARCHAR(10) CHECK (status IN ('ACTIVE', 'LEFT', 'BANNED')) DEFAULT 'ACTIVE',
    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (room_id) REFERENCES rooms(room_id),
    FOREIGN KEY (user_uid) REFERENCES users(uid)
);

DROP TABLE IF EXISTS chats CASCADE;
CREATE TABLE chats (
    chat_id BIGSERIAL PRIMARY KEY,
    room_id BIGINT NOT NULL,
    user_uid  VARCHAR(36) NOT NULL,
    message TEXT,        
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (room_id) REFERENCES rooms(room_id),
    FOREIGN KEY (user_uid) REFERENCES users(uid)
);

DROP TABLE IF EXISTS rtc_sessions CASCADE;
CREATE TABLE rtc_sessions (
    session_id BIGSERIAL PRIMARY KEY,
    room_id BIGINT NOT NULL,
    session_key TEXT NOT NULL,     
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (room_id) REFERENCES rooms(room_id)
);
--------------------------플랜 엔티티
-- 5. 룸 플랜 (방 전체의 대분류 계획, text로 구성 가능)
DROP TABLE IF EXISTS room_plans CASCADE;
CREATE TABLE room_plans (
    room_plan_id BIGSERIAL PRIMARY KEY,
    room_id BIGINT NOT NULL,              -- 어느 방의 계획인지
    title VARCHAR(100) NOT NULL,
    content TEXT,                         -- 텍스트로 구성될 수 있는 본문/설명
    total_budget DECIMAL(15, 2),          -- 전체 예산
    start_date DATE,
    end_date DATE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (room_id) REFERENCES rooms(room_id) ON DELETE CASCADE
);

-- 6. 개별 플랜 (여러 개의 개인 플랜, 룸 플랜에 소속됨)
DROP TABLE IF EXISTS plans CASCADE;
CREATE TABLE plans (
    plan_id BIGSERIAL PRIMARY KEY,
    room_plan_id BIGINT,                  -- 소속된 룸 플랜 (null이면 방에 속하지 않은 개인 플랜)
    user_uid  VARCHAR(36) NOT NULL,              -- 이 플랜을 작성/관리하는 유저
    title VARCHAR(100) NOT NULL,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (room_plan_id) REFERENCES room_plans(room_plan_id) ON DELETE CASCADE,
    FOREIGN KEY (user_uid) REFERENCES users(uid)
);

-- 7. 지도 핀 (각 개별 플랜의 세부 장소 항목)
DROP TABLE IF EXISTS pins CASCADE;
CREATE TABLE pins (
    pin_id BIGSERIAL PRIMARY KEY,
    plan_id BIGINT NOT NULL,              -- 어느 개별 플랜에 속하는 핀인지 연결
    place_name VARCHAR(100),
    latitude DOUBLE PRECISION NOT NULL,   
    longitude DOUBLE PRECISION NOT NULL,  
    memo TEXT,
    sequence INT,                         -- 이동 순서
    cost DECIMAL(15, 2),                  -- 해당 장소 예상 비용
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (plan_id) REFERENCES plans(plan_id) ON DELETE CASCADE
);