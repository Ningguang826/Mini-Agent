"""MiniAgent v0.2 的工具层：read / write / edit / bash。

模型不能执行任何东西，它只能"说想执行什么"。
真正碰文件系统、跑命令的，是这个文件里的普通 Python 函数。
"""

import json
import subprocess
from pathlib import Path


def decode_tool_arguments(arguments: str | dict) -> tuple[dict | None, str | None]:
    """把模型给出的参数变成 dict；失败也作为工具结果返回给模型。"""
    if isinstance(arguments, dict):
        return arguments, None
    try:
        value = json.loads(arguments)
    except (TypeError, json.JSONDecodeError) as exc:
        return None, f"错误：工具参数不是合法 JSON：{exc}"
    if not isinstance(value, dict):
        return None, "错误：工具参数必须是一个 JSON 对象"
    return value, None


def execute_tool_call(name: str, arguments: str | dict) -> str:
    """校验并执行一次本地工具调用，任何失败都转换成可观察的文本。"""
    args, error = decode_tool_arguments(arguments)
    if error:
        return error
    function = TOOL_FUNCTIONS.get(name)
    if function is None:
        return f"错误：未知工具 {name}"
    try:
        result = function(**args)
    except TypeError as exc:
        return f"错误：工具参数不匹配：{exc}"
    except Exception as exc:
        return f"错误：工具执行失败：{type(exc).__name__}: {exc}"
    return str(result)

# ---- 工具的实现：就是普通函数 ----


def read_file(path: str) -> str:
    p = Path(path)
    if not p.is_file():
        return f"错误：文件不存在 {path}"
    # encoding="utf-8"：Windows 默认 GBK，中文文件必须显式 utf-8（同 v03/v04 补丁）
    text = p.read_text(encoding="utf-8")
    if len(text) > 20_000:
        return text[:20_000] + f"\n...（文件过长，已截断，共 {len(text)} 字符）"
    return text


def write_file(path: str, content: str) -> str:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")   # 不写则按 GBK 落盘，读回会乱码
    return f"已写入 {path}（{len(content)} 字符）"


def edit_file(path: str, old_text: str, new_text: str) -> str:
    p = Path(path)
    if not p.is_file():
        return f"错误：文件不存在 {path}"
    text = p.read_text(encoding="utf-8")   # 同 read_file：显式 utf-8
    count = text.count(old_text)
    if count == 0:
        return "错误：没有找到要替换的文本，请先 read_file 确认内容完全一致"
    if count > 1:
        return f"错误：要替换的文本出现了 {count} 次，请提供更长的上下文让它唯一"
    # 写回也必须 utf-8：读对了但写不带 encoding，Windows 会"读 UTF-8 写 GBK"转码污染
    p.write_text(text.replace(old_text, new_text), encoding="utf-8")
    return f"已修改 {path}"


def run_bash(command: str) -> str:
    try:
        # encoding+errors（Windows 关键）：不指定时子进程输出按 GBK 解码，含中文输出会
        # 崩读线程、stdout 变 None；errors="replace" 让解不了的字符退成 ? 而非崩溃
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=30,
            encoding="utf-8", errors="replace",
        )
    except subprocess.TimeoutExpired:
        return "错误：命令执行超过 30 秒，已终止"
    output = (result.stdout + result.stderr).strip()
    if len(output) > 10_000:
        output = output[:10_000] + "\n...（输出过长，已截断）"
    return f"退出码 {result.returncode}\n{output}" if output else f"退出码 {result.returncode}（无输出）"


# ---- 工具的 Schema：给模型看的"说明书" ----

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "读取一个文本文件的完整内容",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件路径"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "创建或覆盖写入一个文本文件",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件路径"},
                    "content": {"type": "string", "description": "要写入的完整内容"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "把文件中一段唯一出现的文本替换为新文本。old_text 必须与文件内容逐字符一致且只出现一次",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件路径"},
                    "old_text": {"type": "string", "description": "要被替换的原文"},
                    "new_text": {"type": "string", "description": "替换后的新文本"},
                },
                "required": ["path", "old_text", "new_text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_bash",
            "description": "在 shell 中执行一条命令并返回输出，用于运行测试、查看目录等",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "要执行的命令"},
                },
                "required": ["command"],
            },
        },
    },
]

TOOL_FUNCTIONS = {
    "read_file": read_file,
    "write_file": write_file,
    "edit_file": edit_file,
    "run_bash": run_bash,
}


# ---- v0.5 新增：代码库检索工具 ----

import re


def grep_code(pattern: str, directory: str = ".", file_glob: str = "*") -> str:
    """在目录下所有匹配 file_glob 的文本文件里正则搜索，返回 路径:行号:内容。"""
    root = Path(directory)
    if not root.is_dir():
        return f"错误：目录不存在 {directory}"
    try:
        regex = re.compile(pattern)
    except re.error as e:
        return f"错误：正则表达式不合法：{e}"
    hits = []
    for path in sorted(root.rglob(file_glob)):
        if not path.is_file() or any(part.startswith(".") for part in path.parts):
            continue
        try:
            # encoding="utf-8"：Windows 默认 GBK，UTF-8 中文文件会被解成乱码（不报错但匹配失灵），
            # 显式 utf-8 后二进制文件解码失败 → 走下面的 except 被跳过，行为跨平台一致
            lines = path.read_text(encoding="utf-8").splitlines()
        except (UnicodeDecodeError, OSError):
            continue  # 跳过二进制和读不了的文件
        for lineno, line in enumerate(lines, 1):
            if regex.search(line):
                hits.append(f"{path}:{lineno}: {line.strip()[:200]}")
                if len(hits) >= 50:
                    hits.append("...（超过 50 条命中，请用更精确的 pattern）")
                    return "\n".join(hits)
    return "\n".join(hits) if hits else "没有找到匹配"


TOOL_SCHEMAS.append(
    {
        "type": "function",
        "function": {
            "name": "grep_code",
            "description": (
                "在代码库中用正则表达式搜索，返回 文件路径:行号:匹配行。"
                "用于定位函数定义、找到某个字符串出现的位置。"
                "在大项目里应该先 grep 定位再 read_file，不要逐个文件乱读"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "正则表达式"},
                    "directory": {"type": "string", "description": "搜索目录，默认当前目录"},
                    "file_glob": {"type": "string", "description": "文件名过滤，如 *.py，默认所有文件"},
                },
                "required": ["pattern"],
            },
        },
    }
)
TOOL_FUNCTIONS["grep_code"] = grep_code
