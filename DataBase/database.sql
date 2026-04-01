-- 1. 유저 테이블
DROP TABLE IF EXISTS users CASCADE;
CREATE TABLE IF NOT EXISTS users (
    user_id BIGSERIAL PRIMARY KEY, -- SERIAL에서 BIGSERIAL로 변경 (BIGINT 외래키와 매칭)
    email VARCHAR(100) NOT NULL,
    pass VARCHAR(255) NOT NULL,
    nickname VARCHAR(50) NOT NULL,
    phone_number VARCHAR(20) NOT NULL,
    profile_img_url VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. 친구 테이블
DROP TABLE IF EXISTS friendships CASCADE;
CREATE TABLE friendships (
    friendship_id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,      -- 나
    friend_id BIGINT NOT NULL,    -- 친구
    status VARCHAR(20) CHECK (status IN ('PENDING', 'ACCEPTED', 'REJECTED')) DEFAULT 'PENDING',
    FOREIGN KEY (user_id) REFERENCES users(user_id),
    FOREIGN KEY (friend_id) REFERENCES users(user_id)
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
    host_id BIGINT NOT NULL,      -- 방장
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (host_id) REFERENCES users(user_id)
);

-- 4. 방-유저 연결 테이블
DROP TABLE IF EXISTS room_user CASCADE;
CREATE TABLE room_user (
    participant_id BIGSERIAL PRIMARY KEY,
    room_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    role_as VARCHAR(10) CHECK (role_as IN ('ADMIN', 'USER')) DEFAULT 'USER',
    status VARCHAR(10) CHECK (status IN ('ACTIVE', 'LEFT', 'BANNED')) DEFAULT 'ACTIVE',
    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (room_id) REFERENCES rooms(room_id),
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

DROP TABLE IF EXISTS chats CASCADE;
CREATE TABLE chats (
    chat_id BIGSERIAL PRIMARY KEY,
    room_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    message TEXT,        
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (room_id) REFERENCES rooms(room_id),
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

DROP TABLE IF EXISTS rtc_sessions CASCADE;
CREATE TABLE rtc_sessions (
    session_id BIGSERIAL PRIMARY KEY,
    room_id BIGINT NOT NULL,
    session_key TEXT NOT NULL,     
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (room_id) REFERENCES rooms(room_id)
);
--------------------------플랜 엔티티들
-- 5. 룸 플랜 (방 전체의 대분류 계획, text로 구성 가능)
DROP TABLE IF EXISTS room_plans CASCADE;
CREATE TABLE room_plans (
    room_plan_id BIGSERIAL PRIMARY KEY,
    room_id BIGINT NOT NULL,              -- 어느 방의 계획인지
    title VARCHAR(100) NOT NULL,
    content TEXT,                         -- 설명
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
    user_id BIGINT NOT NULL,              -- 이 플랜을 작성/관리하는 유저
    title VARCHAR(100) NOT NULL,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (room_plan_id) REFERENCES room_plans(room_plan_id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
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
    sequence INT,                         -- 룸 플랜에서의 이동 순서
    cost DECIMAL(15, 2),                  -- 해당 장소 예상 비용
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (plan_id) REFERENCES plans(plan_id) ON DELETE CASCADE
);