# Sort & Filter by Metadata Field Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user sort and filter the observation/sample axes by metadata field value, with the resulting order/filter applied everywhere that axis is displayed (data mode and both metadata modes).

**Architecture:** Sort/filter state and the resulting index permutation are computed entirely client-side in the existing single-file app (`biom_viewer/app.py`), since the frontend already holds the full id/metadata arrays after `meta()` loads. Only the paginated data-cell fetch needs a new backend method (`data_window_idx`) to gather non-contiguous matrix indices; everything else (labels, metadata cells, stat fetches) is redirected through two small index-mapping functions.

**Tech Stack:** Python (biom-format, scipy sparse matrices) backend exposed via pywebview `Api`; vanilla JS/CSS frontend embedded in the same file. pytest for backend tests.

**Spec:** `docs/superpowers/specs/2026-08-19-sort-filter-design.md`

**Plan-time clarification on the sort/filter trigger:** the spec's brainstorming phase said "click the field header again" to cycle sort, by analogy with the existing click-to-select behavior. The shipped code already binds `dblclick` on every header to `toggleSummary()` (the stats-strip toggle from sub-project 1), so overloading plain `click` would fire ambiguously alongside it. This plan instead adds small inline icons (`▲/▼` sort, `⏷` filter) rendered inside the header cell itself, visible only on headers that are metadata fields (column headers in `row` mode, row headers in `col` mode) — same affordance intent as the spec, mechanically distinct from both single- and double-click on the cell body.

---

## File Structure

- Modify: `biom_viewer/app.py`
  - Backend: add `data_window_idx(row_idxs, col_idxs)` function + `Api.data_window_idx` method, near the existing `data_window`.
  - Frontend JS: add sort/filter state, index-mapping helpers, and UI wiring, near the existing axis-helper functions (`rowsTotal`/`colsTotal`/`rowLabel`/`colLabel`/`metaCellAt`) and inside `render()`.
  - Frontend CSS: add rules for the new header icons, inline filter input, and status chip strip.
- Modify: `tests/test_app.py` — add `data_window_idx` test cases.

No new files — this codebase is deliberately a single-file app; splitting it out is not part of this feature's scope.

---

### Task 1: Backend `data_window_idx`

**Files:**
- Modify: `biom_viewer/app.py:89-94` (right after `data_window`)
- Modify: `biom_viewer/app.py:184-197` (`Api` class)
- Test: `tests/test_app.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_app.py`, after `test_data_window_clamps_out_of_range_bounds` (currently ending around line 47):

```python
def test_data_window_idx_arbitrary_unsorted_indices():
    app.TABLE = make_table()
    # rows [2, 0] (reversed, non-contiguous), cols [3, 1]
    assert app.data_window_idx([2, 0], [3, 1]) == [
        [0, 0],
        [0, 1],
    ]


def test_data_window_idx_single_element():
    app.TABLE = make_table()
    assert app.data_window_idx([1], [3]) == [[5]]


def test_data_window_idx_full_axis_matches_data_window():
    app.TABLE = make_table()
    assert app.data_window_idx([0, 1, 2], [0, 1, 2, 3]) == app.data_window(0, 3, 0, 4)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_app.py -k data_window_idx -v`
Expected: FAIL with `AttributeError: module 'biom_viewer.app' has no attribute 'data_window_idx'`

- [ ] **Step 3: Implement `data_window_idx`**

In `biom_viewer/app.py`, immediately after the existing `data_window` function (ends at line 94):

```python
def data_window_idx(row_idxs, col_idxs):
    # Gather arbitrary (unsorted, non-contiguous) row/col index lists —
    # used once either axis has an active sort or filter, since the visible
    # page no longer maps to a contiguous matrix range. Densify only the
    # requested submatrix, same as data_window.
    sub = TABLE.matrix_data.tocsr()[row_idxs, :].tocsc()[:, col_idxs]
    return sub.toarray().tolist()
```

Add the matching `Api` method right after `data_window` in the `Api` class (`biom_viewer/app.py:187-188`):

```python
    def data_window_idx(self, row_idxs, col_idxs):
        return data_window_idx(row_idxs, col_idxs)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_app.py -k data_window_idx -v`
Expected: 3 passed

- [ ] **Step 5: Run full backend suite**

Run: `python3 -m pytest tests/ -q`
Expected: all passing (17 tests: 14 existing + 3 new)

- [ ] **Step 6: Wire the new endpoint into the dev server shim**

`scripts/dev_server.py` fronts the app's real `PAGE` with a fetch-based stand-in for the pywebview bridge (used for manual browser verification in later tasks). It needs to expose `data_window_idx` the same way it already exposes `data_window`.

In `scripts/dev_server.py`, add to the `SHIM`'s `window.pywebview.api` object (after the existing `data_window` line):

```javascript
    data_window_idx: (row_idxs, col_idxs) => post('/api/data_window_idx', {row_idxs, col_idxs}),
```

And add to the `API` dict (after the existing `/api/data_window` entry):

```python
    "/api/data_window_idx": lambda body: bv.data_window_idx(body["row_idxs"], body["col_idxs"]),
```

- [ ] **Step 7: Commit**

```bash
git add biom_viewer/app.py tests/test_app.py scripts/dev_server.py
git commit -m "Add data_window_idx for fetching non-contiguous row/col index lists"
```

---

### Task 2: Frontend state model and index-mapping helpers

**Files:**
- Modify: `biom_viewer/app.py:498-499` (mode/field globals) and `biom_viewer/app.py:546-568` (axis helpers)

- [ ] **Step 1: Add sort/filter state globals**

Immediately after `let rowFields=[], colFields=[];` (`biom_viewer/app.py:499`):

```javascript
// Sort/filter state lives per underlying axis identity (observation, sample),
// not per mode -- a filter set while viewing row-metadata mode still applies
// to the same axis's rows in data mode. `field_summary`'s numeric/categorical
// detection is reused for filter input type; see fieldIsNumeric().
let axisState = {
  observation: { sortField: null, sortDir: 0, filters: [] }, // sortDir: 0=off, 1=asc, -1=desc
  sample: { sortField: null, sortDir: 0, filters: [] },
};
// filters entries: {field, kind:'numeric', min, max} or {field, kind:'categorical', text}

// Computed visible-index arrays. null = identity (no active sort/filter for
// that axis) -- the common case stays on the cheap contiguous data_window path.
let visObs = null, visSample = null;

function obsAt(i){ return visObs ? visObs[i] : i; }
function sampleAt(j){ return visSample ? visSample[j] : j; }
```

- [ ] **Step 2: Rewrite `rowsTotal`/`colsTotal`/`rowLabel`/`colLabel`/`metaCellAt` to go through the mapping**

Replace `biom_viewer/app.py:546-568`:

```javascript
function rowsTotal(){ return mode==='col' ? colFields.length : (visObs ? visObs.length : meta.rows); }
function colsTotal(){ return mode==='row' ? rowFields.length : (visSample ? visSample.length : meta.cols); }
function rowLabel(i){ return mode==='col' ? colFields[i] : meta.row_ids[obsAt(i)]; }
function colLabel(j){ return mode==='row' ? rowFields[j] : meta.col_ids[sampleAt(j)]; }

function formatMetaValue(v){
  if(Array.isArray(v)) v = v.length ? v.join(', ') : null;
  else if(v && typeof v === 'object') v = Object.entries(v).map(([k,x])=>`${k}=${x}`).join(', ');
  if(v===null || v===undefined || v==='') return {text:'—', cls:'mv-empty'};
  return {text:v, cls:'mv'};
}

function metaCellAt(i, j){
  // i = row index (grid row), j = col index (grid col)
  if(mode==='row'){
    // row axis = observation obsAt(i), col axis = field j (fields unaffected by filters)
    const entry = meta.row_metadata && meta.row_metadata[obsAt(i)];
    return entry ? entry[rowFields[j]] : null;
  }
  // mode==='col': row axis = field i (unaffected), col axis = sample sampleAt(j)
  const entry = meta.col_metadata && meta.col_metadata[sampleAt(j)];
  return entry ? entry[colFields[i]] : null;
}
```

(`formatMetaValue` is unchanged — included above only so the replacement block is contiguous and unambiguous to apply.)

- [ ] **Step 3: Add the filter/sort computation function**

Add after the block above:

```javascript
function fieldIsNumeric(axis, field){
  const entries = axis==='observation' ? meta.row_metadata : meta.col_metadata;
  const present = (entries||[]).map(e=>e && e[field]).filter(v=>v!==null && v!==undefined && v!=='');
  if(!present.length) return false;
  return present.every(v=>typeof v==='number' || (typeof v==='string' && v.trim()!=='' && !isNaN(Number(v))));
}

// Recompute visObs/visSample from current axisState. Called whenever a sort
// or filter changes. Leaves the axis untouched (null) if nothing is active,
// keeping the cheap contiguous fetch path for the common case.
function recomputeVisible(axis){
  const state = axisState[axis];
  const entries = axis==='observation' ? meta.row_metadata : meta.col_metadata;
  const total = axis==='observation' ? meta.rows : meta.cols;
  const active = state.filters.length>0 || state.sortDir!==0;
  let result = null;
  if(active){
    let idxs = [];
    for(let i=0;i<total;i++) idxs.push(i);
    state.filters.forEach(f=>{
      idxs = idxs.filter(i=>{
        const entry = entries && entries[i];
        const v = entry ? entry[f.field] : null;
        if(v===null || v===undefined || v==='') return false;
        if(f.kind==='numeric'){
          const n = Number(v);
          if(f.min!==null && n<f.min) return false;
          if(f.max!==null && n>f.max) return false;
          return true;
        }
        return String(v).toLowerCase().includes(f.text.toLowerCase());
      });
    });
    if(state.sortDir!==0){
      const field = state.sortField;
      const numeric = fieldIsNumeric(axis, field);
      idxs = idxs.slice().sort((a,b)=>{
        const va = entries[a] ? entries[a][field] : null;
        const vb = entries[b] ? entries[b][field] : null;
        let cmp;
        if(numeric) cmp = Number(va) - Number(vb);
        else cmp = String(va).localeCompare(String(vb));
        return state.sortDir * cmp;
      });
    }
    result = idxs;
  }
  if(axis==='observation') visObs = result; else visSample = result;
}
```

- [ ] **Step 4: Commit**

```bash
git add biom_viewer/app.py
git commit -m "Add per-axis sort/filter state and index-mapping helpers"
```

No test run here — this step only adds functions, nothing calls them yet, and this file has no JS test harness (per the spec's testing section).

---

### Task 3: Wire the data/stat fetch path through the index mapping

**Files:**
- Modify: `biom_viewer/app.py:777-819` (`render()`, data fetch section)
- Modify: `biom_viewer/app.py:923-927` (`colStatsFetch`)

- [ ] **Step 1: Update the data-window fetch in `render()`**

Replace `biom_viewer/app.py:789` (`const data = mode==='data' ? await window.pywebview.api.data_window(r0, r1, c0, c1) : null;`) with:

```javascript
  let data = null;
  if(mode==='data'){
    if(visObs || visSample){
      const rowIdxs = []; for(let i=r0;i<r1;i++) rowIdxs.push(obsAt(i));
      const colIdxs = []; for(let j=c0;j<c1;j++) colIdxs.push(sampleAt(j));
      data = await window.pywebview.api.data_window_idx(rowIdxs, colIdxs);
    } else {
      data = await window.pywebview.api.data_window(r0, r1, c0, c1);
    }
  }
```

- [ ] **Step 2: Map `colStatsFetch`'s sample index through `sampleAt`**

Replace `biom_viewer/app.py:923-927`:

```javascript
function colStatsFetch(j){
  return mode==='row'
    ? window.pywebview.api.field_summary('observation', rowFields[j])
    : window.pywebview.api.col_summary(sampleAt(j));
}
```

`rowFields[j]` is unchanged — in `row` mode `j` indexes the (unfiltered) field list, not the sample axis.

- [ ] **Step 3: Update the `data` mode cell click handler's value lookup**

In the render loop's data-mode cell branch (`biom_viewer/app.py:870-879`), `data[r-r0][c-c0]` already indexes into whatever `data` came back — since `data` is now built from the same `r0..r1`/`c0..c1` loop bounds regardless of which fetch path was used, no change needed there. Confirm by inspection, no edit required.

- [ ] **Step 4: Manual verification**

Run: `python3 scripts/dev_server.py .venv/lib/python3.14/site-packages/examples/rich_sparse_otu_table.biom` (a real BIOM file already present via the biom-format package's bundled examples — no fixture needs to be created) and open `http://127.0.0.1:8765/` in a browser. Confirm the grid still renders identically to before this change in all three modes, with no sort/filter active yet (`visObs`/`visSample` are still always `null` at this point since nothing sets them until Task 4/5). This is a regression check only.

- [ ] **Step 5: Commit**

```bash
git add biom_viewer/app.py
git commit -m "Route data-window and column-stat fetches through the sort/filter index mapping"
```

---

### Task 4: Sort UI — header icon, cycling, chip removal for sort

**Files:**
- Modify: `biom_viewer/app.py:825-839` (column header rendering, `row`/`data` modes)
- Modify: `biom_viewer/app.py:848-866` (row header rendering, `col` mode)
- Modify: `biom_viewer/app.py` CSS block (`biom_viewer/app.py:280-341` region)

- [ ] **Step 1: Add sort-icon markup to column headers when they're fields (`row` mode)**

In the column-header loop (`biom_viewer/app.py:825-839`), the header only needs the icon when `mode==='row'` (the field is on the column axis there, describing the observation/row axis). Replace the loop body:

```javascript
  for(let c=c0;c<c1;c++){
    const label = colLabel(c);
    const h = document.createElement('div');
    h.className = 'cell hdr colhdr';
    h.title = label;
    h.dataset.c = c;
    if(mode==='row'){
      h.innerHTML = `<span class="hdr-label">${escapeHtml(label)}</span>${axisControlsHtml('observation', label)}`;
    } else {
      h.textContent = label;
    }
    h.addEventListener('click', (e)=>{
      if(e.target.closest('.axis-ctl')) return; // icon clicks handled separately below
      selR=null; selC=c;
      showSelected(label);
      applyHighlight();
    });
    h.addEventListener('dblclick', ()=>{ toggleSummary(); });
    grid.appendChild(h);
  }
```

- [ ] **Step 2: Add sort-icon markup to row headers when they're fields (`col` mode)**

In the row-header block (`biom_viewer/app.py:848-866`), the icon applies when `mode==='col'` (field on the row axis, describing the sample/column axis). The existing block already branches on `stripOnRows()` for the summary-strip label; add the axis controls alongside the plain-label branch (stats-strip case already carries its own label bar and is not extended here — sorting/filtering while the strip is open is out of scope, see Task 6's note):

```javascript
  for(let r=r0;r<r1;r++){
    const label = rowLabel(r);
    const rh = document.createElement('div');
    rh.className = 'cell rh';
    if(stripOnRows()){
      rh.classList.add('rh-stats');
      rh.innerHTML = `<div class="stat-line rh-label">${escapeHtml(label)}</div>` + statCellHtml(rowStats[r-r0]);
    } else if(mode==='col'){
      rh.innerHTML = `<span class="hdr-label">${escapeHtml(label)}</span>${axisControlsHtml('sample', label)}`;
    } else {
      rh.textContent = label;
    }
    rh.title = label;
    rh.dataset.r = r;
    rh.addEventListener('click', (e)=>{
      if(e.target.closest('.axis-ctl')) return;
      selR=r; selC=null;
      showSelected(label);
      applyHighlight();
    });
    rh.addEventListener('dblclick', ()=>{ toggleSummary(r); });
    grid.appendChild(rh);
    // ... existing inner column loop unchanged below this point
```

- [ ] **Step 3: Add `axisControlsHtml` and the click delegation that drives it**

Add near `colStatsFetch` (after `biom_viewer/app.py:927`, the function this plan already touched in Task 3):

```javascript
function axisControlsHtml(axis, field){
  const st = axisState[axis];
  const arrow = st.sortField===field ? (st.sortDir===1 ? '▲' : st.sortDir===-1 ? '▼' : '⇅') : '⇅';
  const sortOn = st.sortField===field && st.sortDir!==0;
  const filterOn = st.filters.some(f=>f.field===field);
  return `<span class="axis-ctl">` +
    `<button class="axis-sort${sortOn?' on':''}" data-axis="${axis}" data-field="${escapeHtml(field)}" title="Sort by ${escapeHtml(field)}">${arrow}</button>` +
    `<button class="axis-filter${filterOn?' on':''}" data-axis="${axis}" data-field="${escapeHtml(field)}" title="Filter by ${escapeHtml(field)}">⏷</button>` +
  `</span>`;
}

function cycleSort(axis, field){
  const st = axisState[axis];
  if(st.sortField!==field){ st.sortField=field; st.sortDir=1; }
  else if(st.sortDir===1){ st.sortDir=-1; }
  else if(st.sortDir===-1){ st.sortField=null; st.sortDir=0; }
  else { st.sortDir=1; }
  recomputeVisible(axis);
  if(axis==='observation'){ rowPage=0; } else { colPage=0; }
  render();
  renderAxisChips();
}

document.getElementById('grid').addEventListener('click', (e)=>{
  const sortBtn = e.target.closest('.axis-sort');
  if(sortBtn){ e.stopPropagation(); cycleSort(sortBtn.dataset.axis, sortBtn.dataset.field); return; }
  const filterBtn = e.target.closest('.axis-filter');
  if(filterBtn){ e.stopPropagation(); openFilterInput(filterBtn.dataset.axis, filterBtn.dataset.field, filterBtn); return; }
});
```

(`openFilterInput` and `renderAxisChips` are implemented in Tasks 5 and 6 respectively — this step will not be manually testable in isolation until those land; that's expected for this task's icon/sort half, which is independently testable via the sort arrows alone. If executing tasks in strict order with verification after each, stub `openFilterInput` as a no-op and `renderAxisChips` as a no-op in this step, then replace both in their respective tasks — do not leave TODO comments, just a minimal real no-op body: `function openFilterInput(){}` / `function renderAxisChips(){}`.)

- [ ] **Step 4: CSS for the header icons**

Add to the stylesheet, near `.hdr.colhdr:hover{...}` (`biom_viewer/app.py:286`):

```css
  .hdr-label{overflow:hidden;text-overflow:ellipsis}
  .axis-ctl{display:inline-flex;gap:2px;margin-left:4px;vertical-align:middle}
  .axis-ctl button{background:none;border:none;color:var(--dim);cursor:pointer;font-size:calc(var(--fs)*0.95);
             padding:0 2px;line-height:1}
  .axis-ctl button:hover{color:var(--fg)}
  .axis-ctl button.on{color:var(--accent);font-weight:700}
```

- [ ] **Step 5: Manual verification**

Run `python3 scripts/dev_server.py .venv/lib/python3.14/site-packages/examples/rich_sparse_otu_table.biom` and open `http://127.0.0.1:8765/`, switch to `row` mode, click a field column header's sort arrow three times: confirm it cycles ascending → descending → off, the observation row order changes accordingly (visible via row-header ids), and switching to `data` mode preserves that same row order. Repeat for `col` mode's row-header sort affecting the sample/column order.

- [ ] **Step 6: Commit**

```bash
git add biom_viewer/app.py
git commit -m "Add sort-by-field header icon, cycling through asc/desc/off per axis"
```

---

### Task 5: Filter UI — inline input under the header

**Files:**
- Modify: `biom_viewer/app.py` (add `openFilterInput`, replacing the Task 4 stub)
- Modify: `biom_viewer/app.py` CSS block

- [ ] **Step 1: Implement `openFilterInput`**

Replace the `function openFilterInput(){}` stub added in Task 4 with:

```javascript
function closeFilterPopover(){
  const existing = document.getElementById('filterPopover');
  if(existing) existing.remove();
}

function openFilterInput(axis, field, anchorEl){
  closeFilterPopover();
  const st = axisState[axis];
  const existing = st.filters.find(f=>f.field===field);
  const numeric = fieldIsNumeric(axis, field);
  const pop = document.createElement('div');
  pop.id = 'filterPopover';
  const rect = anchorEl.getBoundingClientRect();
  pop.style.left = rect.left + 'px';
  pop.style.top = (rect.bottom + 4) + 'px';
  if(numeric){
    pop.innerHTML = `<input class="fp-min" type="number" placeholder="min" value="${existing?existing.min ?? '':''}">` +
      `<input class="fp-max" type="number" placeholder="max" value="${existing?existing.max ?? '':''}">` +
      `<button class="fp-apply">Apply</button>` +
      (existing ? `<button class="fp-clear">Clear</button>` : '');
  } else {
    pop.innerHTML = `<input class="fp-text" type="text" placeholder="contains…" value="${existing?escapeHtml(existing.text):''}">` +
      `<button class="fp-apply">Apply</button>` +
      (existing ? `<button class="fp-clear">Clear</button>` : '');
  }
  document.body.appendChild(pop);
  pop.querySelector(numeric ? '.fp-min' : '.fp-text').focus();

  const apply = ()=>{
    const filters = st.filters.filter(f=>f.field!==field);
    if(numeric){
      const minV = pop.querySelector('.fp-min').value;
      const maxV = pop.querySelector('.fp-max').value;
      filters.push({field, kind:'numeric', min: minV===''?null:Number(minV), max: maxV===''?null:Number(maxV)});
    } else {
      const text = pop.querySelector('.fp-text').value.trim();
      if(text) filters.push({field, kind:'categorical', text});
    }
    st.filters = filters;
    recomputeVisible(axis);
    if(axis==='observation'){ rowPage=0; } else { colPage=0; }
    closeFilterPopover();
    render();
    renderAxisChips();
  };
  pop.querySelector('.fp-apply').onclick = apply;
  const clearBtn = pop.querySelector('.fp-clear');
  if(clearBtn) clearBtn.onclick = ()=>{
    st.filters = st.filters.filter(f=>f.field!==field);
    recomputeVisible(axis);
    if(axis==='observation'){ rowPage=0; } else { colPage=0; }
    closeFilterPopover();
    render();
    renderAxisChips();
  };
  pop.addEventListener('keydown', e=>{ if(e.key==='Enter') apply(); if(e.key==='Escape') closeFilterPopover(); });
}

document.addEventListener('click', (e)=>{
  const pop = document.getElementById('filterPopover');
  if(pop && !pop.contains(e.target) && !e.target.closest('.axis-filter')) closeFilterPopover();
});
```

- [ ] **Step 2: CSS for the popover**

Add to the stylesheet:

```css
  #filterPopover{position:fixed;z-index:30;background:var(--panel-bg);border:1px solid var(--border);
             border-radius:6px;box-shadow:0 8px 24px rgba(0,0,0,.3);padding:6px;display:flex;gap:4px;align-items:center}
  #filterPopover input{width:70px;box-sizing:border-box;background:var(--input-bg);color:var(--fg);
             border:1px solid var(--input-border);border-radius:4px;padding:3px 6px;font-size:12px}
  #filterPopover input.fp-text{width:140px}
  #filterPopover button{background:var(--panel-bg);color:var(--fg);border:1px solid var(--input-border);
             border-radius:4px;padding:3px 8px;font-size:12px;cursor:pointer}
```

- [ ] **Step 3: Manual verification**

Run the dev server. In `row` mode, open a numeric field's filter, set min/max, apply — confirm the observation row count drops and only matching rows show, in both `row` mode and after switching to `data` mode. Repeat for a categorical field's substring filter. Confirm two filters on the same axis (different fields) AND together. Confirm the empty-result case (filter matching nothing) shows the grid's existing empty state rather than erroring.

- [ ] **Step 4: Commit**

```bash
git add biom_viewer/app.py
git commit -m "Add inline filter popover for metadata fields, AND'ed per axis"
```

---

### Task 6: Status chip strip

**Files:**
- Modify: `biom_viewer/app.py:349-363` (`#toolbar`) — add a chip container
- Modify: `biom_viewer/app.py` (add `renderAxisChips`, replacing the Task 4 stub)
- Modify: `biom_viewer/app.py` CSS block

- [ ] **Step 1: Add the chip container markup**

In the `#info` block, right after the closing `</span>` of `#toolbar` (`biom_viewer/app.py:363`), before `</div>` (line 364):

```html
  </span>
</div>
<div id="axisChips"></div>
```

(This replaces the plan's literal target — insert the new `<div id="axisChips"></div>` as a sibling of `#info`, not inside it, so it can wrap onto its own line without disturbing the toolbar layout.)

- [ ] **Step 2: Implement `renderAxisChips`**

Replace the `function renderAxisChips(){}` stub added in Task 4 with:

```javascript
function axisChipLabel(axis){
  const st = axisState[axis];
  const parts = [];
  if(st.filters.length) parts.push(`${st.filters.length} filter${st.filters.length>1?'s':''}`);
  if(st.sortDir!==0) parts.push(`sorted by ${st.sortField} ${st.sortDir===1?'▲':'▼'}`);
  return parts.join(' · ');
}

function clearAxis(axis){
  axisState[axis] = { sortField: null, sortDir: 0, filters: [] };
  recomputeVisible(axis);
  if(axis==='observation'){ rowPage=0; } else { colPage=0; }
  render();
  renderAxisChips();
}

function renderAxisChips(){
  const el = document.getElementById('axisChips');
  const chips = ['observation','sample']
    .filter(axis => axisState[axis].filters.length || axisState[axis].sortDir!==0)
    .map(axis => `<span class="chip" data-axis="${axis}">${axis}: ${axisChipLabel(axis)} <button class="chip-x" data-axis="${axis}">✕</button></span>`);
  el.innerHTML = chips.join('');
  el.style.display = chips.length ? 'flex' : 'none';
  el.querySelectorAll('.chip-x').forEach(btn=>{
    btn.onclick = ()=>clearAxis(btn.dataset.axis);
  });
}
```

- [ ] **Step 3: Call `renderAxisChips()` once at startup**

In `loadMeta()` (`biom_viewer/app.py:521-534`), after `render();`, add:

```javascript
    renderAxisChips();
```

(Harmless no-op at startup since no axis has active state yet — keeps the chip strip correctly hidden/shown if `loadMeta` is ever called more than once, e.g. a future "open another file" action.)

- [ ] **Step 4: CSS for the chip strip**

Add to the stylesheet:

```css
  #axisChips{display:none;gap:6px;padding:4px 10px;flex-wrap:wrap}
  .chip{display:inline-flex;align-items:center;gap:5px;background:var(--hl);color:var(--fg);
             border-radius:10px;padding:3px 8px;font-size:11.5px}
  .chip-x{background:none;border:none;color:var(--dim);cursor:pointer;font-size:10px;padding:0;line-height:1}
  .chip-x:hover{color:var(--fg)}
```

- [ ] **Step 5: Manual verification**

Run the dev server, apply a sort and a filter on the same axis — confirm one chip shows both (`sample: 2 filters · sorted by depth ▲`), clicking its ✕ clears both and the grid returns to the full unsorted axis. Confirm chips for both axes can be active and shown simultaneously.

- [ ] **Step 6: Note on the stats-strip interaction (documented, not built)**

`stripOnRows()`'s row-header branch (Task 4, Step 2) intentionally does not get axis-control icons — when the field summary strip is open, the row header is already a two-line label+stats block (`rh-stats`) and adding sort/filter icons there was out of the approved design's scope. If a user wants to sort/filter while the strip is open, they toggle it off (double-click), use the icon, then reopen it — acceptable friction for v1, not a bug.

- [ ] **Step 7: Commit**

```bash
git add biom_viewer/app.py
git commit -m "Add per-axis status chip strip showing active sort/filter with clear-all"
```

---

### Task 7: Full regression pass

**Files:** none (verification only)

- [ ] **Step 1: Run the backend test suite**

Run: `python3 -m pytest tests/ -q`
Expected: all passing (17 tests)

- [ ] **Step 2: Manual full-app walkthrough**

Using `dev_server.py` (or the packaged app if you rebuild it — see the project's standing instruction to rebuild and install after code changes), walk through:
1. Default load, no sort/filter: grid renders identically to before this feature (regression check).
2. Sort an observation-axis field in `row` mode; confirm `data` mode rows follow the same order; confirm `col` mode is unaffected (different axis).
3. Filter a sample-axis field in `col` mode; confirm `data` mode columns shrink to the filtered set; confirm the column count readout (`cols X-Y / Z`) reflects the filtered total, not the table total.
4. Combine a sort + 2 filters on one axis, 1 filter on the other axis simultaneously; confirm both axes behave independently.
5. Clear via chip ✕; confirm full axis returns.
6. Resize the window and change font size while a sort/filter is active; confirm pagination math (`computeFit`) still works off the filtered totals (it does, since `rowsTotal()`/`colsTotal()` already source from the filtered counts — this step is a sanity check, not expected to require code changes).

- [ ] **Step 3: Rebuild and install the app**

Per standing project instruction: rebuild and copy to `/Applications` after code changes, no need to ask.

```bash
scripts/build_macos_app.sh
scripts/install_macos_app.sh
```
