from __future__ import annotations

import sys
from pathlib import Path

# Add the project root (one level up from 'test') to sys.path
project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import os
import sys
import traceback
from PIL import Image
import torch

from pathlib import Path

# Import the adapter from the project package
from MangaWebTranslator.services.ocr.engines.manga_ocr_adapter import MangaOcrAdapter
"""
Manual test for MangaOcrAdapter without pytest.

Run from the repository root with the same Python/venv you run the app:
    python tests\run_manga_ocr_adapter_manual.py

Exits with code 0 on success, 2 if skipped (manga-ocr unavailable), and 1 on failure.
"""
def main() -> int:
    """Run a basic integration-style check of MangaOcrAdapter.

    Returns:
        int: exit code (0 success, 2 skipped, 1 failure).
    """
    adapter = MangaOcrAdapter()

    # If the adapter can't import manga-ocr or its deps, skip the test but provide diagnostics.
    if not adapter.available():
        print("SKIP: manga-ocr backend not available in this Python environment.")
        print("Diagnostics:")
        print("  python executable:", sys.executable)
        print("  PYTHONPATH entries:")
        for p in sys.path[:8]:
            print("   -", p)
        print("\nInstall manga-ocr and compatible torch for your Python version, or run this in the venv used by the app.")
        return 2

    # Create a small test image with simple Japanese text to feed the OCR.
    img = Image.open("_scraped_images/test3.jpg").convert("RGB")
    print("Test image with Japanese text displayed.")
    img.show()

    try:
        # Run recognition; adapters should accept pil Image, lang and device keywords.
        result = adapter.recognize(img, lang="jpn")
    except Exception as exc:
        print("ERROR: adapter.recognize raised an exception:")
        traceback.print_exc()
        return 1

    # Basic validations on the normalized result structure
    try:
        if not isinstance(result, dict):
            raise AssertionError("Result must be a dict")

        if "text" not in result or "blocks" not in result:
            raise AssertionError("Result must contain 'text' and 'blocks' keys")

        if not isinstance(result["text"], str):
            raise AssertionError("'text' must be a string")

        if not isinstance(result["blocks"], list):
            raise AssertionError("'blocks' must be a list")

        # Validate block structure
        for i, block in enumerate(result["blocks"]):
            if not isinstance(block, dict):
                raise AssertionError(f"Block {i} is not a dict")
            for key in ("text", "left", "top", "width", "height", "conf"):
                if key not in block:
                    raise AssertionError(f"Block {i} missing key: {key}")
            # Check types for bbox/conf fields
            if not isinstance(block["text"], str):
                raise AssertionError(f"Block {i} 'text' must be string")
            for num_key in ("left", "top", "width", "height", "conf"):
                if not isinstance(block[num_key], (int, float)):
                    raise AssertionError(f"Block {i} key '{num_key}' must be numeric")

    except AssertionError as ae:
        print("FAIL: Result structure validation failed:")
        print("  ", ae)
        print("Full result:", result)
        return 1

    # If we reached here, structure is valid. Print a short summary.
    print("OK: MangaOcrAdapter returned valid structure.")
    print("Recognized text (first 200 chars):")
    print(result["text"][:200])
    print("Number of blocks:", len(result["blocks"]))
    return 0

if __name__ == "__main__":
    sys.exit(main())
    
    
    
"""
Manual quick-check of the installed `manga-ocr` callable.

Run from the repository root using the same venv you run the app in:
    python tests\manual_mangaocr_call.py [path/to/image.png]

Default image path used if none provided:
    _scraped_images/test.png

This script:
- Imports MangaOcr
- Instantiates it (lazy model download may occur)
- Calls the instance with the PIL image
- Prints the returned object's type and a short summary so you can see the exact shape
"""

def main() -> int:
    img_path = Path("_scraped_images/test 2.png")
    if not img_path.exists():
        print(f"ERROR: image not found: {img_path}", file=sys.stderr)
        return 2

    try:
        # Import and instantiate MangaOcr using the environment/venv in which you run this script.
        from manga_ocr import MangaOcr  # type: ignore
    except Exception as exc:
        print("ERROR: failed to import manga_ocr:", exc, file=sys.stderr)
        traceback.print_exc()
        return 3

    try:
        print("Instantiating MangaOcr() (may download model on first run)...")
        mocr = MangaOcr()  # do not pass device here; keep default (we'll run CPU)
    except Exception as exc:
        print("ERROR: failed to instantiate MangaOcr():", exc, file=sys.stderr)
        traceback.print_exc()
        return 4

    try:
        img = Image.open(img_path).convert("RGB")
    except Exception as exc:
        print("ERROR: failed to open image:", exc, file=sys.stderr)
        traceback.print_exc()
        return 5
    try:
            print(f"Displaying image: {img_path}")
            img.show()
            # Pause briefly so user running the script from console can see the image viewer.
            # This input keeps the script open; press Enter to continue.
            input("Image displayed. Press Enter to run MangaOcr on this image...")
    except Exception as exc:
            print("WARNING: failed to display image with Image.show():", exc, file=sys.stderr)

    try:
        print("Running mocr(img)...")
        out = mocr(img)
    except Exception as exc:
        print("ERROR: MangaOcr call raised an exception:", exc, file=sys.stderr)
        traceback.print_exc()
        return 6

    # Print concise diagnostics about the returned value so you can adapt the adapter.
    print("Returned type:", type(out))
    if isinstance(out, str):
        print("String result (first 500 chars):")
        print(out[:500])
    elif isinstance(out, (list, tuple)):
        print(f"List/Tuple with {len(out)} elements. Sample repr of first element:")
        print(repr(out[0])[:1000])
    elif isinstance(out, dict):
        print("Dict keys:", list(out.keys()))
        # If keys contain 'text' or 'blocks' print short previews
        if 'text' in out:
            t = out.get('text') or ''
            print("text (first 500 chars):")
            print(t[:500])
        if 'blocks' in out:
            b = out.get('blocks') or []
            print(f"blocks: {len(b)} entries. Sample first block:")
            if b:
                print(repr(b[0])[:1000])
    else:
        print("Unhandled return type. repr:")
        print(repr(out)[:1000])

    print("\nDone. Use output shape above to simplify/adjust the adapter logic.")
    return 0

# if __name__ == "__main__":
#     sys.exit(main())
