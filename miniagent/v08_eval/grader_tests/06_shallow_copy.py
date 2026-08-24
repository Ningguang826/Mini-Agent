from grid import make_grid, set_cell


def test_rows_are_distinct_objects():
    grid = make_grid(2, 1)
    set_cell(grid, 1, 0, 9)
    assert grid == [[0], [9]]
