"""Export the official YOLOv8n pose checkpoint with a static 640px input."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from ultralytics import YOLO


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("weights", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    exported = Path(YOLO(str(args.weights)).export(
        format="onnx", imgsz=640, batch=1, opset=12, dynamic=False,
        simplify=False, nms=False,
    ))
    if exported.resolve() != args.output.resolve():
        shutil.copy2(exported, args.output)
    print(args.output)


if __name__ == "__main__":
    main()
