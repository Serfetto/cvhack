from engine.fsm import FsmParams, RuleFsm, State

P = FsmParams(threshold=0.5, confirm_s=2.0, confirm_ratio=0.7, release_s=3.0, cooldown_s=10.0, merge_s=5.0)
FPS = 5


def run(fsm: RuleFsm, scores: list[float], t0: float = 0.0, p: FsmParams = P) -> list[tuple[float, str]]:
    out = []
    for i, s in enumerate(scores):
        ts = t0 + i / FPS
        r = fsm.step(ts, s, p, bbox=[0, 0, 1, 1], center=(0.5, 0.5))
        if r:
            out.append((ts, r))
    return out


def test_short_blip_does_not_fire():
    fsm = RuleFsm("cam", 1, 1)
    assert run(fsm, [1.0] * 5 + [0.0] * 20) == []  # 1 с нарушения при окне 2 с
    assert fsm.state == State.IDLE


def test_confirm_then_single_event_then_end():
    fsm = RuleFsm("cam", 1, 1)
    res = run(fsm, [1.0] * 50 + [0.0] * 30)
    kinds = [k for _, k in res]
    assert kinds == ["started", "ended"]
    started_ts = res[0][0]
    assert 2.0 <= started_ts <= 2.4
    assert fsm.started_at == 0.0
    assert fsm.state == State.COOLDOWN


def test_flicker_below_ratio_never_confirms():
    fsm = RuleFsm("cam", 1, 1)
    assert run(fsm, [1.0, 0.0] * 50) == []  # 50% «да» < 70%


def test_noise_inside_active_does_not_end_or_duplicate():
    fsm = RuleFsm("cam", 1, 1)
    scores = [1.0] * 15 + ([1.0] * 4 + [0.0] * 3) * 10  # пропуски по 0,6 с < release_s
    assert [k for _, k in run(fsm, scores)] == ["started"]


def test_cooldown_suppresses_repeat():
    fsm = RuleFsm("cam", 1, 1)
    # нарушение 4 с → пауза 4 с (ended через 3 с) → снова 4 с внутри cooldown 10 с
    scores = [1.0] * 20 + [0.0] * 20 + [1.0] * 20 + [0.0] * 20
    assert [k for _, k in run(fsm, scores)] == ["started", "ended"]


def test_new_event_after_cooldown():
    fsm = RuleFsm("cam", 1, 1)
    scores = [1.0] * 20 + [0.0] * 75 + [1.0] * 20
    assert [k for _, k in run(fsm, scores)] == ["started", "ended", "started"]


def test_lost_track_ends_after_merge_window():
    fsm = RuleFsm("cam", 1, 1)
    run(fsm, [1.0] * 15)
    assert fsm.state == State.ACTIVE
    assert fsm.tick(2.8 + 4.0, P) is None   # пропал на 4 с < merge_s
    assert fsm.tick(2.8 + 5.5, P) == "ended"


def test_zero_confirm_fires_immediately():
    fsm = RuleFsm("cam", 1, 1)
    p = FsmParams(confirm_s=0)
    assert run(fsm, [1.0], p=p) == [(0.0, "started")]
