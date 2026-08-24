def get_page(items, page, size):
    """按页取数据，page 从 0 开始，每页 size 条。"""
    start = page * size
    return items[start : start + size - 1]
