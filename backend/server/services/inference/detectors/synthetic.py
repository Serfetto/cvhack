"""Детекторы без нейросети — для разработки и проверки конвейера, пока нет моделей ML."""

from __future__ import annotations

import math
import time
import zlib

from common.messages import Obj, Person

from .base import DetectResult

# Поза стоящего человека в долях рамки (x, y), COCO-17
_STAND = [
    (0.50, 0.07), (0.46, 0.05), (0.54, 0.05), (0.42, 0.07), (0.58, 0.07),
    (0.32, 0.20), (0.68, 0.20), (0.25, 0.38), (0.75, 0.38), (0.22, 0.52), (0.78, 0.52),
    (0.38, 0.53), (0.62, 0.53), (0.38, 0.76), (0.62, 0.76), (0.38, 0.98), (0.62, 0.98),
]


class NullDetector:
    name = "null"

    def detect(self, jpeg: bytes, camera_id: str | None = None, ts: float | None = None) -> DetectResult:
        return DetectResult(backend=self.name, latency_ms={"total": 0.0})

    def info(self) -> dict:
        return {"backend": self.name, "models": []}


class SyntheticDetector:
    """Человек ходит по кадру слева направо и обратно (период `period_s`), навстречу едет погрузчик.
    Фаза зависит от камеры, поэтому камеры не синхронны. В левой трети кадра человек ~1/3 периода —
    с зоной из infra/cameras.yml это даёт нарушение `in_zone` примерно раз в период."""

    name = "synthetic"

    def __init__(self, period_s: float = 40.0):
        self.period_s = period_s

    def detect(self, jpeg: bytes, camera_id: str | None = None, ts: float | None = None) -> DetectResult:
        start = time.perf_counter()
        ts = ts or time.time()
        phase = (zlib.crc32((camera_id or "").encode()) % 1000) / 1000
        t = (ts / self.period_s + phase) % 1.0
        x = 0.1 + 0.8 * (1 - abs(2 * t - 1))  # 0.1 → 0.9 → 0.1
        bw, bh = 0.09, 0.36
        x1, y1 = x - bw / 2, 0.55 - bh / 2 + 0.01 * math.sin(ts * 6)
        bbox = [x1, y1, x1 + bw, y1 + bh]
        kpts = [[x1 + px * bw, y1 + py * bh, 0.9] for px, py in _STAND]
        fx = 0.9 - 0.7 * (1 - abs(2 * ((t + 0.5) % 1.0) - 1))
        forklift = Obj(cls="forklift", bbox=[fx - 0.08, 0.45, fx + 0.08, 0.75], score=0.8)
        return DetectResult(
            persons=[Person(bbox=bbox, score=0.9, kpts=kpts)],
            objects=[forklift],
            backend=self.name,
            models={"pose": "synthetic", "objects": "synthetic"},
            latency_ms={"total": round((time.perf_counter() - start) * 1000, 3)},
        )

    def info(self) -> dict:
        return {"backend": self.name, "models": [{"name": "synthetic", "task": "pose+detect", "version": "1"}]}
