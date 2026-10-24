"""Опасное сближение человека с техникой (погрузчик, рохля) — ARCHITECTURE §7.2, сценарий 2.

Расстояние считается в кадре от точки опоры человека до рамки техники и сравнивается с ростом
человека: так порог не зависит от того, насколько далеко камера. Водителя внутри погрузчика
не считаем — его рамка почти целиком лежит в рамке техники. С зоной в правиле — только внутри неё.

Детектор техники на камерах сверху срабатывает не на каждом кадре, а погрузчик за секунду
не исчезает: сценарий помнит технику, замеченную за последние `memory_s` секунд.
"""

import math
from collections import deque

from scenarios.base import Obj, ScenarioBase, Scene, Severity, Track, register


def inside_share(inner, outer) -> float:
    """Доля площади рамки `inner` внутри рамки `outer`."""
    w = min(inner[2], outer[2]) - max(inner[0], outer[0])
    h = min(inner[3], outer[3]) - max(inner[1], outer[1])
    area = (inner[2] - inner[0]) * (inner[3] - inner[1])
    return max(w, 0) * max(h, 0) / area if area > 0 else 0.0


@register
class ProximityScenario(ScenarioBase):
    code = "proximity"
    title = "Опасное сближение с техникой"
    description = "Человек ближе заданного числа своих ростов к погрузчику или рохле. Водитель внутри техники не считается."
    requires = {"pose", "objects"}
    severity = Severity.CRITICAL
    params_schema = {
        "type": "object",
        "properties": {
            "classes": {"type": "array", "items": {"type": "string", "enum": ["forklift", "pallet_truck"]},
                        "uniqueItems": True, "default": ["forklift", "pallet_truck"], "title": "Техника"},
            "distance_heights": {"type": "number", "minimum": 0, "maximum": 5, "default": 1.0,
                                 "title": "Опасное расстояние, ростов человека",
                                 "description": "От точки опоры человека до рамки техники; 0 — только касание рамки"},
            "min_score": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.25, "title": "Мин. уверенность детекции техники"},
            "memory_s": {"type": "number", "minimum": 0, "maximum": 5, "default": 1.0,
                         "title": "Помнить технику, с", "description": "Сколько секунд учитывать технику после последней детекции"},
            "driver_overlap": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.6,
                               "title": "Водитель: доля рамки человека внутри техники"},
            "confirm_s": {"default": 1.0},
        },
    }

    def __init__(self) -> None:
        self.seen: dict[str, deque[tuple[float, Obj]]] = {}  # камера → недавние детекции техники
        self.last_seq: dict[str, int] = {}

    def vehicles(self, scene: Scene, params: dict) -> list[Obj]:
        seen = self.seen.setdefault(scene.camera_id, deque())
        if self.last_seq.get(scene.camera_id) != scene.seq:  # check зовётся на каждого человека, кадр учитываем один раз
            self.last_seq[scene.camera_id] = scene.seq
            seen.extend((scene.ts, o) for o in scene.objects_of(*params.get("classes", ["forklift", "pallet_truck"]),
                                                                 min_score=params.get("min_score", 0.25)))
            while seen and scene.ts - seen[0][0] > params.get("memory_s", 1.0):
                seen.popleft()
        return [o for _, o in seen]

    def check(self, track: Track, scene: Scene, params: dict) -> float:
        vehicles = self.vehicles(scene, params)
        if track.score < 0.4:
            return 0.0
        fx, fy = track.foot
        if scene.zone is not None and not scene.zone.contains(fx, fy):
            return 0.0
        limit = params.get("distance_heights", 1.0) * track.height_px
        for obj in vehicles:
            x1, y1, x2, y2 = obj.bbox
            if inside_share(track.bbox, obj.bbox) >= params.get("driver_overlap", 0.6):
                continue
            dx = max(x1 - fx, 0.0, fx - x2) * scene.w
            dy = max(y1 - fy, 0.0, fy - y2) * scene.h
            if math.hypot(dx, dy) <= limit:
                return 1.0
        return 0.0
