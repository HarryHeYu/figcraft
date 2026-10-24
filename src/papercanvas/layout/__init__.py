"""Automatic layout: linear and layered presets + orthogonal routing.

Layout is a MUTABLE operation on the IR (it writes coordinates): callers must
commit the returned figure through ``FigureDocument.save_figure`` so the file
lock / expected_revision / atomic-write discipline applies (constraint 3).

Determinism: pure functions of the IR — no randomness, no wall clock, no
set/dict iteration order in the output (constraint 6d).
"""

from papercanvas.layout.layered import layout_layered
from papercanvas.layout.linear import layout_linear
from papercanvas.layout.sizes import auto_size_nodes, text_layout_for_theme

LAYOUT_PRESETS: tuple[str, ...] = ("linear-h", "linear-v", "layered")

__all__ = [
    "LAYOUT_PRESETS",
    "auto_size_nodes",
    "layout_layered",
    "layout_linear",
    "run_layout",
    "text_layout_for_theme",
]


def run_layout(fig, preset: str):  # -> Figure (untyped here to avoid a cycle)
    """Apply a layout preset and return a new laid-out Figure (original untouched)."""
    if preset not in LAYOUT_PRESETS:
        raise ValueError(f"unknown layout preset {preset!r}; supported: {list(LAYOUT_PRESETS)}")
    from papercanvas.core.validate import ensure_valid

    ensure_valid(fig)  # layout refuses to run on an already-invalid figure
    if preset == "linear-h":
        result = layout_linear(fig, direction="h")
    elif preset == "linear-v":
        result = layout_linear(fig, direction="v")
    else:
        result = layout_layered(fig)
    ensure_valid(result)
    return result
