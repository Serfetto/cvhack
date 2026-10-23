"""analytics-service: детекции → трекинг → сценарии → подтверждение → violations + доказательства в MinIO."""

from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from prometheus_client import Counter, Gauge, Histogram

from common.bus import Bus, MsgCtx, default_consumer_name
from common.camconfig import CameraRegistry
from common.logging import get_logger
from common.messages import DetectionsMsg, Keys, ScenarioInfo, Streams, ViolationMsg
from common.metrics import LATENCY_BUCKETS
from common.service import Supervisor, create_app
from common.settings import BaseServiceSettings
from common.storage import Storage
from engine import Engine, Transition
from scenarios import LOAD_ERRORS, catalog

from . import evidence

log = get_logger(__name__)


class Settings(BaseServiceSettings):
    service_name: str = "analytics"
    tracker: str = "bytetrack"
    cameras_yaml: str | None = "/app/infra/cameras.yml"
    save_annotated: bool = True


settings = Settings()
bus = Bus(settings.redis_url)
storage = Storage.from_settings(settings)
registry = CameraRegistry(bus, settings.cameras_yaml)
engine = Engine(settings.tracker, settings.app_tz)
sup = Supervisor()

STEP_SECONDS = Histogram("analytics_step_seconds", "Трекинг и правила на кадр", ["camera"], buckets=LATENCY_BUCKETS)
LAG_SECONDS = Histogram("stream_lag_seconds", "Задержка кадра до обработки", ["stream"], buckets=LATENCY_BUCKETS)
VIOLATIONS = Counter("violations_total", "Начала и окончания нарушений", ["camera", "scenario", "kind"])
TRACKS = Gauge("analytics_tracks", "Активные треки людей", ["camera"])
EVIDENCE_ERRORS = Counter("evidence_errors_total", "Ошибки сохранения доказательств")


async def save_evidence(t: Transition, msg: ViolationMsg) -> None:
    if not t.frame_key:
        return
    jpeg = await bus.redis.get(t.frame_key)
    if not jpeg:
        log.warning("evidence_frame_expired", event_id=t.event_id, frame_key=t.frame_key)
        return
    clean_key, ann_key = evidence.keys_for(t.event_id, t.started_at or t.frame_ts)
    try:
        uploads = [storage.put(clean_key, jpeg, "image/jpeg")]
        if settings.save_annotated:
            label = f"{t.scenario} #{t.track_id}" if t.track_id is not None else t.scenario
            ann = await asyncio.to_thread(evidence.annotate, jpeg, t.bbox, t.zone.coords if t.zone else None, label, t.severity.value)
            uploads.append(storage.put(ann_key, ann, "image/jpeg"))
        await asyncio.gather(*uploads)
        msg.snapshot_key, msg.snapshot_sha256 = clean_key, evidence.sha256(jpeg)
        msg.annotated_key = ann_key if settings.save_annotated else None
    except Exception:
        EVIDENCE_ERRORS.inc()
        log.exception("evidence_upload_failed", event_id=t.event_id)


async def emit(transitions: list[Transition]) -> None:
    for t in transitions:
        msg = t.to_violation()
        if t.kind == "started":
            await save_evidence(t, msg)
        await bus.xadd(Streams.VIOLATIONS, msg)
        VIOLATIONS.labels(t.camera.id, t.scenario, t.kind).inc()
        log.info("violation", kind=t.kind, event_id=t.event_id, camera=t.camera.id, scenario=t.scenario,
                 track=t.track_id, confidence=t.confidence)
    if transitions:
        await save_state()


async def save_state() -> None:
    await bus.set_json(Keys.ANALYTICS_STATE, engine.snapshot())


async def persist_state() -> None:
    while True:
        await asyncio.sleep(2)
        await save_state()


async def on_detections(det: DetectionsMsg, ctx: MsgCtx) -> None:
    LAG_SECONDS.labels("detections").observe(max(time.time() - det.ts, 0))
    start = time.perf_counter()
    transitions = engine.process(det)
    STEP_SECONDS.labels(det.camera_id).observe(time.perf_counter() - start)
    rt = engine.cameras.get(det.camera_id)
    if rt:
        TRACKS.labels(det.camera_id).set(len(rt.tracks))
    if transitions:
        await emit(transitions)


async def on_config_change(changed: set[str]) -> None:
    ended = []
    for cid in changed:
        cfg = registry.cameras.get(cid)
        ended += engine.set_config(cfg) if cfg else engine.remove_camera(cid)
    if ended:
        await emit(ended)


async def publish_catalog() -> None:
    await bus.set_json(Keys.SCENARIO_CATALOG, [s.model_dump(mode="json") for s in catalog()])


@asynccontextmanager
async def lifespan(app: FastAPI):
    for name, err in LOAD_ERRORS.items():
        log.error("scenario_load_failed", module=name, error=err)
    await bus.wait_ready()
    await storage.ensure_bucket()
    await publish_catalog()
    await on_config_change(await registry.refresh())
    restored = engine.restore(await bus.get_json(Keys.ANALYTICS_STATE) or {}, time.time())
    log.info("analytics_started", cameras=sorted(registry.cameras), config_source=registry.source,
             scenarios=[s.code for s in catalog()], restored_violations=restored)
    sup.spawn("consume-detections", lambda: bus.consume(
        [Streams.DETECTIONS], "analytics", default_consumer_name("analytics"), DetectionsMsg, on_detections, count=50))
    sup.spawn("watch-config", lambda: registry.watch(on_config_change))
    sup.spawn("persist-state", persist_state)
    yield
    await sup.stop()
    await bus.close()


app = create_app(settings, "analytics-service", "Трекинг, сценарии нарушений, подтверждение и подавление повторов", lifespan=lifespan)


@app.get("/scenarios", response_model=list[ScenarioInfo], tags=["analytics"], summary="Загруженные сценарии")
async def scenarios():
    return catalog()


@app.get("/scenarios/errors", tags=["analytics"], summary="Сценарии, которые не загрузились (трассировка)")
async def scenario_errors():
    return LOAD_ERRORS


@app.get("/state", tags=["analytics"], summary="Состояние по камерам: треки, автоматы, активные нарушения")
async def state():
    return {"config_source": registry.source, "cameras": engine.stats()}
