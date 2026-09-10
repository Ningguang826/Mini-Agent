"""MiniAgent v0.4 —— 记忆管理：上下文压缩 + 会话持久化。

两个新能力：
1. 历史太长时，把旧消息压缩成一段摘要，腾出上下文预算（compact）
2. 每轮消息落盘成 JSONL，完整记录可以恢复；未完成的工具调用不会重放
"""

import json
import os
import re
import sys
import uuid
from pathlib import Path

from openai import OpenAI

from tools import TOOL_SCHEMAS, decode_tool_arguments, execute_tool_call
from mcp_client import MCP_PREFIX, call_mcp_tool, discover_mcp_tools
from reviewer import run_reviewer


def load_api_key() -> str:
    if key := os.environ.get("DEEPSEEK_API_KEY"):
        return key
    env_file = Path(__file__).resolve().parents[2] / ".env"
    for line in env_file.read_text().splitlines():
        if line.startswith("DEEPSEEK_API_KEY="):
            return line.split("=", 1)[1].strip()
    sys.exit("没有找到 DEEPSEEK_API_KEY")


client = OpenAI(api_key=load_api_key(), base_url="https://api.deepseek.com")
MODEL = "deepseek-v4-flash"
MAX_TURNS = 3

# 压缩阈值：历史字符数超过它就触发 compact。
# 真实系统按 token 精确计数（用模型的 tokenizer 或 usage 回报），
# 教学版用"字符数 / 3 ≈ token 数"的粗估，量级是对的。
COMPACT_THRESHOLD = int(os.environ.get("COMPACT_THRESHOLD", 120_000))
KEEP_RECENT = 6  # 压缩时保留最近几条消息不动

SESSIONS_DIR = Path(__file__).parent / "sessions"
SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

SYSTEM_PROMPT = (
    "你是 MiniAgent，一个能独立完成编码任务的命令行 Agent。\n"
    "工作方式：先观察（读文件、跑命令），再动手（改文件），改完必须验证"
    "（重新运行测试或程序），确认无误后用一段话总结你做了什么。\n"
    "不要凭想象修改没读过的文件。"
)


# ---------- 会话持久化 ----------


class Session:
    """把每条消息追加写进 JSONL 文件。一行一条消息，随时可恢复。"""

    def __init__(self, session_id: str | None = None):
        SESSIONS_DIR.mkdir(exist_ok=True)
        self.id = session_id or uuid.uuid4().hex[:8]
        if not SESSION_ID_RE.fullmatch(self.id):
            raise ValueError("session_id 只能包含字母、数字、下划线和连字符")
        self.path = SESSIONS_DIR / f"{self.id}.jsonl"
        self.recovery_warning: str | None = None

    def append(self, message: dict) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(message, ensure_ascii=False) + "\n")

    def load(self) -> list[dict]:
        if not self.path.exists():
            return []
        lines = self.path.read_text(encoding="utf-8").splitlines()
        messages = []
        for index, line in enumerate(lines):
            if not line.strip():
                continue
            try:
                messages.append(json.loads(line))
            except json.JSONDecodeError as exc:
                if index == len(lines) - 1:
                    self.recovery_warning = "最后一行没有写完整，已忽略；工具副作用不会自动重放"
                    break
                raise ValueError(f"会话第 {index + 1} 行损坏：{exc}") from exc
        return messages

    def rewrite(self, messages: list[dict]) -> None:
        """压缩后历史变了，整个文件重写一遍。"""
        with self.path.open("w", encoding="utf-8") as f:
            for m in messages:
                f.write(json.dumps(m, ensure_ascii=False) + "\n")


def has_incomplete_tool_call(messages: list[dict]) -> bool:
    """判断历史结尾是否停在尚未收到结果的工具调用上。"""
    pending: set[str] = set()
    for message in messages:
        if pending and message.get("role") != "tool":
            return True
        if message.get("role") == "assistant" and message.get("tool_calls"):
            pending = {call["id"] for call in message["tool_calls"]}
        elif message.get("role") == "tool":
            pending.discard(message.get("tool_call_id"))
    return bool(pending)


def to_dict(message) -> dict:
    """把 SDK 返回的 assistant 消息转成可序列化、可重发的纯 dict。

    注意丢弃 reasoning_content：它是给人看的调试信息，回填历史
    既浪费上下文，也可能不被 API 接受。
    """
    result = {"role": "assistant", "content": message.content or ""}
    if message.tool_calls:
        result["tool_calls"] = [
            {
                "id": c.id,
                "type": "function",
                "function": {
                    "name": c.function.name,
                    "arguments": c.function.arguments,
                },
            }
            for c in message.tool_calls
        ]
    return result


# ---------- 上下文压缩 ----------


def history_size(messages: list[dict]) -> int:
    return sum(len(json.dumps(m, ensure_ascii=False)) for m in messages)


def compact(messages: list[dict], verbose: bool = True) -> list[dict]:
    """把 [system 之后 ... 最近 KEEP_RECENT 条之前] 的消息压成一段摘要。"""
    if len(messages) <= 1 + KEEP_RECENT:
        return messages

    cut = len(messages) - KEEP_RECENT
    # 不能把 tool 消息和它对应的 assistant 消息切开，往后挪到安全边界
    while cut < len(messages) and messages[cut]["role"] == "tool":
        cut += 1
    old, recent = messages[1:cut], messages[cut:]
    if not old:
        return messages

    if verbose:
        print(f"[压缩] 历史 {history_size(messages)} 字符超过阈值，"
              f"压缩前 {len(messages)} 条消息")

    summary_request = [
        {
            "role": "user",
            "content": (
                "把下面这段 Agent 的工作历史压缩成一份摘要，供它稍后继续工作用。"
                "必须保留：任务目标、已经完成的步骤、关键文件路径和修改内容、"
                "跑过的命令和结果结论、尚未完成的事项。丢弃：文件的完整内容、"
                "重复的命令输出。\n\n" + json.dumps(old, ensure_ascii=False)
            ),
        }
    ]
    summary = (
        client.chat.completions.create(model=MODEL, messages=summary_request)
        .choices[0].message.content
    )

    compacted = [
        messages[0],  # system 永远原样保留
        {"role": "user", "content": f"[此前工作的摘要]\n{summary}"},
        *recent,
    ]
    if verbose:
        print(f"[压缩] 完成：{len(messages)} 条 → {len(compacted)} 条，"
              f"{history_size(compacted)} 字符")
    return compacted


# ---------- Agent Loop ----------


def run_agent(task: str | None, session: Session, verbose: bool = True) -> str:
    # v0.6：启动时发现 MCP 工具，和本地工具合并成一张工具表
    mcp_schemas = discover_mcp_tools()
    all_schemas = TOOL_SCHEMAS + mcp_schemas
    if verbose:
        names = [s['function']['name'] for s in mcp_schemas]
        print(f"[MCP] 发现 {len(names)} 个工具：{names}")

    messages = session.load()
    if has_incomplete_tool_call(messages):
        return (
            "检测到上次会话停在未完成的工具调用上。"
            "MiniAgent 不会猜测工具是否执行成功，也不会自动重放；请新建任务确认现场。"
        )
    if not messages:
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        session.append(messages[0])
    if task:
        user_msg = {"role": "user", "content": task}
        messages.append(user_msg)
        session.append(user_msg)

    for turn in range(1, MAX_TURNS + 1):
        if history_size(messages) > COMPACT_THRESHOLD:
            messages = compact(messages, verbose)
            session.rewrite(messages)

        response = client.chat.completions.create(
            model=MODEL, messages=messages, tools=all_schemas
        )
        message = response.choices[0].message
        assistant_msg = to_dict(message)
        messages.append(assistant_msg)
        session.append(assistant_msg)

        if not message.tool_calls:
            if verbose:
                print(f"\n—— 第 {turn} 轮，任务结束（会话 {session.id}）——")
            return message.content or ""

        for call in message.tool_calls:
            name = call.function.name
            args, argument_error = decode_tool_arguments(call.function.arguments)
            if verbose:
                brief = json.dumps(args, ensure_ascii=False)
                print(f"[第 {turn} 轮] {name} {brief[:120]}")
            if argument_error:
                result = argument_error
            elif name.startswith(MCP_PREFIX):
                try:
                    result = call_mcp_tool(name, args)
                except Exception as exc:
                    result = f"错误：MCP 工具调用失败：{type(exc).__name__}: {exc}"
            else:
                result = execute_tool_call(name, args)
            if verbose:
                print(f"        ↳ {result[:150].replace(chr(10), ' ')}")
            tool_msg = {
                "role": "tool", "tool_call_id": call.id, "content": result,
            }
            messages.append(tool_msg)
            session.append(tool_msg)

    return f"达到 {MAX_TURNS} 轮上限，任务未完成。"


if __name__ == "__main__":
    args = sys.argv[1:]
    session_id = None
    if args and args[0] == "--resume":
        session_id = args[1]
        print(f"恢复会话 {session_id}")
        args = args[2:]
        
    task = " ".join(args) or None
    if not task and not session_id:
        task = input("任务> ").strip()

    session = Session(session_id)
    print(f"会话 {session.id}")

    answer = run_agent(task, session)
    print(f"\nMiniAgent> {answer}")

    # v0.7：评审环节。最多一次返工，避免两个模型互相拉扯不收敛
    for review_round in range(1):
        print("\n—— 移交评审 ——")
        verdict = run_reviewer(client, MODEL, task or "（延续会话任务）", answer)
        status = verdict["verdict"]
        print(f"\n评审员> [{status}]")
        for reason in verdict["reasons"]:
            print(f"  - {reason}")
        if status == "APPROVE" or review_round == 1:
            break
        if status == "ERROR":
            # 评审失败 ≠ 工作被驳回：不返工，警告后放行。
            # 旧文本协议里两者混在同一个字符串里，ERROR 会被当成
            # "驳回意见"回喂主 Agent，触发一次莫名其妙的返工
            print("警告：评审流程本身出错，本次成果未经评审。")
            break
        feedback = (
            "评审员驳回了你的工作，意见如下，请修复后重新汇报：\n"
            + "\n".join(f"- {r}" for r in verdict["reasons"])
        )
        answer = run_agent(feedback, session)
        print(f"\nMiniAgent（返工后）> {answer}")
