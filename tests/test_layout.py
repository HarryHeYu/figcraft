"""Layout presets: ordering, determinism, revision bookkeeping (constraint 6b/6d)."""

from __future__ import annotations

from pathlib import Path

import pytest

from papercanvas.core.document import FigureDocument
from papercanvas.core.errors import LayoutError
from papercanvas.core.models import Figure
from papercanvas.layout import run_layout
from papercanvas.layout.layered import layer_map
from papercanvas.layout.linear import layout_linear


@pytest.fixture
def pipeline(figure_dict: dict) -> Figure:
    """Three nodes a -> b, no coordinates at all (awaiting layout)."""
    figure_dict["nodes"] = [
        {"id": "a", "type": "rounded_rect", "label": "Input Video"},
        {"id": "b", "type": "rounded_rect", "label": "Video Encoder"},
        {"id": "c", "type": "rounded_rect", "label": "Prediction"},
    ]
    figure_dict["edges"] = [
        {"id": "e1", "source": "a", "target": "b"},
        {"id": "e2", "source": "b", "target": "c"},
    ]
    return Figure.model_validate(figure_dict)


def test_linear_h_orders_nodes_left_to_right(pipeline: Figure) -> None:
    result = layout_linear(pipeline, direction="h")
    xs = [node.x for node in result.nodes]
    assert xs == sorted(xs)
    ys = [node.y for node in result.nodes]
    assert len({round(y, 6) for y in ys}) == 1  # vertically aligned row
    assert all(node.is_placed for node in result.nodes)


def test_linear_v_orders_nodes_top_to_bottom(pipeline: Figure) -> None:
    result = layout_linear(pipeline, direction="v")
    ys = [node.y for node in result.nodes]
    assert ys == sorted(ys)


def test_canvas_recomputed_from_content_plus_margin(pipeline: Figure) -> None:
    result = layout_linear(pipeline, direction="h")
    margin = result.canvas.margin
    content_w = max(n.x + n.w for n in result.nodes) - min(n.x for n in result.nodes)
    assert result.canvas.width == pytest.approx(content_w + 2 * margin)
    assert result.canvas.height == pytest.approx(
        max(n.h for n in result.nodes) + 2 * margin
    )


def test_auto_size_fits_label_and_respects_minimum(pipeline: Figure) -> None:
    result = layout_linear(pipeline, direction="h")
    assert all(node.w >= 20.0 and node.h >= 10.0 for node in result.nodes)
    tiny = pipeline.model_copy(
        update={"nodes": [pipeline.nodes[0].model_copy(update={"label": ""})]}
    )
    result = layout_linear(tiny, direction="h")
    assert (result.nodes[0].w, result.nodes[0].h) == (20.0, 10.0)


def test_layered_assigns_layers_by_dag_depth(pipeline: Figure) -> None:
    result = run_layout(pipeline, "layered")
    assert [n.id for n in sorted(result.nodes, key=lambda n: n.x)] == ["a", "b", "c"]
    assert layer_map(pipeline) == {"a": 0, "b": 1, "c": 2}


def test_layered_rejects_cycles(figure_dict: dict) -> None:
    figure_dict["nodes"] = [
        {"id": n, "x": None, "y": None, "w": None, "h": None} for n in ("a", "b")
    ]
    figure_dict["edges"] = [
        {"id": "e1", "source": "a", "target": "b"},
        {"id": "e2", "source": "b", "target": "a"},
    ]
    fig = Figure.model_validate(figure_dict)
    with pytest.raises(LayoutError, match="cycle"):
        run_layout(fig, "layered")


def test_isolated_node_gets_layer_zero(figure_dict: dict) -> None:
    figure_dict["nodes"] = [
        {"id": "a", "label": "A"},
        {"id": "lonely", "label": "L"},
        {"id": "b", "label": "B"},
    ]
    figure_dict["edges"] = [{"id": "e1", "source": "a", "target": "b"}]
    fig = Figure.model_validate(figure_dict)
    assert layer_map(fig) == {"a": 0, "lonely": 0, "b": 1}


def test_layout_is_deterministic(pipeline: Figure) -> None:
    """Constraint 6d (layout half): two layout runs serialize byte-identically."""
    first = run_layout(pipeline.model_copy(deep=True), "layered")
    second = run_layout(pipeline.model_copy(deep=True), "layered")
    from papercanvas.core.document import serialize_figure

    assert serialize_figure(first) == serialize_figure(second)


def test_layout_commit_bumps_revision_on_disk(pipeline: Figure, tmp_path: Path) -> None:
    """Constraint 6b: a committed layout increments the file revision by one."""
    path = tmp_path / "fig.json"
    doc = FigureDocument.create(path, pipeline)
    base = doc.figure.revision

    laid_out = run_layout(doc.figure, "linear-h")
    laid_out.revision = base + 1
    doc.save_figure(laid_out, expected_revision=base)

    on_disk = FigureDocument.load(path).figure
    assert on_disk.revision == base + 1
    assert all(node.is_placed for node in on_disk.nodes)


def test_layout_arithmetic_overflow_is_a_clean_error(pipeline: Figure) -> None:
    """Nodes with astronomic (but schema-legal) sizes must fail layout with a
    validation error, never an inf-canvas traceback."""
    huge = 1e308
    nodes = [
        pipeline.nodes[0].model_copy(update={"w": huge}),
        pipeline.nodes[1],
    ]
    blown = pipeline.model_copy(update={"nodes": nodes})
    with pytest.raises(Exception) as excinfo:  # noqa: PT011 - any PaperCanvasError is fine
        run_layout(blown, "linear-h")
    assert not isinstance(excinfo.value, (OverflowError, ValueError, RecursionError))


def test_layout_keeps_ids_and_edges_stable(pipeline: Figure) -> None:
    result = run_layout(pipeline, "linear-h")
    assert {n.id for n in result.nodes} == {n.id for n in pipeline.nodes}
    assert [e.id for e in result.edges] == [e.id for e in pipeline.edges]
    assert result.revision == pipeline.revision  # revision is the document's business
