def is_leap(year):
    """闰年判定：能被 4 整除且不能被 100 整除，或能被 400 整除。"""
    return year % 4 == 0
