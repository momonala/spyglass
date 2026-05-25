"""SQLAlchemy ORM models for metrics and logs.

Two separate declarative bases keep metrics and log tables in separate DB files.
timestamp is the primary key for both tables; SQLite indexes PKs automatically.
"""

import datetime
from enum import StrEnum

from sqlalchemy import DateTime
from sqlalchemy import Float
from sqlalchemy import Index
from sqlalchemy import String
from sqlalchemy import Text
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column


class MetricsBase(DeclarativeBase):
    pass


class LogsBase(DeclarativeBase):
    pass


class MetricType(StrEnum):
    """Allowed values for ``MetricPoint.metric_type`` (single source of truth)."""

    COUNTER = "counter"
    GAUGE = "gauge"
    TIMING = "timing"
    SET = "set"


class MetricPoint(MetricsBase):
    """One emitted metric data point."""

    __tablename__ = "metric_points"
    __table_args__ = (
        Index("ix_metric_name_ts", "name", "timestamp"),
    )

    timestamp: Mapped[datetime.datetime] = mapped_column(DateTime, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    metric_type: Mapped[str] = mapped_column(String, nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    tags: Mapped[str | None] = mapped_column(Text, nullable=True)


class LogEntry(LogsBase):
    """One emitted log record."""

    __tablename__ = "log_entries"
    __table_args__ = (
        Index("ix_log_level_ts", "level", "timestamp"),
    )

    timestamp: Mapped[datetime.datetime] = mapped_column(DateTime, primary_key=True)
    level: Mapped[str] = mapped_column(String, nullable=False)
    logger_name: Mapped[str] = mapped_column(String, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    extra: Mapped[str | None] = mapped_column(Text, nullable=True)
