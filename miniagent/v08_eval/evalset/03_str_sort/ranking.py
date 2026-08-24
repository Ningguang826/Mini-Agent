def parse_and_rank(lines):
    """lines 是从文本文件读出的分数（字符串），返回从高到低的整数列表。"""
    return sorted(lines, reverse=True)
