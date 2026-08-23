import numpy as np
import biom

from biom_viewer import app
from biom_viewer.app import _histogram, _numeric_summary


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


def test_data_window_idx_arbitrary_unsorted_indices():
    app.TABLE = make_table()
    # rows [2, 0] (reversed, non-contiguous), cols [3, 1]
    assert app.data_window_idx([2, 0], [3, 1]) == [
        [0, 0],
        [0, 1],
    ]


def test_data_window_idx_single_element():
    app.TABLE = make_table()
    assert app.data_window_idx([1], [3]) == [[5]]


def test_data_window_idx_full_axis_matches_data_window():
    app.TABLE = make_table()
    assert app.data_window_idx([0, 1, 2], [0, 1, 2, 3]) == app.data_window(0, 3, 0, 4)


def test_histogram_ten_equal_width_buckets():
    buckets = _histogram([1.0, 2.0, 3.0, 4.0, 5.0])
    assert len(buckets) == 10
    assert buckets[0]["lo"] == 1.0
    assert buckets[-1]["hi"] == 5.0
    assert sum(b["count"] for b in buckets) == 5


def test_histogram_single_value_returns_one_bucket():
    buckets = _histogram([3.0, 3.0, 3.0])
    assert buckets == [{"lo": 3.0, "hi": 3.0, "count": 3}]


def test_numeric_summary_basic_stats():
    s = _numeric_summary([2.0, 5.0], total=4)
    assert s["kind"] == "numeric"
    assert s["n"] == 4
    assert s["sum"] == 7.0
    assert s["min"] == 2.0
    assert s["max"] == 5.0
    assert s["mean"] == 3.5
    assert s["median"] == 3.5
    assert len(s["histogram"]) == 10
    assert sum(b["count"] for b in s["histogram"]) == 2


def test_numeric_summary_empty_values():
    s = _numeric_summary([], total=3)
    assert s == {
        "kind": "numeric", "n": 3, "sum": None, "min": None,
        "max": None, "mean": None, "median": None, "histogram": [],
    }


def test_row_summary_mixed_sparse_row():
    app.TABLE = make_table()
    s = app.row_summary(1)  # obs2: [2, 0, 0, 5]
    assert s["kind"] == "numeric"
    assert s["n"] == 4
    assert s["nonzero"] == 2
    assert s["sparsity"] == 50.0
    assert s["sum"] == 7.0
    assert s["min"] == 2.0
    assert s["max"] == 5.0
    assert s["mean"] == 3.5
    assert s["median"] == 3.5


def test_row_summary_all_zero_row():
    app.TABLE = make_table()
    s = app.row_summary(2)  # obs3: [0, 0, 0, 0]
    assert s["nonzero"] == 0
    assert s["sparsity"] == 100.0
    assert s["min"] is None
    assert s["mean"] is None
    assert s["histogram"] == []


def test_col_summary_single_nonzero_value():
    app.TABLE = make_table()
    s = app.col_summary(0)  # s1: [0, 2, 0]
    assert s["nonzero"] == 1
    assert s["sparsity"] == round(2 / 3 * 100, 1)
    assert s["min"] == s["max"] == 2.0


def make_table_with_sample_metadata():
    # 2 observations x 12 samples; abundance values irrelevant for these tests.
    data = np.zeros((2, 12))
    sample_ids = [f"s{i}" for i in range(12)]
    sample_metadata = []
    for i in range(12):
        ph = None if i == 0 else float(i)  # one missing, values 1..11 present
        sample_metadata.append({"ph": ph, "habitat": f"habitat{i}"})
    return biom.Table(data, ["o1", "o2"], sample_ids, sample_metadata=sample_metadata)


def test_field_summary_numeric_field_with_missing():
    app.TABLE = make_table_with_sample_metadata()
    s = app.field_summary("sample", "ph")
    assert s["kind"] == "numeric"
    assert s["n"] == 12
    assert s["missing"] == 1
    assert s["min"] == 1.0
    assert s["max"] == 11.0
    assert s["mean"] == 6.0
    assert s["median"] == 6.0
    assert sum(b["count"] for b in s["histogram"]) == 11


def test_field_summary_categorical_field_top10_and_other_count():
    app.TABLE = make_table_with_sample_metadata()
    s = app.field_summary("sample", "habitat")
    assert s["kind"] == "categorical"
    assert s["n"] == 12
    assert s["missing"] == 0
    assert s["distinct"] == 12
    assert len(s["top"]) == 10
    assert [t["value"] for t in s["top"]] == [f"habitat{i}" for i in range(10)]
    assert all(t["count"] == 1 for t in s["top"])
    assert s["other_count"] == 2


def test_field_summary_numeric_field_treats_nan_as_missing():
    # pandas-sourced sample metadata commonly uses NaN as its missing-value
    # marker for numeric columns; NaN must not poison sum/min/max/median.
    table = make_table_with_sample_metadata()
    table.metadata(axis="sample")[1]["ph"] = float("nan")  # was 1.0
    app.TABLE = table
    s = app.field_summary("sample", "ph")
    assert s["kind"] == "numeric"
    assert s["n"] == 12
    assert s["missing"] == 2  # the original None plus the new NaN
    assert s["min"] == 2.0
    assert s["max"] == 11.0
    assert sum(b["count"] for b in s["histogram"]) == 10


def test_field_summary_numeric_field_treats_na_string_as_missing():
    # Real-world exports (e.g. clinical metadata TSVs) commonly spell missing
    # numeric values as the literal string "NA" rather than leaving them
    # empty or using a float NaN. A handful of these shouldn't downgrade an
    # otherwise-numeric field to categorical.
    table = make_table_with_sample_metadata()
    meta = table.metadata(axis="sample")
    meta[1]["ph"] = "NA"  # was 1.0
    meta[2]["ph"] = "n/a"  # was 2.0
    app.TABLE = table
    s = app.field_summary("sample", "ph")
    assert s["kind"] == "numeric"
    assert s["n"] == 12
    assert s["missing"] == 3  # the original None plus "NA" and "n/a"
    assert s["min"] == 3.0
    assert s["max"] == 11.0
    assert sum(b["count"] for b in s["histogram"]) == 9


def test_build_export_table_applies_filter_sort_rename_delete_replace():
    app.TABLE = make_table_with_sample_metadata()
    spec = {
        "sample": {
            # keep s2..s5, reversed order
            "ids": ["s5", "s4", "s3", "s2"],
            "replacements": [{"field": "habitat", "find": "habitat", "replace": "H"}],
            "renames": {"ph": "pH"},
            "deletedFields": [],
        },
        "observation": {
            "ids": None,
            "replacements": [],
            "renames": {},
            "deletedFields": ["taxonomy"],  # field that doesn't exist -- must not error
        },
    }
    table = app.build_export_table(spec)
    assert list(table.ids(axis="sample")) == ["s5", "s4", "s3", "s2"]
    md = dict(zip(table.ids(axis="sample"), table.metadata(axis="sample")))
    assert md["s3"]["habitat"] == "H3"
    assert md["s3"]["pH"] == 3.0
    assert "ph" not in md["s3"]
    # observation axis untouched aside from the (no-op) delete
    assert list(table.ids(axis="observation")) == ["o1", "o2"]


def test_build_export_table_normalizes_inconsistent_metadata_keys(tmp_path):
    # Real-world biom files routinely have per-id metadata dicts that
    # disagree on which keys are present (an optional field missing
    # entirely for some ids, not just null) -- biom's own to_hdf5() rejects
    # that outright ("inconsistent metadata categories") rather than writing
    # a partial file. build_export_table must normalize so export always
    # produces something to_hdf5() (and thus write_biom_file) can write.
    data = np.zeros((3, 2))
    obs_md = [
        {"taxonomy": "A", "confidence": 0.9},
        {"taxonomy": "B", "confidence": 0.8},
        {"taxonomy": "C"},  # missing "confidence" entirely, not null
    ]
    app.TABLE = biom.Table(data, ["o1", "o2", "o3"], ["s1", "s2"], observation_metadata=obs_md)
    spec = {
        "observation": {"ids": None, "replacements": [], "renames": {"taxonomy": "name"}, "deletedFields": []},
        "sample": {"ids": None, "replacements": [], "renames": {}, "deletedFields": []},
    }
    table = app.build_export_table(spec)
    md = dict(zip(table.ids(axis="observation"), table.metadata(axis="observation")))
    assert md["o3"]["name"] == "C"
    assert md["o3"]["confidence"] is None  # filled in, not dropped

    out_path = str(tmp_path / "export.biom")
    app.write_biom_file(table, out_path)  # must not raise
    reloaded = biom.load_table(out_path)
    assert reloaded.shape == (3, 2)
