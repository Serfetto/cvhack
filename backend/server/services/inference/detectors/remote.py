"""RemoteDetector (режим A1): кадры уходят JPEG-ом на tpu-worker стенда LinQ, обратно — JSON детекций.

tpu-worker — это тот же inference-service, запущенный на стенде с INFERENCE_BACKEND=pytpu и CONSUME=false:
    POST {REMOTE_URL}/detect   тело — JPEG (Content-Type: image/jpeg)   →   DetectResult (JSON)
"""

from __future__ import annotations

import time

import httpx

from .base import DetectResult


class RemoteDetector:
    name = "remote"

    def __init__(self, url: str, timeout_s: float = 2.0):
        self.url = url.rstrip("/")
        self.client = httpx.Client(timeout=timeout_s, limits=httpx.Limits(max_keepalive_connections=4))
        self._info: dict | None = None

    def detect(self, jpeg: bytes, camera_id: str | None = None, ts: float | None = None) -> DetectResult:
        start = time.perf_counter()
        params = {k: v for k, v in (("camera_id", camera_id), ("ts", ts)) if v is not None}
        r = self.client.post(f"{self.url}/detect", content=jpeg, params=params, headers={"Content-Type": "image/jpeg"})
        r.raise_for_status()
        res = DetectResult.model_validate(r.json())
        total = (time.perf_counter() - start) * 1000
        remote_total = res.latency_ms.get("total", 0.0)
        res.latency_ms["rpc"] = round(max(total - remote_total, 0.0), 3)
        res.latency_ms["total"] = round(total, 3)
        res.backend = f"remote:{res.backend}" if res.backend else "remote"
        return res

    def info(self) -> dict:
        try:
            info = self.client.get(f"{self.url}/models").json()
        except httpx.HTTPError as e:
            return {"backend": self.name, "url": self.url, "error": str(e), "models": []}
        return {"backend": f"remote:{info.get('backend', '?')}", "url": self.url, "models": info.get("models", [])}
