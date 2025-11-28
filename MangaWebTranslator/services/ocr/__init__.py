"""OCR package: adapter factory and helpers.

This package provides a `create_ocr(cfg=None)` factory (in `ocr_adapter`) and
small preprocessing helpers. The package keeps a lightweight stub fallback so
the application remains importable when heavy dependencies (torch/models)
are not present.
"""
from .ocr_adapter import create_ocr

__all__ = ["create_ocr"]
"""OCR service package (skeleton)."""