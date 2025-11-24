"""Kanji similarity skeleton.
Future: stroke/radical feature extraction and nearest neighbor search.
"""
from __future__ import annotations

class KanjiSimilarityEngine:
    def __init__(self, kanji_records):
        self.records = kanji_records

    def similar(self, literal: str, k: int = 8):
        """Skeleton: return empty list."""
        return []

