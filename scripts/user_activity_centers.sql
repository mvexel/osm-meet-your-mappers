-- The weighted score represents a time-decayed count of changesets. 
-- Clusters with more recent activity will have a higher weighted score 
-- compared to clusters with mostly older changesets.
--\
-- The radius represents the geographic dispersion of the cluster
-- Determined by the epsilon parameter for the DBScan function.

CREATE MATERIALIZED VIEW user_activity_centers_mv AS
WITH normalized_geometries AS (
    SELECT 
        username,
        CASE 
            WHEN ST_GeometryType(bbox) = 'ST_Point' THEN bbox
            ELSE ST_Centroid(bbox)
        END AS point_geom,
        EXP(EXTRACT(EPOCH FROM (NOW() - closed_at)) / -31536000.0) as time_weight
    FROM changesets
    WHERE bbox IS NOT NULL 
),
clustered_locations AS (
    SELECT 
        username,
        ST_ClusterDBSCAN(ST_SetSRID(point_geom, 4326), eps := 0.005, minpoints := 3) 
            OVER (PARTITION BY username) as cluster_id,
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
    JOIN clustered_locations l 
      ON c.username = l.username AND c.cluster_id = l.cluster_id
    GROUP BY 
        c.username, 
        c.cluster_id, 
        c.cluster_center, 
        c.total_changesets,
        c.weighted_score
),
ranked_clusters AS (
    SELECT 
        cluster_id,
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
    cluster_id,
    rc.username,
    cluster_center,
    rc.total_changesets,
    rc.weighted_score,
    ROUND(rc.radius_meters::numeric, 2) as radius_meters,
    rc.cluster_center as location_point,
    adm.admin as adm0,
    adm.name as adm1
FROM ranked_clusters rc
LEFT JOIN geoboundaries.adm1 adm
  ON ST_Within(rc.cluster_center, adm.geom)
WHERE rc.rank <= 5;

CREATE INDEX idx_adm1_admin_name ON geoboundaries.adm1(admin, name);
CREATE INDEX idx_user_activity_centers_mv_username ON user_activity_centers_mv(username);
CREATE INDEX idx_user_activity_centers_mv_cluster_center ON user_activity_centers_mv USING GIST(cluster_center);

-- Schedule refresh every 1h
DO $$
DECLARE
  r RECORD;
BEGIN
  FOR r IN SELECT jobid FROM cron.job WHERE jobname = 'refresh-user-activity-centers'
  LOOP
    PERFORM cron.unschedule(r.jobid);
  END LOOP;
  
  -- Now schedule the job
  PERFORM cron.schedule(
    'refresh-user-activity-centers',
    '0 * * * *',
    'REFRESH MATERIALIZED VIEW CONCURRENTLY user_activity_centers_mv'
  );
END$$;
