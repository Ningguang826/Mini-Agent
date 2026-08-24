def count_words(words):
    """统计每个词出现的次数，返回 dict。"""
    counts = {}
    for w in words:
        counts[w] += 1
    return counts
