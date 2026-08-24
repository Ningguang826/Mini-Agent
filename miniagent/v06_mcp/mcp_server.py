"""一个极简 MCP server：对外提供两个工具。

跑法不用管——MCP client（我们的 Agent）会把它作为子进程拉起，
通过 stdin/stdout 用 JSON-RPC 对话。这就是 stdio 传输。
"""

import time
from pathlib import Path

from mcp.server.fastmcp import FastMCP

server = FastMCP("demo-server")


@server.tool()
def current_time() -> str:
    """返回当前的日期和时间"""
    return time.strftime("%Y-%m-%d %H:%M:%S")


@server.tool()
def project_stats(directory: str) -> str:
    """统计一个目录下的 Python 文件数量和总行数"""
    root = Path(directory)
    if not root.is_dir():
        return f"错误：目录不存在 {directory}"
    files = [p for p in root.rglob("*.py") if p.is_file()]
    lines = sum(len(p.read_text().splitlines()) for p in files)
    return f"{directory}：{len(files)} 个 Python 文件，共 {lines} 行"


if __name__ == "__main__":
    server.run()  # 默认 stdio 传输
