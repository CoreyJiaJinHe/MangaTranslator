"""
Quick demo to visualize text region detection and cropping.

This version uses fixed variables (no CLI args):
- Input image: `_scraped_images/1.jpg`
- Output directory: `_ocr_debug/`
- Threshold, pad, and blur are set via variables below.
- Overlay window show is enabled by default.

This script:
- Loads the image with PIL
- Runs detect_text_regions() to get rectangles
- Draws rectangles on the original image and saves an overlay
- Runs crop_regions() and saves each crop image to the output folder
"""
from __future__ import annotations

import os
import sys
from typing import List, Dict

from PIL import Image, ImageDraw

# Attempt import; if package path isn't on sys.path, add repo root
try:
    from MangaWebTranslator.services.ocr.ocr_preprocess import (
        detect_text_regions,
        crop_regions,
    )
except Exception:
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
    from MangaWebTranslator.services.ocr.ocr_preprocess import (
        detect_text_regions,
        crop_regions,
    )


def _draw_overlay(base_img: Image.Image, rects: List[Dict[str, int]]) -> Image.Image:
    """Draw red rectangles on a copy of the image and return it.

    Rects are expected as dicts: {left, top, width, height} in image-space coords.
    """
    overlay = base_img.convert("RGB").copy()
    draw = ImageDraw.Draw(overlay)
    for r in rects:
        try:
            l = int(r.get("left", 0))
            t = int(r.get("top", 0))
            w = int(r.get("width", 0))
            h = int(r.get("height", 0))
            draw.rectangle([(l, t), (l + w, t + h)], outline=(255, 0, 0), width=2)
        except Exception:
            continue
    return overlay


def main() -> int:
    # Fixed variables per request (no CLI args)
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    image_path = os.path.join(repo_root, "_scraped_images", "1.jpg")
    out_dir = os.path.join(repo_root, "_ocr_debug")
    threshold_value = 240  # --threshold equivalent
    pad_pixels = 2         # --pad equivalent
    blur_enabled = False   # --blur equivalent
    show_overlay = True    # --show default on

    if not os.path.exists(image_path):
        print(f"Image not found: {image_path}")
        return 2

    os.makedirs(out_dir, exist_ok=True)

    # Load image
    img = Image.open(image_path).convert("RGB")

    # Detect rectangles
    rects = detect_text_regions(
        img,
        blur=blur_enabled,
        fixed_threshold=threshold_value,
        subsume_ratio_primary=0.8,
        kernel_trials=[(3, 5, 1), (5, 10, 2), (5, 15, 4), (7, 7, 2)],
    )
    print(f"Detected rectangles: {len(rects)}")
    if rects:
        # Save overlay
        overlay = _draw_overlay(img, rects)
        overlay_path = os.path.join(out_dir, "overlay.png")
        try:
            overlay.save(overlay_path)
            print(f"Saved overlay: {overlay_path}")
        except Exception as e:
            print(f"Failed to save overlay: {e}")
        # Show overlay by default
        if show_overlay:
            try:
                overlay.show()
            except Exception:
                pass

        # Save crops
        crops = crop_regions(img, rects, pad=pad_pixels)
        print(f"Saved {len(crops)} crops:")
        for i, c in enumerate(crops):
            cp = os.path.join(out_dir, f"crop_{i:03}.png")
            try:
                c.save(cp)
                print(f"  - {cp}")
            except Exception as e:
                print(f"  ! Failed to save crop {i}: {e}")
    else:
        print("No rectangles detected.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
