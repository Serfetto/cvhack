"""event-service: журнал нарушений, статусы и история действий, статистика, экспорт, эскалация."""

from __future__ import annotations

import asyncio
import base64
import csv
import hashlib
import io
import time
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from prometheus_client import Counter, Histogram
from pydantic import BaseModel, Field
from sqlalchemy import case, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from common.auth import CurrentUser, require
from common.bus import MsgCtx, default_consumer_name
from common.logging import get_logger
from common.messages import (
    Channels, ClipReady, ClipRequest, EventOut, EventStatus, Role, Streams, ViolationKind, ViolationMsg,
)
from common.metrics import LATENCY_BUCKETS
from common.service import Supervisor, create_app

from . import demo, stats
from .core import EventFilter, bus, db, notify, settings, storage, to_out
from .models import Base, Event, EventAction

log = get_logger(__name__)
sup = Supervisor()

EVENTS_CREATED = Counter("events_created_total", "Созданные события", ["scenario", "severity"])
EVENT_STORE_SECONDS = Histogram("event_store_seconds", "От кадра, подтвердившего нарушение, до записи в журнал", buckets=LATENCY_BUCKETS)

READ = require()
ACT = require(Role.OPERATOR, Role.MASTER, Role.HSE)
EXPORT = require(Role.HSE, Role.AUDITOR, Role.MANAGER)

# Допустимые переходы статуса (кейс: new → confirmed / false / forwarded → resolved)
TRANSITIONS: dict[EventStatus, set[EventStatus]] = {
    EventStatus.NEW: {EventStatus.CONFIRMED, EventStatus.FALSE, EventStatus.FORWARDED, EventStatus.RESOLVED},
    EventStatus.FORWARDED: {EventStatus.CONFIRMED, EventStatus.FALSE, EventStatus.RESOLVED},
    EventStatus.CONFIRMED: {EventStatus.RESOLVED, EventStatus.FORWARDED},
    EventStatus.FALSE: {EventStatus.NEW},
    EventStatus.RESOLVED: {EventStatus.NEW},
}

STATUS_TITLES = {"new": "Новое", "confirmed": "Подтверждено", "false": "Ложное", "forwarded": "Передано мастеру", "resolved": "Устранено"}
SEVERITY_TITLES = {"critical": "Критическое", "high": "Высокая", "medium": "Средняя", "low": "Низкая"}


def _dt(ts: float | None) -> datetime | None:
    return datetime.fromtimestamp(ts, UTC) if ts else None


# --- консьюмеры --------------------------------------------------------------------------


async def on_violation(v: ViolationMsg, ctx: MsgCtx) -> None:
    async with db.sessionmaker() as s:
        if v.kind == ViolationKind.STARTED:
            stmt = insert(Event).values(
                id=uuid.UUID(v.event_id), camera_id=v.camera_id, camera_name=v.camera_name, area_id=v.area_id,
                zone_id=v.zone_id, zone_name=v.zone_name, rule_id=v.rule_id, scenario=v.scenario,
                scenario_title=v.scenario_title, severity=v.severity.value, status=EventStatus.NEW.value,
                started_at=_dt(v.started_at), confirmed_at=_dt(v.confirmed_at), confidence=v.confidence,
                track_id=v.track_id, bbox=v.bbox, snapshot_key=v.snapshot_key, snapshot_sha256=v.snapshot_sha256,
                annotated_key=v.annotated_key, clip_status="pending", frame_ts=v.frame_ts, demo=v.demo,
            ).on_conflict_do_nothing(index_elements=["id"]).returning(Event.id)
            inserted = (await s.execute(stmt)).scalar_one_or_none()
            if inserted is None:
                return  # повтор после рестарта — событие уже есть (идемпотентность)
            s.add(EventAction(event_id=inserted, action="created", to_status="new"))
            await s.commit()
            e = await s.get(Event, inserted)
            if v.frame_ts:
                EVENT_STORE_SECONDS.observe(max(time.time() - v.frame_ts, 0))
            EVENTS_CREATED.labels(v.scenario, v.severity.value).inc()
            await notify(Channels.EVENTS_CREATED, e)
            t_ref = v.confirmed_at or v.started_at
            await bus.xadd(Streams.CLIP_REQUESTS, ClipRequest(
                event_id=v.event_id, camera_id=v.camera_id, t0=v.started_at - settings.clip_pre_s, t1=t_ref + settings.clip_post_s))
        else:
            e = await s.get(Event, uuid.UUID(v.event_id))
            if e is None or e.ended_at is not None:
                return
            e.ended_at = _dt(v.ended_at) or datetime.now(UTC)
            s.add(EventAction(event_id=e.id, action="ended"))
            await s.commit()
            await notify(Channels.EVENTS_UPDATED, e)


async def on_clip_ready(c: ClipReady, ctx: MsgCtx) -> None:
    async with db.sessionmaker() as s:
        e = await s.get(Event, uuid.UUID(c.event_id))
        if e is None:
            return
        e.clip_status = c.status
        e.clip_key = c.clip_key
        await s.commit()
        await notify(Channels.EVENTS_UPDATED, e)


async def housekeeping() -> None:
    """Эскалация непринятых событий и тайм-аут клипов."""
    thresholds = {"critical": settings.escalate_critical_min, "high": settings.escalate_high_min,
                  "medium": settings.escalate_medium_min, "low": settings.escalate_low_min}
    while True:
        now = datetime.now(UTC)
        async with db.sessionmaker() as s:
            for sev, minutes in thresholds.items():
                rows = (await s.execute(
                    update(Event)
                    .where(Event.status == "new", Event.escalated_at.is_(None), Event.demo.is_(False),
                           Event.severity == sev, Event.created_at < now - timedelta(minutes=minutes))
                    .values(escalated_at=now).returning(Event.id))).scalars().all()
                for eid in rows:
                    s.add(EventAction(event_id=eid, action="escalated", comment=f"Не принято за {minutes:g} мин"))
                await s.commit()
                for eid in rows:
                    await notify(Channels.EVENTS_ESCALATED, await s.get(Event, eid))
            stale = (await s.execute(
                update(Event).where(Event.clip_status == "pending", Event.created_at < now - timedelta(minutes=3))
                .values(clip_status="failed").returning(Event.id))).scalars().all()
            await s.commit()
            if stale:
                log.warning("clips_timed_out", n=len(stale))
        await asyncio.sleep(15)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init(Base.metadata)
    await bus.wait_ready()
    await storage.ensure_bucket()
    consumer = default_consumer_name("events")
    sup.spawn("consume-violations", lambda: bus.consume([Streams.VIOLATIONS], "events", consumer, ViolationMsg, on_violation))
    sup.spawn("consume-clips", lambda: bus.consume([Streams.CLIP_READY], "events", consumer, ClipReady, on_clip_ready))
    sup.spawn("housekeeping", housekeeping)
    yield
    await sup.stop()
    await bus.close()
    await db.close()


app = create_app(settings, "event-service", "Журнал нарушений, статусы, статистика и экспорт", lifespan=lifespan)
app.include_router(stats.router)
app.include_router(demo.router)


# --- журнал --------------------------------------------------------------------------------


class EventPage(BaseModel):
    items: list[EventOut]
    total: int
    page: int
    page_size: int


class ActionOut(BaseModel):
    id: int
    user_id: int | None
    username: str | None
    action: str
    from_status: str | None
    to_status: str | None
    comment: str | None
    at: datetime


class EventDetail(EventOut):
    actions: list[ActionOut]
    allowed_statuses: list[EventStatus]


class StatusIn(BaseModel):
    status: EventStatus
    comment: str | None = Field(default=None, max_length=2000)
    assignee_id: int | None = Field(default=None, description="Кому передано (для forwarded)")


class CommentIn(BaseModel):
    comment: str = Field(min_length=1, max_length=2000)


SEVERITY_RANK = case({"critical": 3, "high": 2, "medium": 1, "low": 0}, value=Event.severity, else_=0)
SORTS = {"-started_at": [Event.started_at.desc()], "started_at": [Event.started_at.asc()],
         "-severity": [SEVERITY_RANK.desc(), Event.started_at.desc()], "-created_at": [Event.created_at.desc()]}


@app.get("/events", response_model=EventPage, tags=["events"], summary="Журнал с фильтрами и пагинацией")
async def list_events(
    f: EventFilter = Depends(),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    sort: str = Query("-started_at", description="-started_at | started_at | -severity | -created_at"),
    user: CurrentUser = Depends(READ),
    session: AsyncSession = Depends(db.session),
):
    q = f.apply(select(Event), user)
    total = await session.scalar(select(func.count()).select_from(q.subquery()))
    rows = (await session.execute(q.order_by(*SORTS.get(sort, SORTS["-started_at"])).offset((page - 1) * page_size).limit(page_size))).scalars()
    return EventPage(items=[to_out(e) for e in rows], total=total or 0, page=page, page_size=page_size)


@app.get("/events/export.csv", tags=["events"], summary="Экспорт журнала в CSV (Excel, разделитель «;»)")
async def export_csv(f: EventFilter = Depends(), user: CurrentUser = Depends(EXPORT), session: AsyncSession = Depends(db.session)):
    rows = (await session.execute(f.apply(select(Event), user).order_by(Event.started_at.desc()).limit(50_000))).scalars().all()
    tz = ZoneInfo(settings.app_tz)
    buf = io.StringIO()
    buf.write("﻿")
    w = csv.writer(buf, delimiter=";")
    w.writerow(["ID", "Начало", "Окончание", "Камера", "Участок", "Зона", "Нарушение", "Важность", "Статус",
                "Уверенность", "Снапшот", "SHA-256 снапшота", "Клип", "Демо"])
    for e in rows:
        w.writerow([e.id, e.started_at.astimezone(tz).strftime("%d.%m.%Y %H:%M:%S"),
                    e.ended_at.astimezone(tz).strftime("%d.%m.%Y %H:%M:%S") if e.ended_at else "",
                    e.camera_name or e.camera_id, e.area_id or "", e.zone_name or "", e.scenario_title or e.scenario,
                    SEVERITY_TITLES.get(e.severity, e.severity), STATUS_TITLES.get(e.status, e.status),
                    f"{e.confidence:.2f}" if e.confidence is not None else "", storage.public_url(e.snapshot_key) or "",
                    e.snapshot_sha256 or "", storage.public_url(e.clip_key) or "", "да" if e.demo else ""])
    name = f"violations_{datetime.now(tz):%Y%m%d_%H%M}.csv"
    return StreamingResponse(iter([buf.getvalue().encode("utf-8")]), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{name}"'})


async def _get_event(session: AsyncSession, event_id: uuid.UUID, user: CurrentUser) -> Event:
    e = await session.get(Event, event_id)
    if e is None or not user.has_area(e.area_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Событие не найдено")
    return e


async def _detail(session: AsyncSession, e: Event) -> EventDetail:
    acts = (await session.execute(select(EventAction).where(EventAction.event_id == e.id).order_by(EventAction.at, EventAction.id))).scalars()
    return EventDetail(**to_out(e).model_dump(),
                       actions=[ActionOut(id=a.id, user_id=a.user_id, username=a.username, action=a.action, from_status=a.from_status,
                                          to_status=a.to_status, comment=a.comment, at=a.at) for a in acts],
                       allowed_statuses=sorted(TRANSITIONS[EventStatus(e.status)]))


@app.get("/events/{event_id}", response_model=EventDetail, tags=["events"], summary="Карточка события с историей действий")
async def get_event(event_id: uuid.UUID, user: CurrentUser = Depends(READ), session: AsyncSession = Depends(db.session)):
    return await _detail(session, await _get_event(session, event_id, user))


@app.patch("/events/{event_id}/status", response_model=EventDetail, tags=["events"], summary="Сменить статус (с комментарием)")
async def set_status(event_id: uuid.UUID, body: StatusIn, user: CurrentUser = Depends(ACT), session: AsyncSession = Depends(db.session)):
    e = await _get_event(session, event_id, user)
    cur = EventStatus(e.status)
    if body.status != cur and body.status not in TRANSITIONS[cur]:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Переход «{STATUS_TITLES[cur]}» → «{STATUS_TITLES[body.status]}» недопустим")
    now = datetime.now(UTC)
    e.status = body.status.value
    if body.assignee_id is not None:
        e.assignee_id = body.assignee_id
    if e.first_action_at is None:
        e.first_action_at = now
    session.add(EventAction(event_id=e.id, user_id=user.id, username=user.username, action="status",
                            from_status=cur.value, to_status=body.status.value, comment=body.comment))
    await session.commit()
    await notify(Channels.EVENTS_UPDATED, e)
    return await _detail(session, e)


@app.post("/events/{event_id}/comments", response_model=EventDetail, tags=["events"], summary="Добавить комментарий")
async def add_comment(event_id: uuid.UUID, body: CommentIn, user: CurrentUser = Depends(ACT), session: AsyncSession = Depends(db.session)):
    e = await _get_event(session, event_id, user)
    session.add(EventAction(event_id=e.id, user_id=user.id, username=user.username, action="comment", comment=body.comment))
    await session.commit()
    await notify(Channels.EVENTS_UPDATED, e)
    return await _detail(session, e)


# --- приём нарушений по HTTP (режим B: горячий путь целиком на стенде LinQ) ----------------------


class ViolationIn(ViolationMsg):
    snapshot_b64: str | None = Field(default=None, description="JPEG кадра в base64 — если на стенде нет доступа к MinIO")


@app.post("/ingest/violations", status_code=202, tags=["ingest"],
          summary="Принять нарушение со стенда (заголовок X-Ingest-Token)")
async def ingest_violation(body: ViolationIn, x_ingest_token: str = Header(...)):
    if x_ingest_token != settings.ingest_token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверный X-Ingest-Token")
    msg = ViolationMsg.model_validate(body.model_dump(exclude={"snapshot_b64"}))
    if body.snapshot_b64 and body.kind == ViolationKind.STARTED:
        jpeg = base64.b64decode(body.snapshot_b64)
        d = datetime.fromtimestamp(msg.started_at, UTC)
        msg.snapshot_key = f"events/{d:%Y/%m/%d}/{msg.event_id}.jpg"
        msg.snapshot_sha256 = hashlib.sha256(jpeg).hexdigest()
        await storage.put(msg.snapshot_key, jpeg, "image/jpeg")
    await bus.xadd(Streams.VIOLATIONS, msg)
    return {"accepted": True, "event_id": msg.event_id}
