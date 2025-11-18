"""Manual check that Phase 2 MCP tools can be called via DSpy wrappers."""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from mcp_code_mode.mcp_integration import setup_mcp_tools


async def call_tool(tool_name: str, **kwargs: Any) -> Any:
    """Invoke the requested tool with keyword arguments."""

    setup = await setup_mcp_tools()
    manager = setup["manager"]
    try:
        tool = _find_tool(setup["tools"], tool_name)
        if tool is None:
            raise SystemExit(f"Tool '{tool_name}' not found in discovered MCP tools.")
        print(f"Calling tool '{tool.name}' with args {kwargs}")
        result = await tool.acall(**kwargs)
        print("Tool result:")
        print(result)
        return result
    finally:
        await manager.shutdown()


def _find_tool(tools: list[Any], tool_name: str):
    """Locate a tool by case-insensitive name or substring."""

    lowered = tool_name.lower()
    for tool in tools:
        name = getattr(tool, "name", "")
        if lowered == name.lower() or lowered in name.lower():
            return tool
    return None


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Call an MCP tool via DSpy wrapper.")
    parser.add_argument(
        "tool",
        help="Exact or partial name of the tool to invoke (e.g. 'read_file')",
    )
    parser.add_argument(
        "--path",
        help="Optional file path argument for filesystem tools (default: /tmp/mcp_tool.txt)",
        default="/tmp/mcp_tool.txt",
    )
    return parser.parse_args()


async def main() -> None:
    args = _parse_args()
    path = Path(args.path)
    if not path.exists():
        path.write_text("Hello from MCP tool call script!", encoding="utf-8")
    await call_tool(args.tool, path=str(path))


if __name__ == "__main__":
    asyncio.run(main())
