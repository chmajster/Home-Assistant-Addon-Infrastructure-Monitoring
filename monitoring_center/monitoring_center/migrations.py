from __future__ import annotations

from .database import Database


SCHEMA_VERSION = 3


def migrate(db: Database) -> None:
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """
    )

    current = db.fetchone("SELECT MAX(version) AS version FROM schema_migrations")
    version = int(current["version"] or 0) if current else 0
    if version < 1:
        _migration_001(db)
        db.execute("INSERT INTO schema_migrations(version) VALUES (?)", (1,))
    if version < 2:
        _migration_002(db)
        db.execute("INSERT INTO schema_migrations(version) VALUES (?)", (2,))
    if version < 3:
        _migration_003(db)
        db.execute("INSERT INTO schema_migrations(version) VALUES (?)", (3,))


def _migration_001(db: Database) -> None:
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS monitors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL,
            name TEXT NOT NULL,
            target TEXT NOT NULL,
            interval_seconds INTEGER NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            config_json TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'unknown',
            last_response_ms REAL,
            last_http_status INTEGER,
            last_error TEXT,
            last_content_hash TEXT,
            last_checked_at TEXT,
            last_changed_at TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_monitors_type ON monitors(type);
        CREATE INDEX IF NOT EXISTS idx_monitors_enabled ON monitors(enabled);

        CREATE TABLE IF NOT EXISTS monitor_checks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            monitor_id INTEGER NOT NULL,
            checked_at TEXT NOT NULL DEFAULT (datetime('now')),
            status TEXT NOT NULL,
            response_ms REAL,
            http_status INTEGER,
            packet_loss REAL,
            error TEXT,
            previous_status TEXT,
            new_status TEXT,
            content_changed INTEGER NOT NULL DEFAULT 0,
            content_hash TEXT,
            details_json TEXT NOT NULL DEFAULT '{}',
            FOREIGN KEY(monitor_id) REFERENCES monitors(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_checks_monitor_time
            ON monitor_checks(monitor_id, checked_at DESC);
        CREATE INDEX IF NOT EXISTS idx_checks_status ON monitor_checks(status);

        CREATE TABLE IF NOT EXISTS website_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            monitor_id INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            content_hash TEXT NOT NULL,
            normalized_content TEXT NOT NULL,
            raw_excerpt TEXT,
            diff TEXT,
            FOREIGN KEY(monitor_id) REFERENCES monitors(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_snapshots_monitor_time
            ON website_snapshots(monitor_id, created_at DESC);

        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            monitor_id INTEGER,
            event_type TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            previous_state TEXT,
            new_state TEXT,
            payload_json TEXT NOT NULL DEFAULT '{}',
            delivered_to_ha INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY(monitor_id) REFERENCES monitors(id) ON DELETE SET NULL
        );

        CREATE INDEX IF NOT EXISTS idx_events_time ON events(created_at DESC);
        """
    )


def _migration_002(db: Database) -> None:
    db.executescript(
        """
        PRAGMA foreign_keys=OFF;

        DROP INDEX IF EXISTS idx_monitors_type;
        DROP INDEX IF EXISTS idx_monitors_enabled;

        CREATE TABLE IF NOT EXISTS monitors_v2 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL,
            name TEXT NOT NULL,
            target TEXT NOT NULL,
            interval_seconds INTEGER NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            config_json TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'unknown',
            last_response_ms REAL,
            last_http_status INTEGER,
            last_error TEXT,
            last_content_hash TEXT,
            last_checked_at TEXT,
            last_changed_at TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        INSERT INTO monitors_v2(
            id, type, name, target, interval_seconds, enabled, config_json,
            status, last_response_ms, last_http_status, last_error, last_content_hash,
            last_checked_at, last_changed_at, created_at, updated_at
        )
        SELECT
            id,
            CASE type
                WHEN 'device' THEN 'ping_host'
                WHEN 'website' THEN 'http_hash'
                ELSE type
            END,
            name, target, interval_seconds, enabled, config_json,
            status, last_response_ms, last_http_status, last_error, last_content_hash,
            last_checked_at, last_changed_at, created_at, updated_at
        FROM monitors;

        DROP TABLE monitors;
        ALTER TABLE monitors_v2 RENAME TO monitors;

        CREATE INDEX IF NOT EXISTS idx_monitors_type ON monitors(type);
        CREATE INDEX IF NOT EXISTS idx_monitors_enabled ON monitors(enabled);

        PRAGMA foreign_keys=ON;
        """
    )


def _migration_003(db: Database) -> None:
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS monitor_groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            description TEXT,
            color TEXT NOT NULL DEFAULT '#0f766e',
            maintenance_until TEXT,
            maintenance_reason TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        INSERT OR IGNORE INTO monitor_groups(name, description, color) VALUES
            ('Sieć domowa', 'Routery, przełączniki i podstawowa łączność LAN', '#0f766e'),
            ('Serwery', 'Usługi i hosty serwerowe', '#2563eb'),
            ('Strony WWW', 'Monitoring stron i endpointów HTTP', '#0891b2'),
            ('Home Assistant', 'Instancja Home Assistant i jej encje', '#f59e0b'),
            ('NAS', 'Macierze, SMB i usługi plikowe', '#16a34a');

        ALTER TABLE monitors ADD COLUMN group_id INTEGER REFERENCES monitor_groups(id) ON DELETE SET NULL;
        ALTER TABLE monitors ADD COLUMN maintenance_until TEXT;
        ALTER TABLE monitors ADD COLUMN maintenance_reason TEXT;

        CREATE INDEX IF NOT EXISTS idx_monitors_group ON monitors(group_id);
        CREATE INDEX IF NOT EXISTS idx_groups_maintenance ON monitor_groups(maintenance_until);
        CREATE INDEX IF NOT EXISTS idx_monitors_maintenance ON monitors(maintenance_until);
        """
    )
