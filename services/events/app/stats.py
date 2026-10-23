"""Агрегаты для дашборда. Время группируется по местному часовому поясу (APP_TZ)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import Float, cast, extract, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from common.auth import CurrentUser, require

from .core import EventFilter, db, settings
from .models import Event

router = APIRouter(prefix="/stats", tags=["stats"])
READ = require()


def local(col):
    return func.timezone(settings.app_tz, col)


class Summary(BaseModel):
    total: int
    today: int
    critical: int
    unaccepted: int
    forwarded: int
    confirmed: int
    false: int
    resolved: int
    escalated: int
    precision: float | None
    avg_reaction_s: float | None
    by_severity: dict[str, int]


class TypeRow(BaseModel):
    scenario: str
    title: str | None
    count: int
    critical: int


class CameraRow(BaseModel):
    camera_id: str
    camera_name: str | None
    area_id: int | None
    count: int


class AreaRow(BaseModel):
    area_id: int | None
    count: int


class HeatCell(BaseModel):
    dow: int  # 0 — понедельник
    hour: int
    count: int


class TrendRow(BaseModel):
    date: str
    count: int
    critical: int


class PrecisionRow(BaseModel):
    scenario: str
    title: str | None
    camera_id: str | None = None
    confirmed: int
    false: int
    precision: float | None


@router.get("/summary", response_model=Summary, summary="KPI: всего, сегодня, критичных, непринятых, время реакции, precision")
async def summary(f: EventFilter = Depends(), user: CurrentUser = Depends(READ), session: AsyncSession = Depends(db.session)):
    today0 = datetime.now(ZoneInfo(settings.app_tz)).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)
    st = Event.status

    def cnt(cond):
        return func.count().filter(cond)

    q = f.apply(select(
        func.count(), cnt(Event.started_at >= today0), cnt(Event.severity == "critical"), cnt(st == "new"),
        cnt(st == "forwarded"), cnt(st == "confirmed"), cnt(st == "false"), cnt(st == "resolved"),
        cnt(Event.escalated_at.is_not(None)),
        func.avg(extract("epoch", Event.first_action_at - Event.created_at)),
    ).select_from(Event), user)
    r = (await session.execute(q)).one()
    sev = f.apply(select(Event.severity, func.count()).group_by(Event.severity), user)
    by_sev = {k: v for k, v in (await session.execute(sev)).all()}
    confirmed, false = r[5], r[6]
    real = confirmed + r[7]  # «устранено» — тоже настоящее нарушение (как в /stats/precision)
    return Summary(total=r[0], today=r[1], critical=r[2], unaccepted=r[3], forwarded=r[4], confirmed=confirmed, false=false,
                   resolved=r[7], escalated=r[8], precision=round(real / (real + false), 3) if real + false else None,
                   avg_reaction_s=round(float(r[9]), 1) if r[9] is not None else None, by_severity=by_sev)


@router.get("/by-type", response_model=list[TypeRow], summary="Нарушения по типам")
async def by_type(f: EventFilter = Depends(), user: CurrentUser = Depends(READ), session: AsyncSession = Depends(db.session)):
    q = f.apply(select(Event.scenario, func.max(Event.scenario_title), func.count(), func.count().filter(Event.severity == "critical"))
                .group_by(Event.scenario).order_by(func.count().desc()), user)
    return [TypeRow(scenario=a, title=b, count=c, critical=d) for a, b, c, d in (await session.execute(q)).all()]


@router.get("/by-camera", response_model=list[CameraRow], summary="Нарушения по камерам")
async def by_camera(f: EventFilter = Depends(), user: CurrentUser = Depends(READ), session: AsyncSession = Depends(db.session)):
    q = f.apply(select(Event.camera_id, func.max(Event.camera_name), func.max(Event.area_id), func.count())
                .group_by(Event.camera_id).order_by(func.count().desc()), user)
    return [CameraRow(camera_id=a, camera_name=b, area_id=c, count=d) for a, b, c, d in (await session.execute(q)).all()]


@router.get("/by-area", response_model=list[AreaRow], summary="Нарушения по участкам")
async def by_area(f: EventFilter = Depends(), user: CurrentUser = Depends(READ), session: AsyncSession = Depends(db.session)):
    q = f.apply(select(Event.area_id, func.count()).group_by(Event.area_id).order_by(func.count().desc()), user)
    return [AreaRow(area_id=a, count=c) for a, c in (await session.execute(q)).all()]


@router.get("/heatmap", response_model=list[HeatCell], summary="Тепловая карта: день недели × час (когда чаще нарушают)")
async def heatmap(f: EventFilter = Depends(), user: CurrentUser = Depends(READ), session: AsyncSession = Depends(db.session)):
    dow = (cast(extract("isodow", local(Event.started_at)), Float) - 1).label("dow")
    hour = cast(extract("hour", local(Event.started_at)), Float).label("hour")
    q = f.apply(select(dow, hour, func.count()).group_by(dow, hour), user)
    return [HeatCell(dow=int(d), hour=int(h), count=c) for d, h, c in (await session.execute(q)).all()]


@router.get("/trend", response_model=list[TrendRow], summary="Динамика по дням (по умолчанию — последние 30 дней)")
async def trend(f: EventFilter = Depends(), user: CurrentUser = Depends(READ), session: AsyncSession = Depends(db.session)):
    if f.date_from is None:
        f.date_from = datetime.now(UTC) - timedelta(days=30)
    day = func.date(local(Event.started_at)).label("day")
    q = f.apply(select(day, func.count(), func.count().filter(Event.severity == "critical")).group_by(day).order_by(day), user)
    return [TrendRow(date=str(d), count=c, critical=k) for d, c, k in (await session.execute(q)).all()]


@router.get("/precision", response_model=list[PrecisionRow],
            summary="Доля подтверждённых среди отмеченных операторами — онлайн-оценка точности по сценариям и камерам")
async def precision(f: EventFilter = Depends(), by_camera: bool = False, user: CurrentUser = Depends(READ),
                    session: AsyncSession = Depends(db.session)):
    confirmed = func.count().filter(Event.status.in_(["confirmed", "resolved"]))
    false = func.count().filter(Event.status == "false")
    cols = [Event.scenario, func.max(Event.scenario_title)] + ([Event.camera_id] if by_camera else [])
    groups = [Event.scenario] + ([Event.camera_id] if by_camera else [])
    q = f.apply(select(*cols, confirmed, false).group_by(*groups).order_by(*groups), user)
    out = []
    for row in (await session.execute(q)).all():
        c, fl = row[-2], row[-1]
        out.append(PrecisionRow(scenario=row[0], title=row[1], camera_id=row[2] if by_camera else None, confirmed=c, false=fl,
                                precision=round(c / (c + fl), 3) if c + fl else None))
    return out

