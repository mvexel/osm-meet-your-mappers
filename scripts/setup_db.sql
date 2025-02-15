CREATE EXTENSION IF NOT EXISTS btree_gist;
GRANT ALL PRIVILEGES ON DATABASE osm_db TO osmuser;


CREATE TABLE IF NOT EXISTS changesets (
    id SERIAL PRIMARY KEY,
    username VARCHAR(255),
    uid INTEGER,
    created_at TIMESTAMP,
    closed_at TIMESTAMP,
    open BOOLEAN,
    num_changes INTEGER,
    comments_count INTEGER,
    min_lat DOUBLE PRECISION,
    min_lon DOUBLE PRECISION,
    max_lat DOUBLE PRECISION,
    max_lon DOUBLE PRECISION,
    bbox geometry(POLYGON, 4326)
);

CREATE INDEX IF NOT EXISTS idx_changesets_bbox_username ON changesets USING GIST (bbox, username);
CREATE INDEX IF NOT EXISTS idx_changesets_username ON changesets using BTREE;

CREATE TABLE IF NOT EXISTS changeset_tags (
    id SERIAL PRIMARY KEY,
    changeset_id INTEGER REFERENCES changesets(id) ON DELETE CASCADE,
    k VARCHAR(255),
    v VARCHAR(255)
);

CREATE INDEX idx_changeset_tags_changeset_id ON changeset_tags(changeset_id);
CREATE INDEX idx_changeset_tags_changeset_id_k ON changeset_tags(changeset_id, k);


CREATE TABLE IF NOT EXISTS changeset_comments (
    id SERIAL PRIMARY KEY,
    changeset_id INTEGER REFERENCES changesets(id) ON DELETE CASCADE,
    uid INTEGER,
    username VARCHAR(255),
    date TIMESTAMP,
    text TEXT
);

CREATE INDEX idx_changeset_comments_changeset_id ON changeset_comments(changeset_id);
CREATE INDEX idx_changeset_comments_uid ON changeset_comments(uid);
CREATE INDEX idx_changeset_comments_date ON changeset_comments(date);

CREATE TABLE IF NOT EXISTS metadata (
    id SERIAL PRIMARY KEY,
    current_tip INTEGER,
    last_processed INTEGER,
    timestamp TIMESTAMP
);
