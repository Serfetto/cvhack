"""YOLOv8 pose letterbox, CPU tail, person NMS and normalized coordinates."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import cv2
import numpy as np
import onnxruntime as ort

from backends.base import ModelSpec


@dataclass(frozen=True)
class LetterboxMeta:
    width: int
    height: int
    ratio: float
    pad_x: int
    pad_y: int


def preprocess(image_bgr: np.ndarray, spec: ModelSpec) -> tuple[np.ndarray, LetterboxMeta]:
    height, width = image_bgr.shape[:2]
    size = spec.imgsz
    ratio = min(size / width, size / height)
    new_w, new_h = round(width * ratio), round(height * ratio)
    pad_x = (size - new_w) // 2
    pad_y = (size - new_h) // 2
    canvas = np.full((size, size, 3), 114, dtype=np.uint8)
    resized = cv2.resize(image_bgr, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
    canvas[pad_y:pad_y + new_h, pad_x:pad_x + new_w] = resized
    rgb = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB)
    tensor = np.ascontiguousarray(rgb.transpose(2, 0, 1)[None], dtype=np.float32) / 255.0
    return tensor, LetterboxMeta(width, height, ratio, pad_x, pad_y)


@lru_cache(maxsize=4)
def _tail_session(path: str) -> ort.InferenceSession:
    options = ort.SessionOptions()
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    return ort.InferenceSession(path, sess_options=options, providers=["CPUExecutionProvider"])


def _decoded_output(outputs: dict[str, np.ndarray], spec: ModelSpec) -> np.ndarray:
    # Full ONNX export yields [B, 56, 8400]. A TPU program yields the seven
    # cut tensors; the small ONNX tail completes YOLO's DFL/keypoint decode.
    if len(outputs) == 1:
        candidate = next(iter(outputs.values()))
        if candidate.ndim == 3 and candidate.shape[1] == 56:
            return candidate
    tail_path = spec.path("onnx_tail")
    session = _tail_session(str(tail_path))
    tail_inputs = {item.name: np.asarray(outputs[item.name], dtype=np.float32)
                   for item in session.get_inputs()}
    return session.run(None, tail_inputs)[0]


def _iou_one(box: np.ndarray, others: np.ndarray) -> np.ndarray:
    left = np.maximum(box[:2], others[:, :2])
    right = np.minimum(box[2:], others[:, 2:])
    intersection = np.maximum(right - left, 0).prod(axis=1)
    area_a = np.maximum(box[2:] - box[:2], 0).prod()
    area_b = np.maximum(others[:, 2:] - others[:, :2], 0).prod(axis=1)
    return intersection / np.maximum(area_a + area_b - intersection, 1e-9)


def postprocess_pose(
    outputs: dict[str, np.ndarray], meta: LetterboxMeta, spec: ModelSpec,
    conf: float = 0.35, iou: float = 0.5,
) -> list[dict]:
    prediction = _decoded_output(outputs, spec)
    if prediction.ndim != 3 or prediction.shape[0] != 1 or prediction.shape[1] != 56:
        raise ValueError(f"Expected YOLOv8 pose output [1,56,N], got {prediction.shape}")
    candidates = prediction[0].T
    candidates = candidates[candidates[:, 4] >= conf]
    if not len(candidates):
        return []
    candidates = candidates[np.argsort(candidates[:, 4])[::-1][:300]]
    xywh = candidates[:, :4]
    boxes = np.column_stack((xywh[:, :2] - xywh[:, 2:] / 2,
                             xywh[:, :2] + xywh[:, 2:] / 2))
    selected: list[int] = []
    remaining = np.arange(len(candidates))
    while len(remaining) and len(selected) < 100:
        index = int(remaining[0])
        selected.append(index)
        remaining = remaining[1:]
        if len(remaining):
            remaining = remaining[_iou_one(boxes[index], boxes[remaining]) <= iou]

    result = []
    for index in selected:
        box = boxes[index].copy()
        box[[0, 2]] = (box[[0, 2]] - meta.pad_x) / (meta.ratio * meta.width)
        box[[1, 3]] = (box[[1, 3]] - meta.pad_y) / (meta.ratio * meta.height)
        box = np.clip(box, 0.0, 1.0)
        points = candidates[index, 5:].reshape(17, 3).copy()
        points[:, 0] = (points[:, 0] - meta.pad_x) / (meta.ratio * meta.width)
        points[:, 1] = (points[:, 1] - meta.pad_y) / (meta.ratio * meta.height)
        points[:, :2] = np.clip(points[:, :2], 0.0, 1.0)
        result.append({"bbox": box.tolist(), "score": float(candidates[index, 4]),
                       "kpts": points.tolist()})
    return result
