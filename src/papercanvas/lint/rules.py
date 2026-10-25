"""Lint rules FC001–FC008 — figure QUALITY checks.

Deliberately separate from core/validate.py hard errors (constraint 5):
lint findings advise, they never block loading, patching or rendering.
Every rule is computed from real geometry or font metrics — no
"character count x average width" approximations.
"""

from __future__ import annotations

from dataclasses import dataclass

from papercanvas.core.models import Figure, Node
from papercanvas.layout.routing import route_orthogonal
from papercanvas.text.text_layout import TextLayout

ERROR = "error"
WARNING = "warning"

_EPS = 1e-6

RULE_ORDER: tuple[str, ...] = (
    "FC001", "FC002", "FC003", "FC004", "FC005", "FC006", "FC007", "FC008"
)


@dataclass(frozen=True)
class Finding:
    rule_id: str
    severity: str  # "error" | "warning"
    message: str
    object_id: str | None = None

    def as_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "severity": self.severity,
            "message": self.message,
            "object_id": self.object_id,
        }


def fc001_canvas_bounds(fig: Figure) -> list[Finding]:
    findings: list[Finding] = []
    for node in fig.nodes:
        if not node.is_placed:
            continue
        outside = (
            node.x < -_EPS
            or node.y < -_EPS
            or node.x + node.w > fig.canvas.width + _EPS
            or node.y + node.h > fig.canvas.height + _EPS
        )
        if outside:
            findings.append(
                Finding(
                    "FC001",
                    ERROR,
                    f"node {node.id!r} crosses the canvas bounds "
                    f"(node [{node.x:g}, {node.y:g}, {node.w:g}x{node.h:g}] vs canvas "
                    f"{fig.canvas.width:g}x{fig.canvas.height:g} mm)",
                    node.id,
                )
            )
    return findings


def fc002_invalid_structure(fig: Figure) -> list[Finding]:
    """Duplicate ids / invalid connections — a lint pass over API-constructed
    figures that may have skipped hard validation."""
    from papercanvas.core.validate import validate_figure

    return [Finding("FC002", ERROR, message) for message in validate_figure(fig)]


def fc003_text_overflow(fig: Figure, text_layout: TextLayout) -> list[Finding]:
    """Label overflow per node, computed from real font metrics.

    Scope note: v0.1 covers node labels only; group labels wrap into a
    padding-derived box and are deliberately out of range until M3.
    """
    findings: list[Finding] = []
    for node in fig.nodes:
        if not node.is_placed or not node.label:
            continue
        result = text_layout.layout_label(
            node.label,
            font_family=fig.theme.font_family,
            font_size_pt=fig.theme.font_size_pt,
            box_w_mm=node.w,
            box_h_mm=node.h,
        )
        if not result.fits:
            findings.append(
                Finding(
                    "FC003",
                    ERROR,
                    f"node {node.id!r}: label overflows its box "
                    f"(x+{result.overflow_x_mm:.2f} mm, y+{result.overflow_y_mm:.2f} mm)",
                    node.id,
                )
            )
    return findings


def fc004_node_overlap(fig: Figure) -> list[Finding]:
    """Unexpected node overlaps. Group members sitting inside the group's
    background box are fine — the group box is not a node."""
    findings: list[Finding] = []
    placed = [node for node in fig.nodes if node.is_placed]
    for i in range(len(placed)):
        for j in range(i + 1, len(placed)):
            a, b = placed[i], placed[j]
            overlap_w = min(a.x + a.w, b.x + b.w) - max(a.x, b.x)
            overlap_h = min(a.y + a.h, b.y + b.h) - max(a.y, b.y)
            if overlap_w > _EPS and overlap_h > _EPS:
                findings.append(
                    Finding(
                        "FC004",
                        WARNING,
                        f"nodes {a.id!r} and {b.id!r} overlap "
                        f"({max(overlap_w, 0):.2f} x {max(overlap_h, 0):.2f} mm)",
                        a.id,
                    )
                )
    return findings


def fc005_font_size(fig: Figure, min_font_size_pt: float) -> list[Finding]:
    if fig.theme.font_size_pt < min_font_size_pt:
        return [
            Finding(
                "FC005",
                WARNING,
                f"theme font size {fig.theme.font_size_pt:g} pt is below the "
                f"configured minimum {min_font_size_pt:g} pt",
            )
        ]
    return []


def fc006_arrow_through_node(fig: Figure) -> list[Finding]:
    findings: list[Finding] = []
    for edge in fig.edges:
        source = fig.node(edge.source)
        target = fig.node(edge.target)
        if source is None or target is None:
            continue
        if not source.is_placed or not target.is_placed:
            continue
        obstacles = [
            node
            for node in fig.nodes
            if node.is_placed and node.id not in (edge.source, edge.target)
        ]
        points = route_orthogonal(
            source, edge.source_port, target, edge.target_port, obstacles
        )
        for node in fig.nodes:
            if node.id in (edge.source, edge.target) or not node.is_placed:
                continue
            if _path_hits(points, node):
                findings.append(
                    Finding(
                        "FC006",
                        WARNING,
                        f"edge {edge.id!r} passes through unrelated node {node.id!r}",
                        edge.id,
                    )
                )
    return findings


def _path_hits(points, node: Node) -> bool:
    """Liang-Barsky style segment/AABB intersection against the node rect,
    shrunk by a hair so merely touching a boundary is not 'passing through'."""
    x0, y0 = node.x + _EPS, node.y + _EPS
    x1, y1 = node.x + node.w - _EPS, node.y + node.h - _EPS
    for start, end in zip(points, points[1:], strict=False):
        dx, dy = end.x - start.x, end.y - start.y
        t0, t1 = 0.0, 1.0
        for p, q in (
            (-dx, start.x - x0),
            (dx, x1 - start.x),
            (-dy, start.y - y0),
            (dy, y1 - start.y),
        ):
            if p == 0:
                if q < 0:
                    break
                continue
            t = q / p
            if p < 0:
                t0 = max(t0, t)
            else:
                t1 = min(t1, t)
            if t0 > t1:
                break
        else:
            return True
    return False


def fc007_font_resolution(fig: Figure, text_layout: TextLayout) -> list[Finding]:
    metrics = text_layout.metrics
    if metrics.substituted:
        reason = metrics.substitution_reason or "is not installed"
        return [
            Finding(
                "FC007",
                WARNING,
                f"font family {fig.theme.font_family!r} {reason}; "
                f"substituted with {metrics.resolved_family!r} "
                f"({metrics.path.name}) — line breaks were measured against "
                f"the substitute",
            )
        ]
    return []


def fc008_raster_images(fig: Figure, svg_bytes: bytes | None) -> list[Finding]:
    """v0.1's IR cannot declare images, so any <image> in a rendered artifact
    would be undeclared. Skipped honestly when no rendered output is given."""
    if svg_bytes is None:
        return []
    if b"<image" in svg_bytes:
        return [
            Finding(
                "FC008",
                WARNING,
                "rendered output contains a raster <image> element, which the "
                "Figure IR cannot have declared",
            )
        ]
    return []
