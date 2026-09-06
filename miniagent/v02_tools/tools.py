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
    text = p.read_text()
    if len(text) > 20_000:  # 单位是"字符"（len() 数字符串长度），非 token；1 万~2 万字符 ≈ 几千 token，远小于模型窗口的 1M token
        return text[:20_000] + f"\n...（文件过长，已截断，共 {len(text)} 字符）"
    return text


def write_file(path: str, content: str) -> str:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return f"已写入 {path}（{len(content)} 字符）"


def edit_file(path: str, old_text: str, new_text: str) -> str:
    p = Path(path)
    if not p.is_file():
        return f"错误：文件不存在 {path}"
    text = p.read_text()
    count = text.count(old_text) # count 在计算 old_text 在整个文件里出现了几次。
    if count == 0:
        return "错误：没有找到要替换的文本，请先 read_file 确认内容完全一致"
    if count > 1:
        return f"错误：要替换的文本出现了 {count} 次，请提供更长的上下文让它唯一"
    p.write_text(text.replace(old_text, new_text))

    # replace 用法：
    # "hello world".replace("hello", "hi")          # "hi world"（变短）
    # "hello world".replace("hello", "hello there")  # "hello there world"（变长）
    # "hello world".replace("hello", "")             # " world"（直接删掉）

    return f"已修改 {path}"


def run_bash(command: str) -> str:
    try:
       
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=30
        )
        # shell=True: 交给系统 shell 解析，支持管道/&&/重定向；
        # capture_output=True: 抓回 stdout+stderr 而非直接打印到终端；
        # text=True: 把返回的字节流解码成字符串（bytes → str），省去手动 .decode()

    except subprocess.TimeoutExpired:
        return "错误：命令执行超过 30 秒，已终止"
    output = (result.stdout + result.stderr).strip()
    # 截断上限同理按"字符"算；模型上下文窗口按 token 计（1M token ≠ 100 万字符，英文 ≈ 4 字符/token）
    if len(output) > 10_000:  # 10_000 == 10000 两种写法等价
        output = output[:10_000] + "\n...（输出过长，已截断）"
    return f"退出码 {result.returncode}\n{output}" if output else f"退出码 {result.returncode}（无输出）"


def list_dir(path: str = ".") -> str:
    '''
    默认参数 path="."：. 是“当前目录”

    运行：python miniagent/v02_tools/main.py "看看 miniagent/v02_tools 目录里有什么"

    '''
    try:
        entries = sorted(p.name + ("/" if p.is_dir() else "") for p in Path(path).iterdir())
        # Path(path).iterdir() —— 遍历目录下的每一项，产生 Path 对象（不是字符串），每个 p 依次是一个文件或子目录

    except NotADirectoryError:
        return f"错误：{path} 不是目录"
    output = "\n".join(entries) if entries else "（空目录）"
    if len(output) > 5_000:
        output = output[:5_000] + "\n...（输出过长，已截断）"
    return output

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

    # 新增 list_dir 工具的 Schema
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "列出指定目录下的文件和子目录，默认列出当前目录",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "目录路径，默认为当前目录"},
                },
                "required": [],
            },
        },
    },
]

TOOL_FUNCTIONS = {
    "read_file": read_file,
    "write_file": write_file,
    "edit_file": edit_file,
    "run_bash": run_bash,
    "list_dir": list_dir, # 新增函数
}
