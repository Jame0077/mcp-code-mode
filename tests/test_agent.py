import asyncio
import sys
import types
import unittest
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch


class AgentTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        mock_dspy = types.SimpleNamespace()
        mock_dspy.InputField = MagicMock()
        mock_dspy.OutputField = MagicMock()
        mock_dspy.Code = MagicMock()
        mock_dspy.ProgramOfThought = MagicMock(return_value=MagicMock())
        mock_dspy.CodeAct = MagicMock(return_value=MagicMock())

        self.modules_patcher = patch.dict(sys.modules, {"dspy": mock_dspy})
        self.modules_patcher.start()

        import mcp_code_mode.agent as agent_module

        self.agent_module = agent_module
        self.mock_tools = [MagicMock(name="tool_a"), MagicMock(name="tool_b")]
        for idx, tool in enumerate(self.mock_tools):
            tool.name = f"tool_{idx}"
            tool.description = f"description {idx}"
            tool.input_schema = {"properties": {"arg": {"type": "string"}}}

        self.runner_calls: list[dict[str, Any]] = []

        async def stub_runner(
            code,
            timeout=30,
            ctx=None,
            variables=None,
        ):
            self.runner_calls.append(
                {
                    "code": code,
                    "timeout": timeout,
                    "variables": variables,
                }
            )
            return {
                "success": True,
                "stdout": "sandbox-output",
                "stderr": "",
                "duration_ms": 12,
                "diagnostics": {"source": "sandbox"},
            }

        self.stub_runner = stub_runner
        self.bridge_sessions: list[str] = []

        class StubBridge:
            def __init__(self, outer):
                self.outer = outer

            async def create_session(self, timeout=0):
                token = f"token-{len(self.outer.bridge_sessions)}"
                self.outer.bridge_sessions.append(token)
                return {"endpoint": "http://127.0.0.1:9999/call", "token": token}

            def invalidate_session(self, token):
                if token in self.outer.bridge_sessions:
                    self.outer.bridge_sessions.remove(token)

        self.stub_bridge = StubBridge(self)

    def tearDown(self):
        self.modules_patcher.stop()

    async def test_run_returns_execution_result(self):
        agent = self.agent_module.CodeExecutionAgent(
            self.mock_tools,
            "context",
            sandbox_runner=self.stub_runner,
            tool_bridge=self.stub_bridge,  # type: ignore[arg-type]
        )
        fake_result = SimpleNamespace(code="print('ok')", answer="done")
        agent._invoke_generator = MagicMock(return_value=(fake_result, "", 0.1))

        result = await agent.run("do something")

        self.assertTrue(result["execution_result"]["success"])
        self.assertEqual(result["execution_result"]["stdout"], "sandbox-output")
        diagnostics = result["execution_result"]["diagnostics"]
        self.assertEqual(diagnostics["llm_answer"], "done")
        self.assertEqual(diagnostics["source"], "sandbox")
        self.assertIn("print('ok')", result["generated_code"])

        self.assertEqual(len(self.runner_calls), 1)
        runner_call = self.runner_calls[0]
        self.assertIn("call_mcp_tool", runner_call["code"])
        self.assertTrue(runner_call["code"].strip().endswith("print('ok')"))
        self.assertIn("MCP_TOOLS", runner_call["variables"])
        self.assertEqual(self.bridge_sessions, [])


if __name__ == "__main__":
    unittest.main()
