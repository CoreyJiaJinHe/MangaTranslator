"""Translation service skeleton.
Future: implement Google Cloud Translate integration.
"""
from __future__ import annotations

class GoogleTranslateClient:
    def __init__(self, api_key: str | None):
        self.api_key = api_key

    def translate_lines(self, lines, source: str = "ja", target: str = "en"):
        """Skeleton: echo lines without translation."""
        return list(lines)

