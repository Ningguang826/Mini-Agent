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
from datetime import datetime
from pathlib import Path

from openai import OpenAI

from tools import TOOL_SCHEMAS, execute_tool_call


def load_api_key() -> str:
    if key := os.environ.get("DEEPSEEK_API_KEY"):
        return key
    env_file = Path(__file__).resolve().parents[2] / ".env"
    # encoding="utf-8"：.env 注释含中文，Windows 默认 GBK 读会 UnicodeDecodeError（同 v03）
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if line.startswith("DEEPSEEK_API_KEY="):
            return line.split("=", 1)[1].strip()
    sys.exit("没有找到 DEEPSEEK_API_KEY")


client = OpenAI(api_key=load_api_key(), base_url="https://api.deepseek.com")
MODEL = "deepseek-v4-flash"
MAX_TURNS = 30

PRICING = {
    "cache_hit_input": 0.007,   # $/1M：缓存命中的输入部分（单价差 30 倍，必须和未命中分开算）
    "cache_miss_input": 0.22,   # $/1M：缓存未命中的输入部分
    "output": 0.66,             # $/1M：输出
}


def cost_usd(cached: int, uncached: int, completion: int) -> float:
    """按 (缓存命中输入, 未命中输入, 输出) 三部分 token 数计费，返回美元。"""
    return (
        cached * PRICING["cache_hit_input"]
        + uncached * PRICING["cache_miss_input"]
        + completion * PRICING["output"]
    ) / 1_000_000


def usage_billboard(turn: int, total_prompt: int, total_cached: int,
                    total_completion: int, verbose: bool = True) -> None:
    """打印截至当前轮的累计 token 与预估费用。轮内调用（verbose 关时静默）。"""
    if not verbose:
        return
    
    total_cached = min(total_cached, total_prompt)  # 防御：个别后端 cached 可能略超 prompt
    uncached = total_prompt - total_cached
    cost = cost_usd(total_cached, uncached, total_completion)
    # 1 里 ≈ $0.000433（按 1 美元 = 7.2 元换算、元/厘百进制）；打印"厘"方便和练习4 对账
    print(f"[费用] 至第 {turn} 轮累计：输入 {total_prompt}（缓存命中 {total_cached} / 未命中 {uncached}），"
          f"输出 {total_completion}，约 {cost:.5f}$（≈  {cost * 7.2:.5f}元）")

    
# 压缩阈值：历史字符数超过它就触发 compact。
# 真实系统按 token 精确计数（用模型的 tokenizer 或 usage 回报），
# 教学版用"字符数 / 3 ≈ token 数"的粗估，量级是对的。
COMPACT_THRESHOLD = int(os.environ.get("COMPACT_THRESHOLD", 12_000))
KEEP_RECENT = 6  # 压缩时保留最近几条消息不动

SESSIONS_DIR = Path(__file__).parent / "sessions" # 会话存到的目录
SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
# Session ID 做格式校验用的正则，预编译成对象供反复匹配。

# ^...$ —— 必须从头到尾整串匹配（不能只匹配中间一段）
# [A-Za-z0-9_-] —— 只允许：字母、数字、下划线 _、连字符 -
# {1,64} —— 长度 1~64 个字符
# re.compile(...) —— 编译一次，后续 SESSION_ID_RE.match(sid) 直接用

# 缓存实验②：时间戳放最前面 —— 前缀缓存从第 1 个 token 开始逐块匹配，
# system 的第一个字节每次启动都不同 → 跨进程前缀必然断裂，第 1 轮命中归零。
# （若放尾部，固定段在前照样命中，只毁尾部几十 token，实验信号弱。）
# 注意：datetime.now() 在模块加载时求值一次 → 进程内 30 轮 system 恒定，轮内爬升不受影响。
SYSTEM_PROMPT = (
    f"当前时间：{datetime.now().isoformat()}\n"
    "你是 MiniAgent，一个能独立完成编码任务的命令行 Agent。\n"
    "工作方式：先观察（读文件、跑命令），再动手（改文件），改完必须验证"
    "（重新运行测试或程序），确认无误后用一段话总结你做了什么。\n"
    "防幻觉机制：修改没读过的文件是禁止的 ，不要凭想象修改没读过的文件。"
)




# ---------- 会话持久化 ----------


class Session:
    """把每条消息追加写进 JSONL 文件。一行一条消息，随时可恢复。"""

    def __init__(self, session_id: str | None = None):
        SESSIONS_DIR.mkdir(exist_ok=True)
        self.id = session_id or uuid.uuid4().hex[:8] #uuid.uuid4() 造一个 128 位随机 UUID → .hex 取它的 32 位纯 hex 字符串 
        if not SESSION_ID_RE.fullmatch(self.id):
            raise ValueError("session_id 只能包含字母、数字、下划线和连字符")
        self.path = SESSIONS_DIR / f"{self.id}.jsonl"
        self.recovery_warning: str | None = None

    def append(self, message: dict) -> None:
        # encoding="utf-8"：Windows 下 open() 默认按 GBK 写入，ensure_ascii=False 的
        # 中文/emoji 遇到 GBK 无对应码位会直接 UnicodeEncodeError，或造成"写 GBK 读 UTF-8"错配
        with self.path.open("a", encoding="utf-8") as f: # a可写不可读，a+可写可读
            f.write(json.dumps(message, ensure_ascii=False) + "\n") #dumps：转换成json字符串

    def load(self) -> list[dict]:
        if not self.path.exists():
            return []

        # 与 append 用同一套编码：写utf-8 读也必须utf-8，否则中文全是乱码
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
        # encoding="utf-8"：同 append，与 load 统一编码契约
        with self.path.open("w", encoding="utf-8") as f:
            for m in messages:
                f.write(json.dumps(m, ensure_ascii=False) + "\n")


def has_incomplete_tool_call(messages: list[dict]) -> bool:
    """判断历史结尾是否停在尚未收到结果的工具调用上。"""
    pending: set[str] = set() #账本，记着“模型已经发起tool_calls、但结果还没交回来的工具调用 id"。
    for message in messages:
        if pending and message.get("role") != "tool":
            return True
        
        # 先记账（先记录tool_calls中的id）
        if message.get("role") == "assistant" and message.get("tool_calls"):
            pending = {call["id"] for call in message["tool_calls"]}

        # 再销账（遍历到下一条message，再从账本中删去前一轮记录的id）
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
    if len(messages) <= 1 + KEEP_RECENT: #这里的1表示system prompt
        return messages

    cut = len(messages) - KEEP_RECENT
    # 不能把 tool 消息和它对应的 assistant 消息切开，往后挪到安全边界
    while cut < len(messages) and messages[cut]["role"] == "tool": #这里之所以是tool是因为下面recent是从cut索引开始的
        cut += 1
    old, recent = messages[1:cut], messages[cut:]
    if not old:
        return messages

    if verbose:
        print(f"[压缩] 历史 {history_size(messages)} 字符超过阈值，"
              f"压缩前: {len(messages)} 条消息")

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
        {"role": "user", "content": f"[此前工作的摘要:]\n{summary}"},
        *recent,
    ]
    if verbose:
        print(f"[压缩] 完成：{len(messages)} 条 → {len(compacted)} 条，"
              f"{history_size(compacted)} 字符")
    return compacted


# ---------- Agent Loop ----------


def run_agent(task: str | None, session: Session, verbose: bool = True) -> str:
    # 双记账原则：每条消息诞生时总是"双写"——
    #   messages.append  = 内存账本，伺候本进程的 API 调用（传给 create()），进程结束即消失
    #   session.append   = 磁盘账本，伺候下一个进程的恢复（load() 读回），跨进程持久
    # 因此本函数内两行 append 永远成对出现，只留一个都会丢账。
    # 注意：两个 append 名字一样但不是一个方法——messages 用的是 Python list 自带的
    # list.append；session.append 是上面 Session 类自定义的方法（把一条消息追加写入
    # JSONL 文件）。同名不同物，一个是内置列表操作，一个是自定义的落盘动作。
    messages = session.load()
    total_prompt, total_cached, total_completion = 0, 0, 0

    
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
        messages.append(user_msg)      # 双写（同下）：内存给 API，磁盘给恢复
        session.append(user_msg)       # 新任务的起点，进磁盘后未来 resume 才有账可读

    for turn in range(1, MAX_TURNS + 1):
        if history_size(messages) > COMPACT_THRESHOLD:
            messages = compact(messages, verbose)
            session.rewrite(messages)

        response = client.chat.completions.create(
            model=MODEL, messages=messages, tools=TOOL_SCHEMAS
        )
        message = response.choices[0].message
        assistant_msg = to_dict(message)
        messages.append(assistant_msg)   # 内存账本：给下一轮 create() 看
        session.append(assistant_msg)    # 磁盘账本：给下次 --resume 时 load() 看


        usage = response.usage   # DeepSeek 特有字段族：prompt_cache_hit_tokens（v04 实验用）
        # or 0 兜底：该字段是 int（DeepSeek 总返回），保险处理万一为 None 的兼容情况
        total_prompt += usage.prompt_tokens
        total_cached += usage.prompt_cache_hit_tokens or 0
        total_completion += usage.completion_tokens

        # 每轮实时"计费播报"：一眼看出 loop 跑到第几轮、烧了多少钱（后续版本沿用 usage_billboard）
        usage_billboard(turn, total_prompt, total_cached, total_completion, verbose)

        if not message.tool_calls:
            if verbose:
                print(f"\n—— 第 {turn} 轮，任务结束（会话 {session.id}）——")
            return message.content or ""

        for call in message.tool_calls:
            name = call.function.name
            try:
                args = json.loads(call.function.arguments)
            except json.JSONDecodeError:
                args = call.function.arguments
            if verbose:
                brief = json.dumps(args, ensure_ascii=False)
                print(f"[第 {turn} 轮] {name} {brief[:120]}")
            result = execute_tool_call(name, call.function.arguments)
            if verbose:
                print(f"        ↳ {result[:150].replace(chr(10), ' ')}")
            tool_msg = {
                "role": "tool", "tool_call_id": call.id, "content": result,
            }
            messages.append(tool_msg)     # 双写（同上）：内存给 API，磁盘给恢复
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
