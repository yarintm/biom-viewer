# Row/Column Summary Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user click a selected row/column header and see quick stats (min/max/mean/median, sparsity or missingness, and a histogram or top-values list) for that entire row/column/metadata field, computed over the whole axis (not just the visible page).

**Architecture:** Three new pure-Python stat functions in `biom_viewer/app.py` (`row_summary`, `col_summary`, `field_summary`), each exposed as an `Api` method, computed directly off the sparse `TABLE.matrix_data` or `TABLE.metadata()` — never densifying more than one row/column vector. The frontend gets a small "Σ Summary" button that appears next to `#selected` whenever exactly one row or column is selected, and reuses the existing `#metaOverlay`/`#metaModal` popup (adding one new content block below the stats table for a histogram or frequency bar list).

**Tech Stack:** Python stdlib only (`collections.Counter`, `math`) — no new dependencies. Frontend: vanilla JS/CSS already used throughout `app.py`'s embedded `PAGE` string, no charting library.

**Design spec:** `docs/superpowers/specs/2026-08-19-summary-panel-design.md`

---

## Response Shape Decisions (not fully pinned in the spec — resolved here)

- Row/col summaries (over nonzero values) use the numeric shape but with `nonzero`/`sparsity` fields instead of `missing` (there's no such thing as a "missing" abundance value — only zero or nonzero). Field summaries (metadata) use `missing` instead. Both share `n`, `sum`, `min`, `max`, `mean`, `median`, `histogram`.
- `_numeric_summary(values, total)` is the one shared stat-computation helper; callers attach either `nonzero`/`sparsity` (row/col) or `missing` (field) afterward.
- Histogram: 10 equal-width buckets over `[min, max]` of the values passed in; if `min == max` (all one value), return a single bucket instead of dividing by zero.
- Categorical top-values: `collections.Counter.most_common()` is stable on ties (preserves first-seen order in CPython), so results are deterministic — relied on directly in tests.

---

### Task 1: Backend — histogram + numeric summary helpers

**Files:**
- Modify: `biom_viewer/app.py` (add helpers near top, after `_json_safe`, ~line 25)
- Test: `tests/test_app.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_app.py`:

```python
from biom_viewer.app import _histogram, _numeric_summary


def test_histogram_ten_equal_width_buckets():
    buckets = _histogram([1.0, 2.0, 3.0, 4.0, 5.0])
    assert len(buckets) == 10
    assert buckets[0]["lo"] == 1.0
    assert buckets[-1]["hi"] == 5.0
    assert sum(b["count"] for b in buckets) == 5


def test_histogram_single_value_returns_one_bucket():
    buckets = _histogram([3.0, 3.0, 3.0])
    assert buckets == [{"lo": 3.0, "hi": 3.0, "count": 3}]


def test_numeric_summary_basic_stats():
    s = _numeric_summary([2.0, 5.0], total=4)
    assert s["kind"] == "numeric"
    assert s["n"] == 4
    assert s["sum"] == 7.0
    assert s["min"] == 2.0
    assert s["max"] == 5.0
    assert s["mean"] == 3.5
    assert s["median"] == 3.5
    assert len(s["histogram"]) == 10
    assert sum(b["count"] for b in s["histogram"]) == 2


def test_numeric_summary_empty_values():
    s = _numeric_summary([], total=3)
    assert s == {
        "kind": "numeric", "n": 3, "sum": None, "min": None,
        "max": None, "mean": None, "median": None, "histogram": [],
    }
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_app.py -k "histogram or numeric_summary" -v`
Expected: FAIL with `ImportError: cannot import name '_histogram'`

- [ ] **Step 3: Implement the helpers**

In `biom_viewer/app.py`, add after the `_json_safe` function (after line 24):

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_app.py -k "histogram or numeric_summary" -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add biom_viewer/app.py tests/test_app.py
git commit -m "Add histogram and numeric summary stat helpers"
```

---

### Task 2: Backend — row_summary / col_summary + Api methods

**Files:**
- Modify: `biom_viewer/app.py` (add functions after `data_window`, ~line 55; add `Api` methods after `data_window` method, ~line 65)
- Test: `tests/test_app.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_app.py` (uses the existing `make_table()` helper):

```python
def test_row_summary_mixed_sparse_row():
    app.TABLE = make_table()
    s = app.row_summary(1)  # obs2: [2, 0, 0, 5]
    assert s["kind"] == "numeric"
    assert s["n"] == 4
    assert s["nonzero"] == 2
    assert s["sparsity"] == 50.0
    assert s["sum"] == 7.0
    assert s["min"] == 2.0
    assert s["max"] == 5.0
    assert s["mean"] == 3.5
    assert s["median"] == 3.5


def test_row_summary_all_zero_row():
    app.TABLE = make_table()
    s = app.row_summary(2)  # obs3: [0, 0, 0, 0]
    assert s["nonzero"] == 0
    assert s["sparsity"] == 100.0
    assert s["min"] is None
    assert s["mean"] is None
    assert s["histogram"] == []


def test_col_summary_single_nonzero_value():
    app.TABLE = make_table()
    s = app.col_summary(0)  # s1: [0, 2, 0]
    assert s["nonzero"] == 1
    assert s["sparsity"] == round(2 / 3 * 100, 1)
    assert s["min"] == s["max"] == 2.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_app.py -k "row_summary or col_summary" -v`
Expected: FAIL with `AttributeError: module 'biom_viewer.app' has no attribute 'row_summary'`

- [ ] **Step 3: Implement row_summary/col_summary and wire into Api**

In `biom_viewer/app.py`, add after `data_window` (after line 54):

```python
def row_summary(r):
    row = TABLE.matrix_data.tocsr()[r, :]
    values = [float(v) for v in row.data if v != 0]
    total = TABLE.shape[1]
    summary = _numeric_summary(values, total)
    summary["nonzero"] = len(values)
    summary["sparsity"] = round((total - len(values)) / total * 100, 1) if total else 0.0
    return summary


def col_summary(c):
    col = TABLE.matrix_data.tocsc()[:, c]
    values = [float(v) for v in col.data if v != 0]
    total = TABLE.shape[0]
    summary = _numeric_summary(values, total)
    summary["nonzero"] = len(values)
    summary["sparsity"] = round((total - len(values)) / total * 100, 1) if total else 0.0
    return summary
```

In the `Api` class, add after the `data_window` method (after line 64):

```python
    def row_summary(self, r):
        return row_summary(r)

    def col_summary(self, c):
        return col_summary(c)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_app.py -k "row_summary or col_summary" -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add biom_viewer/app.py tests/test_app.py
git commit -m "Add row_summary/col_summary backend stats"
```

---

### Task 3: Backend — field_summary (metadata, numeric + categorical)

**Files:**
- Modify: `biom_viewer/app.py` (add `_is_numeric`, `field_summary` after `col_summary`; add `Api.field_summary`; add `from collections import Counter` to imports)
- Test: `tests/test_app.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_app.py`:

```python
def make_table_with_sample_metadata():
    # 2 observations x 12 samples; abundance values irrelevant for these tests.
    data = np.zeros((2, 12))
    sample_ids = [f"s{i}" for i in range(12)]
    sample_metadata = []
    for i in range(12):
        ph = None if i == 0 else float(i)  # one missing, values 1..11 present
        sample_metadata.append({"ph": ph, "habitat": f"habitat{i}"})
    return biom.Table(data, ["o1", "o2"], sample_ids, sample_metadata=sample_metadata)


def test_field_summary_numeric_field_with_missing():
    app.TABLE = make_table_with_sample_metadata()
    s = app.field_summary("sample", "ph")
    assert s["kind"] == "numeric"
    assert s["n"] == 12
    assert s["missing"] == 1
    assert s["min"] == 1.0
    assert s["max"] == 11.0
    assert s["mean"] == 6.0
    assert s["median"] == 6.0
    assert sum(b["count"] for b in s["histogram"]) == 11


def test_field_summary_categorical_field_top10_and_other_count():
    app.TABLE = make_table_with_sample_metadata()
    s = app.field_summary("sample", "habitat")
    assert s["kind"] == "categorical"
    assert s["n"] == 12
    assert s["missing"] == 0
    assert len(s["top"]) == 10
    assert [t["value"] for t in s["top"]] == [f"habitat{i}" for i in range(10)]
    assert all(t["count"] == 1 for t in s["top"])
    assert s["other_count"] == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_app.py -k field_summary -v`
Expected: FAIL with `AttributeError: module 'biom_viewer.app' has no attribute 'field_summary'`

- [ ] **Step 3: Implement _is_numeric and field_summary**

Add `from collections import Counter` to the top imports in `biom_viewer/app.py` (near `import math`).

Add after `col_summary` (after the new block from Task 2):

```python
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


def field_summary(axis, field):
    entries = TABLE.metadata(axis=axis)
    total = len(entries)
    raw = [(dict(e) if e else {}).get(field) for e in entries]
    present = [v for v in raw if v is not None and v != ""]
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
        "top": top,
        "other_count": other_count,
    }
```

Add to the `Api` class, after `col_summary`:

```python
    def field_summary(self, axis, field):
        return field_summary(axis, field)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_app.py -k field_summary -v`
Expected: PASS (2 tests)

Then run the full suite:

Run: `pytest tests/test_app.py -v`
Expected: PASS (all tests, including Tasks 1-2)

- [ ] **Step 5: Commit**

```bash
git add biom_viewer/app.py tests/test_app.py
git commit -m "Add field_summary backend stats for metadata fields"
```

---

### Task 4: Frontend — summary button + modal markup/CSS

**Files:**
- Modify: `biom_viewer/app.py` (embedded `PAGE` string: CSS block ~lines 67-179, HTML body ~lines 202, 218-226)

- [ ] **Step 1: Adjust `#selected` CSS and wrap it with a summary button**

Find this existing CSS rule (~line 134):

```css
  #selected{width:100%;box-sizing:border-box;margin:6px 0;padding:5px 8px;background:transparent;color:var(--dim);
             border:1px solid transparent;border-radius:4px;font-family:ui-monospace,monospace;outline:none;
             caret-color:transparent;transition:color .15s}
  #selected.flash{color:var(--fg)}
```

Replace with:

```css
  #selectedWrap{display:flex;align-items:center;gap:6px;margin:6px 10px}
  #selected{flex:1;box-sizing:border-box;padding:5px 8px;background:transparent;color:var(--dim);
             border:1px solid transparent;border-radius:4px;font-family:ui-monospace,monospace;outline:none;
             caret-color:transparent;transition:color .15s}
  #selected.flash{color:var(--fg)}
  #summaryBtn{display:none;flex-shrink:0}
```

- [ ] **Step 2: Add histogram/frequency bar CSS**

Add after the `#metaModal .empty` rule (~line 178, right before the closing `</style>`):

```css
  #summaryExtra .sg-cap{padding:2px 14px 4px;font:700 10px/1.4 ui-monospace,monospace;color:var(--dim);letter-spacing:.04em;text-transform:uppercase}
  #summaryExtra .hist{padding:0 14px 12px}
  .hist-row{display:flex;align-items:center;gap:6px;font-size:11px;margin:3px 0}
  .hist-label{width:100px;flex-shrink:0;color:var(--dim);text-align:right;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .hist-bar-wrap{flex:1;background:var(--hdr-bg);border-radius:3px;overflow:hidden;height:12px}
  .hist-bar{height:100%;background:var(--accent)}
  .hist-count{width:32px;flex-shrink:0;color:var(--dim)}
  #summaryExtra .sr-more{padding:0 14px 12px;font-size:11px;color:var(--dim);font-style:italic}
```

- [ ] **Step 3: Update the `#selected` HTML and add the summary button**

Find (~line 202):

```html
<input id="selected" readonly value="Click a row, column, or cell to see its full text here (auto-copied to clipboard).">
```

Replace with:

```html
<div id="selectedWrap">
  <input id="selected" readonly value="Click a row, column, or cell to see its full text here (auto-copied to clipboard).">
  <button class="tool" id="summaryBtn" title="Show summary of the selected row/column">Σ Summary</button>
</div>
```

- [ ] **Step 4: Add `#summaryExtra` container to the metadata modal**

Find (~line 224):

```html
    <dl class="rows" id="metaRows"></dl>
```

Replace with:

```html
    <dl class="rows" id="metaRows"></dl>
    <div id="summaryExtra"></div>
```

- [ ] **Step 5: Manually verify no syntax errors**

Run: `python3 -c "import biom_viewer.app"`
Expected: no output, exit code 0 (confirms the `PAGE` triple-quoted string still parses as valid Python)

- [ ] **Step 6: Commit**

```bash
git add biom_viewer/app.py
git commit -m "Add summary button and modal markup/CSS"
```

---

### Task 5: Frontend — wire up summary fetch, render, and button visibility

**Files:**
- Modify: `biom_viewer/app.py` (embedded `PAGE` string, JS section)

- [ ] **Step 1: Add `summaryTarget()` and `fmtNum()` helpers**

Find the `applyHighlight` function definition (~line 610, right before `function applyHighlight(){`). Add just above it:

```javascript
function fmtNum(v){ return Number.isInteger(v) ? String(v) : v.toFixed(2); }

// Returns null if no exactly-one-axis selection exists (nothing selected, or
// a specific cell with both selR and selC set). Otherwise returns the label
// to show and a fetch() that calls the matching backend summary method.
function summaryTarget(){
  if(selR!==null && selC!==null) return null;
  if(selR!==null){
    if(mode==='col') return {label: colFields[selR], fetch: ()=>window.pywebview.api.field_summary('sample', colFields[selR])};
    return {label: rowLabel(selR), fetch: ()=>window.pywebview.api.row_summary(selR)};
  }
  if(selC!==null){
    if(mode==='row') return {label: rowFields[selC], fetch: ()=>window.pywebview.api.field_summary('observation', rowFields[selC])};
    return {label: colLabel(selC), fetch: ()=>window.pywebview.api.col_summary(selC)};
  }
  return null;
}
```

- [ ] **Step 2: Update `applyHighlight()` to toggle the summary button**

Find the `applyHighlight` function (~line 610-621):

```javascript
function applyHighlight(){
  document.querySelectorAll('#grid .hl-row,#grid .hl-col,#grid .hl-cell')
    .forEach(el=>el.classList.remove('hl-row','hl-col','hl-cell'));
  if(selR===null && selC===null) return;
  document.querySelectorAll('#grid [data-r],#grid [data-c]').forEach(el=>{
    const r = el.dataset.r!==undefined ? parseInt(el.dataset.r) : null;
    const c = el.dataset.c!==undefined ? parseInt(el.dataset.c) : null;
    if(selR!==null && r===selR) el.classList.add('hl-row');
    if(selC!==null && c===selC) el.classList.add('hl-col');
    if(selR!==null && selC!==null && r===selR && c===selC) el.classList.add('hl-cell');
  });
}
```

Replace with (adds one line at the top of the body and one at the end):

```javascript
function applyHighlight(){
  document.getElementById('summaryBtn').style.display = summaryTarget() ? 'inline-block' : 'none';
  document.querySelectorAll('#grid .hl-row,#grid .hl-col,#grid .hl-cell')
    .forEach(el=>el.classList.remove('hl-row','hl-col','hl-cell'));
  if(selR===null && selC===null) return;
  document.querySelectorAll('#grid [data-r],#grid [data-c]').forEach(el=>{
    const r = el.dataset.r!==undefined ? parseInt(el.dataset.r) : null;
    const c = el.dataset.c!==undefined ? parseInt(el.dataset.c) : null;
    if(selR!==null && r===selR) el.classList.add('hl-row');
    if(selC!==null && c===selC) el.classList.add('hl-col');
    if(selR!==null && selC!==null && r===selR && c===selC) el.classList.add('hl-cell');
  });
}
```

- [ ] **Step 3: Add `renderBars()` and `openSummary()`**

Find the `openMeta` function (~line 623-639). Add immediately before it:

```javascript
function renderBars(container, items){
  const max = Math.max(...items.map(i=>i.count), 1);
  container.innerHTML = items.map(i => `
    <div class="hist-row">
      <span class="hist-label" title="${escapeHtml(i.label)}">${escapeHtml(i.label)}</span>
      <span class="hist-bar-wrap"><span class="hist-bar" style="width:${(i.count/max*100).toFixed(1)}%"></span></span>
      <span class="hist-count">${i.count}</span>
    </div>`).join('');
}

async function openSummary(){
  const target = summaryTarget();
  if(!target) return;
  const s = await target.fetch();
  document.getElementById('metaTitle').textContent = `Summary — ${target.label}`;

  const stats = s.kind==='numeric'
    ? {
        count: s.nonzero!==undefined
          ? `${s.nonzero} / ${s.n} nonzero (${s.sparsity}% zero)`
          : `${s.n - s.missing} / ${s.n} present (${s.missing} missing)`,
        sum: s.sum===null ? null : fmtNum(s.sum),
        min: s.min===null ? null : fmtNum(s.min),
        max: s.max===null ? null : fmtNum(s.max),
        mean: s.mean===null ? null : fmtNum(s.mean),
        median: s.median===null ? null : fmtNum(s.median),
      }
    : { total: s.n, missing: s.missing, 'distinct shown': s.top.length };

  const rows = document.getElementById('metaRows');
  rows.innerHTML = '';
  Object.entries(stats).forEach(([k,v])=>{
    if(v===null || v===undefined) return;
    const dt = document.createElement('dt'); dt.textContent = k;
    const dd = document.createElement('dd'); dd.textContent = v;
    rows.append(dt, dd);
  });

  const extra = document.getElementById('summaryExtra');
  if(s.kind==='numeric' && s.histogram.length){
    extra.innerHTML = '<div class="sg-cap">Distribution</div><div class="hist"></div>';
    renderBars(extra.querySelector('.hist'), s.histogram.map(b=>({label:`${fmtNum(b.lo)}–${fmtNum(b.hi)}`, count:b.count})));
  } else if(s.kind==='categorical' && s.top.length){
    extra.innerHTML = '<div class="sg-cap">Top values</div><div class="hist"></div>';
    renderBars(extra.querySelector('.hist'), s.top.map(t=>({label:t.value, count:t.count})));
    if(s.other_count) extra.innerHTML += `<div class="sr-more">+${s.other_count} other value(s)</div>`;
  } else {
    extra.innerHTML = '';
  }

  document.getElementById('metaOverlay').classList.add('open');
}
```

- [ ] **Step 4: Wire the button and clear `#summaryExtra` when the table-info modal opens**

Find (~line 641-648):

```javascript
document.getElementById('metaBtn').onclick = ()=>{
  openMeta('Table metadata', {
    table_id: meta.table_id,
    type: meta.table_type,
    generated_by: meta.generated_by,
    create_date: meta.create_date,
  });
};
```

Replace with:

```javascript
document.getElementById('metaBtn').onclick = ()=>{
  document.getElementById('summaryExtra').innerHTML = '';
  openMeta('Table metadata', {
    table_id: meta.table_id,
    type: meta.table_type,
    generated_by: meta.generated_by,
    create_date: meta.create_date,
  });
};
document.getElementById('summaryBtn').onclick = openSummary;
```

- [ ] **Step 5: Manually verify no syntax errors**

Run: `python3 -c "import biom_viewer.app"`
Expected: no output, exit code 0

- [ ] **Step 6: Commit**

```bash
git add biom_viewer/app.py
git commit -m "Wire up summary button, fetch, and modal rendering"
```

---

### Task 6: Rebuild, install, and manually verify in the real app

**Files:** none (build + manual QA only)

- [ ] **Step 1: Run the full backend test suite**

Run: `pytest tests/test_app.py -v`
Expected: PASS (all tests from Tasks 1-3 plus the pre-existing ones)

- [ ] **Step 2: Rebuild and install the app**

Per project convention, always rebuild and reinstall after app code changes:

```bash
./scripts/build_macos_app.sh
rm -rf /Applications/BiomViewer.app
ditto dist/BiomViewer.app /Applications/BiomViewer.app
touch /Applications/BiomViewer.app
```

- [ ] **Step 3: Manually verify the feature**

Open `/Applications/BiomViewer.app` with a real `.biom` file (double-click a `.biom` file, or `open /Applications/BiomViewer.app --args /path/to/file.biom`). Check:

- In **Data** mode: click a row header (observation) → "Σ Summary" button appears next to the selected-text box → click it → modal shows nonzero/sparsity/sum/min/max/mean/median and a distribution bar chart.
- Click a column header (sample) in Data mode → same, via `col_summary`.
- Switch to **Row metadata** mode, click a column header (a field) → summary via `field_summary('observation', field)` — numeric field shows a histogram, categorical field shows a top-values bar list.
- Switch to **Col metadata** mode, click a row header (a field) → summary via `field_summary('sample', field)`.
- Click a single **cell** (both row and column selected) → the Σ button disappears (no axis summary for a single cell).
- Click the ⓘ table-info button after viewing a summary → old histogram/frequency bars don't linger in the modal.

- [ ] **Step 4: Report result**

If any check fails, fix the underlying code (not the build), rebuild, and re-verify — do not consider this task done until all checks in Step 3 pass in the real app.
