"""Контракт сценария нарушения (ARCHITECTURE §7.3) и типы, которые видит сценарий.

Новый тип нарушения = новый файл в этом пакете:

    from scenarios.base import ScenarioBase, Scene, Severity, Track, register

    @register
    class FallScenario(ScenarioBase):
        code = "fall"
        title = "Падение человека"
        requires = {"pose"}
        severity = Severity.CRITICAL
        params_schema = {"type": "object", "properties": {
            "torso_angle_deg": {"type": "number", "default": 60, "title": "Угол торса, °"},
            "confirm_s": {"type": "number", "default": 1.0, "title": "Окно подтверждения, с"},
        }}

        def check(self, track: Track, scene: Scene, params: dict) -> float:
            ...  # 0..1 — «нарушение есть на этом кадре»

`check` вызывается на каждом кадре для каждого видимого человека. Подтверждение во времени,
подавление повторов и склейку треков делает конечный автомат (engine/fsm.py) — в сценарии этого не нужно.
Общие параметры автомата (threshold, confirm_s, confirm_ratio, release_s, cooldown_s) можно
переопределить значениями по умолчанию в params_schema сценария и в правиле камеры.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Any, ClassVar, Protocol, runtime_checkable

import numpy as np
from shapely.geometry import Point, Polygon
from shapely.prepared import prep

from common.messages import Obj, ScenarioInfo, Severity

__all__ = [
    "KPT", "Observation", "Track", "Zone", "Scene", "Scenario", "ScenarioBase", "Severity", "Obj",
    "REGISTRY", "register", "COMMON_PARAMS_SCHEMA", "effective_params", "catalog",
]

# Индексы ключевых точек COCO-17
KPT = {
    "nose": 0, "l_eye": 1, "r_eye": 2, "l_ear": 3, "r_ear": 4,
    "l_shoulder": 5, "r_shoulder": 6, "l_elbow": 7, "r_elbow": 8, "l_wrist": 9, "r_wrist": 10,
    "l_hip": 11, "r_hip": 12, "l_knee": 13, "r_knee": 14, "l_ankle": 15, "r_ankle": 16,
}


@dataclass(slots=True)
class Observation:
    ts: float
    bbox: np.ndarray            # [x1, y1, x2, y2], 0..1
    score: float
    kpts: np.ndarray | None     # (17, 3): x, y, conf; x и y — 0..1


@dataclass
class Track:
    """Человек, которого трекер ведёт между кадрами. История — последние `history_s` секунд."""

    id: int
    camera_id: str
    w: int                      # размер кадра в пикселях: нужен, чтобы считать расстояния без искажения пропорций
    h: int
    history: deque[Observation] = field(default_factory=deque)
    history_s: float = 10.0

    def add(self, obs: Observation) -> None:
        self.history.append(obs)
        while self.history and obs.ts - self.history[0].ts > self.history_s:
            self.history.popleft()

    @property
    def last(self) -> Observation:
        return self.history[-1]

    @property
    def ts(self) -> float:
        return self.last.ts

    @property
    def first_ts(self) -> float:
        return self.history[0].ts

    @property
    def bbox(self) -> np.ndarray:
        return self.last.bbox

    @property
    def score(self) -> float:
        return self.last.score

    @property
    def kpts(self) -> np.ndarray | None:
        return self.last.kpts

    @property
    def center(self) -> tuple[float, float]:
        x1, y1, x2, y2 = self.bbox
        return float((x1 + x2) / 2), float((y1 + y2) / 2)

    @property
    def foot(self) -> tuple[float, float]:
        """Точка опоры: середина нижней стороны рамки (или середина лодыжек, если они видны)."""
        la, ra = self.kpt("l_ankle"), self.kpt("r_ankle")
        if la is not None and ra is not None:
            return float((la[0] + ra[0]) / 2), float((la[1] + ra[1]) / 2)
        x1, _, x2, y2 = self.bbox
        return float((x1 + x2) / 2), float(y2)

    @property
    def height(self) -> float:
        """Высота рамки в долях кадра."""
        return float(self.bbox[3] - self.bbox[1])

    @property
    def height_px(self) -> float:
        return self.height * self.h

    @property
    def width_px(self) -> float:
        return float(self.bbox[2] - self.bbox[0]) * self.w

    def kpt(self, name: str, min_conf: float = 0.3, obs: Observation | None = None) -> tuple[float, float] | None:
        k = (obs or self.last).kpts
        if k is None:
            return None
        x, y, c = k[KPT[name]]
        return (float(x), float(y)) if c >= min_conf else None

    def window(self, seconds: float) -> list[Observation]:
        t0 = self.ts - seconds
        return [o for o in self.history if o.ts >= t0]

    def at(self, seconds_ago: float) -> Observation:
        """Наблюдение примерно `seconds_ago` секунд назад (самое старое, если истории не хватает)."""
        t = self.ts - seconds_ago
        for o in self.history:
            if o.ts >= t:
                return o
        return self.history[-1]

    def speed_heights(self, seconds: float = 1.0) -> float:
        """Скорость точки опоры в ростах человека в секунду за последние `seconds` секунд."""
        old = self.at(seconds)
        dt = self.ts - old.ts
        if dt <= 1e-6 or self.height_px <= 1:
            return 0.0
        ox, oy = (old.bbox[0] + old.bbox[2]) / 2 * self.w, old.bbox[3] * self.h
        nx, ny = (self.bbox[0] + self.bbox[2]) / 2 * self.w, self.bbox[3] * self.h
        return math.hypot(nx - ox, ny - oy) / self.height_px / dt


@dataclass
class Zone:
    id: int
    name: str
    kind: str
    coords: list[list[float]]
    polygon: Polygon = field(init=False)

    def __post_init__(self) -> None:
        self.polygon = Polygon(self.coords)
        if not self.polygon.is_valid:
            self.polygon = self.polygon.buffer(0)
        self._prepared = prep(self.polygon)

    def contains(self, x: float, y: float) -> bool:
        return self._prepared.contains(Point(x, y))

    def bbox_overlap(self, bbox) -> float:
        """Доля площади рамки внутри зоны."""
        x1, y1, x2, y2 = (float(v) for v in bbox)
        box = Polygon([(x1, y1), (x2, y1), (x2, y2), (x1, y2)])
        return box.intersection(self.polygon).area / box.area if box.area > 0 else 0.0


@dataclass
class Scene:
    """Всё, что известно о кадре. Для правила с зоной в `zone` лежит её полигон."""

    camera_id: str
    ts: float
    seq: int
    w: int
    h: int
    zones: dict[int, Zone]
    tracks: list[Track]
    objects: list[Obj]
    zone: Zone | None = None

    def objects_of(self, *classes: str, min_score: float = 0.0) -> list[Obj]:
        return [o for o in self.objects if o.cls in classes and o.score >= min_score]

    def zones_of_kind(self, kind: str) -> list[Zone]:
        return [z for z in self.zones.values() if z.kind == kind]

    def to_px(self, x: float, y: float) -> tuple[float, float]:
        return x * self.w, y * self.h

    def dist_px(self, a: tuple[float, float], b: tuple[float, float]) -> float:
        return math.hypot((a[0] - b[0]) * self.w, (a[1] - b[1]) * self.h)


@runtime_checkable
class Scenario(Protocol):
    code: str
    title: str
    requires: set[str]
    params_schema: dict
    severity: Severity

    def check(self, track: Track, scene: Scene, params: dict) -> float: ...


class ScenarioBase:
    """Удобная база: значения по умолчанию для необязательных полей."""

    code: ClassVar[str]
    title: ClassVar[str]
    description: ClassVar[str] = ""
    requires: ClassVar[set[str]] = {"pose"}
    severity: ClassVar[Severity] = Severity.MEDIUM
    # False — сценарий про кадр целиком (огонь, дым): check(None, scene, params) раз на кадр
    per_track: ClassVar[bool] = True
    zone_required: ClassVar[bool] = False
    params_schema: ClassVar[dict] = {"type": "object", "properties": {}}

    def check(self, track: Track | None, scene: Scene, params: dict) -> float:
        raise NotImplementedError


REGISTRY: dict[str, Any] = {}


def register(cls):
    """Декоратор: регистрирует сценарий в реестре по его коду."""
    REGISTRY[cls.code] = cls()
    return cls


# Параметры конечного автомата — есть у каждого сценария
COMMON_PARAMS_SCHEMA: dict[str, dict] = {
    "threshold": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.5, "title": "Порог срабатывания на кадре"},
    "confirm_s": {"type": "number", "minimum": 0, "maximum": 60, "default": 2.0, "title": "Окно подтверждения, с"},
    "confirm_ratio": {"type": "number", "minimum": 0.1, "maximum": 1, "default": 0.7, "title": "Доля кадров «да» в окне"},
    "release_s": {"type": "number", "minimum": 0, "maximum": 120, "default": 3.0, "title": "Нарушение закончилось, если его нет, с"},
    "cooldown_s": {"type": "number", "minimum": 0, "maximum": 3600, "default": 30.0, "title": "Пауза перед повторным событием, с"},
}


def _schema_of(sc) -> dict:
    schema = dict(getattr(sc, "params_schema", None) or {"type": "object", "properties": {}})
    props = {**COMMON_PARAMS_SCHEMA}
    for k, v in (schema.get("properties") or {}).items():
        props[k] = {**props.get(k, {}), **v}
    schema["type"] = "object"
    schema["properties"] = props
    return schema


def _defaults(schema: dict) -> dict:
    return {k: v["default"] for k, v in (schema.get("properties") or {}).items() if isinstance(v, dict) and "default" in v}


def effective_params(sc, rule_params: dict | None) -> dict:
    """Общие значения по умолчанию ← значения сценария ← параметры правила."""
    return {**_defaults(_schema_of(sc)), **(rule_params or {})}


def catalog() -> list[ScenarioInfo]:
    out = []
    for code, sc in sorted(REGISTRY.items()):
        out.append(ScenarioInfo(
            code=code,
            title=getattr(sc, "title", code),
            description=getattr(sc, "description", ""),
            requires=sorted(getattr(sc, "requires", set())),
            severity=getattr(sc, "severity", Severity.MEDIUM),
            per_track=getattr(sc, "per_track", True),
            zone_required=getattr(sc, "zone_required", False),
            params_schema=_schema_of(sc),
        ))
    return out
