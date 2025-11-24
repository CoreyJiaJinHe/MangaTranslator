# Kanji Core Dataset Schema (Skeleton Phase)

This document defines the planned JSON structure for the canonical kanji dataset `kanji_core.json` to be produced in a later data ingestion phase.

## Top-Level Structure
```json
{
  "version": "0.1-skeleton",
  "generated_at": "YYYY-MM-DD",
  "kanji": [ { /* KanjiRecord objects */ } ],
  "radicals": { "<radical_id>": { "glyph": "⼀", "kangxi_no": 1 } },
  "source_meta": { "kanjivg": {"license": "CC BY-SA 3.0"}, "kanjidic2": {"license": "EDRDG"} }
}
```

## KanjiRecord Object
```json
{
  "codepoint": "6f22",          // lowercase hex codepoint
  "literal": "漢",               // single kanji character
  "stroke_count_primary": 13,     // primary stroke count
  "stroke_count_alt": [12],       // alternative counts if available
  "radical_id": 85,               // primary radical numeric ID (classical)
  "radicals_all": [85],           // all associated radical ids (for variants/classical vs indexing)
  "on_readings": ["カン"],        // katakana ON readings
  "kun_readings": ["xxx"],       // hiragana KUN readings
  "meanings": ["China", "Han"], // English-only meanings (initial phase)
  "freq_rank": 427,               // integer rank (lower = more frequent); optional
  "joyo": true,                   // part of Joyo list
  "jinmeiyo": false,              // part of Jinmeiyo list
  "variant_of": null,             // codepoint of canonical variant if this is an old form
  "variants": [],                 // list of variant codepoints
  "strokes": [                    // stroke geometry from KanjiVG
    {
      "index": 0,
      "points": [[0.02,0.15],[0.05,0.16],...],  // normalized unit-square polyline
      "length": 0.83,
      "bbox": [0.02,0.14,0.25,0.31],           // (minx,miny,maxx,maxy)
      "direction_stats": [1.57,0.42,0.73],     // mean_angle, std_angle, straightness
      "curvature": null                        // reserved for later
    }
  ],
  "sources": {
    "kanjivg_file": "u6f22.svg", // original filename
    "kanjidic2_entry": true       // present in Kanjidic2
  },
  "quality_flags": ["ALT_STROKE_DISCREPANCY"] // data quality notes
}
```

## Radicals Section
```json
"radicals": {
  "85": {"glyph": "⽕", "kangxi_no": 86, "strokes": 4},
  "1": {"glyph": "⼀", "kangxi_no": 1, "strokes": 1}
}
```

## Notes / Conventions
- All codepoints stored as lowercase hex (no leading `U+`).
- Unicode normalization: NFC enforced during ingestion.
- Stroke points normalized to unit square per glyph bounding box.
- `freq_rank` derived from a chosen corpus (e.g. Wikipedia) and is optional; absence -> null.
- `quality_flags` used to annotate inconsistencies (stroke count disagreements, missing frequency, variant mapping unresolved).
- Meanings limited to English initially; other languages added later via separate map.

## Future Extensions
- Embeddings: `embedding": [float,...]` for CNN/GNN vector.
- Radicals extended: `radical_forms` for variant radical glyphs.
- Phonetic classification tags.
- Semantic domains clustering.

## Validation Approach (Later Phase)
- JSON Schema or pydantic model will enforce required fields.
- Cross-field checks (stroke_count_primary == len(strokes) or documented disparity).
- Duplicate literal detection and variant cycle prevention.

---
Skeleton phase: documentation only. No generators or parsers implemented yet.
