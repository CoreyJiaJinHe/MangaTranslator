"""Minimal pytesseract OCR implementation for region workflow.

Provides a thin wrapper around ``pytesseract.image_to_data`` to extract
line-level text blocks from a PIL Image (or QImage converted to PIL).
This remains intentionally lightweight; advanced preprocessing (binarization,
rotation detection, vertical handling) will be introduced in later phases.
"""
from __future__ import annotations

from typing import List, Dict, Any
import pytesseract
from PIL import Image, ImageOps, ImageFilter
import io
import traceback
import tempfile
import os
import time
try:
    from PyQt6.QtGui import QImage
except Exception:  # pragma: no cover - PyQt may not always be available in tests
    QImage = None  # type: ignore


class PyTesseractOCR:
    """Wrapper around pytesseract providing simple preprocessing and structured output.

    Methods
    - `extract_blocks(image, lang='jpn', preprocess=True, conf_thresh=0)` -> list of dicts
      Each dict: {text, left, top, width, height, conf}
    - `extract_text(image, **kwargs)` -> list[str] (lines), for backward compatibility
    """

    def __init__(self, cfg: Dict[str, Any] | None = None) -> None:
        self.cfg = cfg or {}

    def _to_pil(self, image) -> Image.Image:
        """Convert supported image objects to a PIL Image.

        Supports:
        - PIL.Image.Image (returned as-is)
        - PyQt6.QtGui.QImage (converted by saving to an in-memory PNG)
        - Any object exposing raw bytes via ``tobytes`` and ``size`` (best-effort)

        Raises TypeError when conversion is not possible.
        """
        if isinstance(image, Image.Image):
            return image

        # Prefer converting QImage via an in-memory PNG (robust across formats)
        if QImage is not None and isinstance(image, QImage):
            try:
                from PyQt6.QtCore import QBuffer, QByteArray
                ba = QByteArray()
                buf = QBuffer(ba)
                buf.open(QBuffer.OpenModeFlag.WriteOnly)
                image.save(buf, 'PNG')
                data = bytes(ba)
                pil = Image.open(io.BytesIO(data)).convert('RGB')
                return pil
            except Exception:
                # best-effort fallback to raw bits — log traceback to help debug conversion problems
                try:
                    mem = image.bits()
                    # ensure buffer size matches
                    mem.setsize(image.byteCount())
                    raw = bytes(mem)
                    # try to construct from raw RGBA bytes
                    try:
                        pil = Image.frombuffer('RGBA', (image.width(), image.height()), raw, 'raw', 'RGBA')
                        return pil.convert('RGB')
                    except Exception:
                        try:
                            return Image.open(io.BytesIO(raw)).convert('RGB')
                        except Exception:
                            traceback.print_exc()
                except Exception:
                    traceback.print_exc()

        # Generic fallback: objects exposing `tobytes()` and `size` attributes
        if hasattr(image, 'tobytes') and hasattr(image, 'size'):
            try:
                return Image.frombytes('RGB', image.size, image.tobytes())
            except Exception:
                pass

        raise TypeError('Unsupported image type for OCR; provide PIL.Image.Image or PyQt QImage')

    def _preprocess(self, pil: Image.Image, do_binarize: bool = True) -> Image.Image:
        """Apply light preprocessing to improve OCR: convert to grayscale, despeckle, optional binarization."""
        img = pil.convert('L')
        # gentle median filter to reduce noise
        try:
            img = img.filter(ImageFilter.MedianFilter(size=3))
        except Exception:
            pass
        if do_binarize:
            # simple adaptive-like step: use ImageOps.autocontrast then point threshold
            img = ImageOps.autocontrast(img)
            # Otsu would be better but avoid extra deps; use a fixed threshold fallback
            try:
                # attempt to use PIL's point for simple thresholding
                threshold = 128
                img = img.point(lambda p: 255 if p > threshold else 0)
            except Exception:
                pass
        return img

    def extract_blocks(self, image, lang: str = 'jpn', preprocess: bool = True, conf_thresh: int = 0) -> List[Dict[str, Any]]:
        """Return list of OCR blocks with bounding boxes and confidence.

        Each block is a dict: {text, left, top, width, height, conf}
        """
        pil = self._to_pil(image)
        if preprocess:
            pil = self._preprocess(pil)

        # Diagnostic: print tesseract version and available languages when debugging
        try:
            ver = pytesseract.get_tesseract_version()
            try:
                langs = pytesseract.get_languages(config='')
            except Exception:
                langs = []
            print(f"[pytesseract] version={ver} requested_lang={lang} available_langs={langs}")
        except Exception:
            traceback.print_exc()

        # Use pytesseract to get granular word/line data
        try:
            data = pytesseract.image_to_data(pil, lang=lang, output_type=pytesseract.Output.DICT)
        except Exception as e:
            print(f"[pytesseract] image_to_data raised: {e}")
            traceback.print_exc()
            # Re-raise so caller can handle, but also return empty list as fallback
            return []
        blocks: List[Dict[str, Any]] = []
        n = len(data.get('text', []))
        print(f"[pytesseract] image_to_data returned {n} text entries")
        # show a small sample of returned entries for debugging
        try:
            sample_n = min(8, n)
            samples = []
            for i in range(sample_n):
                samples.append({'text': data.get('text', [])[i], 'conf': data.get('conf', [])[i]})
            print(f"[pytesseract] sample entries={samples}")
        except Exception:
            pass

        all_blocks: List[Dict[str, Any]] = []
        for i in range(n):
            txt = (data.get('text', [])[i] or '').strip()
            if not txt:
                continue
            conf_raw = data.get('conf', [])[i]
            try:
                conf = int(float(conf_raw))
            except Exception:
                conf = -1
            left = int(data.get('left', [0])[i])
            top = int(data.get('top', [0])[i])
            width = int(data.get('width', [0])[i])
            height = int(data.get('height', [0])[i])
            all_blocks.append({'text': txt, 'left': left, 'top': top, 'width': width, 'height': height, 'conf': conf})

        # Apply confidence threshold filter if requested
        if conf_thresh and conf_thresh > 0:
            filtered = [b for b in all_blocks if (b.get('conf', -1) >= conf_thresh)]
            if not filtered and all_blocks:
                # If the confidence filter removed everything, fall back to returning unfiltered blocks
                print(f"[pytesseract] confidence threshold {conf_thresh} removed all {len(all_blocks)} blocks; returning unfiltered results for visibility")
                blocks = all_blocks
            else:
                blocks = filtered
        else:
            blocks = all_blocks

        # If results are empty or low-confidence, try alternative strategies (scaling, PSMs, vertical Japanese)
        def _score_blocks(bls: List[Dict[str, Any]]) -> float:
            if not bls:
                return 0.0
            confs = [b.get('conf', -1) for b in bls if b.get('conf', -1) >= 0]
            avg_conf = (sum(confs) / len(confs)) if confs else 0.0
            return len(bls) * (1 + avg_conf / 100.0)

        initial_score = _score_blocks(blocks)
        print(f"[pytesseract] initial blocks={len(blocks)} score={initial_score:.2f}")

        if initial_score < 1.0 and all_blocks:
            try:
                avail_langs = []
                try:
                    avail_langs = pytesseract.get_languages(config='')
                except Exception:
                    pass
                variants = []
                for psm in (6, 3, 11):
                    variants.append({'scale': 1, 'binarize': preprocess, 'psm': psm, 'lang': lang})
                for scale in (2, 3):
                    variants.append({'scale': scale, 'binarize': True, 'psm': 6, 'lang': lang})
                    variants.append({'scale': scale, 'binarize': False, 'psm': 3, 'lang': lang})
                if 'jpn_vert' in avail_langs:
                    variants.append({'scale': 2, 'binarize': True, 'psm': 6, 'lang': 'jpn_vert'})

                best_score = initial_score
                best_blocks = blocks
                best_variant = None

                for v in variants:
                    try:
                        pil2 = pil.copy()
                        if v['scale'] > 1:
                            new_sz = (int(pil2.width * v['scale']), int(pil2.height * v['scale']))
                            pil2 = pil2.resize(new_sz, resample=Image.LANCZOS)
                        if v['binarize']:
                            pil2 = self._preprocess(pil2, do_binarize=True)
                        else:
                            pil2 = pil2.convert('L')
                        bls = []
                        # run image_to_data for this variant
                        try:
                            data_v = pytesseract.image_to_data(pil2, lang=v['lang'], config=f"--psm {v['psm']} --oem 1", output_type=pytesseract.Output.DICT)
                        except Exception as e:
                            print(f"[pytesseract] image_to_data raised for variant {v}: {e}")
                            traceback.print_exc()
                            continue
                        n_v = len(data_v.get('text', []))
                        for j in range(n_v):
                            t = (data_v.get('text', [])[j] or '').strip()
                            if not t:
                                continue
                            conf_raw = data_v.get('conf', [])[j]
                            try:
                                c = int(float(conf_raw))
                            except Exception:
                                c = -1
                            l = int(data_v.get('left', [0])[j])
                            ttop = int(data_v.get('top', [0])[j])
                            w = int(data_v.get('width', [0])[j])
                            h = int(data_v.get('height', [0])[j])
                            bls.append({'text': t, 'left': l, 'top': ttop, 'width': w, 'height': h, 'conf': c})
                        sc = _score_blocks(bls)
                        print(f"[pytesseract] variant lang={v['lang']} scale={v['scale']} bin={v['binarize']} psm={v['psm']} -> blocks={len(bls)} score={sc:.2f}")
                        if sc > best_score:
                            best_score = sc
                            best_blocks = bls
                            best_variant = v
                    except Exception:
                        traceback.print_exc()

                if best_variant is not None and best_score > initial_score:
                    print(f"[pytesseract] selected variant {best_variant} with score={best_score:.2f}")
                    try:
                        t1 = int(time.time() * 1000)
                        tmpdir = tempfile.gettempdir()
                        chosen_fname = os.path.join(tmpdir, f"manga_ocr_chosen_{t1}.png")
                        cpil = pil.copy()
                        if best_variant['scale'] > 1:
                            cpil = cpil.resize((int(cpil.width * best_variant['scale']), int(cpil.height * best_variant['scale'])), resample=Image.LANCZOS)
                        if best_variant['binarize']:
                            cpil = self._preprocess(cpil, do_binarize=True)
                        cpil.save(chosen_fname)
                        print(f"[pytesseract] Saved chosen-variant image to: {chosen_fname}")
                    except Exception:
                        traceback.print_exc()
                    blocks = best_blocks
            except Exception:
                traceback.print_exc()

        # If no blocks found, run additional diagnostics: save the PIL image and run image_to_string
        if not blocks:
            try:
                t0 = int(time.time() * 1000)
                tmpdir = tempfile.gettempdir()
                fname = os.path.join(tmpdir, f"manga_ocr_debug_{t0}.png")
                try:
                    pil.save(fname)
                    print(f"[pytesseract] Saved debug image to: {fname}")
                except Exception:
                    traceback.print_exc()

                # Try a plain text extraction to see what tesseract returns
                try:
                    txt_out = pytesseract.image_to_string(pil, lang=lang)
                    print(f"[pytesseract] image_to_string (lang={lang}) output:\n{txt_out!r}")
                except Exception:
                    traceback.print_exc()

                # If vertical Japanese available, try that too
                try:
                    langs = []
                    try:
                        langs = pytesseract.get_languages(config='')
                    except Exception:
                        pass
                    if 'jpn_vert' in langs and lang != 'jpn_vert':
                        try:
                            txt_vert = pytesseract.image_to_string(pil, lang='jpn_vert')
                            print(f"[pytesseract] image_to_string (lang=jpn_vert) output:\n{txt_vert!r}")
                        except Exception:
                            traceback.print_exc()
                except Exception:
                    pass

                # Try image_to_data with an alternate PSM (single column of text, good for vertical text)
                try:
                    alt_data = pytesseract.image_to_data(pil, lang=lang, config='--psm 6', output_type=pytesseract.Output.DICT)
                    print(f"[pytesseract] alt image_to_data psm=6 returned {len(alt_data.get('text', []))} entries")
                except Exception:
                    traceback.print_exc()
            except Exception:
                traceback.print_exc()

        return blocks

    def extract_text(self, image, lang: str = 'jpn', preprocess: bool = True, conf_thresh: int = 0) -> List[str]:
        """Compatibility method: return list of non-empty lines in reading order.

        This aggregates word-level data into lines using the `line_num` field if available.
        """
        pil = self._to_pil(image)
        if preprocess:
            pil = self._preprocess(pil)

        data = pytesseract.image_to_data(pil, lang=lang, output_type=pytesseract.Output.DICT)
        lines: List[str] = []
        current_line = None
        buffer: List[str] = []
        n = len(data.get('text', []))
        for i in range(n):
            txt = (data.get('text', [])[i] or '').strip()
            if not txt:
                continue
            conf_raw = data.get('conf', [])[i]
            try:
                conf = int(float(conf_raw))
            except Exception:
                conf = -1
            if conf_thresh and conf < conf_thresh:
                continue
            line_num = data.get('line_num', [None])[i]
            if current_line is None:
                current_line = line_num
            if line_num != current_line:
                if buffer:
                    lines.append(' '.join(buffer))
                buffer = [txt]
                current_line = line_num
            else:
                buffer.append(txt)
        if buffer:
            lines.append(' '.join(buffer))
        return lines

