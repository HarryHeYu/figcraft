"""Unit conversions — the only place in the codebase where units meet.

All geometry inside PaperCanvas is millimetres; font sizes are points. Every
conversion between mm, pt, px and EMU must go through this module; renderers
and layout code must never embed their own conversion factors.
"""

from __future__ import annotations

PT_PER_MM = 72.0 / 25.4  # 1 mm = 2.834645669... pt
PX_PER_MM = 96.0 / 25.4  # CSS reference pixel at 96 dpi
EMU_PER_MM = 36000.0  # OOXML drawingml: 914400 EMU per inch


def mm_to_pt(mm: float) -> float:
    return mm * PT_PER_MM


def pt_to_mm(pt: float) -> float:
    return pt / PT_PER_MM


def mm_to_px(mm: float) -> float:
    return mm * PX_PER_MM


def px_to_mm(px: float) -> float:
    return px / PX_PER_MM


def mm_to_emu(mm: float) -> int:
    return round(mm * EMU_PER_MM)
