"""A person remains horizontal and nearly motionless for several seconds."""

from __future__ import annotations

import math

from scenarios._pose import is_ground, posture
from scenarios.base import ScenarioBase, Scene, Severity, Track, register


@register
class ImmobileScenario(ScenarioBase):
    code = "immobile"
    title = "Человек лежит без движения"
    description = "Человек остаётся в горизонтальной позе почти без движения несколько секунд."
    requires = {"pose"}
    severity = Severity.CRITICAL
    params_schema = {
        "type": "object",
        "properties": {
            "min_score": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.4,
                          "title": "Мин. уверенность детекции"},
            "fallen_angle_deg": {"type": "number", "minimum": 0, "maximum": 90, "default": 60,
                                 "title": "Мин. угол горизонтальной позы"},
            "fallen_aspect_min": {"type": "number", "minimum": 0, "default": 1.15,
                                  "title": "Мин. ширина/высота рамки"},
            "still_s": {"type": "number", "minimum": 1, "maximum": 9, "default": 4.0,
                        "title": "Время без движения, с"},
            "max_motion": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.15,
                           "title": "Допустимое движение, долей длины рамки"},
            "max_gap_s": {"type": "number", "minimum": 0.2, "maximum": 5, "default": 1.5,
                          "title": "Макс. пропуск между детекциями, с"},
            "confirm_s": {"default": 0.0},  # still_s уже проверяет полное окно времени
            "cooldown_s": {"default": 30.0},
        },
    }

    def check(self, track: Track, scene: Scene, params: dict) -> float:
        if track.score < params.get("min_score", 0.4):
            return 0.0
        still_s = params.get("still_s", 4.0)
        history = track.window(still_s)
        if len(history) < 3 or history[-1].ts - history[0].ts < still_s - 1e-6:
            return 0.0
        if any(b.ts - a.ts > params.get("max_gap_s", 1.5) for a, b in zip(history, history[1:])):
            return 0.0
        shapes = [posture(track, obs) for obs in history]
        if not all(is_ground(shape, params) for shape in shapes):
            return 0.0
        anchor = shapes[0]
        limit = params.get("max_motion", 0.15) * anchor.length_px
        return 1.0 if all(math.hypot(shape.center_x - anchor.center_x, shape.center_y - anchor.center_y) <= limit
                          for shape in shapes[1:]) else 0.0
