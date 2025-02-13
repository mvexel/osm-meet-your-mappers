CREATE TABLE changesets (
    id SERIAL PRIMARY KEY,
    user VARCHAR(255),
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
    bbox GEOMETRY
);

CREATE TABLE changeset_tags (
    id SERIAL PRIMARY KEY,
    changeset_id INTEGER REFERENCES changesets(id) ON DELETE CASCADE,
    k VARCHAR(255),
    v VARCHAR(255)
);

CREATE TABLE changeset_comments (
    id SERIAL PRIMARY KEY,
    changeset_id INTEGER REFERENCES changesets(id) ON DELETE CASCADE,
    uid INTEGER,
    user VARCHAR(255),
    date TIMESTAMP,
    text TEXT
);

CREATE TABLE metadata (
    id SERIAL PRIMARY KEY,
    state VARCHAR(255),
    timestamp TIMESTAMP
);
