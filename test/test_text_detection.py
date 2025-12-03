import sys
from pathlib import Path

# Add the project root (one level up from 'test') to sys.path
project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
    
from PIL import Image, ImageDraw
from MangaWebTranslator.services.ocr.engines.comic_text_detector_adapter import ComicTextDetectorAdapter

# Load image
img = Image.open("_scraped_images/1.jpg").convert("RGB")

# Detect regions
det = ComicTextDetectorAdapter()
rects = det.detect_regions(img)
print("Detected regions:", len(rects))

# Overlay rectangles on original image
overlay = img.copy()
draw = ImageDraw.Draw(overlay)
for r in rects:
	# r may be a TextRegion dataclass with left/top/width/height
	try:
		x, y, w, h = r.left, r.top, r.width, r.height
	except AttributeError:
		# Fallback if plain tuple
		x, y, w, h = r
	draw.rectangle([(x, y), (x + w, y + h)], outline=(255, 0, 0), width=2)

# Show and save for inspection
overlay.show()