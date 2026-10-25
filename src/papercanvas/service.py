"""Shared service layer — the single business surface for CLI, MCP and Python API.

Every operation takes a :class:`ServiceContext` bound to one project root and
returns JSON-safe dicts, so MCP tool results need no adapter logic. Path
policy: every path argument must resolve inside the context root — this is
the MCP security requirement, and the CLI uses the same code with
``root=Path.cwd()``.

Operations raise :class:`papercanvas.core.errors.PaperCanvasError` subclasses
on failure and never leave partial writes behind (core guarantees).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from papercanvas.core.document import FigureDocument, atomic_write
from papercanvas.core.errors import PaperCanvasError, RenderError
from papercanvas.core.models import Figure
from papercanvas.core.patch import PatchRequest, apply_patch
from papercanvas.core.validate import validate_figure
from papercanvas.layout import LAYOUT_PRESETS, run_layout
from papercanvas.lint import LintConfig, findings_to_json, lint_figure
from papercanvas.render import RENDER_SUFFIXES, render_pdf, render_pptx, render_svg
from papercanvas.text.text_layout import TextLayout
from papercanvas.text.text_metrics import FontMetrics


@dataclass(frozen=True)
class ServiceContext:
    """One project root. With ``enforce_root=True`` (the MCP posture) every
    path argument must resolve inside the root; the local CLI passes
    ``enforce_root=False`` because a local user may point anywhere."""

    root: Path = Path(".")
    enforce_root: bool = True

    def resolve(self, path_str: str | os.PathLike[str]) -> Path:
        candidate = Path(path_str)
        if not candidate.is_absolute():
            candidate = self.root / candidate
        resolved = candidate.resolve()
        if self.enforce_root:
            root = self.root.resolve()
            if resolved != root and root not in resolved.parents:
                raise PaperCanvasError(
                    f"path {str(path_str)!r} escapes the project root {str(root)!r}; "
                    f"only files inside the root may be touched"
                )
        return resolved


def text_layout_for(fig: Figure) -> TextLayout:
    """One TextLayout for the whole figure, resolved against ALL label text
    so the chosen font covers every glyph (CJK labels included) and all
    three renderers measure with the exact same font."""
    labels = [node.label for node in fig.nodes if node.label]
    labels += [group.label for group in fig.groups if group.label]
    return TextLayout(FontMetrics.for_text(fig.theme.font_family, '\n'.join(labels)))


def ensure_not_ir(target: Path, ir_path: Path) -> None:
    """Rendered output must never overwrite the single source of truth."""
    if target.exists() and target.resolve() == ir_path.resolve():
        raise RenderError(
            f"refusing to write rendered output over the IR file {ir_path}; "
            f"choose another --out"
        )


def create_figure(
    ctx: ServiceContext,
    path_str: str,
    figure_id: str,
    *,
    width: float = 182.0,
    height: float = 58.0,
    margin: float = 4.0,
) -> dict:
    from papercanvas.core.models import Canvas

    target = ctx.resolve(path_str)
    figure = Figure(id=figure_id, canvas=Canvas(width=width, height=height, margin=margin))
    doc = FigureDocument.create(target, figure)
    return {
        "ok": True,
        "path": str(doc.path),
        "figure_id": figure.id,
        "revision": figure.revision,
    }


def get_figure(ctx: ServiceContext, path_str: str) -> dict:
    """Full figure dump. Lenient load: broken figures still come back, with
    ``hard_errors`` describing what validation would reject."""
    target = ctx.resolve(path_str)
    doc = FigureDocument.load(target, lenient=True)
    fig = doc.figure
    dump = fig.model_dump(mode="json")
    return {
        "ok": True,
        "path": str(target),
        "figure_id": fig.id,
        "revision": fig.revision,
        "schema_version": fig.schema_version,
        "canvas": dump["canvas"],
        "theme": dump["theme"],
        "nodes": dump["nodes"],
        "edges": dump["edges"],
        "groups": dump["groups"],
        "hard_errors": validate_figure(fig),
    }


def patch_figure(
    ctx: ServiceContext,
    path_str: str,
    operations: list[dict],
    expected_revision: int | None = None,
) -> dict:
    target = ctx.resolve(path_str)
    doc = FigureDocument.load(target)
    result = apply_patch(
        doc,
        PatchRequest(operations=operations, expected_revision=expected_revision),
    )
    return {
        "ok": True,
        "path": str(doc.path),
        "revision": result.revision,
        "applied": result.applied,
    }


def layout_figure(ctx: ServiceContext, path_str: str, preset: str = "linear-h") -> dict:
    if preset not in LAYOUT_PRESETS:
        raise PaperCanvasError(
            f"unknown layout preset {preset!r}; supported: {list(LAYOUT_PRESETS)}"
        )
    target = ctx.resolve(path_str)
    doc = FigureDocument.load(target)
    base_revision = doc.figure.revision
    laid_out = run_layout(doc.figure, preset)
    laid_out.revision = base_revision + 1
    doc.save_figure(laid_out, expected_revision=base_revision)
    return {
        "ok": True,
        "path": str(target),
        "revision": laid_out.revision,
        "preset": preset,
        "canvas": laid_out.canvas.model_dump(mode="json"),
        "nodes_placed": sum(1 for node in laid_out.nodes if node.is_placed),
    }


def render_figure(
    ctx: ServiceContext, path_str: str, formats: list[str], out: str | None = None
) -> dict:
    for fmt in formats:
        if fmt not in RENDER_SUFFIXES:
            raise PaperCanvasError(
                f"unknown render format {fmt!r}; supported: {sorted(RENDER_SUFFIXES)}"
            )
    if len(formats) > 1 and out is not None:
        raise RenderError("--out with multiple formats is ambiguous; omit --out")
    ir_path = ctx.resolve(path_str)
    doc = FigureDocument.load(ir_path)
    layout = text_layout_for(doc.figure)
    files = []
    for fmt in formats:
        default = ir_path.with_suffix(RENDER_SUFFIXES[fmt])
        target = ctx.resolve(out) if (out is not None and len(formats) == 1) else default
        ensure_not_ir(target, ir_path)
        payload = {"svg": render_svg, "pdf": render_pdf, "pptx": render_pptx}[fmt](
            doc.figure, layout
        )
        atomic_write(target, payload)
        files.append({"path": str(target), "format": fmt, "bytes": len(payload)})
    return {"ok": True, "files": files, "revision": doc.figure.revision}


def lint_figure_file(
    ctx: ServiceContext, path_str: str, min_font_size_pt: float = 6.0
) -> dict:
    ir_path = ctx.resolve(path_str)
    doc = FigureDocument.load(ir_path, lenient=True)
    layout = text_layout_for(doc.figure)
    try:
        # FC008 scans rendered output; best-effort for unplaceable/broken
        # figures (FC002 reports the root cause instead).
        svg_bytes = render_svg(doc.figure, layout)
    except (RenderError, ValueError):
        svg_bytes = None
    findings = lint_figure(
        doc.figure,
        layout,
        config=LintConfig(min_font_size_pt=min_font_size_pt),
        svg_bytes=svg_bytes,
    )
    report = findings_to_json(findings)
    report["ok"] = True
    report["path"] = str(ir_path)
    return report


def inspect_figure(
    ctx: ServiceContext, path_str: str, object_id: str | None = None
) -> dict:
    ir_path = ctx.resolve(path_str)
    doc = FigureDocument.load(ir_path)
    fig = doc.figure
    summary = {
        "ok": True,
        "path": str(ir_path),
        "figure_id": fig.id,
        "revision": fig.revision,
        "canvas": fig.canvas.model_dump(mode="json"),
        "objects": [
            {"id": node.id, "kind": "node", "label": node.label, "placed": node.is_placed}
            for node in fig.nodes
        ]
        + [
            {"id": edge.id, "kind": "edge", "label": f"{edge.source}->{edge.target}"}
            for edge in fig.edges
        ]
        + [
            {"id": group.id, "kind": "group", "label": group.label}
            for group in fig.groups
        ],
    }
    if object_id is None:
        return summary

    node = fig.node(object_id)
    if node is not None:
        detail = node.model_dump(mode="json")
        detail.update(
            {
                "kind": "node",
                "connected_edges": [
                    edge.id
                    for edge in fig.edges
                    if edge.source == object_id or edge.target == object_id
                ],
                "member_of_groups": [
                    group.id for group in fig.groups if object_id in group.children
                ],
            }
        )
        return {"ok": True, "object": detail}
    edge = fig.edge(object_id)
    if edge is not None:
        detail = edge.model_dump(mode="json")
        detail["kind"] = "edge"
        return {"ok": True, "object": detail}
    group = fig.group(object_id)
    if group is not None:
        detail = group.model_dump(mode="json")
        detail["kind"] = "group"
        return {"ok": True, "object": detail}
    raise PaperCanvasError(
        f"no object with id {object_id!r} in figure {fig.id!r}; "
        f"known ids: {[item['id'] for item in summary['objects']]}"
    )
