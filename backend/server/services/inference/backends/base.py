"""Контракт бэкенда инференса (ARCHITECTURE §5.6). Реализации пишет ML: onnx.py, pytpu.py.

Бэкенд работает с тензорами: пре- и постпроцессинг общие (ml_runtime), поэтому выходы CPU и TPU
сравниваются один в один.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import numpy as np


@dataclass
class ModelSpec:
    """Описание модели из data/models/<name>/meta.json (его пишет ML-пайплайн компиляции)."""

    name: str                       # "pose" | "objects"
    task: str                       # "pose" | "detect"
    version: str = ""
    dir: Path = Path(".")
    input_name: str = "images"
    input_shape: list[int] = field(default_factory=lambda: [1, 3, 640, 640])
    output_names: list[str] = field(default_factory=list)
    classes: list[str] = field(default_factory=list)
    files: dict[str, str] = field(default_factory=dict)   # {"onnx": "model.onnx", "tpu": "model_b1_o5_h1m.tpu"}
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def imgsz(self) -> int:
        return int(self.input_shape[-1])

    def path(self, kind: str) -> Path:
        f = self.files.get(kind)
        if not f:
            raise FileNotFoundError(f"В meta.json модели {self.name} нет файла для «{kind}»")
        return self.dir / f

    @classmethod
    def load(cls, model_dir: str | Path) -> ModelSpec:
        d = Path(model_dir)
        meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        files = dict(meta.get("files", {}))
        for kind, ext in (("onnx", ".onnx"), ("tpu", ".tpu")):
            if kind not in files:
                found = sorted(d.glob(f"*{ext}"))
                if found:
                    files[kind] = found[0].name
        return cls(
            name=meta.get("name", d.name), task=meta.get("task", "pose" if "pose" in d.name else "detect"),
            version=str(meta.get("version", "")), dir=d, input_name=meta.get("input_name", "images"),
            input_shape=list(meta.get("input_shape", [1, 3, 640, 640])), output_names=list(meta.get("output_names", [])),
            classes=list(meta.get("classes", [])), files=files, meta=meta,
        )


class Backend(Protocol):
    name: str  # "pytpu" | "onnx"

    def load(self, model: ModelSpec) -> None: ...

    def infer(self, model: str, inputs: dict[str, np.ndarray]) -> dict[str, np.ndarray]: ...
