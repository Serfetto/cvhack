import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

import fakeredis.aioredis
import pytest

from common.bus import Bus
from common.messages import FrameMsg, RuleCfg, Schedule, shard_for
from common.schedule import is_active

MSK = ZoneInfo("Europe/Moscow")


def at(day: int, hh: int, mm: int = 0) -> datetime:
    # 2026-10-19 — понедельник
    return datetime(2026, 10, 19 + day, hh, mm, tzinfo=MSK)


def test_schedule_window():
    s = Schedule.model_validate({"days": [0, 1, 2, 3, 4], "from": "07:55", "to": "12:00"})
    assert is_active(s, None, at(0, 8))
    assert not is_active(s, None, at(0, 12, 30))
    assert not is_active(s, None, at(5, 9))  # суббота


def test_schedule_overnight_and_valid_until():
    s = Schedule.model_validate({"from": "22:00", "to": "06:00"})
    assert is_active(s, None, at(0, 23)) and is_active(s, None, at(1, 3)) and not is_active(s, None, at(1, 12))
    assert not is_active(None, at(0, 12), at(0, 13))
    assert is_active(None, at(0, 12), at(0, 11))


def test_schedule_alias_roundtrip():
    r = RuleCfg(id=1, scenario="x", schedule={"from": "08:00", "to": "09:00"})
    dumped = r.model_dump(mode="json", by_alias=True)
    assert dumped["schedule"]["from"] == "08:00"
    assert RuleCfg.model_validate(dumped).schedule.from_ == "08:00"


def test_shard_stable():
    assert shard_for("cam-01", 4) == shard_for("cam-01", 4)
    assert shard_for("cam-01", 1) == 0


@pytest.fixture
def bus():
    b = Bus("redis://localhost:6379/0")
    b.redis = fakeredis.aioredis.FakeRedis()
    return b


def test_bus_consume_ack_and_dead_letter(bus):
    async def scenario():
        got, attempts = [], {}

        async def handler(msg: FrameMsg, ctx):
            attempts[msg.seq] = attempts.get(msg.seq, 0) + 1
            if msg.seq == 2:
                raise RuntimeError("boom")
            got.append(msg.seq)

        for i in (1, 2, 3):
            await bus.xadd("frames:0", FrameMsg(camera_id="c", seq=i, ts=0, frame_key="k", w=1, h=1))
        await bus.redis.xadd("frames:0", {"data": b"not json"})
        stop = asyncio.Event()
        task = asyncio.create_task(bus.consume(["frames:0"], "g", "c1", FrameMsg, handler, block_ms=50, max_retries=2, stop=stop))
        for _ in range(100):
            await asyncio.sleep(0.05)
            if await bus.redis.xlen("dlq:frames:0") >= 2:
                break
        stop.set()
        await asyncio.wait_for(task, 2)
        pending = await bus.redis.xpending("frames:0", "g")
        return got, attempts, await bus.redis.xlen("dlq:frames:0"), pending["pending"]

    got, attempts, dlq, pending = asyncio.run(scenario())
    assert got == [1, 3]
    assert attempts[2] == 2
    assert dlq == 2  # битый JSON + сообщение, упавшее max_retries раз
    assert pending == 0


def test_bus_pubsub_roundtrip(bus):
    async def scenario():
        it = bus.listen(channels=["config.updated"])
        task = asyncio.create_task(it.__anext__())
        await asyncio.sleep(0.1)
        await bus.publish("config.updated", {"camera_id": "cam-01"})
        ch, data = await asyncio.wait_for(task, 2)
        await it.aclose()
        return ch, data

    assert asyncio.run(scenario()) == ("config.updated", {"camera_id": "cam-01"})


