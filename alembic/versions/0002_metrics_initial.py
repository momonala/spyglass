"""Create metric_names and metric_points.

Revision ID: 0002_metrics
Revises:
Create Date: 2026-08-05
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
    conn.execute(
        text("CREATE TABLE metric_names (id INTEGER PRIMARY KEY AUTOINCREMENT, name VARCHAR NOT NULL UNIQUE)")
    )
    conn.execute(
        text(
            "CREATE TABLE metric_points ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "timestamp REAL NOT NULL, "
            "name_id INTEGER NOT NULL REFERENCES metric_names(id), "
            "metric_type VARCHAR(1) NOT NULL, "
            "value FLOAT NOT NULL, "
            "tags TEXT)"
        )
    )
    conn.execute(text("CREATE INDEX ix_metric_name_id_ts ON metric_points (name_id, timestamp)"))
    conn.execute(text("CREATE INDEX ix_metric_points_timestamp ON metric_points (timestamp)"))


def downgrade() -> None:
    pass
