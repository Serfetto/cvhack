"""Огонь в кадре — эвристика без обучения: объекты `fire` от FireFinder (inference, цвет пламени
+ мерцание). Сценарий про кадр целиком: одно событие на камеру, рамка — самая уверенная область.

Область, центр которой внутри рамки человека, по умолчанию не считается: так отсекаются
оранжевые жилеты в движении. С зоной в правиле — только огонь с центром внутри неё.
"""

from scenarios.base import ScenarioBase, Scene, Severity, register


@register
class FireScenario(ScenarioBase):
    code = "fire"
    title = "Огонь"
    description = "Мерцающая область цвета пламени дольше окна подтверждения. Без нейросети: цвет + мерцание."
    requires = set()
    severity = Severity.CRITICAL
    per_track = False
    params_schema = {
        "type": "object",
        "properties": {
            "min_score": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.5,
                          "title": "Мин. уверенность области огня"},
            "min_area": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.0005,
                         "title": "Мин. площадь области, доля кадра"},
            "ignore_people": {"type": "boolean", "default": True,
                              "title": "Не считать области на людях (жилеты)"},
            "confirm_s": {"default": 2.0},
            "confirm_ratio": {"default": 0.6},
            "cooldown_s": {"default": 120.0},
        },
    }

    def check(self, track, scene: Scene, params: dict) -> float:
        best, bbox = 0.0, None
        for obj in scene.objects_of("fire", min_score=params.get("min_score", 0.5)):
            x1, y1, x2, y2 = obj.bbox
            if (x2 - x1) * (y2 - y1) < params.get("min_area", 0.0005):
                continue
            cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
            if scene.zone is not None and not scene.zone.contains(cx, cy):
                continue
            if params.get("ignore_people", True) and any(
                    p.bbox[0] <= cx <= p.bbox[2] and p.bbox[1] <= cy <= p.bbox[3] for p in scene.persons):
                continue
            if obj.score > best:
                best, bbox = obj.score, [float(v) for v in obj.bbox]
        scene.evidence_bbox = bbox
        return best
