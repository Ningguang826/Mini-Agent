"""v0.7 新增：reviewer 子 Agent。

和主 Agent 的三个关键差异：
1. 独立的 messages —— 它没见过主 Agent 的思考过程，只看任务和成果，
   这正是评审价值的来源：没有"我写的肯定没错"的立场。
2. 无源码修改工具 —— read / grep / run_tests，没有 write、edit 和任意 shell。
3. 结构化裁决 —— 最终输出必须是 {"verdict": ..., "reasons": [...]} JSON，程序好校验。
"""

import json
import re
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
    "核实完成后，输出一个 JSON 对象作为最终裁决，不要输出其他任何文字：\n"
    '{"verdict": "APPROVE", "reasons": ["一句话说明核实了什么"]}\n'
    "或\n"
    '{"verdict": "REJECT", "reasons": ["问题1及证据", "问题2及证据"]}\n'
    "verdict 只能取 APPROVE 或 REJECT，reasons 必须是字符串数组，"
    "不要用 markdown 代码块包裹。"
)

MAX_REVIEW_TURNS = 10


VALID_VERDICTS = {"APPROVE", "REJECT"}


class VerdictError(ValueError):
    """裁决输出不符合协议。"""


def parse_verdict(text: str) -> dict:
    """从模型自由文本里提取并校验裁决 JSON，失败抛 VerdictError。

    三层防御，每层只拦一种故障：
    1. 剥围栏、截取 {...} —— 容忍模型加 markdown 和说明文字
    2. json.loads —— 拦语法错误（单引号、尾逗号、中文引号）
    3. schema 校验 —— 拦字段缺失、类型错、枚举值错
    """
    if not text or not text.strip():
        raise VerdictError("输出为空")

    cleaned = text.strip()
    if cleaned.startswith("```"):  # ```json ... ```
        cleaned = re.sub(r"^```[\w-]*\s*|\s*```$", "", cleaned).strip()
        # 1. 左边：`^\`\`\`[\w-]*\s*`
        # - `[\w-]*`：匹配可选的语言标记（`\w`：word 字符，等价 `[a-zA-Z0-9_]`，`-`横杠，`*`代表 0 个或多个，可以没有）
        # - `\s*`：匹配后面任意空白（空格、换行）

        # 2. 右边：`\s*\`\`\`$`
        # - `\s*`：匹配末尾 ``` 前面的空白 / 换行
        # - `$`：匹配**字符串结尾**

    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        raise VerdictError("输出里没有找到 JSON 对象")

    try:
        data = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as exc:
        raise VerdictError(f"JSON 语法错误：{exc}") from exc

    if not isinstance(data, dict):
        raise VerdictError("JSON 顶层必须是对象")
    if data.get("verdict") not in VALID_VERDICTS:
        raise VerdictError(
            f"verdict 必须是 APPROVE/REJECT，实际是 {data.get('verdict')!r}"
        )
    reasons = data.get("reasons", [])
    if not isinstance(reasons, list) or not all(isinstance(r, str) for r in reasons):
        raise VerdictError("reasons 必须是字符串数组")
    return {"verdict": data["verdict"], "reasons": reasons}


def run_reviewer(client, model: str, task: str, report: str, verbose=True) -> dict:
    """跑一个没有源码修改工具的评审循环。

    返回值保证是 {"verdict": "APPROVE"|"REJECT"|"ERROR", "reasons": [...]}，
    调用方拿到的是数据而不是需要二次解析的文本——这就是接口加固：
    解析和校验收敛在边界这一处，内部全走结构化对象。
    """
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
            try:
                return parse_verdict(message.content or "")
            except VerdictError as exc:
                # JSON 协议独有的自愈：错误能定位到字段，回喂后模型知道改什么。
                # 文本协议只能说"你没按协议"，模型只能盲猜重试
                if verbose:
                    print(f"[评审 第 {turn} 轮] 裁决解析失败：{exc}")
                messages.append(message)
                messages.append({
                    "role": "user",
                    "content": (
                        f"你的输出不符合协议：{exc}\n"
                        "请只输出一个符合格式的 JSON 对象，"
                        "不要 markdown 代码块，不要任何其他文字。"
                    ),
                })
            continue
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
    return {"verdict": "ERROR", "reasons": ["评审超过轮数上限，未能完成核实"]}
