"""papercanvas MCP server (stdio) — seven tools over the shared service layer.

Security posture:
- The server binds to ONE project root (``--root``, default: cwd). Every path
  argument must resolve inside that root and every output file is derived
  from in-root IR paths; escapes are rejected by :class:`ServiceContext`.
- Tools never raise domain errors at the protocol level: failures come back
  as ``{"ok": false, "error": ...}`` so coding agents get actionable
  messages instead of stack traces.
- Read-only tools (get/lint/inspect) load leniently where noted so they can
  diagnose broken figures; mutating tools always run full validation.

Run: ``uv run papercanvas-mcp --root path/to/project`` (console script) or
``python -m papercanvas.integrations.mcp_server``.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from mcp.server.mcpserver import MCPServer

from papercanvas import __version__
from papercanvas.core.errors import PaperCanvasError
from papercanvas.service import (
    ServiceContext,
    create_figure,
    get_figure,
    inspect_figure,
    layout_figure,
    lint_figure_file,
    patch_figure,
    render_figure,
)

INSTRUCTIONS = (
    "PaperCanvas draws scientific figures as code. Workflow: papercanvas_create "
    "-> papercanvas_patch (semantic operations, all-or-nothing) -> papercanvas_layout "
    "-> papercanvas_lint (fix FC00xx findings) -> papercanvas_render (svg/pdf/pptx). "
    "Use papercanvas_get/papercanvas_inspect to read state before patching. "
    "Never hand-edit the IR JSON; all changes go through patches. All paths must "
    "stay inside the configured project root."
)


def build_server(root: Path) -> MCPServer:
    ctx = ServiceContext(root=root, enforce_root=True)
    server = MCPServer(
        name="papercanvas",
        version=__version__,
        instructions=INSTRUCTIONS,
    )

    def guard(fn):
        """Return {"ok": false, "error": ...} instead of raising on domain
        errors — including missing files (OSError) and malformed payloads
        (ValueError/TypeError), so agents always get actionable messages."""

        def wrapped(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except (
                PaperCanvasError,
                OSError,
                ValueError,
                TypeError,
                RecursionError,
            ) as exc:
                return {"ok": False, "error": str(exc)}

        return wrapped

    @server.tool(
        name="papercanvas_create",
        description=(
            "Create a new figure IR file. Returns the path and initial revision."
        ),
    )
    def papercanvas_create(
        path: str,
        figure_id: str,
        width: float = 182.0,
        height: float = 58.0,
        margin: float = 4.0,
    ) -> dict:
        return guard(create_figure)(
            ctx, path, figure_id, width=width, height=height, margin=margin
        )

    @server.tool(
        name="papercanvas_get",
        description=(
            "Read the full figure IR (nodes, edges, groups, theme, canvas) plus "
            "hard_errors — the list of structural problems that block render/patch. "
            "Call this before patching."
        ),
    )
    def papercanvas_get(path: str) -> dict:
        return guard(get_figure)(ctx, path)

    @server.tool(
        name="papercanvas_patch",
        description=(
            "Apply a batch of semantic operations in ONE all-or-nothing transaction: "
            "add_node, remove_node (+remove_edges:true), update_node, set_style, "
            "add_edge, remove_edge, add_group, update_label, move_node. On success "
            "the revision increments by 1; on failure nothing changes. Pass "
            "expected_revision for optimistic concurrency."
        ),
    )
    def papercanvas_patch(
        path: str,
        operations: list[dict],
        expected_revision: int | None = None,
    ) -> dict:
        return guard(patch_figure)(ctx, path, operations, expected_revision)

    @server.tool(
        name="papercanvas_layout",
        description=(
            "Arrange nodes (preset: linear-h | linear-v | layered) and commit the "
            "coordinates to the IR; revision increments by 1. Cycles are hard errors."
        ),
    )
    def papercanvas_layout(path: str, preset: str = "linear-h") -> dict:
        return guard(layout_figure)(ctx, path, preset)

    @server.tool(
        name="papercanvas_render",
        description=(
            "Render the figure to svg / pdf / pptx (a list, e.g. ['svg','pdf','pptx']). "
            "Output files are written next to the IR and are true vector + editable. "
            "Strictly read-only on the IR."
        ),
    )
    def papercanvas_render(path: str, formats: list[str] | None = None) -> dict:
        return guard(render_figure)(ctx, path, formats or ["svg"])

    @server.tool(
        name="papercanvas_lint",
        description=(
            "Run quality checks FC001-FC008 (canvas bounds, structure, text overflow, "
            "overlap, font size, arrows through nodes, font substitution, raster "
            "images). Returns findings with rule_id/severity/object_id; severity "
            "'error' means fix before delivering. Read-only."
        ),
    )
    def papercanvas_lint(path: str, min_font_size_pt: float = 6.0) -> dict:
        return guard(lint_figure_file)(ctx, path, min_font_size_pt)

    @server.tool(
        name="papercanvas_inspect",
        description=(
            "Inventory of all objects (ids, kinds, labels), or full detail for one "
            "object_id (geometry, style, connected edges, groups). Read-only."
        ),
    )
    def papercanvas_inspect(path: str, object_id: str | None = None) -> dict:
        return guard(inspect_figure)(ctx, path, object_id)

    return server


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="papercanvas-mcp",
        description="PaperCanvas MCP server (stdio). All file access is confined "
        "to the project root.",
    )
    parser.add_argument(
        "--root",
        default=".",
        help="Project root directory; every tool path must resolve inside it "
        "(default: current directory)",
    )
    args = parser.parse_args()
    server = build_server(Path(args.root))
    server.run_stdio_async()


if __name__ == "__main__":
    main()
