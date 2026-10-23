"""Детектор — то, что видит inference-service: JPEG на вход, люди и объекты на выход.

Реализации:
- `synthetic` — фейковый человек ходит по кадру (сквозная проверка конвейера без ML);
- `null` — пустые детекции;
- `onnx` / `pytpu` — LocalDetector: ml_runtime + бэкенд из backends/;
- `remote` — tpu-worker на стенде LinQ по HTTP (POST /detect);
- FallbackDetector — основной + аварийный (переключение при ошибках).
"""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, Field

from common.messages import Obj, Person


class DetectResult(BaseModel):
    persons: list[Person] = Field(default_factory=list)
    objects: list[Obj] = Field(default_factory=list)
    backend: str = ""
    models: dict[str, str] = Field(default_factory=dict)
    # pre, infer, post, rpc, total — миллисекунды
    latency_ms: dict[str, float] = Field(default_factory=dict)


class Detector(Protocol):
    name: str

    def detect(self, jpeg: bytes, camera_id: str | None = None, ts: float | None = None) -> DetectResult: ...

    def info(self) -> dict[str, Any]: ...
