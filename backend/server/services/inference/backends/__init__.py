"""Фабрика бэкендов. Модули onnx.py и pytpu.py пишет ML; каждый экспортирует класс с полем name
и методами load/infer (backends/base.py). Импорт ленивый: на машине без pytpu onnx-бэкенд работает."""

from __future__ import annotations

import importlib

from backends.base import Backend, ModelSpec  # noqa: F401

_MODULES = {"onnx": ("backends.onnx", "OnnxBackend"), "pytpu": ("backends.pytpu", "PyTpuBackend")}


def create_backend(name: str, **kwargs) -> Backend:
    if name not in _MODULES:
        raise ValueError(f"Неизвестный бэкенд {name!r}. Есть: {', '.join(_MODULES)}")
    module, cls = _MODULES[name]
    return getattr(importlib.import_module(module), cls)(**kwargs)
