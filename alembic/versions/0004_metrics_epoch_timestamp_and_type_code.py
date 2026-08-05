"""Store metric_points.timestamp as epoch-seconds REAL, metric_type as a 1-char code.

ISO text costs ~26 bytes/row and is duplicated in both indexes on the column;
an epoch float costs 8 bytes and keeps sub-millisecond precision via julianday().
metric_type only ever holds "counter"/"gauge"/"timing"/"set" (see MetricType);
storing the first letter instead of the full word is lossless (see MetricTypeCode).

Revision ID: 0004_metrics
Revises: 0002_metrics
Create Date: 2026-08-05
"""

from __future__ import annotations

from sqlalchemy import text

from alembic import op

revision = "0004_metrics"
down_revision = "0002_metrics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(text("ALTER TABLE metric_points RENAME TO _metric_points_old"))
    conn.execute(text("DROP INDEX IF EXISTS ix_metric_name_ts"))
    conn.execute(text("DROP INDEX IF EXISTS ix_metric_points_timestamp"))
    _create_table(conn)
    conn.execute(
        text(
            "INSERT INTO metric_points (timestamp, name, metric_type, value, tags) "
            "SELECT (julianday(timestamp) - 2440587.5) * 86400.0, name, substr(metric_type, 1, 1), value, tags "
            "FROM _metric_points_old"
        )
    )
    conn.execute(text("DROP TABLE _metric_points_old"))


def _create_table(conn) -> None:  # type: ignore[no-untyped-def]
    conn.execute(
        text(
            "CREATE TABLE metric_points ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "timestamp REAL NOT NULL, "
            "name VARCHAR NOT NULL, "
            "metric_type VARCHAR(1) NOT NULL, "
            "value FLOAT NOT NULL, "
            "tags TEXT)"
        )
    )
    conn.execute(text("CREATE INDEX ix_metric_name_ts ON metric_points (name, timestamp)"))
    conn.execute(text("CREATE INDEX ix_metric_points_timestamp ON metric_points (timestamp)"))


def downgrade() -> None:
    pass
