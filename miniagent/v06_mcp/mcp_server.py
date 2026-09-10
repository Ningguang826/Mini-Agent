"""一个极简 MCP server：对外提供三个工具。

跑法不用管——MCP client（我们的 Agent）会把它作为子进程拉起，
通过 stdin/stdout 用 JSON-RPC 对话。这就是 stdio 传输。
"""

import time
from pathlib import Path
import subprocess

from mcp.server.fastmcp import FastMCP

server = FastMCP("demo-server")

# 写 MCP 工具就是普通函数加一个装饰器。
# docstring 自动变成工具描述，类型注解自动变成参数 Schema:（directory: str → {"type": "string"}）
@server.tool()
def current_time() -> str:
    """返回当前的日期和时间"""
    return time.strftime("%Y-%m-%d %H:%M:%S")


@server.tool()
def project_stats(directory: str) -> str:
    """统计一个目录下的 Py 文件数量和总行数"""
    root = Path(directory)

    if not root.is_dir():
        return f"错误：目录不存在 {directory}"
    
    files = [p for p in root.rglob("*.py") if p.is_file()] # rglob = 递归 glob，把子目录,子子目录全部走一遍
    lines = sum(len(p.read_text(encoding="utf-8").splitlines()) for p in files)
    return f"{directory}：{len(files)} 个 .Py 文件，共 {lines} 行"


def _find_git_root(start: Path) -> Path | None:
    """从 start 逐级向上找 .git，返回仓库根；找不到返回 None。

    .git 通常是目录，但在 worktree / submodule 里是一个文件，所以用 exists() 而不是 is_dir()。
    """
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


@server.tool()
def git_log(directory: str = ".", n: int = 5) -> str:
    """返回目录所在 Git 仓库的最近 n 条提交记录。

    directory 可以是仓库内的任意子目录，会自动向上查找 .git 定位仓库根；
    不传时从当前目录开始找。
    """
    root = Path(directory).resolve()
    if not root.is_dir():
        return f"错误：目录不存在 {directory}"

    repo = _find_git_root(root)
    if repo is None:
        return f"错误：{root} 及其上层都不是 Git 仓库"

    try:
        result = subprocess.run(
            ["git", "-C", str(repo), "log", f"-n{n}", "--oneline"],
            capture_output=True,
            text=True,
            check=True,
            encoding="utf-8", errors="replace",  # 不写则子进程输出按 GBK 解码，中文提交信息会乱码
            # stdio server 里再拉子进程的两个保命参数：
            # stdin=DEVNULL：否则 git 继承 server 的 stdin（连着 MCP client 的管道），
            #                孙进程和协议信道搅在一起，实测会卡死不返回
            # CREATE_NO_WINDOW：server 无控制台，不指定的话 git 会自己开一个新控制台
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return f"[{repo}]\n{result.stdout.strip() or '(没有提交记录)'}"
    except subprocess.CalledProcessError as e:
        return f"错误：无法获取 Git 日志：{e.stderr.strip()}"

    
if __name__ == "__main__":
    server.run()  # 默认 stdio 传输
    # 这个文件里永远不要用 print 调试，stdout 是协议信道
    # 一行 print 就能毁掉整个消息流。要输出调试信息走 stderr
