"""PDF renderer (reportlab) — true vector output with embedded TTF fonts.

Determinism: the canvas is created with ``invariant=1`` (fixed creation date
and document id), so the same IR + same fonts produce byte-identical PDFs.

Discipline: text lines and their positions come from TextLayout verbatim —
this renderer never wraps or measures text; every mm→pt conversion goes
through core.geometry.
"""

from __future__ import annotations

import io
import math
import re

from reportlab.lib.colors import HexColor
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

from papercanvas.core.errors import RenderError
from papercanvas.core.geometry import mm_to_pt, pt_to_mm
from papercanvas.core.models import Figure
from papercanvas.layout.routing import Point, route_orthogonal
from papercanvas.render.style import (
    DASH_PATTERNS,
    DEFAULT_FILL,
    DEFAULT_TEXT_FILL,
    GROUP_PADDING_MM,
    require_placed,
    resolve_fill,
    resolve_stroke,
    round_corner_mm,
    stroke_width_mm,
)
from papercanvas.text.text_layout import LINE_SPACING, TextLayout, wrap_text

_REGISTERED_FONTS: dict[tuple[str, str], str] = {}

# Arrowhead proportions mirror the SVG marker geometry (markerWidth 6 on a
# 10-unit viewBox with refX 9 -> 5.4 x stroke width long, +/-3 x stroke wide).
_ARROW_LENGTH_STROKE_WIDTHS = 5.4
_ARROW_HALF_WIDTH_STROKE_WIDTHS = 3.0


def _hex6(value: str) -> HexColor:
    h = value.lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    return HexColor(f"#{h}")


def _register_font(font_name: str, path) -> str:
    # key includes the resolved file: two different families can sanitize to
    # the same reportlab name but must embed their own font files
    key = (font_name, str(path))
    if key not in _REGISTERED_FONTS:
        pdfmetrics.registerFont(TTFont(font_name, str(path)))
        _REGISTERED_FONTS[key] = font_name
    return font_name


def _font_name(family: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", family)
    return f"papercanvas-{safe}"


def _set_dash(canvas: Canvas, dash: str | None) -> None:
    if dash and dash in DASH_PATTERNS:
        on, off = DASH_PATTERNS[dash].split()
        canvas.setDash([mm_to_pt(float(on)), mm_to_pt(float(off))])
    else:
        canvas.setDash()


def _apply_arrow(
    canvas: Canvas,
    tail: Point,
    tip: Point,
    color: str,
    stroke_pt: float,
    to_page,
) -> None:
    """Filled arrowhead triangle with the tip exactly on the path vertex."""
    dx = mm_to_pt(tip.x) - mm_to_pt(tail.x)
    dy = mm_to_pt(tip.y) - mm_to_pt(tail.y)
    norm = math.hypot(dx, dy) or 1.0
    ux, uy = dx / norm, dy / norm
    length = _ARROW_LENGTH_STROKE_WIDTHS * stroke_pt
    half = _ARROW_HALF_WIDTH_STROKE_WIDTHS * stroke_pt
    tip_x, tip_y = to_page(tip.x, tip.y)
    base_x, base_y = tip_x - ux * length, tip_y - uy * length
    px, py = -uy, ux
    path = canvas.beginPath()
    path.moveTo(tip_x, tip_y)
    path.lineTo(base_x + px * half, base_y + py * half)
    path.lineTo(base_x - px * half, base_y - py * half)
    path.close()
    canvas.setFillColor(HexColor(color))
    canvas.drawPath(path, stroke=0, fill=1)


def render_pdf(fig: Figure, text_layout: TextLayout) -> bytes:
    """Render the laid-out figure to a deterministic, vector PDF (bytes)."""
    require_placed(fig)
    theme = fig.theme
    font_name = _register_font(_font_name(theme.font_family), text_layout.metrics.path)

    page_w = mm_to_pt(fig.canvas.width)
    page_h = mm_to_pt(fig.canvas.height)

    def to_page(x_mm: float, y_mm: float) -> tuple[float, float]:
        # IR y grows downward; PDF y grows upward from the bottom-left corner
        return mm_to_pt(x_mm), page_h - mm_to_pt(y_mm)

    buffer = io.BytesIO()
    # invariant=1 pins creation date + document id; pageCompression=0 keeps
    # the content stream readable (figures are small, fonts stay compressed)
    canvas = Canvas(buffer, pagesize=(page_w, page_h), invariant=1, pageCompression=0)
    canvas.setTitle(fig.id)

    # background
    canvas.setFillColor(_hex6(resolve_fill(theme.background, theme, DEFAULT_FILL)))
    canvas.rect(0, 0, page_w, page_h, stroke=0, fill=1)

    # groups first (background boxes), then edges, then nodes on top —
    # the same paint order as the SVG renderer
    for group in fig.groups:
        children = [fig.node(child_id) for child_id in group.children]
        missing = [
            c.id if c is not None else "<missing>"
            for c in children
            if c is None or not c.is_placed
        ]
        if missing:
            raise RenderError(
                f"group {group.id!r} contains unplaced or missing node(s) {missing}; "
                f"run `papercanvas layout` first"
            )
        x0 = min(c.x for c in children) - GROUP_PADDING_MM
        y0 = min(c.y for c in children) - GROUP_PADDING_MM
        x1 = max(c.x + c.w for c in children) + GROUP_PADDING_MM
        y1 = max(c.y + c.h for c in children) + GROUP_PADDING_MM
        gx, gy = to_page(x0, y1)
        gw, gh = mm_to_pt(x1 - x0), mm_to_pt(y1 - y0)
        stroke = resolve_stroke(group.style.stroke, theme)
        canvas.setStrokeColor(_hex6(stroke))
        canvas.setLineWidth(mm_to_pt(stroke_width_mm(group.style.stroke_width)))
        _set_dash(canvas, group.style.stroke_dash)
        group_fill = resolve_fill(group.style.fill, theme, DEFAULT_FILL)
        if group.style.fill is None:
            canvas.rect(gx, gy, gw, gh, stroke=1, fill=0)
        else:
            canvas.setFillColor(_hex6(group_fill))
            canvas.rect(gx, gy, gw, gh, stroke=1, fill=1)
        if group.label:
            # label sits ABOVE the dashed border, left-aligned (paper-figure
            # convention); it never wraps (group labels are short) but honors
            # explicit — — the line set still comes from the TextLayout
            # module. A block that would leave the canvas clamps down inside
            # the border strip instead.
            lines = wrap_text(group.label, math.inf, text_layout.metrics, theme.font_size_pt)
            n_lines = len(lines)
            ascent_mm = pt_to_mm(
                text_layout.metrics.ascent_descent_pt(theme.font_size_pt)[0]
            )
            line_height_mm = pt_to_mm(theme.font_size_pt * LINE_SPACING)
            first_baseline = max(
                y0 - 1.0 - (n_lines - 1) * line_height_mm,
                0.5 + ascent_mm + (n_lines - 1) * line_height_mm,
            )
            for index, line_text in enumerate(lines):
                baseline_mm = first_baseline - (n_lines - 1 - index) * line_height_mm
                tx, ty = to_page(x0 + 1.5, baseline_mm)
                canvas.drawString(tx, ty, line_text)

    for edge in fig.edges:
        source = fig.node(edge.source)
        target = fig.node(edge.target)
        if source is None or target is None:
            raise RenderError(
                f"edge {edge.id!r} references missing node(s) "
                f"{[n for n in (edge.source, edge.target) if fig.node(n) is None]}"
            )
        points = route_orthogonal(source, edge.source_port, target, edge.target_port)
        stroke = resolve_stroke(edge.style.stroke, theme)
        stroke_pt = mm_to_pt(stroke_width_mm(edge.style.stroke_width))
        canvas.setStrokeColor(_hex6(stroke))
        canvas.setLineWidth(stroke_pt)
        _set_dash(canvas, None)
        path = canvas.beginPath()
        path.moveTo(*to_page(points[0].x, points[0].y))
        for point in points[1:]:
            path.lineTo(*to_page(point.x, point.y))
        canvas.drawPath(path, stroke=1, fill=0)
        if edge.style.arrow in ("end", "both") and len(points) >= 2:
            _apply_arrow(canvas, points[-2], points[-1], stroke, stroke_pt, to_page)
        if edge.style.arrow in ("start", "both") and len(points) >= 2:
            _apply_arrow(canvas, points[1], points[0], stroke, stroke_pt, to_page)

    for node in fig.nodes:
        nx, ny_top = to_page(node.x, node.y + node.h)
        nw, nh = mm_to_pt(node.w), mm_to_pt(node.h)
        canvas.setFillColor(_hex6(resolve_fill(node.style.fill, theme, DEFAULT_FILL)))
        canvas.setStrokeColor(_hex6(resolve_stroke(node.style.stroke, theme)))
        canvas.setLineWidth(mm_to_pt(stroke_width_mm(node.style.stroke_width)))
        _set_dash(canvas, node.style.stroke_dash)
        radius = round_corner_mm(node)
        if radius is not None:
            canvas.roundRect(nx, ny_top, nw, nh, mm_to_pt(radius), stroke=1, fill=1)
        else:
            canvas.rect(nx, ny_top, nw, nh, stroke=1, fill=1)

        if node.label:
            result = text_layout.layout_label(
                node.label,
                font_family=theme.font_family,
                font_size_pt=theme.font_size_pt,
                box_w_mm=node.w,
                box_h_mm=node.h,
            )
            canvas.setFillColor(_hex6(DEFAULT_TEXT_FILL))
            canvas.setFont(font_name, theme.font_size_pt)
            for line in result.lines:
                tx, ty = to_page(node.x + line.x_mm, node.y + line.y_mm)
                canvas.drawString(tx, ty, line.text)

    canvas.showPage()
    canvas.save()
    return buffer.getvalue()
