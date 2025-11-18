"""FastMCP server that exposes the Phase 1 `execute_code` tool."""
from __future__ import annotations

import logging
from typing import Any

from fastmcp import Context, FastMCP

from .executor import ExecutionResult, SandboxOptions, SandboxedPythonExecutor

LOGGER = logging.getLogger(__name__)

# Default sandbox forbids network/env/filesystem access for Phase 1.
EXECUTOR = SandboxedPythonExecutor(
    options=SandboxOptions(
        enable_network_access=False,
        enable_env_vars=False,
        enable_read_paths=(),
        enable_write_paths=(),
        max_output_chars=64_000,
    )
)

mcp = FastMCP("Code Executor Server")
DEFAULT_TIMEOUT = 30


@mcp.tool()
async def execute_code(
    code: str,
    timeout: int = DEFAULT_TIMEOUT,
    ctx: Context | None = None,
) -> ExecutionResult:
    """Execute Python code inside DSpy's sandboxed interpreter."""

    try:
        numeric_timeout = _coerce_timeout(timeout)
    except ValueError as exc:
        return ExecutionResult(
            success=False,
            stdout="",
            stderr=str(exc),
            duration_ms=0,
            diagnostics={"error_type": "INVALID_ARGUMENT"},
        )

    if ctx is not None:
        await ctx.info(
            f"Executing snippet ({len(code)} chars, timeout={numeric_timeout}s)"
        )

    result = await EXECUTOR.run(code, timeout=numeric_timeout)

    if ctx is not None and not result.get("success", False):
        diagnostics = result.get("diagnostics") or {}
        await ctx.error(
            f"Execution failed: {diagnostics.get('error_type', 'Unknown error')}"
        )

    return result


def _coerce_timeout(raw: Any) -> float:
    """Convert timeout values from MCP clients into a float."""

    try:
        timeout = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("timeout must be numeric") from exc

    if timeout <= 0:
        raise ValueError("timeout must be greater than zero seconds")
    return timeout


def main() -> None:
    """CLI entry point for running the executor server."""

    logging.basicConfig(level=logging.INFO)
    LOGGER.info("Starting Code Executor Server (Phase 1)")
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
