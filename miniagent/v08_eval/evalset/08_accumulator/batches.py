def batch_sums(batches):
    """batches: 列表的列表，返回每个子列表各自的和。"""
    sums = []
    total = 0
    for batch in batches:
        for x in batch:
            total += x
        sums.append(total)
    return sums
