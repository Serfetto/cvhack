"""Расписание действия правил: дни недели, интервал времени, срок действия."""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

from common.messages import Schedule


def _parse(hhmm: str) -> time:
    h, m = hhmm.split(":")
    return time(int(h), int(m))


def is_active(schedule: Schedule | None, valid_until: datetime | None, now: datetime, tz: str = "Europe/Moscow") -> bool:
    """now — время с часовым поясом (обычно UTC). Интервал from–to по местному времени tz."""
    if valid_until is not None:
        vu = valid_until if valid_until.tzinfo else valid_until.replace(tzinfo=ZoneInfo(tz))
        if now >= vu:
            return False
    if schedule is None:
        return True
    local = now.astimezone(ZoneInfo(tz))
    if schedule.days and local.weekday() not in schedule.days:
        # интервал через полночь: в 01:00 вторника действует правило понедельника 22:00–06:00
        if not (schedule.from_ and schedule.to and _parse(schedule.from_) > _parse(schedule.to)
                and (local.weekday() - 1) % 7 in schedule.days and local.time() < _parse(schedule.to)):
            return False
    if not schedule.from_ and not schedule.to:
        return True
    start = _parse(schedule.from_) if schedule.from_ else time(0, 0)
    end = _parse(schedule.to) if schedule.to else time(23, 59, 59)
    t = local.time()
    if start <= end:
        return start <= t < end
    return t >= start or t < end
