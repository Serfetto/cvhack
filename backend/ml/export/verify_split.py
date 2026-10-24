"""Check that CPU execution of the LinQ head plus ONNX tail matches full ONNX."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np
import onnxruntime as ort


INFERENCE_DIR = Path(__file__).resolve().parents[2] / "server/services/inference"
sys.path.insert(0, str(INFERENCE_DIR))
from backends.base import ModelSpec  # noqa: E402
from ml_runtime import postprocess_detect, postprocess_pose, preprocess  # noqa: E402


def session(path: Path) -> ort.InferenceSession:
    options = ort.SessionOptions()
    options.intra_op_num_threads = 1
    return ort.InferenceSession(str(path), sess_options=options, providers=["CPUExecutionProvider"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("model_dir", type=Path)
    parser.add_argument("images", type=Path)
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()
    spec = ModelSpec.load(args.model_dir)
    full = session(spec.path("onnx"))
    head = session(spec.path("onnx_head"))
    tail = session(spec.path("onnx_tail"))
    paths = sorted(p for p in args.images.rglob("*") if p.suffix.lower() in {".jpg", ".jpeg", ".png"})
    postprocess = postprocess_pose if spec.task == "pose" else postprocess_detect
    errors = []
    detection_counts = []
    for path in paths[:args.limit]:
        image = cv2.imread(str(path))
        if image is None:
            continue
        tensor, meta = preprocess(image, spec)
        full_output = full.run(None, {spec.input_name: tensor})[0]
        cut_output = dict(zip(spec.output_names, head.run(spec.output_names, {spec.input_name: tensor}), strict=True))
        reconstructed = tail.run(None, cut_output)[0]
        errors.append(float(np.max(np.abs(full_output - reconstructed))))
        full_people = postprocess({full.get_outputs()[0].name: full_output}, meta, spec)
        cut_people = postprocess(cut_output, meta, spec)
        if len(full_people) != len(cut_people):
            raise AssertionError(f"Detection count differs on {path}: {len(full_people)} / {len(cut_people)}")
        detection_counts.append(len(full_people))
    if not errors:
        raise ValueError("No valid images checked")
    max_error = max(errors)
    print({"images": len(errors), "max_abs_output_error": max_error,
           "detections": sum(detection_counts)})
    if max_error > 1e-4:
        raise AssertionError(f"ONNX split changed output by {max_error}")


if __name__ == "__main__":
    main()
