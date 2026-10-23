"""Конечный автомат подтверждения нарушения на ключ (камера, правило, трек).

    IDLE ──score≥thr──▶ CANDIDATE ──доля «да» ≥ ratio за confirm_s──▶ ACTIVE (одно событие started)
      ▲                    │ «да» нет дольше confirm_s                   │ «нет» дольше release_s
      └────────────────────┘                                             ▼        (или трек пропал дольше merge_s)
      └──────────── прошло cooldown_s ◀──────────────────────────── COOLDOWN (событие ended)

Время — метки кадров (ts), а не часы сервера: прогон видео быстрее реального времени даёт тот же результат.
"""

from __future__ import annotations

import uuid
from collections import deque
from dataclasses import dataclass, field
from enum import StrEnum


class State(StrEnum):
    IDLE = "idle"
    CANDIDATE = "candidate"
    ACTIVE = "active"
    COOLDOWN = "cooldown"


@dataclass(frozen=True, slots=True)
class FsmParams:
    threshold: float = 0.5
    confirm_s: float = 2.0
    confirm_ratio: float = 0.7
    release_s: float = 3.0
    cooldown_s: float = 30.0
    merge_s: float = 5.0          # сколько ждать пропавший трек, прежде чем закрыть нарушение
    merge_dist: float = 0.1       # новый трек ближе этого (доли кадра) наследует нарушение пропавшего

    @classmethod
    def from_params(cls, p: dict) -> FsmParams:
        kw = {k: float(p[k]) for k in cls.__dataclass_fields__ if k in p and p[k] is not None}
        return cls(**kw)


@dataclass
class RuleFsm:
    camera_id: str
    rule_id: int
    track_id: int | None
    state: State = State.IDLE
    event_id: str | None = None
    candidate_since: float | None = None
    started_at: float | None = None
    confirmed_at: float | None = None
    ended_at: float | None = None
    last_positive: float | None = None
    last_seen: float = 0.0
    last_step: float = 0.0
    cooldown_until: float = 0.0
    bbox: list[float] | None = None
    center: tuple[float, float] | None = None
    samples: deque = field(default_factory=deque)  # (ts, positive, score)
    confidence: float = 0.0

    def _reset(self) -> None:
        self.state = State.IDLE
        self.samples.clear()
        self.candidate_since = None

    def step(self, ts: float, score: float, p: FsmParams, bbox: list[float] | None = None,
             center: tuple[float, float] | None = None) -> str | None:
        """Трек виден на кадре ts. Возвращает 'started' / 'ended' / None."""
        positive = score >= p.threshold
        self.last_seen = self.last_step = ts
        if bbox is not None:
            self.bbox, self.center = bbox, center

        if self.state == State.COOLDOWN:
            if ts < self.cooldown_until:
                return None
            self._reset()

        if self.state == State.IDLE:
            if positive:
                self.state = State.CANDIDATE
                self.candidate_since = ts
                self.last_positive = ts
                self.samples.clear()
                self.samples.append((ts, True, score))
                if p.confirm_s <= 0:
                    return self._activate(ts)
            return None

        if self.state == State.CANDIDATE:
            self.samples.append((ts, positive, score))
            while self.samples and ts - self.samples[0][0] > p.confirm_s:
                self.samples.popleft()
            if positive:
                self.last_positive = ts
            elif ts - (self.last_positive or ts) > p.confirm_s:
                self._reset()
                return None
            ratio = sum(1 for s in self.samples if s[1]) / len(self.samples)
            if ts - self.candidate_since >= p.confirm_s and ratio >= p.confirm_ratio:
                return self._activate(ts)
            return None

        if self.state == State.ACTIVE:
            if positive:
                self.last_positive = ts
                return None
            if ts - (self.last_positive or ts) >= p.release_s:
                return self._end(p)
        return None

    def tick(self, ts: float, p: FsmParams) -> str | None:
        """Трека на кадре ts нет (перекрытие или ушёл)."""
        self.last_step = ts
        if self.state == State.CANDIDATE and ts - (self.last_positive or ts) > p.confirm_s:
            self._reset()
        elif self.state == State.ACTIVE and ts - self.last_seen > max(p.merge_s, p.release_s):
            return self._end(p)
        elif self.state == State.COOLDOWN and ts >= self.cooldown_until:
            self._reset()
        return None

    def force_end(self, ts: float) -> str | None:
        """Правило выключили или вышло его время: закрыть активное нарушение."""
        if self.state == State.ACTIVE:
            self.state = State.IDLE
            self.ended_at = self.last_positive or ts
            return "ended"
        self._reset()
        return None

    def _activate(self, ts: float) -> str:
        self.state = State.ACTIVE
        self.event_id = str(uuid.uuid4())
        self.started_at = self.candidate_since
        self.confirmed_at = ts
        self.ended_at = None
        pos = [s[2] for s in self.samples if s[1]]
        self.confidence = float(sum(pos) / len(pos)) if pos else 0.0
        return "started"

    def _end(self, p: FsmParams) -> str:
        self.state = State.COOLDOWN
        self.ended_at = self.last_positive
        self.cooldown_until = (self.last_positive or self.last_step) + p.cooldown_s
        self.samples.clear()
        return "ended"
