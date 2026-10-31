"""Figure Doctor: aggregated diagnosis (blocking / advisory / environment)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from papercanvas.core.models import Figure
from papercanvas.doctor import run_doctor
from papercanvas.service import text_layout_for
from papercanvas.text.text_layout import TextLayout
from papercanvas.text.text_metrics import FontMetrics


@pytest.fixture
def layout(figure_dict: dict) -> TextLayout:
    fig = Figure.model_validate(figure_dict)
    return text_layout_for(fig)


def _lint(fig: Figure, layout: TextLayout, **kwargs):
    return run_doctor(fig, layout, **kwargs).findings


def test_clean_figure_is_healthy(figure_dict: dict, layout: TextLayout) -> None:
    report = run_doctor(Figure.model_validate(figure_dict), layout)
    assert report.healthy
    assert report.blocking_count == 0
    d = report.as_dict()
    assert d["summary"]["healthy"] is True
    assert d["renderability"] == {"svg": True, "pdf": True, "pptx": True}


def test_fc003_suggests_wider_node(figure_dict: dict, layout: TextLayout) -> None:
    figure_dict["nodes"][0].update({"label": "A Very Long Module Label", "w": 12, "h": 6})
    fig = Figure.model_validate(figure_dict)
    report = run_doctor(fig, layout)
    fc003 = [f for f in report.findings if f.rule_id == "FC003"]
    assert fc003 and fc003[0].level == "blocking"
    assert fc003[0].suggested_patch is not None
    patch = fc003[0].suggested_patch
    assert patch["op"] == "update_node"
    assert patch["id"] == "a"
    assert patch["w"] > 12  # suggests a wider box


def test_unplaced_figure_reports_blocking(figure_dict: dict) -> None:
    figure_dict["nodes"][0].pop("x")
    figure_dict["nodes"][0].pop("y")
    fig = Figure.model_validate(figure_dict)
    layout = TextLayout(FontMetrics.for_family(fig.theme.font_family))
    report = run_doctor(fig, layout)
    not_placed = [f for f in report.findings if f.rule_id == "NOT_PLACED"]
    assert not_placed and not_placed[0].level == "blocking"


def test_font_coverage_is_environment_not_blocking(figure_dict: dict, layout: TextLayout) -> None:
    figure_dict["nodes"][0]["label"] = "视频编码器模块"
    fig = Figure.model_validate(figure_dict)
    layout = TextLayout(FontMetrics.for_family(fig.theme.font_family))
    report = run_doctor(fig, layout)
    font_hits = [f for f in report.findings if f.rule_id == "FONT_COVERAGE"]
    if not font_hits:
        pytest.skip("this machine's font covers CJK glyphs")
    assert font_hits[0].level == "environment"
    assert report.healthy  # environment findings don't make it unhealthy


def test_validation_errors_block_before_lint(figure_dict: dict, layout: TextLayout) -> None:
    """When hard validation fails, lint is skipped to avoid noise."""
    figure_dict["edges"][0]["target"] = "ghost"
    findings = run_doctor(Figure.model_validate(figure_dict), layout).findings
    assert any(f.rule_id == "VALIDATION" for f in findings)
    assert not any(f.rule_id == "FC001" for f in findings)  # lint was skipped


def test_doctor_json_serializable(figure_dict: dict, layout: TextLayout) -> None:
    report = run_doctor(Figure.model_validate(figure_dict), layout)
    d = report.as_dict()
    json.dumps(d)  # must not raise


def test_doctor_read_only(figure_dict: dict, tmp_path: Path) -> None:
    from papercanvas.core.document import FigureDocument

    ir = tmp_path / "fig.json"
    FigureDocument.create(ir, Figure.model_validate(figure_dict))
    before = ir.read_bytes()
    doc = FigureDocument.load(ir)
    layout = TextLayout(FontMetrics.for_family(doc.figure.theme.font_family))
    run_doctor(doc.figure, layout)
    assert ir.read_bytes() == before
