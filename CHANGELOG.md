# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

 ## [1.0.6] - 2025-02-24

 ### Added
 - Geo boundaries support with optimized Docker builds
 - Retention period environment variable for data management
 - Cron scheduling for automated tasks
 - Changeset cleanup job for database maintenance
 - Additional indices on changesets table
 - Retry delay mechanism for better resiliency

 ### Changed
 - Optimized materialized views with tweaks and indices
 - Improved archive loader resilience and performance
 - Enhanced database connection resilience with retry logic
 - Cleaned up Dockerfile and Docker Compose configuration
 - Updated database path in Docker Compose configuration
 - Added volume support for database persistence

 ### Fixed
 - Various naming inconsistencies
 - Improved documentation and README clarifications
 - Fixed environment variable documentation

### Notes

When upgrading from a previous version, you need to update the DB:
```SQL
 -- Add new indices for performance
 CREATE INDEX IF NOT EXISTS idx_changesets_closed_at ON changesets(closed_at);
 CREATE INDEX IF NOT EXISTS idx_user_activity_centers_mv_username ON user_activity_centers_mv(username);
 CREATE INDEX IF NOT EXISTS idx_user_activity_centers_mv_cluster_center ON user_activity_centers_mv USING GIST(cluster_center);

 -- Add pg_cron extension if not exists
 CREATE EXTENSION IF NOT EXISTS pg_cron;

 -- Schedule cleanup job
 SELECT cron.schedule(
     'cleanup-old-changesets',
     '0 0 * * *', -- Runs daily at midnight
     format('DELETE FROM changesets WHERE closed_at < NOW() - interval ''%s''',
            current_setting('app.retention_period'))
 );

 -- Create materialized view for user activity centers
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
 -- ... (rest of the materialized view definition from user_activity_centers.sql)

 -- Schedule MV refresh
 DO $$
 BEGIN
   PERFORM cron.schedule(
     'refresh-user-activity-centers',
     '0 * * * *', -- Runs every hour
     'REFRESH MATERIALIZED VIEW CONCURRENTLY user_activity_centers_mv'
   );
 END $$;

 -- Create geoboundaries schema and table
 CREATE SCHEMA IF NOT EXISTS geoboundaries;
 CREATE TABLE IF NOT EXISTS geoboundaries.adm1 (
     admin VARCHAR(255),
     name VARCHAR(255),
     geom GEOMETRY(MultiPolygon, 4326)
 );
 CREATE INDEX IF NOT EXISTS idx_adm1_admin_name ON geoboundaries.adm1(admin, name);
 ```

## [v1.0.5] - 2025-02-16

### Added

### Changed
- Updated UI to display logged-in user information in the top right corner

### Fixed
- OAuth problem with redirect URI


## [v1.0.4] - 2025-02-16

### Added
- UI behavior responsive to auth status

### Changed
- Styling updates

### Fixed
- Build system (I hate poetry)

## [v1.0.3] - 2025-02-16

### Added
- OAuth authentication and login/logout functionality
- Application version display in website footer
- Favicon to website
- "Logged in as <user>" display before logout link
- Poetry package management system

### Changed
- Refactored to read package version from pyproject.toml using tomli
- Updated and reordered dependencies
- Migrated Docker setup to use Poetry
- Updated README with Poetry installation and usage instructions
- Refactored API endpoints for authentication
- Improved script organization and cleanup

### Fixed
- OSM user object naming consistency

## [v1.0.2] - 2025-02-15

### Added
 - Added maximum age filter for changesets
   - Ensures only recent changesets are considered
   - Helps improve query performance and relevance

### Fixed
 - Fixed date parsing issues
   - Improved handling of various date formats
   - Added better error handling for invalid dates
 - Added username index for faster queries
   - Optimized database lookups by username
 - Dropped redundant spatial index
   - Removed unused index to improve write performance
 - Excluded huge changesets from processing
   - Added size-based filtering to prevent processing of extremely large changesets

## [v1.0.1] - 2025-02-15

### Changed
 - Reorganized mobile layout with button grouping and map positioning
 - Improved mobile responsiveness with adaptive layout and viewport settings
 - Improved button styling
 - Enhanced "Start Over" functionality

### Fixed
 - Fixed spatial query implementation
 - Corrected HTML formatting in documentation
 - Fixed map container layout issues

[Unreleased]: https://github.com/yourusername/yourrepo/compare/v1.0.3...HEAD
[v1.0.3]: https://github.com/yourusername/yourrepo/compare/v1.0.2...v1.0.3
[v1.0.2]: https://github.com/yourusername/yourrepo/tree/v1.0.2
[v1.0.0]: https://github.com/yourusername/yourrepo/tree/v1.0.0
