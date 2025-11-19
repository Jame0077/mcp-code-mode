import unittest
from unittest.mock import MagicMock, patch, AsyncMock
import sys

# Mock dspy module before importing agent
mock_dspy = MagicMock()
sys.modules["dspy"] = mock_dspy

# Mock executor module
mock_executor_module = MagicMock()
sys.modules["mcp_code_mode.executor"] = mock_executor_module

from mcp_code_mode.agent import CodeExecutionAgent

class TestAgentInjection(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Setup mock tools
        self.mock_tool_read = MagicMock()
        self.mock_tool_read.name = "read_file"
        
        self.mock_tool_write = MagicMock()
        self.mock_tool_write.name = "write_file"
        
        self.tools = [self.mock_tool_read, self.mock_tool_write]
        self.tool_context = "Mock context"
        
        # Mock dspy.ProgramOfThought
        mock_dspy.ProgramOfThought.return_value = MagicMock()
        
        self.agent = CodeExecutionAgent(self.tools, self.tool_context)

    def test_generate_tool_shims(self):
        """Test that shims are generated for known tools."""
        shims = self.agent._generate_tool_shims()
        
        self.assertIn("def read_file(path):", shims)
        self.assertIn("def write_file(path, content):", shims)
        self.assertIn("with open(path", shims)

    async def test_execute_with_tools_injects_shims(self):
        """Test that _execute_with_tools prepends shims to code."""
        generated_code = "print(read_file('/tmp/test.txt'))"
        
        # Mock SandboxedPythonExecutor instance
        mock_executor_instance = AsyncMock()
        mock_executor_instance.run.return_value = {"success": True}
        
        # Setup the mock class to return our instance
        mock_executor_module.SandboxedPythonExecutor.return_value = mock_executor_instance
        
        # Run execution
        await self.agent._execute_with_tools(generated_code)
        
        # Verify run was called
        self.assertTrue(mock_executor_instance.run.called)
        
        # Get the code passed to run
        call_args = mock_executor_instance.run.call_args
        passed_code = call_args[0][0]
        
        # Verify shims are present
        self.assertIn("def read_file(path):", passed_code)
        self.assertIn("# Generated Code", passed_code)
        self.assertIn("print(read_file('/tmp/test.txt'))", passed_code)

if __name__ == "__main__":
    unittest.main()
