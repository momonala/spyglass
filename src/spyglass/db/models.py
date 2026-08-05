"""SQLAlchemy ORM models for metrics and logs.

Two separate declarative bases keep metrics and log tables in separate DB files.
id is the surrogate primary key for both tables; timestamp is indexed separately.
"""

import datetime
from enum import StrEnum

from sqlalchemy import Float
from sqlalchemy import ForeignKey
from sqlalchemy import Index
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import Text
from sqlalchemy import TypeDecorator
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


class EpochDateTime(TypeDecorator):
    """Stores naive UTC datetimes as float unix-epoch seconds instead of ISO text.

    ISO text costs ~26 bytes/row and is duplicated across every index on the
    column; an epoch float costs 8 bytes and still keeps sub-millisecond
    precision. Transparent to callers: the Python side always sees ``datetime``.
    """

    impl = Float
    cache_ok = True

    def process_bind_param(self, value: datetime.datetime | None, dialect: object) -> float | None:
        if value is None:
            return None
        return value.replace(tzinfo=datetime.UTC).timestamp()

    def process_result_value(self, value: float | None, dialect: object) -> datetime.datetime | None:
        if value is None:
            return None
        return datetime.datetime.fromtimestamp(value, tz=datetime.UTC).replace(tzinfo=None)


class MetricTypeCode(TypeDecorator):
    """Stores MetricType as a 1-char code instead of the full word.

    Callers still see the full word (e.g. "counter"): only the DB storage is
    shrunk, so routes/queries comparing against MetricType.value are unaffected.
    """

    impl = String(1)
    cache_ok = True

    _TO_CODE = {member.value: member.value[0] for member in MetricType}
    _FROM_CODE = {code: word for word, code in _TO_CODE.items()}

    def process_bind_param(self, value: str | None, dialect: object) -> str | None:
        if value is None:
            return None
        return self._TO_CODE[value]

    def process_result_value(self, value: str | None, dialect: object) -> str | None:
        if value is None:
            return None
        return self._FROM_CODE[value]


class MetricName(MetricsBase):
    """A distinct metric name, normalized out of metric_points.

    Metric names are long, low-cardinality strings (a few dozen at most)
    repeated across hundreds of thousands of rows; storing them once here
    and referencing by id shrinks both the table and its indexes.
    """

    __tablename__ = "metric_names"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False, unique=True)


class MetricPoint(MetricsBase):
    """One emitted metric data point."""

    __tablename__ = "metric_points"
    __table_args__ = (Index("ix_metric_name_id_ts", "name_id", "timestamp"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime.datetime] = mapped_column(EpochDateTime, nullable=False, index=True)
    name_id: Mapped[int] = mapped_column(Integer, ForeignKey("metric_names.id"), nullable=False)
    metric_type: Mapped[str] = mapped_column(MetricTypeCode, nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    tags: Mapped[str | None] = mapped_column(Text, nullable=True)


class LogEntry(LogsBase):
    """One emitted log record."""

    __tablename__ = "log_entries"
    __table_args__ = (Index("ix_log_level_ts", "level", "timestamp"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime.datetime] = mapped_column(EpochDateTime, nullable=False, index=True)
    level: Mapped[str] = mapped_column(String, nullable=False)
    logger_name: Mapped[str] = mapped_column(String, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
