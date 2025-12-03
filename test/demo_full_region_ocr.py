import sys
from pathlib import Path

# Add the project root (one level up from 'test') to sys.path
project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
    
import os
from PIL import Image

from MangaWebTranslator.services.ocr.region_ocr_pipeline import ocr_text_regions


def main():
    img_path = "_scraped_images/1.jpg"
    img = Image.open(img_path)
    pairs = ocr_text_regions(img)
    out_path = "_ocr_debug/ocr_regions.txt"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        for r, text in pairs:
            f.write(f"{r.left},{r.top},{r.width},{r.height}\t{text}\n")
    print(f"OCR finished for {len(pairs)} regions. Saved to {out_path}")


if __name__ == "__main__":
    main()
