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
# Every file listed here must genuinely carry that family name — files that
# merely look similar (metric-compatible substitutes such as DejaVu for
# Arial) belong in _FALLBACKS, otherwise substitution goes unreported.
_FONT_CANDIDATES: dict[str, tuple[Path, ...]] = {
    "arial": (
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
        Path("/Library/Fonts/Arial.ttf"),
        Path("/usr/share/fonts/truetype/vista/arial.ttf"),
    ),
    "helvetica": (
        Path("/System/Library/Fonts/Helvetica.ttc"),
        Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
    ),
    "times new roman": (
        Path("C:/Windows/Fonts/times.ttf"),
        Path("/System/Library/Fonts/Supplemental/Times New Roman.ttf"),
    ),
    "dejavu sans": (
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("C:/Windows/Fonts/DejaVuSans.ttf"),
    ),
}

# Generic fallback when the requested family is unknown on this machine.
# Anything resolved through this chain is BY DEFINITION a substitution.
_FALLBACKS: tuple[Path, ...] = (
    Path("C:/Windows/Fonts/arial.ttf"),
    Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
    Path("/Library/Fonts/Arial.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
)

# CJK-capable fonts, consulted only when the requested font cannot cover the
# figure's glyphs. TrueType-flavored entries (.ttf/.ttc) can be embedded by
# the PDF renderer; CFF-flavored (.otf) are measurement-only.
_CJK_CANDIDATES: tuple[Path, ...] = (
    Path("C:/Windows/Fonts/simhei.ttf"),
    Path("C:/Windows/Fonts/msyh.ttc"),
    Path("C:/Windows/Fonts/simsun.ttc"),
    Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
    Path("/System/Library/Fonts/STHeiti Light.ttc"),
    Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"),
    Path("/usr/share/fonts/truetype/wenquanyi/wqy-zenhei.ttc"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
)


def _embedded_family_is(path: Path, requested_lower: str) -> bool:
    """True when the file's embedded family name matches the request.

    Unreadable font files are skipped rather than trusted.
    """
    try:
        return family_of_file(str(path)).lower() == requested_lower
    except Exception:  # noqa: BLE001 - any parse failure disqualifies the file
        return False


@lru_cache(maxsize=64)
def resolve_font(family: str) -> tuple[Path, bool]:
    """Map a family name to an existing font file.

    Returns ``(path, substituted)``. A candidate file counts as the requested
    family only when its embedded name agrees (case-insensitively); anything
    reached through the fallback chain is by definition a substitution. This
    keeps ``substituted`` and :attr:`FontMetrics.is_consistent` in lockstep
    on every platform. Raises FontError when nothing usable exists.
    """
    requested = family.strip().lower()
    for candidate in _FONT_CANDIDATES.get(requested, ()):
        if candidate.exists() and _embedded_family_is(candidate, requested):
            return candidate, False
    for candidate in _FALLBACKS:
        if candidate.exists():
            return candidate, True
    raise FontError(
        f"no usable TrueType font found for family {family!r} "
        f"(searched known system locations; last resort list is empty on this machine)"
    )


@lru_cache(maxsize=128)
def file_covers(path_str: str, text_sample: str) -> bool:
    """True when the font's cmap covers every codepoint in ``text_sample``.

    Requires fontTools; when it cannot read the file the answer is False
    (never silently claim coverage).
    """
    if not text_sample:
        return True
    try:
        from fontTools.ttLib import TTFont as FontFile

        font_file = FontFile(path_str, fontNumber=0, lazy=True)
        best_cmap = font_file.getBestCmap()
        # whitespace never appears in cmaps; only real glyphs matter
        return all(ord(ch) in best_cmap for ch in text_sample if not ch.isspace())
    except Exception:  # noqa: BLE001 - unreadable font == does not cover
        return False


@lru_cache(maxsize=64)
def file_is_true_type(path_str: str) -> bool:
    """True when the file is TrueType-flavored (glyph outlines reportlab's
    TTFont can embed). CFF/PostScript-flavored fonts (.otf, Noto CJK) cannot
    be embedded by the PDF renderer."""
    try:
        from fontTools.ttLib import TTFont as FontFile

        font_file = FontFile(path_str, fontNumber=0, lazy=True)
        true_type_magic = chr(0) + chr(1) + chr(0) + chr(0)
        return font_file.sfntVersion == true_type_magic
    except Exception:  # noqa: BLE001 - unreadable == not embeddable
        return False


@lru_cache(maxsize=64)
def resolve_font_for_text(family: str, text: str) -> tuple[Path, bool, str | None]:
    """Like :func:`resolve_font`, but prefers a font covering every glyph.

    Returns ``(path, substituted, reason)``. When the requested font misses
    glyphs (CJK on a Latin-only install, for instance) the CJK candidate
    table is searched for maximum coverage; ``reason`` explains the
    substitution for FC007.
    """
    path, substituted = resolve_font(family)
    uncovered = {
        ch for ch in text if not ch.isspace() and not file_covers(str(path), ch)
    }
    if not uncovered:
        return path, substituted, ("is not installed" if substituted else None)

    # partial coverage beats zero coverage: pick the candidate covering the
    # most of the still-uncovered set (e.g. a CJK font for 视频 even when an
    # emoji remains uncovered elsewhere)
    best_path = None
    best_count = 0
    for candidate in _CJK_CANDIDATES:
        if not candidate.exists():
            continue
        count = sum(1 for ch in uncovered if file_covers(str(candidate), ch))
        if count > best_count:
            best_path, best_count = candidate, count

    if best_path is not None and best_count > 0:
        return best_path, True, "does not cover all glyphs in this figure"

    # nothing better exists on this machine: keep the primary font and let
    # FC007 warn about the uncovered glyphs
    return path, True, "does not cover all glyphs in this figure and no CJK font is installed"


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
    substitution_reason: str | None = None  # why the substitute was picked

    @classmethod
    def for_text(cls, family: str, text: str) -> FontMetrics:
        """Resolve for the given text: picks a glyph-covering font when the
        requested one cannot render some of it (e.g. CJK labels)."""
        path, substituted, reason = resolve_font_for_text(family, text)
        return cls(
            family=family,
            path=path,
            substituted=substituted,
            resolved_family=family_of_file(str(path)),
            substitution_reason=reason,
        )

    @classmethod
    def for_family(cls, family: str) -> FontMetrics:
        """Resolve without glyph-coverage considerations (ASCII-only figures)."""
        return cls.for_text(family, "")

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
