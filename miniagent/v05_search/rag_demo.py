"""最小 RAG 管线演示：切分 → 向量化 → 余弦召回，全程纯 Python。

说明：DeepSeek 没有 embedding 接口，这里用手写 TF-IDF 代替 embedding
模型来演示"向量检索"的机制——把文本变向量、算相似度、取 top-k，
它保留了切分、向量化、相似度和 top-k 召回这条核心骨架。生产系统
还会处理索引存储与更新、元数据、权限、重排和检索评测；TF-IDF
只有词频没有语义，本 demo 也会直接暴露换个说法就搜不到的短板。

用法：python rag_demo.py "你的问题" [语料目录]
"""

import math
import re
import sys
from collections import Counter
from pathlib import Path

CHUNK_SIZE = 400  # 每块约 400 字符


def tokenize(text: str) -> list[str]:
    """中文按单字切，英文按单词切。真实系统用专门的分词器。"""
    return re.findall(r"[a-zA-Z_]+|[一-鿿]", text.lower())


def split_chunks(corpus_dir: Path) -> list[dict]:
    """按段落聚合到约 CHUNK_SIZE 字符一块，并记住来源。"""
    chunks = []
    for path in sorted(corpus_dir.rglob("*.md")) + sorted(corpus_dir.rglob("*.py")):
        if any(part.startswith(".") for part in path.parts):
            continue
        paragraphs = path.read_text().split("\n\n")
        buffer = ""
        for para in paragraphs:
            if len(buffer) + len(para) > CHUNK_SIZE and buffer:
                chunks.append({"source": str(path), "text": buffer.strip()})
                buffer = ""
            buffer += para + "\n\n"
        if buffer.strip():
            chunks.append({"source": str(path), "text": buffer.strip()})
    return chunks


def build_vectors(chunks: list[dict]) -> tuple[list[dict], dict[str, float]]:
    """TF-IDF：词频 × 逆文档频率。生产系统里这一步换成调 embedding 模型。"""
    if not chunks:
        raise ValueError("语料目录里没有可检索的 Markdown 或 Python 文件")
    n = len(chunks)
    df = Counter()
    for chunk in chunks:
        df.update(set(tokenize(chunk["text"])))
    idf = {word: math.log((1 + n) / (1 + count)) + 1 for word, count in df.items()}
    for chunk in chunks:
        tf = Counter(tokenize(chunk["text"]))
        chunk["vector"] = {word: count * idf[word] for word, count in tf.items()}
    return chunks, idf


def cosine(a: dict, b: dict) -> float:
    dot = sum(a[w] * b[w] for w in a.keys() & b.keys())
    norm = math.sqrt(sum(v * v for v in a.values())) * math.sqrt(
        sum(v * v for v in b.values())
    )
    return dot / norm if norm else 0.0


def search(
    query: str,
    chunks: list[dict],
    idf: dict[str, float],
    top_k: int = 3,
    min_score: float = 0.05,
) -> list[tuple[float, dict]]:
    query_vector = {
        word: count * idf[word]
        for word, count in Counter(tokenize(query)).items()
        if word in idf
    }
    scored = [(cosine(query_vector, c["vector"]), c) for c in chunks]
    scored = [pair for pair in scored if pair[0] >= min_score]
    scored.sort(key=lambda pair: -pair[0])
    return scored[:top_k]


if __name__ == "__main__":
    query = sys.argv[1] if len(sys.argv) > 1 else "怎么让对话有记忆"
    corpus = (
        Path(sys.argv[2])
        if len(sys.argv) > 2
        else Path(__file__).parents[2] / "fixtures" / "rag_corpus"
    )

    chunks, idf = build_vectors(split_chunks(corpus))
    print(f"语料：{corpus}（{len(chunks)} 个 chunk）\n查询：{query}\n")
    results = search(query, chunks, idf)
    if not results:
        print("没有找到包含相同词语的内容。词法检索不理解同义表达。")
    for score, chunk in results:
        print(f"—— 相似度 {score:.3f} | 来源 {chunk['source']}")
        print(chunk["text"][:150].replace("\n", " ") + "…\n")
