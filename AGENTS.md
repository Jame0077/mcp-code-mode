# mcp-code-mode Agent Guide

## Quick Links
- [Documentation & User Guide](file:///Users/themrb/Documents/personal/mcp-code-mode/docs/README.md)
- [Roadmap](file:///Users/themrb/Documents/personal/mcp-code-mode/docs/ROADMAP.md)

## Commands
- **Install**: `python -m venv .venv && source .venv/bin/activate && pip install -e .[dev]`
- **Run Server**: `python -m mcp_code_mode.executor_server`
- **Test**: `pytest` or single file `pytest tests/test_executor.py`
- **Lint**: `ruff check .` (fix with `--fix`), `black .`, `mypy src`
- **Verify**: `python scripts/test_dspy_sandbox.py` (sanity check)

## Guidelines
- **Style**: Python 3.11+, Black formatting, Ruff linting, comprehensive type hints (`mypy`).
- **Conventions**: Use absolute imports from `mcp_code_mode`. Prefer `async/await`.
- **Env**: Copy `.env.example` to `.env`.
