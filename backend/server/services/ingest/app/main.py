"""ingest-service: воркер на каждую камеру (RTSP / файл / папка кадров) → frames:{shard}; клипы событий."""

from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from prometheus_client import Counter

from common.bus import Bus, MsgCtx, default_consumer_name
from common.camconfig import CameraRegistry
from common.logging import get_logger
from common.messages import CameraConfig, ClipReady, ClipRequest, Streams
from common.service import Supervisor, create_app
from common.settings import BaseServiceSettings
from common.storage import Storage

from .capture import CameraWorker
from .clips import clip_key, encode_mp4

log = get_logger(__name__)


class Settings(BaseServiceSettings):
    service_name: str = "ingest"
    cameras_yaml: str | None = "/app/infra/cameras.yml"
    jpeg_quality: int = 85
    max_side: int = 1280
    clip_fps: float = 8.0
    buffer_s: float = 20.0


settings = Settings()
bus = Bus(settings.redis_url)
storage = Storage.from_settings(settings)
registry = CameraRegistry(bus, settings.cameras_yaml)
sup = Supervisor()
workers: dict[str, CameraWorker] = {}
clip_tasks: set[asyncio.Task] = set()

CLIPS = Counter("ingest_clips_total", "Клипы событий", ["status"])


def _source_key(c: CameraConfig) -> tuple:
    return c.source_type, c.source_url, c.analysis_fps


def start_worker(cfg: CameraConfig) -> None:
    w = CameraWorker(cfg, settings.redis_url, settings.frame_shards, jpeg_quality=settings.jpeg_quality,
                     max_side=settings.max_side, clip_fps=settings.clip_fps, buffer_s=settings.buffer_s)
    workers[cfg.id] = w
    w.start()
    log.info("worker_started", camera=cfg.id, source=cfg.source_url, fps=cfg.analysis_fps, stream=w.stream)


async def stop_worker(cid: str) -> None:
    w = workers.pop(cid, None)
    if w:
        await asyncio.to_thread(w.stop)
        log.info("worker_stopped", camera=cid)


async def sync_workers(changed: set[str]) -> None:
    for cid in changed:
        cfg = registry.cameras.get(cid)
        w = workers.get(cid)
        if cfg is None or not cfg.enabled:
            await stop_worker(cid)
        elif w is None:
            start_worker(cfg)
        elif _source_key(w.cfg) != _source_key(cfg):
            await stop_worker(cid)
            start_worker(cfg)
        else:
            w.cfg = cfg


async def build_clip(req: ClipRequest) -> None:
    w = workers.get(req.camera_id)
    try:
        if w is None:
            raise RuntimeError("камера не обслуживается этим ingest")
        wait = req.t1 + 0.5 - time.time()
        if wait > 0:
            await asyncio.sleep(min(wait, 30))
        frames = w.frames_between(req.t0, req.t1)
        if len(frames) < 2:
            raise RuntimeError(f"в буфере нет кадров за [{req.t0:.1f}, {req.t1:.1f}]")
        mp4 = await asyncio.to_thread(encode_mp4, frames)
        key = clip_key(req.event_id, req.t0)
        await storage.put(key, mp4, "video/mp4")
        await bus.xadd(Streams.CLIP_READY, ClipReady(event_id=req.event_id, camera_id=req.camera_id, status="ready", clip_key=key))
        CLIPS.labels("ready").inc()
        log.info("clip_ready", event_id=req.event_id, frames=len(frames), size=len(mp4))
    except Exception as e:
        CLIPS.labels("failed").inc()
        log.warning("clip_failed", event_id=req.event_id, error=str(e))
        await bus.xadd(Streams.CLIP_READY, ClipReady(event_id=req.event_id, camera_id=req.camera_id, status="failed", error=str(e)[:300]))


async def on_clip_request(req: ClipRequest, ctx: MsgCtx) -> None:
    # клип ждёт окончания окна (t1) — собираем в отдельной задаче, чтобы не задерживать другие запросы
    t = asyncio.create_task(build_clip(req))
    clip_tasks.add(t)
    t.add_done_callback(clip_tasks.discard)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await bus.wait_ready()
    await storage.ensure_bucket()
    await sync_workers(await registry.refresh())
    log.info("ingest_started", cameras=sorted(workers), config_source=registry.source)
    sup.spawn("watch-config", lambda: registry.watch(sync_workers))
    sup.spawn("consume-clips", lambda: bus.consume(
        [Streams.CLIP_REQUESTS], "ingest", default_consumer_name("ingest"), ClipRequest, on_clip_request, start_id="$"))
    yield
    await sup.stop()
    for cid in list(workers):
        await stop_worker(cid)
    await bus.close()


app = create_app(settings, "ingest-service", "Захват видео: RTSP / файлы / папки кадров → очередь кадров; клипы событий", lifespan=lifespan)


@app.get("/streams", tags=["streams"], summary="Статус потоков: состояние, фактический FPS, ошибки")
async def streams():
    return {"config_source": registry.source, "streams": [w.status() for w in workers.values()]}


@app.post("/streams/{camera_id}/restart", tags=["streams"], summary="Перезапустить захват камеры")
async def restart(camera_id: str):
    cfg = registry.cameras.get(camera_id)
    if cfg is None:
        raise HTTPException(404, "Камера не найдена в конфигурации")
    await stop_worker(camera_id)
    if cfg.enabled:
        start_worker(cfg)
    return {"ok": True}
