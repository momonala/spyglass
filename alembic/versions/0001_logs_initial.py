"""Create log_entries.

Revision ID: 0001_logs
Revises:
Create Date: 2026-08-05
"""

from __future__ import annotations

from sqlalchemy import text

from alembic import op

revision = "0001_logs"
down_revision = None
branch_labels = ("logs",)
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        text(
            "CREATE TABLE log_entries ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "timestamp REAL NOT NULL, "
            "level VARCHAR NOT NULL, "
            "logger_name VARCHAR NOT NULL, "
            "message TEXT NOT NULL)"
        )
    )
    conn.execute(text("CREATE INDEX ix_log_level_ts ON log_entries (level, timestamp)"))
    conn.execute(text("CREATE INDEX ix_log_entries_timestamp ON log_entries (timestamp)"))


def downgrade() -> None:
    pass
