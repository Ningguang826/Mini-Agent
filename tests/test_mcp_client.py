from __future__ import annotations

import sys
from pathlib import Path

import pytest

from conftest import load_module


@pytest.mark.parametrize(
    "relative",
    [
        "miniagent/v06_mcp/mcp_client.py",
        "miniagent/v07_review/mcp_client.py",
        "miniagent/v08_eval/mcp_client.py",
    ],
)
def test_mcp_server_uses_current_python_and_absolute_path(relative):
    client = load_module(relative, "client_" + relative.split("/")[1])
    assert client.SERVER.command == sys.executable
    server_path = Path(client.SERVER.args[0])
    assert server_path.is_absolute()
    assert server_path.is_file()
