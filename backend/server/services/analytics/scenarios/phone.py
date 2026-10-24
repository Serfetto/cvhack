"""Телефон в руке или у уха — ARCHITECTURE §7.2, сценарий 3.

Телефон привязывается к человеку по ключевым точкам: центр рамки телефона рядом с кистью или головой
(в долях роста человека). Если поза не видна, достаточно, чтобы телефон был в верхних 2/3 рамки
человека. С зоной в правиле — только внутри неё (зона оборудования).
"""

from scenarios.base import ScenarioBase, Scene, Severity, Track, register

POINTS = ("l_wrist", "r_wrist", "nose", "l_ear", "r_ear")


@register
class PhoneScenario(ScenarioBase):
    code = "phone"
    title = "Телефон в руке"
    description = "Телефон у кисти или у головы человека дольше окна подтверждения."
    requires = {"pose", "objects"}
    severity = Severity.MEDIUM
    params_schema = {
        "type": "object",
        "properties": {
            "near_heights": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.15,
                             "title": "Телефон у кисти или головы, долей роста"},
            "min_score": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.3, "title": "Мин. уверенность детекции телефона"},
            "confirm_s": {"default": 3.0},
        },
    }

    def check(self, track: Track, scene: Scene, params: dict) -> float:
        if track.score < 0.4:
            return 0.0
        if scene.zone is not None and not scene.zone.contains(*track.foot):
            return 0.0
        points = [p for p in (track.kpt(name) for name in POINTS) if p is not None]
        limit = params.get("near_heights", 0.15) * track.height_px
        x1, y1, x2, y2 = track.bbox
        for obj in scene.objects_of("phone", min_score=params.get("min_score", 0.3)):
            c = ((obj.bbox[0] + obj.bbox[2]) / 2, (obj.bbox[1] + obj.bbox[3]) / 2)
            if points:
                if min(scene.dist_px(c, p) for p in points) <= limit:
                    return 1.0
            elif x1 <= c[0] <= x2 and y1 <= c[1] <= y1 + (y2 - y1) * 2 / 3:
                return 1.0
        return 0.0
