CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS place_embeddings (
    place_id BIGINT PRIMARY KEY,
    source_version BIGINT NOT NULL,
    latest_seen_version BIGINT NOT NULL,
    name VARCHAR(200) NOT NULL,
    description TEXT,
    region VARCHAR(100),
    city VARCHAR(50),
    category VARCHAR(50),
    source_category VARCHAR(50),
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,
    tour_content_id VARCHAR(50),
    image_url VARCHAR(500),
    homepage_url TEXT,
    embedding VECTOR(1024),
    document_status VARCHAR(20) NOT NULL DEFAULT 'READY'
        CHECK (document_status IN ('READY', 'DELETED')),
    index_config_version VARCHAR(100) NOT NULL DEFAULT 'bge-m3-v1',
    indexed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (source_version <= latest_seen_version)
);

CREATE INDEX IF NOT EXISTS idx_place_embeddings_region ON place_embeddings (region);
CREATE INDEX IF NOT EXISTS idx_place_embeddings_city ON place_embeddings (city);
CREATE INDEX IF NOT EXISTS idx_place_embeddings_category ON place_embeddings (category);
CREATE INDEX IF NOT EXISTS idx_place_embeddings_vector
    ON place_embeddings USING hnsw (embedding vector_cosine_ops);

CREATE TABLE IF NOT EXISTS place_index_jobs (
    job_id UUID PRIMARY KEY,
    event_id UUID NOT NULL UNIQUE,
    place_id BIGINT NOT NULL,
    source_version BIGINT NOT NULL,
    payload JSONB NOT NULL,
    status VARCHAR(24) NOT NULL DEFAULT 'PENDING'
        CHECK (status IN ('PENDING', 'RUNNING', 'SUCCEEDED', 'SUPERSEDED', 'FAILED')),
    attempt_count INTEGER NOT NULL DEFAULT 0,
    last_error_code VARCHAR(100),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS recommendation_requests (
    request_id UUID PRIMARY KEY,
    event_id UUID NOT NULL UNIQUE,
    context_version BIGINT NOT NULL,
    payload JSONB NOT NULL,
    status VARCHAR(24) NOT NULL DEFAULT 'PENDING'
        CHECK (status IN ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED')),
    attempt_count INTEGER NOT NULL DEFAULT 0,
    result_payload JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_recommendation_requests_pending
    ON recommendation_requests (created_at) WHERE status = 'PENDING';

CREATE TABLE IF NOT EXISTS recommendation_result_outbox (
    event_id UUID PRIMARY KEY,
    request_id UUID NOT NULL UNIQUE REFERENCES recommendation_requests(request_id),
    payload JSONB NOT NULL,
    published_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
