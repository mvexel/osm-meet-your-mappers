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
CREATE EXTENSION IF NOT EXISTS pg_cron;

CREATE MATERIALIZED VIEW user_activity_centers_mv AS
WITH normalized_geometries AS (
    SELECT 
        username,
        CASE 
            WHEN ST_GeometryType(bbox) = 'ST_Point' THEN bbox
            ELSE ST_Centroid(bbox)
        END AS point_geom,
        EXP(EXTRACT(EPOCH FROM (NOW() - created_at)) / -31536000.0) as time_weight
    FROM changesets
    WHERE bbox IS NOT NULL 
),
clustered_locations AS (
    SELECT 
        username,
        ST_ClusterDBSCAN(ST_SetSRID(point_geom, 4326), eps := 0.005, minpoints := 3) 
            over (PARTITION BY username) as cluster_id,
        point_geom,
        time_weight
    FROM normalized_geometries
),
cluster_centers AS (
    SELECT 
        username,
        cluster_id,
        ST_SetSRID(
            ST_MakePoint(
                SUM(ST_X(point_geom) * time_weight) / SUM(time_weight),
                SUM(ST_Y(point_geom) * time_weight) / SUM(time_weight)
            ), 
            4326
        ) as cluster_center,
        COUNT(*) as total_changesets,
        SUM(time_weight) as weighted_score
    FROM clustered_locations
    WHERE cluster_id IS NOT NULL
    GROUP BY username, cluster_id
),
cluster_stats AS (
    SELECT 
        c.username,
        c.cluster_id,
        c.cluster_center,
        c.total_changesets,
        c.weighted_score,
        MAX(ST_Distance(
            c.cluster_center::geography,
            l.point_geom::geography
        )) as radius_meters
    FROM cluster_centers c
    JOIN clustered_locations l ON 
        c.username = l.username AND 
        c.cluster_id = l.cluster_id
    GROUP BY 
        c.username, 
        c.cluster_id, 
        c.cluster_center, 
        c.total_changesets,
        c.weighted_score
),
ranked_clusters AS (
    SELECT 
        username,
        cluster_center,
        total_changesets,
        weighted_score,
        radius_meters,
        ROW_NUMBER() OVER (
            PARTITION BY username 
            ORDER BY weighted_score DESC
        ) as rank
    FROM cluster_stats
)
SELECT 
    username,
    ST_X(cluster_center) as lon,
    ST_Y(cluster_center) as lat,
    total_changesets,
    weighted_score,
    ROUND(radius_meters::numeric, 2) as radius_meters,
    cluster_center as location_point
FROM ranked_clusters
WHERE rank <= 5;

-- Create indexes on the materialized view
CREATE INDEX idx_user_activity_centers_mv_username 
ON user_activity_centers_mv(username);

CREATE INDEX idx_user_activity_centers_mv_spatial 
ON user_activity_centers_mv USING GIST(location_point);

-- Create a function to refresh the materialized view
CREATE OR REPLACE FUNCTION refresh_user_activity_centers_mv()
RETURNS void AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY user_activity_centers_mv;
END;
$$ LANGUAGE plpgsql;

-- Schedule the refresh to run every hour
SELECT cron.schedule('refresh_user_activity_centers', '0 * * * *', 'SELECT refresh_user_activity_centers_mv()');

-- Grant necessary permissions
GRANT SELECT ON user_activity_centers_mv TO osmuser;
