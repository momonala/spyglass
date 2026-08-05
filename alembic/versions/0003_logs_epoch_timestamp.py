"""Store log_entries.timestamp as epoch-seconds REAL instead of ISO text.

ISO text costs ~26 bytes/row and is duplicated in both indexes on the column;
an epoch float costs 8 bytes and keeps sub-millisecond precision via julianday().

Revision ID: 0003_logs
Revises: 0001_logs
Create Date: 2026-08-05
"""

from __future__ import annotations

from sqlalchemy import text

from alembic import op

revision = "0003_logs"
down_revision = "0001_logs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(text("ALTER TABLE log_entries RENAME TO _log_entries_old"))
    conn.execute(text("DROP INDEX IF EXISTS ix_log_level_ts"))
    conn.execute(text("DROP INDEX IF EXISTS ix_log_entries_timestamp"))
    _create_table(conn)
    conn.execute(
        text(
            "INSERT INTO log_entries (timestamp, level, logger_name, message, extra) "
            "SELECT (julianday(timestamp) - 2440587.5) * 86400.0, level, logger_name, message, extra "
            "FROM _log_entries_old"
        )
    )
    conn.execute(text("DROP TABLE _log_entries_old"))


def _create_table(conn) -> None:  # type: ignore[no-untyped-def]
    conn.execute(
        text(
            "CREATE TABLE log_entries ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "timestamp REAL NOT NULL, "
            "level VARCHAR NOT NULL, "
            "logger_name VARCHAR NOT NULL, "
            "message TEXT NOT NULL, "
            "extra TEXT)"
        )
    )
    conn.execute(text("CREATE INDEX ix_log_level_ts ON log_entries (level, timestamp)"))
    conn.execute(text("CREATE INDEX ix_log_entries_timestamp ON log_entries (timestamp)"))


def downgrade() -> None:
    pass
