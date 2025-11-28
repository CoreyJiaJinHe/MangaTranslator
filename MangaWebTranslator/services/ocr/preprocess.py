"""Small image conversion and preprocessing helpers used by OCR adapters.

Functions here are intentionally minimal and dependency-light so importing
the package doesn't require heavy ML libraries.
"""
from __future__ import annotations

import io
import logging
from typing import Iterable, List

from PIL import Image, ImageOps

logger = logging.getLogger(__name__)


def qimage_to_pil(qimage) -> Image.Image:
    """Convert a PyQt6 `QImage` to a PIL `Image`.

    If the passed object is already a PIL Image, it is returned unchanged.
    """
    # Defer import of PyQt types to avoid hard dependency at import time.
    try:
        from PyQt6.QtGui import QImage
    except Exception:
        QImage = None

    if hasattr(qimage, 'tobytes') and hasattr(qimage, 'format') and QImage is not None and isinstance(qimage, QImage):
        # Convert via PNG bytes to preserve alpha and color space reliably.
        buf = qimage.bits().asstring(qimage.byteCount())
        fmt = qimage.format()  # noqa: F841 - keep for debugging
        try:
            img = Image.frombuffer('RGBA', (qimage.width(), qimage.height()), buf, 'raw', 'BGRA')
            return img.convert('RGB')
        except Exception:
            # Fallback to saving to bytes via QImage.save if available
            try:
                b = io.BytesIO()
                qimage.save(b, 'PNG')
                b.seek(0)
                return Image.open(b).convert('RGB')
            except Exception:
                logger.exception('Failed converting QImage to PIL.Image')
                raise

    # Already a PIL Image
    if isinstance(qimage, Image.Image):
        return qimage

    raise TypeError('Expected QImage or PIL.Image')


def generate_variants(img: Image.Image) -> List[Image.Image]:
    """Yield a small set of preprocessing variants for OCR.

    Keep this list limited to avoid heavy CPU usage. Each adapter may choose
    which variants to run.
    """
    variants: List[Image.Image] = []
    try:
        variants.append(img)
        # grayscale
        variants.append(ImageOps.grayscale(img).convert('RGB'))
        # contrast stretch (simple autocontrast)
        variants.append(ImageOps.autocontrast(img))
    except Exception:
        logger.exception('Failed generating preprocessing variants')
    # Ensure unique objects
    unique: List[Image.Image] = []
    seen = set()
    for v in variants:
        try:
            key = (v.width, v.height, v.mode)
        except Exception:
            key = id(v)
        if key not in seen:
            seen.add(key)
            unique.append(v)
    return unique
