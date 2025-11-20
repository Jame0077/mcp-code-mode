import aiohttp
import pytest

from mcp_code_mode.tool_bridge import MCPToolBridge


class DummyTool:
    def __init__(self):
        self.name = "echo"
        self.calls = []

    async def acall(self, **kwargs):
        self.calls.append(kwargs)
        return kwargs


@pytest.mark.asyncio
async def test_tool_bridge_handles_calls():
    tool = DummyTool()
    bridge = MCPToolBridge([tool])
    try:
        await bridge.start()
    except PermissionError as exc:  # pragma: no cover - CI may restrict sockets
        pytest.skip(f"socket binding not permitted: {exc}")
    session = await bridge.create_session(timeout=10)

    async with aiohttp.ClientSession() as client:
        resp = await client.post(
            session["endpoint"],
            json={
                "token": session["token"],
                "name": "echo",
                "params": {"value": 42},
            },
        )
        data = await resp.json()

    await bridge.stop()

    assert data["success"] is True
    assert data["result"] == {"value": 42}
    assert tool.calls == [{"value": 42}]
