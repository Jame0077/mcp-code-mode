"""DSpy agent for generating and executing code using MCP tools."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence

try:
    import dspy
except ImportError:
    dspy = None  # type: ignore

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
        self.tool_names = [getattr(t, "name", str(t)) for t in self.mcp_tools]

        # Create code generator with tool-aware signature
        # We use ProgramOfThought to allow for reasoning before code generation
        self.generator = dspy.ProgramOfThought(
            CodeGenerationSignature,
            max_iters=max_iters,
        )

    async def run(self, task: str) -> Dict[str, Any]:
        """Generate and execute code for a task.

        Args:
            task: The user's natural language request.

        Returns:
            A dictionary containing the task, generated code, and execution result.
        """
        LOGGER.info("Running agent for task: %s", task)
        LOGGER.debug("Available tools: %s", self.tool_names)

        # Generate code - tool_context tells LLM what tools exist
        # ProgramOfThought.acall returns a Prediction object
        # Note: dspy.ProgramOfThought might not support async acall in all versions, so we use sync call
        result = self.generator(
            task=task,
            available_tools=self.tool_context,
        )

        generated_code = result.code
        LOGGER.info("Generated code:\n%s", generated_code)

        # Execute code with access to MCP tools
        execution_result = await self._execute_with_tools(generated_code)

        return {
            "task": task,
            "generated_code": generated_code,
            "execution_result": execution_result,
        }

    def _generate_tool_shims(self) -> str:
        """Generate Python shims for MCP tools to be injected into the sandbox.

        Since the sandbox is isolated, we need to provide implementations for the
        tools that the agent expects to be available.
        
        For Phase 3, we implement shims for common filesystem operations that
        map to standard Python file I/O, which Pyodide/Deno supports (within
        allowed paths).
        """
        shims = []
        
        # Helper for read_file
        if "read_file" in self.tool_names:
            shims.append('''
def read_file(path):
    """Read the contents of a file."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"Error reading file: {e}"
''')

        # Helper for write_file
        if "write_file" in self.tool_names:
            shims.append('''
def write_file(path, content):
    """Write content to a file."""
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Successfully wrote to {path}"
    except Exception as e:
        return f"Error writing file: {e}"
''')

        # Helper for list_directory (optional but good to have)
        if "list_directory" in self.tool_names:
            shims.append('''
import os
def list_directory(path):
    """List files in a directory."""
    try:
        return os.listdir(path)
    except Exception as e:
        return f"Error listing directory: {e}"
''')

        return "\n".join(shims)

    async def _execute_with_tools(self, code: str) -> Dict[str, Any]:
        """Execute generated code with MCP tools available.

        This uses the Phase 1 SandboxedPythonExecutor to run the code.
        """
        # Validate code first
        is_valid, message = self.validate_code(code)
        if not is_valid:
            return {
                "success": False,
                "stdout": "",
                "stderr": f"Validation failed: {message}",
                "duration_ms": 0,
            }

        # Initialize executor with default options for now
        from .executor import SandboxedPythonExecutor, SandboxOptions

        # Inject tool shims
        tool_header = self._generate_tool_shims()
        full_code = f"{tool_header}\n\n# Generated Code\n{code}"

        options = SandboxOptions(
            enable_network_access=True,  # Enable network for fetch tools
            enable_env_vars=True,       # Enable env vars if needed
            # We might need to mount paths for filesystem tools
            enable_read_paths=["/tmp"],
            enable_write_paths=["/tmp"],
        )
        executor = SandboxedPythonExecutor(options=options)

        # Execute
        try:
            result = await executor.run(full_code)
            return result
        except Exception as e:
            return {
                "success": False,
                "stdout": "",
                "stderr": f"Execution error: {str(e)}",
                "duration_ms": 0,
            }

    def validate_code(self, code: str) -> tuple[bool, str]:
        """Validate generated code before execution."""
        # Check if code uses any available tools
        # This is a heuristic; a proper parser would be better but this suffices for now.
        uses_tools = any(name in code for name in self.tool_names)

        # Check if code prints result (common requirement for PoT/CodeAct to see output)
        has_output = "print" in code

        if not uses_tools:
            # It's possible the task doesn't need tools, but for this agent's purpose,
            # we generally expect tool usage. We'll warn but maybe not fail strictly
            # if the prompt was just "calculate 1+1".
            # For the strict requirement of "using MCP tools", we'll enforce it.
            return False, "Code does not use any available MCP tools"

        if not has_output:
            return False, "Code does not print any output"

        return True, "Code validation passed"
