-- Additive migration in the FastAPI-owned database, never the Spring database.
ALTER TABLE place_embeddings ADD COLUMN IF NOT EXISTS chunk_generation BIGINT NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS retrieval_source_versions (
    source_id UUID NOT NULL,
    source_version VARCHAR(64) NOT NULL,
    document JSONB NOT NULL,
    stored_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (source_id, source_version)
);
CREATE TABLE IF NOT EXISTS retrieval_chunks (
    chunk_id UUID PRIMARY KEY,
    source_id UUID NOT NULL,
    source_version VARCHAR(64) NOT NULL,
    start_offset INTEGER NOT NULL CHECK (start_offset >= 0),
    end_offset INTEGER NOT NULL CHECK (end_offset > start_offset),
    splitter_version TEXT NOT NULL,
    chunk_text TEXT NOT NULL,
    FOREIGN KEY (source_id, source_version) REFERENCES retrieval_source_versions,
    UNIQUE (source_id, source_version, start_offset, end_offset, splitter_version)
);
CREATE TABLE IF NOT EXISTS retrieval_chunk_contexts (
    chunk_id UUID NOT NULL REFERENCES retrieval_chunks,
    context_version VARCHAR(64) NOT NULL,
    document JSONB NOT NULL,
    embedding VECTOR(1024),
    embedding_model TEXT NOT NULL DEFAULT 'BAAI/bge-m3',
    PRIMARY KEY (chunk_id, context_version)
);
CREATE TABLE IF NOT EXISTS retrieval_chunk_bundles (
    bundle_id VARCHAR(64) PRIMARY KEY,
    place_id BIGINT NOT NULL REFERENCES place_embeddings,
    place_fingerprint VARCHAR(64) NOT NULL,
    manifest JSONB NOT NULL,
    applied_order BIGSERIAL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_retrieval_bundle_place ON retrieval_chunk_bundles(place_id, applied_order DESC);
CREATE TABLE IF NOT EXISTS place_active_chunks (
    place_id BIGINT NOT NULL REFERENCES place_embeddings,
    slot SMALLINT NOT NULL CHECK (slot BETWEEN 1 AND 20),
    chunk_id UUID NOT NULL,
    context_version VARCHAR(64) NOT NULL,
    role TEXT NOT NULL DEFAULT 'subject' CHECK (role = 'subject'),
    PRIMARY KEY (place_id, slot),
    UNIQUE (place_id, chunk_id),
    FOREIGN KEY (chunk_id, context_version) REFERENCES retrieval_chunk_contexts
);
-- Slots enforce the per-place limit even for concurrent/direct SQL writers.
CREATE INDEX IF NOT EXISTS idx_retrieval_chunk_embedding ON retrieval_chunk_contexts
    USING hnsw (embedding vector_cosine_ops);

CREATE OR REPLACE FUNCTION enforce_active_chunk_subject() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM retrieval_chunk_contexts c
        WHERE c.chunk_id=NEW.chunk_id AND c.context_version=NEW.context_version
          AND c.document->'place_refs' @> jsonb_build_array(
              jsonb_build_object('place_id', NEW.place_id, 'role', 'subject'))
    ) THEN
        RAISE EXCEPTION 'Active chunk must explicitly describe the subject place' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS enforce_active_chunk_subject ON place_active_chunks;
CREATE TRIGGER enforce_active_chunk_subject BEFORE INSERT OR UPDATE ON place_active_chunks
    FOR EACH ROW EXECUTE FUNCTION enforce_active_chunk_subject();
