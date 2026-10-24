"""Lint engine: runs FC001–FC008 and produces machine-readable findings.

Strictly read-only — linting never touches the IR file or renders to disk.
"""

from __future__ import annotations

from dataclasses import dataclass

from papercanvas.core.models import Figure
from papercanvas.lint import rules
from papercanvas.lint.rules import ERROR, Finding
from papercanvas.text.text_layout import TextLayout


@dataclass(frozen=True)
class LintConfig:
    """Thresholds a caller may tune (FC005 is the only configurable rule)."""

    min_font_size_pt: float = 6.0


DEFAULT_CONFIG = LintConfig()


def lint_figure(
    fig: Figure,
    text_layout: TextLayout,
    *,
    config: LintConfig = DEFAULT_CONFIG,
    svg_bytes: bytes | None = None,
) -> list[Finding]:
    """Run every rule and return findings in stable, deterministic order.

    ``svg_bytes`` (optional) enables the FC008 output scan; when the caller
    does not supply rendered output, FC008 reports nothing.
    """
    findings: list[Finding] = []
    findings += rules.fc001_canvas_bounds(fig)
    findings += rules.fc002_invalid_structure(fig)
    findings += rules.fc003_text_overflow(fig, text_layout)
    findings += rules.fc004_node_overlap(fig)
    findings += rules.fc005_font_size(fig, config.min_font_size_pt)
    findings += rules.fc006_arrow_through_node(fig)
    findings += rules.fc007_font_resolution(fig, text_layout)
    findings += rules.fc008_raster_images(fig, svg_bytes)

    order = {rule_id: index for index, rule_id in enumerate(rules.RULE_ORDER)}
    findings.sort(key=lambda finding: (order.get(finding.rule_id, 99), finding.message))
    return findings


def findings_to_json(findings: list[Finding]) -> dict:
    """Machine-readable result: rule id, severity, message, object id."""
    errors = sum(1 for finding in findings if finding.severity == ERROR)
    warnings = len(findings) - errors
    return {
        "findings": [finding.as_dict() for finding in findings],
        "summary": {"errors": errors, "warnings": warnings},
    }
