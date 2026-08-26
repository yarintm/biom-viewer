# Saved Views (Persistent Filter/Sort Workspaces) — Design

## Context

BiomViewer is a lazy-loading native viewer for BIOM tables (pywebview + biom-format, single-file app in `biom_viewer/app.py`). Sort/filter/pin/rename/replace/delete state (`2026-08-19-sort-filter-design.md`, row pinning commits) all lives in memory only — closing and reopening a file starts from scratch every time.

This surfaced as a real pain point: building up a filter set, clearing it to build another, then wanting the first one back with no way to get it except redoing the work. Exporting a filtered `.biom` file was tried as a workaround but just trades the problem for a worse one — juggling multiple physical files on disk for what is fundamentally a *view* over one dataset, not a new dataset.

This spec adds two related capabilities on top of the existing per-axis `axisState` + pin sets:

1. **Auto-restore**: reopening a `.biom` file returns you to exactly the filter/sort/pin/mode state you left it in.
2. **Named views**: explicitly save the current state under a name, and switch between saved states on the same file without ever touching the filesystem or leaving the app.

## Scope

- A "view" captures everything `snapshotState()` already tracks (`axisState`: sort/filters/renames/replacements/deletedFields, `rowFields`, `colFields`) plus `mode` and both pin sets (`pinnedObs`, `pinnedColFields`). Nothing new to invent — it's the existing undo-snapshot shape, extended by three fields.
- Persistence lives entirely in a single app-support JSON file, never touches the source `.biom` file, never creates sidecar files next to user data.
- Views are keyed to the **dataset's identity**, not the file's path — so renaming, moving, or copying the `.biom` file doesn't orphan its saved views.
- Out of scope: syncing views across machines, sharing/exporting a view to hand to someone else, view thumbnails/previews.

## Storage & identity key

One JSON file at `platformdirs.user_data_dir("BiomViewer") / "state.json"` (macOS: `~/Library/Application Support/BiomViewer/state.json`), shape:

```json
{
  "<identity-key>": {
    "current": { "mode": "data", "axisState": {...}, "rowFields": [...], "colFields": [...],
                 "pinnedObs": [...], "pinnedColFields": [...] },
    "views": [
      { "name": "High abundance only", "mode": "data", "axisState": {...},
        "rowFields": [...], "colFields": [...],
        "pinnedObs": [...], "pinnedColFields": [...], "savedAt": "2026-08-26T10:00:00" }
    ]
  }
}
```

`rowFields`/`colFields` are included alongside `axisState` — `deleteField` splices them directly (`biom_viewer/app.py:1876-1878`) rather than only recording the deletion in `axisState.deletedFields`, so a view can't restore a deleted or reordered field without them. This is the same pair undo's `restoreState()` already restores together with `axisState` for exactly this reason.

Identity key derivation, computed once per `Api` instance from data already loaded in `meta()`:

1. `table.table_id` if present and non-empty (BIOM's own embedded identifier — stable across move/rename/copy, since it's baked into the HDF5 content, not the filesystem path).
2. Fallback fingerprint if `table_id` is missing/empty: a hash of `(shape, row_ids[:5], row_ids[-5:], col_ids[:5], col_ids[-5:])` — cheap, no extra pass over the matrix, just the id lists `meta()` already sent.

Collision risk (two unrelated files fingerprint-identically) is accepted as a display-only annoyance — worst case you see an unrelated file's saved views, nothing about the actual `.biom` data is ever read from or written to based on this key.

## Python domain model

This repo is deliberately single-file (`biom_viewer/app.py`), so "one class per file" doesn't apply — but each responsibility below is still its own small class in that file, not a grab-bag of loose functions. Everything is type-hinted; `ViewState`/`SavedView` are frozen dataclasses (immutable value objects — a "view" is a snapshot, never mutated in place), `Workspace` is a plain mutable dataclass (its list of views changes over its lifetime).

```python
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
    def from_payload(cls, payload: dict) -> "ViewState": ...
    def to_payload(self) -> dict: ...


@dataclass(frozen=True)
class SavedView:
    """A named, timestamped ViewState the user explicitly saved."""
    name: str
    state: ViewState
    saved_at: str

    @classmethod
    def from_payload(cls, payload: dict) -> "SavedView": ...
    def to_payload(self) -> dict: ...


@dataclass
class Workspace:
    """Everything persisted for one dataset identity: the live 'current' state plus named saves."""
    current: ViewState | None
    views: list[SavedView]

    def upsert_view(self, view: SavedView) -> None: ...       # replace by name, else append
    def delete_view(self, name: str) -> None: ...
    def rename_view(self, old_name: str, new_name: str) -> None: ...  # raises ViewNameTakenError if new_name exists
    def find_view(self, name: str) -> SavedView | None: ...


class DatasetIdentity:
    """The table_id-or-fingerprint key described above, computed once and reused."""
    def __init__(self, key: str) -> None: ...

    @classmethod
    def from_table(cls, table: biom.Table) -> "DatasetIdentity": ...

    def __str__(self) -> str: ...


class WorkspaceStore:
    """Owns all read/write access to the app-support JSON file. Nothing else touches it."""
    def __init__(self, store_path: Path) -> None: ...

    def load_workspace(self, identity: DatasetIdentity) -> Workspace: ...   # missing/corrupt -> empty Workspace
    def save_workspace(self, identity: DatasetIdentity, workspace: Workspace) -> None: ...
```

`WorkspaceStore` owns a private `threading.Lock`, held for the full read-modify-write in `save_workspace` (protects same-process multi-window races; cross-process is out of scope — last write wins, acceptable for a single-user desktop app). `load_workspace`/`save_workspace` each stay under 10 lines by delegating the actual file I/O to private helpers (`_read_document`, `_write_document`) that guard-clause their way out on missing file / bad JSON / write failure and return/no-op rather than raising — persistence degrades to "nothing saved," the app keeps working exactly as it does today.

`Api` gets one `WorkspaceStore` instance and one memoized `DatasetIdentity` (computed once in `__init__`, from data `meta()` already loads — no extra table scan). Its new methods are thin orchestration, each ≤10 lines, translating the JS-boundary `dict` payloads into `ViewState`/`SavedView` at the edge and calling into `Workspace`/`WorkspaceStore` for everything else:

- `load_workspace() -> dict` — `self._store.load_workspace(self._identity)`, serialized back to `{"current": ..., "views": [...]}` for JS.
- `save_current(state: dict) -> None`
- `save_view(name: str, state: dict) -> None`
- `delete_view(name: str) -> None`
- `rename_view(old_name: str, new_name: str) -> None`

Each is a guard clause (build the value object) followed by one call into `Workspace` + one call into `WorkspaceStore.save_workspace` — no `else`, no branchy handler.

## Frontend behavior

- **Startup**: after `meta()` resolves, call `load_workspace()`. If `current` is non-null, apply it (extend `restoreState()` to also set `mode`, `pinnedObs`, `pinnedColFields`, not just `axisState`/field arrays) before the first `render()`.
- **Autosave**: every mutation that already calls `recordHistory()` — plus any `pinnedObs`/`pinnedColFields`/`mode` change — triggers a debounced (~1s) `save_current(snapshotState() + mode + pins)`. Reuses existing mutation choke points; no new instrumentation at individual call sites.
- **Views dropdown**: new toolbar control next to `#modeGroup` (`biom_viewer/app.py:598` area). Lists saved view names, current one highlighted; a "Save current as…" entry at the bottom opens the app's existing name-input modal pattern. Each row: double-click to rename (matching the app's existing dblclick-to-edit idiom), a small ✕ to delete. If `rename_view` rejects the new name (already taken), the rename input stays open with an inline error instead of closing — same pattern as any other name-collision validation in the app.
- **Switching**: before applying a clicked view, compare current `snapshotState()+mode+pins` against every saved view and against the state last loaded (on startup or on the last switch). No match → lightweight confirm ("Discard current filters?"). Match → switch immediately, no prompt. Applying a view calls `recordHistory()` first, so ⌘Z undoes a view switch like any other state change.

## Edge cases

- **Missing/empty `table_id`**: fingerprint fallback, see above.
- **Corrupted or unwritable store file**: `load_workspace()` returns the empty shape; `save_current`/`save_view` no-op with a console warning. Never blocks normal viewing/editing.
- **Saved view references a since-deleted field**: already handled — restoring `axisState` goes through the same `recomputeVisible`/render path undo already uses, which tolerates stale field references (see `deleteField`'s cleanup, `biom_viewer/app.py:1879`).

## Testing

New `test_*.py` (or extend `tests/test_app.py`), one test per behavior, each following Arrange/Act/Assert with blank lines between the three blocks:

- `DatasetIdentity.from_table`: `table_id` present → key equals it directly; `table_id` empty/missing → falls back to the fingerprint; two tables with identical shape+id-edges → same fingerprint (documents the accepted collision behavior, doesn't try to eliminate it).
- `Workspace.upsert_view` / `delete_view` / `rename_view` / `find_view`: pure in-memory behavior, no file I/O — new name appends, existing name overwrites in place, deleting a missing name is a no-op, renaming onto an already-taken name raises `ViewNameTakenError` and leaves both views untouched.
- `WorkspaceStore` round-trip: `save_workspace` then `load_workspace` for the same identity returns an equal `Workspace`; a corrupt/missing file on disk → `load_workspace` returns an empty `Workspace` without raising.

No JS test harness exists in this repo (consistent with the sort/filter spec) — the dropdown/switch/autosave UI is verified by hand in the running app via `dev_server.py`.
