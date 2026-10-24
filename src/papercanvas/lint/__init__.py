"""Lint: figure-quality checks FC001–FC008, strictly separated from hard validation."""

from papercanvas.lint.engine import LintConfig, findings_to_json, lint_figure
from papercanvas.lint.rules import ERROR, WARNING, Finding

__all__ = ["ERROR", "WARNING", "Finding", "LintConfig", "findings_to_json", "lint_figure"]
