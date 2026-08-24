from __future__ import annotations

from conftest import load_module


def test_reviewer_has_no_arbitrary_shell_and_verdict_is_strict():
    reviewer = load_module("miniagent/v07_review/reviewer.py", "reviewer_protocol")
    assert reviewer.REVIEW_TOOL_NAMES == {"read_file", "grep_code", "run_tests"}
    assert reviewer.verdict_status("APPROVE\n测试通过") == "APPROVE"
    assert reviewer.verdict_status("REJECT\n存在问题") == "REJECT"
    assert reviewer.verdict_status("**APPROVE**") == "ERROR"
    assert reviewer.verdict_status("APPROVED") == "ERROR"
