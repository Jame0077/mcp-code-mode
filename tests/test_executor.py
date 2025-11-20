import time
from typing import Any

import pytest

from mcp_code_mode import executor_server
from mcp_code_mode.executor import SandboxOptions, SandboxedPythonExecutor


class StubInterpreter:
    """Minimal stand-in for DSpy's PythonInterpreter used in unit tests."""

    def __init__(
        self,
        *,
        stdout: str = "",
        stderr: str = "",
        delay: float = 0.0,
        exc: BaseException | None = None,
    ) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.delay = delay
        self.exc = exc

    def execute(self, code: str) -> dict[str, Any]:
        if self.delay:
            time.sleep(self.delay)
        if self.exc is not None:
            raise self.exc
        return {"stdout": self.stdout or code, "stderr": self.stderr}


@pytest.mark.asyncio
async def test_executor_success_normalizes_output() -> None:
    executor = SandboxedPythonExecutor(
        options=SandboxOptions(max_output_chars=5),
        interpreter_factory=lambda: StubInterpreter(stdout="hello!", stderr=""),
    )
    result = await executor.run("print('hi')")

    assert result["success"] is True
    assert result["stdout"].startswith("hello")
    assert "truncated" in result["stdout"]


@pytest.mark.asyncio
async def test_executor_timeout_result() -> None:
    executor = SandboxedPythonExecutor(
        interpreter_factory=lambda: StubInterpreter(delay=0.1)
    )
    result = await executor.run("while True: pass", timeout=0.01)

    assert result["success"] is False
    assert result["diagnostics"]["error_type"] == "TIMEOUT"


@pytest.mark.asyncio
async def test_executor_exception_result() -> None:
    executor = SandboxedPythonExecutor(
        interpreter_factory=lambda: StubInterpreter(
            exc=RuntimeError("boom")
        )
    )
    result = await executor.run("1/0")

    assert result["success"] is False
    assert result["diagnostics"]["error_type"] == "RuntimeError"
    assert "boom" in result["stderr"]


@pytest.mark.asyncio
async def test_execute_code_invalid_timeout(monkeypatch) -> None:
    # No executor patch needed; timeout validation happens before execution.
    # We call the underlying function (.fn) because the tool wrapper is not directly callable
    result = await executor_server.execute_code.fn("print('x')", timeout=0)

    assert result["success"] is False
    assert result["diagnostics"]["error_type"] == "INVALID_ARGUMENT"


@pytest.mark.asyncio
async def test_execute_code_success(monkeypatch) -> None:
    class RecordingExecutor:
        def __init__(self) -> None:
            self.calls: list[tuple[str, float]] = []

        async def run(self, code: str, *, timeout: float) -> dict[str, Any]:
            self.calls.append((code, timeout))
            return {
                "success": True,
                "stdout": "ok",
                "stderr": "",
                "duration_ms": 1,
                "diagnostics": None,
            }

    fake_executor = RecordingExecutor()
    monkeypatch.setattr(executor_server, "EXECUTOR", fake_executor)

    # Call the underlying function
    result = await executor_server.execute_code.fn("print('ok')", timeout=5)

    assert result["success"] is True
    assert fake_executor.calls == [("print('ok')", 5.0)]
