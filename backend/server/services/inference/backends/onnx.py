"""ONNX Runtime backend for local CPU inference and TPU result comparison."""

from __future__ import annotations

import numpy as np
import onnxruntime as ort

from .base import ModelSpec


class OnnxBackend:
    name = "onnx"

    def __init__(self) -> None:
        self.sessions: dict[str, ort.InferenceSession] = {}

    def load(self, model: ModelSpec) -> None:
        options = ort.SessionOptions()
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        self.sessions[model.name] = ort.InferenceSession(
            str(model.path("onnx")), sess_options=options,
            providers=["CPUExecutionProvider"],
        )

    def infer(self, model: str, inputs: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
        session = self.sessions[model]
        names = [output.name for output in session.get_outputs()]
        return dict(zip(names, session.run(names, inputs), strict=True))
