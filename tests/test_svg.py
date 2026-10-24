"""SVG renderer: read-only guarantee, determinism, cross-backend text agreement."""

from __future__ import annotations

from pathlib import Path

import pytest

from papercanvas.core.document import FigureDocument, serialize_figure
from papercanvas.core.errors import RenderError
from papercanvas.core.models import Figure
from papercanvas.layout import run_layout
from papercanvas.render import render_svg
from papercanvas.text.text_layout import TextLayout
from papercanvas.text.text_metrics import FontMetrics

FONT_FAMILY = "Arial"


@pytest.fixture
def laid_out(figure_dict: dict) -> Figure:
    figure_dict["nodes"] = [
        {"id": "a", "type": "rounded_rect", "label": "Input Video"},
        {"id": "b", "type": "rounded_rect", "label": "Video Encoder"},
        {"id": "c", "type": "rounded_rect", "label": "Prediction"},
    ]
    figure_dict["edges"] = [
        {"id": "e1", "source": "a", "target": "b", "style": {"arrow": "end"}},
        {"id": "e2", "source": "b", "target": "c", "style": {"arrow": "end"}},
    ]
    figure_dict["groups"] = [{"id": "g1", "children": ["a", "b"], "label": "Stage 1"}]
    return run_layout(Figure.model_validate(figure_dict), "linear-h")


def _render(fig: Figure) -> bytes:
    layout = TextLayout(FontMetrics.for_family(fig.theme.font_family))
    return render_svg(fig, layout)


def test_render_does_not_modify_source_file(
    laid_out: Figure, tmp_path: Path
) -> None:
    """Constraint 6a: rendering is strictly read-only on the IR file."""
    path = tmp_path / "fig.json"
    FigureDocument.create(path, laid_out)
    before = path.read_bytes()

    _render(FigureDocument.load(path).figure)

    assert path.read_bytes() == before
    assert not list(tmp_path.glob("*.lock"))  # render never took a write lock


def test_render_is_byte_deterministic(laid_out: Figure) -> None:
    """Constraint 6a: two renders of the same IR produce identical bytes."""
    first = _render(laid_out.model_copy(deep=True))
    second = _render(laid_out.model_copy(deep=True))
    assert first == second


def test_svg_contains_text_and_no_images_or_scripts(laid_out: Figure) -> None:
    svg = _render(laid_out)
    assert b"<text" in svg
    assert b"<image" not in svg
    assert b"<script" not in svg
    assert b"<!--" not in svg  # no generator comments, no timestamps


def test_svg_text_line_count_matches_textlayout(laid_out: Figure) -> None:
    """Constraint 6c, exact form: total <text> elements == TextLayout lines
    for every node AND group label — a renderer that drops or adds a line
    cannot pass."""
    from papercanvas.render.svg import (
        GROUP_LABEL_OFFSET_MM,
        GROUP_PADDING_MM,
    )

    text_layout = TextLayout(FontMetrics.for_family(laid_out.theme.font_family))
    expected_total = 0
    for node in laid_out.nodes:
        result = text_layout.layout_label(
            node.label,
            font_family=laid_out.theme.font_family,
            font_size_pt=laid_out.theme.font_size_pt,
            box_w_mm=node.w,
            box_h_mm=node.h,
        )
        expected_total += len(result.lines)
    for group in laid_out.groups:
        children = [laid_out.node(child_id) for child_id in group.children]
        x0 = min(c.x for c in children) - GROUP_PADDING_MM
        x1 = max(c.x + c.w for c in children) + GROUP_PADDING_MM
        result = text_layout.layout_label(
            group.label,
            font_family=laid_out.theme.font_family,
            font_size_pt=laid_out.theme.font_size_pt,
            box_w_mm=x1 - x0,
            box_h_mm=GROUP_LABEL_OFFSET_MM,
            padding_h_mm=GROUP_PADDING_MM,
            padding_v_mm=0.5,
        )
        expected_total += len(result.lines)

    svg = _render(laid_out).decode("utf-8")
    assert svg.count("<text") == expected_total


def test_multiline_label_renders_every_textlayout_line(figure_dict: dict) -> None:
    """Constraint 6c on a forced multi-line label: every planned line appears
    exactly once, none missing, none invented."""
    figure_dict["nodes"] = [
        {
            "id": "a",
            "type": "rect",
            "label": "Shared Temporal Encoder Block",
            "x": 10,
            "y": 10,
            "w": 24,
            "h": 24,
        }
    ]
    figure_dict["edges"] = []
    fig = Figure.model_validate(figure_dict)
    text_layout = TextLayout(FontMetrics.for_family(fig.theme.font_family))
    result = text_layout.layout_label(
        fig.nodes[0].label,
        font_family=fig.theme.font_family,
        font_size_pt=fig.theme.font_size_pt,
        box_w_mm=24,
        box_h_mm=24,
    )
    assert len(result.lines) >= 2  # the box is deliberately too narrow for one line

    svg = _render(fig).decode("utf-8")
    assert svg.count("<text") == len(result.lines)
    for line in result.lines:
        assert f">{line.text}<" in svg


def test_svg_page_is_the_mm_canvas(laid_out: Figure) -> None:
    svg = _render(laid_out).decode("utf-8")
    w, h = _fmt_mm(laid_out.canvas.width), _fmt_mm(laid_out.canvas.height)
    assert f'viewBox="0 0 {w} {h}"' in svg
    assert f'width="{w}mm"' in svg


def _fmt_mm(value: float) -> str:
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def test_node_stroke_dash_is_rendered(figure_dict: dict) -> None:
    """Regression: node-level stroke_dash used to be silently dropped."""
    figure_dict["nodes"][0]["style"]["stroke_dash"] = "dashed"
    figure_dict["nodes"][1]["style"]["stroke_dash"] = "dotted"
    svg = _render(Figure.model_validate(figure_dict)).decode("utf-8")
    assert 'stroke-dasharray="3 1.5"' in svg
    assert 'stroke-dasharray="0.8 1.2"' in svg


def test_group_label_stays_inside_canvas_when_group_hugs_the_top(
    figure_dict: dict,
) -> None:
    """Regression: a narrow group at the top of the canvas wrapped its label
    and pushed the text above the canvas edge. The block must clamp down."""
    figure_dict["nodes"] = [
        {"id": "a", "type": "rect", "label": "A", "x": 10, "y": 4, "w": 22, "h": 10},
        {"id": "b", "type": "rect", "label": "B", "x": 10, "y": 20, "w": 22, "h": 10},
    ]
    figure_dict["edges"] = []
    figure_dict["groups"] = [
        {"id": "gtop", "children": ["a", "b"], "label": "Unlearning"}
    ]
    fig = Figure.model_validate(figure_dict)
    svg = _render(fig).decode("utf-8")

    import re

    group_y = float(
        re.search(r'id="group:gtop"[^>]*? y="([\d.-]+)"', svg).group(1)
    )
    text_ys = [
        (float(y), text)
        for y, text in re.findall(r'<text x="[\d.]+" y="([\d.-]+)"[^>]*>([^<]*)</text>', svg)
    ]
    assert text_ys, "no text elements rendered"
    assert min(y for y, _text in text_ys) >= 0.0, "group label escaped the canvas"
    # the group label (baseline clamped below the border) must stay above the
    # children, which start at y=4 (group top + 3 mm padding)
    label_ys = [y for y, text in text_ys if text == "Unlearning"]
    assert label_ys, "group label missing"
    assert max(label_ys) < 4.0, "group label collided with children"
    assert group_y == pytest.approx(1.0, abs=0.01)


def test_arrow_markers_present_and_absent(figure_dict: dict) -> None:
    figure_dict["nodes"] = [
        {"id": "a", "x": 10, "y": 20, "w": 30, "h": 15},
        {"id": "b", "x": 80, "y": 20, "w": 30, "h": 15},
    ]
    figure_dict["edges"] = [
        {"id": "e1", "source": "a", "target": "b", "style": {"arrow": "end"}},
        {"id": "e2", "source": "b", "target": "a", "style": {"arrow": "none"}},
    ]
    fig = Figure.model_validate(figure_dict)
    svg = _render(fig).decode("utf-8")
    assert "marker-end" in svg
    assert svg.count("marker-end") == 1
    assert svg.count("<marker") == 1


def test_palette_colors_resolved_to_hex(figure_dict: dict) -> None:
    figure_dict["nodes"][0]["style"]["fill"] = "accent"  # palette key from conftest
    fig = Figure.model_validate(figure_dict)
    svg = _render(fig).decode("utf-8")
    assert "#3366CC" in svg
    assert "accent" not in svg


def test_unplaced_nodes_are_a_render_error(figure_dict: dict) -> None:
    figure_dict["nodes"] = [{"id": "a", "label": "no coords yet"}]
    fig = Figure.model_validate(figure_dict)
    with pytest.raises(RenderError, match="layout"):
        _render(fig)


def test_render_consumes_serialized_ir_unchanged(laid_out: Figure) -> None:
    """Same IR -> same SVG bytes, even after a serialize/parse roundtrip."""
    import json

    direct = _render(laid_out)
    roundtrip = Figure.model_validate(json.loads(serialize_figure(laid_out).decode("utf-8")))
    assert _render(roundtrip) == direct
