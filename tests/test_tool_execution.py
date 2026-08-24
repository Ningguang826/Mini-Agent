from __future__ import annotations

import pytest

from conftest import load_module


TOOL_MODULES = [
    "miniagent/v02_tools/tools.py",
    "miniagent/v03_loop/tools.py",
    "miniagent/v04_memory/tools.py",
    "miniagent/v05_search/tools.py",
    "miniagent/v06_mcp/tools.py",
    "miniagent/v07_review/tools.py",
    "miniagent/v08_eval/tools.py",
]


@pytest.mark.parametrize("relative", TOOL_MODULES)
def test_bad_tool_calls_become_observations(relative):
    tools = load_module(relative, "course_tools_" + relative.split("/")[1])
    assert "合法 JSON" in tools.execute_tool_call("read_file", "{")
    assert "JSON 对象" in tools.execute_tool_call("read_file", "[]")
    assert "未知工具" in tools.execute_tool_call("missing", {})
    assert "参数不匹配" in tools.execute_tool_call("read_file", {})


def test_v08_workspace_blocks_parent_paths(tmp_path):
    tools = load_module("miniagent/v08_eval/tools.py", "eval_tools")
    tools.set_workspace(tmp_path)
    assert "超出评测工作目录" in tools.execute_tool_call(
        "read_file", {"path": "../secret.txt"}
    )
    assert "run_bash" not in tools.TOOL_FUNCTIONS
    assert "run_bash" not in {
        schema["function"]["name"] for schema in tools.TOOL_SCHEMAS
    }
