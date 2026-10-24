"""MCP server tests over the in-memory transport (real protocol round-trips).

Covers all seven tools plus the security posture: path escapes are rejected,
outputs stay inside the root, and domain failures come back as structured
``{"ok": false, "error": ...}`` results instead of protocol errors.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from mcp.client._memory import InMemoryTransport
from mcp.client.session import ClientSession

from papercanvas.integrations.mcp_server import build_server


@asynccontextmanager
async def _connected(root: Path):
    """One in-memory protocol session against a freshly built server."""
    async with InMemoryTransport(build_server(root), raise_exceptions=True) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


def call_tool(root: Path, tool: str, arguments: dict) -> dict:
    """Run one tool call over the real MCP protocol (synchronously)."""

    async def run() -> dict:
        async with _connected(root) as session:
            result = await session.call_tool(tool, arguments)
        if result.is_error:
            raise AssertionError(f"tool {tool} returned protocol error: {result.content}")
        if result.structured_content is not None:
            return result.structured_content
        return json.loads(result.content[0].text)

    return asyncio.run(run())


@pytest.fixture
def mcp(tmp_path: Path):
    class _Session:
        def call(self, tool: str, arguments: dict) -> dict:
            return call_tool(tmp_path, tool, arguments)

    return _Session()


def test_list_tools_exposes_the_seven_tools(tmp_path: Path) -> None:
    async def run() -> set[str]:
        async with _connected(tmp_path) as session:
            listing = await session.list_tools()
        return {tool.name for tool in listing.tools}

    names = asyncio.run(run())
    assert names == {
        "papercanvas_create",
        "papercanvas_get",
        "papercanvas_patch",
        "papercanvas_layout",
        "papercanvas_render",
        "papercanvas_lint",
        "papercanvas_inspect",
    }


def test_full_agent_flow_over_the_protocol(mcp, tmp_path: Path) -> None:
    created = mcp.call(
        "papercanvas_create", {"path": "fig.json", "figure_id": "demo"}
    )
    assert created["ok"] and created["revision"] == 1

    patched = mcp.call(
        "papercanvas_patch",
        {
            "path": "fig.json",
            "operations": [
                {"op": "add_node", "node": {"id": "a", "label": "Alpha"}},
                {"op": "add_node", "node": {"id": "b", "label": "Beta"}},
                {"op": "add_edge", "edge": {"id": "e1", "source": "a", "target": "b"}},
            ],
            "expected_revision": 1,
        },
    )
    assert patched["ok"] and patched["revision"] == 2

    laid = mcp.call("papercanvas_layout", {"path": "fig.json", "preset": "linear-h"})
    assert laid["ok"] and laid["revision"] == 3 and laid["nodes_placed"] == 2

    rendered = mcp.call(
        "papercanvas_render",
        {"path": "fig.json", "formats": ["svg", "pdf", "pptx"]},
    )
    assert rendered["ok"]
    assert [f["format"] for f in rendered["files"]] == ["svg", "pdf", "pptx"]
    for file_info in rendered["files"]:
        assert (tmp_path / Path(file_info["path"]).name).exists()

    linted = mcp.call("papercanvas_lint", {"path": "fig.json"})
    assert linted["ok"] and linted["summary"]["errors"] == 0

    inspected = mcp.call("papercanvas_inspect", {"path": "fig.json", "object_id": "a"})
    assert inspected["object"]["kind"] == "node"
    assert inspected["object"]["connected_edges"] == ["e1"]

    got = mcp.call("papercanvas_get", {"path": "fig.json"})
    assert got["figure_id"] == "demo" and got["revision"] == 3
    assert got["hard_errors"] == []


def test_path_escape_is_rejected(mcp, tmp_path: Path) -> None:
    """Security: nothing may be created or read outside the project root."""
    created = mcp.call(
        "papercanvas_create", {"path": "../evil.json", "figure_id": "escape"}
    )
    assert created["ok"] is False
    assert "escapes the project root" in created["error"]
    assert not (tmp_path.parent / "evil.json").exists()

    absolute = mcp.call(
        "papercanvas_create",
        {"path": str(tmp_path.parent / "evil_abs.json"), "figure_id": "escape"},
    )
    assert absolute["ok"] is False
    assert not (tmp_path.parent / "evil_abs.json").exists()

    read = mcp.call("papercanvas_get", {"path": ".."})
    assert read["ok"] is False


def test_domain_errors_are_structured_not_protocol_errors(mcp) -> None:
    created = mcp.call(
        "papercanvas_create", {"path": "fig.json", "figure_id": "demo"}
    )
    assert created["ok"]

    conflict = mcp.call(
        "papercanvas_patch",
        {
            "path": "fig.json",
            "operations": [{"op": "move_node", "id": "a", "x": 0, "y": 0}],
            "expected_revision": 99,
        },
    )
    assert conflict["ok"] is False
    assert "expected_revision" in conflict["error"]

    unknown_preset = mcp.call(
        "papercanvas_layout", {"path": "fig.json", "preset": "quantum"}
    )
    assert unknown_preset["ok"] is False and "preset" in unknown_preset["error"]

    missing = mcp.call("papercanvas_render", {"path": "nope.json"})
    assert missing["ok"] is False

    bad_object = mcp.call(
        "papercanvas_inspect", {"path": "fig.json", "object_id": "ghost"}
    )
    assert bad_object["ok"] is False and "ghost" in bad_object["error"]


def test_lint_surfaces_fc_findings_over_protocol(mcp, tmp_path: Path) -> None:
    mcp.call("papercanvas_create", {"path": "fig.json", "figure_id": "linty"})
    # a dangling edge: schema-valid, hard-invalid -> FC002 over the protocol
    result = mcp.call(
        "papercanvas_patch",
        {
            "path": "fig.json",
            "operations": [
                {"op": "add_node", "node": {"id": "a", "x": 5, "y": 5, "w": 10, "h": 8}},
                {"op": "add_edge", "edge": {"id": "e1", "source": "a", "target": "ghost"}},
            ],
        },
    )
    assert result["ok"] is False  # hard validation blocks the patch itself

    # construct the broken figure via API-equivalent patch that passes, then
    # break it on disk the way a confused agent would
    ir = tmp_path / "fig.json"
    payload = json.loads(ir.read_text(encoding="utf-8"))
    payload["edges"].append({"id": "e_bad", "source": "a", "target": "ghost"})
    ir.write_text(json.dumps(payload), encoding="utf-8")

    linted = mcp.call("papercanvas_lint", {"path": "fig.json"})
    assert linted["ok"]
    assert any(f["rule_id"] == "FC002" for f in linted["findings"])
    assert linted["summary"]["errors"] >= 1


def test_render_output_stays_inside_root(mcp, tmp_path: Path) -> None:
    mcp.call("papercanvas_create", {"path": "fig.json", "figure_id": "scoped"})
    mcp.call(
        "papercanvas_patch",
        {
            "path": "fig.json",
            "operations": [
                {
                    "op": "add_node",
                    "node": {"id": "a", "label": "A", "x": 5, "y": 5, "w": 20, "h": 10},
                }
            ],
        },
    )
    rendered = mcp.call(
        "papercanvas_render", {"path": "fig.json", "formats": ["svg", "pdf", "pptx"]}
    )
    assert rendered["ok"]
    for file_info in rendered["files"]:
        resolved = Path(file_info["path"]).resolve()
        assert resolved.is_relative_to(tmp_path.resolve())
