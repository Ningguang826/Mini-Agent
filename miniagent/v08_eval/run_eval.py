"""MiniAgent v0.8 —— 带完整性检查的最小评测 runner。

用法：
    python run_eval.py            # 跑全部 10 个任务
    python run_eval.py 03 07      # 只跑指定编号，其余记为 NOT_RUN

runner 不信 Agent 的口头汇报，也不只看 pytest 退出码。它先确认任务基线
确实失败，再检查 Agent 是否只修改允许的源码，最后运行可见测试和独立测试。

读取任务清单
   ↓
复制题目到独立工作目录
   ↓
先运行测试，确认原始代码确实有 Bug（基线失败）
   ↓
让 Agent 在副本中修复
   ↓
比较修复前后的文件哈希，检查是否修改越权
   ↓
重新运行公开测试 + 隐藏测试
   ↓
生成 PASSED / FAILED / TAMPERED / ERROR / TIMEOUT 等结果
   ↓
写入 eval_results/*.json

测试层次：
- evalset/<任务>/test_*.py 是随题目副本一起交给 Agent 的可见测试；
  它用于帮助定位 Bug，类似开发时可反复运行的公开验证样例。
- grader_tests/<任务>.py 由 runner 在基线检查和 Agent 修复后的复测阶段都显式传给 pytest；
  它不在 Agent 的 work 工作区内，用独立边界条件验证修复不能只适配可见样例。
- tests/test_eval_runner.py 测的是 runner 自身：它用伪 Agent 验证通过、越权、异常、
  超时和 Windows 子进程回收等评测规则，不是在测试某一道 Bug 题是否被修好。
  运行 ``python -m pytest -q tests/test_eval_runner.py`` 得到的是这台“裁判机”的回归结果。

"""

from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing
import os
import queue
import shutil
import signal
import subprocess
import sys
import time
import threading
import uuid
from pathlib import Path
from typing import Callable


# 使用绝对路径，避免 pytest 或动态导入改变 cwd 后把评测目录误解析到其他位置。
HERE = Path(__file__).resolve().parent
EVALSET = HERE / "evalset"
GRADER_TESTS = HERE / "grader_tests"
MANIFEST = EVALSET / "manifest.json"
RESULTS_DIR = HERE / "eval_results"
WORK_ROOT = HERE / "eval_work"
TEST_TIMEOUT = 120
AGENT_TIMEOUT = 600

TASK_PROMPT = (
    "修复 {work} 项目里的 bug：先用 run_tests 看哪些测试失败，"
    "读相关代码定位原因，修复后重跑测试，直到全部通过。"
    "你可以读测试，但只允许修改这些源码文件：{editable}。"
)

IGNORED_PARTS = {"__pycache__", ".pytest_cache"}
IGNORED_NAMES = {".coverage"}


class AgentTimeout(RuntimeError):
    pass


def sha256(path: Path) -> str:
    # 使用内容哈希而不是文件修改时间，避免时间戳精度差异造成误判。
    return hashlib.sha256(path.read_bytes()).hexdigest() # 给每个文件的内容计算 SHA-256 哈希


def file_hashes(root: Path) -> dict[str, str]:
    """记录工作目录中需要纳入完整性检查的文件内容哈希。"""
    hashes: dict[str, str] = {}
    for path in sorted(root.rglob("*")): # 递归遍历根目录下所有子文件 / 文件夹
        if not path.is_file():
            continue
        relative = path.relative_to(root) # 转为 相对于根目录的路径，哈希字典和目录位置无关，移动整个项目根目录也能正常比对

        # pytest/Python 运行时生成的缓存不是 Agent 的源码修改。
        if any(part in IGNORED_PARTS for part in relative.parts):
            continue
        # 覆盖率文件和字节码属于运行副产物，不触发越权修改判定。
        if path.name in IGNORED_NAMES or path.suffix == ".pyc":
            continue

        hashes[relative.as_posix()] = sha256(path) #- 把 Windows 风格路径（`miniagent\v06_mcp\mcp_client.py`）统一转为 POSIX 标准斜杠 `/`- 输出字符串：`miniagent/v06_mcp/mcp_client.py`

        # {
        #     "cart.py": "f92f...",
        #     "test_cart.py": "a1c9...",
        #     "README.md": "7e32...",
        # }
    return hashes


def changed_files(before: dict[str, str], after: dict[str, str]) -> set[str]:
    # 使用并集同时覆盖文件修改、删除和新建三种情况。
    # | 情况 | `before` | `after` | 能否识别 |

    # | 修改已有文件 | 有旧哈希 | 有新哈希 | 可以 |
    # | 删除已有文件 | 有旧哈希 | 无 | 可以 |
    # | 新建文件 | 无 | 有新哈希 | 可以 |
    paths = before.keys() | after.keys()
    return {path for path in paths if before.get(path) != after.get(path)}


def run_tests(work: Path, hidden_test: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()

    # 确保测试导入的是当前任务副本中的源码，而不是其他位置的同名模块。
    # 目的是隐藏测试执行：
    # from cart import ...时，导入的是：
    # eval_work/<run_id>/01_cart_boundary/cart.py
    # 而不是仓库中其他位置碰巧存在的同名 cart.py
    env["PYTHONPATH"] = str(work) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        # 同时运行：
        # 1. work 目录里的公开测试；例如：miniagent/v08_eval/evalset/01_cart_boundary/
                                                                # ├─ cart.py
                                                                # └─ test_cart.py
        # 2. hidden_test 指向的独立测试测试。 hidden_test = GRADER_TESTS / config["hidden_test"]
        # work 和 hidden_test 可能位于不同盘符；固定 rootdir 可避免 pytest 向磁盘根目录回溯收集。
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            f"--rootdir={work}",
            str(work),
            str(hidden_test),
        ],
        cwd=work,
        env=env,
        capture_output=True,
        text=True,
        timeout=TEST_TIMEOUT,
    )


def output_tail(result: subprocess.CompletedProcess[str]) -> str:
    # 只保留末尾少量输出，避免完整 pytest 日志撑大汇总 JSON。
    output = (result.stdout + result.stderr).strip().splitlines()
    return "\n".join(output[-8:])


def default_agent_runner(work: Path) -> tuple[str, str, int]:
    """延迟导入在线 Agent，让 runner 的离线单元测试不需要 API Key。"""
    sys.path.insert(0, str(HERE))
    from agent import Session, run_agent
    from tools import set_workspace

    # Agent 的工具操作范围切换到任务副本，避免修改 evalset 原件。
    set_workspace(work)
    config = json.loads(MANIFEST.read_text(encoding="utf-8"))[work.name]
    session = Session()
    answer = run_agent(
        TASK_PROMPT.format(work=work, editable=", ".join(config["editable"])),
        session,
        verbose=False,
    )
    # assistant 消息数近似表示 Agent 轮数，只用于统计，不参与通过判定。
    turns = sum(1 for message in session.load() if message.get("role") == "assistant")
    return answer, session.id, turns


def _default_agent_process_entry(work_text: str, result_queue) -> None:
    """子进程入口：默认 Agent 的返回值或异常必须通过 Queue 回传给父进程。"""
    try:
        answer, session_id, turns = default_agent_runner(Path(work_text))
        # 父进程结果只保存 answer 的前 300 字；子进程同样截断，避免大消息堵塞 Queue。
        result_queue.put(("ok", (answer[:300], session_id, turns)))
    except Exception as exc:
        # 异常对象本身未必可 pickle；仅传回稳定的文本信息。
        result_queue.put(("error", f"{type(exc).__name__}: {exc}"))


def call_default_agent_with_timeout(
    work: Path, seconds: int
) -> tuple[str, str, int]:
    """在独立子进程运行默认 Agent，Windows 超时时可彻底终止其执行。"""
    # Windows 使用 spawn。子进程拥有独立解释器和工具状态，terminate 后不会继续写 work。
    context = multiprocessing.get_context("spawn")
    result_queue = context.Queue()
    process = context.Process(
        target=_default_agent_process_entry,
        args=(str(work), result_queue),
    )
    try:
        process.start()
        process.join(seconds)
        if process.is_alive():
            process.terminate()
            process.join()
            raise AgentTimeout(f"Agent 执行超过 {seconds} 秒")

        try:
            status, payload = result_queue.get(timeout=1)
        except queue.Empty as exc:
            raise RuntimeError(
                f"Agent 子进程未返回结果，exitcode={process.exitcode}"
            ) from exc
        if status == "error":
            raise RuntimeError(payload)
        return payload
    finally:
        # 无论正常结束还是超时，都回收句柄，避免多任务评测时累积系统资源。
        result_queue.close()
        result_queue.join_thread()
        if process.pid is not None and not process.is_alive():
            process.close()


def call_with_timeout(
    runner: Callable[[Path], tuple[str, str, int]], work: Path, seconds: int
) -> tuple[str, str, int]:
    """为注入的测试 runner 提供跨平台超时；默认 Agent 不走此函数的 Windows 分支。"""
    if os.name == "nt":
        # Python 线程不能安全地强制终止，因此仅用于单元测试注入的轻量 runner。
        # 真实 default_agent_runner 在 Windows 必须走上面的独立子进程，防止超时后继续改文件。
        result: list[tuple[str, str, int]] = []
        errors: list[BaseException] = []
        completed = threading.Event()

        def run_in_thread() -> None:
            try:
                result.append(runner(work))
            except BaseException as exc:  # 保留原异常，交由调用方转成 ERROR。
                errors.append(exc)
            finally:
                completed.set()

        thread = threading.Thread(target=run_in_thread, daemon=True)
        thread.start()
        if not completed.wait(seconds):
            raise AgentTimeout(f"Agent 执行超过 {seconds} 秒")
        if errors:
            raise errors[0]
        return result[0]

    # POSIX 保留原有 SIGALRM 实现；finally 恢复旧处理器并取消闹钟，避免影响后续任务。
    def handle_timeout(_signum, _frame):
        raise AgentTimeout(f"Agent 执行超过 {seconds} 秒")

    previous = signal.signal(signal.SIGALRM, handle_timeout)
    signal.alarm(seconds)
    try:
        return runner(work)
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


def run_one(
    task_dir: Path,
    config: dict,
    run_id: str,
    agent_runner: Callable[[Path], tuple[str, str, int]] = default_agent_runner,
    agent_timeout: int = AGENT_TIMEOUT,
) -> dict:
    # 每个任务使用独立副本，保护原题并避免任务之间互相污染。
    work = WORK_ROOT / run_id / task_dir.name
    shutil.copytree(task_dir, work)
    # manifest 保存的是文件名；隐藏测试实际位于统一的 grader_tests 目录。
    hidden_test = GRADER_TESTS / config["hidden_test"]
    # Agent 运行前建立快照，用于识别实际改动。
    before = file_hashes(work)
    started = time.time()

    # 先确认基线确实失败；已通过的题目不能被算作 Agent 修复成功。
    try:
        baseline = run_tests(work, hidden_test)
    except subprocess.TimeoutExpired:
        return {
            "task": task_dir.name,
            "status": "ERROR",
            "passed": False,
            "reason": "基线测试超时，无法确认任务是否有效",
            "seconds": round(time.time() - started, 1),
        }
    if baseline.returncode == 0:
        return {
            "task": task_dir.name,
            "status": "ERROR",
            "passed": False,
            "reason": "基线已经通过，任务没有可测量的失败",
            "baseline_tail": output_tail(baseline),
            "seconds": round(time.time() - started, 1),
        }

    # Agent 的口头答案不作为成功依据，最终以文件完整性和测试结果为准。
    answer = ""
    session_id = ""
    turns = 0
    agent_error = None
    agent_timed_out = False
    try:
        # Windows 上把真实 Agent 放到可终止子进程；注入 runner 仍用于离线单元测试。
        if os.name == "nt" and agent_runner is default_agent_runner:
            answer, session_id, turns = call_default_agent_with_timeout(work, agent_timeout)
        else:
            answer, session_id, turns = call_with_timeout(
                agent_runner, work, agent_timeout
            )
    except AgentTimeout as exc:
        agent_timed_out = True
        agent_error = str(exc)
    except Exception as exc:
        agent_error = f"{type(exc).__name__}: {exc}"

    # Agent 结束后再次快照；差异包含修改、删除和新增文件。
    after = file_hashes(work)
    modified = sorted(changed_files(before, after))
    editable = set(config["editable"])
    forbidden = sorted(set(modified) - editable)

    # 即使 Agent 报错也尝试复测，尽量保留可审计的最终证据。
    test_result = None
    test_timed_out = False
    try:
        test_result = run_tests(work, hidden_test)
    except subprocess.TimeoutExpired:
        test_timed_out = True

    # 越权修改优先级最高；否则依次处理超时、异常和测试结果。
    if forbidden:
        status = "TAMPERED"
        reason = "修改了清单以外的文件"
    elif agent_timed_out or test_timed_out:
        status = "TIMEOUT"
        reason = agent_error or "测试执行超时"
    elif agent_error:
        status = "ERROR"
        reason = agent_error
    elif test_result and test_result.returncode == 0:
        status = "PASSED"
        reason = "允许的源码修改通过了可见测试和独立测试"
    else:
        status = "FAILED"
        reason = "独立测试仍然失败"

    return {
        "task": task_dir.name,
        "status": status,
        "passed": status == "PASSED",
        "reason": reason,
        "editable": sorted(editable),
        "modified": modified,
        "forbidden_changes": forbidden,
        "turns": turns,
        "seconds": round(time.time() - started, 1),
        "session": session_id,
        "agent_error": agent_error,
        "baseline_tail": output_tail(baseline),
        "pytest_tail": output_tail(test_result) if test_result else "",
        "agent_answer": answer[:300],
        "work": str(work),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("tasks", nargs="*", help="任务编号，例如 03 07")
    parser.add_argument("--agent-timeout", type=int, default=AGENT_TIMEOUT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    # 不指定任务则跑全部；指定编号时，其余任务明确记为 NOT_RUN。

    selected = set(args.tasks)
    known_ids = {name.split("_", 1)[0] for name in manifest} # split("_", 1)表示最多只切一次

    # "01_cart_boundary".split("_", 1)
    # ["01", "cart_boundary"]


    unknown = selected - known_ids
    if unknown:
        raise SystemExit(f"未知任务编号：{', '.join(sorted(unknown))}")

    # 同一轮评测共享 run_id，便于关联工作副本和结果 JSON。
    run_id = uuid.uuid4().hex[:8]
    WORK_ROOT.mkdir(exist_ok=True)
    print(f"评测开始：run_id={run_id}\n")

    results = []
    for task_name, config in manifest.items():
        task_id = task_name.split("_", 1)[0]
        if selected and task_id not in selected:
            results.append(
                {"task": task_name, "status": "NOT_RUN", "passed": False}
            )
            continue
        print(f"[{task_name}] 运行中...", end=" ", flush=True)
        result = run_one(
            EVALSET / task_name,
            config,
            run_id,
            agent_timeout=args.agent_timeout,
        )
        results.append(result)
        print(f"{result['status']}  {result.get('turns', 0)} 轮 {result['seconds']}s")

    # attempted 排除 NOT_RUN，部分任务评测时分母不会错误地算成全部任务。
    passed = sum(result["status"] == "PASSED" for result in results)
    attempted = sum(result["status"] != "NOT_RUN" for result in results)
    print(f"\n{'任务':<24}{'状态':<12}{'轮数':<6}{'耗时'}")
    for result in results:
        seconds = f"{result.get('seconds', 0)}s" if "seconds" in result else "-"
        print(
            f"{result['task']:<24}{result['status']:<12}"
            f"{result.get('turns', 0):<6}{seconds}"
        )
    print(f"\n可信通过：{passed}/{attempted}")

    RESULTS_DIR.mkdir(exist_ok=True)
    output = RESULTS_DIR / f"{time.strftime('%Y%m%d-%H%M%S')}-{run_id}.json"
    # 结果以 UTF-8 JSON 持久化，保留状态、证据、工作目录和 Agent 摘要。
    output.write_text(
        json.dumps(
            {
                "run_id": run_id,
                "passed": passed,
                "attempted": attempted,
                "total": len(results),
                "results": results,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"结果已写入 {output}")


if __name__ == "__main__":
    main()
