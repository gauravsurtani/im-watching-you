-- Initial schema for lifelogger
-- This file is automatically executed when TimescaleDB container starts

-- Enable TimescaleDB extension
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- Main activity events table
CREATE TABLE IF NOT EXISTS activity_events (
    id BIGSERIAL,
    timestamp TIMESTAMPTZ NOT NULL,
    device_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    app_name TEXT,
    window_title TEXT,
    duration_seconds DOUBLE PRECISION,
    data JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (id, timestamp)
);

-- Convert to hypertable for time-series optimization
SELECT create_hypertable('activity_events', 'timestamp', if_not_exists => TRUE);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_activity_device_timestamp
    ON activity_events (device_id, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_activity_event_type
    ON activity_events (event_type, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_activity_app_name
    ON activity_events (app_name, timestamp DESC)
    WHERE app_name IS NOT NULL;

-- GIN index for JSONB queries
CREATE INDEX IF NOT EXISTS idx_activity_data_gin
    ON activity_events USING GIN (data);

-- Continuous aggregate for daily app usage (auto-refreshed)
CREATE MATERIALIZED VIEW IF NOT EXISTS daily_app_usage
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 day', timestamp) AS day,
    device_id,
    app_name,
    SUM(duration_seconds) as total_seconds,
    COUNT(*) as event_count
FROM activity_events
WHERE event_type = 'app_usage' AND app_name IS NOT NULL
GROUP BY day, device_id, app_name
WITH NO DATA;

-- Refresh policy for continuous aggregate
SELECT add_continuous_aggregate_policy('daily_app_usage',
    start_offset => INTERVAL '3 days',
    end_offset => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists => TRUE
);

-- Devices table for tracking connected devices
CREATE TABLE IF NOT EXISTS devices (
    device_id TEXT PRIMARY KEY,
    device_name TEXT NOT NULL,
    platform TEXT NOT NULL,
    last_sync TIMESTAMPTZ,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    metadata JSONB
);

-- Digests table for storing generated summaries
CREATE TABLE IF NOT EXISTS daily_digests (
    id SERIAL PRIMARY KEY,
    digest_date DATE UNIQUE NOT NULL,
    summary TEXT NOT NULL,
    top_apps JSONB,
    topics JSONB,
    action_items JSONB,
    raw_response TEXT,
    generated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Sync status tracking
CREATE TABLE IF NOT EXISTS sync_status (
    id SERIAL PRIMARY KEY,
    device_id TEXT REFERENCES devices(device_id),
    file_path TEXT NOT NULL,
    file_hash TEXT NOT NULL,
    processed_at TIMESTAMPTZ DEFAULT NOW(),
    event_count INTEGER,
    UNIQUE(device_id, file_path, file_hash)
);

-- Retention policy: auto-delete old data (configurable)
-- Uncomment and adjust interval as needed:
-- SELECT add_retention_policy('activity_events', INTERVAL '1 year', if_not_exists => TRUE);
