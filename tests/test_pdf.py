"""PDF renderer: determinism, true vector content, TTF embedding, geometry."""

from __future__ import annotations

import re
import zlib
from pathlib import Path

import pytest

from papercanvas.core.models import Figure
from papercanvas.layout import run_layout
from papercanvas.render.pdf import render_pdf
from papercanvas.text.text_layout import TextLayout
from papercanvas.text.text_metrics import FontMetrics


@pytest.fixture
def laid_out(figure_dict: dict) -> Figure:
    figure_dict["nodes"] = [
        {"id": "a", "type": "rounded_rect", "label": "Input Video"},
        {"id": "b", "type": "rect", "label": "Video Encoder"},
        {"id": "c", "type": "rect", "label": "Prediction"},
    ]
    figure_dict["edges"] = [
        {"id": "e1", "source": "a", "target": "b"},
        {"id": "e2", "source": "b", "target": "c"},
    ]
    figure_dict["groups"] = [{"id": "g1", "children": ["a", "b"], "label": "Stage 1"}]
    return run_layout(Figure.model_validate(figure_dict), "linear-h")


def _render(fig: Figure) -> bytes:
    return render_pdf(fig, TextLayout(FontMetrics.for_family(fig.theme.font_family)))


def _streams(pdf_bytes: bytes) -> list[bytes]:
    """Decompress every content stream in the PDF."""
    streams = []
    for match in re.finditer(rb"stream\r?\n(.*?)endstream", pdf_bytes, re.DOTALL):
        raw = match.group(1)
        try:
            streams.append(zlib.decompress(raw))
        except zlib.error:
            streams.append(raw)
    return streams


def _content(pdf_bytes: bytes) -> bytes:
    return b"\n".join(_streams(pdf_bytes))


def test_pdf_is_byte_deterministic(laid_out: Figure) -> None:
    """invariant=1 pins the creation date and document id -> identical bytes."""
    first = _render(laid_out.model_copy(deep=True))
    second = _render(laid_out.model_copy(deep=True))
    assert first == second


def test_pdf_contains_no_creation_timestamp(laid_out: Figure) -> None:
    pdf = _render(laid_out)
    assert b"D:2000" in pdf or b"D:1999" in pdf  # invariant epoch, not today
    assert str(laid_out.nodes[0].label).encode() in _content(pdf)


def test_pdf_is_vector_not_raster(laid_out: Figure) -> None:
    pdf = _render(laid_out)
    assert b"/Subtype /Image" not in pdf  # no raster XObjects
    assert b"/FontFile2" in pdf  # TTF subset embedded
    content = _content(pdf)
    assert b" re" in content  # rectangle operators present
    assert b"Tj" in content or b"TJ" in content  # real text operators


def test_pdf_page_size_matches_canvas(laid_out: Figure) -> None:
    pdf = _render(laid_out)
    match = re.search(rb"/MediaBox \[ 0 0 ([\d.]+) ([\d.]+) \]", pdf)
    assert match, "MediaBox missing"
    from papercanvas.core.geometry import mm_to_pt

    width_pt, height_pt = float(match.group(1)), float(match.group(2))
    assert width_pt == pytest.approx(mm_to_pt(laid_out.canvas.width), abs=0.01)
    assert height_pt == pytest.approx(mm_to_pt(laid_out.canvas.height), abs=0.01)


def test_pdf_node_rects_match_ir_geometry(laid_out: Figure) -> None:
    from papercanvas.core.geometry import mm_to_pt

    content = _content(_render(laid_out))
    flat = re.findall(rb"([\d.]+) ([\d.]+) ([\d.]+) ([\d.]+) re", content)
    assert flat, "no rectangle operators found"
    rects = [(float(a), float(b), float(c), float(d)) for a, b, c, d in flat]
    page_rects = rects[1:]  # first rect is the full-page background
    assert len(page_rects) >= 3  # group box + nodes
    # plain rects must appear with matching geometry (PDF y axis is flipped);
    # rounded_rect nodes draw as bezier curves, so they are excluded here
    plain = [node for node in laid_out.nodes if node.type == "rect"]
    assert plain
    for node in plain:
        expected = (
            pytest.approx(mm_to_pt(node.x), abs=0.05),
            pytest.approx(mm_to_pt(laid_out.canvas.height - node.y - node.h), abs=0.05),
            pytest.approx(mm_to_pt(node.w), abs=0.05),
            pytest.approx(mm_to_pt(node.h), abs=0.05),
        )
        match = any(
            r[0] == expected[0]
            and r[1] == expected[1]
            and r[2] == expected[2]
            and r[3] == expected[3]
            for r in page_rects
        )
        assert match, f"node {node.id} rect {expected} not found in {page_rects}"


def test_pdf_arrowhead_drawn_for_end_arrows(figure_dict: dict) -> None:
    figure_dict["nodes"] = [
        {"id": "a", "x": 10, "y": 20, "w": 30, "h": 15},
        {"id": "b", "x": 80, "y": 20, "w": 30, "h": 15},
    ]
    figure_dict["edges"] = [{"id": "e1", "source": "a", "target": "b", "style": {"arrow": "end"}}]
    fig = Figure.model_validate(figure_dict)
    content = _content(_render(fig))
    # edge polyline (m/l/S) + closed filled arrowhead triangle (m/l/l/h + f*)
    assert content.count(b" m ") + content.count(b" m\n") >= 2
    assert b" h" in content
    assert b"f*" in content


def test_pdf_render_does_not_modify_source(laid_out: Figure, tmp_path) -> None:
    from papercanvas.core.document import FigureDocument

    path = tmp_path / "fig.json"
    FigureDocument.create(path, laid_out)
    before = path.read_bytes()
    _render(FigureDocument.load(path).figure)
    assert path.read_bytes() == before


def test_pdf_group_label_present(laid_out: Figure) -> None:
    content = _content(_render(laid_out))
    assert b"Stage 1" in content


def test_pdf_font_registration_is_per_file_not_per_name() -> None:
    """Regression: two families sanitizing to one reportlab name but
    resolving to different font files must each embed their own file."""
    from papercanvas.text import text_metrics as tm
    from papercanvas.text.text_layout import TextLayout
    from papercanvas.text.text_metrics import FontMetrics

    first_path, _ = tm.resolve_font("Arial")
    # a second, genuinely different font file available on this machine
    system_dirs = [
        Path("C:/Windows/Fonts"),
        Path("/usr/share/fonts"),
        Path("/System/Library/Fonts"),
        Path("/Library/Fonts"),
    ]
    second_path = next(
        (
            path
            for directory in system_dirs
            if directory.exists()
            for path in sorted(directory.rglob("*.ttf"))
            if path != first_path
        ),
        None,
    )

    def layout_for(path) -> TextLayout:
        return TextLayout(
            FontMetrics(
                family="Same Sanitized Name",
                path=path,
                substituted=True,
                resolved_family=tm.family_of_file(str(path)),
            )
        )

    ir_payload = {
        "schema_version": "0.1",
        "id": "fx",
        "canvas": {"width": 80, "height": 40},
        "theme": {"font_family": "Same Sanitized Name"},
        "nodes": [{"id": "n", "type": "rect", "label": "Hi", "x": 5, "y": 5, "w": 30, "h": 10}],
    }
    fig_a = Figure.model_validate(ir_payload)
    fig_b = Figure.model_validate(ir_payload)
    file_a = _font_file(render_pdf(fig_a, layout_for(first_path)))
    file_b = _font_file(render_pdf(fig_b, layout_for(second_path)))
    assert file_a is not None and file_b is not None
    assert file_a != file_b  # two different TTF files actually embedded


def _font_file(pdf_bytes: bytes) -> bytes | None:
    """Extract the raw /FontFile2 stream payload (the subset TTF binary)."""
    matches = re.findall(
        rb"/FontFile2 (\d+) 0 R.*?stream\r?\n(.*?)endstream", pdf_bytes, re.DOTALL
    )
    for _length, payload in matches:
        try:
            return zlib.decompress(payload)
        except zlib.error:
            return payload
    return None


def test_pdf_cjk_labels_embed_a_covering_font(figure_dict: dict) -> None:
    """CJK labels must be measured AND embedded with a covering font — the
    .notdef-box problem from earlier milestones."""
    from papercanvas.service import text_layout_for
    from papercanvas.text.text_metrics import file_covers

    figure_dict["nodes"][0]["label"] = "视频编码器"
    fig = Figure.model_validate(figure_dict)
    layout = text_layout_for(fig)
    if not file_covers(str(layout.metrics.path), "视频编码器"):
        pytest.skip("no CJK-capable font available on this machine")

    pdf = render_pdf(fig, layout)
    assert b"/FontFile2" in pdf
    content = _content(pdf)
    assert b"Tj" in content or b"TJ" in content
