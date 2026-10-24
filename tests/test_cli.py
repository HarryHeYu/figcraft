"""CLI end-to-end for M0 commands: init, validate, --version."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from papercanvas import __version__
from papercanvas.cli import app

runner = CliRunner()


def test_version_flag() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_init_then_validate_roundtrip(tmp_path: Path) -> None:
    target = tmp_path / "new.json"
    result = runner.invoke(
        app, ["init", str(target), "--id", "my_fig", "--width", "120", "--height", "80"]
    )
    assert result.exit_code == 0, result.output
    assert target.exists()

    result = runner.invoke(app, ["validate", str(target)])
    assert result.exit_code == 0, result.output
    assert "valid" in result.output
    assert "my_fig" in result.output


def test_init_refuses_overwrite(tmp_path: Path) -> None:
    target = tmp_path / "new.json"
    first = runner.invoke(app, ["init", str(target), "--id", "one"])
    assert first.exit_code == 0, first.output
    second = runner.invoke(app, ["init", str(target), "--id", "two"])
    assert second.exit_code == 1
    assert "refusing to overwrite" in second.output


def test_validate_reports_hard_errors(tmp_path: Path, figure_dict: dict) -> None:
    import json

    figure_dict["edges"][0]["target"] = "ghost"
    target = tmp_path / "broken.json"
    target.write_text(json.dumps(figure_dict), encoding="utf-8")

    result = runner.invoke(app, ["validate", str(target)])
    assert result.exit_code == 1
    assert "invalid" in result.output
    assert "ghost" in result.output


def test_validate_missing_file_fails_cleanly(tmp_path: Path) -> None:
    result = runner.invoke(app, ["validate", str(tmp_path / "absent.json")])
    assert result.exit_code == 1
    assert "error" in result.output
