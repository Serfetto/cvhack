"""Calibrate and compile a cut YOLO pose graph using the official LinQ SDK."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np
import onnx
from tpu_framework import (
    Network, O1, O5, QuantizedModel, RegularModel, TPU_H1M, TpuProgram,
    compiler, preliminary_model_conditioning,
)


INFERENCE_DIR = Path(__file__).resolve().parents[2] / "server/services/inference"
sys.path.insert(0, str(INFERENCE_DIR))
from backends.base import ModelSpec  # noqa: E402
from ml_runtime import preprocess  # noqa: E402


def calibration_data(image_dir: Path, spec: ModelSpec, limit: int) -> np.ndarray:
    images = []
    paths = sorted(p for p in image_dir.rglob("*") if p.suffix.lower() in {".jpg", ".jpeg", ".png"})
    for path in paths[:limit]:
        image = cv2.imread(str(path))
        if image is None:
            continue
        tensor, _ = preprocess(image, spec)
        images.append(tensor[0])
    if not images:
        raise ValueError(f"No readable calibration images under {image_dir}")
    print(f"Calibrating on {len(images)} real images", flush=True)
    return np.stack(images).astype(np.float32)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("model_dir", type=Path)
    parser.add_argument("calibration_dir", type=Path)
    parser.add_argument("--limit", type=int, default=300)
    parser.add_argument("--preset", choices=["o5", "o1"], default="o5")
    args = parser.parse_args()
    spec = ModelSpec.load(args.model_dir)
    model = onnx.load(spec.path("onnx_head"))
    model = preliminary_model_conditioning(model)
    onnx.save(model, args.model_dir / "pose_head_opt.onnx")
    regular = RegularModel(model=model)
    data = calibration_data(args.calibration_dir, spec, args.limit)
    thresholds = regular.calibrate_torch(calibration_data={spec.input_name: data}, device="cpu")
    RegularModel.dump_thresholds(str(args.model_dir / "thresholds.json"), thresholds)
    quantized = regular.quantize(thresholds)
    quant_name = "pose_head.qm.onnx"
    quantized.save(file_dir=str(args.model_dir), file_name=quant_name)
    network, _ = Network.from_quantized_model(QuantizedModel.load(str(args.model_dir / quant_name)))

    presets = [("o5", O5), ("o1", O1)] if args.preset == "o5" else [("o1", O1)]
    failures = []
    for name, preset in presets:
        try:
            executable, descriptions = compiler.compile_(
                hardware_parameters=TPU_H1M, network=network, parameters=preset,
            )
            program_name = f"yolov8n_pose_b1_{name}_h1m.tpu"
            TpuProgram.from_executable(executable, descriptions).to_file(str(args.model_dir / program_name))
            metadata = spec.meta | {
                "files": spec.files | {"tpu": program_name}, "preset": name,
                "calibration_images": int(data.shape[0]), "sdk": "2026.9.45",
            }
            (args.model_dir / "meta.json").write_text(json.dumps(metadata, indent=2) + "\n")
            print(args.model_dir / program_name)
            return
        except Exception as exc:
            failures.append(f"{name}: {exc}")
            print(f"Compilation with {name} failed: {exc}", file=sys.stderr, flush=True)
    raise RuntimeError("All compilation presets failed: " + "; ".join(failures))


if __name__ == "__main__":
    main()
