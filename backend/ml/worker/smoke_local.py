"""Exercise the Jupyter worker with the ONNX head while the VPN is unavailable."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import onnxruntime as ort

from linq_worker import LinqPoseWorker, ModelSpec


class CpuHeadWorker(LinqPoseWorker):
    def __init__(self, spec: ModelSpec, program: Path):
        super().__init__(spec, program, "unused", "unused")
        options = ort.SessionOptions()
        options.intra_op_num_threads = 1
        options.log_severity_level = 3
        self.session = ort.InferenceSession(
            str(spec.path("onnx_head")), sess_options=options,
            providers=["CPUExecutionProvider"],
        )

    def infer_tpu(self, tensor):
        values = self.session.run(self.spec.output_names, {self.spec.input_name: tensor})
        return dict(zip(self.spec.output_names, values, strict=True))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("model_dir", type=Path)
    parser.add_argument("image", type=Path)
    args = parser.parse_args()
    spec = ModelSpec.load(args.model_dir)
    worker = CpuHeadWorker(spec, spec.path("tpu"))
    result = worker.detect(args.image.read_bytes())
    print(json.dumps({"persons": len(result["persons"]), "scores":
                      [round(person["score"], 3) for person in result["persons"]],
                      "latency_ms": result["latency_ms"]}, indent=2))
    if not result["persons"]:
        raise AssertionError("No person detected in the smoke image")


if __name__ == "__main__":
    main()
