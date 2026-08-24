"""MiniAgent v0.3 —— Agent Loop：把第 0 章那十行伪代码变成真的。

    history = [user_task]
    while True:
        reply = llm(history)
        if reply 是最终答案: return reply
        result = 执行(reply 想调用的工具)
        history.append(reply, result)

判断"是不是最终答案"不需要任何魔法：模型没有请求工具调用
（finish_reason 不是 tool_calls），就是它认为说完了。
"""

import json
import os
import sys
from pathlib import Path

from openai import OpenAI

from tools import TOOL_SCHEMAS, execute_tool_call


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
MAX_TURNS = 20  # 停止条件之二：轮数上限，防止失控空转烧钱

SYSTEM_PROMPT = (
    "你是 MiniAgent，一个能独立完成编码任务的命令行 Agent。\n"
    "工作方式：先观察（读文件、跑命令），再动手（改文件），改完必须验证"
    "（重新运行测试或程序），确认无误后用一段话总结你做了什么。\n"
    "不要凭想象修改没读过的文件。"
)


def run_agent(task: str, verbose: bool = True) -> str:
    """跑一个完整的 Agent Loop，返回最终回答。"""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": task},
    ]

    total_prompt, total_cached, total_completion = 0, 0, 0

    for turn in range(1, MAX_TURNS + 1):
        response = client.chat.completions.create(
            model=MODEL, messages=messages, tools=TOOL_SCHEMAS
        )
        message = response.choices[0].message
        usage = response.usage
        total_prompt += usage.prompt_tokens
        total_completion += usage.completion_tokens
        total_cached += usage.prompt_tokens_details.cached_tokens or 0

        # 停止条件之一：模型不再请求工具，说明它认为任务完成了
        if not message.tool_calls:
            if verbose:
                print(f"\n—— 第 {turn} 轮，任务结束 ——")
                print(
                    f"[用量] 输入 {total_prompt} tokens（其中缓存命中 {total_cached}），"
                    f"输出 {total_completion} tokens"
                )
            return message.content or ""

        messages.append(message)
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
            messages.append(
                {"role": "tool", "tool_call_id": call.id, "content": result}
            )

    return f"达到 {MAX_TURNS} 轮上限，任务未完成。"


if __name__ == "__main__":
    task = " ".join(sys.argv[1:]) or input("任务> ").strip()
    answer = run_agent(task)
    print(f"\nMiniAgent> {answer}")
