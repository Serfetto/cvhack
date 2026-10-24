"""Geometry shared by the fall and immobility scenarios."""

from __future__ import annotations

import math
from dataclasses import dataclass

from scenarios.base import Observation, Track


@dataclass(frozen=True)
class Posture:
    center_x: float  # pixels
    center_y: float
    height_px: float
    length_px: float
    aspect: float  # width / height in pixels
    torso_angle_deg: float | None  # 0 = upright, 90 = horizontal


def posture_from_detection(bbox, kpts, width: int, height: int) -> Posture:
    x1, y1, x2, y2 = bbox
    width_px = max(float(x2 - x1) * width, 1.0)
    height_px = max(float(y2 - y1) * height, 1.0)
    shoulders = [kpts[i] for i in (5, 6) if kpts is not None and len(kpts) > i and kpts[i][2] >= 0.3]
    hips = [kpts[i] for i in (11, 12) if kpts is not None and len(kpts) > i and kpts[i][2] >= 0.3]
    angle = None
    if shoulders and hips:
        sx = sum(p[0] for p in shoulders) / len(shoulders)
        sy = sum(p[1] for p in shoulders) / len(shoulders)
        hx = sum(p[0] for p in hips) / len(hips)
        hy = sum(p[1] for p in hips) / len(hips)
        angle = math.degrees(math.atan2(abs(hx - sx) * width, abs(hy - sy) * height))
    return Posture(
        center_x=float(x1 + x2) * width / 2,
        center_y=float(y1 + y2) * height / 2,
        height_px=height_px,
        length_px=max(width_px, height_px),
        aspect=width_px / height_px,
        torso_angle_deg=angle,
    )


def posture(track: Track, obs: Observation | None = None) -> Posture:
    obs = obs or track.last
    return posture_from_detection(obs.bbox, obs.kpts, track.w, track.h)


def is_upright(p: Posture, params: dict) -> bool:
    return p.torso_angle_deg is not None and p.torso_angle_deg <= params.get("upright_angle_deg", 35) \
        and p.aspect <= params.get("upright_aspect_max", 0.8)


def is_ground(p: Posture, params: dict) -> bool:
    return p.torso_angle_deg is not None and p.torso_angle_deg >= params.get("fallen_angle_deg", 60) \
        and p.aspect >= params.get("fallen_aspect_min", 1.15)
