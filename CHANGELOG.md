# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.2.0] - 2025-09-03

### Added
- `Clear` button to clear drawn area and mappers table
- Geolocation button (implements #29)

### Fixed
- Dependency updates

### Removed
- OSM Auth (resolves #19)

## [1.0.10] - 2025-04-07

### Added
- Add map zoom in / out buttons

### Fixed
- Dependency updates.
- Use preferred OSM tile URL #20 - thanks @Dimitar5555

## [1.0.9] - 2025-03-02

### Added
- Permalink
- Share functionality for map views with URL parameters

### Changed

### Fixed
- Inconsistency in login / logout UI state

## [1.0.8] - 2025-03-01

### Added
- Username filter functionality to search for specific mappers
- Accessibility features including:
  - Skip to content link
  - ARIA labels and roles
  - Keyboard navigation improvements
  - Screen reader announcements
  - Improved focus styles
- Database state indicator showing when data was last updated

### Changed
- Improved UI with better color contrast for accessibility
- Enhanced user links with icon-based design
- Updated "Map long and prosper" message with Vulcan salute emoji
- Reorganized instructions in about page
- Optimized CSS structure and removed redundant styles
- Refactored JavaScript for better performance

### Fixed
- Various UI and layout issues
- Improved error handling

## [1.0.7] - 2025-02-27

### Added
- **Threaded Backfill:**  
  Introduced multi-threaded backfill scripts with improved error handling, retry logic (including exponential backoff), and a database connection pool for more robust concurrency.
- **CSV Export Function:**  
  A dedicated `exportToCsv()` function is now used with a single click listener, preventing multiple export dialogs from being triggered inadvertently.

### Changed
- **Table Sorting Logic:**  
  Removed external TableSort dependency in favor of a custom DOM-based sorting mechanism, which streamlines dependencies and simplifies maintenance.
- **Enhanced Network Resilience:**  
  Updated the replication file download logic to handle SSL/connection errors with specific retries and exponential backoff.
- **API & JS Refactoring:**  
  Aligned front-end JavaScript with API changes due to the new `tags`, `comments` (JSON), and `bbox` columns. Improved date parsing and display in `script.js`.
- **Docker & DB Configuration:**
  - Removed the external port mapping for PostgreSQL (`5432` no longer exposed on the host).
  - Expanded environment variables and Docker Compose settings for advanced Postgres usage and improved backfill scripts.

### Fixed
- **Duplicate CSV Exports:**  
  Addressed an issue where multiple CSV export event listeners were attached, causing duplicate export dialogs.
- **Date Parsing:**  
  Enhanced error handling around invalid date strings when parsing changeset data, reducing runtime exceptions.
- **Connection Stability:**  
  Created new sessions to avoid SSL and connection reuse issues, stabilizing concurrent downloads and database writes.

### Removed
- **TableSort Scripts & Styles:**  
  Deleted `tablesort.js`, `tablesort.css`, and associated references, replaced with a custom sorting solution.

### Dependency Updates
- **asyncpg** upgraded from `0.29.0` to `0.30.0`.
- **psycopg2-binary** upgraded from `2.9.9` to `2.9.10`.
- Minor upgrades merged via Dependabot for `aiofiles`, `black`, `pytest-cov`, and other packages.

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
