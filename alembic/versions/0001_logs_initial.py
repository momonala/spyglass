"""Create log_entries with autoincrement id PK (migrates tables using timestamp as PK).

Revision ID: 0001_logs
Revises:
Create Date: 2026-06-08
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
    table_exists = conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name='log_entries'")
    ).fetchone()

    if table_exists:
        col_names = {row[1] for row in conn.execute(text("PRAGMA table_info(log_entries)"))}
        if "id" in col_names:
            return
        conn.execute(text("ALTER TABLE log_entries RENAME TO _log_entries_old"))
        conn.execute(text("DROP INDEX IF EXISTS ix_log_level_ts"))
        conn.execute(text("DROP INDEX IF EXISTS ix_log_entries_timestamp"))
        _create_table(conn)
        conn.execute(
            text(
                "INSERT INTO log_entries (timestamp, level, logger_name, message, extra) "
                "SELECT timestamp, level, logger_name, message, extra FROM _log_entries_old"
            )
        )
        conn.execute(text("DROP TABLE _log_entries_old"))
    else:
        _create_table(conn)


def _create_table(conn) -> None:  # type: ignore[no-untyped-def]
    conn.execute(
        text(
            "CREATE TABLE log_entries ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "timestamp DATETIME NOT NULL, "
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
