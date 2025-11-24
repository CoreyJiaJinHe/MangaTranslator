"""Minimal pytesseract OCR implementation for region workflow.

Provides a thin wrapper around ``pytesseract.image_to_data`` to extract
line-level text blocks from a PIL Image (or QImage converted to PIL).
This remains intentionally lightweight; advanced preprocessing (binarization,
rotation detection, vertical handling) will be introduced in later phases.
"""
from __future__ import annotations

from typing import List
import pytesseract
from PIL import Image


class PyTesseractOCR:
    def __init__(self, cfg) -> None:  # cfg will be AppConfig later
        self.cfg = cfg

    def extract_text(self, image) -> List[str]:
        """Extract line text from a PIL Image.

        Parameters
        ----------
        image : PIL.Image.Image | QImage | any
            Source image. If not already a PIL Image, attempts conversion.

        Returns
        -------
        list[str]
            List of non-empty line strings in reading order.
        """
        if not isinstance(image, Image.Image):
            try:
                # Attempt conversion if a QImage-like object; deferred for later improvements.
                image = Image.frombytes("RGBA", (image.width(), image.height()), image.bits().asstring())  # type: ignore
            except Exception:
                raise TypeError("Unsupported image type for OCR; provide PIL.Image.Image")

        # Use tesseract to obtain granular data; we aggregate lines.
        data = pytesseract.image_to_data(image, lang="jpn", output_type=pytesseract.Output.DICT)
        lines: List[str] = []
        current_line_num = None
        buffer = []
        for i in range(len(data["text"])):
            txt = data["text"][i].strip()
            if not txt:
                continue
            line_num = data.get("line_num", [None])[i]
            if current_line_num is None:
                current_line_num = line_num
            if line_num != current_line_num:
                if buffer:
                    lines.append(" ".join(buffer))
                buffer = [txt]
                current_line_num = line_num
            else:
                buffer.append(txt)
        if buffer:
            lines.append(" ".join(buffer))
        return lines

