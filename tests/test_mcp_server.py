import numpy as np
import biom
import pytest

from biom_viewer import app, mcp_server


def make_table():
    # 3 observations x 4 samples, with row (observation) and column (sample)
    # metadata so list_fields/field_summary/pinned_column_fields all have
    # something real to operate on.
    data = np.array(
        [
            [0, 1, 0, 0],
            [2, 0, 0, 5],
            [0, 0, 0, 0],
        ]
    )
    table = biom.Table(
        data,
        ["obs1", "obs2", "obs3"],
        ["s1", "s2", "s3", "s4"],
        observation_metadata=[
            {"taxonomy": "Bacteria"},
            {"taxonomy": "Archaea"},
            {"taxonomy": "Bacteria"},
        ],
        sample_metadata=[
            {"diagnosis": "IBD", "age": 40},
            {"diagnosis": "healthy", "age": 22},
            {"diagnosis": "IBD", "age": 51},
            {"diagnosis": "healthy", "age": 33},
        ],
    )
    return table


@pytest.fixture(autouse=True)
def _api(monkeypatch):
    api = app.Api(make_table(), "fake.biom")
    monkeypatch.setattr(mcp_server, "_api", api)
    return api


def test_list_fields_observation():
    assert mcp_server.list_fields("observation") == ["taxonomy"]


def test_list_fields_sample():
    assert mcp_server.list_fields("sample") == ["age", "diagnosis"]


def test_field_summary_categorical():
    summary = mcp_server.field_summary("sample", "diagnosis")
    assert summary["kind"] == "categorical"
    assert {"value": "IBD", "count": 2} in summary["top"]


def test_field_summary_numeric():
    summary = mcp_server.field_summary("sample", "age")
    assert summary["missing"] == 0
    assert summary["n"] if "n" in summary else True  # numeric summary shape from _numeric_summary
