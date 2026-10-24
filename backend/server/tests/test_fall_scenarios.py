import numpy as np

from common.messages import CameraConfig, DetectionsMsg, Person, RuleCfg
from engine import Engine
from scenarios.base import KPT, Observation, Scene, Track, effective_params
from scenarios.fall import FallScenario
from scenarios.immobile import ImmobileScenario


def pose(horizontal: bool, bbox: list[float], score: float = 0.9) -> Person:
    points = np.zeros((17, 3), dtype=np.float32)
    if horizontal:
        positions = {"l_shoulder": (0.39, 0.55), "r_shoulder": (0.40, 0.56),
                     "l_hip": (0.55, 0.56), "r_hip": (0.56, 0.57)}
    else:
        positions = {"l_shoulder": (0.44, 0.23), "r_shoulder": (0.46, 0.23),
                     "l_hip": (0.44, 0.43), "r_hip": (0.46, 0.43)}
    for name, (x, y) in positions.items():
        points[KPT[name]] = (x, y, 0.9)
    return Person(bbox=bbox, score=score, kpts=points.tolist())


STANDING = pose(False, [0.4, 0.1, 0.5, 0.7])
FALLEN = pose(True, [0.35, 0.5, 0.65, 0.65])


def track(person: Person, t: float = 1000.0) -> Track:
    tr = Track(id=1, camera_id="cam-01", w=1280, h=720)
    tr.add(Observation(t, np.asarray(person.bbox), person.score, np.asarray(person.kpts)))
    return tr


def scene(tr: Track, t: float) -> Scene:
    return Scene(camera_id=tr.camera_id, ts=t, seq=1, w=tr.w, h=tr.h, zones={}, tracks=[tr], objects=[])


def fall_scene(person: Person, t: float) -> Scene:
    return Scene(camera_id="cam-01", ts=t, seq=1, w=1280, h=720,
                 zones={}, tracks=[], objects=[], persons=[person])


def test_fall_bridges_lost_track_and_rejects_repeated_detection():
    scenario = FallScenario()
    params = effective_params(scenario, None)
    assert scenario.check(None, fall_scene(STANDING, 1000.0), params) == 0.0
    # ByteTrack can hide a one-frame horizontal person; the raw pose remains available.
    assert scenario.check(None, fall_scene(FALLEN, 1001.0), params) == 1.0
    assert scenario.check(None, fall_scene(FALLEN, 1001.2), params) == 1.0  # hold one incident briefly
    assert scenario.check(None, fall_scene(FALLEN, 1004.0), params) == 0.0  # no duplicate fall


def test_fall_requires_upright_transition_and_downward_motion():
    params = effective_params(FallScenario(), None)
    assert FallScenario().check(None, fall_scene(FALLEN, 1001.0), params) == 0.0
    scenario = FallScenario()
    scenario.check(None, fall_scene(STANDING, 1000.0), params)
    same_level = pose(True, [0.35, 0.2, 0.65, 0.35])
    assert scenario.check(None, fall_scene(same_level, 1001.0), params) == 0.0


def test_immobile_requires_a_visible_horizontal_pose_for_full_window():
    scenario = ImmobileScenario()
    params = effective_params(scenario, None)
    lying = track(FALLEN)
    assert scenario.check(lying, scene(lying, 1000.0), params) == 0.0
    for i in range(1, 5):
        lying.add(Observation(1000.0 + i, np.asarray(FALLEN.bbox), FALLEN.score, np.asarray(FALLEN.kpts)))
    assert scenario.check(lying, scene(lying, 1004.0), params) == 1.0
    upright = track(STANDING)
    for i in range(1, 5):
        upright.add(Observation(1000.0 + i, np.asarray(STANDING.bbox), STANDING.score, np.asarray(STANDING.kpts)))
    assert scenario.check(upright, scene(upright, 1004.0), params) == 0.0


def test_fall_produces_regular_engine_violation_after_detection_gap():
    from scenarios import REGISTRY

    scenario = REGISTRY["fall"]
    scenario.upright.clear()
    scenario.recent_falls.clear()
    scenario.hold_until.clear()
    engine = Engine("iou")
    engine.set_config(CameraConfig(id="cam-01", name="Камера 1", source_url="x", analysis_fps=5,
                                   rules=[RuleCfg(id=101, scenario="fall")]))
    events = []
    for i, (t, people) in enumerate(((1000.0, [STANDING]), (1000.2, [STANDING]),
                                     (1000.4, []), (1000.6, []), (1001.0, [FALLEN]))):
        events += engine.process(DetectionsMsg(camera_id="cam-01", seq=i + 1, ts=t, frame_key=f"f{i}",
                                               w=1280, h=720, persons=people))
    started = [event for event in events if event.kind == "started"]
    assert len(started) == 1
    assert started[0].scenario == "fall" and started[0].severity == "critical"
    assert started[0].track_id is None  # fall uses raw pose detections before ByteTrack
    assert started[0].bbox == FALLEN.bbox


def test_immobile_produces_event_only_after_stillness_window():
    engine = Engine("iou")
    engine.set_config(CameraConfig(id="cam-01", name="Камера 1", source_url="x", analysis_fps=5,
                                   rules=[RuleCfg(id=102, scenario="immobile")]))
    events = []
    for i in range(26):
        t = 1000.0 + i / 5
        events += engine.process(DetectionsMsg(camera_id="cam-01", seq=i + 1, ts=t, frame_key=f"f{i}",
                                               w=1280, h=720, persons=[FALLEN]))
    started = [event for event in events if event.kind == "started"]
    assert len(started) == 1
    assert started[0].confirmed_at >= 1004.0
    assert started[0].scenario == "immobile" and started[0].track_id is not None


def test_new_rules_are_in_camera_seed_and_catalog():
    from pathlib import Path

    from common.camconfig import load_yaml
    from scenarios import catalog

    _, cameras = load_yaml(Path(__file__).resolve().parents[1] / "infra/cameras.yml")
    assert {rule.scenario for rule in cameras["cam-03"].rules} >= {"fall", "immobile"}
    assert {item.code for item in catalog()} >= {"fall", "immobile"}
