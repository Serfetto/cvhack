"""inference-service: frames:{shard} → детектор (TPU / CPU / удалённый) → detections.

Тот же сервис работает как tpu-worker на стенде LinQ: INFERENCE_BACKEND=pytpu CONSUME=false —
тогда он не читает очереди, а отвечает на POST /detect.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from prometheus_client import Counter, Gauge, Histogram
from pydantic import BaseModel, Field

from common.bus import Bus, MsgCtx, default_consumer_name
from common.logging import get_logger
from common.messages import DetectionsMsg, FrameMsg, Keys, Streams
from common.metrics import LATENCY_BUCKETS
from common.service import Supervisor, create_app
from common.settings import BaseServiceSettings
from detectors import DetectResult, FallbackDetector, create_detector, create_with_fallback

log = get_logger(__name__)


class Settings(BaseServiceSettings):
    service_name: str = "inference"
    inference_backend: str = "synthetic"
    inference_fallback: str = "none"
    remote_url: str = ""
    remote_timeout_s: float = 2.0
    models_dir: str = "/app/data/models"
    models: str = "pose"
    conf: float = 0.35
    iou: float = 0.5
    max_frame_age_s: float = 2.0
    shards: str = "all"
    consume: bool = True
    benchmark_reports_dir: str = "/app/ml/benchmark/out"


settings = Settings()
bus = Bus(settings.redis_url)
sup = Supervisor()
detector = None
lock = threading.Lock()
processed: deque[float] = deque(maxlen=500)

STAGE_SECONDS = Histogram("inference_seconds", "Время инференса по стадиям", ["stage", "backend"], buckets=LATENCY_BUCKETS)
LAG_SECONDS = Histogram("stream_lag_seconds", "Задержка кадра до обработки", ["stream"], buckets=LATENCY_BUCKETS)
FRAMES = Counter("inference_frames_total", "Обработанные кадры", ["backend"])
DROPPED = Counter("inference_dropped_total", "Пропущенные кадры", ["reason"])
ERRORS = Counter("inference_errors_total", "Ошибки инференса", ["backend"])
FALLBACK = Gauge("inference_fallback_active", "1 — работает аварийный бэкенд")
FPS = Gauge("inference_fps", "Кадров в секунду за последние 10 с")


def run_detect(jpeg: bytes, camera_id: str | None, ts: float | None) -> DetectResult:
    with lock:  # TPU выполняет программы по одной: бенчмарк и конвейер не мешают друг другу
        return detector.detect(jpeg, camera_id, ts)


def current_fps() -> float:
    now = time.time()
    n = sum(1 for t in processed if now - t <= 10)
    return round(n / 10, 2)


def shard_list() -> list[int]:
    if settings.shards == "all":
        return list(range(settings.frame_shards))
    return [int(x) for x in settings.shards.split(",") if x.strip()]


async def on_frame(msg: FrameMsg, ctx: MsgCtx) -> None:
    age = time.time() - msg.ts
    LAG_SECONDS.labels("frames").observe(max(age, 0))
    if age > settings.max_frame_age_s:
        DROPPED.labels("stale").inc()
        return
    jpeg = await bus.redis.get(msg.frame_key)
    if not jpeg:
        DROPPED.labels("expired").inc()
        return
    picked = time.time()
    try:
        res = await asyncio.to_thread(run_detect, jpeg, msg.camera_id, msg.ts)
    except Exception as e:
        ERRORS.labels(getattr(detector, "name", "?")).inc()
        log.warning("detect_failed", camera=msg.camera_id, seq=msg.seq, error=f"{type(e).__name__}: {e}")
        return  # кадр не повторяем: важнее следующий, свежий
    latency = {"queue": round((picked - msg.ts) * 1000, 3), **res.latency_ms}
    for stage in ("pre", "infer", "post", "rpc", "total"):
        if stage in latency:
            STAGE_SECONDS.labels(stage, res.backend).observe(latency[stage] / 1000)
    FRAMES.labels(res.backend).inc()
    processed.append(time.time())
    await bus.xadd(Streams.DETECTIONS, DetectionsMsg(
        camera_id=msg.camera_id, seq=msg.seq, ts=msg.ts, frame_key=msg.frame_key, w=msg.w, h=msg.h,
        backend=res.backend, models=res.models, latency_ms=latency, persons=res.persons, objects=res.objects,
    ), maxlen=2000)


async def publish_status() -> None:
    while True:
        fb = isinstance(detector, FallbackDetector) and detector.active_fallback
        FALLBACK.set(1 if fb else 0)
        FPS.set(current_fps())
        status = {"backend": detector.name, "fallback_active": fb, "fps": current_fps(), "updated_at": time.time()}
        await bus.set_json(Keys.INFERENCE_STATUS, status, ex=30)
        await asyncio.sleep(5)


def build_detector():
    kw = dict(models_dir=settings.models_dir, models=[m.strip() for m in settings.models.split(",") if m.strip()],
              remote_url=settings.remote_url, remote_timeout_s=settings.remote_timeout_s, conf=settings.conf, iou=settings.iou)
    try:
        return create_with_fallback(settings.inference_backend, settings.inference_fallback, **kw)
    except Exception as e:
        if settings.inference_fallback in ("", "none", settings.inference_backend):
            raise
        log.error("primary_backend_init_failed", backend=settings.inference_backend, error=str(e), using=settings.inference_fallback)
        return create_detector(settings.inference_fallback, **kw)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global detector
    detector = await asyncio.to_thread(build_detector)
    log.info("detector_ready", **{k: v for k, v in detector.info().items() if k in ("backend", "url")})
    if settings.consume:
        await bus.wait_ready()
        for shard in shard_list():
            stream = Streams.frames(shard)
            sup.spawn(f"consume-{stream}", lambda s=stream: bus.consume(
                [s], "inference", default_consumer_name("inference"), FrameMsg, on_frame, count=20, start_id="$"))
        sup.spawn("status", publish_status)
    yield
    await sup.stop()
    await bus.close()


app = create_app(settings, "inference-service", "Шлюз к LinQ TPU: кадры → детекции. Бенчмарк FPS и задержек.", lifespan=lifespan)


# --- API -------------------------------------------------------------------------------


@app.get("/models", tags=["inference"], summary="Активный бэкенд и модели (версия, вход, пресет компиляции)")
async def models():
    return {**detector.info(), "active_backend": detector.name, "consume": settings.consume,
            "shards": shard_list() if settings.consume else [], "fps": current_fps()}


@app.post("/detect", response_model=DetectResult, tags=["inference"],
          summary="Детекция по одному кадру: тело запроса — JPEG (так ходит RemoteDetector)",
          openapi_extra={"requestBody": {"content": {"image/jpeg": {"schema": {"type": "string", "format": "binary"}}}, "required": True}})
async def detect(request: Request, camera_id: str | None = Query(None), ts: float | None = Query(None)):
    jpeg = await request.body()
    if not jpeg:
        raise HTTPException(400, "Пустое тело: ожидается JPEG")
    try:
        return await asyncio.to_thread(run_detect, jpeg, camera_id, ts)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.post("/detect/upload", response_model=DetectResult, tags=["inference"], summary="То же, но файлом (удобно из Swagger)")
async def detect_upload(file: UploadFile = File(...)):
    return await asyncio.to_thread(run_detect, await file.read(), None, None)


class BenchmarkIn(BaseModel):
    runs: int = Field(default=200, ge=1, le=5000)
    warmup: int = Field(default=20, ge=0, le=500)
    camera_id: str | None = Field(default=None, description="Взять последний кадр камеры; пусто — синтетический кадр 1280×720")


def _pct(xs: list[float], q: float) -> float:
    return round(float(np.percentile(xs, q)), 3) if xs else 0.0


def _bench(jpeg: bytes, runs: int, warmup: int) -> dict:
    for _ in range(warmup):
        run_detect(jpeg, "bench", time.time())
    stages: dict[str, list[float]] = {}
    wall = []
    for _ in range(runs):
        t = time.perf_counter()
        res = run_detect(jpeg, "bench", time.time())
        wall.append((time.perf_counter() - t) * 1000)
        for k, v in res.latency_ms.items():
            stages.setdefault(k, []).append(v)
    stages["total"] = wall
    info = detector.info()
    m = info.get("models") or [{}]
    return {
        "model": "+".join(x.get("name", "?") for x in m),
        "program": ",".join(str(x.get("program")) for x in m if x.get("program")) or None,
        "backend": detector.name,
        "batch": 1,
        "input": m[0].get("input"),
        "runs": runs,
        "measured_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "latency_ms": {k: {"p50": _pct(v, 50), "p95": _pct(v, 95), "mean": round(float(np.mean(v)), 3)} for k, v in stages.items()},
        "fps": round(runs / (sum(wall) / 1000), 2) if wall else 0.0,
        "source": "inference-service",
    }


@app.post("/benchmark", tags=["inference"], summary="Замер: N прогонов одного кадра → FPS и p50/p95 по стадиям")
async def benchmark(body: BenchmarkIn):
    jpeg = None
    if body.camera_id and settings.consume:
        jpeg = await bus.redis.get(Keys.last_frame(body.camera_id))
        if not jpeg:
            raise HTTPException(404, "Нет последнего кадра этой камеры")
    if jpeg is None:
        img = np.random.default_rng(0).integers(0, 255, (720, 1280, 3), dtype=np.uint8)
        jpeg = cv2.imencode(".jpg", img)[1].tobytes()
    report = await asyncio.to_thread(_bench, jpeg, body.runs, body.warmup)
    if settings.consume:
        await bus.redis.lpush(Keys.BENCHMARKS, json.dumps(report, ensure_ascii=False))
        await bus.redis.ltrim(Keys.BENCHMARKS, 0, 49)
    return report


@app.get("/benchmarks", tags=["inference"], summary="История замеров: из сервиса и JSON-отчёты ML (ml/benchmark/out)")
async def benchmarks():
    out = []
    if settings.consume:
        out += [json.loads(x) for x in await bus.redis.lrange(Keys.BENCHMARKS, 0, 49)]
    d = Path(settings.benchmark_reports_dir)
    if d.is_dir():
        for f in sorted(d.glob("*.json")):
            try:
                rep = json.loads(f.read_text(encoding="utf-8"))
                for r in rep if isinstance(rep, list) else [rep]:
                    out.append({**r, "source": f"ml/{f.name}"})
            except ValueError:
                log.warning("bad_benchmark_report", file=f.name)
    return sorted(out, key=lambda r: r.get("measured_at", ""), reverse=True)
