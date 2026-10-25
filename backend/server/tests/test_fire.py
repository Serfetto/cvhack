import numpy as np

from common.messages import Obj, Person
from ml_runtime.fire import FireFinder
from scenarios import REGISTRY, effective_params
from scenarios.base import Scene, Zone


def frame(rng, flame: bool = False, vest: bool = False) -> np.ndarray:
    img = np.full((360, 640, 3), 60, np.uint8)
    if flame:  # пламя: оранжево-жёлтый язык, высота и яркость которого скачут от кадра к кадру
        top = 260 - int(rng.integers(25, 61))
        r = int(rng.integers(200, 256))
        g = int(r * rng.uniform(0.35, 0.85))
        img[top:260, 300:350] = (g * 0.3, g, r)
    if vest:  # оранжевый жилет: тот же цвет, но неподвижный
        img[100:160, 100:140] = (20, 120, 240)
    return img


def run(finder: FireFinder, n: int = 6, **kw) -> list[dict]:
    rng = np.random.default_rng(0)
    out = []
    for _ in range(n):
        out = finder.find(frame(rng, **kw), "cam")
    return out


def test_flickering_flame_found():
    found = run(FireFinder(), flame=True)
    assert len(found) == 1
    x1, y1, x2, y2 = found[0]["bbox"]
    assert 0.45 < (x1 + x2) / 2 < 0.52 and 0.6 < (y1 + y2) / 2 < 0.7
    assert found[0]["score"] >= 0.5


def test_static_orange_ignored():
    assert run(FireFinder(), vest=True) == []


def test_first_frame_and_global_change_give_nothing():
    f = FireFinder()
    rng = np.random.default_rng(0)
    assert f.find(frame(rng, flame=True), "cam") == []
    for _ in range(5):
        f.find(frame(rng, flame=True), "cam")
    assert f.find(np.full((360, 640, 3), 220, np.uint8), "cam") == []  # включили свет


def check(objects, persons=(), zone=None, **params) -> tuple[float, list | None]:
    sc = REGISTRY["fire"]
    scene = Scene(camera_id="cam-01", ts=1000.0, seq=1, w=1280, h=720, zones={}, tracks=[], objects=objects,
                  persons=list(persons), zone=zone)
    return sc.check(None, scene, effective_params(sc, params)), scene.evidence_bbox


FIRE = Obj(cls="fire", bbox=[0.4, 0.5, 0.5, 0.6], score=0.8)


def test_fire_scenario_reports_best_area():
    weak = Obj(cls="fire", bbox=[0.1, 0.1, 0.2, 0.2], score=0.6)
    assert check([weak, FIRE]) == (0.8, FIRE.bbox)
    assert check([Obj(cls="fire", bbox=FIRE.bbox, score=0.3)])[0] == 0.0


def test_fire_scenario_ignores_people_and_outside_zone():
    person = Person(bbox=[0.38, 0.3, 0.55, 0.9], score=0.9)
    assert check([FIRE], persons=[person])[0] == 0.0
    assert check([FIRE], persons=[person], ignore_people=False)[0] == 0.8
    zone = Zone(id=1, name="z", kind="danger", coords=[[0, 0], [0.3, 0], [0.3, 0.3], [0, 0.3]])
    assert check([FIRE], zone=zone)[0] == 0.0
