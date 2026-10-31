"""Figure Doctor — aggregated quality diagnosis for a figure.

One call that runs hard validation, FC001–FC008 lint, font coverage, and
three-format renderability, then classifies every finding as blocking /
advisory / environment so an agent knows what to fix before delivering.
Read-only: never touches the IR file or writes to disk.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from papercanvas.core.models import Figure
from papercanvas.text.text_layout import TextLayout

DoctorLevel = Literal["blocking", "advisory", "environment"]

_LEVEL_ORDER: dict[str, int] = {"blocking": 0, "advisory": 1, "environment": 2}


@dataclass(frozen=True)
class DoctorFinding:
    level: DoctorLevel
    rule_id: str
    message: str
    object_id: str | None = None
    suggested_patch: dict | None = None

    def as_dict(self) -> dict:
        d: dict = {"level": self.level, "rule_id": self.rule_id, "message": self.message}
        if self.object_id is not None:
            d["object_id"] = self.object_id
        if self.suggested_patch is not None:
            d["suggested_patch"] = self.suggested_patch
        return d


@dataclass(frozen=True)
class DoctorReport:
    findings: list[DoctorFinding]
    renderability: dict[str, bool]
    font: dict

    @property
    def blocking_count(self) -> int:
        return sum(1 for f in self.findings if f.level == "blocking")

    @property
    def healthy(self) -> bool:
        return self.blocking_count == 0

    def as_dict(self) -> dict:
        return {
            "findings": [f.as_dict() for f in self.findings],
            "renderability": self.renderability,
            "font": self.font,
            "summary": {
                "blocking": self.blocking_count,
                "advisory": sum(1 for f in self.findings if f.level == "advisory"),
                "environment": sum(1 for f in self.findings if f.level == "environment"),
                "healthy": self.healthy,
            },
        }


def run_doctor(
    fig: Figure,
    layout: TextLayout,
    *,
    svg_bytes: bytes | None = None,
) -> DoctorReport:
    """Aggregate every quality signal into one classified report.

    Read-only: the engine's own guarantees mean this never writes to disk.
    """
    from papercanvas.lint import lint_figure
    from papercanvas.text.text_metrics import file_covers, file_is_true_type

    findings: list[DoctorFinding] = []
    figure_text = "\n".join(
        [n.label for n in fig.nodes if n.label]
        + [g.label for g in fig.groups if g.label]
    )

    # -- hard validation ------------------------------------------------------
    from papercanvas.core.validate import validate_figure

    for msg in validate_figure(fig):
        findings.append(DoctorFinding("blocking", "VALIDATION", msg))

    # -- font coverage --------------------------------------------------------
    metrics = layout.metrics
    font_info = {
        "requested": metrics.family,
        "resolved": metrics.resolved_family,
        "substituted": metrics.substituted,
        "substitution_reason": metrics.substitution_reason,
        "file": metrics.path.name,
    }
    uncovered: list[str] = []
    if figure_text:
        uncovered = sorted(
            {
                ch
                for ch in figure_text
                if not ch.isspace() and not file_covers(str(metrics.path), ch)
            }
        )
    if uncovered:
        sample = ", ".join(f"U+{ord(ch):04X} {ch!r}" for ch in uncovered[:8])
        more = f" (+{len(uncovered) - 8} more)" if len(uncovered) > 8 else ""
        findings.append(
            DoctorFinding(
                "environment",
                "FONT_COVERAGE",
                f"{len(uncovered)} character(s) not covered by {metrics.resolved_family!r}: "
                f"{sample}{more}. PDF will show boxes for these; SVG/PPTX depend on viewer.",
            )
        )
    if metrics.substituted:
        reason = metrics.substitution_reason or "is not installed"
        findings.append(
            DoctorFinding(
                "environment",
                "FONT_SUBSTITUTION",
                f"font family {metrics.family!r} {reason}; "
                f"using {metrics.resolved_family!r} ({metrics.path.name})",
            )
        )

    # -- lint (skipped when hard validation failed; the structural errors
    #    make the lint results noisy and unreliable) ---------------------------
    renderability: dict[str, bool] = {"svg": False, "pdf": False, "pptx": False}
    has_validation_errors = any(f.rule_id == "VALIDATION" for f in findings)

    if not has_validation_errors:
        lint_findings = lint_figure(fig, layout, svg_bytes=svg_bytes)
        for lf in lint_findings:
            level: DoctorLevel = "blocking" if lf.severity == "error" else "advisory"
            finding = DoctorFinding(level, lf.rule_id, lf.message, lf.object_id)

            # Actionable suggestion for FC003 (text overflow)
            if lf.rule_id == "FC003" and lf.object_id is not None:
                node = fig.node(lf.object_id)
                if node is not None and node.label:
                    result = layout.layout_label(
                        node.label,
                        font_family=fig.theme.font_family,
                        font_size_pt=fig.theme.font_size_pt,
                        box_w_mm=10_000,
                        box_h_mm=node.h or 10,
                    )
                    needed_w = round(result.text_width_mm + 5.0, 1)
                    import dataclasses

                    finding = dataclasses.replace(
                        finding,
                        suggested_patch={"op": "update_node", "id": node.id, "w": needed_w}
                    )

            findings.append(finding)

        # -- renderability ------------------------------------------------------
        from papercanvas.core.errors import RenderError
        from papercanvas.render.style import require_placed

        try:
            require_placed(fig)
            renderability = {"svg": True, "pdf": True, "pptx": True}
            if not file_is_true_type(str(metrics.path)):
                renderability["pdf"] = False
                findings.append(
                    DoctorFinding(
                        "environment",
                        "PDF_FONT_CFF",
                        f"resolved font {metrics.resolved_family!r} is CFF-flavored; "
                        f"PDF export will raise. Use SVG/PPTX or install a TrueType CJK font.",
                    )
                )
        except RenderError:
            renderability = {"svg": False, "pdf": False, "pptx": False}
            findings.append(
                DoctorFinding(
                    "blocking",
                    "NOT_PLACED",
                    "nodes have no coordinates; run `papercanvas layout` before rendering",
                )
            )

    findings.sort(key=lambda f: (_LEVEL_ORDER.get(f.level, 9), f.rule_id, f.message))
    return DoctorReport(findings=findings, renderability=renderability, font=font_info)
