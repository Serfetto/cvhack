"""Render pose detections and a candidate fall from an offline replay JSONL.

First run tools/replay.py with the ONNX pose model and --save-detections.
This script then draws the detections on the original video without Docker.
The fall rule is deliberately conservative: a horizontal pose must follow a
nearby upright pose within two seconds. It is a demo heuristic, not a medical
assessment or a validated fall classifier.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import deque
from dataclasses import dataclass
from pathlib import Path

import cv2


SKELETON = (
    (5, 6), (5, 7), (7, 9), (6, 8), (8, 10),
    (5, 11), (6, 12), (11, 12), (11, 13), (13, 15),
    (12, 14), (14, 16),
)


@dataclass(frozen=True)
class Posture:
    center_x: float
    center_y: float
    height_px: float
    angle_deg: float | None
    aspect: float


def posture(person: dict, width: int, height: int) -> Posture:
    x1, y1, x2, y2 = person["bbox"]
    box_h = max((y2 - y1) * height, 1.0)
    angle = None
    points = person.get("kpts") or []
    if len(points) == 17:
        shoulders = [points[i] for i in (5, 6) if points[i][2] >= 0.3]
        hips = [points[i] for i in (11, 12) if points[i][2] >= 0.3]
        if shoulders and hips:
            sx = sum(p[0] for p in shoulders) / len(shoulders)
            sy = sum(p[1] for p in shoulders) / len(shoulders)
            hx = sum(p[0] for p in hips) / len(hips)
            hy = sum(p[1] for p in hips) / len(hips)
            angle = math.degrees(math.atan2(abs(hx - sx) * width, abs(hy - sy) * height))
    return Posture((x1 + x2) * width / 2, (y1 + y2) * height / 2, box_h, angle,
                   (x2 - x1) * width / box_h)


def detect_falls(detections: list[dict]) -> list[tuple[float, int]]:
    """Return (seconds since first frame, person index) for upright-to-ground transitions."""
    if not detections:
        return []
    first_ts = detections[0]["ts"]
    upright: deque[tuple[float, Posture]] = deque()
    falls: list[tuple[float, int]] = []
    for frame in detections:
        t = frame["ts"] - first_ts
        while upright and t - upright[0][0] > 2.0:
            upright.popleft()
        for index, person in enumerate(frame["persons"]):
            if person["score"] < 0.4:
                continue
            pose = posture(person, frame["w"], frame["h"])
            if pose.angle_deg is None:
                continue
            if pose.angle_deg <= 35 and pose.aspect <= 0.8:
                upright.append((t, pose))
            elif pose.angle_deg >= 60 and pose.aspect >= 1.15:
                for seen_t, before in reversed(upright):
                    moved_down = pose.center_y - before.center_y >= 0.2 * before.height_px
                    distance = math.hypot(pose.center_x - before.center_x,
                                          pose.center_y - before.center_y)
                    if moved_down and distance <= 1.6 * before.height_px:
                        if not falls or t - falls[-1][0] > 3.0:
                            falls.append((t, index))
                        break
    return falls


def draw_person(image, person: dict, fallen: bool) -> None:
    h, w = image.shape[:2]
    color = (20, 30, 235) if fallen else (60, 220, 80)
    x1, y1, x2, y2 = person["bbox"]
    p1, p2 = (int(x1 * w), int(y1 * h)), (int(x2 * w), int(y2 * h))
    cv2.rectangle(image, p1, p2, color, 3)
    label = "FALL DETECTED" if fallen else f"person {person['score']:.2f}"
    cv2.putText(image, label, (p1[0], max(p1[1] - 9, 20)), cv2.FONT_HERSHEY_SIMPLEX,
                0.65, color, 2, cv2.LINE_AA)
    points = person.get("kpts") or []
    if len(points) != 17:
        return
    for a, b in SKELETON:
        if points[a][2] >= 0.3 and points[b][2] >= 0.3:
            cv2.line(image, (int(points[a][0] * w), int(points[a][1] * h)),
                     (int(points[b][0] * w), int(points[b][1] * h)), color, 2, cv2.LINE_AA)
    for x, y, confidence in points:
        if confidence >= 0.3:
            cv2.circle(image, (int(x * w), int(y * h)), 3, color, -1, cv2.LINE_AA)


def render(video: Path, detections_path: Path, output: Path, output_width: int = 1280) -> list[float]:
    detections = [json.loads(line) for line in detections_path.read_text(encoding="utf-8").splitlines()
                  if line.strip()]
    if not detections:
        raise ValueError("No detections in JSONL")
    falls = detect_falls(detections)
    fall_lookup = {(round(t, 3), index) for t, index in falls}
    start_ts = detections[0]["ts"]
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise ValueError(f"Cannot open video: {video}")
    source_fps = cap.get(cv2.CAP_PROP_FPS)
    source_w, source_h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    if source_fps <= 0 or source_w <= 0 or source_h <= 0:
        raise ValueError("Invalid video FPS or dimensions")
    output_height = round(output_width * source_h / source_w / 2) * 2
    output_fps = min(source_fps, 15.0)
    output.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(output), cv2.VideoWriter_fourcc(*"mp4v"), output_fps,
                             (output_width, output_height))
    if not writer.isOpened():
        raise ValueError(f"Cannot create video: {output}")
    detection_idx = 0
    next_output_t = 0.0
    frame_idx = 0
    written = 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            t = frame_idx / source_fps
            frame_idx += 1
            if t + 1e-6 < next_output_t:
                continue
            next_output_t += 1 / output_fps
            while detection_idx + 1 < len(detections) and detections[detection_idx + 1]["ts"] - start_ts <= t:
                detection_idx += 1
            detected_t = detections[detection_idx]["ts"] - start_ts
            image = cv2.resize(frame, (output_width, output_height), interpolation=cv2.INTER_AREA)
            if t - detected_t <= 0.3:
                for index, person in enumerate(detections[detection_idx]["persons"]):
                    marked = (round(detected_t, 3), index) in fall_lookup
                    draw_person(image, person, marked)
            past_falls = [fall_t for fall_t, _ in falls if fall_t <= t]
            if past_falls:
                latest = past_falls[-1]
                cv2.rectangle(image, (0, 0), (output_width, 53), (16, 19, 35), -1)
                message = f"FALL DETECTED at {latest:.1f}s" if t - latest <= 3.5 else f"Fall detected at {latest:.1f}s"
                cv2.putText(image, message, (18, 38), cv2.FONT_HERSHEY_SIMPLEX, 1.05,
                            (30, 45, 250), 3, cv2.LINE_AA)
            writer.write(image)
            written += 1
    finally:
        writer.release()
        cap.release()
    if not written:
        raise ValueError("Video contains no frames")
    return [round(t, 2) for t, _ in falls]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", type=Path)
    parser.add_argument("detections", type=Path, help="JSONL from tools/replay.py --save-detections")
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    times = render(args.video, args.detections, args.output)
    print(f"Output: {args.output}")
    print(f"Candidate falls at: {times or 'none'} seconds")


if __name__ == "__main__":
    main()
