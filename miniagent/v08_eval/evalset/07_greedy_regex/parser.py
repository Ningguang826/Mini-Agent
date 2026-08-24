import re

def first_tag(html):
    """返回字符串里第一个尖括号标签的名字，没有则返回 None。"""
    m = re.search(r"<(.+)>", html)
    return m.group(1) if m else None
