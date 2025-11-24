"""Core data model schema (skeleton phase).

Only dataclass definitions; no operational logic. These define the shapes of
objects the system will use in later phases.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Dict, Any

# ---- Kanji / Stroke Structures ----
@dataclass
class Stroke:
    index: int
    points: List[Tuple[float, float]]  # normalized unit-square polyline
    length: float = 0.0
    bbox: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)  # (minx, miny, maxx, maxy)
    direction_stats: Optional[Tuple[float, float, float]] = None  # (mean_angle, std_angle, straightness)
    curvature: Optional[float] = None

@dataclass
class KanjiRecord:
    codepoint: str  # hex codepoint string e.g. "6f22"
    literal: str
    strokes: List[Stroke] = field(default_factory=list)
    stroke_count_primary: int = 0
    stroke_count_alt: List[int] = field(default_factory=list)
    radical_id: Optional[int] = None
    radicals_all: List[int] = field(default_factory=list)
    on_readings: List[str] = field(default_factory=list)
    kun_readings: List[str] = field(default_factory=list)
    meanings: List[str] = field(default_factory=list)
    freq_rank: Optional[int] = None
    joyo: bool = False
    jinmeiyo: bool = False
    variant_of: Optional[str] = None
    variants: List[str] = field(default_factory=list)
    sources: Dict[str, Any] = field(default_factory=dict)
    quality_flags: List[str] = field(default_factory=list)

# ---- OCR Layout Structures ----
@dataclass
class TextLine:
    text: str
    bbox: Tuple[int, int, int, int]  # (x,y,w,h)
    confidence: Optional[float] = None
    rotation_deg: float = 0.0
    ocr_meta: Dict[str, Any] = field(default_factory=dict)

@dataclass
class TextBlock:
    lines: List[TextLine] = field(default_factory=list)
    bbox: Tuple[int, int, int, int] = (0, 0, 0, 0)
    block_type: str = "dialogue"  # placeholder categorization
    order_index: int = 0

@dataclass
class Panel:
    image_path: str
    page_number: int
    panel_index: int
    bbox: Tuple[int, int, int, int]
    blocks: List[TextBlock] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class TranslationResult:
    original: str
    translated: str
    lines_map: Dict[int, str] = field(default_factory=dict)  # line index -> translated string
    provider: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)

@dataclass
class KanjiSimilarityCandidate:
    literal: str
    distance: float
    freq_rank: Optional[int] = None
    stroke_count: Optional[int] = None
    radical_id: Optional[int] = None

