"""Small image conversion and preprocessing helpers used by OCR adapters.

Functions here are intentionally minimal and dependency-light so importing
the package doesn't require heavy ML libraries.
"""
from __future__ import annotations

import io
import logging
from typing import Iterable, List
import os
from pathlib import Path
from PIL import Image
from PIL import Image, ImageOps
import cv2
import numpy as np

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


def preprocess_for_ocr(img: Image.Image) -> Image.Image:
    img_np = np.array(img.convert("RGB"))
    gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)
    print("gray dtype/shape/min/max/mean:", gray.dtype, gray.shape, gray.min(), gray.max(), float(gray.mean()))
    
    # 2) Gaussian blur (reduce noise)
    blurred = None
    override = True
    if override:
        blurred = gray
        print("Blur step skipped (disable_blur=True)")
    else:
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        print("Blurred applied (disable_blur=False or unset)")
        print("blurred min/max/mean:", blurred.min(), blurred.max(), float(blurred.mean()))

    # 3) Fixed threshold (example 180)
    fixed_threshold=240
    _, th_fixed = cv2.threshold(blurred, fixed_threshold, 255, cv2.THRESH_BINARY)
    print("Fixed thresh nonzero:", np.count_nonzero(th_fixed))

    # 4) Inverse fixed (useful if text is dark on light bg)
    inverse_threshold=300-fixed_threshold
    _, th_fixed_inv = cv2.threshold(blurred, inverse_threshold, 255, cv2.THRESH_BINARY_INV)
    print("Fixed inv nonzero:", np.count_nonzero(th_fixed_inv))
    
    
    """Run contour detection and filtering across kernel trials.

    Returns a list of lists, where each inner list contains the filtered
    rectangles `(x, y, w, h)` for a specific kernel setting. The first
    entry corresponds to no morphology `(1,1,0)`, followed by each trial.

    This enables downstream debug overlays to reuse the already computed
    rectangles without recomputing step five.
    """
    def contours_and_overlay(bin_img, name_prefix, kernel_sizes_iters=None):
        """Find contours on bin_img, save overlay with boxes, print counts.
        kernel_sizes_iters: iterable of (kernel_w, kernel_h, iterations) to try dilations.
        """
        print(f"{name_prefix}: running contours_and_overlay")
        # ensure binary uint8 (0/255)
        bi = (bin_img > 0).astype(np.uint8) * 255

        # run for each morphological setting (including no morph)
        settings = [(1,1,0)]
        if kernel_sizes_iters:
            settings.extend(kernel_sizes_iters)
        per_setting_rects: List[List[tuple]] = []
        for idx, (kw, kh, iters) in enumerate(settings):
            work = bi.copy()
            if iters > 0:
                kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kw, kh))
                work = cv2.dilate(work, kernel, iterations=iters)
            # findContours expects a binary image
            res = work.copy()
            contours_info = cv2.findContours(res, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            # OpenCV may return (contours, hierarchy) or (image, contours, hierarchy)
            if len(contours_info) == 3:
                _, contours, hierarchy = contours_info
            else:
                contours, hierarchy = contours_info
            print(f"{name_prefix} setting#{idx} kernel=({kw},{kh}) iters={iters} -> contours found: {len(contours)}")

            # Build bounding rect list for all contours
            rects = []
            for c in contours:
                x, y, w, h = cv2.boundingRect(c)
                rects.append((x, y, w, h))

            # Filter by size and remove rects completely subsumed by a larger rect
            filtered_rects = []
            # subsume threshold: fraction of the smaller rect's area that must be inside a larger rect
            subsume_ratio = 0.8  # default: ignore contours with >=80% of area inside a larger contour

            def intersection_area(r1, r2):
                """Return intersection area of two rects r=(x,y,w,h)."""
                x1, y1, w1, h1 = r1
                x2, y2, w2, h2 = r2
                ix1 = max(x1, x2)
                iy1 = max(y1, y2)
                ix2 = min(x1 + w1, x2 + w2)
                iy2 = min(y1 + h1, y2 + h2)
                if ix2 <= ix1 or iy2 <= iy1:
                    return 0
                return (ix2 - ix1) * (iy2 - iy1)

            for i, (x, y, w, h) in enumerate(rects):
                # # # basic size filters
                if w < 30 or h < 30:
                    continue
                # Only apply this filter for fixed_inverted threshold and kernel size 5x10
                if (
                    name_prefix.startswith("10_fixed")  # fixed_inverted
                    and w > 150
                ):
                    continue
                if w > 600 or h > 600:
                    continue
                if w * h > 250000:
                    continue
                filtered_rects.append((x, y, w, h))
                
            per_setting_rects.append(filtered_rects)

        # Return filtered rects for this setting
        return per_setting_rects
    
    kernel_trials = [(3, 5, 1), (5, 10, 2), (5, 15, 4), (7,7,2)]
    rects1= contours_and_overlay(th_fixed, f"09_fixed{fixed_threshold}", kernel_trials)
    rects2 = contours_and_overlay(th_fixed_inv, f"10_fixed{inverse_threshold}_inv", kernel_trials)
    # Aggregate filtered rectangles for all settings and return
    filtered_rects=rects1 + rects2
    flat_rects: List[tuple] = []
    for rect_list in filtered_rects:
        flat_rects.extend(rect_list)
        
    final_rects: List[tuple] = []
    for i, (x, y, w, h) in enumerate(flat_rects):
        #Skip this rect if a larger rect contains a large fraction of its area.
        small_rect = (x, y, w, h)
        small_area = w * h
        contained = False
        for j, (X, Y, W, H) in enumerate(flat_rects):
            if i == j:
                continue
            # consider only larger candidate containers
            if W * H <= small_area:
                continue
            big_rect = (X, Y, W, H)
            def intersection_area(r1, r2):
                """Return intersection area of two rects r=(x,y,w,h)."""
                x1, y1, w1, h1 = r1
                x2, y2, w2, h2 = r2
                ix1 = max(x1, x2)
                iy1 = max(y1, y2)
                ix2 = min(x1 + w1, x2 + w2)
                iy2 = min(y1 + h1, y2 + h2)
                if ix2 <= ix1 or iy2 <= iy1:
                    return 0
                return (ix2 - ix1) * (iy2 - iy1)
            inter = intersection_area(small_rect, big_rect)
            # if a large fraction of the small rect's area is inside the big one, treat it as subsumed
            subsume_ratio = 0.8  # default: ignore contours with >=80% of area inside a larger contour

            if small_area > 0 and (inter / small_area) >= subsume_ratio:
                contained = True
                break
        if not contained:
            final_rects.append(small_rect)
    
    logging.warning(final_rects)
    
    
    pil_img= Image.fromarray(cv2.cvtColor(img_np, cv2.COLOR_BGR2RGB))
    debug_preprocess_for_ocr_display_results(pil_img, "all_filtered", precomputed_rects=final_rects)
    








def debug_preprocess_for_ocr_display_results(img: Image.Image, name_prefix: str, precomputed_rects: List[List[tuple]]) -> Image.Image:
    """Display all detected and filtered rectangles from step_five on the original image.

    Parameters:
    - img: original PIL Image
    - name_prefix: label to include in window/output names (e.g., "09_fixed240")
    - precomputed_rects: list of lists of `(x, y, w, h)` produced by `preprocess_for_ocr_step_five`

    Returns:
    - A PIL Image with all filtered rectangles drawn in red.

    This function does NOT perform any contour detection or filtering. It only
    draws the rectangles returned by step five onto the original image and
    displays the result.
    """
    try:
        # Convert original to OpenCV BGR for drawing
        try:
            orig_bgr = cv2.cvtColor(np.array(img.convert("RGB")), cv2.COLOR_RGB2BGR)
        except Exception:
            # If img is already a NumPy array
            arr = np.array(img)
            if arr.ndim == 2:
                orig_bgr = cv2.cvtColor(arr, cv2.COLOR_GRAY2BGR)
            else:
                # assume RGB
                orig_bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
        # Flatten precomputed rectangles from all settings
        # aggregated_rects: List[tuple] = []
        # for rect_list in precomputed_rects:
        #     aggregated_rects.extend(rect_list)

        # Draw on original
        overlay = orig_bgr.copy()
        for (x, y, w, h) in precomputed_rects:
            cv2.rectangle(overlay, (x, y), (x + w, y + h), (0, 0, 255), 2)

        # Show window and return PIL Image
        try:
            cv2.imshow(f"{name_prefix}_all_filtered_rects", overlay)
            cv2.waitKey(0)
        except Exception:
            # Headless environments may not support imshow
            pass

        return Image.fromarray(cv2.cvtColor(overlay, cv2.COLOR_BGR2RGB))
    except Exception:
        logger.exception("Failed to display aggregated filtered rectangles for %s", name_prefix)
        return img

# New debug helper: visualizes every step, saves images, prints stats and contour counts.
def debug_preprocess_for_ocr(img: Image.Image, out_dir: str = "_ocr_debug", show: bool = False) -> None:
    """
    Debug helper that saves and (optionally) displays intermediate images, prints numeric stats,
    and tries multiple threshold/dilation parameter combinations to show contour counts.

    Usage:
        from PIL import Image
        img = Image.open('_scraped_images/1.jpg')
        debug_preprocess_for_ocr(img, out_dir='_ocr_debug', show=True)

    This does NOT modify the original preprocess_for_ocr behavior — it is strictly diagnostic.
    """

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    # Convert to OpenCV-native NumPy array in RGB order (PIL -> RGB)
    img_np = np.array(img.convert("RGB"))
    def save_arr(a, name):
        """Save uint8 NumPy array (gray or RGB) to disk for inspection."""
        p = out / name
        try:
            if a.ndim == 2:
                Image.fromarray(a).save(str(p))
            else:
                Image.fromarray(a).save(str(p))
            logger.info("Wrote debug image %s", p)
            if show:
                Image.fromarray(a).show()
        except Exception:
            logger.exception("Failed to save debug image %s", p)

    # 1) Original image
    save_arr(img_np, "01_original_rgb.png")

    # 2) Grayscale
    gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)
    save_arr(gray, "02_gray.png")
    print("gray dtype/shape/min/max/mean:", gray.dtype, gray.shape, gray.min(), gray.max(), float(gray.mean()))

    # 3) Gaussian blur (reduce noise)
    override = False
    if override:
        blurred = gray
        print("Blur step skipped (disable_blur=True)")
    else:
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        print("Blurred applied (disable_blur=False or unset)")
    save_arr(blurred, "03_blur.png")
    print("blurred min/max/mean:", blurred.min(), blurred.max(), float(blurred.mean()))

    # 4) Otsu threshold (automatic)
    ret_otsu, th_otsu = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    save_arr(th_otsu, f"04_thresh_otsu_{int(ret_otsu)}.png")
    print("Otsu threshold value:", ret_otsu, "unique values:", np.unique(th_otsu)[:10], "nonzero count:", np.count_nonzero(th_otsu))

    # 5) Fixed threshold (example 180)
    fixed_threshold=240
    _, th_fixed = cv2.threshold(blurred, fixed_threshold, 255, cv2.THRESH_BINARY)
    save_arr(th_fixed, f"05_thresh_fixed_{fixed_threshold}.png")
    print("Fixed thresh nonzero:", np.count_nonzero(th_fixed))

    # 6) Inverse fixed (useful if text is dark on light bg)
    inverse_threshold=300-fixed_threshold
    _, th_fixed_inv = cv2.threshold(blurred, inverse_threshold, 255, cv2.THRESH_BINARY_INV)
    save_arr(th_fixed_inv, f"06_thresh_fixed_inv_{inverse_threshold}.png")
    print("Fixed inv nonzero:", np.count_nonzero(th_fixed_inv))

    # 7) Adaptive threshold (good for uneven lighting)
    th_adapt = cv2.adaptiveThreshold(blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                     cv2.THRESH_BINARY_INV, 21, 10)
    save_arr(th_adapt, "07_thresh_adaptive.png")
    print("Adaptive thresh nonzero:", np.count_nonzero(th_adapt))

    def contours_and_overlay(bin_img, name_prefix, kernel_sizes_iters=None):
        """Find contours on bin_img, save overlay with boxes, print counts.
        kernel_sizes_iters: iterable of (kernel_w, kernel_h, iterations) to try dilations.
        """
        print(f"{name_prefix}: running contours_and_overlay")
        # ensure binary uint8 (0/255)
        bi = (bin_img > 0).astype(np.uint8) * 255

        # run for each morphological setting (including no morph)
        settings = [(1,1,0)]
        if kernel_sizes_iters:
            settings.extend(kernel_sizes_iters)

        for idx, (kw, kh, iters) in enumerate(settings):
            work = bi.copy()
            if iters > 0:
                kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kw, kh))
                work = cv2.dilate(work, kernel, iterations=iters)
            # findContours expects a binary image
            res = work.copy()
            contours_info = cv2.findContours(res, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            # OpenCV may return (contours, hierarchy) or (image, contours, hierarchy)
            if len(contours_info) == 3:
                _, contours, hierarchy = contours_info
            else:
                contours, hierarchy = contours_info
            print(f"{name_prefix} setting#{idx} kernel=({kw},{kh}) iters={iters} -> contours found: {len(contours)}")

            # Build bounding rect list for all contours
            rects = []
            for c in contours:
                x, y, w, h = cv2.boundingRect(c)
                rects.append((x, y, w, h))

            # Filter by size and remove rects completely subsumed by a larger rect
            filtered_rects = []
            # subsume threshold: fraction of the smaller rect's area that must be inside a larger rect
            subsume_ratio = 0.6  # default: ignore contours with >=60% of area inside a larger contour

            def intersection_area(r1, r2):
                """Return intersection area of two rects r=(x,y,w,h)."""
                x1, y1, w1, h1 = r1
                x2, y2, w2, h2 = r2
                ix1 = max(x1, x2)
                iy1 = max(y1, y2)
                ix2 = min(x1 + w1, x2 + w2)
                iy2 = min(y1 + h1, y2 + h2)
                if ix2 <= ix1 or iy2 <= iy1:
                    return 0
                return (ix2 - ix1) * (iy2 - iy1)

            for i, (x, y, w, h) in enumerate(rects):
                # # basic size filters
                if w < 30 or h < 30:
                    continue
                # Only apply this filter for fixed_inverted threshold and kernel size 5x10
                if (
                    name_prefix.startswith("10_fixed")  # fixed_inverted
                    and w > 100
                ):
                    continue
                if w > 600 or h > 600:
                    continue
                if w * h > 250000:
                    continue
                #File Maximum Size: 1,020,000
                # Skip this rect if a larger rect contains a large fraction of its area.
                # small_rect = (x, y, w, h)
                # small_area = w * h
                # contained = False
                # for j, (X, Y, W, H) in enumerate(rects):
                #     if i == j:
                #         continue
                #     # consider only larger candidate containers
                #     if W * H <= small_area:
                #         continue
                #     big_rect = (X, Y, W, H)
                #     inter = intersection_area(small_rect, big_rect)
                #     # if a large fraction of the small rect's area is inside the big one, treat it as subsumed
                #     if small_area > 0 and (inter / small_area) >= subsume_ratio:
                #         contained = True
                #         break
                # if contained:
                #     continue


                filtered_rects.append((x, y, w, h))

            # create overlay (color) and draw rectangles
            overlay = cv2.cvtColor(img_np.copy(), cv2.COLOR_RGB2BGR)
            for (x, y, w, h) in filtered_rects:
                cv2.rectangle(overlay, (x, y), (x + w, y + h), (0, 0, 255), 2)
            save_arr(cv2.cvtColor(overlay, cv2.COLOR_BGR2RGB), f"{name_prefix}_overlay_{idx}_k{kw}x{kh}_i{iters}.png")

    # Try contours on multiple binarizations
    kernel_trials = [(3, 5, 1), (5, 10, 2), (5, 15, 4), (7,7,2)]
    #contours_and_overlay(th_otsu, "08_otsu", kernel_trials)
    contours_and_overlay(th_fixed, f"09_fixed{fixed_threshold}", kernel_trials)
    contours_and_overlay(th_fixed_inv, f"10_fixed{inverse_threshold}_inv", kernel_trials)
    #contours_and_overlay(th_adapt, "11_adaptive", kernel_trials)
    
    #10_fixed inv 0_k1x1_i0 is the best of th_fixed for 1.jpg
    #11_adaptive_0_k1x1_i0 is the best of th_adapt for 1.jpg

    #9_fixed240_inv 0_k1x1_i0 is the best of th_fixed for 2.jpg
    #10_fixed60_inv 4_k7x7_i2 is the best of th_fixed_inv for 2.jpg
    #It specifically grabs the columns of text, surprisingly. When we don't subsume sections.
    
    #Conclusion, don't use otsu. Automatic is no good. Fixed is best.
    #Adaptive is no good either. Best to stick with fixed thresholds and inverted threshold.

    print("Debug images written to:", out.resolve())
    print("Check the saved images and overlays to see where contours appear or vanish.")
    print("Common reasons for zero contours:")
    print(" - threshold value too high/low (text removed)")
    print(" - image is already mostly white or black (check gray min/max and mean above)")
    print(" - wrong channel order (we use RGB->GRAY which is correct for PIL->NumPy)")
    print(" - kernel/iterations too aggressive (dilating can merge or erase small shapes)")
    print(" - findContours parameters mismatch with binary image (ensure 0/255 uint8)")

    return None


x= debug_preprocess_for_ocr(Image.open("_scraped_images/1.jpg"))
x=preprocess_for_ocr(Image.open("_scraped_images/1.jpg"))