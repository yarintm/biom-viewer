# Search: numeric data-cell value queries

## Problem

The search box (`web_script.py`) already matches sample IDs, observation/taxon
IDs, field names, and metadata field *values*. It has no way to find numeric
*abundance cells* in the data matrix (e.g. "show me every cell whose value is
under 1"), and clicking a metadata-value result doesn't jump to a data-matrix
cell — only to a metadata cell. There is also no in-product explanation of the
existing `field=value` query syntax, so a new syntax risks being just as
undiscoverable.

## Goals

- Let a user type a comparison like `<1`, `>0.5`, `=0` in the search box and
  see matching (observation, sample) cells from the currently loaded data
  matrix as results.
- Clicking a result jumps to and selects that exact cell in the `data` mode
  grid, identical to what happens when the user clicks the cell directly.
- Make the query syntax (both the new comparator form and the existing
  `field=value` form) discoverable in the UI.

## Non-goals

- No new persisted filter/view state. This is a search-and-jump feature, not
  a filter that hides rows/columns (that's the existing metadata filter
  pipeline, unrelated).
- No support for compound queries (e.g. `<1 and >0`) or ranges in one query.
- No changes to how metadata `field=value`/numeric-metadata filters work.

## Design

### Query detection

In `runSearch()` (`web_script.py:898`), before the existing
`parseFieldQuery()` check, test the trimmed query against:

```
/^(<=|>=|<|>|=)\s*(-?\d+\.?\d*)$/
```

A match means "cell-value query" — branch to the new cell-value search path
instead of the existing field/text search path. A non-match falls through to
existing behavior unchanged.

### Matching

Scan the raw data matrix (all raw row indices × raw col indices) and collect
`{type:'dataCell', rowRaw, colRaw, value}` for every cell whose value
satisfies the operator against the parsed number. This is computed fresh per
query rather than pre-indexed in `buildSearchIndex()`, since a numeric
predicate isn't enumerable ahead of time the way a fixed metadata value is.
At this app's scale (tens of thousands to low hundreds of thousands of
cells) a full scan per keystroke-debounced query is expected to stay well
under 100ms; no incremental/indexed structure is being added for this.

### Sorting and capping

- `<` / `<=`: sort matches descending by value (closest to the threshold
  first) and take the top ~200.
- `>` / `>=`: sort matches descending by value (largest first) and take the
  top ~200.
- `=`: no sort needed (exact matches are typically few); cap at ~200 anyway
  for safety.
- If more than ~200 matches exist, show the same "N more matched — refine
  your query" footer style other tabs already use for overflow, rather than
  a new UI pattern.

### New "Cells" tab

Add `'cells'` to `SEARCH_KINDS` (`web_script.py:860`) as a tab labeled
"Cells". Like other kind-specific tabs, it's populated (and shown) only when
its category has current results — i.e. only when the query parsed as a
cell-value predicate. It appears alongside "All" the same way "Values"
does today.

### Result rendering

Reuse `searchRowHtml()`'s existing row shape. Label format:
`{rowLabel} | {colLabel} = {value}` — this matches the label already shown
when a user manually clicks a data cell (`web_script.py:1417`). No substring
`<mark>` highlighting is applied to these rows since the match is numeric,
not textual.

### Jump-to-cell

Add a `dataCell` branch to `jumpTo()` (`web_script.py:1003`):

1. `setMode('data')`
2. Resolve the row via `selectObservationRow(entry.rowRaw)` (handles the
   pinned-row special case the same way existing row jumps do).
3. Resolve the column via `resolveAxisPosition('sample', entry.colRaw)`,
   mirroring the existing `colValue` branch (`web_script.py:1034-1039`),
   setting `colPage` as needed.
4. Set `selR`/`selC` to the resolved positions.
5. Call `showSelected()` with the same label/value format the direct-click
   handler already uses (`web_script.py:1417`), so the end state is
   identical to a manual click on that cell.

### Discoverability

Add a small "?" affordance next to the search input (near `app.py:674`)
with a tooltip/title text:

> Search taxa, samples, fields, or values. For abundance cells, use
> comparisons like `<1`, `>0.5`, `=0`.

This also documents the pre-existing `field=value` syntax, which currently
has no in-product explanation anywhere.

## Testing

Manual verification only (no test harness exists for this UI layer today):

1. Open a `.biom` file, type `<1` in search — confirm a "Cells" tab appears
   with results sorted descending by value, capped with an overflow note if
   applicable.
2. Type `>0.02`, confirm descending-by-value results.
3. Type `=0`, confirm exact-match results.
4. Click a result — confirm the grid switches to `data` mode, scrolls to and
   selects that exact (row, column) cell, and the detail panel shows the same
   label/value as a direct click on that cell would.
5. Confirm existing search behavior (`field=value`, plain text, sample/taxon
   ID search) is unaffected.
6. Hover/click the new "?" affordance, confirm the tooltip text is legible
   and accurate.

## Files touched

- `biom_viewer/web_script.py` — query detection, matching, sorting/capping,
  new tab, `jumpTo()` branch.
- `biom_viewer/app.py` — "?" help affordance markup near the search input.

No new files, no new dependencies, no persistence/schema changes.
