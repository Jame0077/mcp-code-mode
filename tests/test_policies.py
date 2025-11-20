from mcp_code_mode.policies import enforce_guardrails, MAX_LINES


def test_enforce_guardrails_blocks_disallowed_tokens():
    allowed, message = enforce_guardrails("import subprocess\nprint('x')")
    assert allowed is False
    assert "subprocess" in (message or "")


def test_enforce_guardrails_allows_simple_code():
    allowed, message = enforce_guardrails("print('hello world')")
    assert allowed is True
    assert message is None


def test_enforce_guardrails_blocks_unknown_import():
    allowed, message = enforce_guardrails("import random\nprint(random.randint(1, 2))")
    assert allowed is False
    assert "random" in (message or "")


def test_enforce_guardrails_blocks_large_snippet():
    code = "\n".join(["print('x')"] * (MAX_LINES + 5))
    allowed, message = enforce_guardrails(code)
    assert allowed is False
    assert "too many lines" in (message or "").lower()
