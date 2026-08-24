from __future__ import annotations

import json
import time

from conftest import REPO, load_module


def setup_runner(tmp_path):
    runner = load_module("miniagent/v08_eval/run_eval.py", "eval_runner")
    runner.WORK_ROOT = tmp_path / "work"
    runner.WORK_ROOT.mkdir()
    manifest = json.loads(
        (REPO / "miniagent" / "v08_eval" / "evalset" / "manifest.json").read_text()
    )
    task = REPO / "miniagent" / "v08_eval" / "evalset" / "01_cart_boundary"
    return runner, task, manifest["01_cart_boundary"]


def test_eval_can_report_passed(tmp_path):
    runner, task, config = setup_runner(tmp_path)

    def fix(work):
        path = work / "cart.py"
        path.write_text(path.read_text().replace("total > 100", "total >= 100"))
        return "fixed", "fake", 1

    result = runner.run_one(task, config, "pass", agent_runner=fix)
    assert result["status"] == "PASSED"
    assert result["modified"] == ["cart.py"]


def test_eval_detects_test_tampering(tmp_path):
    runner, task, config = setup_runner(tmp_path)

    def tamper(work):
        (work / "test_cart.py").write_text("def test_fake():\n    assert True\n")
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
