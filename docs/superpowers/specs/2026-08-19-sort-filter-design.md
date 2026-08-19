# Sort & Filter by Metadata Field — Design

## Context

BiomViewer is a lazy-loading native viewer for BIOM tables (pywebview + biom-format, single-file app in `biom_viewer/app.py`). It shows a paginated grid over a sparse abundance matrix, with three modes: `data` (observations × samples), `row` (observation metadata fields), `col` (sample metadata fields).

This is sub-project 2 of the "Data Wrangler-inspired insights" effort. Sub-project 1 (read-only summary panel, `2026-08-19-summary-panel-design.md`) is done. This spec covers sort and filter by metadata field value. Sort/filter by raw abundance values, by id strings, and code export remain out of scope and deferred to later sub-projects.

## Scope

- Sort and filter apply to **metadata fields only** — a field visible as a column header in `row`/`data` mode (observation metadata) or a row header in `col` mode (sample metadata).
- State is **per-axis** (observation, sample), not per-mode: an observation-axis sort/filter set while in `row` mode also applies to `data` mode's rows, since both are views over the same observation axis. Switching modes never resets this state.
- **One active sort field per axis** (asc/desc/off). Setting a new sort field on an axis replaces the previous one.
- **Multiple simultaneous filters per axis**, AND'ed together. Each filter targets one field.
- Filter semantics: categorical fields use case-insensitive substring match; numeric fields use an inclusive min/max range. A field's type (numeric vs categorical) reuses the same auto-detection `field_summary` already does (`_is_numeric`).

## Client-side index computation

`meta()` already ships the full `row_ids`/`col_ids`/`row_metadata`/`col_metadata` arrays to the client on load. Sort/filter is computed entirely client-side as an index permutation — no backend sort/filter logic needed:

1. Start from `[0..n-1]` for the axis.
2. Apply all active filters for that axis (AND) → filtered index array.
3. If a sort field is active for that axis, stable-sort the filtered index array by that field's value (numeric compare if the field is numeric, else locale string compare), respecting `sortDir`.
4. Result is `visibleIndices[axis]` — pagination walks this array instead of `[0..n-1]` directly. Page N's row/col range becomes `visibleIndices.slice(page*perPage, (page+1)*perPage)`.

Recomputed whenever a filter or sort changes; cheap (single pass + sort) even at ~1e5 ids since it's the same order of data `meta()` already sends.

## Backend change

`data_window(r0, r1, c0, c1)` currently assumes contiguous ranges — a page's worth of rows/cols always sits at consecutive matrix indices. Once either axis is filtered/sorted, the visible page maps to an arbitrary (unsorted, non-contiguous) list of matrix indices instead.

Add a sibling API method:

```python
def data_window_idx(row_idxs, col_idxs):
    # Gather arbitrary row/col index lists from the sparse matrix.
    # row_idxs, col_idxs: lists of int matrix indices (any order, may repeat-free assume unique).
```

Implementation: fancy-index the sparse matrix (`TABLE.matrix_data.tocsr()[row_idxs, :].tocsc()[:, col_idxs]`), densify only that submatrix, return as nested lists (same shape/shape-safety as `data_window`).

The frontend calls `data_window` (existing, contiguous) when neither axis has an active sort/filter for the current page fetch, and `data_window_idx` when either does. This keeps the common unsorted/unfiltered case on the cheaper contiguous-slice path.

## Frontend UI

- **Sort trigger:** clicking a field header selects it (existing behavior). A small sort-arrow icon appears next to the existing summary "ⓘ" affordance, active only when exactly one row/column header is selected. Clicking it cycles: unsorted → ascending → descending → unsorted. Setting a sort on a new field for that axis clears any previous sort field on that axis.
- **Filter trigger:** a filter icon next to the same affordance opens a small inline input directly under that field's header — a text box for categorical fields, a min/max number pair for numeric fields. Enter applies it; the input stays open showing the active value until cleared. Multiple fields on the same axis can each have their own open/applied filter simultaneously.
- **Status chips:** a chip strip near the top toolbar shows active state per axis, e.g. `sample: 3 filters · sorted by depth ▼` with a per-axis `[x]` to clear everything on that axis, and each filter chip individually removable. Reuses the app's existing small-button/chip visual style (no new visual language).
- Changing any sort/filter resets that axis's current page to 0 and updates the displayed row/col count (e.g. "42 of 120 samples" in the existing count/position readout).
- Empty filtered result (0 matching rows/cols) shows the grid's existing empty-state treatment rather than a special-cased message.

## Testing

Extend `tests/test_app.py`:
- `data_window_idx`: arbitrary unsorted index list, single-element list, an index list covering the full axis (should match `data_window`'s full-range output), mismatched-length row/col guard.
- No backend test coverage for the sort/filter index computation itself — it's pure frontend JS and this repo has no JS test harness. Manual verification via the dev server (`dev_server.py`) covers it, consistent with how the summary panel's frontend logic was verified.
