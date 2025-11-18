import pytest

from mcp_code_mode.mcp_integration import setup_mcp_tools


class FakeTool:
    def __init__(self, name: str):
        self.name = name
        self.description = f"{name} description"
        self.input_schema = {
            "properties": {
                "foo": {"type": "string", "description": "Example parameter"}
            },
            "required": ["foo"],
        }


class StubManager:
    def __init__(self):
        self.initialized = False
        self._tools = [FakeTool("foo_tool")]

    async def initialize(self):
        self.initialized = True
        return self._tools


@pytest.mark.asyncio
async def test_setup_mcp_tools_returns_context():
    manager = StubManager()
    result = await setup_mcp_tools(manager)

    assert result["manager"] is manager
    assert result["tools"] == manager._tools
    assert "# Available MCP Tools" in result["llm_context"]
    assert result["tool_names"] == ["foo_tool"]
