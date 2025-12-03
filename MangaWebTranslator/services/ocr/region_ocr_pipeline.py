from __future__ import annotations

import logging
import os
from typing import List, Tuple

from PIL import Image, ImageDraw

from engines.comic_text_detector_adapter import ComicTextDetectorAdapter, TextRegion
from engines.manga_ocr_adapter import MangaOcrAdapter

logger = logging.getLogger(__name__)


def _inter_area(a: TextRegion, b: TextRegion) -> int:
    ax1, ay1, ax2, ay2 = a.left, a.top, a.left + a.width, a.top + a.height
    bx1, by1, bx2, by2 = b.left, b.top, b.left + b.width, b.top + b.height
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    if ix2 <= ix1 or iy2 <= iy1:
        return 0
    return (ix2 - ix1) * (iy2 - iy1)


def suppress_nested_boxes(regions: List[TextRegion], subsume_ratio: float = 0.8) -> List[TextRegion]:
    """Drop regions that are largely contained inside bigger boxes (IOA>=subsume_ratio)."""
    kept: List[TextRegion] = []
    for i, small in enumerate(regions):
        sa = small.width * small.height
        if sa <= 0:
            continue
        contained = False
        for j, big in enumerate(regions):
            if i == j:
                continue
            ba = big.width * big.height
            if ba <= sa:
                continue
            ia = _inter_area(small, big)
            if ia / sa >= subsume_ratio:
                contained = True
                break
        if not contained:
            kept.append(small)
    return kept


def pad_crop(img: Image.Image, r: TextRegion, pad_frac: float = 0.06) -> Image.Image:
    W, H = img.size
    pad = int(min(r.width, r.height) * pad_frac)
    x1 = max(0, r.left - pad)
    y1 = max(0, r.top - pad)
    x2 = min(W, r.left + r.width + pad)
    y2 = min(H, r.top + r.height + pad)
    return img.crop((x1, y1, x2, y2)).convert("RGB")


def detect_text_regions(img: Image.Image) -> List[TextRegion]:
    device = os.getenv("COMIC_TEXT_DEVICE", "cpu")
    models_dir = os.getenv("COMIC_TEXT_MODELS_DIR", "MangaWebTranslator/services/ocr/models")
    det = ComicTextDetectorAdapter(device=device, models_dir=models_dir)
    regions = det.detect_regions(img)
    regions = suppress_nested_boxes(regions, subsume_ratio=0.8)
    regions.sort(key=lambda r: (r.top, r.left))
    return regions


def ocr_text_regions(img: Image.Image) -> List[Tuple[TextRegion, str]]:
    mocr = MangaOcrAdapter()
    if not mocr.available():
        raise RuntimeError(
            "manga-ocr not available. Install it and CPU torch:\n"
            "  python -m pip install --index-url https://download.pytorch.org/whl/cpu torch torchvision\n"
            "  pip install manga-ocr"
        )
    pairs: List[Tuple[TextRegion, str]] = []
    for r in detect_text_regions(img):
        crop = pad_crop(img, r, pad_frac=0.06)
        out = mocr.recognize(crop, lang="jpn")
        text = out.get("text", "") if isinstance(out, dict) else ""
        pairs.append((r, text))
    return pairs


def draw_regions_overlay(img: Image.Image, regions: List[TextRegion]) -> Image.Image:
    over = img.convert("RGB").copy()
    d = ImageDraw.Draw(over)
    for r in regions:
        d.rectangle((r.left, r.top, r.left + r.width, r.top + r.height), outline="red", width=2)
    return over
