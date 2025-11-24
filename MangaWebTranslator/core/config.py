"""Configuration schema (skeleton phase).
No persistence functions are provided yet; only dataclass structures.
"""
from __future__ import annotations
from dataclasses import dataclass

@dataclass
class OCRConfig:
    language: str = "jpn"
    tesseract_cmd: str | None = None
    psm: int = 6
    oem: int = 3
    vertical_detection: bool = True

@dataclass
class TranslationConfig:
    provider: str = "google"
    api_key: str | None = None
    batch_size: int = 20

@dataclass
class SimilarityConfig:
    max_candidates: int = 8
    method: str = "engineered"  # future: cnn

@dataclass
class PathsConfig:
    data_root: str = "data"
    kanji_root: str = "data/kanji"
    panels_root: str = "data/panels"
    export_root: str = "data/exports"

@dataclass
class AppConfig:
    ocr: OCRConfig = OCRConfig()
    translation: TranslationConfig = TranslationConfig()
    similarity: SimilarityConfig = SimilarityConfig()
    paths: PathsConfig = PathsConfig()
