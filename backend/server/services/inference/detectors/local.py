"""LocalDetector: ml_runtime (пре/постпроцессинг от ML) + бэкенд onnx или pytpu на этой машине.

Контракт ml_runtime (пишет ML; если сигнатуры другие — правится только этот файл):

    preprocess(image_bgr: np.ndarray, spec: ModelSpec) -> tuple[np.ndarray, Any]
        # тензор [1, 3, H, W] float32 и метаданные letterbox для обратного масштабирования
    postprocess_pose(outputs: dict[str, np.ndarray], meta, spec: ModelSpec, conf: float, iou: float) -> list[dict]
        # [{"bbox": [x1, y1, x2, y2], "score": 0.9, "kpts": [[x, y, conf] × 17]}], координаты 0..1 исходного кадра
    postprocess_detect(outputs: dict[str, np.ndarray], meta, spec: ModelSpec, conf: float, iou: float) -> list[dict]
        # [{"cls": "forklift", "bbox": [...], "score": 0.8}]

Модели лежат в MODELS_DIR/<name>/ с meta.json (backends/base.py: ModelSpec).
"""

from __future__ import annotations

import importlib
import time
from pathlib import Path

import cv2
import numpy as np

from backends import ModelSpec, create_backend
from common.messages import Obj, Person

from .base import DetectResult


class LocalDetector:
    def __init__(self, backend: str, models_dir: str, models: list[str], conf: float = 0.35, iou: float = 0.5):
        self.name = backend
        self.conf, self.iou = conf, iou
        self.rt = importlib.import_module("ml_runtime")
        self.backend = create_backend(backend)
        self.specs: list[ModelSpec] = []
        for m in models:
            d = Path(models_dir) / m
            if not (d / "meta.json").exists():
                raise FileNotFoundError(f"Нет {d / 'meta.json'}: модель «{m}» не подготовлена")
            spec = ModelSpec.load(d)
            self.backend.load(spec)
            self.specs.append(spec)

    def detect(self, jpeg: bytes, camera_id: str | None = None, ts: float | None = None) -> DetectResult:
        t0 = time.perf_counter()
        img = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("Не удалось декодировать JPEG")
        lat = {"decode": (time.perf_counter() - t0) * 1000, "pre": 0.0, "infer": 0.0, "post": 0.0}
        res = DetectResult(backend=self.name)
        for spec in self.specs:
            a = time.perf_counter()
            tensor, meta = self.rt.preprocess(img, spec)
            b = time.perf_counter()
            outputs = self.backend.infer(spec.name, {spec.input_name: tensor})
            c = time.perf_counter()
            if spec.task == "pose":
                res.persons += [Person.model_validate(p) for p in self.rt.postprocess_pose(outputs, meta, spec, self.conf, self.iou)]
            else:
                res.objects += [Obj.model_validate(o) for o in self.rt.postprocess_detect(outputs, meta, spec, self.conf, self.iou)]
            d = time.perf_counter()
            lat["pre"] += (b - a) * 1000
            lat["infer"] += (c - b) * 1000
            lat["post"] += (d - c) * 1000
            res.models[spec.name] = f"{spec.name}@{spec.version or 'dev'}-{self.name}"
        lat["total"] = (time.perf_counter() - t0) * 1000
        res.latency_ms = {k: round(v, 3) for k, v in lat.items()}
        return res

    def info(self) -> dict:
        return {
            "backend": self.name,
            "models": [
                {"name": s.name, "task": s.task, "version": s.version, "input": s.input_shape,
                 "program": s.files.get("tpu" if self.name == "pytpu" else "onnx"), "classes": s.classes,
                 "preset": s.meta.get("preset"), "accuracy": s.meta.get("accuracy")}
                for s in self.specs
            ],
        }
