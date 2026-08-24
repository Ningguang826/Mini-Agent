def add_item(item, bucket=[]):
    """把 item 加进 bucket 并返回。不传 bucket 时应该返回只含 item 的新列表。"""
    bucket.append(item)
    return bucket
