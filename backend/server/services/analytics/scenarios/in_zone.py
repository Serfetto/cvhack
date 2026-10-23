"""Эталонный сценарий каркаса: человек находится в полигоне дольше окна подтверждения.

Работает без специальных моделей (нужен только детектор людей), поэтому на нём проверяется весь
конвейер до готовности сценариев ML. Подходит и как самостоятельное правило: запретная зона,
зона работы пресса, проход под конвейером.
"""

from scenarios.base import ScenarioBase, Scene, Severity, Track, register


@register
class InZoneScenario(ScenarioBase):
    code = "in_zone"
    title = "Человек в опасной зоне"
    description = "Человек находится внутри полигона зоны дольше окна подтверждения. Без зоны — человек в любом месте кадра."
    requires = {"pose"}
    severity = Severity.HIGH
    params_schema = {
        "type": "object",
        "properties": {
            "point": {"type": "string", "enum": ["foot", "center"], "default": "foot",
                      "title": "Какая точка человека должна быть в зоне", "description": "foot — точка опоры, center — центр рамки"},
            "min_score": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.4, "title": "Мин. уверенность детекции"},
            "confirm_s": {"default": 2.0},
        },
    }

    def check(self, track: Track, scene: Scene, params: dict) -> float:
        if track.score < params.get("min_score", 0.4):
            return 0.0
        if scene.zone is None:
            return 1.0
        x, y = track.foot if params.get("point", "foot") == "foot" else track.center
        return 1.0 if scene.zone.contains(x, y) else 0.0
