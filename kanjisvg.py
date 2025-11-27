# quick_check_svg_parsing.py
from pathlib import Path
from MangaWebTranslator.services.data_prep.kanji_sources import merge_kanji_records, parse_kanjidic2, parse_kanjivg, parse_kanjivg_dir
import logging
logging.basicConfig(level=logging.DEBUG)
svg_dir = Path('MangaWebTranslator/data/kanjivg')
# files = sorted(svg_dir.glob('*.svg'))
# print("SVG files in dir:", len(files))

# for f in files[:50]:                  # sample first 50, increase as needed
#     recs = parse_kanjivg(str(f))
#     stroke_count = sum(getattr(r, 'stroke_count', 0) for r in recs)
#     print(f.name, "-> parsed records:", len(recs), "total strokes:", stroke_count)
    
    
# breakpoint()

# vg = parse_kanjivg_dir('MangaWebTranslator/data/kanjivg')
# kd = parse_kanjidic2('MangaWebTranslator/data/kanjidic2.xml.gz')   # adjust path if needed
# merged = merge_kanji_records(vg, kd)

# no_strokes = [r.char for r in merged if getattr(r, 'stroke_count', None) is None]

# print("Merged total:", len(merged))
# print("No strokes:", len(no_strokes), no_strokes[:60])
# print("No grade:", len(no_grade), no_grade[:60])
# print("No frequency:", len(no_freq), no_freq[:60])

# quick_stats.py
from MangaWebTranslator.services.data_prep.kanji_sources import load_merged_json
merged = load_merged_json('MangaWebTranslator/data/kanji_merged.json')  # adjust path
total = len(merged)
has_strokes = sum(1 for r in merged if getattr(r, 'stroke_count', None) is not None)
print(f"Total: {total}")
print(f"Strokes: {has_strokes} ({has_strokes/total:.1%})")
print('Grade and frequency fields removed from schema; use external sources if needed')



# check_svg_presence.py
from pathlib import Path
from MangaWebTranslator.services.data_prep.kanji_sources import load_merged_json
svg_dir = Path('MangaWebTranslator/data/kanjivg')  # adjust
merged = load_merged_json('MangaWebTranslator/data/kanji_merged.json')

def possible_filenames(ch):
    code = f"{ord(ch):04X}"
    return [f"{ch}.svg", f"U+{code}.svg", f"{code}.svg", f"{code.lower()}.svg"]

missing = [r.char for r in merged if getattr(r, 'stroke_count', None) is None]
samples = missing[:200]
exists_map = {}
for ch in samples:
    found = False
    for fn in possible_filenames(ch):
        if (svg_dir / fn).exists():
            exists_map[ch] = fn
            found = True
            break
    if not found:
        exists_map[ch] = None

for ch, fn in list(exists_map.items())[:60]:
    print(ch, "->", fn or "NO SVG")


# filter_non_kanji.py
def is_cjk(ch):
    cp = ord(ch)
    return (
        0x4E00 <= cp <= 0x9FFF or
        0x3400 <= cp <= 0x4DBF or
        0x20000 <= cp <= 0x2FA1F
    )

from MangaWebTranslator.services.data_prep.kanji_sources import load_merged_json
merged = load_merged_json('MangaWebTranslator/data/kanji_merged.json')
non_kanji = [r.char for r in merged if not is_cjk(r.char)]
print("Non-kanji count:", len(non_kanji))
print("Sample non-kanji:", non_kanji[:80])
