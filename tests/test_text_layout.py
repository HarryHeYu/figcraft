"""TextLayout: determinism, wrapping quality, and the constraint-2 contract."""

from __future__ import annotations

import pytest

from papercanvas.text.text_layout import TextLayout, wrap_text
from papercanvas.text.text_metrics import FontMetrics

FONT_FAMILY = "Arial"
SIZE_PT = 8.0


@pytest.fixture
def layout() -> TextLayout:
    return TextLayout(FontMetrics.for_family(FONT_FAMILY))


def test_two_instances_agree_exactly() -> None:
    """Constraint 6c (first half): two independently-constructed TextLayout
    instances produce identical results for the same input."""
    first = TextLayout(FontMetrics.for_family(FONT_FAMILY))
    second = TextLayout(FontMetrics.for_family(FONT_FAMILY))
    label = "Multi-modal Video Encoder with Temporal Pooling"
    box = {"font_family": FONT_FAMILY, "font_size_pt": SIZE_PT, "box_w_mm": 40.0, "box_h_mm": 12.0}
    assert first.layout_label(label, **box) == second.layout_label(label, **box)
    assert first.measure_block(label, font_size_pt=SIZE_PT) == second.measure_block(
        label, font_size_pt=SIZE_PT
    )


def test_layout_is_deterministic(layout: TextLayout) -> None:
    kwargs = {
        "font_family": FONT_FAMILY,
        "font_size_pt": SIZE_PT,
        "box_w_mm": 30.0,
        "box_h_mm": 10.0,
    }
    assert layout.layout_label("Encoder Block", **kwargs) == layout.layout_label(
        "Encoder Block", **kwargs
    )


def test_wrapping_respects_box_width(layout: TextLayout) -> None:
    result = layout.layout_label(
        "Input Video",
        font_family=FONT_FAMILY,
        font_size_pt=SIZE_PT,
        box_w_mm=16.0,
        box_h_mm=20.0,
    )
    assert [line.text for line in result.lines] == ["Input", "Video"]
    assert result.text_width_mm <= 16.0 - 2 * 2.5 + 1e-6


def test_wrapping_prefers_word_breaks(layout: TextLayout) -> None:
    # A hair narrower than "shared temporal": a pure character wrap would cut
    # mid-word ("shared tempora|l"); the word-preference rule must not.
    max_width_pt = layout.metrics.width_pt("shared temporal", SIZE_PT) - 0.01
    lines = wrap_text(
        "shared temporal encoder",
        max_width_pt=max_width_pt,
        metrics=layout.metrics,
        size_pt=SIZE_PT,
    )
    assert lines == ("shared", "temporal", "encoder")


def test_cjk_breaks_between_characters(layout: TextLayout) -> None:
    lines = wrap_text(
        "视频编码器模块",
        max_width_pt=layout.metrics.width_pt("视频编码", SIZE_PT),
        metrics=layout.metrics,
        size_pt=SIZE_PT,
    )
    assert len(lines) >= 2
    assert "".join(lines) == "视频编码器模块"


def test_explicit_newline_always_breaks(layout: TextLayout) -> None:
    lines = wrap_text(
        "line one\nline two",
        max_width_pt=layout.metrics.width_pt("line one line two", SIZE_PT) * 2,
        metrics=layout.metrics,
        size_pt=SIZE_PT,
    )
    assert lines == ("line one", "line two")


def test_overflow_is_reported_not_hidden(layout: TextLayout) -> None:
    result = layout.layout_label(
        "A Very Long Module Label That Cannot Fit",
        font_family=FONT_FAMILY,
        font_size_pt=SIZE_PT,
        box_w_mm=25.0,
        box_h_mm=8.0,
    )
    assert not result.fits
    assert result.overflow_y_mm > 0


def test_word_breaks_leave_no_trailing_spaces(layout: TextLayout) -> None:
    """Regression: a double space used to survive as a trailing space on the
    broken line ('ab ' instead of 'ab')."""
    max_width_pt = layout.metrics.width_pt("ab ", SIZE_PT) + 0.5
    lines = wrap_text(
        "ab  cd",
        max_width_pt=max_width_pt,
        metrics=layout.metrics,
        size_pt=SIZE_PT,
    )
    assert lines == ("ab", "cd")


def test_measure_block_single_line(layout: TextLayout) -> None:
    from papercanvas.core.geometry import PT_PER_MM

    width, height, n_lines = layout.measure_block("Input Video", font_size_pt=SIZE_PT)
    assert n_lines == 1
    assert width > 0
    assert height == pytest.approx(SIZE_PT * 1.2 / PT_PER_MM, rel=1e-6)


def test_empty_label_layouts_to_nothing(layout: TextLayout) -> None:
    result = layout.layout_label(
        "", font_family=FONT_FAMILY, font_size_pt=SIZE_PT, box_w_mm=20.0, box_h_mm=10.0
    )
    assert result.lines == ()
    assert result.fits
