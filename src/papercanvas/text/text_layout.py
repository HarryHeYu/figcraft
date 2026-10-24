"""TextLayout — the single place where text is wrapped and positioned.

Constraint 2: renderers consume :class:`TextLayoutResult` verbatim; they must
never decide line breaks themselves. All coordinates in a result are in
millimetres relative to the containing box's top-left corner; ``y_mm`` of a
:class:`PlacedLine` is the **baseline**.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from math import inf

from papercanvas.core.geometry import mm_to_pt, pt_to_mm
from papercanvas.text.text_metrics import FontMetrics

#: line height = LINE_SPACING x font size (single source of truth for all backends)
LINE_SPACING = 1.2

#: default inner padding between a node box edge and its label
NODE_PADDING_H_MM = 2.5
NODE_PADDING_V_MM = 1.5

#: coordinates are compared with this tolerance when deciding "fits"
_FIT_EPS_MM = 1e-6


def _is_wide(char: str) -> bool:
    """CJK/fullwidth characters break between any two of them."""
    return unicodedata.east_asian_width(char) in ("W", "F")


@dataclass(frozen=True)
class PlacedLine:
    text: str
    x_mm: float  # left edge of the line, relative to the box top-left
    y_mm: float  # baseline of the line, relative to the box top-left
    width_mm: float


@dataclass(frozen=True)
class TextLayoutResult:
    lines: tuple[PlacedLine, ...]
    font_family: str  # family as requested (see FontMetrics.substituted for reality)
    font_size_pt: float
    line_height_pt: float
    text_width_mm: float  # widest line
    text_height_mm: float  # n_lines * line height
    fits: bool
    overflow_x_mm: float  # 0.0 when the block fits horizontally
    overflow_y_mm: float


def wrap_text(
    text: str, max_width_pt: float, metrics: FontMetrics, size_pt: float
) -> tuple[str, ...]:
    """Greedy wrap with word preference and hard breaks for oversized words.

    ``\\n`` always starts a new line. CJK characters may break between any two
    of them. Deterministic: pure function of (text, width, metrics, size).
    """
    if not text:
        return ()
    lines: list[str] = []
    for paragraph in text.split("\n"):
        if max_width_pt <= 0 or not paragraph.strip():
            lines.append(paragraph)
            continue
        if metrics.width_pt(paragraph, size_pt) <= max_width_pt:
            lines.append(paragraph)
            continue
        lines.extend(_wrap_paragraph(paragraph, max_width_pt, metrics, size_pt))
    return tuple(lines)


def _wrap_paragraph(
    paragraph: str, max_width_pt: float, metrics: FontMetrics, size_pt: float
) -> list[str]:
    lines: list[str] = []
    current = ""

    def push(text: str) -> None:
        stripped = text.rstrip()
        if stripped:
            lines.append(stripped)

    for char in paragraph:
        if char == " " and not current:
            continue  # never start a line with a space
        candidate = current + char
        if metrics.width_pt(candidate, size_pt) > max_width_pt and current:
            if char == " " or _is_wide(char) or " " not in current:
                push(current)
                current = "" if char == " " else char
            else:
                # prefer breaking at the previous space instead of mid-word
                cut = current.rfind(" ")
                push(current[:cut])
                current = current[cut + 1 :] + char
        else:
            current = candidate
    push(current)
    return lines or [paragraph]


class TextLayout:
    """Stateless layout engine bound to one resolved font."""

    def __init__(self, metrics: FontMetrics) -> None:
        self._metrics = metrics

    @property
    def metrics(self) -> FontMetrics:
        return self._metrics

    def layout_label(
        self,
        label: str,
        *,
        font_family: str,
        font_size_pt: float,
        box_w_mm: float,
        box_h_mm: float,
        padding_h_mm: float = NODE_PADDING_H_MM,
        padding_v_mm: float = NODE_PADDING_V_MM,
    ) -> TextLayoutResult:
        """Wrap ``label`` into the given box (mm) and position it centered.

        The result's coordinates are relative to the box top-left; every
        renderer is expected to add the box origin and draw nothing else.
        """
        metrics = self._metrics
        avail_w_pt = mm_to_pt(box_w_mm) - mm_to_pt(2 * padding_h_mm)
        line_texts = wrap_text(label, avail_w_pt, metrics, font_size_pt) if label else ()
        line_height_pt = font_size_pt * LINE_SPACING
        ascent_pt, descent_pt = metrics.ascent_descent_pt(font_size_pt)
        # Center the glyphs vertically inside each line slot.
        baseline_in_line_pt = (line_height_pt - (ascent_pt + descent_pt)) / 2 + ascent_pt
        baseline_in_line_mm = pt_to_mm(baseline_in_line_pt)

        widths_mm = [pt_to_mm(metrics.width_pt(t, font_size_pt)) for t in line_texts]
        text_w_mm = max(widths_mm, default=0.0)
        text_h_mm = pt_to_mm(len(line_texts) * line_height_pt)
        avail_w_mm = box_w_mm - 2 * padding_h_mm
        avail_h_mm = box_h_mm - 2 * padding_v_mm

        block_top_mm = max(padding_v_mm, (box_h_mm - text_h_mm) / 2)
        placed: list[PlacedLine] = []
        for index, line_text in enumerate(line_texts):
            line_w_mm = widths_mm[index]
            x_mm = max(padding_h_mm, (box_w_mm - line_w_mm) / 2)
            y_mm = block_top_mm + index * pt_to_mm(line_height_pt) + baseline_in_line_mm
            placed.append(
                PlacedLine(text=line_text, x_mm=x_mm, y_mm=y_mm, width_mm=line_w_mm)
            )

        return TextLayoutResult(
            lines=tuple(placed),
            font_family=font_family,
            font_size_pt=font_size_pt,
            line_height_pt=line_height_pt,
            text_width_mm=text_w_mm,
            text_height_mm=text_h_mm,
            fits=(
                text_w_mm <= avail_w_mm + _FIT_EPS_MM
                and text_h_mm <= avail_h_mm + _FIT_EPS_MM
            ),
            overflow_x_mm=max(0.0, text_w_mm - avail_w_mm),
            overflow_y_mm=max(0.0, text_h_mm - avail_h_mm),
        )

    def measure_block(
        self, label: str, *, font_size_pt: float
    ) -> tuple[float, float, int]:
        """Unconstrained size of ``label`` in mm: (width, height, n_lines).

        Used by automatic layout to size boxes around their labels. Explicit
        ``\\n`` produce extra lines; no automatic wrapping happens here.
        """
        metrics = self._metrics
        line_texts = wrap_text(label, inf, metrics, font_size_pt) if label else ()
        line_height_pt = font_size_pt * LINE_SPACING
        width_mm = max(
            (pt_to_mm(metrics.width_pt(t, font_size_pt)) for t in line_texts),
            default=0.0,
        )
        height_mm = pt_to_mm(len(line_texts) * line_height_pt)
        return width_mm, height_mm, len(line_texts)
