"""Fallback OCR implementation used when no real backend is available.

This stub returns empty results and logs a clear warning so the application
can remain functional (UI won't crash) on machines without heavy ML deps.
"""
from __future__ import annotations

import logging
from typing import List

logger = logging.getLogger(__name__)


class StubOCR:
    def __init__(self):
        logger.warning('Using OCR stub: no OCR backend available. Install manga-ocr and torch to enable real OCR.')

    def extract_text(self, image, **kwargs) -> str:
        return ''

    def extract_blocks(self, image, **kwargs) -> List[dict]:
        # Return an empty list so UI overlays remain silent
        return []
