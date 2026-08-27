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

from biom_viewer.web_script import SCRIPT
from biom_viewer.web_style import STYLE


def _json_safe(v):
    # Real metadata (e.g. pandas-sourced sample sheets) is full of NaN/inf for
    # missing values. json.dumps emits those as bare NaN/Infinity tokens,
    # which is invalid JSON and makes JSON.parse throw on the JS side.
    if isinstance(v, float) and not math.isfinite(v):
        return None
    if isinstance(v, dict):
        return {k: _json_safe(x) for k, x in v.items()}
    # biom-format reads list-valued metadata (e.g. a taxonomy lineage) back
    # as a numpy object array of bytes, not a plain list of str -- neither
    # of which json.dumps can serialize on its own.
    if isinstance(v, np.ndarray):
        return [_json_safe(x) for x in v.tolist()]
    if isinstance(v, (list, tuple)):
        return [_json_safe(x) for x in v]
    if isinstance(v, bytes):
        return v.decode("utf-8", "replace")
    if isinstance(v, np.generic):
        return _json_safe(v.item())
    return v


def _histogram(values, buckets=10):
    lo, hi = min(values), max(values)
    if lo == hi:
        return [{"lo": lo, "hi": hi, "count": len(values)}]
    width = (hi - lo) / buckets
    counts = [0] * buckets
    for v in values:
        idx = int((v - lo) / width)
        if idx == buckets:
            idx -= 1
        counts[idx] += 1
    return [
        {"lo": lo + i * width, "hi": lo + (i + 1) * width, "count": counts[i]}
        for i in range(buckets)
    ]


def _numeric_summary(values, total):
    n = len(values)
    if n == 0:
        return {
            "kind": "numeric", "n": total, "sum": None, "min": None,
            "max": None, "mean": None, "median": None, "histogram": [],
        }
    s = sorted(values)
    mid = n // 2
    median = s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2
    return {
        "kind": "numeric",
        "n": total,
        "sum": sum(values),
        "min": min(values),
        "max": max(values),
        "mean": sum(values) / n,
        "median": median,
        "histogram": _histogram(values, buckets=10),
    }


def _axis_summary(vec, total):
    values = [float(v) for v in vec.data if v != 0]
    summary = _numeric_summary(values, total)
    summary["nonzero"] = len(values)
    summary["sparsity"] = round((total - len(values)) / total * 100, 1) if total else 0.0
    return summary


def _is_numeric(v):
    if isinstance(v, bool):
        return False
    if isinstance(v, (int, float)):
        return True
    if isinstance(v, str):
        try:
            float(v)
            return True
        except ValueError:
            return False
    return False


# Common missing-value conventions in exported clinical/bio metadata. A field
# that's otherwise all numbers shouldn't get downgraded to categorical just
# because a handful of rows spell "missing" as text instead of leaving it
# empty — these are excluded from `present` the same way None/""/NaN are.
_MISSING_TOKENS = {"na", "n/a", "nan", "null", "none", "-"}


def _is_missing(v):
    if v is None or v == "":
        return True
    if isinstance(v, float) and not math.isfinite(v):
        return True
    if isinstance(v, str) and v.strip().lower() in _MISSING_TOKENS:
        return True
    return False


def field_summary(table, axis, field, idxs=None):
    entries = table.metadata(axis=axis)
    if idxs is not None:
        entries = [entries[i] for i in idxs]
    total = len(entries)
    raw = [(dict(e) if e else {}).get(field) for e in entries]
    present = [v for v in raw if not _is_missing(v)]
    missing = total - len(present)

    if present and all(_is_numeric(v) for v in present):
        values = [float(v) for v in present]
        summary = _numeric_summary(values, total)
        summary["missing"] = missing
        return summary

    counts = Counter(str(v) for v in present)
    ranked = counts.most_common()
    top = [{"value": v, "count": c} for v, c in ranked[:10]]
    other_count = sum(c for _, c in ranked[10:])
    return {
        "kind": "categorical",
        "n": total,
        "missing": missing,
        "distinct": len(ranked),
        "top": top,
        "other_count": other_count,
        # Full ranked list, for the "+N other" viewer -- already computed
        # above (ranked), so this is free beyond JSON size. Bounded by the
        # axis length, same as `top`/`other_count` already are.
        "all": [{"value": v, "count": c} for v, c in ranked],
    }


def build_export_table(table, spec):
    # spec: {'observation': {...}, 'sample': {...}}, each with:
    #   ids: list[str] | None (filtered/sorted id order; None = unchanged)
    #   replacements: [{field, find, replace}]
    #   renames: {orig_field: new_field}
    #   deletedFields: [field, ...]
    # Mirrors the frontend's buildAxisExportCode -- see that function's
    # comment for why replacements/renames/deletes go through add_metadata
    # (merge-by-key) plus an explicit del_metadata for the keys that should
    # actually disappear (add_metadata alone never removes a key).
    table = table.copy()
    for axis in ("observation", "sample"):
        s = spec.get(axis) or {}
        ids = s.get("ids")
        if ids is not None:
            table = table.filter(ids, axis=axis)
            table = table.sort_order(ids, axis=axis)

        replacements = s.get("replacements") or []
        if replacements:
            md = {}
            for id_, entry in zip(table.ids(axis=axis), table.metadata(axis=axis) or ()):
                if not entry:
                    continue
                changed = {}
                for r in replacements:
                    field = r["field"]
                    if field in entry and entry[field] is not None:
                        changed[field] = str(entry[field]).replace(r["find"], r["replace"])
                if changed:
                    md[id_] = changed
            if md:
                table.add_metadata(md, axis=axis)

        renames = s.get("renames") or {}
        if renames:
            md = {}
            for id_, entry in zip(table.ids(axis=axis), table.metadata(axis=axis) or ()):
                if not entry:
                    continue
                for orig, new in renames.items():
                    if orig in entry:
                        md.setdefault(id_, {})[new] = entry[orig]
            if md:
                table.add_metadata(md, axis=axis)
            table.del_metadata(keys=list(renames.keys()), axis=axis)

        deleted = s.get("deletedFields") or []
        if deleted:
            table.del_metadata(keys=deleted, axis=axis)

        # to_hdf5() requires every id on an axis to have the exact same
        # metadata *keys* (not just non-null values) -- real-world biom
        # files routinely have per-id metadata dicts that disagree (an
        # optional field present on some ids, absent on others), which
        # to_hdf5() rejects outright rather than writing a partial file.
        # It also requires each key's column to be internally homogeneous:
        # every value a str, or every value a list (of str) -- bare None is
        # the only mix it tolerates. Real files break this in both
        # directions (a list-valued lineage field sitting next to bare None
        # for ids missing it; a list of ints instead of strs; an int field
        # with some ids None). Since the write is not transactional, hitting
        # any of this mid-write used to leave a truncated, unopenable .biom
        # at the destination.
        #
        # Fix by normalizing per *column* rather than per entry, and only
        # where the column actually needs it -- a clean uniform-numeric
        # column (no None) already round-trips fine as numbers via to_hdf5's
        # own dtype inference, and stringifying it unnecessarily would lose
        # that. Only list-valued columns (always, since elements might not
        # be str) and columns that mix None with a non-str type (which
        # to_hdf5 can't reconcile into one dtype) get coerced.
        entries = table.metadata(axis=axis)
        if entries:
            ids = table.ids(axis=axis)
            all_keys = set()
            for e in entries:
                if e:
                    all_keys.update(e.keys())
            columns = {}
            for k in all_keys:
                values = [(e or {}).get(k) for e in entries]
                non_none_types = {type(v) for v in values if v is not None}
                has_none = any(v is None for v in values)
                if non_none_types <= {list, tuple}:
                    columns[k] = [
                        [] if v is None else ["" if x is None else str(x) for x in v]
                        for v in values
                    ]
                elif non_none_types <= {str} or (
                    len(non_none_types) <= 1 and not has_none
                    and next(iter(non_none_types), str) in (str, int, float, bool)
                ):
                    columns[k] = values
                else:
                    columns[k] = [None if v is None else str(v) for v in values]
            filled = {id_: {k: columns[k][i] for k in all_keys} for i, id_ in enumerate(ids)}
            table.add_metadata(filled, axis=axis)

    return table


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


class Api:
    """Exposed to the frontend as window.pywebview.api.* — no HTTP server involved.

    One instance per open file/window (see open_window()) -- table and
    filename are instance state, not module globals, so multiple windows in
    the same process each stay bound to their own file.
    """

    def __init__(self, table, filename, workspace_store: WorkspaceStore | None = None):
        self._table = table
        self._filename = filename
        self.window = None  # set by open_window() once create_window() returns
        self._csc_matrix = None
        self._workspace_store = workspace_store or WorkspaceStore.default()
        self._identity = DatasetIdentity.from_table(table)

    # ponytail: id list sent once (text-only, cheap even at ~1e5 rows); paginate if a table
    # ever has >~500k ids and this becomes a multi-MB response.
    def meta(self):
        table = self._table
        obs_ids = table.ids("observation").tolist()
        sample_ids = table.ids("sample").tolist()
        obs_meta = table.metadata(axis="observation")
        sample_meta = table.metadata(axis="sample")
        return {
            "filename": self._filename,
            "rows": table.shape[0],
            "cols": table.shape[1],
            "row_ids": obs_ids,
            "col_ids": sample_ids,
            "table_id": table.table_id,
            "table_type": table.type,
            "generated_by": table.generated_by,
            "create_date": str(table.create_date) if table.create_date else None,
            "row_metadata": [_json_safe(dict(m)) for m in obs_meta] if obs_meta else None,
            "col_metadata": [_json_safe(dict(m)) for m in sample_meta] if sample_meta else None,
        }

    def data_window(self, r0, r1, c0, c1):
        table = self._table
        r1 = min(r1, table.shape[0])
        c1 = min(c1, table.shape[1])
        # Densify only the requested window, never the full matrix.
        sub = table.matrix_data[r0:r1, :].tocsc()[:, c0:c1]
        return sub.toarray().tolist()

    def data_window_idx(self, row_idxs, col_idxs):
        # Gather arbitrary (unsorted, non-contiguous) row/col index lists —
        # used once either axis has an active sort or filter, since the
        # visible page no longer maps to a contiguous matrix range. Densify
        # only the requested submatrix, same as data_window.
        sub = self._table.matrix_data.tocsr()[row_idxs, :].tocsc()[:, col_idxs]
        return sub.toarray().tolist()

    def row_summary(self, r):
        return _axis_summary(self._table.matrix_data.tocsr()[r, :], self._table.shape[1])

    def _csc(self):
        if self._csc_matrix is None:
            self._csc_matrix = self._table.matrix_data.tocsc()
        return self._csc_matrix

    def col_summary(self, c):
        return _axis_summary(self._csc()[:, c], self._table.shape[0])

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
        # The right-click "Search Google" menu builds this URL itself (see
        # openContextMenu in the frontend) rather than accepting an arbitrary
        # one from anywhere else, so there's no untrusted-input surface here.
        # Routed through Python's webbrowser rather than a JS window.open()/
        # <a target=_blank> click because pywebview's cocoa backend only
        # intercepts real link-navigation events for its "open externally"
        # behavior, not window.open() -- this works regardless of backend.
        webbrowser.open(url)

    def export_table(self, spec):
        default_name = os.path.splitext(os.path.basename(self._filename))[0] + "_export.biom"
        result = self.window.create_file_dialog(
            webview.FileDialog.SAVE,
            save_filename=default_name,
            file_types=("BIOM file (*.biom)", "All files (*.*)"),
        )
        if not result:
            return {"ok": False}
        path = result[0] if isinstance(result, (list, tuple)) else result
        try:
            table = build_export_table(self._table, spec)
            write_biom_file(table, path)
        except Exception as exc:  # noqa: BLE001 -- surface to the UI instead of silently dropping
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "path": path}


PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>BIOM Viewer</title>
<style>
{STYLE}
</style></head>
<body class="mode-data">
<div id="info">
  <span style="display:flex;align-items:center;overflow:hidden">
    <span id="filename">loading…</span>
    <span id="dims"></span>
    <span id="modeTag"></span>
  </span>
  <span id="toolbar">
    <span id="modeGroup">
      <button class="active" data-m="data">Data</button>
      <button data-m="row">Row metadata</button>
      <button data-m="col">Col metadata</button>
    </span>
    <span id="searchWrap">
      <input id="searchBox" type="text" placeholder="Search…" autocomplete="off">
      <button class="tool" id="searchPin" title="Keep search results open while you click around the grid">📌<span>Keep open</span></button>
      <div id="searchResults"></div>
    </span>
  </span>
</div>
<div id="axisChips">
  <button class="tool" id="viewsBtn" title="Saved views">Views ▾</button>
  <div id="axisChipsList"></div>
</div>
<div id="selectedWrap">
  <!-- The hint is a placeholder rather than a value so it can be styled as
       the instructional prose it is (system font) while real selected
       content still lands in the monospace value slot -- and so it comes
       back on its own if the field is ever cleared. -->
  <input id="selected" readonly placeholder="Click a row, column, or cell to see its full text here. Arrow keys move the selection, ⌘C copies it, double-click a header for summary stats.">
  <!-- Copying is now an explicit gesture rather than a side effect of
       clicking, so it needs to visibly confirm that it happened. -->
  <span id="copiedBadge" aria-live="polite"></span>
  <button class="tool" id="expandBtn" title="View full content in a window (⌘⏎)">⤢</button>
</div>

<div id="body">
  <div id="rowNav">
    <button class="nav" id="rowUp">▲</button>
    <span id="rowRange"></span>
    <button class="nav" id="rowDown">▼</button>
  </div>
  <div id="main">
    <div id="colNav">
      <button class="nav" id="colPrev">◀</button>
      <span id="colRange"></span>
      <button class="nav" id="colNext">▶</button>
    </div>
    <div id="grid"></div>
  </div>
</div>
<div id="replaceOverlay" class="wm-overlay">
  <div id="replaceModal" class="wm-modal">
    <header>
      <h3>Find &amp; Replace</h3>
      <button class="x" id="replaceClose">✕</button>
    </header>
    <!-- Labelled: the two selects sat unlabelled one above the other, so
         which was "where to look" and which was "which field" was left to
         be inferred from their current values. -->
    <div class="rp-form">
      <label class="rp-label" for="rpAxis">Search in</label>
      <select id="rpAxis">
        <option value="observation">Observation (row) metadata</option>
        <option value="sample">Sample (col) metadata</option>
      </select>
      <label class="rp-label" for="rpField">Field</label>
      <select id="rpField"></select>
      <input id="rpFind" type="text" placeholder="Find…">
      <input id="rpReplace" type="text" placeholder="Replace with…">
      <button class="tool" id="rpApply">Apply</button>
    </div>
    <div id="rpList"></div>
  </div>
</div>
<div id="codeOverlay" class="wm-overlay">
  <div class="wm-modal">
    <header>
      <h3>Export as Python</h3>
      <button class="tool" id="codeCopy">Copy</button>
      <button class="x" id="codeClose">✕</button>
    </header>
    <pre id="codeBlock" class="wm-body"></pre>
  </div>
</div>
<div id="cellOverlay" class="wm-overlay">
  <div class="wm-modal">
    <header>
      <h3 id="cellTitle">Cell content</h3>
      <button class="tool" id="cellCopy">Copy</button>
      <button class="x" id="cellClose">✕</button>
    </header>
    <pre id="cellBlock" class="wm-body"></pre>
  </div>
</div>
<div id="valuesOverlay" class="wm-overlay">
  <div class="wm-modal">
    <header>
      <h3 id="valuesTitle">All values</h3>
      <button class="tool" id="valuesCopy">Copy</button>
      <button class="x" id="valuesClose">✕</button>
    </header>
    <div id="valuesBody" class="wm-body wm-list"></div>
  </div>
</div>
<script>
{SCRIPT}
</script>
</body></html>
""".replace("{STYLE}", STYLE).replace("{SCRIPT}", SCRIPT)


def _set_dock_icon():
    # pywebview's `webview.start(icon=...)` param is GTK/QT only (per its own
    # docstring) and even its Cocoa code path applies too late to affect the
    # already-created main window. Set the Dock icon ourselves instead —
    # NSApplication.sharedApplication() returns the same singleton pywebview's
    # Cocoa backend already created, so this just overrides its icon in place.
    if sys.platform != "darwin":
        return
    icon_path = os.path.join(os.path.dirname(__file__), "icon.png")
    if not os.path.isfile(icon_path):
        return
    try:
        from AppKit import NSApplication, NSImage

        image = NSImage.alloc().initByReferencingFile_(icon_path)
        NSApplication.sharedApplication().setApplicationIconImage_(image)
    except ImportError:
        pass


def open_window(path):
    table = biom.load_table(path)
    # Standard Mac document-window convention is just the filename, not
    # "AppName — filename" -- the app identity is already carried by the
    # Dock icon and menu bar, so repeating it in the titlebar is redundant.
    title = os.path.basename(path)
    api = Api(table, path)
    window = webview.create_window(title, html=PAGE, js_api=api, width=1280, height=820, min_size=(600, 400))
    api.window = window
    return window


# One shared IPC socket per user so double-clicking another .biom file opens
# a new window in the already-running app instead of a whole new process
# (and a second Dock icon) -- macOS delivers each double-click as a fresh
# process launch (see build_macos_app.sh's launcher comment), so the second
# process has to detect the first and hand its file off instead of running.
def _ipc_path():
    return f"/tmp/biom-viewer-{os.getuid()}.sock"


def _send_to_running_instance(path):
    sock_path = _ipc_path()
    if not os.path.exists(sock_path):
        return False
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(2)
            s.connect(sock_path)
            s.sendall(path.encode("utf-8"))
        return True
    except OSError:
        return False  # stale socket file (instance crashed) -- fall through and become the instance


def _listen_for_files():
    sock_path = _ipc_path()
    if os.path.exists(sock_path):
        os.remove(sock_path)
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(sock_path)
    server.listen(5)
    try:
        while True:
            conn, _ = server.accept()
            with conn:
                data = conn.recv(65536)
            # create_window() from a background thread inserts the window
            # into the already-running GUI loop immediately; called from the
            # main thread it would just queue until that loop starts. See
            # https://pywebview.flowrl.com's create_window() source.
            if data:
                open_window(data.decode("utf-8"))
    finally:
        server.close()
        if os.path.exists(sock_path):
            os.remove(sock_path)


def main():
    if len(sys.argv) < 2:
        print("Usage: biom-viewer <file.biom>", file=sys.stderr)
        sys.exit(1)
    path = sys.argv[1]

    if _send_to_running_instance(path):
        return  # handed off to the already-running instance -- nothing left to do

    open_window(path)
    _set_dock_icon()
    threading.Thread(target=_listen_for_files, daemon=True).start()

    def js(code):
        # Not the window that happened to create this menu -- the one
        # currently focused, so File/Edit/View act on whichever window the
        # user is actually looking at (there can be several now).
        return lambda: (webview.active_window() or webview.windows[0]).evaluate_js(code)

    # Replaces pywebview's default Edit/View menus (Cut/Copy/Paste/Fullscreen)
    # with the app's own actions -- native menu items can't carry a Cocoa key
    # equivalent through pywebview's public API, so ⌘-shortcuts stay bound in
    # the page's own keydown listener; these menu items are for discovery/click.
    webview.settings["SHOW_DEFAULT_MENUS"] = False
    menu = [
        Menu("File", [
            MenuAction("Export as Python…", js("openExportModal()")),
            MenuAction("Export View as .biom…", js("exportBiomFile()")),
        ]),
        Menu("Edit", [
            MenuAction("Undo", js("undo()")),
            MenuAction("Redo", js("redo()")),
            MenuSeparator(),
            MenuAction("Find…", js("document.getElementById('searchBox').focus()")),
            MenuAction("Find & Replace…", js("openReplaceModal()")),
        ]),
        Menu("View", [
            MenuAction("Toggle Theme", js("toggleTheme()")),
            MenuSeparator(),
            MenuAction("Increase Font Size", js("setFontSize(fontSize+1)")),
            MenuAction("Decrease Font Size", js("setFontSize(fontSize-1)")),
            MenuSeparator(),
            MenuAction("Expand Selected Cell…", js("openCellModal()")),
        ]),
    ]
    webview.start(menu=menu)


if __name__ == "__main__":
    main()
