"""Split the current YOLOv8n-pose export before DFL and keypoint decode."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import onnx
from tpu_framework import get_sub_model


# SDK's published seven tensor names refer to a different Ultralytics export.
# In Ultralytics 8.4.0 the three branches join here (box distribution,
# objectness, keypoints); all decode/formatting runs in the ONNX CPU tail.
CUT = [
    "/model.22/Concat_output_0",
    "/model.22/Concat_1_output_0",
    "/model.22/Concat_2_output_0",
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("model", type=Path)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    model = onnx.load(args.model)
    node_outputs = {name for node in model.graph.node for name in node.output}
    missing = set(CUT) - node_outputs
    if missing:
        raise ValueError(f"These cut tensors are absent in the ONNX graph: {sorted(missing)}")
    inputs = [value.name for value in model.graph.input]
    outputs = [value.name for value in model.graph.output]
    if len(inputs) != 1 or len(outputs) != 1:
        raise ValueError(f"Expected one model input/output, got {inputs} / {outputs}")
    head = get_sub_model(model=model, ordered_input_names=inputs, ordered_output_names=CUT)
    tail = get_sub_model(model=model, ordered_input_names=CUT, ordered_output_names=outputs)
    onnx.checker.check_model(head)
    onnx.checker.check_model(tail)
    onnx.save(head, args.out_dir / "pose_head.onnx")
    onnx.save(tail, args.out_dir / "pose_tail.onnx")
    digest = hashlib.sha256(args.model.read_bytes()).hexdigest()
    meta = {
        "name": "pose", "task": "pose", "version": "yolov8n-pose-v8.4.0",
        "input_name": inputs[0], "input_shape": [1, 3, 640, 640],
        "output_names": CUT, "classes": ["person"],
        "files": {"onnx": args.model.name, "onnx_head": "pose_head.onnx", "onnx_tail": "pose_tail.onnx"},
        "source_sha256": digest, "preprocessing": "RGB letterbox /255", "sdk": "2026.9.45",
    }
    (args.out_dir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"inputs": inputs, "outputs": outputs, "cut_outputs": CUT}, indent=2))


if __name__ == "__main__":
    main()
