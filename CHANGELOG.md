# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [v1.0.5] - 2025-02-16

### Added
- UI element showing who you are logged in as

### Changed
- 

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
