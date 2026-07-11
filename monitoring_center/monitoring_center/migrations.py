from __future__ import annotations

from datetime import UTC, datetime

from .database import Database, dumps_json, loads_json

SCHEMA_VERSION = 14


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
    if 0 < version < SCHEMA_VERSION:
        _backup_database(db)
    if version < 1:
        _migration_001(db)
        db.execute("INSERT INTO schema_migrations(version) VALUES (?)", (1,))
    if version < 2:
        _migration_002(db)
        db.execute("INSERT INTO schema_migrations(version) VALUES (?)", (2,))
    if version < 3:
        _migration_003(db)
        db.execute("INSERT INTO schema_migrations(version) VALUES (?)", (3,))
    if version < 4:
        _migration_004(db)
        db.execute("INSERT INTO schema_migrations(version) VALUES (?)", (4,))
    if version < 5:
        _migration_005(db)
        db.execute("INSERT INTO schema_migrations(version) VALUES (?)", (5,))
    if version < 6:
        _migration_006(db)
        db.execute("INSERT INTO schema_migrations(version) VALUES (?)", (6,))
    if version < 7:
        _migration_007(db)
        db.execute("INSERT INTO schema_migrations(version) VALUES (?)", (7,))
    if version < 8:
        _migration_008(db)
        db.execute("INSERT INTO schema_migrations(version) VALUES (?)", (8,))
    if version < 9:
        _migration_009(db)
        db.execute("INSERT INTO schema_migrations(version) VALUES (?)", (9,))
    if version < 10:
        _migration_010(db)
        db.execute("INSERT INTO schema_migrations(version) VALUES (?)", (10,))
    if version < 11:
        _migration_011(db)
        db.execute("INSERT INTO schema_migrations(version) VALUES (?)", (11,))
    if version < 12:
        _migration_012(db)
        db.execute("INSERT INTO schema_migrations(version) VALUES (?)", (12,))
    if version < 13:
        _migration_013(db)
        db.execute("INSERT INTO schema_migrations(version) VALUES (?)", (13,))
    if version < 14:
        _migration_014(db)
        db.execute("INSERT INTO schema_migrations(version) VALUES (?)", (14,))


def _backup_database(db: Database) -> None:
    if not db.path.exists() or db.path.stat().st_size == 0:
        return
    version = db.fetchone("SELECT MAX(version) AS version FROM schema_migrations")
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    schema_version = int(version["version"] or 0) if version else 0
    backup_path = db.path.with_suffix(f"{db.path.suffix}.schema-{schema_version}.{stamp}.bak")
    db.backup(backup_path)
    backups = sorted(db.path.parent.glob(f"{db.path.name}.schema-*.bak"), reverse=True)
    for old in backups[5:]:
        old.unlink(missing_ok=True)


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


def _migration_004(db: Database) -> None:
    settings = {
        row["key"]: loads_json(row["value"], row["value"]) for row in db.fetchall("SELECT key, value FROM settings")
    }
    if "default_timeout_minutes" not in settings:
        timeout_seconds = settings.get("request_timeout_seconds", settings.get("ping_timeout_seconds", 300))
        db.execute(
            """
            INSERT INTO settings(key, value, updated_at) VALUES ('default_timeout_minutes', ?, datetime('now'))
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = datetime('now')
            """,
            (dumps_json(max(_safe_float(timeout_seconds, 300) / 60, 1 / 60)),),
        )
    if "max_page_size_mb" not in settings:
        max_page_size_kb = settings.get("max_page_size_kb", 512)
        db.execute(
            """
            INSERT INTO settings(key, value, updated_at) VALUES ('max_page_size_mb', ?, datetime('now'))
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = datetime('now')
            """,
            (dumps_json(max(_safe_float(max_page_size_kb, 512) / 1024, 1 / 1024)),),
        )
    db.execute(
        "DELETE FROM settings WHERE key IN ('request_timeout_seconds', 'ping_timeout_seconds', 'max_page_size_kb')"
    )

    for row in db.fetchall("SELECT id, config_json FROM monitors"):
        config = loads_json(row.get("config_json"), {})
        changed = False
        if "timeout_minutes" not in config and "timeout_seconds" in config:
            try:
                config["timeout_minutes"] = _safe_float(config.pop("timeout_seconds"), 300) / 60
                changed = True
            except (TypeError, ValueError):
                config.pop("timeout_seconds", None)
                changed = True
        if "max_page_size_mb" not in config and "max_page_size_kb" in config:
            try:
                config["max_page_size_mb"] = _safe_float(config.pop("max_page_size_kb"), 512) / 1024
                changed = True
            except (TypeError, ValueError):
                config.pop("max_page_size_kb", None)
                changed = True
        if changed:
            db.execute(
                "UPDATE monitors SET config_json = ?, updated_at = datetime('now') WHERE id = ?",
                (dumps_json(config), row["id"]),
            )


def _safe_float(value: object, default: float) -> float:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return default


def _migration_005(db: Database) -> None:
    db.executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_checks_time
            ON monitor_checks(checked_at DESC);
        CREATE INDEX IF NOT EXISTS idx_checks_status_time
            ON monitor_checks(status, checked_at DESC);
        CREATE INDEX IF NOT EXISTS idx_checks_changed_time
            ON monitor_checks(content_changed, checked_at DESC);
        CREATE INDEX IF NOT EXISTS idx_events_type_time
            ON events(event_type, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_monitors_status
            ON monitors(status);
        CREATE INDEX IF NOT EXISTS idx_monitors_enabled_type
            ON monitors(enabled, type);
        """
    )


def _migration_006(db: Database) -> None:
    db.execute("UPDATE monitors SET type = 'http_hash', updated_at = datetime('now') WHERE type IN ('website', 'www')")


def _migration_007(db: Database) -> None:
    settings = {
        row["key"]: loads_json(row["value"], row["value"]) for row in db.fetchall("SELECT key, value FROM settings")
    }
    if "default_interval_seconds" not in settings:
        interval = settings.get("default_website_interval", settings.get("default_device_interval", 300))
        db.execute(
            """
            INSERT INTO settings(key, value, updated_at) VALUES ('default_interval_seconds', ?, datetime('now'))
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = datetime('now')
            """,
            (dumps_json(max(int(_safe_float(interval, 300)), 5)),),
        )
    db.execute("DELETE FROM settings WHERE key IN ('default_device_interval', 'default_website_interval')")


def _migration_008(db: Database) -> None:
    db.executescript(
        """
        ALTER TABLE monitors ADD COLUMN failure_count INTEGER NOT NULL DEFAULT 0;
        ALTER TABLE monitors ADD COLUMN recovery_count INTEGER NOT NULL DEFAULT 0;
        ALTER TABLE monitors ADD COLUMN last_raw_status TEXT;
        """
    )


def _migration_009(db: Database) -> None:
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS incidents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            monitor_id INTEGER NOT NULL,
            started_at TEXT NOT NULL,
            ended_at TEXT,
            status TEXT NOT NULL DEFAULT 'open',
            root_status TEXT NOT NULL,
            last_error TEXT,
            check_count INTEGER NOT NULL DEFAULT 1,
            duration_seconds REAL NOT NULL DEFAULT 0,
            FOREIGN KEY(monitor_id) REFERENCES monitors(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_incidents_monitor_time
            ON incidents(monitor_id, started_at DESC);
        CREATE INDEX IF NOT EXISTS idx_incidents_status_time
            ON incidents(status, started_at DESC);
        CREATE INDEX IF NOT EXISTS idx_incidents_open
            ON incidents(monitor_id, status, ended_at);
        """
    )


def _migration_010(db: Database) -> None:
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS topology_nodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            type TEXT NOT NULL DEFAULT 'other',
            monitor_id INTEGER,
            icon TEXT,
            x REAL NOT NULL DEFAULT 0,
            y REAL NOT NULL DEFAULT 0,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY(monitor_id) REFERENCES monitors(id) ON DELETE SET NULL
        );

        CREATE INDEX IF NOT EXISTS idx_topology_nodes_monitor
            ON topology_nodes(monitor_id);
        CREATE INDEX IF NOT EXISTS idx_topology_nodes_type
            ON topology_nodes(type);

        CREATE TABLE IF NOT EXISTS topology_edges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_node_id INTEGER NOT NULL,
            target_node_id INTEGER NOT NULL,
            label TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY(source_node_id) REFERENCES topology_nodes(id) ON DELETE CASCADE,
            FOREIGN KEY(target_node_id) REFERENCES topology_nodes(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_topology_edges_source
            ON topology_edges(source_node_id);
        CREATE INDEX IF NOT EXISTS idx_topology_edges_target
            ON topology_edges(target_node_id);
        """
    )


def _migration_011(db: Database) -> None:
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS scheduler_state (
            monitor_id INTEGER PRIMARY KEY,
            next_check_at TEXT NOT NULL,
            last_started_at TEXT,
            last_finished_at TEXT,
            last_duration_ms REAL,
            last_scheduler_error TEXT,
            consecutive_scheduler_errors INTEGER NOT NULL DEFAULT 0,
            last_skip_reason TEXT,
            FOREIGN KEY(monitor_id) REFERENCES monitors(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_scheduler_due ON scheduler_state(next_check_at, monitor_id);
        INSERT OR IGNORE INTO scheduler_state(monitor_id, next_check_at)
          SELECT id, datetime('now', '+' || (abs(id * 1103515245) % 30) || ' seconds') FROM monitors;

        CREATE TABLE IF NOT EXISTS monitor_runtime (
            monitor_id INTEGER PRIMARY KEY,
            last_dns_result_json TEXT,
            last_ha_state TEXT,
            last_output_hash TEXT,
            last_anomaly_json TEXT,
            alert_state_json TEXT,
            last_alert_at TEXT,
            alert_repeat_count INTEGER NOT NULL DEFAULT 0,
            alert_delivery_state TEXT,
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY(monitor_id) REFERENCES monitors(id) ON DELETE CASCADE
        );
        INSERT OR IGNORE INTO monitor_runtime(monitor_id) SELECT id FROM monitors;
        """
    )
    runtime_keys = {"last_dns_result", "last_ha_state", "last_hash", "last_output_hash", "last_anomaly", "_alert_state"}
    for row in db.fetchall("SELECT id, config_json FROM monitors"):
        config = loads_json(row["config_json"], {})
        runtime = {key: config.pop(key) for key in list(config) if key in runtime_keys}
        if runtime:
            db.execute(
                """UPDATE monitor_runtime SET last_dns_result_json=?, last_ha_state=?, last_output_hash=?,
                   last_anomaly_json=?, alert_state_json=?, updated_at=datetime('now') WHERE monitor_id=?""",
                (
                    dumps_json(runtime.get("last_dns_result")) if "last_dns_result" in runtime else None,
                    runtime.get("last_ha_state"),
                    runtime.get("last_output_hash") or runtime.get("last_hash"),
                    dumps_json(runtime.get("last_anomaly")) if "last_anomaly" in runtime else None,
                    dumps_json(runtime.get("_alert_state")) if "_alert_state" in runtime else None,
                    row["id"],
                ),
            )
            db.execute("UPDATE monitors SET config_json=? WHERE id=?", (dumps_json(config), row["id"]))


def _migration_012(db: Database) -> None:
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS monitor_secrets (
            monitor_id INTEGER NOT NULL,
            field TEXT NOT NULL,
            encrypted_value TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY(monitor_id, field),
            FOREIGN KEY(monitor_id) REFERENCES monitors(id) ON DELETE CASCADE
        );
        """
    )


def _migration_013(db: Database) -> None:
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS alert_deliveries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            monitor_id INTEGER NOT NULL,
            incident_id INTEGER,
            channel TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}',
            attempted_at TEXT,
            result TEXT NOT NULL DEFAULT 'pending',
            response_code INTEGER,
            error TEXT,
            attempt_count INTEGER NOT NULL DEFAULT 0,
            next_attempt_at TEXT NOT NULL DEFAULT (datetime('now')),
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY(monitor_id) REFERENCES monitors(id) ON DELETE CASCADE,
            FOREIGN KEY(incident_id) REFERENCES incidents(id) ON DELETE SET NULL
        );
        CREATE INDEX IF NOT EXISTS idx_alert_delivery_due ON alert_deliveries(result, next_attempt_at, id);
        CREATE TABLE IF NOT EXISTS incident_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            incident_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            comment TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY(incident_id) REFERENCES incidents(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_incident_history ON incident_history(incident_id, created_at DESC);
        ALTER TABLE incidents ADD COLUMN acknowledged_at TEXT;
        ALTER TABLE incidents ADD COLUMN operator_comment TEXT;
        ALTER TABLE incidents ADD COLUMN root_cause_monitor_id INTEGER REFERENCES monitors(id) ON DELETE SET NULL;
        """
    )


def _migration_014(db: Database) -> None:
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS topology_meta (
            singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
            version INTEGER NOT NULL DEFAULT 1,
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        INSERT OR IGNORE INTO topology_meta(singleton, version) VALUES (1, 1);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_topology_edge_unique
          ON topology_edges(source_node_id, target_node_id);
        CREATE INDEX IF NOT EXISTS idx_incidents_ended ON incidents(ended_at, id);
        CREATE INDEX IF NOT EXISTS idx_events_cursor ON events(created_at DESC, id DESC);
        CREATE INDEX IF NOT EXISTS idx_snapshots_cursor ON website_snapshots(created_at DESC, id DESC);
        """
    )
