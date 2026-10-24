"""Visual defaults shared by every renderer.

Values the IR leaves unset resolve here — all three backends (SVG, PDF,
PPTX) must agree on them so the same figure renders consistently.
"""

from __future__ import annotations

from papercanvas.core.models import Figure, Node, Theme, resolve_color

DEFAULT_FILL = "#FFFFFF"
DEFAULT_STROKE = "#444444"
DEFAULT_STROKE_WIDTH_MM = 0.35
DEFAULT_TEXT_FILL = "#000000"
GROUP_LABEL_OFFSET_MM = 4.0
GROUP_PADDING_MM = 3.0
DASH_PATTERNS = {"dashed": "3 1.5", "dotted": "0.8 1.2"}
ROUND_CORNER_MAX_MM = 3.0


def stroke_width_mm(stroke_width: float | None) -> float:
    return DEFAULT_STROKE_WIDTH_MM if stroke_width is None else stroke_width


def resolve_fill(value: str | None, theme: Theme, default: str = DEFAULT_FILL) -> str:
    if value is None:
        return default
    return resolve_color(value, theme)


def resolve_stroke(value: str | None, theme: Theme) -> str:
    if value is None:
        return DEFAULT_STROKE
    return resolve_color(value, theme)


def round_corner_mm(node: Node) -> float | None:
    """Corner radius for rounded_rect nodes (None for plain rects)."""
    if node.type != "rounded_rect":
        return None
    return min(ROUND_CORNER_MAX_MM, node.w / 4, node.h / 4)


def require_placed(fig: Figure) -> None:
    """Renderers refuse to run before a layout pass filled the coordinates."""
    from papercanvas.core.errors import RenderError

    unplaced = [node.id for node in fig.nodes if not node.is_placed]
    if unplaced:
        raise RenderError(
            f"node(s) {unplaced} have no coordinates; run `papercanvas layout` first"
        )


def fmt_number(value: float) -> str:
    """Deterministic compact number formatting (4 decimals, trailing zeros cut)."""
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text
