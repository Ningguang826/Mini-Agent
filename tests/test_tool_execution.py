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


# 参数化：TOOL_MODULES 里 7 个版本的 tools.py 各生成一条独立用例（7+1=8 条）。
# 运行时每轮只有一个变量 tools（用例结束即销毁，7 轮之间不共存），变量名无需区分版本。
# 不直接 import 是因为 7 个文件都叫 tools.py，无条件限制下同名模块只能加载一个，
# 所以用 load_module 按文件路径动态加载，并用唯一注册名（第二参）防止 importlib 缓存里的同名模块被互相顶掉。
@pytest.mark.parametrize("relative", TOOL_MODULES)
def test_bad_tool_calls_become_observations(relative):
    # relative: 当前用例的文件路径，如 "miniagent/v02_tools/tools.py"；
    # relative.split("/")[1] 取第二段 "v02_tools"，拼出唯一模块名 "course_tools_v02_tools"
    tools = load_module(relative, "course_tools_" + relative.split("/")[1])
    assert "合法 JSON" in tools.execute_tool_call("read_file", "{")
    assert "JSON 对象" in tools.execute_tool_call("read_file", "[]")
    assert "未知工具" in tools.execute_tool_call("missing", {})
    assert "参数不匹配" in tools.execute_tool_call("read_file", {})


# 四条"错误也要变成可读文本"的固定断言（对应 execute_tool_call 的四类失败路径）。
# 含义：工具失败绝不能抛异常穿透，必须翻译成模型能读懂、能据此自我纠正的字符串。
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
