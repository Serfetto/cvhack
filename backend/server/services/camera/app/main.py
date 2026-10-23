"""camera-service: площадки → участки → камеры, зоны-полигоны и правила сценариев.

После каждого изменения полная конфигурация камеры уходит в Redis (`config:cameras`) и рассылается
`config.updated` — ingest и analytics применяют её к следующему кадру без перезапуска.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

import jsonschema
from fastapi import Depends, FastAPI, HTTPException, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from common.auth import CurrentUser, require
from common.bus import Bus
from common.camconfig import load_yaml, publish_camera_configs
from common.db import Database
from common.logging import get_logger
from common.messages import CameraConfig, Keys, Role, RuleCfg, Schedule, ScenarioInfo, Severity, SourceType, ZoneCfg, ZoneKind
from common.service import create_app
from common.settings import BaseServiceSettings

from .models import Area, Base, Camera, Rule, Site, Zone

log = get_logger(__name__)


class Settings(BaseServiceSettings):
    service_name: str = "camera"
    cameras_yaml: str | None = "/app/infra/cameras.yml"


settings = Settings()
db = Database(settings.database_url, "config")
bus = Bus(settings.redis_url)

READ = require()
WRITE = require(Role.HSE)


# --- схемы API -----------------------------------------------------------------------


class SiteIn(BaseModel):
    name: str
    address: str = ""


class SiteOut(SiteIn):
    id: int


class AreaIn(BaseModel):
    site_id: int
    name: str


class AreaOut(AreaIn):
    id: int


class CameraIn(BaseModel):
    id: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9_-]{0,31}$", description="Если не задан — cam-NN")
    area_id: int | None = None
    name: str
    description: str = ""
    source_type: SourceType = SourceType.RTSP
    source_url: str = Field(description="rtsp://…, путь к видеофайлу или к папке с кадрами")
    analysis_fps: float = Field(default=5.0, ge=0.2, le=30)
    enabled: bool = True


class CameraPatch(BaseModel):
    area_id: int | None = None
    name: str | None = None
    description: str | None = None
    source_type: SourceType | None = None
    source_url: str | None = None
    analysis_fps: float | None = Field(default=None, ge=0.2, le=30)
    enabled: bool | None = None


class StreamStatus(BaseModel):
    state: str = "unknown"  # online | connecting | offline | disabled | unknown
    fps: float = 0.0
    last_frame_ts: float | None = None
    error: str | None = None
    w: int | None = None
    h: int | None = None


class CameraOut(BaseModel):
    id: str
    area_id: int | None
    area_name: str | None = None
    site_id: int | None = None
    name: str
    description: str
    source_type: SourceType
    source_url: str
    analysis_fps: float
    enabled: bool
    version: int
    zones_count: int = 0
    rules_count: int = 0
    stream: StreamStatus = StreamStatus()
    live_hls: str | None = Field(default=None, description="HLS из MediaMTX через шлюз (/live/…), если источник — RTSP MediaMTX")


def _check_polygon(v: list[list[float]]) -> list[list[float]]:
    if len(v) < 3:
        raise ValueError("В полигоне должно быть не меньше 3 точек")
    for p in v:
        if len(p) != 2 or not all(0.0 <= c <= 1.0 for c in p):
            raise ValueError("Точка полигона — [x, y], координаты нормированы 0..1")
    return v


class ZoneIn(BaseModel):
    name: str
    kind: ZoneKind = ZoneKind.DANGER
    polygon: list[list[float]]
    color: str | None = None
    enabled: bool = True

    @field_validator("polygon")
    @classmethod
    def _poly(cls, v):
        return _check_polygon(v)


class ZonePatch(BaseModel):
    name: str | None = None
    kind: ZoneKind | None = None
    polygon: list[list[float]] | None = None
    color: str | None = None
    enabled: bool | None = None

    @field_validator("polygon")
    @classmethod
    def _poly(cls, v):
        return _check_polygon(v) if v is not None else v


class ZoneOut(ZoneIn):
    id: int
    camera_id: str


class RuleIn(BaseModel):
    scenario: str
    zone_id: int | None = None
    params: dict[str, Any] = Field(default_factory=dict, description="Параметры по params_schema сценария (GET /scenarios)")
    severity: Severity | None = Field(default=None, description="Пусто — важность по умолчанию из сценария")
    schedule: Schedule | None = Field(default=None, description='{"days": [0,1,2,3,4], "from": "07:55", "to": "12:00"}')
    valid_until: datetime | None = None
    enabled: bool = True


class RulePatch(BaseModel):
    zone_id: int | None = None
    params: dict[str, Any] | None = None
    severity: Severity | None = None
    schedule: Schedule | None = None
    valid_until: datetime | None = None
    enabled: bool | None = None


class RuleOut(RuleIn):
    id: int
    camera_id: str


class CameraDetail(CameraOut):
    zones: list[ZoneOut]
    rules: list[RuleOut]


class TreeArea(AreaOut):
    cameras: list[CameraOut]


class TreeSite(SiteOut):
    areas: list[TreeArea]


# --- публикация конфигурации -------------------------------------------------------


async def build_config(session: AsyncSession, cam: Camera) -> CameraConfig:
    area = await session.get(Area, cam.area_id) if cam.area_id else None
    zones = (await session.execute(select(Zone).where(Zone.camera_id == cam.id).order_by(Zone.id))).scalars().all()
    rules = (await session.execute(select(Rule).where(Rule.camera_id == cam.id).order_by(Rule.id))).scalars().all()
    return CameraConfig(
        id=cam.id, name=cam.name, area_id=cam.area_id, area_name=area.name if area else None,
        site_id=area.site_id if area else None, source_type=SourceType(cam.source_type), source_url=cam.source_url,
        analysis_fps=cam.analysis_fps, enabled=cam.enabled, version=cam.version,
        zones=[ZoneCfg(id=z.id, name=z.name, kind=ZoneKind(z.kind), polygon=z.polygon, enabled=z.enabled) for z in zones],
        rules=[RuleCfg(id=r.id, scenario=r.scenario, zone_id=r.zone_id, params=r.params or {},
                       severity=Severity(r.severity) if r.severity else None,
                       schedule=Schedule.model_validate(r.schedule) if r.schedule else None,
                       valid_until=r.valid_until, enabled=r.enabled) for r in rules],
    )


async def publish(session: AsyncSession, camera_id: str) -> None:
    cam = await session.get(Camera, camera_id)
    if cam is None:
        await publish_camera_configs(bus, [], deleted=[camera_id])
        return
    cam.version += 1
    await session.commit()
    await publish_camera_configs(bus, [await build_config(session, cam)])


async def publish_all(session: AsyncSession) -> None:
    cams = (await session.execute(select(Camera))).scalars().all()
    await publish_camera_configs(bus, [await build_config(session, c) for c in cams], replace_all=True)


async def seed_from_yaml(session: AsyncSession) -> None:
    if (await session.execute(select(Site.id).limit(1))).first() or not settings.cameras_yaml:
        return
    sites, _ = load_yaml(settings.cameras_yaml)
    for s in sites:
        session.add(Site(id=s["id"], name=s["name"], address=s.get("address", "")))
        await session.flush()
        for a in s.get("areas", []):
            session.add(Area(id=a["id"], site_id=s["id"], name=a["name"]))
            await session.flush()
            for c in a.get("cameras", []):
                session.add(Camera(id=c["id"], area_id=a["id"], name=c["name"], description=c.get("description", ""),
                                   source_type=c.get("source_type", "rtsp"), source_url=c["source_url"],
                                   analysis_fps=c.get("analysis_fps", 5.0), enabled=c.get("enabled", True)))
                await session.flush()
                for z in c.get("zones", []):
                    session.add(Zone(id=z["id"], camera_id=c["id"], name=z["name"], kind=z.get("kind", "danger"),
                                     polygon=z["polygon"], enabled=z.get("enabled", True)))
                await session.flush()
                for r in c.get("rules", []):
                    session.add(Rule(id=r["id"], camera_id=c["id"], zone_id=r.get("zone_id"), scenario=r["scenario"],
                                     params=r.get("params", {}), severity=r.get("severity"), schedule=r.get("schedule"),
                                     enabled=r.get("enabled", True)))
    await session.flush()
    # явные id из YAML не двигают последовательности — выравниваем, иначе следующий INSERT упадёт
    for table in ("sites", "areas", "zones", "rules"):
        await session.execute(text(
            f"SELECT setval(pg_get_serial_sequence('config.{table}', 'id'), COALESCE((SELECT MAX(id) FROM config.{table}), 0) + 1, false)"))
    await session.commit()
    log.info("seeded_from_yaml", path=settings.cameras_yaml)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init(Base.metadata)
    await bus.wait_ready()
    async with db.sessionmaker() as s:
        await seed_from_yaml(s)
        await publish_all(s)
    yield
    await bus.close()
    await db.close()


app = create_app(settings, "camera-service", "Конфигурация: площадки, участки, камеры, зоны, правила", lifespan=lifespan)


# --- помощники ------------------------------------------------------------------------


async def stream_status(camera_id: str, enabled: bool) -> StreamStatus:
    raw = await bus.redis.hgetall(Keys.ingest_status(camera_id))
    if not raw:
        return StreamStatus(state="disabled" if not enabled else "offline")
    d = {k.decode(): v.decode() for k, v in raw.items()}
    return StreamStatus(state=d.get("state", "unknown"), fps=float(d.get("fps", 0) or 0),
                        last_frame_ts=float(d["last_frame_ts"]) if d.get("last_frame_ts") else None,
                        error=d.get("error") or None, w=int(d["w"]) if d.get("w") else None, h=int(d["h"]) if d.get("h") else None)


def live_hls(cam: Camera) -> str | None:
    if cam.source_type == "rtsp" and "mediamtx" in cam.source_url:
        path = cam.source_url.rstrip("/").rsplit("/", 1)[-1]
        return f"/live/{path}/index.m3u8"
    return None


async def camera_out(session: AsyncSession, cam: Camera, areas: dict[int, Area] | None = None) -> CameraOut:
    area = (areas or {}).get(cam.area_id) if areas is not None else (await session.get(Area, cam.area_id) if cam.area_id else None)
    zc = await session.scalar(select(func.count()).select_from(Zone).where(Zone.camera_id == cam.id))
    rc = await session.scalar(select(func.count()).select_from(Rule).where(Rule.camera_id == cam.id))
    return CameraOut(id=cam.id, area_id=cam.area_id, area_name=area.name if area else None, site_id=area.site_id if area else None,
                     name=cam.name, description=cam.description, source_type=SourceType(cam.source_type), source_url=cam.source_url,
                     analysis_fps=cam.analysis_fps, enabled=cam.enabled, version=cam.version, zones_count=zc or 0, rules_count=rc or 0,
                     stream=await stream_status(cam.id, cam.enabled), live_hls=live_hls(cam))


def zone_out(z: Zone) -> ZoneOut:
    return ZoneOut(id=z.id, camera_id=z.camera_id, name=z.name, kind=ZoneKind(z.kind), polygon=z.polygon, color=z.color, enabled=z.enabled)


def rule_out(r: Rule) -> RuleOut:
    return RuleOut(id=r.id, camera_id=r.camera_id, scenario=r.scenario, zone_id=r.zone_id, params=r.params or {},
                   severity=Severity(r.severity) if r.severity else None,
                   schedule=Schedule.model_validate(r.schedule) if r.schedule else None,
                   valid_until=r.valid_until, enabled=r.enabled)


async def get_or_404(session: AsyncSession, model, key, what: str):
    obj = await session.get(model, key)
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Не найдено: {what.lower()} {key}")
    return obj


async def load_catalog() -> list[ScenarioInfo]:
    data = await bus.get_json(Keys.SCENARIO_CATALOG)
    return [ScenarioInfo.model_validate(x) for x in data or []]


async def validate_rule(session: AsyncSession, camera_id: str, scenario: str, zone_id: int | None, params: dict) -> None:
    if zone_id is not None:
        z = await session.get(Zone, zone_id)
        if z is None or z.camera_id != camera_id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Зона не принадлежит этой камере")
    catalog = {s.code: s for s in await load_catalog()}
    if not catalog:
        return  # analytics ещё не опубликовал каталог — проверим позже
    info = catalog.get(scenario)
    if info is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Неизвестный сценарий «{scenario}». Доступны: {', '.join(catalog)}")
    if info.zone_required and zone_id is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Сценарию «{info.title}» нужна зона")
    try:
        jsonschema.validate(params, info.params_schema)
    except jsonschema.ValidationError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Параметры: {e.message}") from e


# --- площадки и участки ------------------------------------------------------------------


@app.get("/tree", response_model=list[TreeSite], tags=["sites"], summary="Дерево площадка → участки → камеры (для меню)")
async def tree(_: CurrentUser = Depends(READ), session: AsyncSession = Depends(db.session)):
    sites = (await session.execute(select(Site).order_by(Site.id))).scalars().all()
    areas = (await session.execute(select(Area).order_by(Area.id))).scalars().all()
    cams = (await session.execute(select(Camera).order_by(Camera.id))).scalars().all()
    amap = {a.id: a for a in areas}
    out = []
    for s in sites:
        tas = []
        for a in (a for a in areas if a.site_id == s.id):
            tas.append(TreeArea(id=a.id, site_id=a.site_id, name=a.name,
                                cameras=[await camera_out(session, c, amap) for c in cams if c.area_id == a.id]))
        out.append(TreeSite(id=s.id, name=s.name, address=s.address, areas=tas))
    return out


@app.get("/sites", response_model=list[SiteOut], tags=["sites"])
async def list_sites(_: CurrentUser = Depends(READ), session: AsyncSession = Depends(db.session)):
    return [SiteOut(id=s.id, name=s.name, address=s.address) for s in (await session.execute(select(Site).order_by(Site.id))).scalars()]


@app.post("/sites", response_model=SiteOut, status_code=201, tags=["sites"])
async def create_site(body: SiteIn, _: CurrentUser = Depends(WRITE), session: AsyncSession = Depends(db.session)):
    s = Site(**body.model_dump())
    session.add(s)
    await session.commit()
    return SiteOut(id=s.id, name=s.name, address=s.address)


@app.patch("/sites/{site_id}", response_model=SiteOut, tags=["sites"])
async def patch_site(site_id: int, body: SiteIn, _: CurrentUser = Depends(WRITE), session: AsyncSession = Depends(db.session)):
    s = await get_or_404(session, Site, site_id, "Площадка")
    s.name, s.address = body.name, body.address
    await session.commit()
    return SiteOut(id=s.id, name=s.name, address=s.address)


@app.delete("/sites/{site_id}", status_code=204, tags=["sites"])
async def delete_site(site_id: int, _: CurrentUser = Depends(WRITE), session: AsyncSession = Depends(db.session)):
    s = await get_or_404(session, Site, site_id, "Площадка")
    await session.delete(s)
    await session.commit()
    await publish_all(session)


@app.get("/areas", response_model=list[AreaOut], tags=["sites"])
async def list_areas(site_id: int | None = None, _: CurrentUser = Depends(READ), session: AsyncSession = Depends(db.session)):
    q = select(Area).order_by(Area.id)
    if site_id is not None:
        q = q.where(Area.site_id == site_id)
    return [AreaOut(id=a.id, site_id=a.site_id, name=a.name) for a in (await session.execute(q)).scalars()]


@app.post("/areas", response_model=AreaOut, status_code=201, tags=["sites"])
async def create_area(body: AreaIn, _: CurrentUser = Depends(WRITE), session: AsyncSession = Depends(db.session)):
    await get_or_404(session, Site, body.site_id, "Площадка")
    a = Area(**body.model_dump())
    session.add(a)
    await session.commit()
    return AreaOut(id=a.id, site_id=a.site_id, name=a.name)


@app.patch("/areas/{area_id}", response_model=AreaOut, tags=["sites"])
async def patch_area(area_id: int, body: AreaIn, _: CurrentUser = Depends(WRITE), session: AsyncSession = Depends(db.session)):
    a = await get_or_404(session, Area, area_id, "Участок")
    a.site_id, a.name = body.site_id, body.name
    await session.commit()
    await publish_all(session)
    return AreaOut(id=a.id, site_id=a.site_id, name=a.name)


@app.delete("/areas/{area_id}", status_code=204, tags=["sites"])
async def delete_area(area_id: int, _: CurrentUser = Depends(WRITE), session: AsyncSession = Depends(db.session)):
    a = await get_or_404(session, Area, area_id, "Участок")
    await session.delete(a)
    await session.commit()
    await publish_all(session)


# --- камеры ----------------------------------------------------------------------------------


@app.get("/cameras", response_model=list[CameraOut], tags=["cameras"], summary="Камеры со статусом потока")
async def list_cameras(area_id: int | None = None, _: CurrentUser = Depends(READ), session: AsyncSession = Depends(db.session)):
    q = select(Camera).order_by(Camera.id)
    if area_id is not None:
        q = q.where(Camera.area_id == area_id)
    areas = {a.id: a for a in (await session.execute(select(Area))).scalars()}
    return [await camera_out(session, c, areas) for c in (await session.execute(q)).scalars()]


@app.post("/cameras", response_model=CameraOut, status_code=201, tags=["cameras"])
async def create_camera(body: CameraIn, _: CurrentUser = Depends(WRITE), session: AsyncSession = Depends(db.session)):
    if body.area_id is not None:
        await get_or_404(session, Area, body.area_id, "Участок")
    cam_id = body.id
    if not cam_id:
        n = (await session.scalar(select(func.count()).select_from(Camera))) or 0
        while True:
            n += 1
            cam_id = f"cam-{n:02d}"
            if not await session.get(Camera, cam_id):
                break
    elif await session.get(Camera, cam_id):
        raise HTTPException(status.HTTP_409_CONFLICT, "Камера с таким id уже есть")
    cam = Camera(**{**body.model_dump(), "id": cam_id, "source_type": body.source_type.value})
    session.add(cam)
    await session.commit()
    await publish(session, cam.id)
    return await camera_out(session, cam)


@app.get("/cameras/{camera_id}", response_model=CameraDetail, tags=["cameras"], summary="Камера с зонами и правилами")
async def get_camera(camera_id: str, _: CurrentUser = Depends(READ), session: AsyncSession = Depends(db.session)):
    cam = await get_or_404(session, Camera, camera_id, "Камера")
    zones = (await session.execute(select(Zone).where(Zone.camera_id == camera_id).order_by(Zone.id))).scalars()
    rules = (await session.execute(select(Rule).where(Rule.camera_id == camera_id).order_by(Rule.id))).scalars()
    base = await camera_out(session, cam)
    return CameraDetail(**base.model_dump(), zones=[zone_out(z) for z in zones], rules=[rule_out(r) for r in rules])


@app.patch("/cameras/{camera_id}", response_model=CameraOut, tags=["cameras"])
async def patch_camera(camera_id: str, body: CameraPatch, _: CurrentUser = Depends(WRITE), session: AsyncSession = Depends(db.session)):
    cam = await get_or_404(session, Camera, camera_id, "Камера")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(cam, k, v.value if isinstance(v, SourceType) else v)
    await session.commit()
    await publish(session, camera_id)
    return await camera_out(session, cam)


@app.delete("/cameras/{camera_id}", status_code=204, tags=["cameras"])
async def delete_camera(camera_id: str, _: CurrentUser = Depends(WRITE), session: AsyncSession = Depends(db.session)):
    cam = await get_or_404(session, Camera, camera_id, "Камера")
    await session.delete(cam)
    await session.commit()
    await publish(session, camera_id)


@app.get("/cameras/{camera_id}/config", response_model=CameraConfig, tags=["cameras"],
         summary="Конфигурация камеры в том виде, в каком её видит горячий путь")
async def camera_config(camera_id: str, _: CurrentUser = Depends(READ), session: AsyncSession = Depends(db.session)):
    return await build_config(session, await get_or_404(session, Camera, camera_id, "Камера"))


@app.get("/cameras/{camera_id}/snapshot", tags=["cameras"], summary="Последний кадр камеры (JPEG) — фон для редактора зон",
         responses={200: {"content": {"image/jpeg": {}}}})
async def snapshot(camera_id: str, _: CurrentUser = Depends(READ)):
    data = await bus.redis.get(Keys.last_frame(camera_id))
    if not data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Кадров с камеры пока нет: проверьте поток")
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


# --- зоны -----------------------------------------------------------------------------------------


@app.get("/cameras/{camera_id}/zones", response_model=list[ZoneOut], tags=["zones"])
async def list_zones(camera_id: str, _: CurrentUser = Depends(READ), session: AsyncSession = Depends(db.session)):
    return [zone_out(z) for z in (await session.execute(select(Zone).where(Zone.camera_id == camera_id).order_by(Zone.id))).scalars()]


@app.post("/cameras/{camera_id}/zones", response_model=ZoneOut, status_code=201, tags=["zones"])
async def create_zone(camera_id: str, body: ZoneIn, _: CurrentUser = Depends(WRITE), session: AsyncSession = Depends(db.session)):
    await get_or_404(session, Camera, camera_id, "Камера")
    z = Zone(camera_id=camera_id, **{**body.model_dump(), "kind": body.kind.value})
    session.add(z)
    await session.commit()
    await publish(session, camera_id)
    return zone_out(z)


async def _zone(session: AsyncSession, camera_id: str, zone_id: int) -> Zone:
    z = await session.get(Zone, zone_id)
    if z is None or z.camera_id != camera_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Зона не найдена")
    return z


@app.patch("/cameras/{camera_id}/zones/{zone_id}", response_model=ZoneOut, tags=["zones"])
async def patch_zone(camera_id: str, zone_id: int, body: ZonePatch, _: CurrentUser = Depends(WRITE), session: AsyncSession = Depends(db.session)):
    z = await _zone(session, camera_id, zone_id)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(z, k, v.value if isinstance(v, ZoneKind) else v)
    await session.commit()
    await publish(session, camera_id)
    return zone_out(z)


@app.delete("/cameras/{camera_id}/zones/{zone_id}", status_code=204, tags=["zones"], summary="Удалить зону (и её правила)")
async def delete_zone(camera_id: str, zone_id: int, _: CurrentUser = Depends(WRITE), session: AsyncSession = Depends(db.session)):
    z = await _zone(session, camera_id, zone_id)
    await session.execute(delete(Rule).where(Rule.zone_id == zone_id))
    await session.delete(z)
    await session.commit()
    await publish(session, camera_id)


# --- правила ---------------------------------------------------------------------------------------


@app.get("/cameras/{camera_id}/rules", response_model=list[RuleOut], tags=["rules"])
async def list_rules(camera_id: str, _: CurrentUser = Depends(READ), session: AsyncSession = Depends(db.session)):
    return [rule_out(r) for r in (await session.execute(select(Rule).where(Rule.camera_id == camera_id).order_by(Rule.id))).scalars()]


@app.post("/cameras/{camera_id}/rules", response_model=RuleOut, status_code=201, tags=["rules"])
async def create_rule(camera_id: str, body: RuleIn, _: CurrentUser = Depends(WRITE), session: AsyncSession = Depends(db.session)):
    await get_or_404(session, Camera, camera_id, "Камера")
    await validate_rule(session, camera_id, body.scenario, body.zone_id, body.params)
    r = Rule(camera_id=camera_id, scenario=body.scenario, zone_id=body.zone_id, params=body.params,
             severity=body.severity.value if body.severity else None,
             schedule=body.schedule.model_dump(by_alias=True, mode="json") if body.schedule else None,
             valid_until=body.valid_until, enabled=body.enabled)
    session.add(r)
    await session.commit()
    await publish(session, camera_id)
    return rule_out(r)


async def _rule(session: AsyncSession, camera_id: str, rule_id: int) -> Rule:
    r = await session.get(Rule, rule_id)
    if r is None or r.camera_id != camera_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Правило не найдено")
    return r


@app.patch("/cameras/{camera_id}/rules/{rule_id}", response_model=RuleOut, tags=["rules"])
async def patch_rule(camera_id: str, rule_id: int, body: RulePatch, _: CurrentUser = Depends(WRITE), session: AsyncSession = Depends(db.session)):
    r = await _rule(session, camera_id, rule_id)
    data = body.model_dump(exclude_unset=True)
    await validate_rule(session, camera_id, r.scenario, data.get("zone_id", r.zone_id), data.get("params", r.params or {}))
    for k, v in data.items():
        if k == "severity":
            v = v.value if v else None
        elif k == "schedule":
            v = body.schedule.model_dump(by_alias=True, mode="json") if body.schedule else None
        setattr(r, k, v)
    await session.commit()
    await publish(session, camera_id)
    return rule_out(r)


@app.delete("/cameras/{camera_id}/rules/{rule_id}", status_code=204, tags=["rules"])
async def delete_rule(camera_id: str, rule_id: int, _: CurrentUser = Depends(WRITE), session: AsyncSession = Depends(db.session)):
    r = await _rule(session, camera_id, rule_id)
    await session.delete(r)
    await session.commit()
    await publish(session, camera_id)


# --- каталог сценариев ---------------------------------------------------------------------------


@app.get("/scenarios", response_model=list[ScenarioInfo], tags=["scenarios"],
         summary="Каталог сценариев с JSON Schema параметров (публикует analytics-service)")
async def scenarios(_: CurrentUser = Depends(READ)):
    return await load_catalog()
