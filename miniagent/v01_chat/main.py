"""MiniAgent v0.1 —— 记得住对话的终端聊天程序。

核心只有一件事：所谓"多轮对话"，就是把历史 messages 数组原样重发。
"""

import os
import sys
from pathlib import Path

from openai import OpenAI


def load_api_key() -> str:
    """优先读环境变量，其次读仓库根目录的 .env。"""
    # :=  海象运算符：读环境变量，读到了就直接返回。边赋值边判断非空
    if key := os.environ.get("DEEPSEEK_API_KEY"):
        return key
    # 普通写法需要两步：
    # key = os.environ.get("DEEPSEEK_API_KEY")
    # if key:
    #     return key


    # Path(__file__).resolve().parents[2] 定位 .env 在哪：__file__ 是"当前这个 .py 文件自己的路径"，parents[2] 是往上数三层的祖先目录（main.py → v01_chat → miniagent → 仓库根）。这样无论你在哪个目录里运行它，都能找到仓库根下的 .env。
    env_file = Path(__file__).resolve().parents[2] / ".env" 

    # splitlines() 把文件内容按行拆成 list，逐行找 DEEPSEEK_API_KEY= 开头的那行；split("=", 1)[1] 按第一个等号劈成两半、取后半，就是 key 本身。
    for line in env_file.read_text().splitlines():
        if line.startswith("DEEPSEEK_API_KEY="):
            return line.split("=", 1)[1].strip()
        
        
    sys.exit("没有找到 DEEPSEEK_API_KEY，请配置环境变量或仓库根目录的 .env")
   

client = OpenAI(api_key=load_api_key(), base_url="https://api.deepseek.com")
MODEL = "deepseek-v4-flash"
SYSTEM_PROMPT = "你是 MiniAgent，一个简洁直接的中文助手。"


def chat(messages: list[dict]) -> str:
    """流式调用模型，边收边打印，返回完整回复文本。"""
    stream = client.chat.completions.create(
        model=MODEL,
        messages=messages,
        temperature=1.0,
        stream=True,
    )
    reply = ""
    for chunk in stream:
        delta = chunk.choices[0].delta
        if delta and delta.content:
            print(delta.content, end="", flush=True)
            reply += delta.content
    print()
    return reply


def main() -> None:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    print(f"MiniAgent v0.1（{MODEL}），输入 exit 退出")
    while True:
        try:
            user_input = input("\n你> ").strip()
        except EOFError:
            break
        if not user_input or user_input == "exit":
            break

        messages.append({"role": "user", "content": user_input})
        print("MiniAgent> ", end="", flush=True) #flush=True 不能省，Python 的 print 默认攒一批再显示，不强制刷新的话"流式"会退化成一段一段地蹦；
        reply = chat(messages)
        # 不把回复追加回去，模型下一轮就会"失忆"——这行是全章的核心
        messages.append({"role": "assistant", "content": reply})

        # 如果想看usage属性，因为现在 stream=True，流式模式下返回的是一格一格的 chunk，
        # 每个 chunk 里没有汇总的 usage，所以看不到。想看 usage 就要临时改成非流式：

        # resp.usage 里常用字段：

        # prompt_tokens / completion_tokens / total_tokens —— 输入、输出、总量
        # DeepSeek 特有的 prompt_cache_hit_tokens / prompt_cache_miss_tokens —— 输入里命中缓存和未命中的部分


if __name__ == "__main__":
    main()
