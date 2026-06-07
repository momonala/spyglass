"""Create metric_points with autoincrement id PK (migrates tables using timestamp as PK).

Revision ID: 0002_metrics
Revises:
Create Date: 2026-06-08
"""

from __future__ import annotations

from sqlalchemy import text

from alembic import op

revision = "0002_metrics"
down_revision = None
branch_labels = ("metrics",)
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    table_exists = conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name='metric_points'")
    ).fetchone()

    if table_exists:
        col_names = {row[1] for row in conn.execute(text("PRAGMA table_info(metric_points)"))}
        if "id" in col_names:
            return
        conn.execute(text("ALTER TABLE metric_points RENAME TO _metric_points_old"))
        conn.execute(text("DROP INDEX IF EXISTS ix_metric_name_ts"))
        conn.execute(text("DROP INDEX IF EXISTS ix_metric_points_timestamp"))
        _create_table(conn)
        conn.execute(
            text(
                "INSERT INTO metric_points (timestamp, name, metric_type, value, tags) "
                "SELECT timestamp, name, metric_type, value, tags FROM _metric_points_old"
            )
        )
        conn.execute(text("DROP TABLE _metric_points_old"))
    else:
        _create_table(conn)


def _create_table(conn) -> None:  # type: ignore[no-untyped-def]
    conn.execute(
        text(
            "CREATE TABLE metric_points ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "timestamp DATETIME NOT NULL, "
            "name VARCHAR NOT NULL, "
            "metric_type VARCHAR NOT NULL, "
            "value FLOAT NOT NULL, "
            "tags TEXT)"
        )
    )
    conn.execute(text("CREATE INDEX ix_metric_name_ts ON metric_points (name, timestamp)"))
    conn.execute(text("CREATE INDEX ix_metric_points_timestamp ON metric_points (timestamp)"))


def downgrade() -> None:
    pass
