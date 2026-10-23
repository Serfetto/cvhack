"""Трекинг людей по камере. Основной — ByteTrack из `supervision`, запасной — простой IoU-трекер
без зависимостей (для стенда, где нет supervision, и для тестов)."""

from __future__ import annotations

from typing import Protocol

import numpy as np

from common.messages import Person


class Tracker(Protocol):
    def update(self, persons: list[Person], w: int, h: int, ts: float) -> list[tuple[int, Person]]:
        """Возвращает пары (track_id, человек) для людей, которых трекер подтвердил на этом кадре."""
        ...


class ByteTracker:
    """ByteTrack: пакет `trackers` (Roboflow), в старых версиях — `supervision.ByteTrack`.
    Время кадра передаём явно, поэтому неровный FPS (пропуски кадров под нагрузкой) не ломает трекинг."""

    def __init__(self, fps: float = 5.0, activation: float = 0.45, high_conf: float = 0.5, lost_s: float = 2.0,
                 min_iou: float = 0.1, min_frames: int = 2):
        import supervision as sv

        self.sv = sv
        lost_buffer = max(int(lost_s * 30), 1)  # в «кадрах при 30 FPS» — так считают обе библиотеки
        try:
            from trackers import ByteTrackTracker

            self.tracker = ByteTrackTracker(lost_track_buffer=lost_buffer, frame_rate=fps, track_activation_threshold=activation,
                                            minimum_consecutive_frames=min_frames, minimum_iou_threshold=min_iou,
                                            high_conf_det_threshold=high_conf)
            self._with_ts = True
        except ImportError:
            self.tracker = sv.ByteTrack(track_activation_threshold=activation, lost_track_buffer=lost_buffer,
                                        frame_rate=max(int(round(fps)), 1), minimum_consecutive_frames=min_frames)
            self._with_ts = False

    def update(self, persons: list[Person], w: int, h: int, ts: float) -> list[tuple[int, Person]]:
        sv = self.sv
        if persons:
            xyxy = np.array([p.bbox for p in persons], dtype=np.float32) * np.array([w, h, w, h], dtype=np.float32)
            dets = sv.Detections(
                xyxy=xyxy,
                confidence=np.array([p.score for p in persons], dtype=np.float32),
                class_id=np.zeros(len(persons), dtype=int),
                data={"idx": np.arange(len(persons))},
            )
        else:
            dets = sv.Detections.empty()
            dets.data["idx"] = np.zeros(0, dtype=int)
        out = self.tracker.update(dets, timestamp=ts) if self._with_ts else self.tracker.update_with_detections(dets)
        if len(out) == 0 or out.tracker_id is None:
            return []
        keep = out.tracker_id >= 0  # -1 — трек ещё не подтверждён (minimum_consecutive_frames)
        out = out[keep]
        idx = out.data.get("idx")
        if idx is None:  # версия потеряла data — сопоставляем по IoU
            return _match_back(out.xyxy / np.array([w, h, w, h]), out.tracker_id, persons)
        return [(int(tid), persons[int(i)]) for tid, i in zip(out.tracker_id, idx, strict=False)]


def _iou(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """IoU всех пар a (N,4) × b (M,4)."""
    if len(a) == 0 or len(b) == 0:
        return np.zeros((len(a), len(b)))
    x1 = np.maximum(a[:, None, 0], b[None, :, 0])
    y1 = np.maximum(a[:, None, 1], b[None, :, 1])
    x2 = np.minimum(a[:, None, 2], b[None, :, 2])
    y2 = np.minimum(a[:, None, 3], b[None, :, 3])
    inter = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
    area_a = (a[:, 2] - a[:, 0]) * (a[:, 3] - a[:, 1])
    area_b = (b[:, 2] - b[:, 0]) * (b[:, 3] - b[:, 1])
    return inter / np.maximum(area_a[:, None] + area_b[None, :] - inter, 1e-9)


def _match_back(boxes: np.ndarray, ids, persons: list[Person]) -> list[tuple[int, Person]]:
    pb = np.array([p.bbox for p in persons]) if persons else np.zeros((0, 4))
    iou = _iou(boxes, pb)
    out = []
    for i, tid in enumerate(ids):
        if iou.shape[1] and iou[i].max() > 0.3:
            out.append((int(tid), persons[int(iou[i].argmax())]))
    return out


class IouTracker:
    """Жадное сопоставление по IoU с запасом по расстоянию центров. Без фильтра Калмана."""

    def __init__(self, iou_thresh: float = 0.25, max_center_dist: float = 0.08, lost_s: float = 2.0, min_score: float = 0.25):
        self.iou_thresh = iou_thresh
        self.max_center_dist = max_center_dist
        self.lost_s = lost_s
        self.min_score = min_score
        self.next_id = 1
        self.tracks: dict[int, tuple[np.ndarray, float]] = {}  # id → (bbox, last_ts)

    def update(self, persons: list[Person], w: int, h: int, ts: float) -> list[tuple[int, Person]]:
        self.tracks = {tid: v for tid, v in self.tracks.items() if ts - v[1] <= self.lost_s}
        cand = [p for p in persons if p.score >= self.min_score]
        ids = list(self.tracks)
        tb = np.array([self.tracks[i][0] for i in ids]) if ids else np.zeros((0, 4))
        pb = np.array([p.bbox for p in cand]) if cand else np.zeros((0, 4))
        iou = _iou(tb, pb)
        out: list[tuple[int, Person]] = []
        used_t: set[int] = set()
        used_p: set[int] = set()
        pairs = sorted(((iou[i, j], i, j) for i in range(len(ids)) for j in range(len(cand))), reverse=True)
        for v, i, j in pairs:
            if v < self.iou_thresh:
                break
            if i in used_t or j in used_p:
                continue
            used_t.add(i)
            used_p.add(j)
            out.append((ids[i], cand[j]))
        # запасной шаг: близкие центры (быстрое движение при низком FPS)
        for j, p in enumerate(cand):
            if j in used_p:
                continue
            pc = np.array([(p.bbox[0] + p.bbox[2]) / 2, (p.bbox[1] + p.bbox[3]) / 2])
            best, best_d = None, self.max_center_dist
            for i in range(len(ids)):
                if i in used_t:
                    continue
                b = tb[i]
                d = float(np.hypot(*(pc - np.array([(b[0] + b[2]) / 2, (b[1] + b[3]) / 2]))))
                if d < best_d:
                    best, best_d = i, d
            if best is not None:
                used_t.add(best)
                used_p.add(j)
                out.append((ids[best], p))
        for j, p in enumerate(cand):
            if j not in used_p:
                out.append((self.next_id, p))
                self.next_id += 1
        for tid, p in out:
            self.tracks[tid] = (np.array(p.bbox), ts)
        return out


def make_tracker(kind: str, fps: float) -> Tracker:
    if kind == "bytetrack":
        try:
            return ByteTracker(fps=fps)
        except ImportError:
            pass
    return IouTracker()
