"""Font metrics via Pillow — the only place where fonts are measured.

Determinism requirements: the same family + pt size on the same machine always
yields identical numbers. We therefore force Pillow's BASIC layout engine
(independent of whether Raqm happens to be installed), measure at a fixed
64x scale for sub-point precision, and cache both font-file resolution and
loaded font objects.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from PIL import ImageFont

from papercanvas.core.errors import FontError

# Sub-point measurement precision: load fonts at size_pt * SCALE "pixels",
# then divide measured pixel lengths by SCALE to get typographic points.
MEASUREMENT_SCALE = 64

# Known file locations per lower-cased family name, in priority order.
_FONT_CANDIDATES: dict[str, tuple[Path, ...]] = {
    "arial": (
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
        Path("/Library/Fonts/Arial.ttf"),
        Path("/usr/share/fonts/truetype/vista/arial.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
    ),
    "helvetica": (
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("/System/Library/Fonts/Helvetica.ttc"),
        Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
    ),
    "times new roman": (
        Path("C:/Windows/Fonts/times.ttf"),
        Path("/System/Library/Fonts/Supplemental/Times New Roman.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"),
        Path("/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf"),
    ),
    "dejavu sans": (
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("C:/Windows/Fonts/DejaVuSans.ttf"),
    ),
}

# Generic fallback when the requested family is unknown on this machine.
_FALLBACKS: tuple[Path, ...] = (
    Path("C:/Windows/Fonts/arial.ttf"),
    Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
    Path("/Library/Fonts/Arial.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
)


@lru_cache(maxsize=64)
def resolve_font(family: str) -> tuple[Path, bool]:
    """Map a family name to an existing font file.

    Returns ``(path, substituted)``; ``substituted`` is True when the
    requested family was not found and a fallback was used (this drives the
    FC007 lint rule in M2). Raises FontError when nothing usable exists.
    """
    key = family.strip().lower()
    for candidate in _FONT_CANDIDATES.get(key, ()):
        if candidate.exists():
            return candidate, False
    for candidate in _FALLBACKS:
        if candidate.exists():
            return candidate, True
    raise FontError(
        f"no usable TrueType font found for family {family!r} "
        f"(searched known system locations; last resort list is empty on this machine)"
    )


@lru_cache(maxsize=256)
def _load_font(path_str: str, size_px: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path_str, size_px, layout_engine=ImageFont.Layout.BASIC)


@lru_cache(maxsize=64)
def family_of_file(path_str: str) -> str:
    """Read the family name embedded in the font file's name table."""
    font = ImageFont.truetype(path_str, 16, layout_engine=ImageFont.Layout.BASIC)
    return font.getname()[0]


@dataclass(frozen=True)
class FontMetrics:
    """Immutable measurement facade for one resolved font file.

    ``family`` is what the IR asked for; ``resolved_family`` is the family
    name embedded in the font file actually being used. They differ exactly
    when a substitution happened (e.g. Arial missing on Linux -> DejaVu
    Sans), which is what the FC007 lint rule reports.
    """

    family: str  # family as requested in the IR theme
    path: Path  # font file actually used
    substituted: bool  # True if a fallback font was used
    resolved_family: str  # family name from the font file's name table

    @classmethod
    def for_family(cls, family: str) -> FontMetrics:
        path, substituted = resolve_font(family)
        return cls(
            family=family,
            path=path,
            substituted=substituted,
            resolved_family=family_of_file(str(path)),
        )

    @property
    def is_consistent(self) -> bool:
        """True when the resolved family matches the request case-insensitively."""
        return self.resolved_family.lower() == self.family.strip().lower()

    def _font(self, size_pt: float) -> ImageFont.FreeTypeFont:
        size_px = max(1, round(size_pt * MEASUREMENT_SCALE))
        return _load_font(str(self.path), size_px)

    def width_pt(self, text: str, size_pt: float) -> float:
        """Advance width of ``text`` in typographic points."""
        if not text:
            return 0.0
        return self._font(size_pt).getlength(text) / MEASUREMENT_SCALE

    def ascent_descent_pt(self, size_pt: float) -> tuple[float, float]:
        """Ascent and descent in points (positive values)."""
        ascent_px, descent_px = self._font(size_pt).getmetrics()
        return ascent_px / MEASUREMENT_SCALE, descent_px / MEASUREMENT_SCALE
