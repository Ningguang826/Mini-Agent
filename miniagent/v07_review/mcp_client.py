"""MCP 客户端封装：发现工具、调用工具。

教学版为了保持同步代码的简单，每次调用都重新拉起 server 子进程、
握手、调用、关闭。真实实现（tau、Claude Code）在 Agent 启动时
建立一次连接并复用——那需要把整个 Agent 改成 async，第 7 章文档
里解释了这个取舍。
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

MCP_PREFIX = "mcp__"  # 挂在工具名前，让我们能分辨哪些工具走 MCP


async def _list_tools() -> list[dict]:
    async with stdio_client(SERVER) as (read, write):
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
    ]


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
    return asyncio.run(_list_tools())


def call_mcp_tool(name: str, args: dict) -> str:
    """name 带 mcp__ 前缀，去掉后转发给 server。"""
    return asyncio.run(_call_tool(name.removeprefix(MCP_PREFIX), args))
