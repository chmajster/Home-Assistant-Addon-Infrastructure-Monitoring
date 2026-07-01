from __future__ import annotations

from monitoring_center.database import Database
from monitoring_center.migrations import SCHEMA_VERSION


def test_migration_adds_flapping_runtime_columns(db: Database) -> None:
    columns = {row["name"] for row in db.fetchall("PRAGMA table_info(monitors)")}
    schema = db.fetchone("SELECT MAX(version) AS version FROM schema_migrations")

    assert schema is not None
    assert int(schema["version"]) == SCHEMA_VERSION
    assert {"failure_count", "recovery_count", "last_raw_status"} <= columns
