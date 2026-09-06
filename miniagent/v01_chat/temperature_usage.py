"""练习 4 临时实验：temperature 对比 + usage/成本计算。跑完即删。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from miniagent.v01_chat.main import client, MODEL

QUESTION = "用一句话描述'秋天'。"
PRICING = {  # deepseek-v4-flash 非高峰价，$/1M token
    "cache_hit_input": 0.007,
    "cache_miss_input": 0.22,
    "output": 0.66,
}


def ask(temp: float) -> None:
    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": QUESTION}],
        temperature=temp,
        stream=False,
    )
    
    cost = (
        response.usage.prompt_cache_hit_tokens * PRICING["cache_hit_input"]
        + response.usage.prompt_cache_miss_tokens * PRICING["cache_miss_input"]
        + response.usage.completion_tokens * PRICING["output"]
    ) / 1_000_000
    print(f"\n--- temperature={temp} ---")
    print(f"回复: {response.choices[0].message.content!r}")
    print(f"输入: 命中 {response.usage.prompt_cache_hit_tokens} tok, 未命中 {response.usage.prompt_cache_miss_tokens} tok; "
          f"输出 {response.usage.completion_tokens} tok; 总 {response.usage.total_tokens} tok")
    print(f"本轮花费: ${cost:.6f} ≈ {cost * 100:.2f} 厘")


if __name__ == "__main__":
    for t in (0, 0, 1.5, 1.5):
        ask(t)
