from __future__ import annotations

import json

import pytest

from conftest import load_module


def test_session_id_cannot_escape_directory(tmp_path):
    agent = load_module("miniagent/v04_memory/agent.py", "memory_agent_ids")
    agent.SESSIONS_DIR = tmp_path
    with pytest.raises(ValueError):
        agent.Session("../../outside")


def test_partial_last_line_is_ignored(tmp_path):
    agent = load_module("miniagent/v04_memory/agent.py", "memory_agent_partial")
    agent.SESSIONS_DIR = tmp_path
    session = agent.Session("demo")
    session.path.write_text(
        json.dumps({"role": "system", "content": "ok"}) + "\n{"
    )
    assert session.load() == [{"role": "system", "content": "ok"}]
    assert "不会自动重放" in session.recovery_warning


def test_incomplete_tool_call_is_detected():
    agent = load_module("miniagent/v04_memory/agent.py", "memory_agent_pending")
    messages = [
        {"role": "assistant", "tool_calls": [{"id": "call-1"}]},
    ]
    assert agent.has_incomplete_tool_call(messages)
    messages.append({"role": "tool", "tool_call_id": "call-1", "content": "ok"})
    assert not agent.has_incomplete_tool_call(messages)
