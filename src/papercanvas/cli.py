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
from papercanvas.render import render_svg
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
            f"refusing to write SVG over the IR file {ir_path}; choose another --out"
        )


@app.command()
def render(
    path: Annotated[Path, typer.Argument(help="Laid-out figure IR file.")],
    out: Annotated[
        Optional[Path],  # noqa: UP045 - typer handles Optional fine
        typer.Option("--out", help="Output file (default: alongside the IR, .svg)."),
    ] = None,
) -> None:
    """Render the figure to SVG (strictly read-only on the IR)."""
    target = out or path.with_suffix(".svg")
    try:
        doc = FigureDocument.load(path)
        text_layout = TextLayout(FontMetrics.for_family(doc.figure.theme.font_family))
        svg_bytes = render_svg(doc.figure, text_layout)
        _ensure_not_ir(target, path)
        # temp + os.replace: even a hardlink alias that slips past the guard
        # would only re-point this directory entry, never the IR inode
        atomic_write(target, svg_bytes)
    except (PaperCanvasError, OSError) as exc:
        _fail(exc)
        return
    console.print(f"[green]rendered[/green] {target} ({len(svg_bytes)} bytes)")


@app.command()
def build(
    path: Annotated[Path, typer.Argument(help="Figure IR file.")],
    preset: Annotated[LayoutPreset, typer.Option(help="Layout preset.")] = LayoutPreset.linear_h,
    out: Annotated[
        Optional[Path],  # noqa: UP045
        typer.Option("--out", help="Output file (default: alongside the IR, .svg)."),
    ] = None,
) -> None:
    """One command: layout (commits revision+1) then render to SVG."""
    try:
        doc = FigureDocument.load(path)
        base_revision = doc.figure.revision
        laid_out = run_layout(doc.figure, preset.value)
        laid_out.revision = base_revision + 1
        doc.save_figure(laid_out, expected_revision=base_revision)
    except (PaperCanvasError, OSError) as exc:
        _fail(exc)
        return

    target = out or path.with_suffix(".svg")
    try:
        text_layout = TextLayout(FontMetrics.for_family(laid_out.theme.font_family))
        svg_bytes = render_svg(laid_out, text_layout)
        _ensure_not_ir(target, path)
        atomic_write(target, svg_bytes)
    except (PaperCanvasError, OSError) as exc:
        _fail(exc)
        return
    canvas = laid_out.canvas
    console.print(
        f"[green]built[/green] {target} — preset {preset.value}, revision "
        f"{laid_out.revision}, canvas {canvas.width:g}×{canvas.height:g} mm, "
        f"{len(svg_bytes)} bytes"
    )


def main() -> None:
    app()
