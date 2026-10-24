"""Cross-format consistency: SVG, PDF and PPTX geometry for the same IR
must agree within 0.2 mm (plan §6 M2 acceptance)."""

from __future__ import annotations

import io
import re
import zlib

import pytest
from lxml import etree
from pptx import Presentation

from papercanvas.core.geometry import mm_to_pt
from papercanvas.core.models import Figure
from papercanvas.layout import run_layout
from papercanvas.render.pdf import render_pdf
from papercanvas.render.pptx import render_pptx
from papercanvas.render.svg import render_svg
from papercanvas.text.text_layout import TextLayout
from papercanvas.text.text_metrics import FontMetrics

TOLERANCE_MM = 0.2


@pytest.fixture
def figures(figure_dict: dict) -> list[Figure]:
    figure_dict["nodes"] = [
        {"id": "a", "type": "rect", "label": "Input Video"},
        {"id": "b", "type": "rect", "label": "Video Encoder"},
        {"id": "c", "type": "rect", "label": "Prediction"},
    ]
    figure_dict["edges"] = [
        {"id": "e1", "source": "a", "target": "b"},
        {"id": "e2", "source": "b", "target": "c"},
    ]
    figure_dict["groups"] = [{"id": "g1", "children": ["a", "b"], "label": "Stage 1"}]
    base = Figure.model_validate(figure_dict)
    # renderers require coordinates: compare two laid-out variants
    return [run_layout(base, "linear-h"), run_layout(base, "linear-v")]


def _layout(fig: Figure) -> TextLayout:
    return TextLayout(FontMetrics.for_family(fig.theme.font_family))


def _svg_node_rects(fig: Figure) -> dict[str, tuple[float, float, float, float]]:
    root = etree.fromstring(render_svg(fig, _layout(fig)))
    ns = {"s": "http://www.w3.org/2000/svg"}
    rects = {}
    for rect in root.findall("s:rect", ns):
        if rect.get("id", "").startswith("node:"):
            node_id = rect.get("id").split(":", 1)[1]
            rects[node_id] = tuple(
                float(rect.get(attr)) for attr in ("x", "y", "width", "height")
            )
    return rects


def _pdf_content(pdf: bytes) -> bytes:
    parts = []
    for match in re.finditer(rb"stream\r?\n(.*?)endstream", pdf, re.DOTALL):
        raw = match.group(1)
        try:
            parts.append(zlib.decompress(raw))
        except zlib.error:
            parts.append(raw)
    return b"\n".join(parts)


def _pdf_node_rects(fig: Figure) -> dict[str, tuple[float, float, float, float]]:
    content = _pdf_content(render_pdf(fig, _layout(fig)))
    rects = [
        tuple(float(v) for v in values)
        for values in re.findall(rb"([\d.]+) ([\d.]+) ([\d.]+) ([\d.]+) re", content)
    ]
    page_h_pt = mm_to_pt(fig.canvas.height)
    # map IR node rects to PDF rects by exact-geometry match (the PDF stream
    # also contains the background and the group box; rounded rects draw as
    # bezier curves, not `re` operators, so plain-rect nodes only)
    result = {}
    for node in fig.nodes:
        if node.type != "rect":
            continue
        target = (
            mm_to_pt(node.x),
            page_h_pt - mm_to_pt(node.y + node.h),
            mm_to_pt(node.w),
            mm_to_pt(node.h),
        )
        match = min(
            rects,
            key=lambda r: sum(abs(r[i] - target[i]) for i in range(4)),
        )
        result[node.id] = (
            match[0] / mm_to_pt(1),
            (page_h_pt - match[1] - match[3]) / mm_to_pt(1),
            match[2] / mm_to_pt(1),
            match[3] / mm_to_pt(1),
        )
    assert result
    return result


def _pptx_node_rects(fig: Figure) -> dict[str, tuple[float, float, float, float]]:
    prs = Presentation(io.BytesIO(render_pptx(fig, _layout(fig))))
    rects = {}
    for shape in prs.slides[0].shapes:
        if shape.name.startswith("node:"):
            rects[shape.name.split(":", 1)[1]] = (
                shape.left / 36000,
                shape.top / 36000,
                shape.width / 36000,
                shape.height / 36000,
            )
    return rects


def test_svg_pdf_pptx_geometry_within_tolerance(figures: list[Figure]) -> None:
    for fig in figures:
        svg_rects = _svg_node_rects(fig)
        pdf_rects = _pdf_node_rects(fig)
        pptx_rects = _pptx_node_rects(fig)
        assert set(svg_rects) == set(pptx_rects)
        worst = 0.0
        for node in fig.nodes:
            node_id = node.id
            for index, attr in enumerate(("x", "y", "w", "h")):
                expected = getattr(node, attr)
                for fmt, rects in (("svg", svg_rects), ("pptx", pptx_rects)):
                    deviation = abs(rects[node_id][index] - expected)
                    worst = max(worst, deviation)
                    assert deviation <= TOLERANCE_MM, (
                        f"node {node_id} {attr} in {fmt}: {rects[node_id][index]} vs {expected}"
                    )
                if node_id in pdf_rects:
                    deviation = abs(pdf_rects[node_id][index] - expected)
                    worst = max(worst, deviation)
                    assert deviation <= TOLERANCE_MM, (
                        f"node {node_id} {attr} in pdf: {pdf_rects[node_id][index]} vs {expected}"
                    )
        # report the worst observed deviation for the summary
        assert worst <= TOLERANCE_MM


def test_pdf_and_pptx_backgrounds_match_canvas(figures: list[Figure]) -> None:
    from papercanvas.render.pptx import SLIDE_MIN_MM

    for fig in figures:
        pdf = render_pdf(fig, _layout(fig))
        media = re.search(rb"/MediaBox \[ 0 0 ([\d.]+) ([\d.]+) \]", pdf)
        assert media
        assert abs(float(media.group(1)) - mm_to_pt(fig.canvas.width)) < 0.05
        assert abs(float(media.group(2)) - mm_to_pt(fig.canvas.height)) < 0.05
        prs = Presentation(io.BytesIO(render_pptx(fig, _layout(fig))))
        # PPTX slides carry the OOXML 1-inch floor; the canvas is padded, not shrunk
        assert prs.slide_width / 36000 >= fig.canvas.width - TOLERANCE_MM
        assert prs.slide_height / 36000 >= fig.canvas.height - TOLERANCE_MM
        assert prs.slide_width / 36000 == pytest.approx(
            max(fig.canvas.width, SLIDE_MIN_MM), abs=TOLERANCE_MM
        )
        assert prs.slide_height / 36000 == pytest.approx(
            max(fig.canvas.height, SLIDE_MIN_MM), abs=TOLERANCE_MM
        )
