"""Основной детектор + аварийный: если стенд LinQ недоступен, кадры идут в onnx на CPU,
а через `retry_s` секунд снова пробуем основной. Режим виден в метриках и в GET /models."""

from __future__ import annotations

import time

from common.logging import get_logger

from .base import DetectResult

log = get_logger(__name__)


class FallbackDetector:
    def __init__(self, primary, secondary, retry_s: float = 30.0, max_failures: int = 3):
        self.primary, self.secondary = primary, secondary
        self.retry_s = retry_s
        self.max_failures = max_failures
        self.failures = 0
        self.fallback_until = 0.0
        self.last_error: str | None = None

    @property
    def name(self) -> str:
        return self.secondary.name if self.active_fallback else self.primary.name

    @property
    def active_fallback(self) -> bool:
        return time.monotonic() < self.fallback_until

    def detect(self, jpeg: bytes, camera_id: str | None = None, ts: float | None = None) -> DetectResult:
        if not self.active_fallback:
            try:
                res = self.primary.detect(jpeg, camera_id, ts)
                self.failures = 0
                return res
            except Exception as e:
                self.failures += 1
                self.last_error = f"{type(e).__name__}: {e}"
                if self.failures >= self.max_failures:
                    self.fallback_until = time.monotonic() + self.retry_s
                    log.error("fallback_on", primary=self.primary.name, secondary=self.secondary.name, error=self.last_error)
                    self.failures = 0
                else:
                    raise
        res = self.secondary.detect(jpeg, camera_id, ts)
        res.backend = f"{res.backend} (аварийный)"
        return res

    def info(self) -> dict:
        return {**self.primary.info(), "fallback": {"active": self.active_fallback, "backend": self.secondary.name,
                                                    "last_error": self.last_error}}
