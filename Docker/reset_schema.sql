-- ============================================
-- users만 보존, 나머지 전부 재생성
-- ============================================
-- 주의: tour_api_raw는 절대 DROP하지 마세요.
-- TourAPI는 일 1,000건 트래픽 제한이라 다시 수집하려면 며칠이 걸립니다.
-- places와 FK로 안 엮여 있어서 이 스크립트에 안 넣으면 자동으로 보존됩니다 (users와 동일 취급).

-- [1] 자식 테이블부터 삭제 (FK 역순), CASCADE로 관련 제약도 정리
DROP TABLE IF EXISTS pin_activities CASCADE;
DROP TABLE IF EXISTS place_programs CASCADE;
DROP TABLE IF EXISTS place_details CASCADE;
DROP TABLE IF EXISTS pins CASCADE;
DROP TABLE IF EXISTS plans CASCADE;
DROP TABLE IF EXISTS room_plans CASCADE;
DROP TABLE IF EXISTS rtc_sessions CASCADE;
DROP TABLE IF EXISTS chats CASCADE;
DROP TABLE IF EXISTS room_user CASCADE;
DROP TABLE IF EXISTS rooms CASCADE;
DROP TABLE IF EXISTS friendships CASCADE;
DROP TABLE IF EXISTS places CASCADE;
-- users는 DROP하지 않음

CREATE EXTENSION IF NOT EXISTS vector;

-- tour_api_raw: 위 DROP 목록에 없으므로 기존 데이터는 보존됨. 아직 없는 환경을 위해 IF NOT EXISTS로만 생성.
CREATE TABLE IF NOT EXISTS tour_api_raw (
    tour_content_id       VARCHAR(50) PRIMARY KEY,
    tour_content_type_id  VARCHAR(10) NOT NULL,
    raw_list               JSONB,
    raw_common              JSONB,
    raw_info                JSONB,
    fetched_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    processed_at            TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_tour_api_raw_unprocessed ON tour_api_raw (fetched_at) WHERE processed_at IS NULL;


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

-- ============================================
-- places
-- ============================================
CREATE TABLE places (
    id                    BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name                  VARCHAR(200) NOT NULL,
    description           TEXT,
    region                VARCHAR(100),
    city                  VARCHAR(50),
    category              VARCHAR(50),
    source_category       VARCHAR(50),
    latitude              DOUBLE PRECISION,
    longitude             DOUBLE PRECISION,
    kakao_place_id        VARCHAR(100) UNIQUE,
    tour_content_id       VARCHAR(50) UNIQUE,
    tour_content_type_id  VARCHAR(10),
    image_url             VARCHAR(500),
    homepage_url          VARCHAR(500),
    embedding             vector(1024),
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_places_region    ON places (region);
CREATE INDEX idx_places_city      ON places (city);
CREATE INDEX idx_places_category  ON places (category);
CREATE INDEX idx_places_embedding ON places USING hnsw (embedding vector_cosine_ops);

-- ============================================
-- friendships / rooms / room_user / chats / rtc_sessions
-- ============================================
CREATE TABLE friendships (
    friendship_id BIGSERIAL PRIMARY KEY,
    user_uid  VARCHAR(36) NOT NULL,
    friend_uid  VARCHAR(36) NOT NULL,
    status VARCHAR(20) CHECK (status IN ('PENDING', 'ACCEPTED', 'REJECTED')) DEFAULT 'PENDING',
    FOREIGN KEY (user_uid) REFERENCES users(uid),
    FOREIGN KEY (friend_uid) REFERENCES users(uid)
);

CREATE TABLE rooms (
    room_id BIGSERIAL PRIMARY KEY,
    title VARCHAR(100) NOT NULL,
    description TEXT,
    category VARCHAR(50),
    pass VARCHAR(100),
    is_private BOOLEAN DEFAULT FALSE,
    host_uid  VARCHAR(36) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (host_uid) REFERENCES users(uid)
);

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

CREATE TABLE chats (
    chat_id BIGSERIAL PRIMARY KEY,
    room_id BIGINT NOT NULL,
    user_uid  VARCHAR(36) NOT NULL,
    message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (room_id) REFERENCES rooms(room_id),
    FOREIGN KEY (user_uid) REFERENCES users(uid)
);

CREATE TABLE rtc_sessions (
    session_id BIGSERIAL PRIMARY KEY,
    room_id BIGINT NOT NULL,
    session_key TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (room_id) REFERENCES rooms(room_id)
);

-- ============================================
-- room_plans / plans / pins / pin_activities
-- ============================================
CREATE TABLE room_plans (
    room_plan_id BIGSERIAL PRIMARY KEY,
    room_id BIGINT NOT NULL,
    title VARCHAR(100) NOT NULL,
    content TEXT,
    total_budget DECIMAL(15, 2),
    start_date DATE,
    end_date DATE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (room_id) REFERENCES rooms(room_id) ON DELETE CASCADE
);

CREATE TABLE plans (
    plan_id BIGSERIAL PRIMARY KEY,
    room_plan_id BIGINT,
    user_uid  VARCHAR(36) NOT NULL,
    title VARCHAR(100) NOT NULL,
    description TEXT,
    status VARCHAR(20) DEFAULT 'DRAFT',
    pace_preference VARCHAR(20),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (room_plan_id) REFERENCES room_plans(room_plan_id) ON DELETE CASCADE,
    FOREIGN KEY (user_uid) REFERENCES users(uid)
);

CREATE TABLE pins (
    pin_id BIGSERIAL PRIMARY KEY,
    plan_id BIGINT NOT NULL,
    place_id BIGINT,
    place_name VARCHAR(100),
    latitude DOUBLE PRECISION NOT NULL,
    longitude DOUBLE PRECISION NOT NULL,
    memo TEXT,
    sequence INT,
    cost DECIMAL(15, 2),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (plan_id) REFERENCES plans(plan_id) ON DELETE CASCADE,
    FOREIGN KEY (place_id) REFERENCES places(id) ON DELETE SET NULL
);

CREATE TABLE pin_activities (
    activity_id       BIGSERIAL PRIMARY KEY,
    pin_id            BIGINT NOT NULL,
    sequence          INT NOT NULL,
    activity          TEXT NOT NULL,
    reason            TEXT,
    estimated_minutes INT,
    status            VARCHAR(20) NOT NULL DEFAULT 'SUGGESTED',
    source_detail_id  VARCHAR(50),
    user_rating       SMALLINT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (pin_id) REFERENCES pins(pin_id) ON DELETE CASCADE
);

CREATE INDEX idx_pin_activities_pin_id ON pin_activities (pin_id);

-- ============================================
-- place_details / place_programs (RAG 상세)
-- ============================================
CREATE TABLE place_details (
    place_id    BIGINT PRIMARY KEY REFERENCES places(id) ON DELETE CASCADE,
    raw_intro   JSONB,
    fetched_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE place_programs (
    program_id   BIGSERIAL PRIMARY KEY,
    place_id     BIGINT NOT NULL REFERENCES places(id) ON DELETE CASCADE,
    info_name    VARCHAR(100),
    info_text    TEXT,
    serial_num   VARCHAR(10),
    fetched_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_place_programs_place_id ON place_programs (place_id);