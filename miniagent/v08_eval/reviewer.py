"""v0.7 新增：reviewer 子 Agent。

和主 Agent 的三个关键差异：
1. 独立的 messages —— 它没见过主 Agent 的思考过程，只看任务和成果，
   这正是评审价值的来源：没有"我写的肯定没错"的立场。
2. 无源码修改工具 —— read / grep / run_tests，没有 write、edit 和任意 shell。
3. 结构化裁决 —— 最终输出必须以 APPROVE 或 REJECT 开头，程序好解析。
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from tools import TOOL_SCHEMAS, execute_tool_call

REVIEW_TOOL_NAMES = {"read_file", "grep_code", "run_tests"}
REVIEW_SCHEMAS = [
    s for s in TOOL_SCHEMAS if s["function"]["name"] in REVIEW_TOOL_NAMES
]

REVIEWER_PROMPT = (
    "你是一个严格的代码评审员。另一个 Agent 刚完成了一项编码任务，"
    "你要独立核实它的工作：\n"
    "1. 读它声称修改过的文件，确认修改真实存在且正确\n"
    "2. 运行测试或程序验证，不要轻信它的汇报\n"
    "3. 检查有没有引入新问题（误删代码、多余修改、边界情况）\n\n"
    "你没有修改源码和执行任意 shell 的工具，不要尝试修改任何文件。\n"
    "最终回答的第一行只能是 APPROVE 或 REJECT 这一个单词，"
    "不要加粗、不要标题、不要表情符号，从第二行开始写说明：\n"
    "APPROVE —— 工作合格，一句话说明核实了什么\n"
    "REJECT —— 有问题，逐条列出问题和证据，给出修改建议"
)

MAX_REVIEW_TURNS = 10


def verdict_status(verdict: str) -> str:
    """只接受未加装饰的精确状态，其他输出一律视为 ERROR。"""
    first_line = verdict.strip().splitlines()[0] if verdict.strip() else ""
    return first_line if first_line in {"APPROVE", "REJECT"} else "ERROR"


def run_reviewer(client, model: str, task: str, report: str, verbose=True) -> str:
    """跑一个没有源码修改工具的评审循环。"""
    messages = [
        {"role": "system", "content": REVIEWER_PROMPT},
        {
            "role": "user",
            "content": f"原始任务：\n{task}\n\n执行 Agent 的汇报：\n{report}\n\n请核实。",
        },
    ]
    for turn in range(1, MAX_REVIEW_TURNS + 1):
        response = client.chat.completions.create(
            model=model, messages=messages, tools=REVIEW_SCHEMAS
        )
        message = response.choices[0].message
        if not message.tool_calls:
            verdict = message.content or ""
            if verdict_status(verdict) == "ERROR":
                return "ERROR\n评审员没有按协议给出 APPROVE 或 REJECT"
            return verdict
        messages.append(message)
        for call in message.tool_calls:
            try:
                args = json.loads(call.function.arguments)
            except json.JSONDecodeError:
                args = call.function.arguments
            if verbose:
                print(f"[评审 第 {turn} 轮] {call.function.name} "
                      f"{json.dumps(args, ensure_ascii=False)[:100]}")
            result = execute_tool_call(call.function.name, call.function.arguments)
            messages.append(
                {"role": "tool", "tool_call_id": call.id, "content": result}
            )
    return "ERROR\n评审超过轮数上限，未能完成核实"
