"""Движок аналитики без ввода-вывода: детекции кадра → трекинг → сценарии → автомат → переходы.

Один и тот же код работает в analytics-service (очереди Redis) и в tools/replay.py (видеофайл офлайн).
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime

import numpy as np

from common.logging import get_logger
from common.messages import CameraConfig, DetectionsMsg, RuleCfg, Severity, ViolationKind, ViolationMsg
from common.schedule import is_active
from scenarios import REGISTRY, effective_params
from scenarios.base import Observation, Scene, Track, Zone

from .fsm import FsmParams, RuleFsm, State
from .tracking import Tracker, make_tracker

log = get_logger(__name__)

TRACK_TTL_S = 10.0       # трек без наблюдений дольше этого забываем
IDLE_FSM_TTL_S = 30.0    # автомат в IDLE без шагов дольше этого удаляем


@dataclass
class Transition:
    """Нарушение началось (started) или закончилось (ended)."""

    kind: str
    event_id: str
    camera: CameraConfig
    rule: RuleCfg
    scenario: str
    scenario_title: str
    severity: Severity
    zone: Zone | None
    track_id: int | None
    started_at: float
    confirmed_at: float | None
    ended_at: float | None
    bbox: list[float] | None
    confidence: float
    frame_ts: float
    seq: int
    frame_key: str

    def to_violation(self) -> ViolationMsg:
        """Сообщение для потока violations (без доказательств — их добавляет сервис)."""
        return ViolationMsg(
            event_id=self.event_id, kind=ViolationKind(self.kind), camera_id=self.camera.id, camera_name=self.camera.name,
            area_id=self.camera.area_id, zone_id=self.zone.id if self.zone else None, zone_name=self.zone.name if self.zone else None,
            rule_id=self.rule.id, scenario=self.scenario, scenario_title=self.scenario_title, severity=self.severity,
            track_id=self.track_id, started_at=self.started_at, confirmed_at=self.confirmed_at, ended_at=self.ended_at,
            bbox=self.bbox, confidence=self.confidence, frame_ts=self.frame_ts, seq=self.seq,
        )


@dataclass
class CameraRuntime:
    cfg: CameraConfig
    tracker: Tracker
    zones: dict[int, Zone] = field(default_factory=dict)
    tracks: dict[int, Track] = field(default_factory=dict)
    fsms: dict[tuple[int, int | None], RuleFsm] = field(default_factory=dict)
    last_seq: int = -1
    last_ts: float = 0.0


class Engine:
    def __init__(self, tracker_kind: str = "bytetrack", tz: str = "Europe/Moscow", clock=None):
        self.tracker_kind = tracker_kind
        self.tz = tz
        # для расписаний: в сервисе — текущее время, в replay — время видео
        self.clock = clock or (lambda ts: datetime.now(UTC))
        self.cameras: dict[str, CameraRuntime] = {}
        self._warned: set[tuple[int, str]] = set()

    # --- конфигурация -------------------------------------------------------------

    def set_config(self, cfg: CameraConfig) -> list[Transition]:
        rt = self.cameras.get(cfg.id)
        if rt is None or abs(rt.cfg.analysis_fps - cfg.analysis_fps) > 1e-6:
            tracker = make_tracker(self.tracker_kind, cfg.analysis_fps)
            ended = self.remove_camera(cfg.id) if rt else []
            rt = CameraRuntime(cfg=cfg, tracker=tracker)
            self.cameras[cfg.id] = rt
        else:
            ended = []
        rt.cfg = cfg
        rt.zones = {}
        for z in cfg.zones:
            if not z.enabled:
                continue
            try:
                rt.zones[z.id] = Zone(id=z.id, name=z.name, kind=z.kind.value, coords=z.polygon)
            except Exception as e:  # кривой полигон не должен ронять камеру
                log.error("bad_zone", camera=cfg.id, zone=z.id, error=str(e))
        rule_ids = {r.id for r in cfg.rules}
        for key in [k for k in rt.fsms if k[0] not in rule_ids]:
            ended += self._close(rt, rt.fsms.pop(key), rt.last_ts)
        return ended

    # --- состояние между рестартами -------------------------------------------------------

    def snapshot(self) -> dict[str, dict]:
        """Активные нарушения и паузы после них: переживают рестарт сервиса (иначе событие
        не закроется, а человек, оставшийся в зоне, даст повторное оповещение)."""
        out = {}
        for cid, rt in self.cameras.items():
            for (rule_id, _), f in rt.fsms.items():
                if f.event_id and f.state in (State.ACTIVE, State.COOLDOWN):
                    out[f.event_id] = {
                        "camera_id": cid, "rule_id": rule_id, "track_id": f.track_id, "state": f.state.value,
                        "started_at": f.started_at, "confirmed_at": f.confirmed_at, "last_positive": f.last_positive,
                        "cooldown_until": f.cooldown_until, "bbox": f.bbox, "center": f.center, "confidence": f.confidence,
                    }
        return out

    def restore(self, items: dict[str, dict], now: float) -> int:
        """Поднимает сохранённые автоматы как «потерявшие трек»: если человек ещё в кадре, новый трек
        унаследует событие (склейка), иначе через merge_s придёт ended."""
        n = 0
        for i, (event_id, d) in enumerate(items.items()):
            rt = self.cameras.get(d.get("camera_id"))
            if rt is None or not any(r.id == d.get("rule_id") for r in rt.cfg.rules):
                continue
            restored_tid = -(i + 1) if d.get("track_id") is not None else None
            f = RuleFsm(rt.cfg.id, d["rule_id"], restored_tid, state=State(d["state"]), event_id=event_id,
                        started_at=d.get("started_at"), confirmed_at=d.get("confirmed_at"),
                        last_positive=d.get("last_positive"), last_seen=now, last_step=now,
                        cooldown_until=d.get("cooldown_until") or 0.0, bbox=d.get("bbox"),
                        center=tuple(d["center"]) if d.get("center") else None, confidence=d.get("confidence") or 0.0)
            rt.fsms[(d["rule_id"], restored_tid)] = f
            n += 1
        return n

    def remove_camera(self, camera_id: str) -> list[Transition]:
        rt = self.cameras.pop(camera_id, None)
        if rt is None:
            return []
        out = []
        for fsm in rt.fsms.values():
            out += self._close(rt, fsm, rt.last_ts)
        return out

    # --- кадр -------------------------------------------------------------------------------

    def process(self, det: DetectionsMsg) -> list[Transition]:
        rt = self.cameras.get(det.camera_id)
        if rt is None or not rt.cfg.enabled:
            return []
        if det.seq <= rt.last_seq:
            return []  # повтор или кадр не по порядку
        rt.last_seq, rt.last_ts = det.seq, det.ts

        # 1. трекинг
        visible: list[Track] = []
        for tid, p in rt.tracker.update(det.persons, det.w, det.h, det.ts):
            tr = rt.tracks.get(tid)
            if tr is None:
                tr = rt.tracks[tid] = Track(id=tid, camera_id=det.camera_id, w=det.w, h=det.h)
            tr.w, tr.h = det.w, det.h
            tr.add(Observation(ts=det.ts, bbox=np.asarray(p.bbox, dtype=np.float32), score=p.score,
                               kpts=np.asarray(p.kpts, dtype=np.float32) if p.kpts else None))
            visible.append(tr)
        for tid in [t for t, tr in rt.tracks.items() if det.ts - tr.ts > TRACK_TTL_S]:
            del rt.tracks[tid]

        scene = Scene(camera_id=det.camera_id, ts=det.ts, seq=det.seq, w=det.w, h=det.h,
                      zones=rt.zones, tracks=visible, objects=det.objects)
        now = self.clock(det.ts)
        out: list[Transition] = []
        stepped: set[tuple[int, int | None]] = set()

        # 2. правила
        active_rules: dict[int, tuple[RuleCfg, object, dict, FsmParams]] = {}
        for rule in rt.cfg.rules:
            sc = REGISTRY.get(rule.scenario)
            if sc is None:
                self._warn_once(rule.id, f"нет сценария {rule.scenario}")
                continue
            if not rule.enabled or not is_active(rule.schedule, rule.valid_until, now, self.tz):
                continue
            zone = None
            if rule.zone_id is not None:
                zone = rt.zones.get(rule.zone_id)
                if zone is None:
                    continue  # зона выключена или удалена
            params = effective_params(sc, rule.params)
            fp = FsmParams.from_params(params)
            active_rules[rule.id] = (rule, sc, params, fp)
            rscene = replace(scene, zone=zone)

            if getattr(sc, "per_track", True):
                targets = [(tr.id, tr) for tr in visible]
            else:
                targets = [(None, None)]
            for tid, tr in targets:
                score = self._check(sc, tr, rscene, params, rule)
                key = (rule.id, tid)
                fsm = rt.fsms.get(key)
                if fsm is None:
                    if score < fp.threshold:
                        continue
                    fsm = self._adopt(rt, rule.id, tr, fp, det.ts) or RuleFsm(det.camera_id, rule.id, tid)
                    rt.fsms[key] = fsm
                bbox = [float(v) for v in tr.bbox] if tr is not None else None
                res = fsm.step(det.ts, score, fp, bbox=bbox, center=tr.center if tr is not None else None)
                stepped.add(key)
                if res:
                    out.append(self._transition(res, rt, fsm, rule, sc, zone, det))

        # 3. автоматы без наблюдения на этом кадре; правила, которые выключили
        for key, fsm in list(rt.fsms.items()):
            if key in stepped:
                continue
            entry = active_rules.get(key[0])
            if entry is None:
                out += self._close(rt, fsm, det.ts, det)
                del rt.fsms[key]
                continue
            rule, sc, _, fp = entry
            res = fsm.tick(det.ts, fp)
            if res:
                out.append(self._transition(res, rt, fsm, rule, sc, rt.zones.get(rule.zone_id) if rule.zone_id else None, det))
            if fsm.state == State.IDLE and det.ts - fsm.last_step > IDLE_FSM_TTL_S:
                del rt.fsms[key]
            elif fsm.state == State.IDLE and fsm.track_id is not None and fsm.track_id not in rt.tracks:
                del rt.fsms[key]
        return out

    # --- внутреннее ---------------------------------------------------------------------------------

    def _check(self, sc, tr: Track | None, scene: Scene, params: dict, rule: RuleCfg) -> float:
        try:
            v = float(sc.check(tr, scene, params))
            return 0.0 if math.isnan(v) else max(0.0, min(1.0, v))
        except Exception as e:
            self._warn_once(rule.id, f"{rule.scenario}.check: {type(e).__name__}: {e}")
            return 0.0

    def _adopt(self, rt: CameraRuntime, rule_id: int, tr: Track | None, fp: FsmParams, ts: float) -> RuleFsm | None:
        """Склейка треков: человек пропал на пару кадров (перекрытие) и вернулся с новым id —
        нарушение продолжается, второго события нет."""
        if tr is None:
            return None
        cx, cy = tr.center
        best, best_d = None, fp.merge_dist
        for key, fsm in rt.fsms.items():
            if key[0] != rule_id or fsm.state not in (State.ACTIVE, State.COOLDOWN) or fsm.center is None:
                continue
            if fsm.track_id is not None and fsm.track_id in rt.tracks and rt.tracks[fsm.track_id].ts >= ts:
                continue  # старый трек ещё виден — это другой человек
            if ts - fsm.last_seen > fp.merge_s:
                continue
            d = math.hypot(cx - fsm.center[0], cy - fsm.center[1])
            if d < best_d:
                best, best_d = key, d
        if best is None:
            return None
        fsm = rt.fsms.pop(best)
        fsm.track_id = tr.id
        return fsm

    def _close(self, rt: CameraRuntime, fsm: RuleFsm, ts: float, det: DetectionsMsg | None = None) -> list[Transition]:
        if fsm.force_end(ts) != "ended":
            return []
        rule = next((r for r in rt.cfg.rules if r.id == fsm.rule_id), None) or RuleCfg(id=fsm.rule_id, scenario="unknown")
        sc = REGISTRY.get(rule.scenario)
        return [self._transition("ended", rt, fsm, rule, sc, rt.zones.get(rule.zone_id) if rule.zone_id else None, det)]

    def _transition(self, kind: str, rt: CameraRuntime, fsm: RuleFsm, rule: RuleCfg, sc, zone: Zone | None,
                    det: DetectionsMsg | None) -> Transition:
        severity = rule.severity or getattr(sc, "severity", Severity.MEDIUM)
        return Transition(
            kind=kind, event_id=fsm.event_id or "", camera=rt.cfg, rule=rule, scenario=rule.scenario,
            scenario_title=getattr(sc, "title", rule.scenario), severity=Severity(severity), zone=zone,
            track_id=fsm.track_id, started_at=fsm.started_at or 0.0, confirmed_at=fsm.confirmed_at,
            ended_at=fsm.ended_at if kind == "ended" else None, bbox=fsm.bbox, confidence=round(fsm.confidence, 3),
            frame_ts=det.ts if det else rt.last_ts, seq=det.seq if det else rt.last_seq, frame_key=det.frame_key if det else "",
        )

    def _warn_once(self, rule_id: int, msg: str) -> None:
        if (rule_id, msg) not in self._warned:
            self._warned.add((rule_id, msg))
            log.error("rule_problem", rule=rule_id, problem=msg)

    def stats(self) -> dict:
        return {
            cid: {"tracks": len(rt.tracks), "fsms": len(rt.fsms),
                  "active": sum(1 for f in rt.fsms.values() if f.state == State.ACTIVE), "last_ts": rt.last_ts,
                  "lag_s": round(time.time() - rt.last_ts, 3) if rt.last_ts else None}
            for cid, rt in self.cameras.items()
        }
