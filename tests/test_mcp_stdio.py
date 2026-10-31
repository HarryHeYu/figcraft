"""Real stdio regression test: the installed entry point must serve.

The in-memory protocol tests bypass ``main()``; this test spawns the actual
``python -m papercanvas.integrations.mcp_server`` subprocess and speaks MCP
over stdio, so a broken synchronous entry point (e.g. an un-awaited
``run_stdio_async`` coroutine) cannot ship again.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from mcp import StdioServerParameters
from mcp.client.session import ClientSession
from mcp.client.stdio import stdio_client

from papercanvas.integrations.mcp_server import build_server


def _server_params(tmp_path: Path) -> StdioServerParameters:
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "papercanvas.integrations.mcp_server", "--root", str(tmp_path)],
    )


def test_stdio_entry_point_serves_tools(tmp_path: Path) -> None:
    import asyncio

    async def run() -> set[str]:
        async with stdio_client(_server_params(tmp_path)) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                listing = await session.list_tools()
                created = await session.call_tool(
                    "papercanvas_create", {"path": "s.json", "figure_id": "stdio"}
                )
        assert created.is_error is False
        return {tool.name for tool in listing.tools}

    names = asyncio.run(run())
    assert names == {
        "papercanvas_create",
        "papercanvas_get",
        "papercanvas_inspect",
        "papercanvas_doctor",
        "papercanvas_lint",
        "papercanvas_layout",
        "papercanvas_patch",
        "papercanvas_render",
    }
    assert (tmp_path / "s.json").exists()


def test_build_server_registers_exactly_seven_tools(tmp_path: Path) -> None:
    server = build_server(tmp_path)
    tools = asyncio.run(server.list_tools())
    assert len(tools) == 8
