"""Демо-история для дашборда. Все такие события помечены demo=true — на защите говорим об этом честно,
фильтр ?demo=false показывает только реальные."""

from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select

from common.auth import CurrentUser, require
from common.messages import CameraConfig, Keys, Role

from .core import bus, db, settings
from .models import Event, EventAction

router = APIRouter(prefix="/demo", tags=["demo"])
ADMIN = require(Role.ADMIN)

FALLBACK_SCENARIOS = [
    ("fall", "Падение человека", "critical", 1),
    ("proximity", "Опасное сближение с техникой", "critical", 3),
    ("running", "Бег в цехе", "high", 4),
    ("phone", "Телефон в рабочей зоне", "medium", 5),
    ("in_zone", "Человек в опасной зоне", "high", 4),
]


class SeedIn(BaseModel):
    days: int = Field(default=14, ge=1, le=90)
    per_day: int = Field(default=20, ge=1, le=500)
    seed: int | None = 42


@router.post("/seed", summary="Сгенерировать демо-историю событий (demo=true)")
async def seed(body: SeedIn, _: CurrentUser = Depends(ADMIN)):
    rnd = random.Random(body.seed)
    raw = await bus.redis.hgetall(Keys.CAMERA_CONFIGS)
    cams = [CameraConfig.model_validate_json(v) for v in raw.values()] or [
        CameraConfig(id="cam-01", name="Камера 1", area_id=1, source_url="")]
    catalog = await bus.get_json(Keys.SCENARIO_CATALOG) or []
    # только сценарии, которые реально есть в системе; без каталога — запасной список
    weights = {code: w for code, _t, _s, w in FALLBACK_SCENARIOS}
    scen = [(c["code"], c["title"], c.get("severity", "high"), weights.get(c["code"], 3)) for c in catalog] \
        or FALLBACK_SCENARIOS
    # камеры нарушают неравномерно — иначе столбцы «по камерам» выходят одинаковыми
    cam_w = [rnd.uniform(0.2, 1.0) for _ in cams]
    tz = ZoneInfo(settings.app_tz)
    now = datetime.now(tz)
    n = 0
    async with db.sessionmaker() as s:
        for d in range(body.days, 0, -1):
            day = (now - timedelta(days=d)).replace(hour=0, minute=0, second=0, microsecond=0)
            # в выходные работает одна смена — нарушений меньше
            per_day = body.per_day * (0.35 if day.weekday() >= 5 else 1.0)
            for _ in range(max(1, int(rnd.gauss(per_day, per_day * 0.3)))):
                # смены 8–20 ч, пик после обеда и в конце смены
                hour = min(max(int(rnd.choice([rnd.gauss(10, 1.5), rnd.gauss(14.5, 1.5), rnd.gauss(18, 1)])), 0), 23)
                started = day + timedelta(hours=hour, minutes=rnd.randint(0, 59), seconds=rnd.randint(0, 59))
                code, title, sev, _w = rnd.choices(scen, weights=[x[3] for x in scen])[0]
                cam = rnd.choices(cams, weights=cam_w)[0]
                status = rnd.choices(["confirmed", "false", "resolved", "forwarded"], weights=[50, 15, 30, 5])[0]
                created = started + timedelta(seconds=rnd.uniform(1.5, 3.5))
                reaction = timedelta(seconds=max(5.0, rnd.gauss(70, 40)))
                eid = uuid.uuid4()
                s.add(Event(id=eid, camera_id=cam.id, camera_name=cam.name, area_id=cam.area_id, scenario=code,
                            scenario_title=title, severity=sev, status=status, started_at=started.astimezone(UTC),
                            confirmed_at=created.astimezone(UTC), ended_at=(started + timedelta(seconds=rnd.uniform(3, 40))).astimezone(UTC),
                            created_at=created.astimezone(UTC), first_action_at=(created + reaction).astimezone(UTC),
                            confidence=round(rnd.uniform(0.55, 0.95), 2), clip_status="none", demo=True))
                s.add(EventAction(event_id=eid, action="created", to_status="new", at=created.astimezone(UTC)))
                s.add(EventAction(event_id=eid, action="status", from_status="new", to_status=status, username="demo",
                                  at=(created + reaction).astimezone(UTC)))
                n += 1
        await s.commit()
    return {"created": n}


@router.delete("", summary="Удалить всю демо-историю")
async def clear(_: CurrentUser = Depends(ADMIN)):
    async with db.sessionmaker() as s:
        n = await s.scalar(select(func.count()).select_from(Event).where(Event.demo.is_(True)))
        await s.execute(delete(Event).where(Event.demo.is_(True)))
        await s.commit()
    return {"deleted": n}
