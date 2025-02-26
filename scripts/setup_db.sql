CREATE EXTENSION IF NOT EXISTS btree_gist;
GRANT ALL PRIVILEGES ON DATABASE osm_db TO osmuser;

-- For activity Center view (experimental)
CREATE SCHEMA geoboundaries; -- For the admin boundaries
CREATE EXTENSION IF NOT EXISTS pg_cron;

CREATE TABLE IF NOT EXISTS changesets (
    id BIGINT PRIMARY KEY,
    username VARCHAR(255),
    uid INTEGER,
    created_at TIMESTAMPTZ,
    closed_at TIMESTAMPTZ,
    open BOOLEAN,
    num_changes INTEGER,
    comments_count INTEGER,
    tags JSONB,
    comments JSONB,
    bbox geometry(Geometry, 4326)
);

CREATE INDEX IF NOT EXISTS idx_changesets_bbox_username ON changesets USING GIST (bbox, username);
CREATE INDEX IF NOT EXISTS idx_changesets_username ON changesets using BTREE(username);
CREATE INDEX IF NOT EXISTS idx_changesets_closed_at ON changesets using BTREE(closed_at); -- for the materialized view

CREATE TABLE IF NOT EXISTS metadata (
    id SERIAL PRIMARY KEY,
    current_tip INTEGER,
    last_processed INTEGER,
    timestamp TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sequences (
    id SERIAL PRIMARY KEY,
    sequence_number INTEGER NOT NULL UNIQUE,
    ingested_at TIMESTAMP DEFAULT NOW(),
    status VARCHAR(20) NOT NULL CHECK (status IN ('pending', 'processing', 'success', 'failed', 'backfilled', 'empty')),
    error_message TEXT
);

CREATE INDEX idx_sequences_sequence_number ON sequences(sequence_number);
CREATE INDEX idx_sequences_status ON sequences(status);
CREATE INDEX idx_sequences_ingested_at ON sequences(ingested_at);

SELECT cron.schedule(
    'cleanup-old-changesets',
    '0 0 * * *',
    format('DELETE FROM changesets WHERE closed_at < NOW() - interval ''%s''',
           current_setting('app.retention_period'))
);
