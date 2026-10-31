"""Column-aware layout presets for paper figure sizing.

`layout_two_column` wraps nodes into a 2-column grid; `layout_single_column`
is a vertical layout constrained to the given width. Both recompute the
canvas to content + margin, honouring the target width when provided.
"""

from __future__ import annotations

from papercanvas.core.models import Figure
from papercanvas.layout.sizes import auto_size_nodes, text_layout_for_theme

#: canonical journal column widths (mm)
SINGLE_COLUMN_MM = 89.0
DOUBLE_COLUMN_MM = 183.0

#: channel between nodes in the grid (mm)
GRID_GAP_H_MM = 10.0
GRID_GAP_V_MM = 8.0


def layout_two_column(
    fig: Figure, *, target_width_mm: float = DOUBLE_COLUMN_MM
) -> Figure:
    """Arrange nodes in a 2-column grid that fits within ``target_width_mm``.

    Nodes fill column-major (down column 1, then column 2).  The canvas is
    recomputed as content + margin.
    """
    layout = text_layout_for_theme(fig)
    sized = auto_size_nodes(fig, layout)
    margin = sized.canvas.margin
    nodes = [n for n in sized.nodes]

    if not nodes:
        return _canvas_update(sized, 2 * margin, 2 * margin)

    col_w = max(n.w for n in nodes)
    inner_w = target_width_mm - 2 * margin
    _ = max(inner_w, col_w)  # never shrink below the widest node

    # pack into 2 columns (the "two-column" promise)
    import math

    mid = math.ceil(len(nodes) / 2)
    col1, col2 = nodes[:mid], nodes[mid:]
    columns = [c for c in (col1, col2) if c]

    placed = []
    x_offset = margin
    for col_index, col in enumerate(columns):
        y = margin
        col_width = max(n.w for n in col)
        for node in col:
            x = x_offset + (col_width - node.w) / 2  # centre within column
            placed.append(node.model_copy(update={"x": x, "y": y}))
            y += node.h + GRID_GAP_V_MM
        if col_index < len(columns) - 1:
            x_offset += col_width + GRID_GAP_H_MM

    content_w = max(x_offset + max(n.w for n in columns[-1]) - margin, 0.0)
    content_h = max((n.y + n.h for n in placed), default=0.0) - margin
    canvas_w = content_w + 2 * margin
    canvas_h = content_h + 2 * margin

    canvas = sized.canvas.model_copy(update={"width": canvas_w, "height": canvas_h})
    return sized.model_copy(update={"nodes": placed, "canvas": canvas})


def layout_single_column(
    fig: Figure, *, target_width_mm: float = SINGLE_COLUMN_MM
) -> Figure:
    """Vertical layout constrained to ``target_width_mm`` (default 89 mm)."""
    from papercanvas.layout.linear import layout_linear

    result = layout_linear(fig, direction="v")
    canvas = result.canvas.model_copy(update={"width": target_width_mm})
    return result.model_copy(update={"canvas": canvas})


def _canvas_update(fig: Figure, w: float, h: float) -> Figure:
    canvas = fig.canvas.model_copy(update={"width": w, "height": h})
    return fig.model_copy(update={"canvas": canvas})
