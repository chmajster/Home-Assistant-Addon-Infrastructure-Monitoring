from __future__ import annotations

from monitoring_center.database import Database
from monitoring_center.migrations import SCHEMA_VERSION


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
