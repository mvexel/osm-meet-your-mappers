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
    bbox geometry(Geometry, 4326)
);

CREATE INDEX IF NOT EXISTS idx_changesets_bbox_username ON changesets USING GIST (bbox, username);
CREATE INDEX IF NOT EXISTS idx_changesets_username ON changesets using BTREE(username);

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

-- Activity Center view (experimental)

CREATE OR REPLACE VIEW user_activity_centers AS
WITH normalized_geometries AS (
    SELECT 
        username,
        CASE 
            WHEN ST_GeometryType(bbox) = 'ST_Point' THEN bbox
            ELSE ST_Centroid(bbox)
        END AS point_geom
    FROM changesets
    WHERE bbox IS NOT NULL 
),
clustered_locations AS (
    SELECT 
        username,
        -- eps: 0.005 (roughly 500m) for granular clusters
        ST_ClusterDBSCAN(ST_SetSRID(point_geom, 4326), eps := 0.005, minpoints := 3) 
            over (PARTITION BY username) as cluster_id,
        point_geom
    FROM normalized_geometries
),
cluster_stats AS (
    SELECT 
        username,
        cluster_id,
        ST_SetSRID(ST_Centroid(ST_Collect(point_geom)), 4326) as cluster_center,
        COUNT(*) as changeset_count
    FROM clustered_locations
    WHERE cluster_id IS NOT NULL
    GROUP BY username, cluster_id
),
ranked_clusters AS (
    SELECT 
        username,
        cluster_center,
        changeset_count,
        ROW_NUMBER() OVER (
            PARTITION BY username 
            ORDER BY changeset_count DESC
        ) as rank
    FROM cluster_stats
)
SELECT 
    username,
    ST_X(cluster_center) as lon,
    ST_Y(cluster_center) as lat,
    changeset_count,
    cluster_center as location_point
FROM ranked_clusters
WHERE rank <= 5;  -- Show top 5 activity centers
