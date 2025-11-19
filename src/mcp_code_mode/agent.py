"""DSpy agent for generating and executing code using MCP tools."""
from __future__ import annotations

import asyncio
import logging
import json
from typing import Any, Dict, List, Optional, Sequence

try:
    import dspy
except ImportError:
    dspy = None  # type: ignore

try:
    from aiohttp import web
except ImportError:
    web = None

LOGGER = logging.getLogger(__name__)


class CodeGenerationSignature(dspy.Signature):
    """Generate Python code to complete a task using available MCP tools."""

    task: str = dspy.InputField(desc="The user's task to complete")
    available_tools: str = dspy.InputField(
        desc="Detailed documentation of available MCP tools with parameters and examples"
    )
    code: dspy.Code = dspy.OutputField(
        desc="Python code that uses the available tools to complete the task"
    )


class _ToolBridge:
    """Temporary HTTP server to bridge sandbox calls to MCP tools."""

    def __init__(self, tools_map: Dict[str, Any]) -> None:
        self.tools_map = tools_map
        self.runner: Optional[web.AppRunner] = None
        self.site: Optional[web.TCPSite] = None
        self.port: Optional[int] = None

    async def handle_request(self, request: web.Request) -> web.Response:
        try:
            data = await request.json()
            name = data.get("name")
            kwargs = data.get("args", {})

            if name not in self.tools_map:
                return web.json_response(
                    {"error": f"Tool {name} not found"}, status=404
                )

            tool = self.tools_map[name]
            # Handle both sync and async tool wrappers
            # dspy.Tool wrappers might be callable directly
            result = tool(**kwargs)
            if asyncio.iscoroutine(result):
                result = await result

            return web.json_response({"result": result})
        except Exception as e:
            LOGGER.exception(f"Tool bridge error for {name}")
            return web.json_response({"error": str(e)}, status=500)

    async def start(self) -> str:
        if web is None:
            raise RuntimeError("aiohttp is required for tool bridge")

        app = web.Application()
        app.router.add_post("/tool", self.handle_request)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, "localhost", 0)
        await self.site.start()
        
        # Get the assigned port
        # Accessing socket directly to get the ephemeral port
        if self.site is None:
            raise RuntimeError("Server site not initialized")
        server = self.site._server
        if server is None:
            raise RuntimeError("Server not started")
        
        # aiohttp internal API access
        socket = server.sockets[0] # type: ignore
        self.port = socket.getsockname()[1]
        return f"http://localhost:{self.port}/tool"

    async def stop(self) -> None:
        if self.site:
            await self.site.stop()
        if self.runner:
            await self.runner.cleanup()


class CodeExecutionAgent:
    """Agent that generates and executes Python code using MCP tools."""

    def __init__(
        self,
        mcp_tools: Sequence[Any],
        tool_context: str,
        max_iters: int = 3,
    ) -> None:
        """Initialize agent with discovered MCP tools.

        Args:
            mcp_tools: List of DSpy-wrapped MCP tools.
            tool_context: Formatted tool documentation for the LLM.
            max_iters: Maximum number of retry iterations for code generation.
        """
        if dspy is None:
            raise RuntimeError("dspy-ai is not installed")

        self.mcp_tools = list(mcp_tools)
        self.tool_context = tool_context
        # Create a map for easier lookup by name
        self.tool_names = [getattr(t, "name", str(t)) for t in self.mcp_tools]
        self.tools_map = {name: tool for name, tool in zip(self.tool_names, self.mcp_tools)}

        # Create code generator with tool-aware signature
        self.generator = dspy.ProgramOfThought(
            CodeGenerationSignature,
            max_iters=max_iters,
        )

    async def run(self, task: str, timeout: int = 120) -> Dict[str, Any]:
        """Generate and execute code for a task.

        Args:
            task: The user's natural language request.
            timeout: Execution timeout in seconds.

        Returns:
            A dictionary containing the task, generated code, and execution result.
        """
        LOGGER.info("Running agent for task: %s", task)
        LOGGER.debug("Available tools: %s", self.tool_names)

        # Generate code
        result = self.generator(
            task=task,
            available_tools=self.tool_context,
        )

        generated_code = result.code
        LOGGER.info("Generated code:\n%s", generated_code)

        # Execute code with access to MCP tools
        execution_result = await self._execute_with_tools(generated_code, timeout=timeout)

        return {
            "task": task,
            "generated_code": generated_code,
            "execution_result": execution_result,
        }

    def _generate_tool_shims(self, bridge_url: str) -> str:
        """Generate Python shims that call back to the host via HTTP.

        This generates a set of functions that match the discovered tools,
        but implemented as HTTP calls to the ephemeral bridge server.
        """
        shims = [
            "import urllib.request",
            "import json",
            "import os",
            "",
            f'BRIDGE_URL = "{bridge_url}"',
            "",
            "def _call_tool(name, args):",
            "    '''Internal helper to call MCP tools via bridge.'''",
            "    try:",
            "        data = json.dumps({'name': name, 'args': args}).encode('utf-8')",
            "        req = urllib.request.Request(",
            "            BRIDGE_URL, ",
            "            data=data, ",
            "            headers={'Content-Type': 'application/json'}",
            "        )",
            "        with urllib.request.urlopen(req) as response:",
            "            if response.status >= 400:",
            "                return f'Error calling tool {name}: {response.status} {response.reason}'",
            "            result_data = json.loads(response.read().decode('utf-8'))",
            "            if 'error' in result_data:",
            "                return f'Error: {result_data[\"error\"]}'",
            "            return result_data['result']",
            "    except Exception as e:",
            "        return f'Error invoking tool {name}: {e}'",
            ""
        ]

        # Generate a shim function for each available tool
        for tool_name in self.tool_names:
            shims.append(f"def {tool_name}(**kwargs):")
            shims.append(f'    """Call the {tool_name} tool."""')
            shims.append(f'    return _call_tool("{tool_name}", kwargs)')
            shims.append("")

        return "\n".join(shims)

    async def _execute_with_tools(self, code: str, timeout: int = 120) -> Dict[str, Any]:
        """Execute generated code with MCP tools available."""
        # Validate code first
        is_valid, message = self.validate_code(code)
        if not is_valid:
            return {
                "success": False,
                "stdout": "",
                "stderr": f"Validation failed: {message}",
                "duration_ms": 0,
            }

        from .executor import SandboxedPythonExecutor, SandboxOptions

        # Start the tool bridge
        bridge = _ToolBridge(self.tools_map)
        bridge_url = ""
        try:
            bridge_url = await bridge.start()
            LOGGER.info(f"Tool bridge started at {bridge_url}")

            # Inject tool shims pointing to the bridge
            tool_header = self._generate_tool_shims(bridge_url)
            full_code = f"{tool_header}\n\n# Generated Code\n{code}"

            options = SandboxOptions(
                enable_network_access=True,  # Required for bridge
                enable_env_vars=True,
                # Mount /tmp for file tools if they still want local access
                enable_read_paths=["/tmp"],
                enable_write_paths=["/tmp"],
            )
            executor = SandboxedPythonExecutor(options=options)

            # Execute
            result = await executor.run(full_code, timeout=timeout)
            return result
            
        except Exception as e:
            LOGGER.exception("Execution failed")
            return {
                "success": False,
                "stdout": "",
                "stderr": f"Execution error: {str(e)}",
                "duration_ms": 0,
            }
        finally:
            await bridge.stop()

    def validate_code(self, code: str) -> tuple[bool, str]:
        """Validate generated code before execution."""
        # Check if code uses any available tools
        uses_tools = any(name in code for name in self.tool_names)
        has_output = "print" in code

        if not uses_tools:
            # We allow execution even without tools, but warn
            pass
            
        if not has_output:
            return False, "Code does not print any output"

        return True, "Code validation passed"
