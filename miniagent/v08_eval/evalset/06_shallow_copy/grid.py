def make_grid(rows, cols):
    """创建 rows x cols 的二维网格，初始值全为 0，每行相互独立。"""
    return [[0] * cols] * rows

def set_cell(grid, r, c, value):
    grid[r][c] = value
