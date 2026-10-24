"""YOLOv8 detection postprocessing: class-aware NMS and normalized coordinates."""

from __future__ import annotations

import numpy as np

from backends.base import ModelSpec

from .pose import LetterboxMeta, _decoded_output, _iou_one


def postprocess_detect(
    outputs: dict[str, np.ndarray], meta: LetterboxMeta, spec: ModelSpec,
    conf: float = 0.35, iou: float = 0.5,
) -> list[dict]:
    channels = 4 + len(spec.classes)
    prediction = _decoded_output(outputs, spec, channels)
    if prediction.ndim != 3 or prediction.shape[0] != 1 or prediction.shape[1] != channels:
        raise ValueError(f"Expected YOLOv8 detect output [1,{channels},N], got {prediction.shape}")
    candidates = prediction[0].T
    classes = candidates[:, 4:].argmax(axis=1)
    scores = candidates[np.arange(len(candidates)), 4 + classes]
    keep = scores >= conf
    if not keep.any():
        return []
    candidates, classes, scores = candidates[keep], classes[keep], scores[keep]
    order = np.argsort(scores)[::-1][:300]
    candidates, classes, scores = candidates[order], classes[order], scores[order]
    xywh = candidates[:, :4]
    boxes = np.column_stack((xywh[:, :2] - xywh[:, 2:] / 2,
                             xywh[:, :2] + xywh[:, 2:] / 2))
    shifted = boxes + classes[:, None] * 4096.0  # boxes of different classes never overlap in NMS
    selected: list[int] = []
    remaining = np.arange(len(candidates))
    while len(remaining) and len(selected) < 100:
        index = int(remaining[0])
        selected.append(index)
        remaining = remaining[1:]
        if len(remaining):
            remaining = remaining[_iou_one(shifted[index], shifted[remaining]) <= iou]

    result = []
    for index in selected:
        box = boxes[index].copy()
        box[[0, 2]] = (box[[0, 2]] - meta.pad_x) / (meta.ratio * meta.width)
        box[[1, 3]] = (box[[1, 3]] - meta.pad_y) / (meta.ratio * meta.height)
        result.append({"cls": spec.classes[int(classes[index])], "bbox": np.clip(box, 0.0, 1.0).tolist(),
                       "score": float(scores[index])})
    return result
