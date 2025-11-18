"""Utilities for formatting MCP tool schemas for LLM consumption."""
from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Mapping, Sequence

if TYPE_CHECKING:  # pragma: no cover - typing only
    import dspy as dspy_module  # type: ignore

    ToolLike = dspy_module.Tool
else:  # Runtime fallback keeps the formatter usable without DSpy installed.
    ToolLike = Any


class ToolSchemaFormatter:
    """Format MCP tools into readable documentation blocks."""

    def __init__(self, tools: Sequence[ToolLike]):
        self.tools = list(tools)

    def format_for_llm(self) -> str:
        """Return markdown describing all available tools."""

        header = f"# Available MCP Tools ({len(self.tools)} total)\n\n"
        if not self.tools:
            return header + "No tools are currently available."

        body = "\n\n".join(self._format_single_tool(tool) for tool in self.tools)
        return header + body

    def get_tool_names(self) -> list[str]:
        """Return the tool names in discovery order."""

        names: list[str] = []
        for tool in self.tools:
            name = getattr(tool, "name", None)
            if isinstance(name, str):
                names.append(name)
        return names

    def _format_single_tool(self, tool: ToolLike) -> str:
        """Create a markdown block describing one tool."""

        name = getattr(tool, "name", "unknown_tool")
        description = getattr(tool, "description", "").strip() or "No description."

        schema = getattr(tool, "input_schema", None) or {}
        params = self._extract_properties(schema)
        required = self._extract_required(schema)

        signature = self._signature(params, required)
        param_json = json.dumps(params, indent=2, sort_keys=True)
        example = self._generate_example(name, params, required)

        return (
            f"## {name}\n"
            f"**Description**: {description}\n\n"
            f"**Usage**:\n"
            "```python\n"
            f"result = {name}({signature})\n"
            "```\n\n"
            f"**Parameters**:\n{param_json}\n\n"
            "**Example**:\n"
            "```python\n"
            f"{example}\n"
            "```"
        )

    def _extract_properties(self, schema: Mapping[str, Any]) -> dict[str, Any]:
        properties = schema.get("properties")
        if isinstance(properties, Mapping):
            return dict(properties)
        return {}

    def _extract_required(self, schema: Mapping[str, Any]) -> list[str]:
        required = schema.get("required") or []
        return [str(item) for item in required if isinstance(item, str)]

    def _signature(
        self,
        params: Mapping[str, Any],
        required: Sequence[str],
    ) -> str:
        parts: list[str] = []
        for name, info in params.items():
            type_hint = (
                info.get("type") if isinstance(info, Mapping) else None
            ) or "any"
            required_marker = "" if name in required else "?"
            parts.append(f"{name}{required_marker}: {type_hint}")
        return ", ".join(parts)

    def _generate_example(
        self,
        tool_name: str,
        params: Mapping[str, Any],
        required: Sequence[str],
    ) -> str:
        example_args: list[str] = []
        param_names = list(required) if required else list(params.keys())
        for param in param_names:
            info = params.get(param, {})
            type_hint = (
                info.get("type") if isinstance(info, Mapping) else None
            ) or "string"
            example_args.append(f"{param}={self._example_value(param, type_hint)}")

        args = ", ".join(example_args)
        if args:
            return f"result = {tool_name}({args})\nprint(result)"
        return f"result = {tool_name}()\nprint(result)"

    def _example_value(self, name: str, type_hint: str) -> str:
        if type_hint == "integer":
            return "42"
        if type_hint == "number":
            return "3.14"
        if type_hint == "boolean":
            return "True"
        if type_hint == "array":
            return f"[\"{name}_item\"]"
        return f'"{name}_value"'


__all__ = ["ToolSchemaFormatter"]
