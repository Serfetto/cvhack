"""Build a single uploadable Jupyter bundle from the local pose model."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parents[3]
SOURCE_FILES = [
    "backend/ml/worker/linq_worker.py",
    "backend/server/services/inference/backends/__init__.py",
    "backend/server/services/inference/backends/base.py",
    "backend/server/services/inference/ml_runtime/__init__.py",
    "backend/server/services/inference/ml_runtime/pose.py",
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("model_dir", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    meta = json.loads((args.model_dir / "meta.json").read_text(encoding="utf-8"))
    names = ["meta.json", meta["files"]["onnx_tail"], meta["files"]["tpu"]]
    files = [(ROOT / name, name) for name in SOURCE_FILES]
    files += [(args.model_dir / name, f"data/models/pose/{name}") for name in names]
    missing = [str(source) for source, _ in files if not source.is_file()]
    if missing:
        raise FileNotFoundError(f"Cannot build Jupyter bundle; missing: {missing}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(args.output, "w", compression=ZIP_DEFLATED) as bundle:
        for source, target in files:
            bundle.write(source, target)
    print(f"{args.output} ({args.output.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
