"""
OpenCV-based text region detector adapter (no Torch).

Detects regions via thresholding and contours to avoid ML dependencies.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)


@dataclass
class TextRegion:
    left: int
    top: int
    width: int
    height: int
    polygon: Optional[List[Tuple[int, int]]] = None
    score: Optional[float] = None


class ComicTextDetectorAdapter:
    def __init__(self) -> None:
        pass

    def available(self) -> bool:
        return True

    def detect_regions(self, image: Image.Image) -> List[TextRegion]:
        img_np = np.array(image.convert("RGB"))
        gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)

        fixed_threshold = 240
        _, th_fixed = cv2.threshold(blurred, fixed_threshold, 255, cv2.THRESH_BINARY)
        inverse_threshold = 300 - fixed_threshold
        _, th_fixed_inv = cv2.threshold(blurred, inverse_threshold, 255, cv2.THRESH_BINARY_INV)

        def collect_rects(bin_img: np.ndarray) -> List[Tuple[int, int, int, int]]:
            bi = (bin_img > 0).astype(np.uint8) * 255
            contours_info = cv2.findContours(bi, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if len(contours_info) == 3:
                _, contours, _ = contours_info
            else:
                contours, _ = contours_info
            rects: List[Tuple[int, int, int, int]] = []
            for c in contours:
                x, y, w, h = cv2.boundingRect(c)
                rects.append((x, y, w, h))
            return rects

        rects_fixed = collect_rects(th_fixed)
        rects_inv = collect_rects(th_fixed_inv)
        flat_rects = rects_fixed + rects_inv

        def intersection_area(r1, r2):
            x1, y1, w1, h1 = r1
            x2, y2, w2, h2 = r2
            ix1 = max(x1, x2)
            iy1 = max(y1, y2)
            ix2 = min(x1 + w1, x2 + w2)
            iy2 = min(y1 + h1, y2 + h2)
            if ix2 <= ix1 or iy2 <= iy1:
                return 0
            return (ix2 - ix1) * (iy2 - iy1)

        final_rects: List[Tuple[int, int, int, int]] = []
        subsume_ratio = 0.8
        for i, (x, y, w, h) in enumerate(flat_rects):
            if w < 30 or h < 30:
                continue
            if w > 600 or h > 600:
                continue
            if w * h > 250000:
                continue
            small = (x, y, w, h)
            small_area = w * h
            contained = False
            for j, (X, Y, W, H) in enumerate(flat_rects):
                if i == j:
                    continue
                if (W * H) <= small_area:
                    continue
                if small_area > 0 and (intersection_area(small, (X, Y, W, H)) / small_area) >= subsume_ratio:
                    contained = True
                    break
            if not contained:
                final_rects.append(small)

        boxes: List[TextRegion] = [
            TextRegion(left=x, top=y, width=w, height=h)
            for (x, y, w, h) in final_rects
        ]
        boxes.sort(key=lambda r: (r.top, r.left))
        return boxes