"""Контракты между сервисами: сообщения очередей, конфигурация камер, формат событий для API и WebSocket.

Все координаты (рамки, ключевые точки, полигоны) нормированы к 0..1 по ширине и высоте кадра.
Рамка — [x1, y1, x2, y2]. Время в очередях — unix-время в секундах (float), в API — ISO 8601 с часовым поясом.

Менять поля — только после обсуждения в чате команды (docs/plans/README.md).
"""

from __future__ import annotations

import zlib
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class Severity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


SEVERITY_RANK = {Severity.LOW: 0, Severity.MEDIUM: 1, Severity.HIGH: 2, Severity.CRITICAL: 3}


class EventStatus(StrEnum):
    NEW = "new"
    CONFIRMED = "confirmed"
    FALSE = "false"
    FORWARDED = "forwarded"
    RESOLVED = "resolved"


class Role(StrEnum):
    ADMIN = "admin"
    HSE = "hse"
    MASTER = "master"
    OPERATOR = "operator"
    MANAGER = "manager"
    AUDITOR = "auditor"


class ViolationKind(StrEnum):
    STARTED = "started"
    ENDED = "ended"


class ZoneKind(StrEnum):
    DANGER = "danger"
    NO_SMOKING = "no_smoking"
    HEIGHT = "height"
    FENCE = "fence"
    FORBIDDEN = "forbidden"


class SourceType(StrEnum):
    RTSP = "rtsp"
    FILE = "file"
    IMAGES = "images"


# ---------------------------------------------------------------------------
# Имена потоков, каналов и ключей Redis
# ---------------------------------------------------------------------------


class Streams:
    DETECTIONS = "detections"
    VIOLATIONS = "violations"
    CLIP_REQUESTS = "clips:requests"
    CLIP_READY = "clips:ready"

    @staticmethod
    def frames(shard: int) -> str:
        return f"frames:{shard}"


class Channels:
    CONFIG_UPDATED = "config.updated"
    EVENTS_CREATED = "events.created"
    EVENTS_UPDATED = "events.updated"
    EVENTS_ESCALATED = "events.escalated"
    EVENTS_PATTERN = "events.*"


class Keys:
    CAMERA_CONFIGS = "config:cameras"          # hash: camera_id → CameraConfig JSON
    SCENARIO_CATALOG = "scenarios:catalog"     # JSON-список ScenarioInfo, пишет analytics
    BENCHMARKS = "inference:benchmarks"        # список последних отчётов бенчмарка
    INFERENCE_STATUS = "inference:status"      # JSON: активный бэкенд, модели, аварийный режим
    NOTIFY_USERS = "notify:users"              # hash: user_id → {role, area_ids, telegram_chat_id, prefs}
    ANALYTICS_STATE = "analytics:state"        # JSON: активные нарушения и паузы — переживают рестарт analytics

    @staticmethod
    def frame(camera_id: str, seq: int) -> str:
        return f"frame:{camera_id}:{seq}"

    @staticmethod
    def last_frame(camera_id: str) -> str:
        return f"frame:last:{camera_id}"

    @staticmethod
    def frame_seq(camera_id: str) -> str:
        return f"seq:{camera_id}"

    @staticmethod
    def ingest_status(camera_id: str) -> str:
        return f"ingest:status:{camera_id}"


def shard_for(camera_id: str, shards: int) -> int:
    """Шард потока кадров для камеры: стабильный хэш, чтобы кадры камеры шли в одну очередь по порядку."""
    return zlib.crc32(camera_id.encode()) % max(shards, 1)


# ---------------------------------------------------------------------------
# Горячий путь: frames → detections → violations
# ---------------------------------------------------------------------------

BBox = list[float]  # [x1, y1, x2, y2], 0..1


class FrameMsg(BaseModel):
    """frames:{shard} — кадр лежит в Redis под frame_key (JPEG, TTL 60 с)."""

    camera_id: str
    seq: int
    ts: float
    frame_key: str
    w: int
    h: int


class Person(BaseModel):
    bbox: BBox
    score: float
    # 17 точек COCO: [x, y, conf]; None — модель без поз
    kpts: list[list[float]] | None = None


class Obj(BaseModel):
    cls: str
    bbox: BBox
    score: float


class DetectionsMsg(BaseModel):
    """detections — результат инференса одного кадра."""

    camera_id: str
    seq: int
    ts: float
    frame_key: str
    w: int
    h: int
    backend: str = ""
    models: dict[str, str] = Field(default_factory=dict)
    # queue, rpc, pre, infer, post, total
    latency_ms: dict[str, float] = Field(default_factory=dict)
    persons: list[Person] = Field(default_factory=list)
    objects: list[Obj] = Field(default_factory=list)


class ViolationMsg(BaseModel):
    """violations — начало (started) или конец (ended) нарушения. event_id одинаковый у пары."""

    event_id: str
    kind: ViolationKind
    camera_id: str
    camera_name: str | None = None
    area_id: int | None = None
    zone_id: int | None = None
    zone_name: str | None = None
    rule_id: int | None = None
    scenario: str
    scenario_title: str | None = None
    severity: Severity = Severity.MEDIUM
    track_id: int | None = None
    started_at: float
    confirmed_at: float | None = None
    ended_at: float | None = None
    snapshot_key: str | None = None
    snapshot_sha256: str | None = None
    annotated_key: str | None = None
    bbox: BBox | None = None
    confidence: float | None = None
    # время кадра, подтвердившего нарушение: по нему считаем сквозную задержку
    frame_ts: float | None = None
    seq: int | None = None
    demo: bool = False


class ClipRequest(BaseModel):
    event_id: str
    camera_id: str
    t0: float
    t1: float


class ClipReady(BaseModel):
    event_id: str
    camera_id: str
    status: Literal["ready", "failed"]
    clip_key: str | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# Конфигурация камер (camera-service → Redis → ingest, analytics)
# ---------------------------------------------------------------------------


class Schedule(BaseModel):
    """Когда правило действует. days: 0 — понедельник … 6 — воскресенье; пусто — каждый день.
    from/to — «ЧЧ:ММ» по местному времени; если from > to, интервал переходит через полночь."""

    days: list[int] = Field(default_factory=list)
    from_: str | None = Field(default=None, alias="from")
    to: str | None = None

    model_config = {"populate_by_name": True}


class ZoneCfg(BaseModel):
    id: int
    name: str
    kind: ZoneKind = ZoneKind.DANGER
    polygon: list[list[float]]
    enabled: bool = True


class RuleCfg(BaseModel):
    id: int
    scenario: str
    zone_id: int | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    severity: Severity | None = None
    schedule: Schedule | None = None
    valid_until: datetime | None = None
    enabled: bool = True


class CameraConfig(BaseModel):
    id: str
    name: str
    area_id: int | None = None
    area_name: str | None = None
    site_id: int | None = None
    source_type: SourceType = SourceType.RTSP
    source_url: str
    analysis_fps: float = 5.0
    enabled: bool = True
    zones: list[ZoneCfg] = Field(default_factory=list)
    rules: list[RuleCfg] = Field(default_factory=list)
    version: int = 0


class ConfigUpdated(BaseModel):
    camera_id: str | None = None  # None — перечитать всё
    version: int = 0
    deleted: bool = False


class ScenarioInfo(BaseModel):
    code: str
    title: str
    description: str = ""
    requires: list[str] = Field(default_factory=list)
    severity: Severity = Severity.MEDIUM
    per_track: bool = True
    zone_required: bool = False
    params_schema: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# События для API и WebSocket
# ---------------------------------------------------------------------------


class EventOut(BaseModel):
    id: str
    camera_id: str
    camera_name: str | None = None
    area_id: int | None = None
    zone_id: int | None = None
    zone_name: str | None = None
    rule_id: int | None = None
    scenario: str
    scenario_title: str | None = None
    severity: Severity
    status: EventStatus
    started_at: datetime
    confirmed_at: datetime | None = None
    ended_at: datetime | None = None
    created_at: datetime
    escalated_at: datetime | None = None
    confidence: float | None = None
    track_id: int | None = None
    bbox: BBox | None = None
    snapshot_url: str | None = None
    annotated_url: str | None = None
    snapshot_sha256: str | None = None
    clip_url: str | None = None
    clip_status: Literal["none", "pending", "ready", "failed"] = "none"
    assignee_id: int | None = None
    demo: bool = False
    # для расчёта сквозной задержки в notification-service
    frame_ts: float | None = None


class WsMessage(BaseModel):
    """Сообщение в WebSocket /ws: {"type": "event.created" | "event.updated" | "event.escalated", "event": {...}}."""

    type: Literal["event.created", "event.updated", "event.escalated"]
    event: EventOut


CHANNEL_TO_WS_TYPE = {
    Channels.EVENTS_CREATED: "event.created",
    Channels.EVENTS_UPDATED: "event.updated",
    Channels.EVENTS_ESCALATED: "event.escalated",
}
