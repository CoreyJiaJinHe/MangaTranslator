import requests
from pathlib import Path
import json
import os
import time
from typing import Dict, List, Optional


class FileLock:
    """Simple file lock using atomic creation of a directory for short critical sections."""
    def __init__(self, lock_path: Path, retry_delay: float = 0.05, timeout: float = 5.0):
        self.lock_path = Path(lock_path)
        self.retry_delay = retry_delay
        self.timeout = timeout
        self._locked = False

    def __enter__(self):
        start = time.time()
        while True:
            try:
                os.mkdir(str(self.lock_path))
                self._locked = True
                return self
            except FileExistsError:
                if (time.time() - start) > self.timeout:
                    raise TimeoutError(f"Timeout acquiring lock {self.lock_path}")
                time.sleep(self.retry_delay)

    def __exit__(self, exc_type, exc, tb):
        if self._locked:
            try:
                os.rmdir(str(self.lock_path))
            except Exception:
                pass
            finally:
                self._locked = False

"""Jisho dictionary.
HTTP client to query Jisho API for kanji/word definitions.
"""
class JishoClient:
    def search_jisho(self, keyword: str) -> dict:
        """
        Query Jisho.org API for a kanji/word. Returns parsed JSON response or error info.
        """
        if not isinstance(keyword, str):
            return {'error': 'Input must be a string'}
        keyword = keyword.strip()
        if not keyword:
            return {'error': 'Keyword is empty'}
        # Optionally: filter/escape problematic characters
        url = f'https://jisho.org/api/v1/search/words?keyword={requests.utils.quote(keyword)}'
        try:
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            return data
        except Exception as e:
            return {'error': str(e)}

# JishoStorage provides methods for compacting, saving, loading, and indexing Jisho API response data for efficient storage and retrieval.
class JishoStorage():
    def _compact_jisho_item(self,item: Dict) -> Dict:
        """Return a compact representation of a Jisho API item suitable for storage."""
        slug = item.get('slug') or item.get('word') or ''
        compact = {'slug': slug}
        if 'is_common' in item:
            compact['is_common'] = bool(item.get('is_common'))
        if 'tags' in item:
            compact['tags'] = list(item.get('tags') or [])

        jap = []
        seen_j = set()
        for j in item.get('japanese', []) if isinstance(item.get('japanese', []), list) else []:
            w = j.get('word') if isinstance(j, dict) else (j if isinstance(j, str) else None)
            r = j.get('reading') if isinstance(j, dict) else None
            key = (w or '', r or '')
            if key in seen_j:
                continue
            seen_j.add(key)
            jap.append({'word': w, 'reading': r})
        if jap:
            compact['japanese'] = jap

        senses = []
        seen_s = set()
        for s in item.get('senses', []) if isinstance(item.get('senses', []), list) else []:
            defs = list(s.get('english_definitions') or [])
            norm = tuple(d.strip() for d in defs)
            if norm in seen_s:
                continue
            seen_s.add(norm)
            senses.append({'english_definitions': defs})
        if senses:
            compact['senses'] = senses

        return compact
    
    def save_jisho_response(self,response: Dict, json_path: Optional[str | Path] = None, ndjson_path: Optional[str | Path] = None) -> None:
        """Save Jisho API response items into both a JSON array and NDJSON file.

        Deduplication: by `slug` field. If slug already exists in JSON array, new item is skipped.
        No timestamps are stored.
        """
        if not response or not isinstance(response, dict):
            return

        data = response.get('data') or []
        if not isinstance(data, list) or not data:
            return

        root = Path(__file__).resolve().parents[2] / 'data'
        json_path = Path(json_path) if json_path else root / 'jisho_results.json'
        ndjson_path = Path(ndjson_path) if ndjson_path else root / 'jisho_results.ndjson'
        json_path.parent.mkdir(parents=True, exist_ok=True)

        lockfile = json_path.with_suffix(json_path.suffix + '.lock')

        with FileLock(lockfile):
            # load existing array if present
            existing: List[Dict] = []
            if json_path.exists():
                try:
                    with json_path.open('r', encoding='utf8') as fh:
                        existing = json.load(fh) or []
                except Exception:
                    existing = []

            slug_set = {e.get('slug') for e in existing if isinstance(e, dict) and e.get('slug')}

            added = 0
            for item in data:
                try:
                    compact = self._compact_jisho_item(item)
                except Exception:
                    continue
                slug = compact.get('slug') or ''
                if slug in slug_set:
                    continue
                existing.append(compact)
                slug_set.add(slug)
                added += 1
                # append to ndjson
                try:
                    ndjson_path.parent.mkdir(parents=True, exist_ok=True)
                    with ndjson_path.open('a', encoding='utf8') as nf:
                        nf.write(json.dumps(compact, ensure_ascii=False) + '\n')
                except Exception:
                    pass

            if added:
                # atomic write for json_path
                tmp = json_path.with_suffix(json_path.suffix + '.tmp')
                try:
                    with tmp.open('w', encoding='utf8') as fh:
                        json.dump(existing, fh, ensure_ascii=False, indent=2)
                    os.replace(str(tmp), str(json_path))
                    # rebuild index after writing
                    try:
                        self.rebuild_jisho_index(json_path=json_path)
                    except Exception:
                        pass
                finally:
                    try:
                        if tmp.exists():
                            tmp.unlink()
                    except Exception:
                        pass
            
    def load_jisho_results(json_path: Optional[str | Path] = None) -> List[Dict]:
        root = Path(__file__).resolve().parents[2] / 'data'
        json_path = Path(json_path) if json_path else root / 'jisho_results.json'
        if not json_path.exists():
            return []
        try:
            with json_path.open('r', encoding='utf8') as fh:
                return json.load(fh) or []
        except Exception:
            return []


    def rebuild_jisho_index(json_path: Optional[str | Path] = None, index_path: Optional[str | Path] = None) -> dict:
        """Rebuild a simple slug -> position index from the JSON array file and write it to disk.

        The index format is a JSON object mapping slug -> integer index in the array.
        Returns the in-memory index dict.
        """
        root = Path(__file__).resolve().parents[2] / 'data'
        json_path = Path(json_path) if json_path else root / 'jisho_results.json'
        index_path = Path(index_path) if index_path else root / 'jisho_index.json'
        idx: dict = {}
        if not json_path.exists():
            # write empty index
            try:
                index_path.parent.mkdir(parents=True, exist_ok=True)
                with index_path.open('w', encoding='utf8') as fh:
                    json.dump({}, fh, ensure_ascii=False, indent=2)
            except Exception:
                pass
            return idx

        try:
            with json_path.open('r', encoding='utf8') as fh:
                arr = json.load(fh) or []
        except Exception:
            arr = []

        for i, obj in enumerate(arr):
            if isinstance(obj, dict):
                slug = obj.get('slug')
                if slug:
                    # only record first occurrence
                    if slug not in idx:
                        idx[slug] = i

        try:
            index_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = index_path.with_suffix(index_path.suffix + '.tmp')
            with tmp.open('w', encoding='utf8') as fh:
                json.dump(idx, fh, ensure_ascii=False, indent=2)
            os.replace(str(tmp), str(index_path))
        except Exception:
            pass
        return idx


    def load_jisho_index(index_path: Optional[str | Path] = None) -> dict:
        root = Path(__file__).resolve().parents[2] / 'data'
        index_path = Path(index_path) if index_path else root / 'jisho_index.json'
        if not index_path.exists():
            return {}
        try:
            with index_path.open('r', encoding='utf8') as fh:
                return json.load(fh) or {}
        except Exception:
            return {}




def debug_fetch_and_compact(url: Optional[str] = None, keyword: Optional[str] = None, sample: int = 5):
    jisho=JishoClient()
    jisho_storage=JishoStorage()
    """Debug helper: fetch a Jisho API URL (or build from keyword), compact results, and print a summary."""
    if url is None:
        if not keyword:
            raise ValueError('Either url or keyword must be provided')
        url = f"https://jisho.org/api/v1/search/words?keyword={requests.utils.quote(keyword)}"
    print('Fetching:', url)
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print('Fetch failed:', e)
        return None

    meta = data.get('meta') or {}
    status = meta.get('status')
    print('API status:', status)
    items = data.get('data') or []
    print('Total items returned:', len(items))

    # Attempt to save the raw response into storage and report delta
    try:
        before = jisho_storage.load_jisho_results()
        before_count = len(before)
    except Exception:
        before_count = 0
    try:
        # save_jisho_response expects the full response dict
        jisho.save_jisho_response(data)
    except Exception as e:
        print('Save attempt failed:', e)
    try:
        after_count = len(jisho_storage.load_jisho_results())
    except Exception:
        after_count = before_count
    print(f"Saved: {after_count - before_count} new compacted items (JSON/NDJSON updated)")

    comps = []
    for it in items:
        try:
            c = jisho._compact_jisho_item(it)
        except Exception:
            continue
        comps.append(c)

    print('\nCompacted', len(comps), 'items (showing first', min(sample, len(comps)), ')')
    return {'meta': meta, 'items': comps}