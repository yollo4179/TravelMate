ALTER TABLE places
    ADD COLUMN IF NOT EXISTS content_version BIGINT NOT NULL DEFAULT 1;

CREATE TABLE IF NOT EXISTS place_change_outbox (
    event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    place_id BIGINT NOT NULL,
    source_version BIGINT NOT NULL,
    event_type VARCHAR(32) NOT NULL CHECK (event_type IN ('PLACE_UPSERTED', 'PLACE_DELETED')),
    schema_version INTEGER NOT NULL DEFAULT 1,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    published_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_place_change_outbox_pending
    ON place_change_outbox (created_at) WHERE published_at IS NULL;

CREATE TABLE IF NOT EXISTS recommendation_requests (
    request_id UUID PRIMARY KEY,
    context_version BIGINT NOT NULL,
    request_payload JSONB NOT NULL,
    status VARCHAR(24) NOT NULL DEFAULT 'PENDING'
        CHECK (status IN ('PENDING', 'PUBLISHED', 'COMPLETED', 'FAILED')),
    result_payload JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS recommendation_request_outbox (
    event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id UUID NOT NULL UNIQUE REFERENCES recommendation_requests(request_id),
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    published_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_recommendation_request_outbox_pending
    ON recommendation_request_outbox (created_at) WHERE published_at IS NULL;

CREATE TABLE IF NOT EXISTS recommendation_result_inbox (
    event_id UUID PRIMARY KEY,
    request_id UUID NOT NULL UNIQUE REFERENCES recommendation_requests(request_id),
    payload JSONB NOT NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE OR REPLACE FUNCTION enqueue_place_change()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    changed_place RECORD;
    next_version BIGINT;
    change_type VARCHAR(32);
    snapshot JSONB;
    generated_event_id UUID := gen_random_uuid();
BEGIN
    IF TG_OP = 'DELETE' THEN
        changed_place := OLD;
        next_version := OLD.content_version + 1;
        change_type := 'PLACE_DELETED';
        snapshot := NULL;
    ELSE
        changed_place := NEW;
        next_version := NEW.content_version;
        change_type := 'PLACE_UPSERTED';
        snapshot := jsonb_build_object(
            'name', NEW.name,
            'description', NEW.description,
            'region', NEW.region,
            'city', NEW.city,
            'category', NEW.category,
            'source_category', NEW.source_category,
            'latitude', NEW.latitude,
            'longitude', NEW.longitude,
            'tour_content_id', NEW.tour_content_id,
            'image_url', NEW.image_url,
            'homepage_url', NEW.homepage_url
        );
    END IF;

    INSERT INTO place_change_outbox (event_id, place_id, source_version, event_type, payload)
    VALUES (
        generated_event_id,
        changed_place.id,
        next_version,
        change_type,
        jsonb_build_object(
            'schema_version', 1,
            'event_id', generated_event_id,
            'event_type', change_type,
            'place_id', changed_place.id,
            'source_version', next_version,
            'occurred_at', now(),
            'source', snapshot
        )
    );
    RETURN NULL;
END;
$$;

CREATE OR REPLACE FUNCTION increment_place_content_version()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.content_version := OLD.content_version + 1;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_places_content_version ON places;
CREATE TRIGGER trg_places_content_version
BEFORE UPDATE ON places
FOR EACH ROW EXECUTE FUNCTION increment_place_content_version();

DROP TRIGGER IF EXISTS trg_places_change_outbox_insert ON places;
CREATE TRIGGER trg_places_change_outbox_insert
AFTER INSERT ON places
FOR EACH ROW EXECUTE FUNCTION enqueue_place_change();

DROP TRIGGER IF EXISTS trg_places_change_outbox_update ON places;
CREATE TRIGGER trg_places_change_outbox_update
AFTER UPDATE ON places
FOR EACH ROW EXECUTE FUNCTION enqueue_place_change();

DROP TRIGGER IF EXISTS trg_places_change_outbox_delete ON places;
CREATE TRIGGER trg_places_change_outbox_delete
AFTER DELETE ON places
FOR EACH ROW EXECUTE FUNCTION enqueue_place_change();

INSERT INTO place_change_outbox (event_id, place_id, source_version, event_type, payload)
SELECT
    places.event_id,
    places.id,
    places.content_version,
    'PLACE_UPSERTED',
    jsonb_build_object(
        'schema_version', 1,
        'event_id', places.event_id,
        'event_type', 'PLACE_UPSERTED',
        'place_id', places.id,
        'source_version', places.content_version,
        'occurred_at', now(),
        'source', jsonb_build_object(
            'name', places.name,
            'description', places.description,
            'region', places.region,
            'city', places.city,
            'category', places.category,
            'source_category', places.source_category,
            'latitude', places.latitude,
            'longitude', places.longitude,
            'tour_content_id', places.tour_content_id,
            'image_url', places.image_url,
            'homepage_url', places.homepage_url
        )
    )
FROM (
    SELECT source_place.*, gen_random_uuid() AS event_id
    FROM places source_place
) places
WHERE NOT EXISTS (
    SELECT 1 FROM place_change_outbox event
    WHERE event.place_id = places.id AND event.source_version = places.content_version
      AND event.event_type = 'PLACE_UPSERTED'
);
