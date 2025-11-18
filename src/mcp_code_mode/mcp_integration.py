"""Phase 2 helpers for MCP tool discovery + formatting."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict

from .mcp_manager import MCPServerManager
from .tool_formatter import ToolSchemaFormatter

LOGGER = logging.getLogger(__name__)
__all__ = ["setup_mcp_tools", "main"]


async def setup_mcp_tools(
    manager: MCPServerManager | None = None,
) -> Dict[str, Any]:
    """Discover MCP tools and prepare metadata for downstream agents."""

    mgr = manager or MCPServerManager()
    tools = await mgr.initialize()
    formatter = ToolSchemaFormatter(tools)
    llm_context = formatter.format_for_llm()
    tool_names = formatter.get_tool_names()

    return {
        "manager": mgr,
        "tools": tools,
        "llm_context": llm_context,
        "tool_names": tool_names,
    }


async def _cli() -> None:
    """Simple CLI for manually inspecting discovered tools."""

    manager = MCPServerManager()
    try:
        setup = await setup_mcp_tools(manager)
        print("\n" + "=" * 60)
        print("MCP Tool Discovery Summary")
        print("=" * 60)
        print(manager.get_tools_summary())
        print("=" * 60)
        print(f"Total tools discovered: {len(setup['tools'])}")
        print(f"Tool names: {', '.join(setup['tool_names']) or 'None'}")
        print("=" * 60)
        print("LLM Context Preview:")
        print("=" * 60)
        print(setup["llm_context"])
    finally:
        await manager.shutdown()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_cli())


if __name__ == "__main__":
    main()
