# MiniAgent：从零写一个编码 Agent

这是《Agent基础入门》飞书课程的配套代码仓库。代码按教学顺序逐步演进，重点是先看懂 Agent 的核心循环，再逐章增加工具、记忆、检索、MCP、多 Agent 和评测。

## 版本路线

| 目录 | 对应章节 | 新增能力 |
| --- | --- | --- |
| `miniagent/v00_repl/` | 1.2 | 最小 REPL 骨架 |
| `miniagent/v01_chat/` | 2.3 | 流式对话与 messages 历史 |
| `miniagent/v02_tools/` | 3.3 | 单轮 Function Calling |
| `miniagent/v03_loop/` | 4.3 | 完整 Agent Loop |
| `miniagent/v04_memory/` | 5.3 | 上下文压缩与会话持久化 |
| `miniagent/v05_search/` | 6.3 | grep 与最小 TF-IDF 检索 |
| `miniagent/v06_mcp/` | 7.3 | MCP server/client 接入 |
| `miniagent/v07_review/` | 8.3 | Reviewer 子 Agent |
| `miniagent/v08_eval/` | 9.2、9.3 | 带完整性检查的 10 任务评测 runner |

## 环境准备

在仓库根目录执行：

```bash
uv venv --python 3.12
source .venv/bin/activate
uv pip install -r requirements.txt
```

先跑不需要 API Key 的离线检查，确认环境和配套代码都完整：

```bash
pytest -q
python3 scripts/cart_lab.py prepare
cd labs/cart_boundary && python -m pytest -q
```

购物车练习的初始结果应为 `1 failed, 2 passed`。回到仓库根目录后，可以用 `python3 scripts/cart_lab.py reset` 随时恢复起点。

在仓库根目录创建 `.env`：

```text
DEEPSEEK_API_KEY=你的_key
```

## 从最小版本开始

```bash
python miniagent/v00_repl/main.py
python miniagent/v01_chat/main.py
python miniagent/v02_tools/main.py "读一下 README.md"
python miniagent/v03_loop/agent.py \
  "修复 labs/cart_boundary 里的购物车优惠券 bug，修完后运行测试确认"
```

MCP、Reviewer 和评测版本应进入各自目录运行，因为教学代码刻意使用了最直观的相对路径：

```bash
cd miniagent/v06_mcp
python agent.py "用工具查看当前时间"

cd ../v07_review
python agent.py "修复一个 bug"

cd ../v08_eval
python run_eval.py 01
```

`v05_search/rag_demo.py` 默认使用仓库自带的小语料，也可以接收任意本地语料目录：

```bash
python miniagent/v05_search/rag_demo.py "怎么恢复会话"
python miniagent/v05_search/rag_demo.py "怎么恢复会话" /path/to/markdown-corpus
```

第四章的购物车练习可以随时重新准备：

```bash
python3 scripts/cart_lab.py prepare
python3 scripts/cart_lab.py reset
```

## 仓库检查

```bash
pytest -q
```
