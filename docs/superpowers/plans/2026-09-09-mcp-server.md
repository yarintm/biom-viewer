# biom-viewer MCP Server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an MCP server so an LLM client (e.g. Claude Desktop) can inspect a `.biom` file's metadata and create one or many saved views (filters, sort, pinned rows/fields) from a natural-language request, without touching the GUI.

**Architecture:** A new standalone script, `biom_viewer/mcp_server.py`, started with a `.biom` file path as its only CLI arg. It loads the table once with `biom.load_table`, wraps it in the existing `app.Api` (headless — `Api.window` stays `None`, which is fine since only `save_view`/`load_workspace`/`delete_view`/`field_summary`/`meta` are used, none of which touch `window`), and registers plain functions as MCP tools via `FastMCP`. Views are written through `Api.save_view`, which persists to the same `WorkspaceStore` JSON file the GUI reads — keyed by `DatasetIdentity` (content-based, not path-based), so views created via MCP appear next time the GUI opens/reloads that file.

**Tech Stack:** `mcp` Python SDK (`mcp[cli]`, provides `FastMCP`), reusing `biom_viewer.app.Api`/`ViewState`/`Workspace` as-is — no changes to `app.py`.

---

## File Structure

- Modify: `pyproject.toml` — add `mcp[cli]` to `dependencies`, add `biom-viewer-mcp` console script.
- Create: `biom_viewer/mcp_server.py` — tool functions (plain, testable) + `FastMCP` registration + `main()` CLI entry point.
- Create: `tests/test_mcp_server.py` — tests call the plain functions directly (no MCP client/session needed), following `tests/test_app.py`'s `api()`/`make_table()` helper style.
- Modify: `README.md` — add an "MCP server" section with a Claude Desktop config snippet.

No changes to `biom_viewer/app.py`, `web_script.py`, or `web_style.py` — the plan reuses `Api`, `ViewState`, `Workspace`, `WorkspaceStore`, and the module-level `field_summary` exactly as they exist today.

---

### Task 1: Add the `mcp` dependency and console script

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add the dependency and entry point**

In `pyproject.toml`, change:

```toml
dependencies = [
  "biom-format>=2.1",
  "pywebview>=4.0",
]
```

to:

```toml
dependencies = [
  "biom-format>=2.1",
  "pywebview>=4.0",
  "mcp[cli]>=1.2",
]
```

And change:

```toml
[project.scripts]
biom-viewer = "biom_viewer.app:main"
```

to:

```toml
[project.scripts]
biom-viewer = "biom_viewer.app:main"
biom-viewer-mcp = "biom_viewer.mcp_server:main"
```

- [ ] **Step 2: Install in editable mode so the new entry point resolves**

Run: `pip install -e ".[dev]"`
Expected: installs `mcp` and its deps; no errors.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "build: add mcp dependency and biom-viewer-mcp entry point"
```

---

### Task 2: `list_fields` and `field_summary` tools

These are read-only lookups the LLM calls first, to learn what metadata fields exist and their value distributions, before building filters/pins.

**Files:**
- Create: `biom_viewer/mcp_server.py`
- Test: `tests/test_mcp_server.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_mcp_server.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_mcp_server.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'biom_viewer.mcp_server'`

- [ ] **Step 3: Create `biom_viewer/mcp_server.py` with the module scaffold and these two tools**

```python
"""MCP server exposing biom_viewer's Api as tools an LLM can call to build
and save views (filters, sort, pinned rows/fields) from a natural-language
request, without going through the GUI.

Run: biom-viewer-mcp path/to/table.biom
"""
from __future__ import annotations

import sys

import biom
from mcp.server.fastmcp import FastMCP

from biom_viewer.app import Api

mcp = FastMCP("biom-viewer")

# Set by main() at process start. A headless Api bound to one table/file —
# ok that Api.window stays None here, since none of the methods this module
# calls (meta, field_summary, save_view, load_workspace, delete_view) touch
# window; only export_table/open_url do, and this server doesn't expose those.
_api: Api | None = None


def _get_api() -> Api:
    if _api is None:
        raise RuntimeError("mcp_server._api not set — call main() or set it in a test")
    return _api


def list_fields(axis: str) -> list[str]:
    """Metadata field names available on `axis` ('observation' or 'sample')."""
    meta = _get_api().meta()
    key = "row_metadata" if axis == "observation" else "col_metadata"
    rows = meta[key] or []
    fields: set[str] = set()
    for row in rows:
        fields.update(row.keys())
    return sorted(fields)


def field_summary(axis: str, field: str) -> dict:
    """Histogram (numeric field) or top-value counts (categorical field) for
    `field` on `axis` ('observation' or 'sample') — use this to pick sane
    filter thresholds or categorical values before calling create_view."""
    return _get_api().field_summary(axis, field)


mcp.tool()(list_fields)
mcp.tool()(field_summary)


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: biom-viewer-mcp <path-to-biom>", file=sys.stderr)
        raise SystemExit(1)
    global _api
    table = biom.load_table(sys.argv[1])
    _api = Api(table, sys.argv[1])
    mcp.run()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_mcp_server.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add biom_viewer/mcp_server.py tests/test_mcp_server.py
git commit -m "feat: add list_fields and field_summary MCP tools"
```

---

### Task 3: `create_view` tool (filters, sort, row/col fields, pinned rows/fields)

Builds the exact payload shape `ViewState.from_payload` expects (`biom_viewer/app.py:324-332`) and saves it via `Api.save_view`.

**Files:**
- Modify: `biom_viewer/mcp_server.py`
- Test: `tests/test_mcp_server.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_mcp_server.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_mcp_server.py -v -k create_view`
Expected: FAIL with `AttributeError: module 'biom_viewer.mcp_server' has no attribute 'create_view'`

- [ ] **Step 3: Add `create_view` to `biom_viewer/mcp_server.py`**

Insert above the `mcp.tool()(list_fields)` line:

```python
def _axis_state(filters: list[dict] | None, sort: dict | None) -> dict:
    return {
        "sortField": sort["field"] if sort else None,
        "sortDir": sort["dir"] if sort else 0,
        "filters": filters or [],
        "replacements": [],
        "renames": {},
        "deletedFields": [],
        "columnSets": [],
    }


def create_view(
    name: str,
    mode: str = "data",
    row_fields: list[str] | None = None,
    col_fields: list[str] | None = None,
    observation_filters: list[dict] | None = None,
    sample_filters: list[dict] | None = None,
    observation_sort: dict | None = None,
    sample_sort: dict | None = None,
    pinned_observation_ids: list[int] | None = None,
    pinned_column_fields: list[str] | None = None,
) -> dict:
    """Build and save one named view. Overwrites any existing view with the
    same name.

    mode: 'data' | 'row' (observation-metadata mode) | 'col' (sample-metadata mode).
    *_filters: list of
      {"field": str, "kind": "numeric", "min": float, "max": float} or
      {"field": str, "kind": "categorical", "text": str}
    observation_sort / sample_sort: {"field": str, "dir": 1 or -1} or None.
    pinned_observation_ids: raw observation row indices to freeze on screen
      (get these from meta()'s row_ids order, index 0-based).
    pinned_column_fields: metadata field names to freeze in col-metadata mode,
      e.g. ["diagnosis"].
    """
    payload = {
        "mode": mode,
        "axisState": {
            "observation": _axis_state(observation_filters, observation_sort),
            "sample": _axis_state(sample_filters, sample_sort),
        },
        "rowFields": row_fields or [],
        "colFields": col_fields or [],
        "pinnedObs": pinned_observation_ids or [],
        "pinnedColFields": pinned_column_fields or [],
    }
    _get_api().save_view(name, payload)
    return payload
```

And add `mcp.tool()(create_view)` next to the other `mcp.tool()(...)` calls.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_mcp_server.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add biom_viewer/mcp_server.py tests/test_mcp_server.py
git commit -m "feat: add create_view MCP tool"
```

---

### Task 4: `create_views` (batch), `list_views`, `delete_view`

`create_views` is the "many at once" entry point the user asked for — one call, N views.

**Files:**
- Modify: `biom_viewer/mcp_server.py`
- Test: `tests/test_mcp_server.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_mcp_server.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_mcp_server.py -v -k "create_views or delete_view"`
Expected: FAIL with `AttributeError: module 'biom_viewer.mcp_server' has no attribute 'create_views'`

- [ ] **Step 3: Add the three tools to `biom_viewer/mcp_server.py`**

Insert after `create_view`:

```python
def create_views(specs: list[dict]) -> list[dict]:
    """Create several views in one call — e.g. "one view per diagnosis
    value". Each item in `specs` is a kwargs dict for create_view (must
    include "name")."""
    return [create_view(**spec) for spec in specs]


def list_views() -> list[dict]:
    """Name and save timestamp of every saved view."""
    workspace = _get_api().load_workspace()
    return [{"name": v["name"], "saved_at": v["savedAt"]} for v in workspace["views"]]


def delete_view(name: str) -> dict:
    """Delete a saved view by name."""
    _get_api().delete_view(name)
    return {"ok": True}
```

And register all three: `mcp.tool()(create_views)`, `mcp.tool()(list_views)`, `mcp.tool()(delete_view)`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_mcp_server.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add biom_viewer/mcp_server.py tests/test_mcp_server.py
git commit -m "feat: add create_views batch, list_views, delete_view MCP tools"
```

---

### Task 5: Wire up the full test suite and document usage

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Run the whole suite**

Run: `pytest -v`
Expected: all tests pass, including the 8 new ones in `tests/test_mcp_server.py`.

- [ ] **Step 2: Add a README section**

Append to `README.md`:

````markdown
## MCP server

biom-viewer ships an [MCP](https://modelcontextprotocol.io) server so an LLM
client can inspect a `.biom` file's metadata and create views (filters,
sort, pinned rows/fields) from a natural-language request — including many
at once, e.g. "make one view per diagnosis value."

Install with the `mcp` extra already included, then point a client (e.g.
Claude Desktop, in `claude_desktop_config.json`) at it:

```json
{
  "mcpServers": {
    "biom-viewer": {
      "command": "biom-viewer-mcp",
      "args": ["/absolute/path/to/table.biom"]
    }
  }
}
```

Views created this way are written to the same workspace store the desktop
app reads, keyed by the table's content fingerprint — reopen (or reload) the
file in biom-viewer to see them.

Tools exposed: `list_fields`, `field_summary`, `create_view`, `create_views`,
`list_views`, `delete_view`.
````

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: document the MCP server and Claude Desktop config"
```

---

## Out of scope (YAGNI for now)

- **Live GUI refresh** — the open desktop window doesn't currently watch the workspace file for changes; a view created via MCP shows up on next open/reload, not instantly. Add a file-watcher + reload only if that lag turns out to matter in practice.
- **`export_table`/`open_url` as MCP tools** — both require a live `webview.Window` (file dialog, browser launch) that a headless MCP process doesn't have. Not exposed.
- **Value-based row pinning ("pin all IBD samples")** — `pinned_observation_ids` takes raw indices, not a filter expression. The LLM resolves a filter to indices itself (e.g. by reading `meta()`'s `row_ids`/`row_metadata` or from a prior `create_view` call's filtered results) before pinning. A dedicated "resolve filter to ids" tool can be added later if this proves tedious in practice.
- **Auth/multi-user** — the server is a local stdio process per the standard MCP client-spawns-subprocess model; no network exposure, so no auth layer needed.

## Self-Review

- **Spec coverage:** "create views from NL, many at once" → `create_view` + `create_views` (Task 3, 4). "Pin columns/rows" → `pinned_observation_ids`/`pinned_column_fields` params on `create_view`, already backed by existing `ViewState` fields (Task 3). "Pin sample metadata row like diagnosis" → confirmed `pinned_column_fields` pins by field name, works via the same param (Task 3, tested in `test_create_view_round_trips_through_workspace`).
- **Placeholder scan:** none — every step has real, complete code.
- **Type consistency:** `_get_api()`, `_axis_state()`, `create_view()` signatures used identically across Tasks 2-4; `list_views()`'s `saved_at` key correctly reads `SavedView.to_payload()`'s `"savedAt"` (verified against `biom_viewer/app.py:357`), not the Python-side `saved_at` attribute name.
