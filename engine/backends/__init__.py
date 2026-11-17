"""Backend registry. Backends are imported lazily so the app starts instantly
(PyTorch is only loaded when an AI model is actually used)."""

from __future__ import annotations

import importlib

from .base import Backend, Cancelled, Report  # noqa: F401

_BACKENDS = {
    "resize": "engine.backends.resize:ResizeBackend",
    "spandrel": "engine.backends.spandrel_backend:SpandrelBackend",
    "seedvr2": "engine.backends.seedvr2:SeedVR2Backend",
}


def backend_class(name: str) -> type[Backend]:
    try:
        target = _BACKENDS[name]
    except KeyError:
        raise ValueError(f"Unknown backend '{name}'. Known: {', '.join(_BACKENDS)}") from None
    module_name, cls_name = target.split(":")
    return getattr(importlib.import_module(module_name), cls_name)
