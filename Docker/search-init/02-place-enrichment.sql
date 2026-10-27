ALTER TABLE place_embeddings ADD COLUMN IF NOT EXISTS search_description TEXT;
ALTER TABLE place_embeddings ADD COLUMN IF NOT EXISTS enrichment_snapshot_id UUID;

CREATE TABLE IF NOT EXISTS place_enrichment_snapshots (
    snapshot_id UUID PRIMARY KEY,
    place_id BIGINT NOT NULL REFERENCES place_embeddings(place_id),
    source_version BIGINT NOT NULL,
    source_fingerprint VARCHAR(64) NOT NULL,
    request_hash VARCHAR(64) NOT NULL,
    record JSONB NOT NULL,
    raw_response JSONB NOT NULL,
    collected_at TIMESTAMPTZ NOT NULL,
    stored_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_place_enrichment_source
    ON place_enrichment_snapshots (place_id, source_fingerprint, collected_at DESC, snapshot_id DESC);
