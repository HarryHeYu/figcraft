"""Column layout presets (two-column, single-column): determinism + geometry."""

from __future__ import annotations

import pytest

from papercanvas.core.models import Figure
from papercanvas.layout.column import (
    DOUBLE_COLUMN_MM,
    SINGLE_COLUMN_MM,
    layout_single_column,
    layout_two_column,
)

FONT_FAMILY = "Arial"


@pytest.fixture
def six_nodes(figure_dict: dict) -> Figure:
    figure_dict["nodes"] = [
        {"id": f"n{i}", "type": "rect", "label": f"Node {i}"} for i in range(6)
    ]
    figure_dict["edges"] = []
    return Figure.model_validate(figure_dict)


def test_two_column_places_all_nodes(six_nodes: Figure) -> None:
    result = layout_two_column(six_nodes)
    assert all(n.is_placed for n in result.nodes)
    assert len(result.nodes) == 6


def test_two_column_width_within_double_column(six_nodes: Figure) -> None:
    result = layout_two_column(six_nodes)
    assert result.canvas.width <= DOUBLE_COLUMN_MM + 2 * result.canvas.margin


def test_two_column_deterministic(six_nodes: Figure) -> None:
    from papercanvas.core.document import serialize_figure

    a = layout_two_column(six_nodes.model_copy(deep=True))
    b = layout_two_column(six_nodes.model_copy(deep=True))
    assert serialize_figure(a) == serialize_figure(b)


def test_single_column_constrains_width(six_nodes: Figure) -> None:
    result = layout_single_column(six_nodes)
    assert result.canvas.width == pytest.approx(SINGLE_COLUMN_MM)
    assert all(n.is_placed for n in result.nodes)


def test_layout_presets_accepted_via_run_layout(six_nodes: Figure) -> None:
    from papercanvas.layout import run_layout

    for preset in ("two-column", "single-column"):
        result = run_layout(six_nodes.model_copy(deep=True), preset)
        assert all(n.is_placed for n in result.nodes)


def test_two_column_empty_figure(figure_dict: dict) -> None:
    figure_dict["nodes"] = []
    figure_dict["edges"] = []
    fig = Figure.model_validate(figure_dict)
    result = layout_two_column(fig)
    assert result.nodes == []
    assert result.canvas.width > 0
