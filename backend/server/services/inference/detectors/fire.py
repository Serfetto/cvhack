"""FireDetector — обёртка над любым детектором: к его объектам добавляет `fire` от FireFinder
(ml_runtime/fire.py, цвет + мерцание, без нейросети). Работает на CPU сервиса по тому же JPEG,
поэтому огонь ищется и при broker/remote, и в аварийном режиме."""

from __future__ import annotations

import time

import cv2
import numpy as np

from common.messages import Obj
from ml_runtime.fire import FireFinder

from .base import DetectResult


class FireDetector:
    def __init__(self, inner, finder: FireFinder | None = None):
        self.inner = inner
        self.finder = finder or FireFinder()

    @property
    def name(self) -> str:
        return self.inner.name

    @property
    def active_fallback(self) -> bool:
        return bool(getattr(self.inner, "active_fallback", False))

    def detect(self, jpeg: bytes, camera_id: str | None = None, ts: float | None = None) -> DetectResult:
        res = self.inner.detect(jpeg, camera_id, ts)
        t = time.perf_counter()
        # декодирование сразу в половинном размере — дешевле полного
        img = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_REDUCED_COLOR_2)
        if img is not None:
            res.objects = [*res.objects, *(Obj(**o) for o in self.finder.find(img, camera_id or "_"))]
        res.models = {**res.models, "fire": "color+flicker"}
        res.latency_ms = {**res.latency_ms, "fire": round((time.perf_counter() - t) * 1000, 3)}
        return res

    def info(self) -> dict:
        return {**self.inner.info(), "fire": {"method": "color+flicker", "flicker_min": self.finder.flicker_min}}
