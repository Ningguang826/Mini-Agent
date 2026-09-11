"""MCP 客户端封装：发现工具、调用工具。

教学版为了保持同步代码的简单
每次调用都重新拉起 server 子进程、握手、调用、关闭。
真实实现（tau、Claude Code）在 Agent 启动时,建立一次连接并复用
——那需要把整个 Agent 改成 async，第 7 章文档里解释了这个取舍。
"""

import asyncio
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVER = StdioServerParameters(
    command=sys.executable,
    args=[str(Path(__file__).with_name("mcp_server.py"))],
)

MCP_PREFIX = "mcp__"  # 工具前缀名：挂在工具名前，让我们能分辨哪些工具属于哪些 MCP Servicer

# async def 协程函数,调用它不会直接执行函数体,而是返回一个协程对象。
# 要执行协程函数,必须交给事件循环驱动才能运行,需要使用 asyncio.run() 或 await。
async def _list_tools() -> list[dict]:
    '''把 MCP 工具转成 OpenAI 工具表格式'''
    # 进入时用 SERVER 里配置的命令(当前 Python 解释器 + 同目录的mcp_server.py) 启动 server 子进程,并建立 stdio 通道。
    # 通过子进程的 stdin/stdout 建立两条消息管道，返回 (read, write) 这一对读写流——as (read, write) 就是解包这个二元组。退出时关闭子进程、清理管道。
    async with stdio_client(SERVER) as (read, write): 

        # 在这对管道上建立 MCP 会话对象
        async with ClientSession(read, write) as session:
            await session.initialize()          # 握手：交换协议版本和能力
            tools = await session.list_tools()  # 发现：server 有哪些工具

    return [
        {
            "type": "function",
            "function": {
                "name": MCP_PREFIX + t.name,
                "description": t.description or "",
                "parameters": t.inputSchema,
            },
        }
        for t in tools.tools
    ]  # 实质工作只有加前缀，description 和 inputSchema 都是原样转发。和Function Calling是同一套 JSON Schema


async def _call_tool(name: str, args: dict) -> str:
    async with stdio_client(SERVER) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(name, args)
    text = "\n".join(
        block.text for block in result.content if block.type == "text"
    ) or "（无文本输出）"
    return f"错误：MCP 工具执行失败：{text}" if result.isError else text


def discover_mcp_tools() -> list[dict]:
    """返回 OpenAI 工具 Schema 格式的 MCP 工具列表。

    注意这里没有任何格式魔法：MCP 的工具描述本身就是 JSON Schema，
    和 Function Calling 用的是同一套语言，几乎原样转发。
    """
    return asyncio.run(_list_tools()) # asyncio.run 负责“创建事件循环 → 跑这个协程 → 跑完销毁”


def call_mcp_tool(name: str, args: dict) -> str:
    """name 带 mcp__ 前缀，去掉后转发给 server。"""
    return asyncio.run(_call_tool(name.removeprefix(MCP_PREFIX), args))
