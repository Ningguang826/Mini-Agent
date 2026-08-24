from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]


def load_module(relative: str, name: str):
    path = REPO / relative
    os.environ.setdefault("DEEPSEEK_API_KEY", "test-key")
    for local_name in ("tools", "mcp_client", "reviewer", "agent"):
        sys.modules.pop(local_name, None)
    sys.path.insert(0, str(path.parent))
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)
