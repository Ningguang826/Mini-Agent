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
    # encoding="utf-8"：.env 是 UTF-8（注释含中文），Windows 默认 GBK 读会崩溃
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if line.startswith("DEEPSEEK_API_KEY="):
            return line.split("=", 1)[1].strip()
    sys.exit("没有找到 DEEPSEEK_API_KEY")


client = OpenAI(api_key=load_api_key(), base_url="https://api.deepseek.com")
MODEL = "deepseek-v4-flash"
MAX_TURNS = 20  # 停止条件之二：轮数上限，防止失控空转烧钱

# deepseek-v4-flash 非高峰价（$ / 百万 token），用于每轮实时估算费用。
# 高峰时段（UTC 周一~周五 01:00-04:00、06:00-10:00）输入/输出翻倍；缓存命中部分永远按命中价算。
# 更新价格时查 DeepSeek 官方 pricing 页，同步改这三行即可——后续版本直接复用这个常量。
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


SYSTEM_PROMPT = (
    "你是 MiniAgent，一个能独立完成编码任务的命令行 Agent。\n"
    "工作方式：先观察（读文件、跑命令），再动手（改文件），改完必须验证"
    "（重新运行测试或程序），确认无误后用一段话总结你做了什么。\n"
    "防幻觉规则：修改没读过的文件是禁止的，不要凭想象修改没读过的文件。"
   
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
        usage = response.usage  # 与 v01/练习4 区别：这是多轮 loop，API 每轮只报"本轮"的用量，必须自己累加才是整个任务的账
        total_prompt += usage.prompt_tokens
        total_completion += usage.completion_tokens
        total_cached += usage.prompt_tokens_details.cached_tokens or 0
        # DeepSeek 兼容 OpenAI 协议，提供两套缓存字段：
        #   OpenAI 风格嵌套：usage.prompt_tokens_details.cached_tokens（这里用的）
        #   DeepSeek 特有：prompt_cache_hit_tokens / prompt_cache_miss_tokens（v02 练习4 用的）
        # or 0：部分请求该字段可能是 None（如未触发缓存），None + int 会崩，兜底成 0。

        
        # 每轮实时"计费播报"：一眼看出 loop 跑到第几轮、烧了多少钱（后续版本沿用 usage_billboard）
        usage_billboard(turn, total_prompt, total_cached, total_completion, verbose)

        # 停止条件之一：模型不再请求工具，说明它认为任务完成了
        if not message.tool_calls:
            if verbose:
                print(f"\n—— 第 {turn} 轮，任务结束 ——")
                print(
                    f"[用量] 输入 {total_prompt} tokens（其中缓存命中 {total_cached}），"
                    f"输出 {total_completion} tokens"
                )
                # 结束时补一次最终费用（与每轮播报同一公式，最后一行的总账）
                uncached = total_prompt - min(total_cached, total_prompt)
                final_cost = cost_usd(min(total_cached, total_prompt), uncached, total_completion)
                print(f"[账单] 整个任务 ≈ {final_cost:.5f}$（≈  {final_cost * 7.2:.5f}元）")
            return message.content or ""

        messages.append(message) # 模型说了它想调什么。注意 assistant 消息必须原样进历史


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
                # chr(10) 即 "\n"：f-string 表达式里不能写反斜杠，用 chr() 绕开。
                # replace 把工具结果里的换行压成空格，保证每条结果摘要只占"一行"，不破坏日志格式。
                print(f"        ↳ {result[:150].replace(chr(10), ' ')}")

            messages.append(
                {"role": "tool", "tool_call_id": call.id, "content": result}
            )

    return f"达到 {MAX_TURNS} 轮上限，任务未完成。"


if __name__ == "__main__":
    task = " ".join(sys.argv[1:]) or input("任务> ").strip()
    # sys.argv 是“命令行参数列表”：argv[0] 永远是脚本自己的名字（main.py），argv[1:] 切片取后面真正的参数。
    # 等效运行：python miniagent/v03_loop/agent.py "labs/cart_boundary/cart.py 里的 total_price 函数有一个优惠券 bug：满 100 减 20 的券在正好满 100 时没有生效。请读取 labs/cart_boundary/test_cart.py 了解预期行为，找出并修复 cart.py 里的 bug，修完运行 python -m pytest -q 验证（注意在 labs/cart_boundary 目录下运行），通过后总结你做了什么"

    answer = run_agent(task)
    print(f"\nMiniAgent> {answer}")
