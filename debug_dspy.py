
import os
import time
import logging
from dotenv import load_dotenv
import dspy

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("debug_dspy")

def test_dspy():
    load_dotenv()
    
    gemini_key = os.environ.get("GEMINI_API_KEY")
    openai_key = os.environ.get("OPENAI_API_KEY")
    
    logger.info("Configuring DSpy...")
    if gemini_key:
        try:
            lm = dspy.LM("gemini/gemini-2.5-pro", api_key=gemini_key)
            dspy.configure(lm=lm)
            logger.info("✅ DSpy configured with Gemini")
        except Exception as e:
            logger.error(f"❌ Failed to configure Gemini: {e}")
            return
    elif openai_key:
        lm = dspy.LM("openai/gpt-4o-mini", api_key=openai_key)
        dspy.configure(lm=lm)
        logger.info("✅ DSpy configured with OpenAI")
    else:
        logger.error("❌ No API key found")
        return

    # Define the signature as in agent.py
    class CodeGenerationSignature(dspy.Signature):
        """Generate Python code to complete a task using available MCP tools."""
        task: str = dspy.InputField(desc="The user's task to complete")
        available_tools: str = dspy.InputField(
            desc="Detailed documentation of available MCP tools with parameters and examples"
        )
        code: dspy.Code = dspy.OutputField(
            desc="Python code that uses the available tools to complete the task"
        )

    logger.info("Initializing ProgramOfThought...")
    generator = dspy.ProgramOfThought(CodeGenerationSignature)
    
    # Load real tools to reproduce environment accurately
    from mcp_code_mode.mcp_integration import setup_mcp_tools
    from mcp_code_mode.mcp_manager import MCPServerManager
    import asyncio

    logger.info("Loading MCP tools...")
    # We need to run async setup in this sync function, which is awkward but doable for a script
    async def get_context():
        mgr = MCPServerManager()
        setup = await setup_mcp_tools(mgr)
        await mgr.shutdown()
        return setup["llm_context"]
    
    tool_context = asyncio.run(get_context())
    logger.info(f"Tool context length: {len(tool_context)} chars")

    task = "calculate 1+1"
    
    logger.info(f"Generating code for task: '{task}'...")
    start_time = time.time()
    
    try:
        result = generator(task=task, available_tools=tool_context)
        duration = time.time() - start_time
        
        logger.info(f"✅ Generation complete in {duration:.2f} seconds")
        logger.info(f"Generated code:\n{result.code}")
        
    except Exception as e:
        logger.error(f"❌ Generation failed: {e}")

if __name__ == "__main__":
    test_dspy()
