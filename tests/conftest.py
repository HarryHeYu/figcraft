"""Shared fixtures and a minimal valid Figure IR used across the test suite."""

from __future__ import annotations

import copy
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

MINIMAL_FIGURE: dict = {
    "schema_version": "0.1",
    "id": "fig_test",
    "revision": 1,
    "canvas": {"width": 100.0, "height": 60.0, "unit": "mm", "margin": 4.0},
    "theme": {
        "font_family": "Arial",
        "font_size_pt": 8.0,
        "palette": {"accent": "#3366CC"},
        "background": "#FFFFFF",
    },
    "nodes": [
        {
            "id": "a",
            "type": "rect",
            "label": "Alpha",
            "x": 10.0,
            "y": 20.0,
            "w": 30.0,
            "h": 15.0,
            "style": {"fill": "#E8F0FE", "stroke": "#4275C4"},
        },
        {
            "id": "b",
            "type": "rounded_rect",
            "label": "Beta",
            "x": 60.0,
            "y": 20.0,
            "w": 30.0,
            "h": 15.0,
            "style": {"fill": "accent"},
        },
    ],
    "edges": [
        {
            "id": "e1",
            "source": "a",
            "target": "b",
            "source_port": "right",
            "target_port": "left",
            "style": {"stroke": "#444444", "arrow": "end"},
        }
    ],
    "groups": [],
}


def faithful_family() -> str:
    """A family name this machine resolves WITHOUT substitution.

    Requesting "Arial" on a Linux runner correctly yields an FC007
    substitution warning (the font genuinely is not there), so tests that
    expect a lint-clean figure must ask for the locally faithful family.
    """
    from papercanvas.text.text_metrics import FontMetrics

    probe = FontMetrics.for_family("Arial")
    return probe.resolved_family if probe.substituted else probe.family


@pytest.fixture
def figure_dict() -> dict:
    """A deep copy of a minimal, valid Figure IR dict — mutate freely.

    The theme font is the locally faithful family so lint-related tests do
    not depend on which fonts a CI image happens to ship.
    """
    payload = copy.deepcopy(MINIMAL_FIGURE)
    payload["theme"]["font_family"] = faithful_family()
    return payload


# -- MCP protocol test helpers (shared by test_mcp and test_mcp_e2e) ---------


@asynccontextmanager
async def _connected_mcp_session(root):
    """One in-memory protocol session against a freshly built MCP server."""
    import asyncio  # noqa: F401  (anyio drives the transport)

    from mcp.client._memory import InMemoryTransport
    from mcp.client.session import ClientSession

    from papercanvas.integrations.mcp_server import build_server

    async with InMemoryTransport(build_server(root), raise_exceptions=True) as (
        read,
        write,
    ):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


def call_mcp_tool(root, tool: str, arguments: dict) -> dict:
    """Run one MCP tool call over the real protocol (synchronously)."""
    import asyncio
    import json as _json

    async def run() -> dict:
        async with _connected_mcp_session(root) as session:
            result = await session.call_tool(tool, arguments)
        if result.is_error:
            raise AssertionError(f"tool {tool} returned protocol error: {result.content}")
        if result.structured_content is not None:
            return result.structured_content
        return _json.loads(result.content[0].text)

    return asyncio.run(run())


@pytest.fixture
def connected_mcp():
    """The async context-manager factory backing :func:`call_mcp_tool`."""
    return _connected_mcp_session


@pytest.fixture
def mcp(tmp_path: Path):
    """Synchronous MCP caller bound to the test's tmp directory."""

    class _Caller:
        def call(self, tool: str, arguments: dict) -> dict:
            return call_mcp_tool(tmp_path, tool, arguments)

    return _Caller()
