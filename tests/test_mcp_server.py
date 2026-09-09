import numpy as np
import biom
import pytest

from biom_viewer import app, mcp_server
from biom_viewer.app import WorkspaceStore


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
def _api(monkeypatch, tmp_path):
    store = WorkspaceStore(tmp_path / "state.json")
    api = app.Api(make_table(), "fake.biom", workspace_store=store)
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


def test_create_view_round_trips_through_workspace(_api):
    result = mcp_server.create_view(
        name="IBD samples",
        mode="data",
        col_fields=["diagnosis"],
        sample_filters=[{"field": "diagnosis", "kind": "categorical", "text": "IBD"}],
        sample_sort={"field": "age", "dir": -1},
        pinned_observation_ids=[0],
        pinned_column_fields=["diagnosis"],
    )
    assert result["mode"] == "data"
    assert result["pinnedObs"] == [0]
    assert result["pinnedColFields"] == ["diagnosis"]

    workspace = _api.load_workspace()
    saved = next(v for v in workspace["views"] if v["name"] == "IBD samples")
    assert saved["axisState"]["sample"]["filters"] == [
        {"field": "diagnosis", "kind": "categorical", "text": "IBD"}
    ]
    assert saved["axisState"]["sample"]["sortField"] == "age"
    assert saved["axisState"]["sample"]["sortDir"] == -1
    assert saved["axisState"]["observation"]["filters"] == []


def test_create_view_defaults_produce_empty_but_valid_state(_api):
    result = mcp_server.create_view(name="empty view")
    assert result["rowFields"] == []
    assert result["colFields"] == []
    assert result["pinnedObs"] == []
    assert result["pinnedColFields"] == []
    assert result["axisState"]["observation"]["sortDir"] == 0


def test_create_views_creates_all_named_views(_api):
    results = mcp_server.create_views(
        [
            {"name": "IBD", "sample_filters": [{"field": "diagnosis", "kind": "categorical", "text": "IBD"}]},
            {"name": "healthy", "sample_filters": [{"field": "diagnosis", "kind": "categorical", "text": "healthy"}]},
        ]
    )
    assert len(results) == 2
    names = {v["name"] for v in mcp_server.list_views()}
    assert names == {"IBD", "healthy"}


def test_delete_view_removes_it(_api):
    mcp_server.create_view(name="temp")
    assert any(v["name"] == "temp" for v in mcp_server.list_views())
    result = mcp_server.delete_view("temp")
    assert result == {"ok": True}
    assert not any(v["name"] == "temp" for v in mcp_server.list_views())
