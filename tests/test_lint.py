"""Lint rules FC001–FC008 and the engine contract."""

from __future__ import annotations

import pytest

from papercanvas.core.models import Figure
from papercanvas.lint import ERROR, WARNING, LintConfig, findings_to_json, lint_figure
from papercanvas.lint.rules import RULE_ORDER
from papercanvas.render import render_svg
from papercanvas.text.text_layout import TextLayout
from papercanvas.text.text_metrics import FontMetrics


@pytest.fixture
def layout(figure_dict: dict) -> TextLayout:
    return TextLayout(FontMetrics.for_family(figure_dict["theme"]["font_family"]))


def _lint(fig: Figure, layout: TextLayout, **kwargs):
    return lint_figure(fig, layout, **kwargs)


def _ids(findings, rule_id: str):
    return [f for f in findings if f.rule_id == rule_id]


def test_clean_figure_has_no_findings(figure_dict: dict, layout: TextLayout) -> None:
    findings = _lint(Figure.model_validate(figure_dict), layout)
    assert findings == []


def test_fc001_node_outside_canvas(figure_dict: dict, layout: TextLayout) -> None:
    figure_dict["nodes"][0]["x"] = figure_dict["canvas"]["width"] - 5  # w=30 > 5 left
    findings = _lint(Figure.model_validate(figure_dict), layout)
    hits = _ids(findings, "FC001")
    assert hits and hits[0].severity == ERROR and hits[0].object_id == "a"


def test_fc001_unplaced_nodes_are_skipped(figure_dict: dict, layout: TextLayout) -> None:
    figure_dict["nodes"][0].update({"x": None, "y": None, "w": None, "h": None})
    findings = _lint(Figure.model_validate(figure_dict), layout)
    assert _ids(findings, "FC001") == []


def test_fc002_flags_api_constructed_invalid_figure(figure_dict: dict, layout: TextLayout) -> None:
    figure_dict["edges"][0]["target"] = "ghost"
    findings = _lint(Figure.model_validate(figure_dict), layout)
    hits = _ids(findings, "FC002")
    assert hits and hits[0].severity == ERROR
    assert "ghost" in hits[0].message


def test_fc003_text_overflow_uses_font_metrics(figure_dict: dict, layout: TextLayout) -> None:
    figure_dict["nodes"][0].update({"label": "A Very Long Module Label", "w": 12, "h": 6})
    findings = _lint(Figure.model_validate(figure_dict), layout)
    hits = _ids(findings, "FC003")
    assert hits and hits[0].severity == ERROR and hits[0].object_id == "a"
    assert "overflows" in hits[0].message


def test_fc004_overlapping_nodes_warn(figure_dict: dict, layout: TextLayout) -> None:
    figure_dict["nodes"][1].update({"x": 20, "y": 22})  # intersects node a
    findings = _lint(Figure.model_validate(figure_dict), layout)
    hits = _ids(findings, "FC004")
    assert hits and hits[0].severity == WARNING


def test_fc004_group_box_is_not_an_overlap(figure_dict: dict, layout: TextLayout) -> None:
    """Children inside their group's background box must not be flagged."""
    figure_dict["groups"].append({"id": "g1", "children": ["a", "b"]})
    findings = _lint(Figure.model_validate(figure_dict), layout)
    assert _ids(findings, "FC004") == []


def test_fc005_font_size_below_threshold(figure_dict: dict, layout: TextLayout) -> None:
    figure_dict["theme"]["font_size_pt"] = 5.0
    findings = _lint(Figure.model_validate(figure_dict), layout)
    hits = _ids(findings, "FC005")
    assert hits and hits[0].severity == WARNING
    # and it respects the configured threshold
    findings = _lint(
        Figure.model_validate(figure_dict), layout, config=LintConfig(min_font_size_pt=4.0)
    )
    assert _ids(findings, "FC005") == []


def test_fc006_avoidable_crossing_is_routed_around(figure_dict: dict, layout: TextLayout) -> None:
    """a -> c straight across the middle node b: obstacle-aware routing
    detours the edge, so FC006 stays silent — no finding for a problem the
    renderer does not have."""
    figure_dict["nodes"] = [
        {"id": "a", "x": 10, "y": 20, "w": 20, "h": 10},
        {"id": "b", "x": 45, "y": 20, "w": 20, "h": 10},
        {"id": "c", "x": 80, "y": 20, "w": 20, "h": 10},
    ]
    figure_dict["edges"] = [{"id": "e1", "source": "a", "target": "c"}]
    findings = _lint(Figure.model_validate(figure_dict), layout)
    assert _ids(findings, "FC006") == []


def test_fc006_unavoidable_crossing_warns(figure_dict: dict, layout: TextLayout) -> None:
    """When detour channels above AND below are blocked, the router keeps the
    crossing path and FC006 must report it."""
    figure_dict["nodes"] = [
        {"id": "a", "x": 10, "y": 20, "w": 20, "h": 10},
        {"id": "b", "x": 45, "y": 20, "w": 20, "h": 10},
        {"id": "c", "x": 80, "y": 20, "w": 20, "h": 10},
        {"id": "wall_top", "x": 38, "y": 8, "w": 34, "h": 8},
        {"id": "wall_bottom", "x": 38, "y": 34, "w": 34, "h": 8},
    ]
    figure_dict["edges"] = [{"id": "e1", "source": "a", "target": "c"}]
    findings = _lint(Figure.model_validate(figure_dict), layout)
    hits = _ids(findings, "FC006")
    assert hits and hits[0].severity == WARNING and hits[0].object_id == "e1"


def test_fc006_clean_routing_not_flagged(figure_dict: dict, layout: TextLayout) -> None:
    findings = _lint(Figure.model_validate(figure_dict), layout)
    assert _ids(findings, "FC006") == []


def test_fc007_substituted_font_warns(figure_dict: dict, layout: TextLayout) -> None:
    figure_dict["theme"]["font_family"] = "No Such Font 42"
    fig = Figure.model_validate(figure_dict)
    custom = TextLayout(FontMetrics.for_family(fig.theme.font_family))
    assert custom.metrics.substituted
    findings = _lint(fig, custom)
    hits = _ids(findings, "FC007")
    assert hits and hits[0].severity == WARNING


def test_fc007_message_names_requested_and_actual_font(figure_dict: dict) -> None:
    """Real substitutions must produce a finding that names BOTH the family
    the IR asked for and the font actually used (task: FC007 提示真实替代)."""
    requested = "No Such Font 42"
    figure_dict["theme"]["font_family"] = requested
    fig = Figure.model_validate(figure_dict)
    custom = TextLayout(FontMetrics.for_family(requested))
    assert custom.metrics.substituted
    hit = _ids(_lint(fig, custom), "FC007")[0]
    assert requested in hit.message
    assert custom.metrics.resolved_family in hit.message


def test_fc007_absent_when_resolution_is_faithful(figure_dict: dict) -> None:
    """Requesting a family that this machine resolves faithfully must NOT
    trigger FC007 — on every platform, whatever that family locally is."""
    probe = FontMetrics.for_family("Arial")
    family = probe.resolved_family if probe.substituted else "Arial"
    figure_dict["theme"]["font_family"] = family
    fig = Figure.model_validate(figure_dict)
    layout = TextLayout(FontMetrics.for_family(family))
    assert not layout.metrics.substituted  # self-check: faithful resolution
    assert _ids(_lint(fig, layout), "FC007") == []


def test_fc008_scans_rendered_svg_for_images(figure_dict: dict, layout: TextLayout) -> None:
    fig = Figure.model_validate(figure_dict)
    assert _lint(fig, layout, svg_bytes=render_svg(fig, layout)) == []
    dirty = b'<svg><image href="x.png"/><text>a</text></svg>'
    hits = _lint(fig, layout, svg_bytes=dirty)
    assert hits and hits[0].rule_id == "FC008" and hits[0].severity == WARNING


def test_fc008_without_svg_bytes_reports_nothing(figure_dict: dict, layout: TextLayout) -> None:
    assert _lint(Figure.model_validate(figure_dict), layout) == []


def test_findings_order_is_deterministic(figure_dict: dict, layout: TextLayout) -> None:
    figure_dict["nodes"][0]["x"] = 999
    figure_dict["nodes"][1].update({"x": 20, "y": 22})
    fig = Figure.model_validate(figure_dict)
    first = _lint(fig, layout)
    second = _lint(fig, layout)
    assert first == second
    assert [f.rule_id for f in first] == sorted(
        (f.rule_id for f in first), key=RULE_ORDER.index
    )


def test_findings_to_json_shape(figure_dict: dict, layout: TextLayout) -> None:
    figure_dict["edges"][0]["target"] = "ghost"
    report = findings_to_json(_lint(Figure.model_validate(figure_dict), layout))
    assert report["summary"]["errors"] >= 1
    assert report["summary"]["warnings"] == len(report["findings"]) - report["summary"]["errors"]
    for finding in report["findings"]:
        assert set(finding) == {"rule_id", "severity", "message", "object_id"}


def test_lint_never_writes_the_source(figure_dict: dict, layout: TextLayout, tmp_path) -> None:
    from papercanvas.core.document import FigureDocument

    path = tmp_path / "fig.json"
    FigureDocument.create(path, Figure.model_validate(figure_dict))
    before = path.read_bytes()
    _lint(FigureDocument.load(path).figure, layout, svg_bytes=b"<svg/>")
    assert path.read_bytes() == before
