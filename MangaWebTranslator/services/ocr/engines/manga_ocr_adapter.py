"""Adapter for `kha-white/manga-ocr`.

Provides a thin lazy-loading wrapper around `MangaOcr` so importing this
module won't fail if `manga-ocr` / `torch` are not installed. The adapter
exposes `available()` and `recognize(pil_image, lang, device)`.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)


class MangaOcrAdapter:
    """Lazy wrapper around MangaOcr.

    Usage:
        adapter = MangaOcrAdapter()
        if adapter.available():
            out = adapter.recognize(pil_img, lang='jpn', device='cpu')
    """

    def __init__(self):
        self._impl = None

    def available(self) -> bool:
        if self._impl is not None:
            return True
        try:
            # Import only when queried; may raise ImportError if not installed.
            # Note: Top-level import of torch has been removed; use lazy import inside methods only.
            from manga_ocr import MangaOcr  # type: ignore
            self._MangaOcr = MangaOcr
            return True
        except ImportError as exc:
            logger.debug("manga_ocr import failed: %s", exc, exc_info=True)
            return False
        except Exception as exc:
            # Be conservative: some environments may raise non-ImportError issues on import
            logger.warning("manga_ocr import raised unexpected error: %s", exc)
            return False

    def _ensure_impl(self):
        if self._impl is None:
            try:
                MangaOcr = getattr(self, '_MangaOcr', None)
                if MangaOcr is None:
                    from manga_ocr import MangaOcr  # type: ignore
                    MangaOcr = MangaOcr
                self._impl = MangaOcr()
            except Exception as e:
                logger.exception('Failed initializing MangaOcr: %s', e)
                raise

    def recognize(self, pil_image, lang: str = 'jpn') -> Dict:
        """Recognize text from a PIL `Image`.

        Returns a dict: { 'text': str, 'blocks': [ {text,left,top,width,height,conf}, ... ] }
        If `manga-ocr` does not provide per-box bboxes/confidences, a single
        full-image block is returned with `conf` set to -1.
        """
        if not self.available():
            raise RuntimeError('manga-ocr not available')
        self._ensure_impl()
        try:
            # Typical usage: `mocr = MangaOcr(); res = mocr(pil_image)`
            res = self._impl(pil_image)
            # res may be a string or structured; be permissive.
            if isinstance(res, str):
                text = res
                blocks = []
            elif isinstance(res, (list, tuple)):
                # Try to flatten textual parts
                texts = []
                blocks = []
                for item in res:
                    if isinstance(item, str):
                        texts.append(item)
                    elif isinstance(item, dict):
                        t = item.get('text') or item.get('label') or ''
                        texts.append(t)
                        # attempt to extract bbox
                        bbox = item.get('box') or item.get('bbox')
                        if bbox and len(bbox) >= 4:
                            left, top, right, bottom = bbox[:4]
                            blocks.append({'text': t, 'left': left, 'top': top, 'width': right - left, 'height': bottom - top, 'conf': item.get('conf', -1)})
                text = '\n'.join([t for t in texts if t])
            elif isinstance(res, dict):
                text = res.get('text', '')
                blocks = []
                for item in res.get('blocks', []) or []:
                    t = item.get('text', '')
                    bbox = item.get('box') or item.get('bbox')
                    if bbox and len(bbox) >= 4:
                        left, top, right, bottom = bbox[:4]
                        blocks.append({'text': t, 'left': left, 'top': top, 'width': right-left, 'height': bottom-top, 'conf': item.get('conf', -1)})
            else:
                text = str(res)
                blocks = []

            # If no blocks, create a single full-image block
            if not blocks:
                w, h = pil_image.size
                blocks = [{'text': text, 'left': 0, 'top': 0, 'width': w, 'height': h, 'conf': -1}]
            return {'text': text, 'blocks': blocks}
        except Exception as e:
            logger.exception('manga-ocr recognition failed: %s', e)
            raise
