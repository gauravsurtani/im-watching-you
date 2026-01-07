-- Full-text search support for lifelogger
-- Run this migration after 001_initial_schema.sql

-- Enable pg_trgm for fuzzy matching
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Add generated column for full-text search vector
ALTER TABLE activity_events
ADD COLUMN IF NOT EXISTS search_vector tsvector
GENERATED ALWAYS AS (
    setweight(to_tsvector('english', coalesce(app_name, '')), 'A') ||
    setweight(to_tsvector('english', coalesce(window_title, '')), 'B') ||
    setweight(to_tsvector('english', coalesce(url, '')), 'C')
) STORED;

-- Create GIN index for full-text search
CREATE INDEX IF NOT EXISTS idx_activity_search_vector
    ON activity_events USING GIN (search_vector);

-- Create trigram indexes for fuzzy matching
CREATE INDEX IF NOT EXISTS idx_activity_title_trgm
    ON activity_events USING GIN (window_title gin_trgm_ops)
    WHERE window_title IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_activity_app_trgm
    ON activity_events USING GIN (app_name gin_trgm_ops)
    WHERE app_name IS NOT NULL;

-- Function for searching events
CREATE OR REPLACE FUNCTION search_activity_events(
    search_query TEXT,
    from_date TIMESTAMPTZ DEFAULT NOW() - INTERVAL '7 days',
    to_date TIMESTAMPTZ DEFAULT NOW(),
    max_results INTEGER DEFAULT 100
)
RETURNS TABLE (
    id BIGINT,
    timestamp TIMESTAMPTZ,
    device_id TEXT,
    source TEXT,
    app_name TEXT,
    window_title TEXT,
    url TEXT,
    duration_seconds DOUBLE PRECISION,
    rank REAL
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        ae.id,
        ae.timestamp,
        ae.device_id,
        ae.source,
        ae.app_name,
        ae.window_title,
        ae.url,
        ae.duration_seconds,
        ts_rank(ae.search_vector, plainto_tsquery('english', search_query)) as rank
    FROM activity_events ae
    WHERE ae.timestamp BETWEEN from_date AND to_date
    AND ae.search_vector @@ plainto_tsquery('english', search_query)
    ORDER BY rank DESC, ae.timestamp DESC
    LIMIT max_results;
END;
$$ LANGUAGE plpgsql;

-- Function for fuzzy search (slower but finds partial matches)
CREATE OR REPLACE FUNCTION fuzzy_search_activity_events(
    search_query TEXT,
    from_date TIMESTAMPTZ DEFAULT NOW() - INTERVAL '7 days',
    to_date TIMESTAMPTZ DEFAULT NOW(),
    similarity_threshold REAL DEFAULT 0.3,
    max_results INTEGER DEFAULT 100
)
RETURNS TABLE (
    id BIGINT,
    timestamp TIMESTAMPTZ,
    device_id TEXT,
    source TEXT,
    app_name TEXT,
    window_title TEXT,
    url TEXT,
    similarity REAL
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        ae.id,
        ae.timestamp,
        ae.device_id,
        ae.source,
        ae.app_name,
        ae.window_title,
        ae.url,
        GREATEST(
            similarity(ae.window_title, search_query),
            similarity(ae.app_name, search_query)
        ) as sim
    FROM activity_events ae
    WHERE ae.timestamp BETWEEN from_date AND to_date
    AND (
        similarity(ae.window_title, search_query) > similarity_threshold
        OR similarity(ae.app_name, search_query) > similarity_threshold
    )
    ORDER BY sim DESC, ae.timestamp DESC
    LIMIT max_results;
END;
$$ LANGUAGE plpgsql;

-- Add full-text search to transcripts in data column
CREATE OR REPLACE FUNCTION search_transcripts(
    search_query TEXT,
    from_date TIMESTAMPTZ DEFAULT NOW() - INTERVAL '30 days',
    to_date TIMESTAMPTZ DEFAULT NOW(),
    max_results INTEGER DEFAULT 50
)
RETURNS TABLE (
    id BIGINT,
    timestamp TIMESTAMPTZ,
    device_id TEXT,
    full_text TEXT,
    rank REAL
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        ae.id,
        ae.timestamp,
        ae.device_id,
        ae.data->>'full_text' as full_text,
        ts_rank(
            to_tsvector('english', coalesce(ae.data->>'full_text', '')),
            plainto_tsquery('english', search_query)
        ) as rank
    FROM activity_events ae
    WHERE ae.source = 'transcript'
    AND ae.timestamp BETWEEN from_date AND to_date
    AND to_tsvector('english', coalesce(ae.data->>'full_text', ''))
        @@ plainto_tsquery('english', search_query)
    ORDER BY rank DESC, ae.timestamp DESC
    LIMIT max_results;
END;
$$ LANGUAGE plpgsql;
