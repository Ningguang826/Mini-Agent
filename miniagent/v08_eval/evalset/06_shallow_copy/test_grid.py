from grid import make_grid, set_cell

def test_set_one_cell():
    g = make_grid(3, 3)
    set_cell(g, 0, 0, 5)
    assert g[0][0] == 5
    assert g[1][0] == 0  # 别的行不该跟着变
    assert g[2][0] == 0
