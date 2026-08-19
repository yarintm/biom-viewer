# Row/Column Summary Panel — Design

## Context

BiomViewer is a lazy-loading native viewer for BIOM tables (pywebview + biom-format, single-file app in `biom_viewer/app.py`). It shows a paginated grid over a sparse abundance matrix, with three modes: `data` (observations × samples), `row` (observation metadata fields), `col` (sample metadata fields). Clicking a row/column header currently just selects it and shows its label in the `#selected` box.

This is sub-project 1 of a larger "Data Wrangler-inspired insights" effort. Full scope (data-cleaning operations, sort/filter, code export) is deliberately deferred — see the decomposition discussed in brainstorming. This spec covers only the read-only summary/insight panel.

## Trigger & UX

Clicking a row or column header selects it (existing behavior, unchanged). Once selected, a small icon appears next to the selected header (or in the `#selected` bar) — clicking it opens a "Summary" modal for that entire row or column, across *all* pages, not just the currently visible window.

Works in all three modes:
- **Data mode**, row header clicked → summary of that observation's abundance values across all samples.
- **Data mode**, column header clicked → summary of that sample's abundance values across all observations.
- **Row metadata mode**, column header clicked (a field) → summary of that field across all observations.
- **Col metadata mode**, row header clicked (a field) → summary of that field across all samples.

(Row-metadata-mode row headers and col-metadata-mode column headers are observation/sample ids, same as data mode — no new summary needed there beyond what data mode already covers for that axis.)

## Backend API

Three new methods on `Api`, computed in Python against `TABLE.matrix_data` directly — never densify the full matrix, only the requested vector:

```python
def row_summary(self, r):   # observation r, across all samples
def col_summary(self, c):   # sample c, across all observations
def field_summary(self, axis, field):  # axis: 'observation' | 'sample'
```

`row_summary`/`col_summary` slice one row/column out of the sparse matrix (`.tocsr()[r,:]` / `.tocsc()[:,c]`) and compute stats over just that vector — cheap regardless of table width.

**Data mode stats** (nonzero-value stats; zeros dominate BIOM tables and would drown min/mean if included):
- `n` (total length), `nonzero` (count), `sparsity` (% zero)
- `sum`, `min`, `max`, `mean`, `median` — over nonzero values only (all `None` if `nonzero == 0`)
- `histogram`: 10 equal-width buckets over the nonzero value range, each `{lo, hi, count}`

**Metadata field stats** (`field_summary`): pull the field's value across every entry on that axis, then auto-detect type:
- All present values are `int`/`float` (or numeric strings that parse cleanly) → treat as **numeric**: same min/max/mean/median/histogram shape as data mode, computed over present (non-missing) values.
- Otherwise → treat as **categorical**: top 10 values by frequency as `[{value, count}, ...]`, plus `other_count` (sum of counts beyond the top 10, 0 if none).
- Both shapes include `missing` (count of null/empty values) and `total` (entries on that axis).

Shared JSON shape so the frontend has one render path per type:

```
{ kind: 'numeric', n, missing, sum, min, max, mean, median, histogram: [{lo,hi,count}, ...] }
{ kind: 'categorical', n, missing, top: [{value, count}, ...], other_count }
```

## Frontend

- Selecting a header shows a small "ⓘ" affordance (reuses the existing `.tool` button style) next to the `#selected` box, active only when exactly one row or column is selected (not a cell).
- Clicking it calls the matching API method and opens a modal reusing the existing `#metaOverlay`/`#metaModal` pattern (same as the current table-info popup): header shows the row/column/field label, body shows a stats table (`dt`/`dd`, same as `openMeta`), then below it either:
  - a CSS bar-chart histogram (divs sized by `count/maxCount` %, one bar per bucket, labeled with bucket range), or
  - a frequency list (value + count per row, same `dt`/`dd` styling), with an "N other values" line if `other_count > 0`.
- No charting library — plain divs/CSS, consistent with the rest of the app.

## Testing

Extend `tests/test_app.py` with cases against a small constructed BIOM table:
- `row_summary`/`col_summary`: an all-zero row (nonzero=0, min/max/mean/median all `None`), a mixed sparse row (verify sum/min/max/mean/median/histogram bucket counts sum to `nonzero`).
- `field_summary`: a numeric metadata field, a categorical field with >10 distinct values (verify top-10 + `other_count`), and a field with missing values (verify `missing` count and that missing values are excluded from stats).
