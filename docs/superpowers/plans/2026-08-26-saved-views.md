# Saved Views Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist filter/sort/pin/mode state per `.biom` file (auto-restore on reopen) and let users save/switch/rename/delete named "views" of that state, all from inside the app.

**Architecture:** A small Python domain model (`ViewState`, `SavedView`, `Workspace`, `DatasetIdentity`, `WorkspaceStore`) added to `biom_viewer/app.py`, persisting one JSON file in app support keyed by the dataset's `table_id` (or a content fingerprint). Five new methods on `Api` expose it to the frontend. The frontend gains a `captureViewState()`/`applyViewState()` pair (a superset of the existing undo `snapshotState()`/`restoreState()`, also carrying `mode` and both pin sets), a debounced autosave hooked into the existing `recordHistory()` choke point, and a toolbar "Views" popover for save/switch/rename/delete.

**Tech Stack:** Python 3.9+ stdlib only (`dataclasses`, `json`, `hashlib`, `pathlib`, `datetime`) — no new dependency. Vanilla JS in the existing single-file `PAGE` template, matching the app's existing popover/chip idioms.

**Spec:** `docs/superpowers/specs/2026-08-26-saved-views-design.md`

---

## Task 1: Python value objects — `ViewState`, `SavedView`, `Workspace`

**Files:**
- Modify: `biom_viewer/app.py` (new imports; new classes before `class Api:` at line 267)
- Test: `tests/test_app.py`

These are pure in-memory data types — no file I/O yet. TDD from here: tests first.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_app.py` (append at end of file):

```python
from biom_viewer.app import SavedView, ViewState, ViewNameTakenError, Workspace


def make_view_state(mode="data"):
    return ViewState(
        mode=mode,
        axis_state={"observation": {"sortField": None, "sortDir": 0, "filters": [], "replacements": [], "renames": {}, "deletedFields": []}},
        row_fields=["age"],
        col_fields=["site"],
        pinned_observations=[1, 2],
        pinned_column_fields=["site"],
    )


def test_view_state_round_trips_through_payload():
    state = make_view_state()

    payload = state.to_payload()
    restored = ViewState.from_payload(payload)

    assert restored == state


def test_view_state_payload_uses_camel_case_keys():
    payload = make_view_state().to_payload()

    assert set(payload) == {"mode", "axisState", "rowFields", "colFields", "pinnedObs", "pinnedColFields"}


def test_saved_view_round_trips_through_payload():
    view = SavedView(name="High abundance", state=make_view_state(), saved_at="2026-08-26T10:00:00+00:00")

    payload = view.to_payload()
    restored = SavedView.from_payload(payload)

    assert restored == view
    assert payload["name"] == "High abundance"
    assert payload["savedAt"] == "2026-08-26T10:00:00+00:00"


def test_workspace_upsert_view_appends_new_name():
    workspace = Workspace.empty()

    workspace.upsert_view(SavedView(name="A", state=make_view_state(), saved_at="t"))

    assert [v.name for v in workspace.views] == ["A"]


def test_workspace_upsert_view_replaces_existing_name():
    workspace = Workspace.empty()
    workspace.upsert_view(SavedView(name="A", state=make_view_state("data"), saved_at="t1"))

    workspace.upsert_view(SavedView(name="A", state=make_view_state("row"), saved_at="t2"))

    assert len(workspace.views) == 1
    assert workspace.views[0].saved_at == "t2"


def test_workspace_delete_view_removes_matching_name():
    workspace = Workspace.empty()
    workspace.upsert_view(SavedView(name="A", state=make_view_state(), saved_at="t"))

    workspace.delete_view("A")

    assert workspace.views == []


def test_workspace_delete_view_missing_name_is_noop():
    workspace = Workspace.empty()

    workspace.delete_view("does-not-exist")

    assert workspace.views == []


def test_workspace_rename_view_renames_in_place():
    workspace = Workspace.empty()
    workspace.upsert_view(SavedView(name="A", state=make_view_state(), saved_at="t"))

    workspace.rename_view("A", "B")

    assert [v.name for v in workspace.views] == ["B"]


def test_workspace_rename_view_onto_taken_name_raises_and_leaves_both_untouched():
    workspace = Workspace.empty()
    workspace.upsert_view(SavedView(name="A", state=make_view_state(), saved_at="t"))
    workspace.upsert_view(SavedView(name="B", state=make_view_state(), saved_at="t"))

    with pytest.raises(ViewNameTakenError):
        workspace.rename_view("A", "B")

    assert [v.name for v in workspace.views] == ["A", "B"]


def test_workspace_find_view_returns_none_when_missing():
    workspace = Workspace.empty()

    result = workspace.find_view("nope")

    assert result is None


def test_workspace_round_trips_through_payload():
    workspace = Workspace(current=make_view_state(), views=[SavedView(name="A", state=make_view_state(), saved_at="t")])

    restored = Workspace.from_payload(workspace.to_payload())

    assert restored == workspace


def test_workspace_from_payload_handles_no_current():
    restored = Workspace.from_payload({"current": None, "views": []})

    assert restored.current is None
    assert restored.views == []
```

Add `import pytest` to the top of `tests/test_app.py` if it isn't already imported (check first — it currently isn't).

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_app.py -k "view_state or saved_view or workspace" -v`
Expected: FAIL with `ImportError: cannot import name 'ViewState' from 'biom_viewer.app'` (or similar) — none of these types exist yet.

- [ ] **Step 3: Add imports**

In `biom_viewer/app.py`, replace the top of the file:

```python
#!/usr/bin/env python3
"""Lazy-loading BIOM viewer: native window (pywebview) + biom-format, sparse-window slicing, canvas grid UI."""
import math
import os
import socket
import sys
import threading
import webbrowser
from collections import Counter

import biom
import numpy as np
import webview
from webview.menu import Menu, MenuAction, MenuSeparator
```

with:

```python
#!/usr/bin/env python3
"""Lazy-loading BIOM viewer: native window (pywebview) + biom-format, sparse-window slicing, canvas grid UI."""
from __future__ import annotations

import hashlib
import json
import math
import os
import socket
import sys
import threading
import webbrowser
from collections import Counter
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

import biom
import numpy as np
import webview
from webview.menu import Menu, MenuAction, MenuSeparator
```

- [ ] **Step 4: Add the value object classes**

In `biom_viewer/app.py`, find this existing code (just before `class Api:`):

```python
def write_biom_file(table, path):
    # Write to a sibling temp file and rename into place only on success --
    # to_hdf5() is not transactional, so a mid-write failure (see
    # build_export_table's docstring) must never leave a truncated file
    # sitting at the destination the user picked.
    tmp_path = path + ".tmp"
    try:
        with biom.util.biom_open(tmp_path, "w") as f:
            table.to_hdf5(f, "biom-viewer export")
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


class Api:
```

Insert the new classes between them:

```python
def write_biom_file(table, path):
    # Write to a sibling temp file and rename into place only on success --
    # to_hdf5() is not transactional, so a mid-write failure (see
    # build_export_table's docstring) must never leave a truncated file
    # sitting at the destination the user picked.
    tmp_path = path + ".tmp"
    try:
        with biom.util.biom_open(tmp_path, "w") as f:
            table.to_hdf5(f, "biom-viewer export")
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


class ViewNameTakenError(Exception):
    """Raised by Workspace.rename_view when the new name already has a saved view."""


@dataclass(frozen=True)
class ViewState:
    """One snapshot of on-screen state: mode, axis state, field lists, and both pin sets."""

    mode: str
    axis_state: dict
    row_fields: list[str]
    col_fields: list[str]
    pinned_observations: list[int]
    pinned_column_fields: list[str]

    @classmethod
    def from_payload(cls, payload: dict) -> "ViewState":
        return cls(
            mode=payload["mode"],
            axis_state=payload["axisState"],
            row_fields=payload["rowFields"],
            col_fields=payload["colFields"],
            pinned_observations=payload["pinnedObs"],
            pinned_column_fields=payload["pinnedColFields"],
        )

    def to_payload(self) -> dict:
        return {
            "mode": self.mode,
            "axisState": self.axis_state,
            "rowFields": self.row_fields,
            "colFields": self.col_fields,
            "pinnedObs": self.pinned_observations,
            "pinnedColFields": self.pinned_column_fields,
        }


@dataclass(frozen=True)
class SavedView:
    """A named, timestamped ViewState the user explicitly saved."""

    name: str
    state: ViewState
    saved_at: str

    @classmethod
    def from_payload(cls, payload: dict) -> "SavedView":
        return cls(name=payload["name"], state=ViewState.from_payload(payload), saved_at=payload["savedAt"])

    def to_payload(self) -> dict:
        return {**self.state.to_payload(), "name": self.name, "savedAt": self.saved_at}


@dataclass
class Workspace:
    """Everything persisted for one dataset identity: the live 'current' state plus named saves."""

    current: ViewState | None
    views: list[SavedView]

    @classmethod
    def empty(cls) -> "Workspace":
        return cls(current=None, views=[])

    @classmethod
    def from_payload(cls, payload: dict) -> "Workspace":
        current_payload = payload.get("current")
        current = ViewState.from_payload(current_payload) if current_payload else None
        views = [SavedView.from_payload(v) for v in payload.get("views", [])]
        return cls(current=current, views=views)

    def to_payload(self) -> dict:
        return {
            "current": self.current.to_payload() if self.current else None,
            "views": [v.to_payload() for v in self.views],
        }

    def upsert_view(self, view: SavedView) -> None:
        self.views = [v for v in self.views if v.name != view.name]
        self.views.append(view)

    def delete_view(self, name: str) -> None:
        self.views = [v for v in self.views if v.name != name]

    def rename_view(self, old_name: str, new_name: str) -> None:
        if self.find_view(new_name) is not None:
            raise ViewNameTakenError(new_name)
        self.views = [replace(v, name=new_name) if v.name == old_name else v for v in self.views]

    def find_view(self, name: str) -> SavedView | None:
        return next((v for v in self.views if v.name == name), None)


class Api:
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_app.py -k "view_state or saved_view or workspace" -v`
Expected: PASS (12 tests)

- [ ] **Step 6: Commit**

```bash
git add biom_viewer/app.py tests/test_app.py
git commit -m "Add ViewState/SavedView/Workspace value objects for saved views"
```

---

## Task 2: `DatasetIdentity` and `WorkspaceStore`

**Files:**
- Modify: `biom_viewer/app.py` (new classes, right after `Workspace`, still before `class Api:`)
- Test: `tests/test_app.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_app.py`:

```python
from biom_viewer.app import DatasetIdentity, WorkspaceStore


def test_dataset_identity_uses_table_id_when_present():
    table = make_table()
    table.table_id = "my-table-id"

    identity = DatasetIdentity.from_table(table)

    assert str(identity) == "my-table-id"


def test_dataset_identity_falls_back_to_fingerprint_when_table_id_missing():
    table = make_table()
    table.table_id = None

    identity = DatasetIdentity.from_table(table)

    assert str(identity) != ""
    assert str(identity) != "None"


def test_dataset_identity_fingerprint_is_stable_for_identical_tables():
    table_a = make_table()
    table_a.table_id = None
    table_b = make_table()
    table_b.table_id = None

    assert str(DatasetIdentity.from_table(table_a)) == str(DatasetIdentity.from_table(table_b))


def test_dataset_identity_fingerprint_differs_for_different_shapes():
    small = make_table()
    small.table_id = None
    data = np.array([[0, 1], [2, 0]])
    different_shape = biom.Table(data, ["obsA", "obsB"], ["s1", "s2"])
    different_shape.table_id = None

    assert str(DatasetIdentity.from_table(small)) != str(DatasetIdentity.from_table(different_shape))


def test_workspace_store_round_trips_save_and_load(tmp_path):
    store = WorkspaceStore(tmp_path / "state.json")
    identity = DatasetIdentity("dataset-1")
    workspace = Workspace(current=make_view_state(), views=[SavedView(name="A", state=make_view_state(), saved_at="t")])

    store.save_workspace(identity, workspace)
    loaded = store.load_workspace(identity)

    assert loaded == workspace


def test_workspace_store_load_missing_file_returns_empty_workspace(tmp_path):
    store = WorkspaceStore(tmp_path / "does-not-exist.json")

    loaded = store.load_workspace(DatasetIdentity("dataset-1"))

    assert loaded == Workspace.empty()


def test_workspace_store_load_corrupt_file_returns_empty_workspace(tmp_path):
    store_path = tmp_path / "state.json"
    store_path.write_text("not valid json{{{")
    store = WorkspaceStore(store_path)

    loaded = store.load_workspace(DatasetIdentity("dataset-1"))

    assert loaded == Workspace.empty()


def test_workspace_store_keeps_other_identities_untouched(tmp_path):
    store = WorkspaceStore(tmp_path / "state.json")
    store.save_workspace(DatasetIdentity("dataset-1"), Workspace(current=make_view_state("data"), views=[]))

    store.save_workspace(DatasetIdentity("dataset-2"), Workspace(current=make_view_state("row"), views=[]))

    assert store.load_workspace(DatasetIdentity("dataset-1")).current.mode == "data"
    assert store.load_workspace(DatasetIdentity("dataset-2")).current.mode == "row"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_app.py -k "dataset_identity or workspace_store" -v`
Expected: FAIL with `ImportError: cannot import name 'DatasetIdentity'`.

- [ ] **Step 3: Implement `DatasetIdentity` and `WorkspaceStore`**

In `biom_viewer/app.py`, insert right after the `Workspace` class (still before `class Api:`):

```python
def _id_edges(ids, count=5):
    return list(ids[:count]) + list(ids[-count:])


class DatasetIdentity:
    """The table_id-or-fingerprint key a Workspace is stored under."""

    def __init__(self, key: str) -> None:
        self.key = key

    @classmethod
    def from_table(cls, table) -> "DatasetIdentity":
        if table.table_id:
            return cls(table.table_id)
        return cls(cls._fingerprint(table))

    @staticmethod
    def _fingerprint(table) -> str:
        observation_edges = _id_edges(table.ids(axis="observation"))
        sample_edges = _id_edges(table.ids(axis="sample"))
        raw = f"{table.shape}|{observation_edges}|{sample_edges}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

    def __str__(self) -> str:
        return self.key


class WorkspaceStore:
    """Owns all read/write access to the app-support JSON file. Nothing else touches it."""

    def __init__(self, store_path: Path) -> None:
        self._store_path = store_path
        self._lock = threading.Lock()

    @classmethod
    def default(cls) -> "WorkspaceStore":
        support_dir = Path.home() / "Library" / "Application Support" / "BiomViewer"
        return cls(support_dir / "state.json")

    def load_workspace(self, identity: DatasetIdentity) -> Workspace:
        document = self._read_document()
        payload = document.get(str(identity))
        return Workspace.from_payload(payload) if payload else Workspace.empty()

    def save_workspace(self, identity: DatasetIdentity, workspace: Workspace) -> None:
        with self._lock:
            document = self._read_document()
            document[str(identity)] = workspace.to_payload()
            self._write_document(document)

    def _read_document(self) -> dict:
        try:
            return json.loads(self._store_path.read_text())
        except (OSError, ValueError):
            return {}

    def _write_document(self, document: dict) -> None:
        try:
            self._store_path.parent.mkdir(parents=True, exist_ok=True)
            self._store_path.write_text(json.dumps(document))
        except OSError:
            pass
```

Note: `table.ids(axis="observation")` returns a numpy array — slicing (`[:count]`/`[-count:]`) and `list(...)` both work directly on it, same as the existing `_id_edges` usage pattern needs no extra conversion.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_app.py -k "dataset_identity or workspace_store" -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add biom_viewer/app.py tests/test_app.py
git commit -m "Add DatasetIdentity and WorkspaceStore for saved-views persistence"
```

---

## Task 3: Wire persistence into `Api`

**Files:**
- Modify: `biom_viewer/app.py:275-280` (`Api.__init__`) and after `field_summary` (new methods)
- Test: `tests/test_app.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_app.py`:

```python
def api_with_store(table, tmp_path, filename="fake.biom"):
    store = WorkspaceStore(tmp_path / "state.json")
    return app.Api(table, filename, workspace_store=store)


def test_api_load_workspace_starts_empty(tmp_path):
    a = api_with_store(make_table(), tmp_path)

    workspace = a.load_workspace()

    assert workspace == {"current": None, "views": []}


def test_api_save_current_then_load_workspace_returns_it(tmp_path):
    a = api_with_store(make_table(), tmp_path)
    payload = make_view_state().to_payload()

    a.save_current(payload)
    workspace = a.load_workspace()

    assert workspace["current"] == payload


def test_api_save_view_then_load_workspace_lists_it(tmp_path):
    a = api_with_store(make_table(), tmp_path)
    payload = make_view_state().to_payload()

    a.save_view("High abundance", payload)
    workspace = a.load_workspace()

    assert len(workspace["views"]) == 1
    assert workspace["views"][0]["name"] == "High abundance"


def test_api_delete_view_removes_it(tmp_path):
    a = api_with_store(make_table(), tmp_path)
    a.save_view("A", make_view_state().to_payload())

    a.delete_view("A")

    assert a.load_workspace()["views"] == []


def test_api_rename_view_renames_it(tmp_path):
    a = api_with_store(make_table(), tmp_path)
    a.save_view("A", make_view_state().to_payload())

    result = a.rename_view("A", "B")

    assert result == {"ok": True}
    assert [v["name"] for v in a.load_workspace()["views"]] == ["B"]


def test_api_rename_view_onto_taken_name_returns_not_ok(tmp_path):
    a = api_with_store(make_table(), tmp_path)
    a.save_view("A", make_view_state().to_payload())
    a.save_view("B", make_view_state().to_payload())

    result = a.rename_view("A", "B")

    assert result == {"ok": False}
    assert [v["name"] for v in a.load_workspace()["views"]] == ["A", "B"]


def test_api_two_instances_same_table_id_share_a_workspace(tmp_path):
    table = make_table()
    table.table_id = "shared-id"
    store = WorkspaceStore(tmp_path / "state.json")
    first = app.Api(table, "fake.biom", workspace_store=store)
    second = app.Api(table, "fake.biom", workspace_store=store)

    first.save_view("A", make_view_state().to_payload())

    assert [v["name"] for v in second.load_workspace()["views"]] == ["A"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_app.py -k "api_load_workspace or api_save_current or api_save_view or api_delete_view or api_rename_view or api_two_instances" -v`
Expected: FAIL with `TypeError: Api.__init__() got an unexpected keyword argument 'workspace_store'`.

- [ ] **Step 3: Update `Api.__init__`**

In `biom_viewer/app.py`, replace:

```python
    def __init__(self, table, filename):
        self._table = table
        self._filename = filename
        self.window = None  # set by open_window() once create_window() returns
        self._csc_matrix = None
```

with:

```python
    def __init__(self, table, filename, workspace_store: WorkspaceStore | None = None):
        self._table = table
        self._filename = filename
        self.window = None  # set by open_window() once create_window() returns
        self._csc_matrix = None
        self._workspace_store = workspace_store or WorkspaceStore.default()
        self._identity = DatasetIdentity.from_table(table)
```

- [ ] **Step 4: Add the new `Api` methods**

In `biom_viewer/app.py`, find:

```python
    def field_summary(self, axis, field, idxs=None):
        return field_summary(self._table, axis, field, idxs)

    def open_url(self, url):
```

Replace with:

```python
    def field_summary(self, axis, field, idxs=None):
        return field_summary(self._table, axis, field, idxs)

    def load_workspace(self) -> dict:
        return self._workspace_store.load_workspace(self._identity).to_payload()

    def save_current(self, state: dict) -> None:
        workspace = self._workspace_store.load_workspace(self._identity)
        workspace.current = ViewState.from_payload(state)
        self._workspace_store.save_workspace(self._identity, workspace)

    def save_view(self, name: str, state: dict) -> None:
        workspace = self._workspace_store.load_workspace(self._identity)
        saved_at = datetime.now(timezone.utc).isoformat()
        workspace.upsert_view(SavedView(name=name, state=ViewState.from_payload(state), saved_at=saved_at))
        self._workspace_store.save_workspace(self._identity, workspace)

    def delete_view(self, name: str) -> None:
        workspace = self._workspace_store.load_workspace(self._identity)
        workspace.delete_view(name)
        self._workspace_store.save_workspace(self._identity, workspace)

    def rename_view(self, old_name: str, new_name: str) -> dict:
        workspace = self._workspace_store.load_workspace(self._identity)
        try:
            workspace.rename_view(old_name, new_name)
        except ViewNameTakenError:
            return {"ok": False}
        self._workspace_store.save_workspace(self._identity, workspace)
        return {"ok": True}

    def open_url(self, url):
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_app.py -v`
Expected: PASS, full suite (existing tests + all new ones), no regressions.

- [ ] **Step 6: Commit**

```bash
git add biom_viewer/app.py tests/test_app.py
git commit -m "Expose saved-views persistence through the Api class"
```

---

## Task 4: Wire the new API methods into the dev server

**Files:**
- Modify: `scripts/dev_server.py`

Manual-testing only — no automated test (this file is explicitly "not part of the shipped app", see its own docstring). Also points the dev server at a throwaway temp store instead of the real `~/Library/Application Support/BiomViewer/state.json`, so manual testing never pollutes real saved views.

- [ ] **Step 1: Add the new endpoints to the SHIM and API dict, and isolate the store**

In `scripts/dev_server.py`, replace:

```python
import json
import os
import sys
import tempfile
from http.server import BaseHTTPRequestHandler, HTTPServer

import biom

from biom_viewer import app as bv
```

with:

```python
import json
import os
import sys
import tempfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import biom

from biom_viewer import app as bv
```

Then replace:

```python
SHIM = """
<script>
if(!window.pywebview){
  const post = (path, body) => fetch(path, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body||{})}).then(r=>r.json());
  window.pywebview = { api: {
    meta: () => post('/api/meta'),
    data_window: (r0,r1,c0,c1) => post('/api/data_window', {r0,r1,c0,c1}),
    data_window_idx: (row_idxs, col_idxs) => post('/api/data_window_idx', {row_idxs, col_idxs}),
    row_summary: (r) => post('/api/row_summary', {r}),
    col_summary: (c) => post('/api/col_summary', {c}),
    field_summary: (axis, field) => post('/api/field_summary', {axis, field}),
    export_table: (spec) => post('/api/export_table', {spec}),
    open_url: (url) => post('/api/open_url', {url}),
  }};
  window.dispatchEvent(new Event('pywebviewready'));
}
</script>
"""

API = {
    "/api/meta": lambda body: API_INSTANCE.meta(),
    "/api/data_window": lambda body: API_INSTANCE.data_window(body["r0"], body["r1"], body["c0"], body["c1"]),
    "/api/data_window_idx": lambda body: API_INSTANCE.data_window_idx(body["row_idxs"], body["col_idxs"]),
    "/api/row_summary": lambda body: API_INSTANCE.row_summary(body["r"]),
    "/api/col_summary": lambda body: API_INSTANCE.col_summary(body["c"]),
    "/api/field_summary": lambda body: API_INSTANCE.field_summary(body["axis"], body["field"]),
    "/api/export_table": lambda body: _dev_export(body["spec"]),
    "/api/open_url": lambda body: API_INSTANCE.open_url(body["url"]) or {"ok": True},
}
```

with:

```python
SHIM = """
<script>
if(!window.pywebview){
  const post = (path, body) => fetch(path, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body||{})}).then(r=>r.json());
  window.pywebview = { api: {
    meta: () => post('/api/meta'),
    data_window: (r0,r1,c0,c1) => post('/api/data_window', {r0,r1,c0,c1}),
    data_window_idx: (row_idxs, col_idxs) => post('/api/data_window_idx', {row_idxs, col_idxs}),
    row_summary: (r) => post('/api/row_summary', {r}),
    col_summary: (c) => post('/api/col_summary', {c}),
    field_summary: (axis, field) => post('/api/field_summary', {axis, field}),
    export_table: (spec) => post('/api/export_table', {spec}),
    open_url: (url) => post('/api/open_url', {url}),
    load_workspace: () => post('/api/load_workspace'),
    save_current: (state) => post('/api/save_current', {state}),
    save_view: (name, state) => post('/api/save_view', {name, state}),
    delete_view: (name) => post('/api/delete_view', {name}),
    rename_view: (old_name, new_name) => post('/api/rename_view', {old_name, new_name}),
  }};
  window.dispatchEvent(new Event('pywebviewready'));
}
</script>
"""

API = {
    "/api/meta": lambda body: API_INSTANCE.meta(),
    "/api/data_window": lambda body: API_INSTANCE.data_window(body["r0"], body["r1"], body["c0"], body["c1"]),
    "/api/data_window_idx": lambda body: API_INSTANCE.data_window_idx(body["row_idxs"], body["col_idxs"]),
    "/api/row_summary": lambda body: API_INSTANCE.row_summary(body["r"]),
    "/api/col_summary": lambda body: API_INSTANCE.col_summary(body["c"]),
    "/api/field_summary": lambda body: API_INSTANCE.field_summary(body["axis"], body["field"]),
    "/api/export_table": lambda body: _dev_export(body["spec"]),
    "/api/open_url": lambda body: API_INSTANCE.open_url(body["url"]) or {"ok": True},
    "/api/load_workspace": lambda body: API_INSTANCE.load_workspace(),
    "/api/save_current": lambda body: API_INSTANCE.save_current(body["state"]) or {"ok": True},
    "/api/save_view": lambda body: API_INSTANCE.save_view(body["name"], body["state"]) or {"ok": True},
    "/api/delete_view": lambda body: API_INSTANCE.delete_view(body["name"]) or {"ok": True},
    "/api/rename_view": lambda body: API_INSTANCE.rename_view(body["old_name"], body["new_name"]),
}
```

Then replace `main()`:

```python
def main():
    global API_INSTANCE
    if len(sys.argv) < 2:
        print("Usage: dev_server.py <file.biom> [port]", file=sys.stderr)
        sys.exit(1)
    API_INSTANCE = bv.Api(biom.load_table(sys.argv[1]), sys.argv[1])
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8765
```

with:

```python
def main():
    global API_INSTANCE
    if len(sys.argv) < 2:
        print("Usage: dev_server.py <file.biom> [port]", file=sys.stderr)
        sys.exit(1)
    # A dedicated temp-file store, not the real ~/Library/Application
    # Support/BiomViewer/state.json -- manual dev testing should never leave
    # saved views behind in (or read stale ones from) the real app's data.
    dev_store = bv.WorkspaceStore(Path(tempfile.gettempdir()) / "biom-viewer-dev-state.json")
    API_INSTANCE = bv.Api(biom.load_table(sys.argv[1]), sys.argv[1], workspace_store=dev_store)
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8765
```

- [ ] **Step 2: Manually verify the endpoints respond**

Run: `python3 scripts/dev_server.py tests/fixtures/*.biom 8765` (use any real `.biom` file available; if `tests/fixtures` doesn't exist, use any sample `.biom` on disk) in one terminal, then in another:

```bash
curl -s -X POST http://127.0.0.1:8765/api/load_workspace
```

Expected: `{"current": null, "views": []}`

```bash
curl -s -X POST http://127.0.0.1:8765/api/save_view \
  -H 'Content-Type: application/json' \
  -d '{"name":"test","state":{"mode":"data","axisState":{},"rowFields":[],"colFields":[],"pinnedObs":[],"pinnedColFields":[]}}'
curl -s -X POST http://127.0.0.1:8765/api/load_workspace
```

Expected: second call shows `"views": [{"mode": "data", ..., "name": "test", "savedAt": "..."}]`. Stop the server (Ctrl+C) when done.

- [ ] **Step 3: Commit**

```bash
git add scripts/dev_server.py
git commit -m "Wire saved-views API into the dev server"
```

---

## Task 5: Frontend — capture/apply view state and auto-restore on startup

**Files:**
- Modify: `biom_viewer/app.py` (PAGE template's `<script>` section)

No automated test for this task (no JS harness in this repo, per the spec's Testing section) — verified by hand via `dev_server.py` at the end of Task 7, once the full flow (including the UI to trigger a save) exists. This task alone is still independently checkable via the browser console, per Step 3 below.

- [ ] **Step 1: Add `captureViewState`, `applyViewState`, and comparison helpers**

In `biom_viewer/app.py`, find `restoreState`:

```javascript
function restoreState(snap){
  axisState = snap.axisState;
  rowFields = snap.rowFields.slice();
  colFields = snap.colFields.slice();
  recomputeVisible('observation');
  recomputeVisible('sample');
  rowPage=0; colPage=0;
  render();
  renderAxisChips();
}
```

Add immediately after it:

```javascript
// A saved view is a superset of the undo snapshot above -- it also carries
// mode and both pin sets, which snapshotState()/restoreState() deliberately
// exclude from undo history (see pinnedObs's own comment). Two different
// snapshot shapes for two different purposes, not one generalized one.
function captureViewState(){
  return {
    mode,
    axisState: JSON.parse(JSON.stringify(axisState)),
    rowFields: rowFields.slice(),
    colFields: colFields.slice(),
    pinnedObs: [...pinnedObs],
    pinnedColFields: [...pinnedColFields],
  };
}

// Only mutates state -- callers decide when to render(), so a caller that's
// about to do other work (reset a page, close a popover) isn't forced into
// two renders for one logical change.
function applyViewState(vs){
  setMode(vs.mode);
  axisState = JSON.parse(JSON.stringify(vs.axisState));
  rowFields = vs.rowFields.slice();
  colFields = vs.colFields.slice();
  pinnedObs = new Set(vs.pinnedObs);
  pinnedColFields = new Set(vs.pinnedColFields);
  recomputeVisible('observation');
  recomputeVisible('sample');
  rowPage=0; colPage=0;
}

// Payloads from the saved-views list carry extra name/savedAt keys a plain
// captureViewState() snapshot doesn't -- trim to the comparable subset before
// any JSON.stringify equality check, or every comparison would false-negative.
function viewStatePayload(v){
  return {mode: v.mode, axisState: v.axisState, rowFields: v.rowFields, colFields: v.colFields,
    pinnedObs: v.pinnedObs, pinnedColFields: v.pinnedColFields};
}

function viewStatesEqual(a, b){
  return JSON.stringify(a) === JSON.stringify(b);
}
```

- [ ] **Step 2: Load the workspace on startup, before the first render**

Find `loadMeta`:

```javascript
async function loadMeta(){
  try{
    meta = await window.pywebview.api.meta();
    rowFields = fieldUnion(meta.row_metadata);
    colFields = fieldUnion(meta.col_metadata);
    document.getElementById('filename').textContent =
      `${meta.filename}  —  ${meta.rows} rows x ${meta.cols} cols`;
    buildSearchIndex();
    render();
    renderAxisChips();
  } catch(err){
    document.getElementById('filename').textContent = `Failed to load: ${err}`;
    console.error(err);
  }
}
```

Replace with:

```javascript
let savedViews = [];
let lastAppliedViewName = null;
let lastLoadedViewState = null;

async function loadWorkspace(){
  const workspace = await window.pywebview.api.load_workspace();
  savedViews = workspace.views;
  if(workspace.current) applyViewState(workspace.current);
  lastLoadedViewState = captureViewState();
}

async function loadMeta(){
  try{
    meta = await window.pywebview.api.meta();
    rowFields = fieldUnion(meta.row_metadata);
    colFields = fieldUnion(meta.col_metadata);
    document.getElementById('filename').textContent =
      `${meta.filename}  —  ${meta.rows} rows x ${meta.cols} cols`;
    await loadWorkspace();
    buildSearchIndex();
    render();
    renderAxisChips();
  } catch(err){
    document.getElementById('filename').textContent = `Failed to load: ${err}`;
    console.error(err);
  }
}
```

- [ ] **Step 3: Manually verify**

Run `python3 scripts/dev_server.py <some-file.biom>`, open `http://127.0.0.1:8765/` in a browser, open devtools console, and run:

```js
await window.pywebview.api.save_current(captureViewState())
```

Reload the page. In the console:

```js
console.log(mode, [...pinnedObs], axisState)
```

Expected: matches what was captured before reload (all defaults, since nothing was changed yet — this just proves the round trip works end to end). Then apply a filter or sort through the UI, re-run the `save_current` call above, reload, and confirm the filter/sort is back after reload.

- [ ] **Step 4: Commit**

```bash
git add biom_viewer/app.py
git commit -m "Restore saved workspace state on file open"
```

---

## Task 6: Frontend — autosave on every mutation

**Files:**
- Modify: `biom_viewer/app.py` (PAGE template's `<script>` section)

- [ ] **Step 1: Add the debounced autosave and hook it into `recordHistory`**

Find:

```javascript
function recordHistory(){
  historyPast.push(snapshotState());
  if(historyPast.length>50) historyPast.shift();
  historyFuture = [];
}
```

Replace with:

```javascript
let autosaveTimer = null;
// Debounced so a burst of edits (typing a filter value, dragging a range)
// writes once, ~1s after things settle, not on every keystroke.
function scheduleAutosave(){
  clearTimeout(autosaveTimer);
  autosaveTimer = setTimeout(()=>{
    window.pywebview.api.save_current(captureViewState());
  }, 1000);
}

function recordHistory(){
  historyPast.push(snapshotState());
  if(historyPast.length>50) historyPast.shift();
  historyFuture = [];
  scheduleAutosave();
}
```

- [ ] **Step 2: Autosave on pin/mode changes too**

These three mutate state but deliberately don't call `recordHistory()` (pins and mode are excluded from undo history), so they each need their own `scheduleAutosave()` call.

Find `setMode`:

```javascript
function setMode(m){
  mode = m;
  if(m!=='col'){ expandedFieldRow = null; expandedPinnedField = null; }
  modeBtns.forEach(x=>x.classList.toggle('active', x.dataset.m===m));
  document.body.className = 'mode-'+m;
  document.getElementById('modeTag').textContent =
    m==='col' ? 'COL METADATA' : m==='row' ? 'ROW METADATA' : '';
}
```

Replace with:

```javascript
function setMode(m){
  mode = m;
  if(m!=='col'){ expandedFieldRow = null; expandedPinnedField = null; }
  modeBtns.forEach(x=>x.classList.toggle('active', x.dataset.m===m));
  document.body.className = 'mode-'+m;
  document.getElementById('modeTag').textContent =
    m==='col' ? 'COL METADATA' : m==='row' ? 'ROW METADATA' : '';
  scheduleAutosave();
}
```

Find `togglePin`:

```javascript
function togglePin(rawIdx){
  if(pinnedObs.has(rawIdx)) pinnedObs.delete(rawIdx); else pinnedObs.add(rawIdx);
  if(selPinnedRaw===rawIdx) selPinnedRaw = null;
  recomputeVisible('observation');
  // Clamp rather than reset to page 0 -- pin/unpin is a high-frequency
  // action (unlike sort/filter), a full page reset would be jarring.
  const maxPage = Math.max(0, Math.ceil(rowsTotal()/rowsPerPage()) - 1);
  rowPage = Math.min(rowPage, maxPage);
  render();
  renderAxisChips();
}
```

Replace with:

```javascript
function togglePin(rawIdx){
  if(pinnedObs.has(rawIdx)) pinnedObs.delete(rawIdx); else pinnedObs.add(rawIdx);
  if(selPinnedRaw===rawIdx) selPinnedRaw = null;
  recomputeVisible('observation');
  // Clamp rather than reset to page 0 -- pin/unpin is a high-frequency
  // action (unlike sort/filter), a full page reset would be jarring.
  const maxPage = Math.max(0, Math.ceil(rowsTotal()/rowsPerPage()) - 1);
  rowPage = Math.min(rowPage, maxPage);
  scheduleAutosave();
  render();
  renderAxisChips();
}
```

Find `togglePinField`:

```javascript
function togglePinField(field){
  if(pinnedColFields.has(field)) pinnedColFields.delete(field); else pinnedColFields.add(field);
  if(selPinnedField===field) selPinnedField = null;
  const maxPage = Math.max(0, Math.ceil(rowsTotal()/rowsPerPage()) - 1);
  rowPage = Math.min(rowPage, maxPage);
  render();
  renderAxisChips();
}
```

Replace with:

```javascript
function togglePinField(field){
  if(pinnedColFields.has(field)) pinnedColFields.delete(field); else pinnedColFields.add(field);
  if(selPinnedField===field) selPinnedField = null;
  const maxPage = Math.max(0, Math.ceil(rowsTotal()/rowsPerPage()) - 1);
  rowPage = Math.min(rowPage, maxPage);
  scheduleAutosave();
  render();
  renderAxisChips();
}
```

- [ ] **Step 3: Manually verify**

Run `python3 scripts/dev_server.py <some-file.biom>`, open in browser, open devtools Network tab, filter to `save_current`. Apply a filter through the UI. Expected: one `save_current` request fires roughly 1 second after you stop interacting (not one per keystroke/click). Reload the page — the filter should still be applied.

- [ ] **Step 4: Commit**

```bash
git add biom_viewer/app.py
git commit -m "Autosave current filter/sort/pin/mode state on every change"
```

---

## Task 7: Frontend — Views dropdown (save, switch, rename, delete)

**Files:**
- Modify: `biom_viewer/app.py` (PAGE template's `<style>` and toolbar HTML, plus new `<script>` functions)

- [ ] **Step 1: Add the toolbar button**

Find:

```html
    <span id="modeGroup">
      <button class="active" data-m="data">Data</button>
      <button data-m="row">Row metadata</button>
      <button data-m="col">Col metadata</button>
    </span>
    <span id="searchWrap">
```

Replace with:

```html
    <span id="modeGroup">
      <button class="active" data-m="data">Data</button>
      <button data-m="row">Row metadata</button>
      <button data-m="col">Col metadata</button>
    </span>
    <button class="tool" id="viewsBtn" title="Saved views">Views ▾</button>
    <span id="searchWrap">
```

- [ ] **Step 2: Add CSS for the views popover and the discard-confirm popover**

Find:

```css
  .chip-x{background:none;border:none;color:var(--dim);cursor:pointer;font-size:10px;padding:0;line-height:1}
  .chip-x:hover{color:var(--fg)}
```

Replace with:

```css
  .chip-x{background:none;border:none;color:var(--dim);cursor:pointer;font-size:10px;padding:0;line-height:1}
  .chip-x:hover{color:var(--fg)}
  #viewsPopover{position:fixed;z-index:30;background:var(--panel-bg);border:1px solid var(--border);
    border-radius:6px;padding:6px;display:flex;flex-direction:column;gap:4px;width:220px;
    box-shadow:0 4px 14px rgba(0,0,0,.25)}
  .views-list{display:flex;flex-direction:column;gap:2px;max-height:260px;overflow-y:auto}
  .views-empty{color:var(--dim);font-size:12px;padding:4px 6px}
  .views-row{display:flex;align-items:center;gap:6px;padding:4px 6px;border-radius:4px;cursor:pointer}
  .views-row:hover{background:var(--hl)}
  .views-row.active{background:var(--hl);font-weight:700}
  .views-name{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:12px}
  .views-x{background:none;border:none;color:var(--dim);cursor:pointer;font-size:10px;padding:0;line-height:1}
  .views-x:hover{color:var(--danger)}
  .views-save{display:flex;gap:4px;border-top:1px solid var(--border);padding-top:6px}
  .views-save-input,.views-rename-input{flex:1;box-sizing:border-box;background:var(--input-bg);color:var(--fg);
    border:1px solid var(--input-border);border-radius:4px;padding:3px 6px;font-size:12px}
  .views-rename-input.error{border-color:var(--danger)}
  .views-save-btn{background:var(--panel-bg);color:var(--fg);border:1px solid var(--input-border);
    border-radius:4px;padding:3px 8px;cursor:pointer;font-size:12px}
  #confirmPopover{position:fixed;z-index:40;left:50%;top:40%;transform:translate(-50%,-50%);
    background:var(--panel-bg);border:1px solid var(--border);border-radius:6px;padding:14px;
    display:flex;flex-direction:column;gap:10px;box-shadow:0 4px 14px rgba(0,0,0,.3)}
  .confirm-msg{font-size:13px}
  .confirm-buttons{display:flex;gap:6px;justify-content:flex-end}
  .confirm-buttons button{background:var(--panel-bg);color:var(--fg);border:1px solid var(--input-border);
    border-radius:4px;padding:4px 10px;cursor:pointer;font-size:12px}
  .confirm-discard{border-color:var(--danger)!important;color:var(--danger)}
```

- [ ] **Step 3: Add the views popover, switch/save/rename/delete functions, and confirm popover**

Find (the outside-click handler that closes `#filterPopover`):

```javascript
document.addEventListener('click', (e)=>{
  const pop = document.getElementById('filterPopover');
  if(pop && !pop.contains(e.target) && !e.target.closest('.axis-filter') && !e.target.closest('.axis-edit')) closeFilterPopover();
});
```

Replace with:

```javascript
document.addEventListener('click', (e)=>{
  const pop = document.getElementById('filterPopover');
  if(pop && !pop.contains(e.target) && !e.target.closest('.axis-filter') && !e.target.closest('.axis-edit')) closeFilterPopover();
  const viewsPop = document.getElementById('viewsPopover');
  if(viewsPop && !viewsPop.contains(e.target) && e.target!==viewsBtn) closeViewsPopover();
});

function closeViewsPopover(){
  const existing = document.getElementById('viewsPopover');
  if(existing) existing.remove();
  return !!existing;
}

function viewRowHtml(view){
  const activeClass = lastAppliedViewName===view.name ? ' active' : '';
  return `<div class="views-row${activeClass}" data-name="${escapeHtml(view.name)}">` +
    `<span class="views-name">${escapeHtml(view.name)}</span>` +
    `<button class="views-x" title="Delete">✕</button></div>`;
}

function openViewsPopover(){
  closeFilterPopover();
  closeViewsPopover();
  const pop = document.createElement('div');
  pop.id = 'viewsPopover';
  const rect = viewsBtn.getBoundingClientRect();
  pop.style.left = rect.left + 'px';
  pop.style.top = (rect.bottom + 4) + 'px';
  const rows = savedViews.length
    ? savedViews.map(viewRowHtml).join('')
    : `<div class="views-empty">No saved views yet</div>`;
  pop.innerHTML = `<div class="views-list">${rows}</div>` +
    `<div class="views-save"><input class="views-save-input" type="text" placeholder="Save current as…">` +
    `<button class="views-save-btn">Save</button></div>`;
  document.body.appendChild(pop);
  wireViewsPopover(pop);
}

function wireViewsPopover(pop){
  pop.querySelectorAll('.views-row').forEach(row=>{
    const name = row.dataset.name;
    row.querySelector('.views-name').addEventListener('click', ()=> switchToView(name));
    row.querySelector('.views-name').addEventListener('dblclick', (e)=>{ e.stopPropagation(); startRenameView(row, name); });
    row.querySelector('.views-x').addEventListener('click', (e)=>{ e.stopPropagation(); deleteView(name); });
  });
  const saveInput = pop.querySelector('.views-save-input');
  const saveBtn = pop.querySelector('.views-save-btn');
  const doSave = ()=> saveCurrentAsView(saveInput.value.trim());
  saveBtn.onclick = doSave;
  saveInput.addEventListener('keydown', e=>{ if(e.key==='Enter') doSave(); if(e.key==='Escape') closeViewsPopover(); });
}

async function refreshSavedViews(){
  const workspace = await window.pywebview.api.load_workspace();
  savedViews = workspace.views;
}

async function saveCurrentAsView(name){
  if(!name) return;
  await window.pywebview.api.save_view(name, captureViewState());
  await refreshSavedViews();
  lastAppliedViewName = name;
  closeViewsPopover();
}

async function deleteView(name){
  await window.pywebview.api.delete_view(name);
  if(lastAppliedViewName===name) lastAppliedViewName = null;
  await refreshSavedViews();
  openViewsPopover();
}

function startRenameView(row, oldName){
  row.innerHTML = `<input class="views-rename-input" type="text" value="${escapeHtml(oldName)}">`;
  const input = row.querySelector('.views-rename-input');
  input.focus();
  input.select();
  const commit = async ()=>{
    const newName = input.value.trim();
    if(!newName || newName===oldName){ openViewsPopover(); return; }
    const result = await window.pywebview.api.rename_view(oldName, newName);
    if(!result.ok){ input.classList.add('error'); input.title = 'Name already taken'; return; }
    if(lastAppliedViewName===oldName) lastAppliedViewName = newName;
    await refreshSavedViews();
    openViewsPopover();
  };
  input.addEventListener('keydown', e=>{ if(e.key==='Enter') commit(); if(e.key==='Escape') openViewsPopover(); });
  input.addEventListener('blur', commit);
}

function applyView(view, name){
  // recordHistory() only captures the undo snapshot's existing shape
  // (axisState/rowFields/colFields) -- mode and pins are already deliberately
  // outside undo history everywhere else in this app (see pinnedObs's own
  // comment), so ⌘Z after a switch reverts filters/sort but leaves the
  // switched-to view's mode/pins in place. Same partial coverage undo
  // already has for a plain pin toggle, not a new gap.
  recordHistory();
  applyViewState(view);
  lastAppliedViewName = name;
  lastLoadedViewState = captureViewState();
  closeViewsPopover();
  render();
  renderAxisChips();
}

function confirmDiscardCurrent(onConfirm){
  closeFilterPopover();
  closeViewsPopover();
  const pop = document.createElement('div');
  pop.id = 'confirmPopover';
  pop.innerHTML = `<div class="confirm-msg">Discard current filters?</div>` +
    `<div class="confirm-buttons"><button class="confirm-discard">Discard</button><button class="confirm-cancel">Cancel</button></div>`;
  document.body.appendChild(pop);
  pop.querySelector('.confirm-discard').onclick = ()=>{ pop.remove(); onConfirm(); };
  pop.querySelector('.confirm-cancel').onclick = ()=>{ pop.remove(); };
}

async function switchToView(name){
  const view = savedViews.find(v => v.name===name);
  if(!view) return;
  const current = captureViewState();
  const matchesSaved = savedViews.some(v => viewStatesEqual(current, viewStatePayload(v)));
  const dirty = !viewStatesEqual(current, lastLoadedViewState) && !matchesSaved;
  if(dirty){ confirmDiscardCurrent(()=> applyView(view, name)); return; }
  applyView(view, name);
}

const viewsBtn = document.getElementById('viewsBtn');
viewsBtn.onclick = ()=> openViewsPopover();
```

- [ ] **Step 3b: Make `viewStatesEqual` order-insensitive for pin sets**

Added during Task 7's implementation (authorized directly by the controller, based on a finding from Task 5's code quality review — documented here after the fact for plan/code parity): `captureViewState()` and `viewStatePayload()` (both added in Task 5) build their `pinnedObs`/`pinnedColFields` arrays from `Set` iteration order (insertion order), so two states with identical pin *membership* but different insertion history (e.g. pin A then B, vs. unpin-and-repin A giving B-then-A) produce differently-ordered arrays and make `viewStatesEqual`'s `JSON.stringify` comparison false-negative. Task 5 left this inert (nothing called `viewStatesEqual` yet); Task 7's `switchToView` is the first real caller, so the bug becomes user-visible there (an unnecessary "discard current filters?" prompt) — fixed as part of this task instead of shipping it broken.

`captureViewState()` — sort both arrays before returning; `pinnedObs` needs an explicit numeric comparator since default `.sort()` is lexicographic (would put `10` before `2`):

```javascript
function captureViewState(){
  return {
    mode,
    axisState: JSON.parse(JSON.stringify(axisState)),
    rowFields: rowFields.slice(),
    colFields: colFields.slice(),
    pinnedObs: [...pinnedObs].sort((a,b)=>a-b),
    pinnedColFields: [...pinnedColFields].sort(),
  };
}
```

`viewStatePayload(v)` — same sorting applied when extracting the comparable subset from a saved view's payload:

```javascript
function viewStatePayload(v){
  return {mode: v.mode, axisState: v.axisState, rowFields: v.rowFields, colFields: v.colFields,
    pinnedObs: [...v.pinnedObs].sort((a,b)=>a-b), pinnedColFields: [...v.pinnedColFields].sort()};
}
```

- [ ] **Step 4: Manually verify the full flow**

Run `python3 scripts/dev_server.py <some-file.biom>`, open in browser:

1. Apply a filter or sort. Click "Views ▾" → type a name in "Save current as…" → Save. The view appears in the list.
2. Clear the filter (so current state no longer matches the saved view). Click "Views ▾" → click the saved view's name. Expected: a "Discard current filters?" popup appears; click Discard. Expected: the filter is back, and the grid reflects it.
3. Click "Views ▾" again, double-click the view's name, type a new name, press Enter. Expected: it renames in place, no page reload needed.
4. Click "Views ▾", click the ✕ next to the view. Expected: it's removed from the list.
5. Reload the page (simulating reopening the file). Expected: whatever filter/sort/pin/mode was active before reload is restored automatically, with no manual action.

- [ ] **Step 5: Commit**

```bash
git add biom_viewer/app.py
git commit -m "Add Views dropdown: save, switch, rename, delete saved views"
```

---

## Task 8: Full verification pass

**Files:** none (verification only)

- [ ] **Step 1: Run the full Python test suite**

Run: `python3 -m pytest tests/ -v`
Expected: all tests pass, including every test added in Tasks 1-3, with no regressions in the pre-existing tests.

- [ ] **Step 2: Rebuild and install the app**

Per this project's standing instruction, rebuild and install to `/Applications` after code changes:

```bash
bash scripts/build_macos_app.sh && bash scripts/install_macos_app.sh
```

(If these script names differ, check `ls scripts/` first — `build_macos_app.sh` and `install_macos_app.sh` are listed in the repo root's `scripts/` directory as of this plan.)

- [ ] **Step 3: Smoke-test in the real app**

Open a real `.biom` file in the installed app. Repeat the five checks from Task 7 Step 4 inside the actual native window (not the dev server) — in particular, fully quit and reopen the app on the same file to confirm auto-restore survives a real process restart, not just a page reload.

- [ ] **Step 4: Final commit (if Steps 2-3 required any fixes)**

```bash
git add -A
git commit -m "Fix issues found during saved-views manual verification"
```

(Skip this step if nothing needed fixing.)
