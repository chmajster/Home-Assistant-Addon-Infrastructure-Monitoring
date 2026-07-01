# Changelog

All notable changes to the **Monitoring Center** Home Assistant add-on are documented here.

## [0.5.6] - 2026-06-30

### Changed

- Monitor timeout now uses the global Settings value as the default while still honoring per-monitor `timeout_minutes` or `timeout_seconds` in monitor config.
- Added global `default_interval_seconds` setting as the default interval for new monitors.
- Added `SCHEMA_VERSION = 7` migration to fold legacy interval settings into `default_interval_seconds`.
- Added `SCHEMA_VERSION = 8` migration for runtime failure/recovery counters used by flapping protection.
- Added scheduler concurrency limiting, scheduler diagnostics, failure/recovery thresholds and retry delay settings.
- Added basic pytest coverage for timeout config, migrations, thresholds and concurrency, plus GitHub Actions CI.
- Bumped add-on and application metadata version to `0.5.6`.

## [0.5.5] - 2026-06-30

### Added

- Added compatible `GET /api/monitors/{id}`, `POST /api/monitors/{id}/enable`, and `POST /api/monitors/{id}/disable` endpoints.
- Added a `www` type alias mapped to the shared `http_hash` checker.
- Added `SCHEMA_VERSION = 6` migration to fold old `www`/`website` records into the shared WWW checker.

### Changed

- Renamed the main monitors UI label to `Monitoring` and clarified WWW monitor type labels in the form.
- Switched monitor enable/disable UI actions to the shared enable/disable endpoints.
- Bumped add-on and application metadata version to `0.5.5`.

## [0.5.4] - 2026-06-30

### Added

- Added a shared application version source in `monitoring_center.__version__`.
- Added `/ready` and extended `/api/diagnostics/full` diagnostics with app version, schema version, and SQLite statistics.
- Added SQLite pragmas, safer transaction handling, transactional monitor import, a database backup before migrations, and indexes for history and diagnostics queries.
- Added repository tooling files: `.gitignore`, `.dockerignore`, `.editorconfig`, and `pyproject.toml`.

### Changed

- Updated repository and add-on metadata to `https://github.com/chmajster/Home-Assistant-Monitoring`.
- Bumped add-on and application metadata version to `0.5.4`.

## [0.5.3] - 2026-06-30

### Fixed

- Added cache busting for frontend assets and disabled caching of the main HTML shell so the removed Websites tab does not remain visible after an add-on update.
- Bumped add-on and application metadata version to `0.5.3`.

## [0.5.2] - 2026-06-30

### Changed

- Moved monitor-specific actions out of monitor cards and table rows into the monitor detail view.
- Added clearer hover background for clickable monitor cards and table rows.
- Bumped add-on and application metadata version to `0.5.2`.

## [0.5.1] - 2026-06-30

### Changed

- Clarified monitor search labels in the shared Monitors view.
- Added monitor search/jump control to the monitor detail screen.
- Ensured monitor cards open the detail view while target links remain independently clickable.
- Bumped add-on and application metadata version to `0.5.1`.

## [0.5.0] - 2026-06-30

### Added

- Added a refreshed admin dashboard layout with last refresh information and richer monitor statistics.
- Added shared monitor filters for type, status, group, search, sorting, and card/table view mode.
- Added a responsive monitor table for larger installations.

### Changed

- Removed the separate Websites navigation entry and folded website monitors into the main Monitors view.
- Simplified monitor card actions with Service and More menus.
- Improved monitor cards with type-specific fields, readable targets, diagnostics, and status badges.
- Bumped add-on and application metadata version to `0.5.0`.

## [0.4.1] - 2026-06-30

### Fixed

- Added the add-on changelog file expected by Home Assistant Supervisor.
- Bumped add-on and application metadata version to `0.4.1`.

## [0.4.0] - 2026-06-30

### Added

- Added success and error toasts for monitor and settings operations.
- Added light/dark theme switching with local browser persistence.
- Added enable/disable actions for monitors without deleting them.
- Added monitor test without saving from the add/edit form.
- Added a dedicated live test run screen from monitor cards.
- Added website maintenance dialog with custom end date and quick modes: 30 minutes, 2 hours, and 24 hours.
- Added website check date and content hash display in cards, details, history, and test results.
- Added endpoint `POST /api/monitors/test`.

### Changed

- Unified timeout settings to `default_timeout_minutes` and `timeout_minutes`.
- Changed website size limit settings from KB to MB through `max_page_size_mb`.
- Improved the website monitor action layout.
- Updated add-on configuration, example options, translations, and documentation for the new timeout and page size fields.

### Fixed

- API validation errors no longer close the monitor form.
- Kept compatibility with legacy fields: `request_timeout_seconds`, `ping_timeout_seconds`, `timeout_seconds`, and `max_page_size_kb`.

## [0.3.2] - 2026-06-30

### Added

- Added light theme as the default UI theme.
- Added URL/name filtering and duplicate URL hiding in the Websites section.
- Added website monitor detail view with response history, SLO, and content snapshots.

### Fixed

- Added duplicate URL protection for HTTP and REST monitor types.

## [0.3.1] - 2026-06-18

### Fixed

- Removed the Alpine package install layer from the Docker build to avoid APK repository DNS failures.
- Replaced the external `ping` dependency with a Python ICMP implementation.
- Moved add-on build base image selection into `Dockerfile` and removed deprecated `build.yaml`.
- Vendored Python wheels so Supervisor can build the add-on without DNS access to PyPI.

## [0.3.0] - 2026-06-18

### Added

- Added monitor groups with group status, online/offline counts, and SLO statistics.
- Added maintenance mode for monitors and groups.
- Added SLO / uptime statistics for 24h, 7d, 30d, and 90d windows.
- Added Home Assistant event suppression during active maintenance mode.

### Changed

- Dashboard now shows global SLO / uptime.
- Configuration export now includes monitor groups.

## [0.2.0] - 2026-06-18

### Added

- Added plugin-based monitor types.
- Added monitor type and preset API endpoints.
- Added Ping, TCP, HTTP status, HTTP hash, DNS, SSL certificate, REST API, Home Assistant entity, and MQTT monitor types.
- Added Home Assistant events and type-specific sensors.

### Changed

- Replaced the old `device` / `website` monitor type model with extensible monitor types.
- Kept compatibility mapping for legacy monitor types.

## [0.1.0] - 2026-06-18

### Added

- Initial Monitoring Center Home Assistant add-on.
- Added FastAPI backend, SQLite storage, migrations, scheduler, web UI, diagnostics, history, import/export, Home Assistant entity publishing, and website snapshot diffing.
