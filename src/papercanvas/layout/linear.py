"""Linear layout: nodes in IR array order, as a row (h) or a column (v)."""

from __future__ import annotations

from typing import Literal

from papercanvas.core.models import Figure
from papercanvas.layout.sizes import auto_size_nodes, text_layout_for_theme

#: channel between neighbouring nodes (mm) — also the edge routing space
GAP_MM = 10.0

LinearDirection = Literal["h", "v"]


def layout_linear(fig: Figure, direction: LinearDirection = "h") -> Figure:
    layout = text_layout_for_theme(fig)
    sized = auto_size_nodes(fig, layout)
    margin = sized.canvas.margin

    placed = []
    if direction == "h":
        cursor = margin
        max_h = max((node.h for node in sized.nodes), default=0.0)
        for node in sized.nodes:
            placed.append(
                node.model_copy(
                    update={"x": cursor, "y": margin + (max_h - node.h) / 2}
                )
            )
            cursor += node.w + GAP_MM
        # cursor overshot by one GAP; content starts at `margin`
        content_w = max(cursor - GAP_MM - margin, 0.0)
        content_h = max_h
    else:
        cursor = margin
        max_w = max((node.w for node in sized.nodes), default=0.0)
        for node in sized.nodes:
            placed.append(
                node.model_copy(
                    update={"x": margin + (max_w - node.w) / 2, "y": cursor}
                )
            )
            cursor += node.h + GAP_MM
        content_w = max_w
        content_h = max(cursor - GAP_MM - margin, 0.0)

    canvas = sized.canvas.model_copy(
        update={"width": content_w + 2 * margin, "height": content_h + 2 * margin}
    )
    return sized.model_copy(update={"nodes": placed, "canvas": canvas})
