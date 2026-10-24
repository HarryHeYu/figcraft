"""CLI end-to-end for M1 commands: patch, layout, render, build.

Covers the M1 acceptance flow: a three-module pipeline JSON becomes a correct
SVG through one `build` command.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from papercanvas.cli import app

runner = CliRunner()

PIPELINE = {
    "schema_version": "0.1",
    "id": "method_pipeline",
    "canvas": {"width": 182.0, "height": 58.0, "unit": "mm", "margin": 4.0},
    "theme": {"font_family": "Arial", "font_size_pt": 8.0},
    "nodes": [
        {"id": "input", "type": "rounded_rect", "label": "Input Video"},
        {"id": "encoder", "type": "rounded_rect", "label": "Video Encoder"},
        {"id": "output", "type": "rounded_rect", "label": "Prediction"},
    ],
    "edges": [
        {"id": "e1", "source": "input", "target": "encoder"},
        {"id": "e2", "source": "encoder", "target": "output"},
    ],
    "groups": [],
}


def _write(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_full_flow_init_patch_layout_render(tmp_path: Path) -> None:
    ir = tmp_path / "fig.json"

    result = runner.invoke(app, ["init", str(ir), "--id", "flow"])
    assert result.exit_code == 0, result.output

    ops = {
        "operations": [
            {"op": "add_node", "node": {"id": "a", "label": "Alpha"}},
            {"op": "add_node", "node": {"id": "b", "label": "Beta"}},
            {"op": "add_edge", "edge": {"id": "e1", "source": "a", "target": "b"}},
        ]
    }
    ops_file = _write(tmp_path / "ops.json", ops)
    result = runner.invoke(app, ["patch", str(ir), "--ops", str(ops_file)])
    assert result.exit_code == 0, result.output
    assert "revision 2" in result.output

    result = runner.invoke(app, ["layout", str(ir), "--preset", "linear-h"])
    assert result.exit_code == 0, result.output
    assert "revision 3" in result.output

    result = runner.invoke(app, ["render", str(ir)])
    assert result.exit_code == 0, result.output
    svg = ir.with_suffix(".svg")
    assert svg.exists()
    assert b"<text" in svg.read_bytes()


def test_build_one_command_produces_svg(tmp_path: Path) -> None:
    """M1 acceptance: pipeline JSON -> one command -> correct SVG."""
    ir = _write(tmp_path / "pipeline.json", PIPELINE)
    result = runner.invoke(app, ["build", str(ir)])
    assert result.exit_code == 0, result.output

    svg = tmp_path / "pipeline.svg"
    assert svg.exists()
    payload = svg.read_bytes()
    assert b"<text" in payload
    assert b"Input Video" in payload
    assert b"Video Encoder" in payload
    assert b"Prediction" in payload
    assert b"<image" not in payload

    on_disk = json.loads(ir.read_text(encoding="utf-8"))
    assert on_disk["revision"] == 2  # layout committed once
    assert all(n["x"] is not None for n in on_disk["nodes"])


def test_patch_transaction_via_cli(tmp_path: Path, figure_dict: dict) -> None:
    ir = _write(tmp_path / "fig.json", figure_dict)
    ops = _write(
        tmp_path / "ops.json",
        {
            "expected_revision": 1,
            "operations": [
                {"op": "set_style", "target": "a", "style": {"fill": "#FCE4CF"}},
            ],
        },
    )
    result = runner.invoke(app, ["patch", str(ir), "--ops", str(ops)])
    assert result.exit_code == 0, result.output
    on_disk = json.loads(ir.read_text(encoding="utf-8"))
    assert on_disk["nodes"][0]["style"]["fill"] == "#FCE4CF"
    assert on_disk["revision"] == 2


def test_patch_failure_via_cli_keeps_file(tmp_path: Path, figure_dict: dict) -> None:
    ir = _write(tmp_path / "fig.json", figure_dict)
    before = ir.read_bytes()
    ops = _write(
        tmp_path / "ops.json",
        {"operations": [{"op": "remove_edge", "id": "missing"}]},
    )
    result = runner.invoke(app, ["patch", str(ir), "--ops", str(ops)])
    assert result.exit_code == 1
    assert ir.read_bytes() == before


def test_layout_unknown_preset_fails(tmp_path: Path, figure_dict: dict) -> None:
    ir = _write(tmp_path / "fig.json", figure_dict)
    result = runner.invoke(app, ["layout", str(ir), "--preset", "quantum"])
    assert result.exit_code != 0


def test_render_hardlink_alias_cannot_corrupt_the_ir(tmp_path: Path, figure_dict: dict) -> None:
    """Regression: a hardlink alias used to let --out write SVG bytes through
    the alias into the IR inode. Output is now committed via os.replace, so
    the alias entry is re-pointed and the IR inode survives."""
    ir = _write(tmp_path / "fig.json", figure_dict)
    alias = tmp_path / "alias.json"
    try:
        os.link(ir, alias)
    except OSError:
        pytest.skip("hardlinks unavailable on this filesystem")
    before = ir.read_bytes()

    result = runner.invoke(app, ["render", str(ir), "--out", str(alias)])

    assert result.exit_code == 0, result.output
    assert ir.read_bytes() == before  # the IR inode is untouched
    assert alias.read_bytes().startswith(b"<?xml")  # the alias now holds the SVG
    json.loads(before.decode("utf-8"))  # and it is still the valid IR document


def test_patch_deeply_nested_ops_file_is_clean(tmp_path: Path, figure_dict: dict) -> None:
    ir = _write(tmp_path / "fig.json", figure_dict)
    before = ir.read_bytes()
    ops = tmp_path / "deep.json"
    ops.write_bytes(b"[" * 60000 + b"]" * 60000)
    result = runner.invoke(app, ["patch", str(ir), "--ops", str(ops)])
    _assert_clean_error(result)
    assert ir.read_bytes() == before


# -- M2: multi-format render + lint -----------------------------------------


def test_render_all_formats(tmp_path: Path) -> None:
    ir = _write(tmp_path / "pipeline.json", PIPELINE)
    result = runner.invoke(app, ["build", str(ir), "--format", "all"])
    assert result.exit_code == 0, result.output
    for suffix in (".svg", ".pdf", ".pptx"):
        artifact = tmp_path / f"pipeline{suffix}"
        assert artifact.exists() and artifact.stat().st_size > 0
    assert (tmp_path / "pipeline.pdf").read_bytes().startswith(b"%PDF")
    pptx_bytes = (tmp_path / "pipeline.pptx").read_bytes()
    assert pptx_bytes.startswith(b"PK")  # OOXML zip container


def test_render_single_format_with_out(tmp_path: Path) -> None:
    ir = _write(tmp_path / "pipeline.json", PIPELINE)
    runner.invoke(app, ["build", str(ir)])  # lay it out first
    result = runner.invoke(
        app, ["render", str(ir), "--format", "pdf", "--out", str(tmp_path / "custom.pdf")]
    )
    assert result.exit_code == 0, result.output
    assert (tmp_path / "custom.pdf").exists()


def test_render_multi_format_rejects_out(tmp_path: Path) -> None:
    ir = _write(tmp_path / "pipeline.json", PIPELINE)
    result = runner.invoke(
        app, ["render", str(ir), "--format", "all", "--out", str(tmp_path / "x.svg")]
    )
    assert result.exit_code == 1
    assert "ambiguous" in result.output


def test_lint_clean_figure(tmp_path: Path) -> None:
    ir = _write(tmp_path / "pipeline.json", PIPELINE)
    runner.invoke(app, ["build", str(ir)])  # lay it out first
    result = runner.invoke(app, ["lint", str(ir)])
    assert result.exit_code == 0, result.output
    assert "0 error(s)" in result.output


def test_lint_reports_errors_with_exit_1(tmp_path: Path, figure_dict: dict) -> None:
    figure_dict["nodes"][0].update({"label": "A Very Long Module Label", "w": 12, "h": 6})
    ir = _write(tmp_path / "fig.json", figure_dict)
    result = runner.invoke(app, ["lint", str(ir)])
    assert result.exit_code == 1
    assert "FC003" in result.output


def test_lint_json_output_is_machine_readable(tmp_path: Path, figure_dict: dict) -> None:
    figure_dict["edges"][0]["target"] = "ghost"  # FC002
    ir = _write(tmp_path / "fig.json", figure_dict)
    result = runner.invoke(app, ["lint", str(ir), "--format", "json"])
    assert result.exit_code == 1
    report = json.loads(result.output[result.output.index("{") :])
    assert report["summary"]["errors"] >= 1
    finding = report["findings"][0]
    assert set(finding) == {"rule_id", "severity", "message", "object_id"}
    assert any(f["rule_id"] == "FC002" for f in report["findings"])


def test_lint_is_read_only(tmp_path: Path, figure_dict: dict) -> None:
    ir = _write(tmp_path / "fig.json", figure_dict)
    before = ir.read_bytes()
    result = runner.invoke(app, ["lint", str(ir)])
    assert result.exit_code == 0
    assert ir.read_bytes() == before


def test_lint_diagnoses_hard_invalid_figures(tmp_path: Path, figure_dict: dict) -> None:
    """Regression: lint must reach FC002 on schema-valid but hard-invalid
    figures (bad color) instead of crashing in the FC008 pre-render."""
    figure_dict["nodes"][0]["style"]["fill"] = "#not-a-color"
    ir = _write(tmp_path / "fig.json", figure_dict)
    before = ir.read_bytes()
    result = runner.invoke(app, ["lint", str(ir)])
    _assert_clean_error(result)
    assert "FC002" in result.output
    assert "#not-a-color" in result.output
    assert ir.read_bytes() == before


def test_render_without_coordinates_hints_layout(tmp_path: Path) -> None:
    ir = _write(tmp_path / "pipeline.json", PIPELINE)
    result = runner.invoke(app, ["render", str(ir)])
    assert result.exit_code == 1
    assert "layout" in result.output


def test_render_refuses_to_overwrite_the_ir_file(tmp_path: Path, figure_dict: dict) -> None:
    ir = _write(tmp_path / "fig.json", figure_dict)
    before = ir.read_bytes()
    result = runner.invoke(app, ["render", str(ir), "--out", str(ir)])
    assert result.exit_code == 1
    assert "refusing" in result.output
    assert ir.read_bytes() == before  # the source of truth is untouched


def _assert_clean_error(result) -> None:
    """exit 1 via typer.Exit — not an unhandled Python exception."""
    assert result.exit_code == 1
    assert result.exception is None or isinstance(result.exception, SystemExit)


def test_init_invalid_id_is_a_clean_error(tmp_path: Path) -> None:
    result = runner.invoke(app, ["init", str(tmp_path / "x.json"), "--id", "has space"])
    _assert_clean_error(result)
    assert "error" in result.output.lower()


def test_patch_malformed_ops_payload_is_clean(tmp_path: Path, figure_dict: dict) -> None:
    ir = _write(tmp_path / "fig.json", figure_dict)
    before = ir.read_bytes()
    for payload in (
        {"operations": 5},
        [{"op": "move_node"}],
        {"operations": ["junk"]},
        {"operations": [{"op": "add_node", "node": {"id": "bad id"}}]},
        {"operations": [{"op": "move_node", "id": "a", "x": True, "y": 0}]},
    ):
        ops = _write(tmp_path / "ops.json", payload)
        result = runner.invoke(app, ["patch", str(ir), "--ops", str(ops)])
        _assert_clean_error(result)
        assert ir.read_bytes() == before
