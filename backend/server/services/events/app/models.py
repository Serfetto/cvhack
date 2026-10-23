import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, MetaData, String, Text, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

JSONType = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    metadata = MetaData(schema="events")


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        Index("ix_events_started_desc", "started_at"),
        Index("ix_events_status_created", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    camera_id: Mapped[str] = mapped_column(String(32), index=True)
    camera_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    area_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    zone_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    zone_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    rule_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    scenario: Mapped[str] = mapped_column(String(64), index=True)
    scenario_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    severity: Mapped[str] = mapped_column(String(16), index=True)
    status: Mapped[str] = mapped_column(String(16), default="new")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # первая реакция человека: для «среднего времени реакции» на дашборде
    first_action_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    track_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bbox: Mapped[list | None] = mapped_column(JSONType, nullable=True)
    snapshot_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    snapshot_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    annotated_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    clip_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    clip_status: Mapped[str] = mapped_column(String(16), default="none")
    assignee_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    frame_ts: Mapped[float | None] = mapped_column(Float, nullable=True)
    demo: Mapped[bool] = mapped_column(Boolean, default=False, index=True)


class EventAction(Base):
    """Журнал действий: только добавление (доказательная база для проверок и расследований)."""

    __tablename__ = "event_actions"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("events.events.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    action: Mapped[str] = mapped_column(String(32))  # created | status | comment | ended | clip | escalated
    from_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


def new_uuid() -> uuid.UUID:
    return uuid.uuid4()
