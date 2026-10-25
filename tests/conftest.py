"""Shared fixtures and a minimal valid Figure IR used across the test suite."""

from __future__ import annotations

import copy

import pytest

MINIMAL_FIGURE: dict = {
    "schema_version": "0.1",
    "id": "fig_test",
    "revision": 1,
    "canvas": {"width": 100.0, "height": 60.0, "unit": "mm", "margin": 4.0},
    "theme": {
        "font_family": "Arial",
        "font_size_pt": 8.0,
        "palette": {"accent": "#3366CC"},
        "background": "#FFFFFF",
    },
    "nodes": [
        {
            "id": "a",
            "type": "rect",
            "label": "Alpha",
            "x": 10.0,
            "y": 20.0,
            "w": 30.0,
            "h": 15.0,
            "style": {"fill": "#E8F0FE", "stroke": "#4275C4"},
        },
        {
            "id": "b",
            "type": "rounded_rect",
            "label": "Beta",
            "x": 60.0,
            "y": 20.0,
            "w": 30.0,
            "h": 15.0,
            "style": {"fill": "accent"},
        },
    ],
    "edges": [
        {
            "id": "e1",
            "source": "a",
            "target": "b",
            "source_port": "right",
            "target_port": "left",
            "style": {"stroke": "#444444", "arrow": "end"},
        }
    ],
    "groups": [],
}


def faithful_family() -> str:
    """A family name this machine resolves WITHOUT substitution.

    Requesting "Arial" on a Linux runner correctly yields an FC007
    substitution warning (the font genuinely is not there), so tests that
    expect a lint-clean figure must ask for the locally faithful family.
    """
    from papercanvas.text.text_metrics import FontMetrics

    probe = FontMetrics.for_family("Arial")
    return probe.resolved_family if probe.substituted else probe.family


@pytest.fixture
def figure_dict() -> dict:
    """A deep copy of a minimal, valid Figure IR dict — mutate freely.

    The theme font is the locally faithful family so lint-related tests do
    not depend on which fonts a CI image happens to ship.
    """
    payload = copy.deepcopy(MINIMAL_FIGURE)
    payload["theme"]["font_family"] = faithful_family()
    return payload
