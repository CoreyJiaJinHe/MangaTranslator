"""Service registry (skeleton).
Simple factory mapping; no dynamic loading yet.
"""
from __future__ import annotations
from typing import Dict, Callable, Any

class Registry:
    def __init__(self) -> None:
        self._factories: Dict[str, Callable[[], Any]] = {}

    def register(self, name: str, factory: Callable[[], Any]) -> None:
        if name in self._factories:
            raise ValueError(f"Factory already registered for {name}")
        self._factories[name] = factory

    def create(self, name: str) -> Any:
        if name not in self._factories:
            raise KeyError(f"No factory registered for {name}")
        return self._factories[name]()

    def list(self) -> Dict[str, Callable[[], Any]]:
        return dict(self._factories)

# Global registries (placeholders for future phases)
OCR_REGISTRY = Registry()
SEGMENTATION_REGISTRY = Registry()
TRANSLATION_REGISTRY = Registry()
DICTIONARY_REGISTRY = Registry()
SIMILARITY_REGISTRY = Registry()
CAPTURE_REGISTRY = Registry()
DATA_PREP_REGISTRY = Registry()
