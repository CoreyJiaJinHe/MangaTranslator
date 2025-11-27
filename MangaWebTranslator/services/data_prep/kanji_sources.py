"""Kanji data prep skeleton.
Future: parse KanjiVG SVG strokes and Kanjidic2 XML metadata into KanjiRecord objects.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional, Sequence
import xml.etree.ElementTree as ET
import gzip
import io
import logging
import json
import argparse
from dataclasses import asdict
from pathlib import Path
import csv

logger = logging.getLogger(__name__)


@dataclass
class KanjiRecord:
    """Unified data record for a single kanji.

    Fields are intentionally simple and permissive so the parsers can
    populate whatever is available and the merger can combine them.
    """
    char: str
    # store only the number of strokes (small, stable) instead of full SVG paths
    stroke_count: Optional[int] = None
    onyomi: List[str] = field(default_factory=list)
    kunyomi: List[str] = field(default_factory=list)
    meanings: List[str] = field(default_factory=list)
    jlpt: Optional[int] = None
    # grade and frequency removed to reduce data footprint; use external maps if needed
    sources: List[str] = field(default_factory=list)


def _local_name(tag: str) -> str:
    """Return XML local name without namespace."""
    if tag is None:
        return ""
    return tag.split('}')[-1]


def parse_kanjivg(svg_root) -> List[KanjiRecord]:
    """Parse a KanjiVG SVG file or Element and return a list of KanjiRecord.

    Args:
        svg_root: path to an SVG file, a file-like object, or an ElementTree Element.

    Behavior (robust, forgiving):
    - Finds groups (<g> elements) that contain stroke <path> elements.
    - Attempts to determine the character using attributes like 'id',
      'data-unicode', or by extracting a 'U+XXXX' hex sequence from the id.
    - Collects the 'd' attribute of child <path> elements as strokes.

    Returns:
        List of KanjiRecord objects populated with strokes and `sources=['kanjivg']`.
    """
    # Load Element if a path or file-like passed
    source_path = None
    if isinstance(svg_root, (str, bytes)):
        source_path = str(svg_root)
        tree = ET.parse(svg_root)
        root = tree.getroot()
    elif hasattr(svg_root, 'read'):
        # file-like
        tree = ET.parse(svg_root)
        root = tree.getroot()
    else:
        root = svg_root

    records: List[KanjiRecord] = []

    def _extract_from_elem(elem) -> Optional[KanjiRecord]:
        # collect path 'd' attributes inside this element
        strokes: List[str] = []
        for child in elem.iter():
            if _local_name(child.tag).lower() == 'path':
                d = child.get('d')
                if d:
                    strokes.append(d)
        if not strokes:
            return None

        # try to determine a character for this element
        char = None
        for attr in ('data-unicode', 'unicode', 'char', 'glyph-name', 'id'):
            v = elem.get(attr)
            if not v:
                continue
            # id may contain 'U+4E00'
            if 'U+' in v or 'u+' in v:
                import re

                m = re.search(r'[Uu]\+([0-9A-Fa-f]{4,6})', v)
                if m:
                    try:
                        code = int(m.group(1), 16)
                        char = chr(code)
                        break
                    except Exception:
                        pass
            if len(v) == 1:
                char = v
                break

        # as a last resort, try to find a literal child element text
        if char is None:
            for child in elem:
                if _local_name(child.tag).lower() in ('text', 'glyph') and child.text:
                    txt = child.text.strip()
                    if len(txt) == 1:
                        char = txt
                        break

        # infer from filename when available
        if char is None and source_path:
            try:
                from pathlib import Path
                import re as _re

                stem = Path(source_path).stem
                if len(stem) == 1:
                    char = stem
                else:
                    m = _re.search(r'[Uu]?\+?([0-9A-Fa-f]{4,6})', stem)
                    if m:
                        try:
                            code = int(m.group(1), 16)
                            char = chr(code)
                        except Exception:
                            pass
            except Exception:
                pass

        if char is None:
            return None

        # store only stroke count (fewer bytes, easier to merge)
        return KanjiRecord(char=char, stroke_count=len(strokes), sources=['kanjivg'])

    found_any = False
    # try to extract from <g> groups first
    for elem in root.iter():
        if _local_name(elem.tag).lower() != 'g':
            continue
        rec = _extract_from_elem(elem)
        if rec:
            records.append(rec)
            found_any = True

    # if no groups produced records, try the root itself (single-file SVG layout)
    if not found_any:
        rec = _extract_from_elem(root)
        if rec:
            records.append(rec)

    if not records:
        logger.debug('parse_kanjivg: no stroke groups found in %s', source_path or '<element>')

    return records


def parse_kanjidic2(xml_gz_path) -> List[KanjiRecord]:
    """Parse a Kanjidic2 XML (optionally gzipped) and return KanjiRecord list.

        This uses a streaming `iterparse` so it can handle large files.
        The function extracts:
            - literal character
            - readings (r_type attribute: ja_on / ja_kun)
            - meanings
            - misc metadata: jlpt when available

        Returns:
                List[KanjiRecord] populated with metadata and `sources=['kanjidic2']`.
    """
    # open gzipped or plain
    if str(xml_gz_path).lower().endswith('.gz'):
        fp = gzip.open(xml_gz_path, 'rb')
        # ElementTree.iterparse accepts file-like binary streams
        context = ET.iterparse(fp, events=('end',))
    else:
        context = ET.iterparse(xml_gz_path, events=('end',))

    records: List[KanjiRecord] = []

    for event, elem in context:
        if _local_name(elem.tag) != 'character':
            # free memory for non-character elements
            continue

        # parse literal
        literal = None
        for child in elem:
            if _local_name(child.tag) == 'literal' and child.text:
                literal = child.text.strip()
                break
        if not literal:
            elem.clear()
            continue

        onyomi: List[str] = []
        kunyomi: List[str] = []
        meanings: List[str] = []
        jlpt = None

        # Find readings and meanings (reading_meaning groups may be nested)
        for sub in elem.iter():
            tag = _local_name(sub.tag)
            if tag == 'reading':
                rtext = (sub.text or '').strip()
                rtype = sub.get('r_type') or sub.get('type')
                if rtext:
                    if rtype == 'ja_on':
                        onyomi.append(rtext)
                    elif rtype == 'ja_kun':
                        kunyomi.append(rtext)
                    else:
                        # unknown type: keep in onyomi by default
                        onyomi.append(rtext)
            elif tag == 'meaning':
                m = (sub.text or '').strip()
                if m:
                    meanings.append(m)
            elif tag == 'jlpt':
                try:
                    jlpt = int((sub.text or '').strip())
                except Exception:
                    pass
        rec = KanjiRecord(char=literal, onyomi=onyomi, kunyomi=kunyomi, meanings=meanings,
                          jlpt=jlpt, sources=['kanjidic2'])
        records.append(rec)

        # clear parsed element from tree to save memory
        elem.clear()

    # close file if gzip opened it
    try:
        if isinstance(fp, gzip.GzipFile):
            fp.close()
    except Exception:
        pass

    return records


def merge_kanji_records(vg: Sequence[KanjiRecord], kd: Sequence[KanjiRecord]) -> List[KanjiRecord]:
    """Merge KanjiVG stroke records and Kanjidic2 metadata into unified records.

    Strategy:
    - Index VG records by `char` and start from them (stroke data preferred).
    - For each KD record, if same `char` exists, merge fields (extend lists, fill missing metadata).
    - If KD has characters not in VG, include them as new records (metadata-only).

    The merge preserves provenance by adding source tags.
    """
    vg_map = {r.char: KanjiRecord(**{**r.__dict__}) for r in vg}

    for r in kd:
        if r.char in vg_map:
            target = vg_map[r.char]
            # merge readings
            for x in r.onyomi:
                if x not in target.onyomi:
                    target.onyomi.append(x)
            for x in r.kunyomi:
                if x not in target.kunyomi:
                    target.kunyomi.append(x)
            for x in r.meanings:
                if x not in target.meanings:
                    target.meanings.append(x)
            # fill JLPT if missing
            if target.jlpt is None and r.jlpt is not None:
                target.jlpt = r.jlpt
            # merge sources
            for s in r.sources:
                if s not in target.sources:
                    target.sources.append(s)
        else:
            # carry over KD-only record
            vg_map[r.char] = KanjiRecord(**{**r.__dict__})

    merged = list(vg_map.values())
    # optional: sort by character codepoint for deterministic output
    merged.sort(key=lambda rr: ord(rr.char[0]) if rr.char else 0)
    return merged


__all__ = [
    'KanjiRecord', 'parse_kanjivg', 'parse_kanjidic2', 'merge_kanji_records',
]


def parse_kanjivg_dir(directory: str | Path) -> List[KanjiRecord]:
    """Parse all `.svg` files found in `directory` and return combined records.

    The function walks the directory (non-recursive by default) and calls
    `parse_kanjivg` on each SVG file. It returns the combined list of
    `KanjiRecord` objects parsed from the files.
    """
    p = Path(directory)
    if not p.exists():
        raise FileNotFoundError(f"SVG directory not found: {directory}")

    records: List[KanjiRecord] = []
    # prefer non-recursive; use rglob if you want recursive
    for svg in sorted(p.glob('*.svg')):
        try:
            recs = parse_kanjivg(str(svg))
            records.extend(recs)
        except Exception as e:
            logger.exception("Failed to parse %s: %s", svg, e)
    return records


def save_merged_json(path: str | Path, merged: Sequence[KanjiRecord]) -> None:
    """Serialize merged KanjiRecord list to JSON (simple dict form).

    The JSON structure is a list of dicts with the dataclass fields. This
    cached file can be loaded later by other parts of the program.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    out = [asdict(r) for r in merged]
    with p.open('w', encoding='utf8') as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)


def load_merged_json(path: str | Path) -> List[KanjiRecord]:
    """Load JSON previously written by `save_merged_json` and return records."""
    p = Path(path)
    with p.open('r', encoding='utf8') as fh:
        data = json.load(fh)
    records: List[KanjiRecord] = []
    for item in data:
        # Backwards compatibility: if file has 'strokes' list, convert to stroke_count
        if 'strokes' in item and item.get('stroke_count') is None:
            item['stroke_count'] = len(item.get('strokes') or [])
            item.pop('strokes', None)
        records.append(KanjiRecord(**item))
    return records


def compute_merged_stats(merged: Sequence[KanjiRecord]) -> dict:
    """Compute simple coverage statistics for merged records.

    Returns a dict with counts and percentages for fields: `strokes`.
    """
    total = len(merged)
    # count records that have a stroke_count value
    strokes_count = sum(1 for r in merged if getattr(r, 'stroke_count', None) is not None)
    return {
        'total': total,
        'strokes_count': strokes_count,
        'strokes_pct': (strokes_count / total * 100) if total else 0.0,
    }


def load_joyo_csv(path: str | Path) -> dict:
    """Load joyo.csv (with header) and return a map char -> info dict.

    Expected columns include: index,kanji,kanji_old,radical,strokes,grade,year,meanings,on,kun,frequency,jlpt
    The returned info dict may contain keys: 'stroke_count', 'meanings', 'onyomi', 'kunyomi'.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(path)
    info_map = {}
    with p.open('r', encoding='utf8') as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            ch = row.get('kanji')
            if not ch:
                continue
            info = {}
            # strokes (number)
            s = row.get('strokes')
            if s:
                try:
                    info['stroke_count'] = int(s)
                except Exception:
                    pass
            # (We only keep stroke_count, readings and meanings here.)
            # readings / meanings
            on = row.get('on')
            kun = row.get('kun')
            meanings = row.get('meanings')
            if on:
                info['onyomi'] = [x.strip() for x in on.split(',') if x.strip()]
            if kun:
                info['kunyomi'] = [x.strip() for x in kun.split(',') if x.strip()]
            if meanings:
                info['meanings'] = [x.strip() for x in meanings.split(',') if x.strip()]
            info_map[ch] = info
    return info_map


def merge_joyo_into_records(merged: Sequence[KanjiRecord], joyo_map: dict) -> int:
    """Merge joyo info into merged KanjiRecord list. Returns number updated."""
    updated = 0
    for r in merged:
        info = joyo_map.get(r.char)
        if not info:
            continue
        changed = False
        # stroke_count stored as dynamic attribute to avoid reshaping dataclass
        if getattr(r, 'stroke_count', None) is None and 'stroke_count' in info:
            setattr(r, 'stroke_count', info['stroke_count'])
            changed = True
        # stroke_count may be missing in merged; fill from joyo if available
        if getattr(r, 'stroke_count', None) is None and 'stroke_count' in info:
            setattr(r, 'stroke_count', info['stroke_count'])
            changed = True
        for key, attr in (('meanings', 'meanings'), ('onyomi', 'onyomi'), ('kunyomi', 'kunyomi')):
            vals = info.get(key)
            if vals:
                target = getattr(r, attr)
                for v in vals:
                    if v not in target:
                        target.append(v)
                        changed = True
        if changed:
            updated += 1
    return updated


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Parse KanjiVG + Kanjidic2 and merge.')
    parser.add_argument('--svg-dir', default='MangaWebTranslator/data/kanjivg', help='Directory with .svg files')
    parser.add_argument('--kanjidic', default='MangaWebTranslator/data/kanjidic2.xml.gz', help='Path to kanjidic2 xml (or .gz)')
    parser.add_argument('--out', default='MangaWebTranslator/data/kanji_merged.json', help='Output JSON file')
    parser.add_argument('--joyo-csv', default=None, help='Optional path to joyo.csv to merge additional metadata')
    parser.add_argument('--stats', action='store_true', help='Only compute and print stats for the merged records')
    args = parser.parse_args()

    print('Parsing KanjiVG from', args.svg_dir)
    vg = parse_kanjivg_dir(args.svg_dir)
    print('Parsed', len(vg), 'VG records')

    print('Parsing Kanjidic2 from', args.kanjidic)
    kd = parse_kanjidic2(args.kanjidic)
    print('Parsed', len(kd), 'KD records')

    merged = merge_kanji_records(vg, kd)
    # If a joyo CSV exists, merge its data to fill gaps (stroke_count)
    if args.joyo_csv:
        try:
            joyo_map = load_joyo_csv(args.joyo_csv)
            updated = merge_joyo_into_records(merged, joyo_map)
            print(f'Applied joyo.csv: updated {updated} records')
        except Exception as e:
            print('Failed to load/apply joyo.csv:', e)
    print('Merged records:', len(merged))

    if args.stats:
        stats = compute_merged_stats(merged)
        print('Merged stats:')
        print(json.dumps(stats, indent=2, ensure_ascii=False))
    else:
        print('Saving merged JSON to', args.out)
        save_merged_json(args.out, merged)
        print('Done')


