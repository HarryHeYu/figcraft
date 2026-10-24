"""Layered layout — a deliberately small Sugiyama.

1. Kahn topological order over the edges; a dependency cycle is a hard
   LayoutError (layout refuses to guess an ordering).
2. Longest-path layering: ``layer(n) = max(layer(pred) + 1)``; sources at 0.
3. Within-layer order is stable: nodes keep their IR array order.
4. Layers run left to right; the canvas is recomputed as content + margin.

Deterministic by construction: the queue is seeded in IR order and adjacency
lists follow edge array order, and the final geometry depends only on layers
plus IR order anyway (constraint 6d).
"""

from __future__ import annotations

from collections import deque

from papercanvas.core.errors import LayoutError
from papercanvas.core.models import Figure
from papercanvas.layout.sizes import auto_size_nodes, text_layout_for_theme

#: channel between layers (mm) — space for the orthogonal edge routing
LAYER_GAP_MM = 16.0
#: gap between stacked nodes inside one layer (mm)
WITHIN_GAP_MM = 6.0


def layer_map(fig: Figure) -> dict[str, int]:
    """Longest-path layer per node id; raises LayoutError on any cycle."""
    node_ids = fig.node_ids()
    in_degree: dict[str, int] = {nid: 0 for nid in node_ids}
    successors: dict[str, list[str]] = {nid: [] for nid in node_ids}
    for edge in fig.edges:
        successors[edge.source].append(edge.target)
        in_degree[edge.target] += 1

    layer = {nid: 0 for nid in node_ids}
    queue = deque(node.id for node in fig.nodes if in_degree[node.id] == 0)
    processed = 0
    while queue:
        node_id = queue.popleft()
        processed += 1
        for successor in successors[node_id]:
            layer[successor] = max(layer[successor], layer[node_id] + 1)
            in_degree[successor] -= 1
            if in_degree[successor] == 0:
                queue.append(successor)
    if processed != len(node_ids):
        cyclic = sorted(nid for nid in node_ids if in_degree[nid] > 0)
        raise LayoutError(f"cannot layer the figure: dependency cycle through nodes {cyclic}")
    return layer


def layout_layered(fig: Figure) -> Figure:
    layout = text_layout_for_theme(fig)
    sized = auto_size_nodes(fig, layout)
    layer_of = layer_map(sized)
    margin = sized.canvas.margin

    # Bucket nodes per layer, preserving IR array order within each layer.
    layers: list[list] = []
    for node in sized.nodes:
        index = layer_of[node.id]
        while len(layers) <= index:
            layers.append([])
        layers[index].append(node)

    layer_w = [max(node.w for node in column) for column in layers]
    layer_h = [
        sum(node.h for node in column) + WITHIN_GAP_MM * (len(column) - 1)
        for column in layers
    ]

    xs: list[float] = []
    cursor = margin
    for width in layer_w:
        xs.append(cursor)
        cursor += width + LAYER_GAP_MM
    # cursor overshot by one LAYER_GAP; content starts at `margin`
    content_w = max(cursor - LAYER_GAP_MM - margin, 0.0) if layers else 0.0
    content_h = max(layer_h, default=0.0)

    placed = []
    for column_index, column in enumerate(layers):
        x = xs[column_index]
        y = margin + (content_h - layer_h[column_index]) / 2
        for node in column:
            placed.append(
                node.model_copy(
                    update={"x": x + (layer_w[column_index] - node.w) / 2, "y": y}
                )
            )
            y += node.h + WITHIN_GAP_MM

    canvas = sized.canvas.model_copy(
        update={"width": content_w + 2 * margin, "height": content_h + 2 * margin}
    )
    return sized.model_copy(update={"nodes": placed, "canvas": canvas})
