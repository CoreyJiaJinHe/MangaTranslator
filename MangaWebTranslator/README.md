# MangaWebTranslator (Option B)

A lean manga web translation assistant. Captures manga panels via Selenium, performs Japanese OCR with Tesseract (pytesseract), translates text (Google Translate API placeholder), provides kanji dictionary lookups (Jisho.org), and suggests visually similar kanji leveraging stroke/radical data.

## Features (Planned MVP)
- Selenium page capture & panel screenshot extraction
- Segmentation: panel -> text blocks -> lines
- OCR: pytesseract with vertical text handling
- Translation: Google Translate (user-supplied API key or fallback unofficial endpoint)
- Dictionary: Jisho.org kanji & word definitions
- Kanji similarity: engineered stroke + radical feature vectors (KanjiVG + Kanjidic2)
- UI: Panel cards + text overlay editor (PyQt minimal)
- Export: JSON/CSV of original, translated, user-edited text

## Directory Structure
```
MangaWebTranslator/
  core/            # models, config, registry
  services/        # ocr, segmentation, translate, dictionary, similarity, data prep
  ui/              # PyQt windows & widgets
  data/            # local cached datasets (kanji, panels, exports)
  scripts/         # helper scripts (e.g., data sourcing)
  main.py          # entrypoint
  requirements.txt # Python deps for this app only
```

## Requirements
System: Python 3.10+, Tesseract OCR installed & accessible on PATH (e.g., `tesseract --version`).

Install deps:
```cmd
cd MangaWebTranslator
pip install -r requirements.txt
```

## Config
A JSON config file (`config.json`, auto-created) controlling:
- `ocr.language`: default "jpn"
- `paths.tesseract_cmd`: override Tesseract binary path
- `translation.provider`: "google"
- `similarity.maxCandidates`: limit similar kanji suggestions

## Kanji Data Sourcing (Planned)
Scripts will download and parse:
- KanjiVG (strokes, CC BY-SA 3.0)
- Kanjidic2 (readings, radicals, stroke counts)
- Radkfile (radical mappings)
- Wikipedia frequency list subset

Result merged into `data/kanji/merged/kanji_core.json`.

## Running (Prototype)
```cmd
python main.py
```
Initial run shows placeholder UI; services will be stubbed until data is prepared.

## License
Derived design ideas from BallonsTranslator (example only) but code here is newly implemented. Respect upstream dataset licenses (KanjiVG CC BY-SA; Kanjidic2/JMdict EDRDG). Attribution stored in `data/kanji/raw/LICENSES.txt` (planned).

## Roadmap
- [ ] Implement segmentation heuristics
- [ ] Integrate OCR vertical line rotation
- [ ] Build kanji similarity feature extraction
- [ ] Add persistent export & project sessions

