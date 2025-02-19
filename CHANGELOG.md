# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

- cfb0334a79341a148e6d4358f2b9e8ebb83cd720 Fix model and ingest script to allow for changeset bounds that are points. When upgrading from a previous version, manually alter the `changesets` table:
```SQL
ALTER TABLE changesets 
ALTER COLUMN bbox TYPE geometry(Geometry,4326);
```
And convert the invalid polygons to valid points:
```
UPDATE changesets
SET bbox = ST_Point(
    ST_X(ST_PointN(ST_ExteriorRing(bbox), 1)),
    ST_Y(ST_PointN(ST_ExteriorRing(bbox), 1)),
    4326
)
WHERE ST_GeometryType(bbox) = 'ST_Polygon' 
AND ST_Area(bbox) = 0;
```
- 0937a9c071cbbd296c9dae8f82a514871a9f5ce4 Started experimenting with user activity centers
- 36c6b1eb56e5cf02d865c92865aff45343027032 Added links to github and mastodon in footer
- ec0855f738d372150571b3a39551053de038116e Added experimental activity view and the required plumbing for pg_cron to do the scheduld MV refresh. This will require a manual DB upgrade to install pg_cron, to be documented.
- 552b8a36ca9912aff499c9c4c095ffc696fdc9d5 Account for empty changesets 

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
