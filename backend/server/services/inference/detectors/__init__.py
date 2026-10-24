from __future__ import annotations

from .base import DetectResult, Detector  # noqa: F401
from .fallback import FallbackDetector
from .synthetic import NullDetector, SyntheticDetector


def create_detector(kind: str, *, models_dir: str = "data/models", models: list[str] = ("pose",), remote_url: str = "",
                    remote_timeout_s: float = 2.0, broker_url: str = "",
                    broker_request_queue: str = "cvhack12731.jpeg", broker_timeout_s: float = 3.0,
                    conf: float = 0.35, iou: float = 0.5):
    if kind == "synthetic":
        return SyntheticDetector()
    if kind == "null":
        return NullDetector()
    if kind == "remote":
        from .remote import RemoteDetector

        return RemoteDetector(remote_url, remote_timeout_s)
    if kind == "broker":
        from .broker import BrokerDetector

        return BrokerDetector(broker_url, broker_request_queue, broker_timeout_s)
    if kind in ("onnx", "pytpu"):
        from .local import LocalDetector

        return LocalDetector(kind, models_dir, list(models), conf, iou)
    raise ValueError(f"Неизвестный INFERENCE_BACKEND={kind!r}: synthetic | null | onnx | pytpu | remote | broker")


def create_with_fallback(kind: str, fallback: str | None, **kw):
    primary = create_detector(kind, **kw)
    if not fallback or fallback in ("none", kind):
        return primary
    return FallbackDetector(primary, create_detector(fallback, **kw))
