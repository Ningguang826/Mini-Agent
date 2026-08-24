from __future__ import annotations

import pytest

from conftest import REPO, load_module


def test_query_uses_corpus_idf_and_filters_zero_hits():
    rag = load_module("miniagent/v05_search/rag_demo.py", "rag_demo")
    chunks, idf = rag.build_vectors(
        [
            {"source": "a", "text": "会话 可以 恢复"},
            {"source": "b", "text": "工具 调用 失败"},
        ]
    )
    results = rag.search("恢复会话", chunks, idf)
    assert results
    assert results[0][1]["source"] == "a"
    assert rag.search("完全无关xyz", chunks, idf) == []


def test_empty_corpus_has_clear_error():
    rag = load_module("miniagent/v05_search/rag_demo.py", "rag_empty")
    with pytest.raises(ValueError, match="没有可检索"):
        rag.build_vectors([])


def test_bundled_corpus_exists():
    assert list((REPO / "fixtures" / "rag_corpus").glob("*.md"))
