"""A likely fall: a nearby upright pose becomes horizontal and moves downward.

The upright memory is per camera rather than per track. A pose model can lose a
person for a few frames during a fall, and the tracker may assign a new id when
the horizontal person reappears. This rule requires both poses and does not
claim to diagnose why the person fell.
"""

from __future__ import annotations

import math
from collections import deque

from scenarios._pose import Posture, is_ground, is_upright, posture_from_detection
from scenarios.base import ScenarioBase, Scene, Severity, register


@register
class FallScenario(ScenarioBase):
    code = "fall"
    title = "Падение человека"
    description = "Вертикальная поза сменилась горизонтальной рядом с прежним положением человека."
    requires = {"pose"}
    severity = Severity.CRITICAL
    per_track = False  # ByteTrack can hide the only horizontal detection while confirming a new track.
    params_schema = {
        "type": "object",
        "properties": {
            "min_score": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.4,
                          "title": "Мин. уверенность детекции"},
            "upright_angle_deg": {"type": "number", "minimum": 0, "maximum": 90, "default": 35,
                                  "title": "Макс. угол вертикальной позы"},
            "fallen_angle_deg": {"type": "number", "minimum": 0, "maximum": 90, "default": 60,
                                 "title": "Мин. угол позы после падения"},
            "upright_aspect_max": {"type": "number", "minimum": 0, "default": 0.8,
                                   "title": "Макс. ширина/высота вертикальной рамки"},
            "fallen_aspect_min": {"type": "number", "minimum": 0, "default": 1.15,
                                  "title": "Мин. ширина/высота горизонтальной рамки"},
            "transition_s": {"type": "number", "minimum": 0, "maximum": 10, "default": 2.0,
                             "title": "Время перехода, с"},
            "min_drop_heights": {"type": "number", "minimum": 0, "default": 0.2,
                                 "title": "Мин. снижение центра, ростов рамки"},
            "max_move_heights": {"type": "number", "minimum": 0, "default": 1.6,
                                 "title": "Макс. перемещение центра, ростов рамки"},
            "hold_s": {"type": "number", "minimum": 0, "maximum": 10, "default": 2.5,
                       "title": "Длительность сигнала после падения, с"},
            "confirm_s": {"default": 0.0},  # переход бывает виден на единственном кадре
            "release_s": {"default": 1.0},
            "cooldown_s": {"default": 30.0},
        },
    }

    def __init__(self) -> None:
        self.upright: dict[tuple[str, int | None], deque[tuple[float, Posture]]] = {}
        self.recent_falls: dict[tuple[str, int | None], deque[tuple[float, Posture]]] = {}
        self.hold_until: dict[tuple[str, int | None], float] = {}

    def check(self, track: None, scene: Scene, params: dict) -> float:
        t = scene.ts
        key = (scene.camera_id, scene.zone.id if scene.zone is not None else None)
        if t < self.hold_until.get(key, 0.0):
            return 1.0
        upright = self.upright.setdefault(key, deque())
        recent_falls = self.recent_falls.setdefault(key, deque())
        transition_s = params.get("transition_s", 2.0)
        while upright and t - upright[0][0] > transition_s:
            upright.popleft()
        while recent_falls and t - recent_falls[0][0] > 5.0:
            recent_falls.popleft()

        for person in scene.persons:
            if person.score < params.get("min_score", 0.4):
                continue
            current = posture_from_detection(person.bbox, person.kpts, scene.w, scene.h)
            if is_upright(current, params):
                upright.append((t, current))
                continue
            if not is_ground(current, params):
                continue
            if scene.zone is not None and not scene.zone.contains((person.bbox[0] + person.bbox[2]) / 2,
                                                                 person.bbox[3]):
                continue
            if any(math.hypot(current.center_x - old.center_x, current.center_y - old.center_y)
                   <= 1.5 * max(current.length_px, old.length_px) for _, old in recent_falls):
                continue
            for seen_t, old in reversed(upright):
                if t - seen_t < 0.2:  # другой стоящий человек на том же кадре — не доказательство падения
                    continue
                drop = current.center_y - old.center_y
                distance = math.hypot(current.center_x - old.center_x, drop)
                if drop >= params.get("min_drop_heights", 0.2) * old.height_px and \
                        distance <= params.get("max_move_heights", 1.6) * old.height_px:
                    recent_falls.append((t, current))
                    scene.evidence_bbox = [float(value) for value in person.bbox]
                    self.hold_until[key] = t + params.get("hold_s", 2.5)
                    return 1.0
        return 0.0
