"""DSpy agent that directly orchestrates MCP tools (no HTTP bridge required)."""
from __future__ import annotations

import asyncio
import contextlib
import io
import json
import keyword
import logging
import re
from typing import Any, Awaitable, Callable, Dict, Mapping, Sequence

try:
    import dspy
except ImportError:  # pragma: no cover - enforced during runtime
    dspy = None  # type: ignore

LOGGER = logging.getLogger(__name__)

from .executor import ExecutionResult
from .tool_bridge import MCPToolBridge, ToolBridgeSession

SandboxRunner = Callable[
    [str, float, Any | None, Mapping[str, Any] | None],
    Awaitable[ExecutionResult],
]

_TOOL_BRIDGE_TEMPLATE = """
import json
import urllib.error
import urllib.request

_MCP_INTERNAL_ENDPOINT = {endpoint!r}
_MCP_INTERNAL_TOKEN = {token!r}
_MCP_REQUEST_TIMEOUT = {timeout}

def _mcp_bridge_request(name, params):
    payload = json.dumps({{
        "token": _MCP_INTERNAL_TOKEN,
        "name": name,
        "params": params,
    }}).encode("utf-8")
    request = urllib.request.Request(
        _MCP_INTERNAL_ENDPOINT,
        data=payload,
        headers={{"Content-Type": "application/json"}},
    )
    try:
        with urllib.request.urlopen(request, timeout=_MCP_REQUEST_TIMEOUT) as response:
            raw = response.read().decode("utf-8") or "{{}}"
    except urllib.error.URLError as exc:
        raise RuntimeError(f"MCP tool bridge network error: {{exc}}") from exc
    data = json.loads(raw)
    if not data.get("success"):
        raise RuntimeError(data.get("error", "MCP tool call failed"))
    return data.get("result")

def call_mcp_tool(name: str, **params):
    return _mcp_bridge_request(name, params)

def list_mcp_tools():
    return {tools_json}

def _bind_mcp_tool(name: str):
    def _caller(**params):
        return call_mcp_tool(name, **params)
    return _caller

AVAILABLE_MCP_TOOLS = {{}}
{alias_lines}
""".strip()


class CodeGenerationSignature(dspy.Signature):  # type: ignore[misc]
    """Ask DSpy to reason about a task and call MCP tools directly."""

    task: str = dspy.InputField(desc="The end-user request or problem statement.")
    available_tools: str = dspy.InputField(
        desc="LLM-readable documentation for the currently connected MCP tools."
    )
    code: dspy.Code = dspy.OutputField(
        desc="Python helper code that DSpy executed internally while solving the task."
    )
    answer: str = dspy.OutputField(
        desc="Final response to return to the user after calling tools."
    )


class CodeExecutionAgent:
    """High-level agent that delegates orchestration to DSpy's CodeAct."""

    def __init__(
        self,
        mcp_tools: Sequence[Any],
        tool_context: str,
        sandbox_runner: SandboxRunner,
        tool_bridge: MCPToolBridge,
        max_iters: int = 3,
    ) -> None:
        if dspy is None:  # pragma: no cover - runtime guard
            raise RuntimeError("dspy-ai is not installed")

        self.mcp_tools = list(mcp_tools)
        self._tool_bridge = tool_bridge
        self.tool_names = [getattr(t, "name", str(t)) for t in self.mcp_tools]
        self._sandbox_runner = sandbox_runner
        self._tool_specs = self._build_tool_specs()
        self.tool_context = self._augment_tool_context(tool_context)
        self._sandbox_variables = self._build_sandbox_variables()

        generator_cls = getattr(dspy, "CodeAct", dspy.ProgramOfThought)
        try:
            self.generator = generator_cls(
                CodeGenerationSignature,
                tools=self.mcp_tools,
                max_iters=max_iters,
            )
        except (TypeError, ValueError):
            # Fallback for older CodeAct implementations that don't accept tools.
            self.generator = dspy.ProgramOfThought(
                CodeGenerationSignature,
                max_iters=max_iters,
            )

    async def run(self, task: str, timeout: int = 120, ctx: Any = None) -> Dict[str, Any]:
        """Execute the end-to-end tool reasoning flow inside DSpy."""

        LOGGER.info("Running agent for task: %s", task)
        LOGGER.debug("Available tools: %s", self.tool_names)

        stop_ticker = asyncio.Event()

        async def _ticker() -> None:
            seconds = 0
            while not stop_ticker.is_set():
                await asyncio.sleep(1)
                seconds += 1
                if ctx:
                    try:
                        await ctx.info(f"Agent reasoning... ({seconds}s)")
                        await ctx.report_progress(seconds % 10, 10)
                    except Exception:  # pragma: no cover - ctx not always available
                        pass

        ticker_task = asyncio.create_task(_ticker())

        try:
            result, captured_stdout, duration = await asyncio.to_thread(
                self._invoke_generator, task
            )
            if captured_stdout:
                LOGGER.debug("Captured DSpy stdout: %s", captured_stdout)
        finally:
            stop_ticker.set()
            with contextlib.suppress(Exception):
                await ticker_task

        generated_code = str(getattr(result, "code", ""))
        final_answer = str(getattr(result, "answer", "") or getattr(result, "text", ""))

        sandbox_result = await self._run_sandbox_execution(
            code=generated_code,
            timeout=timeout,
            ctx=ctx,
        )
        if final_answer:
            diagnostics = sandbox_result.get("diagnostics") or {}
            diagnostics["llm_answer"] = final_answer
            sandbox_result["diagnostics"] = diagnostics

        return {
            "task": task,
            "generated_code": generated_code,
            "execution_result": sandbox_result,
        }

    def _invoke_generator(self, task: str):
        """Call the (synchronous) DSpy generator with stdout redirection."""

        import time

        buffer = io.StringIO()
        start = time.perf_counter()

        with contextlib.redirect_stdout(buffer):
            result = self.generator(
                task=task,
                available_tools=self.tool_context,
            )

        elapsed = time.perf_counter() - start

        return result, buffer.getvalue(), elapsed

    async def _run_sandbox_execution(
        self,
        *,
        code: str,
        timeout: int,
        ctx: Any | None,
    ) -> ExecutionResult:
        session: ToolBridgeSession | None = None
        try:
            session = await self._tool_bridge.create_session(timeout=timeout)
            execution_code = self._prepare_execution_code(code, session, timeout)
            return await self._sandbox_runner(
                execution_code,
                timeout=timeout,
                ctx=ctx,
                variables=self._sandbox_variables,
            )
        except Exception as exc:  # pragma: no cover - fallback for diagnostics
            LOGGER.exception("Sandbox execution failed")
            return ExecutionResult(
                success=False,
                stdout="",
                stderr=str(exc),
                duration_ms=0,
                diagnostics={"error_type": exc.__class__.__name__},
            )
        finally:
            if session is not None:
                self._tool_bridge.invalidate_session(session["token"])

    def _build_sandbox_variables(self) -> Dict[str, Any]:
        return {
            "MCP_TOOL_CONTEXT": self.tool_context,
            "MCP_TOOL_NAMES": self.tool_names,
            "MCP_TOOLS": self._tool_specs,
        }

    def _build_tool_specs(self) -> list[Dict[str, Any]]:
        aliases_in_use: set[str] = set()
        specs: list[Dict[str, Any]] = []
        for tool in self.mcp_tools:
            spec = self._tool_spec(tool)
            alias = self._generate_alias(spec["name"], aliases_in_use)
            spec["alias"] = alias
            specs.append(spec)
        return specs

    def _tool_spec(self, tool: Any) -> Dict[str, Any]:
        schema = getattr(tool, "input_schema", None) or {}
        return {
            "name": getattr(tool, "name", "unknown_tool"),
            "description": self._normalize_description(getattr(tool, "description", "")),
            "schema": self._sanitize_schema(schema),
        }

    def _augment_tool_context(self, base: str) -> str:
        alias_lines = [
            f"- `{spec['alias']}(**kwargs)` maps to `{spec['name']}`"
            for spec in self._tool_specs
            if spec.get("alias")
        ]
        helper_sections = [
            "## MCP Tool Execution Helpers",
            "Use `call_mcp_tool(tool_name, **params)` to invoke MCP tools inside the sandbox.",
        ]
        if alias_lines:
            helper_sections.append("")
            helper_sections.append("### Shortcut Functions")
            helper_sections.extend(alias_lines)
        return f"{base}\n\n" + "\n".join(helper_sections)

    def _prepare_execution_code(
        self,
        code: str,
        session: ToolBridgeSession,
        timeout: int,
    ) -> str:
        prelude = self._build_bridge_prelude(session, timeout)

        # Some LLM runs return code wrapped in a string variable (e.g., `code = "def foo(): ..."`).
        # To make those runs still execute, add a small postlude that will exec stringified code if present.
        postlude = (
            "\n\n# Auto-execute stringified code if the model wrapped it in `code`\n"
            "if 'code' in locals() and isinstance(code, str):\n"
            "    exec(code, globals(), locals())\n"
        )

        return f"{prelude}\n\n{code}{postlude}"

    def _build_bridge_prelude(
        self,
        session: ToolBridgeSession,
        timeout: int,
    ) -> str:
        alias_lines = self._alias_registration_lines()
        tools_json = json.dumps(
            [
                {
                    "name": spec["name"],
                    "description": spec.get("description", ""),
                    "schema": spec.get("schema", {}),
                    "alias": spec.get("alias"),
                }
                for spec in self._tool_specs
            ]
        )
        return _TOOL_BRIDGE_TEMPLATE.format(
            endpoint=session["endpoint"],
            token=session["token"],
            timeout=max(5, timeout),
            tools_json=tools_json,
            alias_lines=alias_lines,
        )

    def _alias_registration_lines(self) -> str:
        lines: list[str] = []
        for spec in self._tool_specs:
            name = spec["name"]
            lines.append(f"AVAILABLE_MCP_TOOLS[{name!r}] = _bind_mcp_tool({name!r})")
            alias = spec.get("alias")
            if alias:
                lines.append(f"{alias} = AVAILABLE_MCP_TOOLS[{name!r}]  # alias for {name}")
        return "\n".join(lines)

    def _normalize_description(self, description: Any) -> str:
        if callable(description):
            try:
                description = description()
            except Exception:
                description = ""
        if isinstance(description, str):
            return description.strip()
        return ""

    def _sanitize_schema(self, schema: Any) -> Any:
        if not schema:
            return {}
        try:
            return json.loads(json.dumps(schema))
        except (TypeError, ValueError):
            return {}

    def _generate_alias(self, name: str, used: set[str]) -> str | None:
        candidate = re.sub(r"[^0-9a-zA-Z_]", "_", name)
        if not candidate:
            return None
        if candidate[0].isdigit():
            candidate = f"tool_{candidate}"
        candidate = candidate.lower()
        while candidate in used or keyword.iskeyword(candidate):
            candidate = f"{candidate}_tool"
        used.add(candidate)
        return candidate
