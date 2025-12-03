import sys
from pathlib import Path

# Add the project root (one level up from 'test') to sys.path
project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
    
import os
from PIL import Image

from MangaWebTranslator.services.ocr.region_ocr_pipeline import detect_text_regions, draw_regions_overlay


def main():
    img_path = "_scraped_images/test3.jpg"
    img = Image.open(img_path)
    regions = detect_text_regions(img)
    out = draw_regions_overlay(img, regions)
    out_path = "_ocr_debug/regions_overlay.jpg"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    out.save(out_path)
    print(f"Detected {len(regions)} regions. Saved overlay to {out_path}")


if __name__ == "__main__":
    main()
