from mcp_code_mode.tool_formatter import ToolSchemaFormatter


class FakeTool:
    def __init__(self):
        self.name = "read_file"
        self.description = "Read a text file"
        self.input_schema = {
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to read",
                }
            },
            "required": ["path"],
        }


def test_format_for_llm_includes_usage_block():
    formatter = ToolSchemaFormatter([FakeTool()])
    doc = formatter.format_for_llm()

    assert "# Available MCP Tools (1 total)" in doc
    assert "## read_file" in doc
    assert "result = read_file(path: string)" in doc
    assert 'path="path_value"' in doc  # Example generation


def test_get_tool_names_returns_discovered_names():
    tools = [FakeTool(), FakeTool()]
    tools[1].name = "write_file"
    formatter = ToolSchemaFormatter(tools)

    assert formatter.get_tool_names() == ["read_file", "write_file"]
