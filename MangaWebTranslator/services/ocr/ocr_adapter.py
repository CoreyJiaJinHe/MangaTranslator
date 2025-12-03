"""Factory and adapter-facing interface for OCR backends.

This module implements `create_ocr(cfg=None)` which prefers an environment
variable `OCR_BACKEND` then falls back to `cfg['ocr']['backend']` if provided.
Supported backend: `manga-ocr` via `engines.manga_ocr_adapter.MangaOcrAdapter`.
If no backend is available, returns `ocr_stub.StubOCR`.
"""
from __future__ import annotations

import os
import logging
from typing import Any, Dict

from . import ocr_preprocess
from .ocr_stub import StubOCR

logger = logging.getLogger(__name__)


def _select_backend_name(cfg: Dict | None) -> str | None:
    # Env var takes precedence
    be = os.getenv('OCR_BACKEND')
    if be:
        return be.strip().lower()
    try:
        if cfg and isinstance(cfg, dict):
            be = cfg.get('ocr', {}).get('backend')
            if be:
                return str(be).strip().lower()
    except Exception:
        pass
    return None


def create_ocr(cfg: Dict | None = None):
    """Create an OCR object implementing `extract_text(image, **kwargs)` and
    `extract_blocks(image, **kwargs)`.

    `image` may be a PyQt6 `QImage` or a PIL `Image`; conversion is handled
    automatically.
    """
    backend = _select_backend_name(cfg)
    device = os.getenv('MANGA_OCR_DEVICE', 'cpu')

    # Behavior when backend explicitly requested
    if backend:
        name = backend
        if name in ('manga-ocr', 'mangaocr', 'manga'):
            try:
                from .engines.manga_ocr_adapter import MangaOcrAdapter
                adapter = MangaOcrAdapter()
                if not adapter.available():
                    msg = (
                        "Requested OCR backend 'manga-ocr' is not available. "
                        )
                    logger.error(msg)
                    raise RuntimeError(msg)

                logger.info('Using manga-ocr backend (device=%s)', device)

                class _Wrapper:
                    def extract_text(self, image, **kwargs) -> str:
                        pil = ocr_preprocess.qimage_to_pil(image) if not hasattr(image, 'size') else image
                        out = adapter.recognize(pil, lang=kwargs.get('lang', 'jpn'))
                        return out.get('text', '')

                    def extract_blocks(self, image, **kwargs) -> list:
                        pil = ocr_preprocess.qimage_to_pil(image) if not hasattr(image, 'size') else image
                        out = adapter.recognize(pil, lang=kwargs.get('lang', 'jpn'))
                        return out.get('blocks', [])

                return _Wrapper()
            except RuntimeError:
                raise
            except Exception:
                logger.exception('Failed initializing manga-ocr adapter')
                raise
        else:
            msg = f"Unknown OCR backend '{backend}'. Supported: manga-ocr"
            logger.error(msg)
            raise RuntimeError(msg)

    # No explicit backend: try manga-ocr; otherwise stub
    try:
        from .engines.manga_ocr_adapter import MangaOcrAdapter
        adapter = MangaOcrAdapter()
        if adapter.available():
            logger.info('Using manga-ocr backend (device=%s)', device)

            class _Wrapper:
                def extract_text(self, image, **kwargs) -> str:
                    pil = ocr_preprocess.qimage_to_pil(image) if not hasattr(image, 'size') else image
                    out = adapter.recognize(pil, lang=kwargs.get('lang', 'jpn'))
                    return out.get('text', '')

                def extract_blocks(self, image, **kwargs) -> list:
                    pil = ocr_preprocess.qimage_to_pil(image) if not hasattr(image, 'size') else image
                    out = adapter.recognize(pil, lang=kwargs.get('lang', 'jpn'))
                    return out.get('blocks', [])

            return _Wrapper()
    except Exception:
        # Soft-fail: we'll fall back to stub
        logger.debug('manga-ocr backend not available by default', exc_info=True)

    logger.warning('No OCR backend available. Falling back to stub.')
    return StubOCR()
