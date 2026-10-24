"""Exercise the Jupyter worker with the ONNX head while the VPN is unavailable."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import onnxruntime as ort

from linq_worker import LinqWorker, ModelSpec


class CpuHeadWorker(LinqWorker):
    def __init__(self, spec: ModelSpec, program: Path, *more: ModelSpec):
        specs = [spec, *more]
        super().__init__([(s, program if s is spec else s.path("tpu")) for s in specs], "unused", "unused")
        options = ort.SessionOptions()
        options.intra_op_num_threads = 1
        options.log_severity_level = 3
        self.sessions = {s.name: ort.InferenceSession(str(s.path("onnx_head")), sess_options=options,
                                                      providers=["CPUExecutionProvider"]) for s in specs}

    def infer_tpu(self, tensors):
        result = {}
        for spec, _ in self.models:
            values = self.sessions[spec.name].run(spec.output_names, {spec.input_name: tensors[spec.name]})
            result[spec.name] = dict(zip(spec.output_names, values, strict=True))
        return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("model_dir", type=Path, nargs="+", help="pose first, then optional objects")
    parser.add_argument("image", type=Path)
    args = parser.parse_args()
    specs = [ModelSpec.load(d) for d in args.model_dir]
    worker = CpuHeadWorker(specs[0], specs[0].path("tpu"), *specs[1:])
    result = worker.detect(args.image.read_bytes())
    print(json.dumps({"persons": len(result["persons"]), "scores":
                      [round(person["score"], 3) for person in result["persons"]],
                      "objects": [(o["cls"], round(o["score"], 3)) for o in result["objects"]],
                      "latency_ms": result["latency_ms"]}, indent=2))
    if not result["persons"]:
        raise AssertionError("No person detected in the smoke image")


if __name__ == "__main__":
    main()
