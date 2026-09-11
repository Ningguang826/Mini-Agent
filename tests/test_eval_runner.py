"""run_eval 评测器自身的元测试（meta-tests）。

运行 ``python -m pytest -q tests/test_eval_runner.py`` 时，pytest 测试的是
``run_eval.py`` 这台“裁判机”的规则，而不是直接测试某一道 evalset 题目的业务代码。
这里不会调用真实在线 Agent，也不会使用真实模型/API Key；测试通过向 ``run_one``
注入可控的伪 Agent，构造不同场景，验证 runner 是否能正确判定：

- 合法修改源码且公开/独立测试通过：``PASSED``；
- 修改 ``test_cart.py`` 等非白名单文件：``TAMPERED``；
- 没有修好、Agent 抛异常、Agent 超时：``FAILED`` / ``ERROR`` / ``TIMEOUT``；
- Windows 下默认 Agent 是否路由到可终止的 ``spawn`` 子进程，以及超时后是否回收。

因此，这个文件相当于“评测器的单元测试/回归测试”：它保证裁判规则本身没有
因为后续修改而失效；它不是 ``grader_tests/01_cart_boundary.py`` 那种业务题目测试。
"""

from __future__ import annotations

import json
import time

import pytest

from conftest import REPO, load_module


def setup_runner(tmp_path):
    runner = load_module("miniagent/v08_eval/run_eval.py", "eval_runner")
    runner.WORK_ROOT = tmp_path / "work"
    runner.WORK_ROOT.mkdir()
    manifest = json.loads(
        (REPO / "miniagent" / "v08_eval" / "evalset" / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    task = REPO / "miniagent" / "v08_eval" / "evalset" / "01_cart_boundary"
    return runner, task, manifest["01_cart_boundary"]


def test_eval_can_report_passed(tmp_path):
    runner, task, config = setup_runner(tmp_path)

    def fix(work):
        path = work / "cart.py"
        path.write_text(
            path.read_text(encoding="utf-8").replace("total > 100", "total >= 100"),
            encoding="utf-8",
        )
        return "fixed", "fake", 1

    result = runner.run_one(task, config, "pass", agent_runner=fix)
    assert result["status"] == "PASSED"
    assert result["modified"] == ["cart.py"]


def test_eval_detects_test_tampering(tmp_path):
    runner, task, config = setup_runner(tmp_path)

    def tamper(work):
        (work / "test_cart.py").write_text(
            "def test_fake():\n    assert True\n", encoding="utf-8"
        )
        return "done", "fake", 1

    result = runner.run_one(task, config, "tamper", agent_runner=tamper)
    assert result["status"] == "TAMPERED"
    assert result["forbidden_changes"] == ["test_cart.py"]


def test_eval_distinguishes_failed_error_and_timeout(tmp_path):
    runner, task, config = setup_runner(tmp_path)
    failed = runner.run_one(
        task, config, "failed", agent_runner=lambda work: ("no change", "fake", 1)
    )
    assert failed["status"] == "FAILED"

    def crash(_work):
        raise RuntimeError("boom")

    error = runner.run_one(task, config, "error", agent_runner=crash)
    assert error["status"] == "ERROR"

    def wait(_work):
        time.sleep(2)
        return "late", "fake", 1

    timeout = runner.run_one(
        task, config, "timeout", agent_runner=wait, agent_timeout=1
    )
    assert timeout["status"] == "TIMEOUT"


def test_windows_default_agent_uses_terminable_process(tmp_path, monkeypatch):
    """Windows 的真实默认 Agent 必须走子进程，而不是不能安全停止的线程。"""
    runner, task, config = setup_runner(tmp_path)
    calls = []

    def fake_process_runner(work, seconds):
        calls.append((work, seconds))
        path = work / "cart.py"
        path.write_text(
            path.read_text(encoding="utf-8").replace("total > 100", "total >= 100"),
            encoding="utf-8",
        )
        return "fixed", "fake-process", 1

    monkeypatch.setattr(runner, "call_default_agent_with_timeout", fake_process_runner)
    monkeypatch.setattr(runner.os, "name", "nt")

    result = runner.run_one(task, config, "windows-default", agent_timeout=7)

    assert result["status"] == "PASSED"
    assert calls == [(runner.WORK_ROOT / "windows-default" / task.name, 7)]


def test_windows_process_timeout_terminates_child(tmp_path, monkeypatch):
    """子进程超过时限时，父进程必须 terminate，避免后台继续修改工作目录。"""
    runner, _task, _config = setup_runner(tmp_path)
    calls = []

    class FakeQueue:
        def close(self):
            calls.append("queue.close")

        def join_thread(self):
            calls.append("queue.join_thread")

    class FakeProcess:
        pid = 123

        def __init__(self, target, args):
            calls.append(("process", target, args))
            self.alive = True

        def start(self):
            calls.append("start")

        def join(self, seconds=None):
            calls.append(("join", seconds))

        def is_alive(self):
            return self.alive

        def terminate(self):
            calls.append("terminate")
            self.alive = False

        def close(self):
            calls.append("process.close")

    class FakeContext:
        def Queue(self):
            return FakeQueue()

        def Process(self, *, target, args):
            return FakeProcess(target, args)

    def fake_get_context(method):
        calls.append(("get_context", method))
        return FakeContext()

    monkeypatch.setattr(runner.multiprocessing, "get_context", fake_get_context)

    with pytest.raises(runner.AgentTimeout, match="超过 3 秒"):
        runner.call_default_agent_with_timeout(tmp_path / "work", 3)

    assert ("get_context", "spawn") in calls
    assert "terminate" in calls
    assert "process.close" in calls
