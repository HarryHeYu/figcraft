"""Auto-sizing helpers shared by the layout presets.

Node boxes without ``w``/``h`` are sized around their labels using the
TextLayout metrics (constraint 2: all sizing goes through the one text layer).
"""

from __future__ import annotations

from papercanvas.core.models import Figure
from papercanvas.text.text_layout import (
    NODE_PADDING_H_MM,
    NODE_PADDING_V_MM,
    TextLayout,
)
from papercanvas.text.text_metrics import FontMetrics

#: clamps for auto-sized nodes (mm)
MIN_NODE_W_MM = 20.0
MIN_NODE_H_MM = 10.0


def text_layout_for_theme(fig: Figure) -> TextLayout:
    """One TextLayout bound to the figure's theme font."""
    return TextLayout(FontMetrics.for_family(fig.theme.font_family))


def auto_size_nodes(fig: Figure, layout: TextLayout) -> Figure:
    """Return a copy of the figure in which every node has ``w``/``h`` set.

    Explicit dimensions are kept; only missing ones are derived from the label
    measurement plus padding, clamped to the minimums. Nodes without a label
    get the minimum size.
    """
    changed = False
    nodes = []
    for node in fig.nodes:
        if node.w is not None and node.h is not None:
            nodes.append(node)
            continue
        w, h = node.w, node.h
        text_w, text_h, _ = layout.measure_block(node.label, font_size_pt=fig.theme.font_size_pt)
        if w is None:
            w = max(MIN_NODE_W_MM, text_w + 2 * NODE_PADDING_H_MM)
        if h is None:
            h = max(MIN_NODE_H_MM, text_h + 2 * NODE_PADDING_V_MM)
        changed = True
        nodes.append(node.model_copy(update={"w": w, "h": h}))
    if not changed:
        return fig
    return fig.model_copy(update={"nodes": nodes})
