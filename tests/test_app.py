import numpy as np
import biom

from biom_viewer import app


def make_table():
    # 3 observations (rows) x 4 samples (cols), mostly zero.
    data = np.array(
        [
            [0, 1, 0, 0],
            [2, 0, 0, 5],
            [0, 0, 0, 0],
        ]
    )
    return biom.Table(data, ["obs1", "obs2", "obs3"], ["s1", "s2", "s3", "s4"])


def test_meta_reports_shape_and_ids():
    app.TABLE = make_table()
    app.FILENAME = "fake.biom"
    m = app.meta()
    assert m["filename"] == "fake.biom"
    assert m["rows"] == 3
    assert m["cols"] == 4
    assert m["row_ids"] == ["obs1", "obs2", "obs3"]
    assert m["col_ids"] == ["s1", "s2", "s3", "s4"]


def test_data_window_returns_correct_dense_subset():
    app.TABLE = make_table()
    # full window
    assert app.data_window(0, 3, 0, 4) == [
        [0, 1, 0, 0],
        [2, 0, 0, 5],
        [0, 0, 0, 0],
    ]
    # a sub-window, never touching the rest of the (sparse) matrix
    assert app.data_window(1, 2, 1, 3) == [[0, 0]]


def test_data_window_clamps_out_of_range_bounds():
    app.TABLE = make_table()
    # r1/c1 past the table edge should clamp, not error
    assert app.data_window(2, 10, 0, 10) == [[0, 0, 0, 0]]
