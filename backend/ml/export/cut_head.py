"""Split a YOLOv8 export (pose or detect) before DFL and keypoint decode.

    python backend/ml/export/cut_head.py data/models/pose/yolov8n-pose.onnx --out-dir data/models/pose
    python backend/ml/export/cut_head.py data/models/objects/yolov8s-objects.onnx --out-dir data/models/objects --name objects

Task, class names and version come from the ONNX metadata that Ultralytics writes on export.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path

import onnx
from tpu_framework import get_sub_model


# SDK's published seven tensor names refer to a different Ultralytics export.
# In Ultralytics 8.4.0 the head branches join here (box distribution, class
# logits, keypoints for pose); all decode/formatting runs in the ONNX CPU tail.
CUT = {
    "pose": ["/model.22/Concat_output_0", "/model.22/Concat_1_output_0", "/model.22/Concat_2_output_0"],
    "detect": ["/model.22/Concat_output_0", "/model.22/Concat_1_output_0"],
}


def prune(model: onnx.ModelProto) -> onnx.ModelProto:
    """get_sub_model keeps every initializer of the source graph; the tail needs only a few of them."""
    used = {name for node in model.graph.node for name in node.input}
    keep = [init for init in model.graph.initializer if init.name in used]
    del model.graph.initializer[:]
    model.graph.initializer.extend(keep)
    return model


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("model", type=Path)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--name", help="model name in data/models and in the pipeline; default: pose | objects")
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    model = onnx.load(args.model)
    props = {p.key: p.value for p in model.metadata_props}
    task = props.get("task", "pose")
    name = args.name or ("pose" if task == "pose" else "objects")
    cut = CUT[task]
    node_outputs = {out for node in model.graph.node for out in node.output}
    missing = set(cut) - node_outputs
    if missing:
        raise ValueError(f"These cut tensors are absent in the ONNX graph: {sorted(missing)}")
    inputs = [value.name for value in model.graph.input]
    outputs = [value.name for value in model.graph.output]
    if len(inputs) != 1 or len(outputs) != 1:
        raise ValueError(f"Expected one model input/output, got {inputs} / {outputs}")
    head = prune(get_sub_model(model=model, ordered_input_names=inputs, ordered_output_names=cut))
    tail = prune(get_sub_model(model=model, ordered_input_names=cut, ordered_output_names=outputs))
    onnx.checker.check_model(head)
    onnx.checker.check_model(tail)
    onnx.save(head, args.out_dir / f"{name}_head.onnx")
    onnx.save(tail, args.out_dir / f"{name}_tail.onnx")
    classes = ast.literal_eval(props["names"]) if "names" in props else {0: "person"}
    digest = hashlib.sha256(args.model.read_bytes()).hexdigest()
    meta = {
        "name": name, "task": task, "version": f"{args.model.stem}-v{props.get('version', '8.4.0')}",
        "input_name": inputs[0], "input_shape": [1, 3, 640, 640],
        "output_names": cut, "classes": [classes[i] for i in sorted(classes)],
        "files": {"onnx": args.model.name, "onnx_head": f"{name}_head.onnx", "onnx_tail": f"{name}_tail.onnx"},
        "source_sha256": digest, "preprocessing": "RGB letterbox /255", "sdk": "2026.9.45",
    }
    (args.out_dir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"task": task, "inputs": inputs, "outputs": outputs, "cut_outputs": cut}, indent=2))


if __name__ == "__main__":
    main()
