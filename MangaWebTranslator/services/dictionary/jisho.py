import requests


"""Jisho dictionary skeleton.
Future: HTTP client to query Jisho API for kanji/word definitions.
"""
from __future__ import annotations

class JishoClient:
    def lookup(self, query: str):
        """Skeleton: return empty result."""
        return {}

    def search_jisho(keyword: str) -> dict:
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