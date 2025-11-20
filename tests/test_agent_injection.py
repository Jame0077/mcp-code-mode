import unittest
from unittest.mock import MagicMock, patch, AsyncMock
import sys
import importlib
from typing import Any

class TestAgentInjection(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Create mocks
        self.mock_dspy = MagicMock()
        self.mock_executor_module = MagicMock()
        
        # Patch sys.modules
        self.modules_patcher = patch.dict(sys.modules, {
            "dspy": self.mock_dspy,
            "mcp_code_mode.executor": self.mock_executor_module
        })
        self.modules_patcher.start()
        
        # Import/Reload agent module to ensure it uses mocks
        import mcp_code_mode.agent
        importlib.reload(mcp_code_mode.agent)
        self.agent_module = mcp_code_mode.agent
        
        # Setup mock tools
        self.mock_tool_read = MagicMock()
        self.mock_tool_read.name = "read_file"
        
        self.mock_tool_write = MagicMock()
        self.mock_tool_write.name = "write_file"
        
        self.tools = [self.mock_tool_read, self.mock_tool_write]
        self.tool_context = "Mock context"
        
        # Mock dspy.ProgramOfThought
        self.mock_dspy.ProgramOfThought.return_value = MagicMock()
        
        self.agent = self.agent_module.CodeExecutionAgent(self.tools, self.tool_context)

    def tearDown(self):
        self.modules_patcher.stop()
        # Reload agent to restore state (optional, but good for isolation)
        import mcp_code_mode.agent
        importlib.reload(mcp_code_mode.agent)

    def test_generate_tool_shims(self):
        """Test that shims are generated for known tools."""
        shims = self.agent._generate_tool_shims("http://test-bridge")
        
        self.assertIn("def read_file(**kwargs):", shims)
        self.assertIn("def write_file(**kwargs):", shims)
        self.assertIn("BRIDGE_URL = \"http://test-bridge\"", shims)

    @patch("mcp_code_mode.agent._ToolBridge")
    async def test_execute_with_tools_injects_shims(self, mock_bridge_cls):
        """Test that _execute_with_tools prepends shims to code."""
        generated_code = "print(read_file('/tmp/test.txt'))"
        
        # Mock bridge instance
        mock_bridge = mock_bridge_cls.return_value
        mock_bridge.start = AsyncMock(return_value="http://mock-bridge")
        mock_bridge.stop = AsyncMock()

        # Mock SandboxedPythonExecutor instance
        mock_executor_instance = AsyncMock()
        mock_executor_instance.run.return_value = {"success": True}
        
        # Setup the mock class to return our instance
        self.mock_executor_module.SandboxedPythonExecutor.return_value = mock_executor_instance
        
        # Run execution
        await self.agent._execute_with_tools(generated_code)
        
        # Verify run was called
        self.assertTrue(mock_executor_instance.run.called)
        
        # Get the code passed to run
        call_args = mock_executor_instance.run.call_args
        passed_code = call_args[0][0]
        
        # Verify shims are present
        self.assertIn("def read_file(**kwargs):", passed_code)
        self.assertIn("# Generated Code", passed_code)
        self.assertIn("print(read_file('/tmp/test.txt'))", passed_code)

if __name__ == "__main__":
    unittest.main()
