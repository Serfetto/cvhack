"""Воркер захвата одной камеры: отдельный поток, источник — RTSP, видеофайл (по кругу) или папка кадров.

Кадры прореживаются до analysis_fps, кодируются в JPEG и уходят в Redis:
    SET frame:{cam}:{seq} EX 60 + XADD frames:{shard} MAXLEN ~500
Дополнительно держим кольцевой буфер последних buffer_s секунд (clip_fps) для клипов событий.
"""

from __future__ import annotations

import os
import threading
import time
from collections import deque
from pathlib import Path

import cv2
import numpy as np
import redis
from prometheus_client import Counter, Gauge, Histogram

from common.logging import get_logger
from common.messages import CameraConfig, FrameMsg, Keys, SourceType, Streams, shard_for

log = get_logger(__name__)

os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")

FRAMES = Counter("ingest_frames_total", "Кадры, отправленные на анализ", ["camera"])
FPS = Gauge("ingest_fps", "Фактический FPS анализа", ["camera"])
ENCODE_SECONDS = Histogram("ingest_decode_seconds", "Декод и JPEG-кодирование кадра", ["camera"],
                           buckets=(0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5))
RECONNECTS = Counter("ingest_reconnects_total", "Переподключения к источнику", ["camera"])
ONLINE = Gauge("ingest_online", "1 — поток идёт", ["camera"])

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def _next(target: float, period: float, now: float) -> float:
    """Следующий момент выдачи кадра; если отстали — отсчёт от текущего момента, без серии кадров подряд."""
    nxt = target + period
    return nxt if nxt > now else now + period


class CameraWorker:
    def __init__(self, cfg: CameraConfig, redis_url: str, shards: int, *, jpeg_quality: int = 85, max_side: int = 1280,
                 clip_fps: float = 8.0, buffer_s: float = 20.0):
        self.cfg = cfg
        self.redis_url = redis_url
        self.stream = Streams.frames(shard_for(cfg.id, shards))
        self.jpeg_quality = jpeg_quality
        self.max_side = max_side
        self.clip_period = 1.0 / clip_fps
        self.buffer_s = buffer_s
        self.buffer: deque[tuple[float, bytes]] = deque()
        self.buf_lock = threading.Lock()
        self._stop = threading.Event()
        self.thread = threading.Thread(target=self._run, name=f"cam-{cfg.id}", daemon=True)
        self.state = "connecting"
        self.error: str | None = None
        self.w = self.h = 0
        self.last_frame_ts: float | None = None
        self.emitted: deque[float] = deque(maxlen=200)
        self.reconnects = 0
        self._last_status = 0.0

    # --- управление -----------------------------------------------------------

    def start(self) -> None:
        self.thread.start()

    def stop(self, timeout: float = 3.0) -> None:
        self._stop.set()
        self.thread.join(timeout)

    def fps(self) -> float:
        now = time.time()
        recent = [t for t in self.emitted if now - t <= 5]
        return round(len(recent) / 5, 2)

    def status(self) -> dict:
        return {"camera_id": self.cfg.id, "state": self.state, "fps": self.fps(), "target_fps": self.cfg.analysis_fps,
                "last_frame_ts": self.last_frame_ts, "error": self.error, "w": self.w, "h": self.h,
                "reconnects": self.reconnects, "source_type": self.cfg.source_type.value, "stream": self.stream,
                "buffer_frames": len(self.buffer)}

    def frames_between(self, t0: float, t1: float) -> list[tuple[float, bytes]]:
        with self.buf_lock:
            return [f for f in self.buffer if t0 <= f[0] <= t1]

    # --- поток ---------------------------------------------------------------------

    def _run(self) -> None:
        r = redis.Redis.from_url(self.redis_url)
        backoff = 1.0
        while not self._stop.is_set():
            try:
                self._set_state(r, "connecting")
                if self.cfg.source_type == SourceType.IMAGES:
                    self._run_images(r)
                else:
                    self._run_video(r)
                backoff = 1.0
            except Exception as e:  # обрыв RTSP, нет файла, Redis моргнул
                self.error = f"{type(e).__name__}: {e}"
                self.reconnects += 1
                if self.last_frame_ts and time.time() - self.last_frame_ts < 10:
                    backoff = 1.0  # поток только что работал — переподключаемся быстро
                RECONNECTS.labels(self.cfg.id).inc()
                log.warning("source_error", camera=self.cfg.id, error=self.error, retry_in=backoff)
                try:
                    self._set_state(r, "offline", force=True)
                except redis.RedisError:
                    pass
                self._stop.wait(backoff)
                backoff = min(backoff * 2, 30.0)
        ONLINE.labels(self.cfg.id).set(0)
        try:
            r.delete(Keys.ingest_status(self.cfg.id))
        except redis.RedisError:
            pass

    def _open(self) -> cv2.VideoCapture:
        url = self.cfg.source_url
        if self.cfg.source_type == SourceType.FILE and not Path(url).exists():
            raise FileNotFoundError(url)
        params = [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 10000, cv2.CAP_PROP_READ_TIMEOUT_MSEC, 10000]
        cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG, params)
        if not cap.isOpened():
            raise ConnectionError(f"не удалось открыть {url}")
        return cap

    def _run_video(self, r: redis.Redis) -> None:
        cap = self._open()
        is_file = self.cfg.source_type == SourceType.FILE
        src_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        if not 1 <= src_fps <= 120:
            src_fps = 25.0
        period = 1.0 / max(self.cfg.analysis_fps, 0.1)
        next_emit = next_buf = 0.0
        t_start, media_t = time.time(), 0.0
        grabbed = 0
        try:
            while not self._stop.is_set():
                if not cap.grab():
                    if is_file and grabbed:  # файл кончился — по кругу
                        cap.release()
                        cap = self._open()
                        t_start, media_t, grabbed = time.time(), 0.0, 0
                        continue
                    raise ConnectionError("поток прервался" if grabbed else "из источника не читаются кадры")
                grabbed += 1
                now = time.time()
                if is_file:  # отдаём файл в реальном времени, как камера
                    media_t += 1.0 / src_fps
                    delay = t_start + media_t - now
                    if delay > 0:
                        self._stop.wait(delay)
                        now = time.time()
                    elif delay < -1.0:
                        t_start, media_t = now, 0.0
                need_emit, need_buf = now >= next_emit, now >= next_buf
                if not (need_emit or need_buf):
                    continue
                t0 = time.perf_counter()
                ok, frame = cap.retrieve()
                if not ok or frame is None:
                    continue
                jpeg = self._encode(frame)
                ENCODE_SECONDS.labels(self.cfg.id).observe(time.perf_counter() - t0)
                if need_buf:
                    self._buffer(now, jpeg)
                    next_buf = _next(next_buf, self.clip_period, now)
                if need_emit:
                    self._emit(r, jpeg, now)
                    next_emit = _next(next_emit, period, now)
        finally:
            cap.release()

    def _run_images(self, r: redis.Redis) -> None:
        folder = Path(self.cfg.source_url)
        files = sorted(p for p in folder.iterdir() if p.suffix.lower() in IMAGE_EXT) if folder.is_dir() else []
        if not files:
            raise FileNotFoundError(f"в {folder} нет изображений")
        period = 1.0 / max(self.cfg.analysis_fps, 0.1)
        while not self._stop.is_set():
            for f in files:
                if self._stop.is_set():
                    return
                t0 = time.perf_counter()
                frame = cv2.imread(str(f))
                if frame is None:
                    continue
                jpeg = self._encode(frame)
                ENCODE_SECONDS.labels(self.cfg.id).observe(time.perf_counter() - t0)
                now = time.time()
                self._buffer(now, jpeg)
                self._emit(r, jpeg, now)
                self._stop.wait(max(period - (time.perf_counter() - t0), 0))

    def _encode(self, frame: np.ndarray) -> bytes:
        h, w = frame.shape[:2]
        scale = self.max_side / max(h, w)
        if scale < 1:
            frame = cv2.resize(frame, (int(w * scale) // 2 * 2, int(h * scale) // 2 * 2), interpolation=cv2.INTER_AREA)
        self.h, self.w = frame.shape[:2]
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality])
        if not ok:
            raise RuntimeError("JPEG encode failed")
        return buf.tobytes()

    def _buffer(self, ts: float, jpeg: bytes) -> None:
        with self.buf_lock:
            self.buffer.append((ts, jpeg))
            while self.buffer and ts - self.buffer[0][0] > self.buffer_s:
                self.buffer.popleft()

    def _emit(self, r: redis.Redis, jpeg: bytes, ts: float) -> None:
        cam = self.cfg.id
        seq = int(r.incr(Keys.frame_seq(cam)))
        key = Keys.frame(cam, seq)
        msg = FrameMsg(camera_id=cam, seq=seq, ts=ts, frame_key=key, w=self.w, h=self.h)
        pipe = r.pipeline(transaction=False)
        pipe.set(key, jpeg, ex=60)
        pipe.set(Keys.last_frame(cam), jpeg, ex=600)
        pipe.xadd(self.stream, {"data": msg.model_dump_json()}, maxlen=500, approximate=True)
        pipe.execute()
        self.last_frame_ts = ts
        self.emitted.append(ts)
        self.error = None
        FRAMES.labels(cam).inc()
        self._set_state(r, "online")

    def _set_state(self, r: redis.Redis, state: str, force: bool = False) -> None:
        self.state = state
        ONLINE.labels(self.cfg.id).set(1 if state == "online" else 0)
        now = time.time()
        if not force and now - self._last_status < 1.0:
            return
        self._last_status = now
        FPS.labels(self.cfg.id).set(self.fps())
        st = {k: ("" if v is None else str(v)) for k, v in self.status().items()}
        key = Keys.ingest_status(self.cfg.id)
        pipe = r.pipeline(transaction=False)
        pipe.hset(key, mapping=st)
        pipe.expire(key, 30)
        pipe.execute()
