import numpy as np

from common.messages import Obj
from scenarios import REGISTRY, effective_params
from scenarios.base import KPT, Observation, Scene, Track


def track(bbox, kpts: dict[str, tuple[float, float]] | None = None) -> Track:
    k = None
    if kpts is not None:
        k = np.zeros((17, 3), dtype=np.float32)
        for name, (x, y) in kpts.items():
            k[KPT[name]] = (x, y, 0.9)
    tr = Track(id=1, camera_id="cam-01", w=1280, h=720)
    tr.add(Observation(ts=1000.0, bbox=np.asarray(bbox, dtype=np.float32), score=0.9, kpts=k))
    return tr


def check(code: str, tr: Track, objects: list[Obj], ts: float = 1000.0, seq: int = 1, fresh: bool = True, **params) -> float:
    sc = REGISTRY[code]
    if fresh and hasattr(sc, "seen"):
        sc.seen.clear()
        sc.last_seq.clear()
    scene = Scene(camera_id="cam-01", ts=ts, seq=seq, w=1280, h=720, zones={}, tracks=[tr], objects=objects)
    return sc.check(tr, scene, effective_params(sc, params))


FORKLIFT = Obj(cls="forklift", bbox=[0.5, 0.3, 0.7, 0.8], score=0.8)


def test_proximity_near_forklift():
    assert check("proximity", track([0.42, 0.3, 0.48, 0.8]), [FORKLIFT]) == 1.0


def test_proximity_far_from_forklift():
    assert check("proximity", track([0.05, 0.3, 0.11, 0.8]), [FORKLIFT]) == 0.0


def test_proximity_ignores_driver_and_weak_detection():
    assert check("proximity", track([0.55, 0.35, 0.62, 0.7]), [FORKLIFT]) == 0.0
    weak = Obj(cls="forklift", bbox=FORKLIFT.bbox, score=0.2)
    assert check("proximity", track([0.42, 0.3, 0.48, 0.8]), [weak]) == 0.0


def test_proximity_remembers_vehicle_for_memory_s():
    near = track([0.42, 0.3, 0.48, 0.8])
    assert check("proximity", near, [FORKLIFT], ts=1000.0, seq=1) == 1.0
    assert check("proximity", near, [], ts=1000.5, seq=2, fresh=False) == 1.0  # детектор пропустил кадр
    assert check("proximity", near, [], ts=1002.0, seq=3, fresh=False) == 0.0


def test_phone_in_hand():
    tr = track([0.4, 0.2, 0.5, 0.9], {"l_wrist": (0.42, 0.5), "nose": (0.45, 0.25)})
    phone = Obj(cls="phone", bbox=[0.415, 0.49, 0.43, 0.52], score=0.6)
    assert check("phone", tr, [phone]) == 1.0


def test_phone_away_from_hands_and_head():
    tr = track([0.4, 0.2, 0.5, 0.9], {"l_wrist": (0.42, 0.5), "nose": (0.45, 0.25)})
    phone = Obj(cls="phone", bbox=[0.8, 0.8, 0.82, 0.83], score=0.6)
    assert check("phone", tr, [phone]) == 0.0


def test_phone_without_pose_uses_upper_body():
    phone = Obj(cls="phone", bbox=[0.44, 0.3, 0.46, 0.33], score=0.6)
    assert check("phone", track([0.4, 0.2, 0.5, 0.9]), [phone]) == 1.0
