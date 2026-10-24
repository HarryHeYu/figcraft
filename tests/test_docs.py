"""Tests that keep the README examples honest: extract -> validate -> render."""

from __future__ import annotations

import json
import re
from pathlib import Path

from typer.testing import CliRunner

from papercanvas.cli import app
from papercanvas.core.models import Figure
from papercanvas.core.validate import ensure_valid

REPO_ROOT = Path(__file__).resolve().parent.parent
runner = CliRunner()


def _readme_json_blocks() -> list[dict]:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    blocks = []
    for match in re.finditer(r"```json\n(.*?)```", readme, re.DOTALL):
        blocks.append(json.loads(match.group(1)))
    return blocks


def test_readme_json_blocks_are_valid_figure_ir(tmp_path: Path) -> None:
    """Every ```json block in the README must be a valid, renderable Figure IR."""
    blocks = _readme_json_blocks()
    assert blocks, "README lost its Figure IR example"
    for index, payload in enumerate(blocks):
        figure = Figure.model_validate(payload)
        ensure_valid(figure)  # no dangling edges, no hard errors

        target = tmp_path / f"readme_block_{index}.json"
        target.write_text(json.dumps(payload), encoding="utf-8")
        result = runner.invoke(app, ["build", str(target)])
        assert result.exit_code == 0, f"README block {index} fails to build: {result.output}"


def test_readme_naming_section_is_unambiguous() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "pip install papercanvas" in readme
    assert "papercanvas_create" in readme  # MCP tool prefix documented
    assert "HarryHeYu/figcraft" in readme  # repo name documented
    # no leftover claim that the PyPI package is called figcraft
    assert "pip install figcraft" not in readme
