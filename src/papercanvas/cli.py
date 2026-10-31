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
from papercanvas.core.document import FigureDocument
from papercanvas.core.errors import (
    FigureValidationError,
    PaperCanvasError,
)
from papercanvas.doctor import run_doctor
from papercanvas.service import (
    ServiceContext,
    create_figure,
    inspect_figure,
    layout_figure,
    lint_figure_file,
    patch_figure,
    render_figure,
)
from papercanvas.text.text_layout import TextLayout
from papercanvas.text.text_metrics import FontMetrics

#: the CLI is a local user tool: no root containment, any path is allowed
CLI_CONTEXT = ServiceContext(root=Path.cwd(), enforce_root=False)

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
    two_column = "two-column"
    single_column = "single-column"


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
        created = create_figure(
            CLI_CONTEXT, str(path), figure_id, width=width, height=height, margin=margin
        )
    except (PaperCanvasError, OSError, PydanticValidationError) as exc:
        _fail(exc)
        return
    console.print(
        f"[green]created[/green] {created['path']} "
        f"(figure {created['figure_id']!r}, revision {created['revision']})"
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
            raise ValueError("ops payload must be a JSON object")
        if "operations" not in payload:
            raise ValueError("ops payload needs an 'operations' list")
        result = patch_figure(
            CLI_CONTEXT,
            str(path),
            payload["operations"],
            expected_revision=payload.get("expected_revision"),
        )
        console.print(f"[green]patched[/green] {path} -> revision {result['revision']}")
        for line in result["applied"]:
            console.print(f"  • {line}")
    except (
        PaperCanvasError,
        OSError,
        json.JSONDecodeError,
        RecursionError,
        ValueError,
        TypeError,
    ) as exc:
        _fail(exc)
        return


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
        result = layout_figure(CLI_CONTEXT, str(path), preset.value)
    except (PaperCanvasError, OSError) as exc:
        _fail(exc)
        return
    canvas = result["canvas"]
    console.print(
        f"[green]laid out[/green] {path} ({preset.value}) -> revision "
        f"{result['revision']}, canvas {canvas['width']:g}×{canvas['height']:g} mm"
    )


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
        result = render_figure(CLI_CONTEXT, str(path), formats, out=str(out) if out else None)
    except (PaperCanvasError, OSError) as exc:
        _fail(exc)
        return
    for file_info in result["files"]:
        console.print(
            f"[green]rendered[/green] {file_info['path']} ({file_info['bytes']} bytes)"
        )
    for warning in result.get("warnings", ()):
        console.print(f"[yellow]warning:[/yellow] {warning}")


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
    formats = ["svg", "pdf", "pptx"] if format == RenderFormat.all else [format.value]
    try:
        layout_figure(CLI_CONTEXT, str(path), preset.value)
        result = render_figure(CLI_CONTEXT, str(path), formats, out=str(out) if out else None)
    except (PaperCanvasError, OSError) as exc:
        _fail(exc)
        return
    rendered = ", ".join(item["path"] for item in result["files"])
    console.print(
        f"[green]built[/green] {rendered} — preset {preset.value}, revision "
        f"{result['revision']}"
    )
    for warning in result.get("warnings", ()):
        console.print(f"[yellow]warning:[/yellow] {warning}")


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
        report = lint_figure_file(CLI_CONTEXT, str(path), min_font_size_pt=min_font_size)
    except (PaperCanvasError, OSError) as exc:
        _fail(exc)
        return
    if output_format == LintOutputFormat.json:
        payload = {k: v for k, v in report.items() if k not in ("ok", "path")}
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for finding in report["findings"]:
            color = "red" if finding["severity"] == "error" else "yellow"
            scope = f" [{finding['object_id']}]" if finding["object_id"] else ""
            console.print(
                f"[{color}]{finding['rule_id']}[/] {finding['severity']}{scope}: "
                f"{finding['message']}"
            )
        if not report["findings"]:
            console.print("[green]clean[/green] — no findings")
        console.print(
            f"{report['summary']['errors']} error(s), "
            f"{report['summary']['warnings']} warning(s)"
        )

    if report["summary"]["errors"]:
        raise typer.Exit(EXIT_ERROR)


@app.command()
def inspect(
    path: Annotated[Path, typer.Argument(help="Figure IR file to inspect.")],
    object_id: Annotated[
        str | None,
        typer.Argument(help="Optional object id for full detail."),
    ] = None,
    output_format: Annotated[
        LintOutputFormat, typer.Option("--format", help="Human-readable or JSON output.")
    ] = LintOutputFormat.text,
) -> None:
    """Show object inventory or one object's full detail (read-only)."""
    try:
        result = inspect_figure(CLI_CONTEXT, str(path), object_id)
    except (PaperCanvasError, OSError) as exc:
        _fail(exc)
        return

    if output_format == LintOutputFormat.json:
        typer.echo(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if object_id is not None:
        for key, value in result["object"].items():
            console.print(f"{key}: {value}")
        return
    console.print(
        f"figure {result['figure_id']!r} rev {result['revision']} — "
        f"{len(result['objects'])} object(s)"
    )
    for item in result["objects"]:
        console.print(f"  {item['kind']:>5}  {item['id']}  {item.get('label', '')}")


@app.command()
def doctor(
    path: Annotated[Path, typer.Argument(help="Figure IR file to diagnose.")],
    output_format: Annotated[
        LintOutputFormat, typer.Option("--format", help="Human-readable or JSON output.")
    ] = LintOutputFormat.text,
) -> None:
    """Aggregate quality diagnosis: validation, lint, font, renderability.

    Read-only. Exit code 1 when blocking findings exist."""
    try:
        doc = FigureDocument.load(path, lenient=True)
        labels = "\n".join(
            n.label for n in doc.figure.nodes if n.label
        ) + "\n" + "\n".join(g.label for g in doc.figure.groups if g.label)
        layout = TextLayout(FontMetrics.for_text(doc.figure.theme.font_family, labels))
        try:
            from papercanvas.render.svg import render_svg

            svg_bytes = render_svg(doc.figure, layout)
        except Exception:
            svg_bytes = None
        report = run_doctor(doc.figure, layout, svg_bytes=svg_bytes)
    except (PaperCanvasError, OSError) as exc:
        _fail(exc)
        return

    if output_format == LintOutputFormat.json:
        typer.echo(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    else:
        level_colors = {"blocking": "red", "advisory": "yellow", "environment": "cyan"}
        for f in report.findings:
            color = level_colors.get(f.level, "white")
            obj = f" [{f.object_id}]" if f.object_id else ""
            suggestion = ""
            if f.suggested_patch:
                suggestion = f"\n  suggested: {json.dumps(f.suggested_patch)}"
            console.print(
                f"[{color}]{f.rule_id}[/] [{f.level}]{obj}: {f.message}{suggestion}"
            )
        if not report.findings:
            console.print("[green]healthy[/green] — no findings")
        s = report.as_dict()["summary"]
        console.print(
            f"{s['blocking']} blocking, {s['advisory']} advisory, "
            f"{s['environment']} environment"
        )

    if report.blocking_count > 0:
        raise typer.Exit(EXIT_ERROR)


def main() -> None:
    app()
