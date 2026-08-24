"""MiniAgent v0.8 —— 带完整性检查的最小评测 runner。

用法：
    python run_eval.py            # 跑全部 10 个任务
    python run_eval.py 03 07      # 只跑指定编号，其余记为 NOT_RUN

runner 不信 Agent 的口头汇报，也不只看 pytest 退出码。它先确认任务基线
确实失败，再检查 Agent 是否只修改允许的源码，最后运行可见测试和独立测试。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Callable


HERE = Path(__file__).parent
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
    return hashlib.sha256(path.read_bytes()).hexdigest()


def file_hashes(root: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if any(part in IGNORED_PARTS for part in relative.parts):
            continue
        if path.name in IGNORED_NAMES or path.suffix == ".pyc":
            continue
        hashes[relative.as_posix()] = sha256(path)
    return hashes


def changed_files(before: dict[str, str], after: dict[str, str]) -> set[str]:
    paths = before.keys() | after.keys()
    return {path for path in paths if before.get(path) != after.get(path)}


def run_tests(work: Path, hidden_test: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(work) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", str(work), str(hidden_test)],
        cwd=work,
        env=env,
        capture_output=True,
        text=True,
        timeout=TEST_TIMEOUT,
    )


def output_tail(result: subprocess.CompletedProcess[str]) -> str:
    output = (result.stdout + result.stderr).strip().splitlines()
    return "\n".join(output[-8:])


def default_agent_runner(work: Path) -> tuple[str, str, int]:
    """延迟导入在线 Agent，让 runner 的离线单元测试不需要 API Key。"""
    sys.path.insert(0, str(HERE))
    from agent import Session, run_agent
    from tools import set_workspace

    set_workspace(work)
    config = json.loads(MANIFEST.read_text())[work.name]
    session = Session()
    answer = run_agent(
        TASK_PROMPT.format(work=work, editable=", ".join(config["editable"])),
        session,
        verbose=False,
    )
    turns = sum(1 for message in session.load() if message.get("role") == "assistant")
    return answer, session.id, turns


def call_with_timeout(
    runner: Callable[[Path], tuple[str, str, int]], work: Path, seconds: int
) -> tuple[str, str, int]:
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
    work = WORK_ROOT / run_id / task_dir.name
    shutil.copytree(task_dir, work)
    hidden_test = GRADER_TESTS / config["hidden_test"]
    before = file_hashes(work)
    started = time.time()

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

    answer = ""
    session_id = ""
    turns = 0
    agent_error = None
    agent_timed_out = False
    try:
        answer, session_id, turns = call_with_timeout(agent_runner, work, agent_timeout)
    except AgentTimeout as exc:
        agent_timed_out = True
        agent_error = str(exc)
    except Exception as exc:
        agent_error = f"{type(exc).__name__}: {exc}"

    after = file_hashes(work)
    modified = sorted(changed_files(before, after))
    editable = set(config["editable"])
    forbidden = sorted(set(modified) - editable)

    test_result = None
    test_timed_out = False
    try:
        test_result = run_tests(work, hidden_test)
    except subprocess.TimeoutExpired:
        test_timed_out = True

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
    manifest = json.loads(MANIFEST.read_text())
    selected = set(args.tasks)
    known_ids = {name.split("_", 1)[0] for name in manifest}
    unknown = selected - known_ids
    if unknown:
        raise SystemExit(f"未知任务编号：{', '.join(sorted(unknown))}")

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
        + "\n"
    )
    print(f"结果已写入 {output}")


if __name__ == "__main__":
    main()
