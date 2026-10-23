"""Общее для модулей event-service: настройки, подключения, фильтры, преобразование в EventOut."""

from __future__ import annotations

from datetime import datetime

from fastapi import Query
from sqlalchemy import Select

from common.auth import CurrentUser
from common.bus import Bus
from common.db import Database
from common.messages import Channels, EventOut, EventStatus, Role, Severity
from common.settings import BaseServiceSettings
from common.storage import Storage

from .models import Event


class Settings(BaseServiceSettings):
    service_name: str = "events"
    ingest_token: str = "change-me"
    clip_pre_s: float = 5.0
    clip_post_s: float = 5.0
    escalate_critical_min: float = 2
    escalate_high_min: float = 5
    escalate_medium_min: float = 15
    escalate_low_min: float = 60


settings = Settings()
db = Database(settings.database_url, "events")
bus = Bus(settings.redis_url)
storage = Storage.from_settings(settings)


def to_out(e: Event) -> EventOut:
    return EventOut(
        id=str(e.id), camera_id=e.camera_id, camera_name=e.camera_name, area_id=e.area_id, zone_id=e.zone_id,
        zone_name=e.zone_name, rule_id=e.rule_id, scenario=e.scenario, scenario_title=e.scenario_title,
        severity=Severity(e.severity), status=EventStatus(e.status), started_at=e.started_at, confirmed_at=e.confirmed_at,
        ended_at=e.ended_at, created_at=e.created_at, escalated_at=e.escalated_at, confidence=e.confidence,
        track_id=e.track_id, bbox=e.bbox, snapshot_url=storage.public_url(e.snapshot_key),
        annotated_url=storage.public_url(e.annotated_key), snapshot_sha256=e.snapshot_sha256,
        clip_url=storage.public_url(e.clip_key), clip_status=e.clip_status or "none", assignee_id=e.assignee_id,
        demo=e.demo, frame_ts=e.frame_ts,
    )


async def notify(channel: str, e: Event) -> None:
    kind = {Channels.EVENTS_CREATED: "event.created", Channels.EVENTS_UPDATED: "event.updated",
            Channels.EVENTS_ESCALATED: "event.escalated"}[channel]
    await bus.publish(channel, {"type": kind, "event": to_out(e).model_dump(mode="json")})


class EventFilter:
    """Фильтры журнала и статистики (одинаковые для /events, /events/export.csv и /stats/*)."""

    def __init__(
        self,
        camera_id: list[str] | None = Query(None, description="Можно несколько: ?camera_id=cam-01&camera_id=cam-02"),
        area_id: list[int] | None = Query(None),
        zone_id: list[int] | None = Query(None),
        scenario: list[str] | None = Query(None),
        severity: list[Severity] | None = Query(None),
        status: list[EventStatus] | None = Query(None),
        date_from: datetime | None = Query(None, alias="from", description="ISO 8601, включительно"),
        date_to: datetime | None = Query(None, alias="to", description="ISO 8601, не включительно"),
        demo: bool | None = Query(None, description="true — только демо-история, false — только реальные; пусто — все"),
    ):
        self.camera_id, self.area_id, self.zone_id = camera_id, area_id, zone_id
        self.scenario, self.severity, self.status = scenario, severity, status
        self.date_from, self.date_to, self.demo = date_from, date_to, demo

    def apply(self, q: Select, user: CurrentUser | None = None) -> Select:
        if self.camera_id:
            q = q.where(Event.camera_id.in_(self.camera_id))
        if self.area_id:
            q = q.where(Event.area_id.in_(self.area_id))
        if self.zone_id:
            q = q.where(Event.zone_id.in_(self.zone_id))
        if self.scenario:
            q = q.where(Event.scenario.in_(self.scenario))
        if self.severity:
            q = q.where(Event.severity.in_([s.value for s in self.severity]))
        if self.status:
            q = q.where(Event.status.in_([s.value for s in self.status]))
        if self.date_from:
            q = q.where(Event.started_at >= self.date_from)
        if self.date_to:
            q = q.where(Event.started_at < self.date_to)
        if self.demo is not None:
            q = q.where(Event.demo.is_(self.demo))
        return restrict(q, user)


def restrict(q: Select, user: CurrentUser | None) -> Select:
    """Мастер видит только события своих участков."""
    if user and user.role == Role.MASTER and user.area_ids:
        q = q.where(Event.area_id.in_(user.area_ids))
    return q
