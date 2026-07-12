from __future__ import annotations

from monitoring_center.database import Database
from monitoring_center.migrations import SCHEMA_VERSION, migrate


def test_migration_adds_flapping_runtime_columns(db: Database) -> None:
    columns = {row["name"] for row in db.fetchall("PRAGMA table_info(monitors)")}
    schema = db.fetchone("SELECT MAX(version) AS version FROM schema_migrations")

    assert schema is not None
    assert int(schema["version"]) == SCHEMA_VERSION
    assert {"failure_count", "recovery_count", "last_raw_status"} <= columns


def test_migration_adds_topology_tables(db: Database) -> None:
    tables = {row["name"] for row in db.fetchall("SELECT name FROM sqlite_master WHERE type = 'table'")}
    node_columns = {row["name"] for row in db.fetchall("PRAGMA table_info(topology_nodes)")}
    edge_columns = {row["name"] for row in db.fetchall("PRAGMA table_info(topology_edges)")}

    assert {"topology_nodes", "topology_edges"} <= tables
    assert {"id", "name", "type", "monitor_id", "icon", "x", "y", "metadata_json"} <= node_columns
    assert {"id", "source_node_id", "target_node_id", "label", "metadata_json"} <= edge_columns


def test_migration_from_version_14_adds_credentials_without_changing_monitor_config(tmp_path) -> None:
    from monitoring_center import migrations

    database = Database(tmp_path / "schema14.db")
    database.executescript(
        """CREATE TABLE schema_migrations (
               version INTEGER PRIMARY KEY,
               applied_at TEXT NOT NULL DEFAULT (datetime('now'))
           );"""
    )
    for version in range(1, 15):
        getattr(migrations, f"_migration_{version:03d}")(database)
        database.execute("INSERT INTO schema_migrations(version) VALUES (?)", (version,))
    cursor = database.execute(
        """INSERT INTO monitors(type,name,target,interval_seconds,enabled,config_json)
           VALUES ('ssh_command','Legacy','server:22',60,1,'{"username":"root","password":"legacy"}')"""
    )
    monitor_id = int(cursor.lastrowid or 0)

    migrate(database)

    monitor = database.fetchone("SELECT credential_id, config_json FROM monitors WHERE id=?", (monitor_id,))
    assert monitor == {"credential_id": None, "config_json": '{"username":"root","password":"legacy"}'}
    assert database.fetchone("SELECT name FROM sqlite_master WHERE type='table' AND name='credential_profiles'")
    assert database.fetchone("SELECT MAX(version) AS version FROM schema_migrations") == {"version": 15}
    database.close()
