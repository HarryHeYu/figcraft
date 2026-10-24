"""PaperCanvas command line interface (Typer + Rich)."""

from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Optional

import typer
from pydantic import ValidationError as PydanticValidationError
from rich.console import Console

from papercanvas import __version__
from papercanvas.core.document import FigureDocument, atomic_write
from papercanvas.core.errors import (
    FigureValidationError,
    PaperCanvasError,
    PatchError,
    RenderError,
)
from papercanvas.core.models import Canvas, Figure
from papercanvas.core.patch import PatchRequest, apply_patch
from papercanvas.layout import run_layout
from papercanvas.lint import LintConfig, findings_to_json, lint_figure
from papercanvas.render import RENDER_SUFFIXES, render_pdf, render_pptx, render_svg
from papercanvas.text.text_layout import TextLayout
from papercanvas.text.text_metrics import FontMetrics

app = typer.Typer(
    name="papercanvas",
    help="Agent-native scientific figure studio: Figures as Code.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()
err_console = Console(stderr=True)

EXIT_OK = 0
EXIT_ERROR = 1


class LayoutPreset(StrEnum):
    linear_h = "linear-h"
    linear_v = "linear-v"
    layered = "layered"


class RenderFormat(StrEnum):
    svg = "svg"
    pdf = "pdf"
    pptx = "pptx"
    all = "all"


class LintOutputFormat(StrEnum):
    text = "text"
    json = "json"


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"papercanvas {__version__}")
        raise typer.Exit(EXIT_OK)


@app.callback()
def _root(
    version: Annotated[
        bool | None,
        typer.Option(
            "--version",
            callback=_version_callback,
            is_eager=True,
            help="Show the version and exit.",
        ),
    ] = None,
) -> None:
    """Agent-native scientific figure studio: Figures as Code."""


def _fail(exc: Exception) -> None:
    err_console.print(f"[red]error:[/red] {exc}")
    raise typer.Exit(EXIT_ERROR) from exc


@app.command()
def init(
    path: Annotated[Path, typer.Argument(help="Path of the new figure IR (.json).")],
    figure_id: Annotated[str, typer.Option("--id", help="Figure id.")],
    width: Annotated[float, typer.Option(help="Canvas width in mm.")] = 182.0,
    height: Annotated[float, typer.Option(help="Canvas height in mm.")] = 58.0,
    margin: Annotated[float, typer.Option(help="Canvas margin in mm.")] = 4.0,
) -> None:
    """Create a new, empty figure IR file (nodes/edges added via patch or layout)."""
    try:
        figure = Figure(
            id=figure_id,
            canvas=Canvas(width=width, height=height, margin=margin),
        )
        doc = FigureDocument.create(path, figure)
    except (PaperCanvasError, OSError, PydanticValidationError) as exc:
        _fail(exc)
        return
    console.print(
        f"[green]created[/green] {doc.path} "
        f"(figure {figure.id!r}, revision {figure.revision})"
    )
    console.print("Next: papercanvas patch / layout / render")


@app.command()
def validate(
    path: Annotated[Path, typer.Argument(help="Figure IR file to check.")]
) -> None:
    """Load and hard-validate a figure file (strictly read-only)."""
    try:
        doc = FigureDocument.load(path)
    except FigureValidationError as exc:
        for message in exc.errors:
            err_console.print(f"[red]invalid:[/red] {message}")
        raise typer.Exit(EXIT_ERROR) from exc
    except (PaperCanvasError, OSError) as exc:
        _fail(exc)
        return
    fig = doc.figure
    console.print(
        f"[green]valid[/green] {path} — figure {fig.id!r}, revision {fig.revision}, "
        f"{len(fig.nodes)} nodes, {len(fig.edges)} edges, {len(fig.groups)} groups"
    )


@app.command()
def patch(
    path: Annotated[Path, typer.Argument(help="Figure IR file to modify.")],
    ops: Annotated[
        Path,
        typer.Option(
            "--ops",
            help=(
                "JSON file with {\"operations\": [...], \"expected_revision\": N}. "
                "Pass - to read from stdin."
            ),
        ),
    ],
) -> None:
    """Apply a semantic patch batch as one transaction (all-or-nothing)."""
    try:
        raw = ops.read_text(encoding="utf-8") if str(ops) != "-" else _read_stdin()
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise PatchError("ops payload must be a JSON object")
        if "operations" not in payload:
            raise PatchError("ops payload needs an 'operations' list")
        request = PatchRequest(
            operations=payload["operations"],
            expected_revision=payload.get("expected_revision"),
        )
        doc = FigureDocument.load(path)
        result = apply_patch(doc, request)
    except (PaperCanvasError, OSError, json.JSONDecodeError, RecursionError) as exc:
        _fail(exc)
        return
    console.print(f"[green]patched[/green] {path} -> revision {result.revision}")
    for line in result.applied:
        console.print(f"  • {line}")


def _read_stdin() -> str:
    import sys

    return sys.stdin.read()


@app.command()
def layout(
    path: Annotated[Path, typer.Argument(help="Figure IR file to lay out.")],
    preset: Annotated[LayoutPreset, typer.Option(help="Layout preset.")] = LayoutPreset.linear_h,
) -> None:
    """Arrange nodes and rewrite their coordinates (commits revision+1)."""
    try:
        doc = FigureDocument.load(path)
        base_revision = doc.figure.revision
        laid_out = run_layout(doc.figure, preset.value)
        laid_out.revision = base_revision + 1
        doc.save_figure(laid_out, expected_revision=base_revision)
    except (PaperCanvasError, OSError) as exc:
        _fail(exc)
        return
    canvas = laid_out.canvas
    console.print(
        f"[green]laid out[/green] {path} ({preset.value}) -> revision "
        f"{laid_out.revision}, canvas {canvas.width:g}×{canvas.height:g} mm"
    )


def _ensure_not_ir(target: Path, ir_path: Path) -> None:
    """Render output must never overwrite the single source of truth."""
    if target.exists() and target.resolve() == ir_path.resolve():
        raise RenderError(
            f"refusing to write rendered output over the IR file {ir_path}; "
            f"choose another --out"
        )


def _render_bytes(figure, text_layout, fmt: str) -> bytes:
    if fmt == "svg":
        return render_svg(figure, text_layout)
    if fmt == "pdf":
        return render_pdf(figure, text_layout)
    if fmt == "pptx":
        return render_pptx(figure, text_layout)
    raise RenderError(f"unknown render format {fmt!r}")  # pragma: no cover


def _render_formats(
    figure, text_layout, formats: list[str], path: Path, out: Path | None
) -> list[Path]:
    """Render to each requested format; returns the written targets."""
    if len(formats) > 1 and out is not None:
        raise RenderError("--out with multiple formats is ambiguous; omit --out")
    targets = []
    for fmt in formats:
        default = path.with_suffix(RENDER_SUFFIXES[fmt])
        target = out if (out is not None and len(formats) == 1) else default
        _ensure_not_ir(target, path)
        atomic_write(target, _render_bytes(figure, text_layout, fmt))
        targets.append(target)
    return targets


@app.command()
def render(
    path: Annotated[Path, typer.Argument(help="Laid-out figure IR file.")],
    format: Annotated[
        RenderFormat,
        typer.Option("--format", help="Output format(s)."),
    ] = RenderFormat.svg,
    out: Annotated[
        Optional[Path],  # noqa: UP045 - typer handles Optional fine
        typer.Option("--out", help="Output file for a single format (default: alongside the IR)."),
    ] = None,
) -> None:
    """Render the figure (strictly read-only on the IR)."""
    formats = ["svg", "pdf", "pptx"] if format == RenderFormat.all else [format.value]
    try:
        doc = FigureDocument.load(path)
        text_layout = TextLayout(FontMetrics.for_family(doc.figure.theme.font_family))
        targets = _render_formats(doc.figure, text_layout, formats, path, out)
    except (PaperCanvasError, OSError) as exc:
        _fail(exc)
        return
    for target in targets:
        console.print(f"[green]rendered[/green] {target} ({target.stat().st_size} bytes)")


@app.command()
def build(
    path: Annotated[Path, typer.Argument(help="Figure IR file.")],
    preset: Annotated[LayoutPreset, typer.Option(help="Layout preset.")] = LayoutPreset.linear_h,
    format: Annotated[
        RenderFormat,
        typer.Option("--format", help="Output format(s)."),
    ] = RenderFormat.svg,
    out: Annotated[
        Optional[Path],  # noqa: UP045
        typer.Option("--out", help="Output file for a single format (default: alongside the IR)."),
    ] = None,
) -> None:
    """One command: layout (commits revision+1) then render."""
    try:
        doc = FigureDocument.load(path)
        base_revision = doc.figure.revision
        laid_out = run_layout(doc.figure, preset.value)
        laid_out.revision = base_revision + 1
        doc.save_figure(laid_out, expected_revision=base_revision)
        text_layout = TextLayout(FontMetrics.for_family(laid_out.theme.font_family))
        formats = ["svg", "pdf", "pptx"] if format == RenderFormat.all else [format.value]
        targets = _render_formats(laid_out, text_layout, formats, path, out)
    except (PaperCanvasError, OSError) as exc:
        _fail(exc)
        return
    canvas = laid_out.canvas
    rendered = ", ".join(str(target) for target in targets)
    console.print(
        f"[green]built[/green] {rendered} — preset {preset.value}, revision "
        f"{laid_out.revision}, canvas {canvas.width:g}×{canvas.height:g} mm"
    )


@app.command()
def lint(
    path: Annotated[Path, typer.Argument(help="Figure IR file to inspect.")],
    min_font_size: Annotated[
        float, typer.Option(help="FC005 threshold: minimum acceptable font size (pt).")
    ] = 6.0,
    output_format: Annotated[
        LintOutputFormat, typer.Option("--format", help="Human-readable or JSON output.")
    ] = LintOutputFormat.text,
) -> None:
    """Check figure quality (FC001–FC008) — strictly read-only.

    Exit code 1 means at least one Error-severity finding; warnings alone
    still exit 0.
    """
    try:
        # lenient load: lint is the diagnostic entry point for structurally
        # broken figures (FC002 reports what hard validation would reject)
        doc = FigureDocument.load(path, lenient=True)
        text_layout = TextLayout(FontMetrics.for_family(doc.figure.theme.font_family))
        try:
            # FC008 inspects rendered output; rendering to memory is
            # read-only. Best-effort: unplaced figures or hard-invalid
            # colors skip the scan (FC002 reports the root cause instead).
            svg_bytes = _render_bytes(doc.figure, text_layout, "svg")
        except (RenderError, ValueError):
            svg_bytes = None
        findings = lint_figure(
            doc.figure,
            text_layout,
            config=LintConfig(min_font_size_pt=min_font_size),
            svg_bytes=svg_bytes,
        )
    except (PaperCanvasError, OSError) as exc:
        _fail(exc)
        return

    if output_format == LintOutputFormat.json:
        typer.echo(json.dumps(findings_to_json(findings), ensure_ascii=False, indent=2))
    else:
        report = findings_to_json(findings)
        for finding in findings:
            color = "red" if finding.severity == "error" else "yellow"
            scope = f" [{finding.object_id}]" if finding.object_id else ""
            console.print(
                f"[{color}]{finding.rule_id}[/] {finding.severity}{scope}: {finding.message}"
            )
        if not findings:
            console.print("[green]clean[/green] — no findings")
        console.print(
            f"{report['summary']['errors']} error(s), {report['summary']['warnings']} warning(s)"
        )

    if any(finding.severity == "error" for finding in findings):
        raise typer.Exit(EXIT_ERROR)


def main() -> None:
    app()
