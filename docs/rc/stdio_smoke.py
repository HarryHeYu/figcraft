"""RC smoke test: drive the INSTALLED papercanvas-mcp over real stdio.

Run with the release-candidate venv's interpreter against the installed
console script (no repository source on the path):

    /tmp/rc-venv/Scripts/python.exe docs/rc/stdio_smoke.py --root <dir>
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
from pathlib import Path

from mcp import StdioServerParameters, types
from mcp.client.session import ClientSession
from mcp.client.stdio import stdio_client


async def smoke(root: Path, executable: str) -> None:
    params = StdioServerParameters(command=executable, args=["--root", str(root)])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            print(f"server: {init.server_info.name} {init.server_info.version}")

            listing = await session.list_tools()
            names = sorted(tool.name for tool in listing.tools)
            print("tools:", names)
            assert names == [
                "papercanvas_create",
                "papercanvas_doctor",
                "papercanvas_get",
                "papercanvas_inspect",
                "papercanvas_layout",
                "papercanvas_lint",
                "papercanvas_patch",
                "papercanvas_render",
            ]

            def payload(result: types.CallToolResult) -> dict:
                assert not result.is_error, result.content
                if result.structured_content is not None:
                    return result.structured_content
                # some transports deliver the payload as JSON text content
                return json.loads(result.content[0].text)

            created = payload(
                await session.call_tool(
                    "papercanvas_create", {"path": "smoke.json", "figure_id": "stdio_smoke"}
                )
            )
            print("create:", created)

            patched = payload(
                await session.call_tool(
                    "papercanvas_patch",
                    {
                        "path": "smoke.json",
                        "operations": [
                            {
                                "op": "add_node",
                                "node": {"id": "a", "type": "rounded_rect", "label": "A"},
                            },
                            {
                                "op": "add_node",
                                "node": {"id": "b", "type": "rounded_rect", "label": "B"},
                            },
                            {"op": "add_edge", "edge": {"id": "e1", "source": "a", "target": "b"}},
                        ],
                    },
                )
            )
            print("patch:", patched)

            layout_args = {"path": "smoke.json"}
            print("layout:", payload(await session.call_tool("papercanvas_layout", layout_args)))
            rendered = payload(
                await session.call_tool(
                    "papercanvas_render", {"path": "smoke.json", "formats": ["svg", "pdf", "pptx"]}
                )
            )
            print("render:", rendered)
            for file_info in rendered["files"]:
                artifact = root / Path(file_info["path"]).name
                assert artifact.exists() and artifact.stat().st_size > 0

            linted = payload(await session.call_tool("papercanvas_lint", {"path": "smoke.json"}))
            print("lint:", linted["summary"])
            assert linted["summary"]["errors"] == 0

            # path-escape attempt must be rejected with a structured error
            escaped = payload(
                await session.call_tool(
                    "papercanvas_create", {"path": "../escape.json", "figure_id": "nope"}
                )
            )
            assert escaped["ok"] is False and "escapes the project root" in escaped["error"]
            print("path-escape rejected: OK")
    print("MCP stdio smoke: PASS")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument(
        "--executable",
        default=shutil.which("papercanvas-mcp"),
        help="papercanvas-mcp executable (default: look it up on PATH)",
    )
    args = parser.parse_args()
    if not args.executable:
        raise SystemExit("papercanvas-mcp not found on PATH; pass --executable")
    asyncio.run(smoke(Path(args.root).resolve(), args.executable))


if __name__ == "__main__":
    main()
