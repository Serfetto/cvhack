from common.messages import CameraConfig, DetectionsMsg, Person, RuleCfg, ZoneCfg
from engine import Engine

FPS = 5
ZONE = [[0.0, 0.0], [0.4, 0.0], [0.4, 1.0], [0.0, 1.0]]


def cfg(**rule_params) -> CameraConfig:
    return CameraConfig(
        id="cam-01", name="Камера 1", area_id=1, source_url="x", analysis_fps=FPS,
        zones=[ZoneCfg(id=1, name="Опасная", polygon=ZONE)],
        rules=[RuleCfg(id=1, scenario="in_zone", zone_id=1, params={"confirm_s": 2.0, "release_s": 2.0, "cooldown_s": 10, **rule_params})],
    )


def person(x: float) -> Person:
    return Person(bbox=[x - 0.05, 0.3, x + 0.05, 0.8], score=0.9)


def feed(engine: Engine, xs: list[float | None], t0: float = 1000.0, seq0: int = 0):
    out = []
    for i, x in enumerate(xs):
        persons = [] if x is None else [person(x)]
        det = DetectionsMsg(camera_id="cam-01", seq=seq0 + i + 1, ts=t0 + i / FPS, frame_key=f"f{i}", w=1280, h=720, persons=persons)
        out += engine.process(det)
    return out


def make(tracker: str = "iou") -> Engine:
    e = Engine(tracker_kind=tracker)
    e.set_config(cfg())
    return e


def test_person_in_zone_one_event():
    e = make()
    path = [0.8 - 0.02 * i for i in range(30)] + [0.2] * 40 + [0.2 + 0.03 * i for i in range(30)]
    tr = feed(e, path)
    assert [t.kind for t in tr] == ["started", "ended"]
    s = tr[0]
    assert s.scenario == "in_zone" and s.zone.name == "Опасная" and s.camera.area_id == 1
    assert s.confirmed_at - s.started_at >= 2.0
    assert s.event_id == tr[1].event_id
    v = s.to_violation()
    assert v.kind == "started" and v.camera_name == "Камера 1" and v.bbox is not None


def test_person_outside_zone_no_event():
    assert feed(make(), [0.8] * 60) == []


def test_occlusion_and_new_track_id_glued():
    e = make()
    # в зоне 4 с → пропал на 1 с (трекер забудет его) → вернулся рядом с новым id
    xs = [0.2] * 20 + [None] * 5 + [0.21] * 20
    e.cameras["cam-01"].tracker.lost_s = 0.5
    tr = feed(e, xs)
    assert [t.kind for t in tr] == ["started"], tr


def test_two_people_two_events():
    e = make()
    out = []
    for i in range(40):
        det = DetectionsMsg(camera_id="cam-01", seq=i + 1, ts=1000 + i / FPS, frame_key="f", w=1280, h=720,
                            persons=[person(0.1), person(0.3)])
        out += e.process(det)
    assert sorted(t.kind for t in out) == ["started", "started"]
    assert len({t.track_id for t in out}) == 2


def test_rule_removed_while_active_closes_event():
    e = make()
    tr = feed(e, [0.2] * 20)
    assert [t.kind for t in tr] == ["started"]
    ended = e.set_config(cfg().model_copy(update={"rules": []}))
    assert [t.kind for t in ended] == ["ended"] and ended[0].event_id == tr[0].event_id


def test_out_of_order_frames_ignored():
    e = make()
    feed(e, [0.2] * 5)
    assert feed(e, [0.2] * 5, seq0=0) == []


def test_bytetrack_tracker_works():
    e = make("bytetrack")
    tr = feed(e, [0.2] * 40 + [0.8] * 30)
    assert [t.kind for t in tr] == ["started", "ended"]


def test_yaml_and_catalog():
    from pathlib import Path

    from common.camconfig import load_yaml
    from scenarios import catalog

    sites, cams = load_yaml(Path(__file__).resolve().parents[1] / "infra/cameras.yml")
    assert sites and "cam-01" in cams and cams["cam-01"].rules[0].scenario == "in_zone"
    info = {s.code: s for s in catalog()}["in_zone"]
    props = info.params_schema["properties"]
    assert props["confirm_s"]["default"] == 2.0 and "cooldown_s" in props and "point" in props


def test_restart_restores_active_violation_without_duplicate():
    e = make()
    tr = feed(e, [0.2] * 20)
    assert [t.kind for t in tr] == ["started"]
    state = e.snapshot()
    e2 = make()  # «рестарт»: новый движок, тот же человек в зоне
    assert e2.restore(state, now=1000 + 20 / FPS) == 1
    tr2 = feed(e2, [0.2] * 30, t0=1000 + 21 / FPS, seq0=100)
    assert tr2 == []  # новый трек унаследовал событие


def test_restart_closes_violation_if_person_gone():
    e = make()
    started = feed(e, [0.2] * 20)[0]
    e2 = make()
    e2.restore(e.snapshot(), now=1004.0)
    tr = feed(e2, [0.8] * 40, t0=1005.0, seq0=100)
    assert [(t.kind, t.event_id) for t in tr] == [("ended", started.event_id)]
