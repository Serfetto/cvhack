"""Доказательство нарушения: исходный кадр (SHA-256 для журнала) и кадр с рамкой и зоной."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import cv2
import numpy as np

SEVERITY_BGR = {"critical": (40, 40, 230), "high": (0, 140, 255), "medium": (0, 210, 255), "low": (200, 200, 200)}


def keys_for(event_id: str, ts: float) -> tuple[str, str]:
    d = datetime.fromtimestamp(ts, UTC)
    base = f"events/{d:%Y/%m/%d}/{event_id}"
    return f"{base}.jpg", f"{base}_annotated.jpg"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def annotate(jpeg: bytes, bbox: list[float] | None, polygon: list[list[float]] | None, label: str, severity: str) -> bytes:
    img = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return jpeg
    h, w = img.shape[:2]
    color = SEVERITY_BGR.get(severity, (0, 0, 255))
    thick = max(2, w // 400)
    if polygon:
        pts = np.array([[int(x * w), int(y * h)] for x, y in polygon], np.int32)
        overlay = img.copy()
        cv2.fillPoly(overlay, [pts], (0, 0, 200))
        img = cv2.addWeighted(overlay, 0.18, img, 0.82, 0)
        cv2.polylines(img, [pts], True, (0, 0, 220), thick)
    if bbox:
        x1, y1, x2, y2 = int(bbox[0] * w), int(bbox[1] * h), int(bbox[2] * w), int(bbox[3] * h)
        cv2.rectangle(img, (x1, y1), (x2, y2), color, thick + 1)
        # латиница/цифры: шрифты OpenCV не умеют кириллицу, подпись на русском рисует фронтенд
        cv2.putText(img, label, (x1, max(y1 - 8, 16)), cv2.FONT_HERSHEY_SIMPLEX, max(0.5, w / 1600), color, thick)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 88])
    return buf.tobytes() if ok else jpeg
