"""Unified text layer: Pillow-backed font metrics + the one and only TextLayout.

Engineering constraint 2: every renderer (SVG now, PDF/PPTX in M2) consumes
:class:`TextLayoutResult` verbatim — line breaking, line height and glyph
positioning are decided here and nowhere else.
"""

from papercanvas.text.text_layout import (
    LINE_SPACING,
    NODE_PADDING_H_MM,
    NODE_PADDING_V_MM,
    PlacedLine,
    TextLayout,
    TextLayoutResult,
)
from papercanvas.text.text_metrics import (
    FontMetrics,
    family_of_file,
    file_covers,
    resolve_font,
    resolve_font_for_text,
)

__all__ = [
    "LINE_SPACING",
    "NODE_PADDING_H_MM",
    "NODE_PADDING_V_MM",
    "FontMetrics",
    "PlacedLine",
    "TextLayout",
    "TextLayoutResult",
    "family_of_file",
    "file_covers",
    "resolve_font",
    "resolve_font_for_text",
]
