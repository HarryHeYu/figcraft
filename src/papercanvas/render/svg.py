"""SVG renderer — deterministic, editable, pure build product.

Invariants (plan §5 + constraint 6):
- strictly read-only: never touches the IR file;
- no ``<image>``, no scripts, no timestamps, nothing that varies between runs;
- same IR + same fonts + same version => byte-identical SVG;
- labels stay editable ``<text>`` elements, one per TextLayout line, and line
  breaking decisions are consumed from TextLayout, never made here;
- the page is the mm canvas: ``viewBox="0 0 W H"`` with 1 user unit = 1 mm,
  so all geometry, stroke widths and font sizes are written in mm
  (conversions come from core.geometry only).
"""

from __future__ import annotations

from lxml import etree

from papercanvas.core.errors import RenderError
from papercanvas.core.geometry import pt_to_mm
from papercanvas.core.models import Figure, Node, resolve_color
from papercanvas.layout.routing import Point, route_orthogonal
from papercanvas.render.style import (
    DASH_PATTERNS,
    DEFAULT_FILL,
    DEFAULT_STROKE,
    DEFAULT_TEXT_FILL,
    GROUP_LABEL_OFFSET_MM,  # noqa: F401 - re-exported for tests/contract use
    GROUP_PADDING_MM,  # noqa: F401 - re-exported for tests/contract use
    round_corner_mm,
    stroke_width_mm,
)
from papercanvas.render.style import (
    fmt_number as _fmt,
)
from papercanvas.render.style import (
    require_placed as _require_placed,
)
from papercanvas.text.text_layout import LINE_SPACING, TextLayout

SVG_NS = "http://www.w3.org/2000/svg"


def _q(name: str) -> str:
    return f"{{{SVG_NS}}}{name}"


def _resolve(value: str | None, theme, default: str) -> str:
    if value is None:
        return default
    return resolve_color(value, theme)


def _arrow_markers(fig: Figure, parent, color_of) -> dict[str, str]:
    """One arrow marker per distinct edge stroke color, in edge order."""
    markers: dict[str, str] = {}
    defs = etree.SubElement(parent, _q("defs"))
    for edge in fig.edges:
        color = color_of(edge)
        if edge.style.arrow == "none" or color in markers:
            continue
        marker_id = f"pc-arrow-{len(markers)}"
        markers[color] = marker_id
        marker = etree.SubElement(
            defs,
            _q("marker"),
            id=marker_id,
            viewBox="0 0 10 10",
            refX="9",
            refY="5",
            markerWidth="6",
            markerHeight="6",
            orient="auto-start-reverse",
        )
        etree.SubElement(
            marker, _q("path"), d="M 0 0 L 10 5 L 0 10 z", fill=color
        )
    return markers


def _polyline_points(points: list[Point]) -> str:
    return " ".join(f"{_fmt(p.x)},{_fmt(p.y)}" for p in points)


def _round_corner(node: Node) -> str | None:
    radius = round_corner_mm(node)
    return None if radius is None else _fmt(radius)


def render_svg(fig: Figure, text_layout: TextLayout) -> bytes:
    """Render the laid-out figure to a deterministic SVG document (bytes)."""
    _require_placed(fig)
    theme = fig.theme

    root = etree.Element(
        _q("svg"),
        nsmap={None: SVG_NS},
        width=f"{_fmt(fig.canvas.width)}mm",
        height=f"{_fmt(fig.canvas.height)}mm",
        viewBox=f"0 0 {_fmt(fig.canvas.width)} {_fmt(fig.canvas.height)}",
    )

    def color_of_style(value: str | None, default: str) -> str:
        return _resolve(value, theme, default)

    markers = _arrow_markers(
        fig,
        root,
        lambda edge: color_of_style(edge.style.stroke, DEFAULT_STROKE),
    )

    # background
    etree.SubElement(
        root,
        _q("rect"),
        id="background",
        x="0",
        y="0",
        width=_fmt(fig.canvas.width),
        height=_fmt(fig.canvas.height),
        fill=_resolve(theme.background, theme, DEFAULT_FILL),
    )

    # groups first (background boxes), then edges, then nodes on top
    for group in fig.groups:
        children = [fig.node(child_id) for child_id in group.children]
        _require_placed_children(group.id, children)
        x0 = min(c.x for c in children) - GROUP_PADDING_MM
        y0 = min(c.y for c in children) - GROUP_PADDING_MM
        x1 = max(c.x + c.w for c in children) + GROUP_PADDING_MM
        y1 = max(c.y + c.h for c in children) + GROUP_PADDING_MM
        attrs = {
            "id": f"group:{group.id}",
            "x": _fmt(x0),
            "y": _fmt(y0),
            "width": _fmt(x1 - x0),
            "height": _fmt(y1 - y0),
            "fill": color_of_style(group.style.fill, "none"),
            "stroke": color_of_style(group.style.stroke, DEFAULT_STROKE),
            "stroke-width": _fmt(stroke_width_mm(group.style.stroke_width)),
        }
        dash = group.style.stroke_dash
        if dash and dash in DASH_PATTERNS:
            attrs["stroke-dasharray"] = DASH_PATTERNS[dash]
        etree.SubElement(root, _q("rect"), **attrs)
        if group.label:
            # label sits ABOVE the dashed border (paper-figure convention) so
            # it never collides with the children; line breaks still come
            # from TextLayout, and the block is anchored by its last baseline
            result = text_layout.layout_label(
                group.label,
                font_family=theme.font_family,
                font_size_pt=theme.font_size_pt,
                box_w_mm=x1 - x0,
                box_h_mm=GROUP_LABEL_OFFSET_MM,
                padding_h_mm=GROUP_PADDING_MM,
                padding_v_mm=0.5,
            )
            n_lines = len(result.lines)
            ascent_mm = pt_to_mm(
                text_layout.metrics.ascent_descent_pt(theme.font_size_pt)[0]
            )
            line_height_mm = pt_to_mm(theme.font_size_pt * LINE_SPACING)
            first_baseline = max(
                y0 - 1.0 - (n_lines - 1) * line_height_mm,
                0.5 + ascent_mm + (n_lines - 1) * line_height_mm,
            )
            for index, line in enumerate(result.lines):
                baseline_mm = first_baseline - (n_lines - 1 - index) * line_height_mm
                etree.SubElement(
                    root,
                    _q("text"),
                    x=_fmt(x0 + line.x_mm),
                    y=_fmt(baseline_mm),
                    **_text_attrs(theme),
                ).text = line.text

    for edge in fig.edges:
        source = fig.node(edge.source)
        target = fig.node(edge.target)
        if source is None or target is None:
            raise RenderError(
                f"edge {edge.id!r} references missing node(s) "
                f"{[n for n in (edge.source, edge.target) if fig.node(n) is None]}"
            )
        points = route_orthogonal(source, edge.source_port, target, edge.target_port)
        stroke = color_of_style(edge.style.stroke, DEFAULT_STROKE)
        attrs = {
            "id": f"edge:{edge.id}",
            "points": _polyline_points(points),
            "fill": "none",
            "stroke": stroke,
            "stroke-width": _fmt(stroke_width_mm(edge.style.stroke_width)),
        }
        if edge.style.arrow in ("end", "both") and stroke in markers:
            attrs["marker-end"] = f"url(#{markers[stroke]})"
        if edge.style.arrow in ("start", "both") and stroke in markers:
            attrs["marker-start"] = f"url(#{markers[stroke]})"
        etree.SubElement(root, _q("polyline"), **attrs)

    for node in fig.nodes:
        attrs = {
            "id": f"node:{node.id}",
            "x": _fmt(node.x),
            "y": _fmt(node.y),
            "width": _fmt(node.w),
            "height": _fmt(node.h),
            "fill": color_of_style(node.style.fill, DEFAULT_FILL),
            "stroke": color_of_style(node.style.stroke, DEFAULT_STROKE),
            "stroke-width": _fmt(stroke_width_mm(node.style.stroke_width)),
        }
        corner = _round_corner(node)
        if corner is not None:
            attrs["rx"] = corner
        dash = node.style.stroke_dash
        if dash and dash in DASH_PATTERNS:
            attrs["stroke-dasharray"] = DASH_PATTERNS[dash]
        etree.SubElement(root, _q("rect"), **attrs)

        if node.label:
            result = text_layout.layout_label(
                node.label,
                font_family=theme.font_family,
                font_size_pt=theme.font_size_pt,
                box_w_mm=node.w,
                box_h_mm=node.h,
            )
            for line in result.lines:
                text = etree.SubElement(
                    root,
                    _q("text"),
                    x=_fmt(node.x + line.x_mm),
                    y=_fmt(node.y + line.y_mm),
                    **_text_attrs(theme),
                )
                text.text = line.text

    return etree.tostring(
        etree.ElementTree(root), xml_declaration=True, encoding="UTF-8", pretty_print=True
    )


def _text_attrs(theme) -> dict[str, str]:
    return {
        "font-family": theme.font_family,
        "font-size": _fmt(pt_to_mm(theme.font_size_pt)),
        "fill": DEFAULT_TEXT_FILL,
    }


def _require_placed_children(group_id: str, children: list[Node | None]) -> None:
    missing = [
        "<missing>" if child is None else child.id
        for child in children
        if child is None or not child.is_placed
    ]
    if missing:
        raise RenderError(
            f"group {group_id!r} contains unplaced or missing node(s) {missing}; "
            f"run `papercanvas layout` first"
        )
