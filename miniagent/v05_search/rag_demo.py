"""最小 RAG 管线演示：切分 → 向量化 → 余弦召回，全程纯 Python。

说明：DeepSeek 没有 embedding 接口，这里用手写 TF-IDF 代替 embedding
模型来演示"向量检索"的机制——把文本变向量、算相似度、取 top-k，
它保留了切分、向量化、相似度和 top-k 召回这条核心骨架。生产系统
还会处理索引存储与更新、元数据、权限、重排和检索评测；TF-IDF
只有词频没有语义，本 demo 也会直接暴露换个说法就搜不到的短板。

用法：python rag_demo.py "你的问题" [语料目录]
"""
import os
import math
import re
import sys
from collections import Counter
from pathlib import Path

CHUNK_SIZE = 400  # 每块约 400 字符


from openai import OpenAI

def load_api_key() -> str:
    if key := os.environ.get("DEEPSEEK_API_KEY"):
        return key
    env_file = Path(__file__).resolve().parents[2] / ".env"
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if line.startswith("DEEPSEEK_API_KEY="):
            return line.split("=", 1)[1].strip()
    sys.exit("没有找到 DEEPSEEK_API_KEY")

client = OpenAI(api_key=load_api_key(), base_url="https://api.deepseek.com")
MODEL = "deepseek-v4-flash"






def tokenize(text: str) -> list[str]:
    """中文按单字切，英文按单词切。真实系统用专门的分词器。"""
    return re.findall(r"[a-zA-Z_]+|[一-鿿]", text.lower())


def split_chunks(corpus_dir: Path) -> list[dict]:
    """按段落聚合到约 CHUNK_SIZE 字符一块，并记住来源。"""
    chunks = []
    for path in sorted(corpus_dir.rglob("*.md")) + sorted(corpus_dir.rglob("*.py")):
        if any(part.startswith(".") for part in path.parts):
            continue
        paragraphs = path.read_text(encoding="utf-8").split("\n\n")
        buffer = ""
        for para in paragraphs:
            if len(buffer) + len(para) > CHUNK_SIZE and buffer:
                chunks.append({"source": str(path), "text": buffer.strip()})
                buffer = ""
            buffer += para + "\n\n"

        if buffer.strip(): #循环最后一段可能没满 CHUNK_SIZE 也要加进 chunks
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
    # cd F:\MiniAgent\miniagent
    # python miniagent\v05_search\rag_demo.py "你的查询"
    
    # 	查询	考察什么	预期
    # 1	会话恢复	原文原词	高分真命中
    # 2	怎么让对话有记忆	换了几个词（对话/记忆）	部分命中，分数下滑
    # 3	重启后怎么接着上次聊	全部同义替换（重启/接着/聊）	大概率 miss 或泛词蹭分
    # 4	session JSONL	英文词（语料里真实出现）	命中——词法检索不认语言只认字面
    # 5	这个程序怎么处理文件	泛词（程序/文件/处理，到处都有）	低分蹭分区，重点观察对象

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

    context_parts = []
    for i,(score, chunk) in enumerate(results,1):
        print(f"—— 相似度 {score:.3f} | 来源 {chunk['source']}")
        print(chunk["text"][:150].replace("\n", " ") + "…\n")

        part = f"[来源{i}] {chunk['source']}（相似度 {score:.3f}）\n{chunk['text']}"
        context_parts.append(part)

    context = "\n\n".join(context_parts)
    prompt = (
        "根据下面的检索资料回答问题，回答末尾标注用了哪些来源（如：来源：[来源1]）。"
        "资料不足以回答用户回答需要诚实说明界限，告知用户资料不足并不能够提供确切回答，不要编造。\n\n"
        f"问题：{query}\n\n资料：\n{context}"
    )
    
    answer = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
    ).choices[0].message.content
    print(f"\nRAG 回答：\n{answer}")

