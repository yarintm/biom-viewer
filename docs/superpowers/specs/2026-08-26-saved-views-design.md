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
    "current": { "mode": "data", "axisState": {...}, "pinnedObs": [...], "pinnedColFields": [...] },
    "views": [
      { "name": "High abundance only", "mode": "data", "axisState": {...},
        "pinnedObs": [...], "pinnedColFields": [...], "savedAt": "2026-08-26T10:00:00" }
    ]
  }
}
```

Identity key derivation, computed once per `Api` instance from data already loaded in `meta()`:

1. `table.table_id` if present and non-empty (BIOM's own embedded identifier — stable across move/rename/copy, since it's baked into the HDF5 content, not the filesystem path).
2. Fallback fingerprint if `table_id` is missing/empty: a hash of `(shape, row_ids[:5], row_ids[-5:], col_ids[:5], col_ids[-5:])` — cheap, no extra pass over the matrix, just the id lists `meta()` already sent.

Collision risk (two unrelated files fingerprint-identically) is accepted as a display-only annoyance — worst case you see an unrelated file's saved views, nothing about the actual `.biom` data is ever read from or written to based on this key.

## Python API surface (`Api`, `biom_viewer/app.py`)

New methods, all guarded by a module-level `threading.Lock` around read-modify-write of the JSON store (protects against same-process multi-window races; cross-process is out of scope — last write wins, acceptable for a single-user desktop app):

- `load_workspace()` → `{"current": {...} | None, "views": [...]}` for this file's identity key, `{"current": None, "views": []}` if never seen.
- `save_current(state)` → upserts the `current` slot.
- `save_view(name, state)` → upsert into `views` by name (saving under an existing name overwrites it — this doubles as "update a saved view").
- `delete_view(name)`, `rename_view(old, new)`.

All five catch and swallow I/O/JSON errors (corrupt store, disk full, unwritable path) rather than raising into the UI — persistence degrades to a no-op, the app keeps working exactly as it does today. Follow `clean-code-style` conventions when implementing: guard clauses for the error/missing-file paths, small single-purpose methods rather than one large branchy handler, descriptive names over comments explaining *what* the code does.

## Frontend behavior

- **Startup**: after `meta()` resolves, call `load_workspace()`. If `current` is non-null, apply it (extend `restoreState()` to also set `mode`, `pinnedObs`, `pinnedColFields`, not just `axisState`/field arrays) before the first `render()`.
- **Autosave**: every mutation that already calls `recordHistory()` — plus any `pinnedObs`/`pinnedColFields`/`mode` change — triggers a debounced (~1s) `save_current(snapshotState() + mode + pins)`. Reuses existing mutation choke points; no new instrumentation at individual call sites.
- **Views dropdown**: new toolbar control next to `#modeGroup` (`biom_viewer/app.py:598` area). Lists saved view names, current one highlighted; a "Save current as…" entry at the bottom opens the app's existing name-input modal pattern. Each row: double-click to rename (matching the app's existing dblclick-to-edit idiom), a small ✕ to delete.
- **Switching**: before applying a clicked view, compare current `snapshotState()+mode+pins` against every saved view and against the state last loaded (on startup or on the last switch). No match → lightweight confirm ("Discard current filters?"). Match → switch immediately, no prompt. Applying a view calls `recordHistory()` first, so ⌘Z undoes a view switch like any other state change.

## Edge cases

- **Missing/empty `table_id`**: fingerprint fallback, see above.
- **Corrupted or unwritable store file**: `load_workspace()` returns the empty shape; `save_current`/`save_view` no-op with a console warning. Never blocks normal viewing/editing.
- **Saved view references a since-deleted field**: already handled — restoring `axisState` goes through the same `recomputeVisible`/render path undo already uses, which tolerates stale field references (see `deleteField`'s cleanup, `biom_viewer/app.py:1879`).

## Testing

New `test_*.py` (or extend `tests/test_app.py`) covering the non-trivial logic:
- Identity key derivation: `table_id` present → used directly; `table_id` empty/missing → fingerprint fallback; two tables with identical shape+id-edges → same fingerprint (documents the accepted collision behavior).
- JSON store round-trip: `save_current` → `load_workspace()` returns it back unchanged; `save_view`/`rename_view`/`delete_view` mutate `views` correctly; corrupt file on disk → `load_workspace()` returns empty shape without raising.

No JS test harness exists in this repo (consistent with the sort/filter spec) — the dropdown/switch/autosave UI is verified by hand in the running app via `dev_server.py`.
