"""Inline JS for the BIOM Viewer webview page (biom_viewer/app.py's PAGE).

Same rationale as web_style.py: a plain string constant, not a static asset
file, so PyInstaller bundles it via ordinary Python import analysis.
"""

SCRIPT = """
window.onerror = (msg, url, line, col) => {
  const el = document.getElementById('filename');
  if(el) el.textContent = `JS error: ${msg} (line ${line}:${col})`;
};
let meta=null, rowPage=0, colPage=0, selR=null, selC=null, fontSize=11;
let autoRows=20, autoCols=8, rowHPx=22, colWPx=130;
let availH=0, availW=0;
// Pinned rows (raw observation indices) and their own selection slot --
// deliberately outside axisState/undo history: pin/unpin is high-frequency
// and low-stakes compared to sort/filter/rename/delete, so it shouldn't
// flood the 50-entry undo stack or be ctrl-Z-able.
let pinnedObs = new Set();
let selPinnedRaw = null;
// Same idea, one level up: in 'col' mode the "rows" are metadata field
// names (colFields entries), a different identity space entirely -- keyed
// by field name string (stable across sort; deleteField splices colFields
// directly, see deleteField's cleanup) rather than a numeric index.
let pinnedColFields = new Set();
let selPinnedField = null;
let summaryVisible=false;
// In 'col' mode, double-clicking one row header expands just that field's
// row to a stat summary (instead of summaryVisible's "expand every row").
let expandedFieldRow=null;
// Pinned fields live outside the paged position space expandedFieldRow
// indexes into (see colFieldsForPaging), so their own double-click expand
// needs a name-keyed twin instead of a position index. Mutually exclusive
// with expandedFieldRow -- only one field row is ever expanded at a time.
let expandedPinnedField=null;
function anyFieldRowExpanded(){ return stripOnRows() || (mode==='col' && (expandedFieldRow!=null || expandedPinnedField!=null)); }
// Expanding/collapsing a row changes rowsPerPage() (the expanded row eats
// extra height budget), which shifts which fields "page N" covers -- so the
// clicked row can silently scroll off the page it was just clicked on.
// Recompute fit and re-center on r first, same fix toggleSummary already
// needed for the same reason.
function toggleFieldRow(r){
  expandedFieldRow = (expandedFieldRow===r) ? null : r;
  expandedPinnedField = null;
  computeFit();
  const maxPage = Math.max(0, Math.ceil(rowsTotal()/rowsPerPage()) - 1);
  rowPage = Math.min(Math.floor(r/rowsPerPage()), maxPage);
  render();
}
// Same idea for a frozen field row -- it's always visible (top of the grid,
// independent of rowPage), so there's no row to re-center on, just a fit
// recompute since rowsPerPage() shrinks to make room for the tall track.
function toggleFieldRowPinned(field){
  expandedPinnedField = (expandedPinnedField===field) ? null : field;
  expandedFieldRow = null;
  computeFit();
  const maxPage = Math.max(0, Math.ceil(rowsTotal()/rowsPerPage()) - 1);
  rowPage = Math.min(rowPage, maxPage);
  render();
}
const GAP=14;
const COLW_TARGET=130, RHW_MIN=60, RHW_MAX=240;
let RHW=RHW_MAX;
function rowsPerPage(){ return autoRows; }
function colsPerPage(){ return autoCols; }

// The row-header column's width, sized to its actual content instead of a
// flat 240px: in 'col' mode with the stats strip on (field name + a stats
// block needing real room), keep the generous fixed width; otherwise (plain
// ids, e.g. numeric feature ids in row/data mode) shrink to fit the longest
// label so it doesn't waste space for no reason.
let _rhwCache = null;
function computeRHW(){
  if(anyFieldRowExpanded()) return RHW_MAX;
  const key = mode+'|'+fontSize;
  if(_rhwCache && _rhwCache.key===key) return _rhwCache.val;
  const labels = mode==='col' ? colFields : (meta ? meta.row_ids : []);
  let longest = '';
  (labels||[]).forEach(l=>{ const s=''+l; if(s.length>longest.length) longest=s; });
  const probe = document.createElement('span');
  probe.style.cssText = `position:absolute;visibility:hidden;white-space:nowrap;left:-9999px;top:-9999px;font-size:${fontSize}px`;
  probe.textContent = longest;
  document.body.appendChild(probe);
  const w = probe.getBoundingClientRect().width;
  probe.remove();
  const val = Math.min(RHW_MAX, Math.max(RHW_MIN, Math.ceil(w) + 16));
  _rhwCache = {key, val};
  return val;
}

// The stats strip's row-track height, measured (not guessed) off a real
// offscreen worst-case cell so it never clips regardless of fontSize: hand
// magic-number line-height math drifts from the actual CSS as soon as
// padding/gap/line-height values change, and it did.
let _statRowHCache = null;
function statRowH(){
  const key = fontSize + '|' + anyFieldRowExpanded();
  if(_statRowHCache && _statRowHCache.key===key) return _statRowHCache.val;
  const worstCase = {missing:0, n:1, distinct:999,
    top:[{value:'x',count:1},{value:'x',count:1},{value:'x',count:1}], other_count:1};
  const probe = document.createElement('div');
  probe.className = 'cell stat-cell' + (anyFieldRowExpanded() ? ' rh-stats' : '');
  probe.style.cssText = 'position:absolute;visibility:hidden;left:-9999px;top:-9999px;'
    + `width:${anyFieldRowExpanded() ? RHW_MAX : COLW_TARGET}px;`;
  probe.innerHTML = (anyFieldRowExpanded() ? '<div class="stat-line rh-label">X</div>' : '') + statCellHtml(worstCase);
  document.body.appendChild(probe);
  const val = Math.ceil(probe.getBoundingClientRect().height);
  probe.remove();
  _statRowHCache = {key, val};
  return val;
}

// The metadata *fields* — the axis actually worth summarizing — sit on the
// row axis in 'col' mode (colFields) and the column axis everywhere else
// (data mode's samples, or 'row' mode's rowFields). Only 'col' mode's field
// list is what gets summarized on the row side, because it's the only case
// where the row axis is small (bounded by field count, not by taxa/sample
// count) — tall rows are only affordable there.
function stripOnRows(){ return summaryVisible && mode==='col'; }
function stripOnCols(){ return summaryVisible && mode!=='col'; }

// Toggling the strip can drastically shrink rowsPerPage() (tall stat rows
// fit far fewer per page than plain rows), so the page that used to show
// row `centerRow` may no longer be page 0. Recompute fit first, then land
// on whichever page actually contains centerRow — otherwise the view jumps
// back to the top of the list instead of staying on what was clicked.
function toggleSummary(centerRow){
  summaryVisible = !summaryVisible;
  computeFit();
  const maxPage = Math.max(0, Math.ceil(rowsTotal()/rowsPerPage()) - 1);
  rowPage = centerRow!==undefined ? Math.floor(centerRow/rowsPerPage()) : Math.min(rowPage, maxPage);
  render();
}

// Derived from the font, never measured off a rendered cell: cell height is
// set by the grid track computed from this, so measuring it back would feed
// into itself and can collapse the page to 2 giant rows after a partial page.
function shortRowHPx(){ return Math.round(fontSize*1.3) + 8; } // 3px padding + 1px border, top and bottom

function computeFit(){
  const shortRowH = shortRowHPx();
  const mainRect = document.getElementById('main').getBoundingClientRect();
  const colNavH = document.getElementById('colNav').getBoundingClientRect().height;
  availH = mainRect.height - colNavH - GAP - (stripOnCols() ? statRowH() : 0);
  RHW = computeRHW();
  availW = mainRect.width - RHW - GAP;

  // Pinned rows get a fixed track above the paged rows (see render()) --
  // shrink the paged budget by that many so the frozen block + paged rows
  // still fit availH together. Observations (data/row mode) and fields
  // (col mode) are two different identity spaces, but the row-budget math
  // only cares about the count.
  const pinnedCount = (mode==='data'||mode==='row') ? pinnedObs.size
    : mode==='col' ? pinnedColFields.size : 0;

  if(stripOnRows()){
    // The column-header row stays short (it's just sample/observation ids,
    // same as ever) -- only the field rows below it need the tall track,
    // so only they should compete for the height budget. Frozen fields get
    // the same tall track in this view (they're rendered as stat rows
    // too), so they compete for it exactly like paged fields do.
    autoRows = Math.max(1, Math.floor((availH - shortRowH) / statRowH()) - pinnedCount);
  } else if(mode==='col' && expandedFieldRow!=null){
    // One field row is expanded to a stat block; the rest stay short. This
    // reserves the budget even if the expanded row isn't on the current
    // page -- ponytail: slightly conservative, avoids a fit/page chicken-egg.
    // Frozen fields are never the expanded one (see colFieldsForPaging),
    // so they always cost one short track each here.
    autoRows = Math.max(1, Math.floor((availH - shortRowH - statRowH()) / shortRowH) + 1 - pinnedCount);
  } else if(mode==='col' && expandedPinnedField!=null){
    // Same idea, but the expanded row is in the frozen block instead of the
    // paged rows -- the paged rows stay at their normal short cost, only
    // the frozen block's extra height (statRowH() over its usual shortRowH)
    // needs to come out of the budget.
    const extra = statRowH() - shortRowH;
    const totalRowsTarget = Math.max(2, Math.floor((availH - extra)/shortRowH));
    autoRows = Math.max(1, totalRowsTarget - 1 - pinnedCount);
  } else {
    const totalRowsTarget = Math.max(2, Math.floor(availH/shortRowH)); // includes header row
    autoRows = Math.max(1, totalRowsTarget - 1 - pinnedCount);
  }

  autoCols = Math.max(1, Math.floor(availW/COLW_TARGET));
}

let mode='data'; // 'data' | 'row' (observation metadata) | 'col' (sample metadata)
let rowFields=[], colFields=[];

// Sort/filter state lives per underlying axis identity (observation, sample),
// not per mode -- a filter set while viewing row-metadata mode still applies
// to the same axis's rows in data mode. `field_summary`'s numeric/categorical
// detection is reused for filter input type; see fieldIsNumeric().
let axisState = {
  observation: { sortField: null, sortDir: 0, filters: [], replacements: [], renames: {}, deletedFields: [] }, // sortDir: 0=off, 1=asc, -1=desc
  sample: { sortField: null, sortDir: 0, filters: [], replacements: [], renames: {}, deletedFields: [] },
};
// filters entries: {field, kind:'numeric', min, max} or {field, kind:'categorical', text}

// Computed visible-index arrays. null = identity (no active sort/filter for
// that axis) -- the common case stays on the cheap contiguous data_window path.
let visObs = null, visSample = null;

function obsAt(i){ return visObs ? visObs[i] : i; }
function sampleAt(j){ return visSample ? visSample[j] : j; }

// Undo/redo is whole-state snapshotting rather than per-action inverses --
// axisState (sort/filter/replace/rename/delete) plus the field-name arrays
// (deleteField splices them) are small plain data, so a JSON deep-clone
// before each mutation is simpler and less bug-prone than hand-writing an
// inverse for every one of the ~10 mutating actions.
let historyPast = [], historyFuture = [];
function snapshotState(){
  return {
    axisState: JSON.parse(JSON.stringify(axisState)),
    rowFields: rowFields.slice(),
    colFields: colFields.slice(),
  };
}
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
function restoreState(snap){
  axisState = snap.axisState;
  rowFields = snap.rowFields.slice();
  colFields = snap.colFields.slice();
  recomputeVisible('observation');
  recomputeVisible('sample');
  rowPage=0; colPage=0;
  scheduleAutosave();
  render();
  renderAxisChips();
}
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
    // Sorted, not insertion order -- Set iteration order depends on
    // pin/unpin history, not membership, and viewStatesEqual's JSON.stringify
    // compare would otherwise false-negative on two sets with identical
    // members but different pin order (unpin+repin vs. never-touched).
    pinnedObs: [...pinnedObs].sort((a,b)=>a-b),
    pinnedColFields: [...pinnedColFields].sort(),
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
    pinnedObs: [...v.pinnedObs].sort((a,b)=>a-b), pinnedColFields: [...v.pinnedColFields].sort()};
}

function viewStatesEqual(a, b){
  return JSON.stringify(a) === JSON.stringify(b);
}

function undo(){
  if(!historyPast.length) return;
  historyFuture.push(snapshotState());
  restoreState(historyPast.pop());
}
function redo(){
  if(!historyFuture.length) return;
  historyPast.push(snapshotState());
  restoreState(historyFuture.pop());
}

// Search results carry a raw matrix index (jumpTo's entry.i/.fi). If that
// axis has an active sort/filter, the raw index no longer equals its grid
// position -- resolve it against the current visible order, or if the
// target was filtered out entirely, clear that axis's sort/filter so the
// jump always lands on the actual item rather than silently landing on
// whatever else happens to sit at that raw position.
function resolveAxisPosition(axis, rawIdx){
  const vis = axis==='observation' ? visObs : visSample;
  if(!vis) return rawIdx;
  const pos = vis.indexOf(rawIdx);
  if(pos>=0) return pos;
  // Only the "target was filtered out" branch below actually mutates
  // axisState, so recordHistory() is guarded here rather than placed
  // unconditionally at the top -- otherwise every ordinary jump-to (the
  // common case, where pos>=0 above already returned) would push a
  // spurious undo/autosave entry for a navigation that changed nothing.
  recordHistory();
  axisState[axis].sortField = null;
  axisState[axis].sortDir = 0;
  axisState[axis].filters = [];
  recomputeVisible(axis);
  renderAxisChips();
  return rawIdx;
}

// jumpTo's observation-axis branches (search "jump to a taxon/row value")
// route through here rather than calling resolveAxisPosition directly --
// a pinned row is excluded from visObs on purpose (it's in the frozen
// block, not the paginated flow), which resolveAxisPosition can't tell
// apart from "filtered out" and would otherwise mis-resolve.
function selectObservationRow(rawIdx){
  if(pinnedObs.has(rawIdx)){
    selR = null; selPinnedRaw = rawIdx;
    return;
  }
  selPinnedRaw = null;
  const pos = resolveAxisPosition('observation', rawIdx);
  rowPage = Math.floor(pos / rowsPerPage());
  selR = pos;
}

// Same idea for jumpTo's 'colField' branch (search "jump to a metadata
// field" in col mode) -- colFields itself is never filtered/sorted like
// visObs, so there's no resolveAxisPosition equivalent to fall through to;
// a non-pinned field's position is just its index in colFieldsForPaging().
function selectColField(field){
  if(pinnedColFields.has(field)){
    selR = null; selPinnedField = field;
    return;
  }
  selPinnedField = null;
  const pos = colFieldsForPaging().indexOf(field);
  rowPage = Math.floor(Math.max(0, pos) / rowsPerPage());
  selR = pos;
}

const modeBtns = [...document.querySelectorAll('#modeGroup button')];

function setMode(m){
  mode = m;
  if(m!=='col'){ expandedFieldRow = null; expandedPinnedField = null; }
  modeBtns.forEach(x=>x.classList.toggle('active', x.dataset.m===m));
  document.body.className = 'mode-'+m;
  document.getElementById('modeTag').textContent =
    m==='col' ? 'COL METADATA' : m==='row' ? 'ROW METADATA' : '';
  scheduleAutosave();
}

function fieldUnion(metaArr){
  if(!metaArr) return [];
  const seen = new Set();
  const out = [];
  metaArr.forEach(m=>{
    if(!m) return;
    Object.keys(m).forEach(k=>{ if(!seen.has(k)){ seen.add(k); out.push(k); } });
  });
  return out;
}

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

function pageBounds(page, perPage, total){
  const start = page*perPage;
  return [start, Math.min(start+perPage, total)];
}

// 'col' mode's row axis is colFields itself (field names), not an
// obsAt()-style index into a fixed-size axis -- pinning a field excludes it
// from this the same way pinning an observation excludes it from visObs.
// Applied uniformly regardless of stripOnRows()/expandedFieldRow so the
// paged position space never shifts shape when *those* toggle -- only
// pinning itself changes it, matching visObs's contract.
function colFieldsForPaging(){
  return pinnedColFields.size ? colFields.filter(f=>!pinnedColFields.has(f)) : colFields;
}
function colFieldAt(i){ return colFieldsForPaging()[i]; }

// Row/column axis for the grid currently on screen — depends on mode.
// 'row' mode only swaps the COLUMN axis (fields replace samples); the row
// axis (observation ids) stays exactly as in 'data' mode.
// 'col' mode only swaps the ROW axis (fields replace observations); the
// column axis (sample ids) stays exactly as in 'data' mode.
function rowsTotal(){ return mode==='col' ? colFieldsForPaging().length : (visObs ? visObs.length : meta.rows); }
function colsTotal(){ return mode==='row' ? rowFields.length : (visSample ? visSample.length : meta.cols); }
function fieldDisplay(axis, field){ return axisState[axis].renames[field] || field; }
function rowLabel(i){ return mode==='col' ? fieldDisplay('sample', colFieldAt(i)) : meta.row_ids[obsAt(i)]; }
function colLabel(j){ return mode==='row' ? fieldDisplay('observation', rowFields[j]) : meta.col_ids[sampleAt(j)]; }

function formatMetaValue(v){
  if(Array.isArray(v)) v = v.length ? v.join(', ') : null;
  else if(v && typeof v === 'object') v = Object.entries(v).map(([k,x])=>`${k}=${x}`).join(', ');
  if(v===null || v===undefined || v==='') return {text:'—', cls:'mv-empty'};
  return {text:v, cls:'mv'};
}

// Find/replace is a display-only substring substitution over a field's
// values -- it doesn't touch meta.row_metadata/col_metadata, so sorting,
// filtering, and stats keep seeing the original values.
function applyReplacements(axis, field, v){
  const reps = axisState[axis].replacements.filter(r=>r.field===field);
  if(!reps.length || v===null || v===undefined) return v;
  let s = String(v);
  reps.forEach(r=>{ s = s.split(r.find).join(r.replace); });
  return s;
}

function metaCellAt(i, j){
  // i = row index (grid row), j = col index (grid col)
  if(mode==='row'){
    // row axis = observation obsAt(i), col axis = field j (fields unaffected by filters)
    const entry = meta.row_metadata && meta.row_metadata[obsAt(i)];
    const field = rowFields[j];
    return entry ? applyReplacements('observation', field, entry[field]) : null;
  }
  // mode==='col': row axis = field i (unaffected), col axis = sample sampleAt(j)
  return metaCellForField(colFieldAt(i), j);
}

// Frozen field rows (col mode) already know their field directly -- no
// position to run colFieldAt() on, same reasoning as metaCellAtRaw.
function metaCellForField(field, j){
  const entry = meta.col_metadata && meta.col_metadata[sampleAt(j)];
  return entry ? applyReplacements('sample', field, entry[field]) : null;
}

// Pinned/frozen observation rows already have a raw index (they're excluded
// from visObs, so there's no page position to run through obsAt()) --
// metaCellAt(i,j)'s row-mode branch inlined against a raw index directly.
// Only needed for 'row' mode; col-mode's own frozen fields use colFieldAt()
// directly instead, since field pinning excludes by name, not by index.
function metaCellAtRaw(rawIdx, j){
  const entry = meta.row_metadata && meta.row_metadata[rawIdx];
  const field = rowFields[j];
  return entry ? applyReplacements('observation', field, entry[field]) : null;
}

// Missing-value tokens, mirrored from the backend's _MISSING_TOKENS
// (field_summary) so a field the backend treats as numeric-with-some-NAs
// doesn't get misclassified as categorical here just because "NA" isn't a JS number.
const MISSING_TOKENS = new Set(['na', 'n/a', 'nan', 'null', 'none', '-']);
// Sentinel checklist key for blank/missing entries -- distinct from any real
// field value since it's not a plain string a metadata value could equal.
const MISSING_KEY = '\u0000missing';

// Distinct values for a categorical field's filter checklist, counted and
// ranked by frequency (most common first), with a synthetic "(missing)" row
// when any entries are blank. Computed client-side since the full metadata
// array is already loaded -- no backend round trip needed.
function distinctValues(axis, field){
  const entries = axis==='observation' ? meta.row_metadata : meta.col_metadata;
  const counts = new Map();
  (entries||[]).forEach(e=>{
    const raw = e ? e[field] : null;
    const missing = raw===null || raw===undefined || raw==='';
    const key = missing ? MISSING_KEY : String(raw);
    const label = missing ? '(missing)' : String(raw);
    const cur = counts.get(key) || {key, label, count:0};
    cur.count++;
    counts.set(key, cur);
  });
  return [...counts.values()].sort((a,b)=> b.count-a.count || a.label.localeCompare(b.label));
}
function fieldIsNumeric(axis, field){
  const entries = axis==='observation' ? meta.row_metadata : meta.col_metadata;
  const present = (entries||[]).map(e=>e && e[field])
    .filter(v=>v!==null && v!==undefined && v!=='' && !(typeof v==='string' && MISSING_TOKENS.has(v.trim().toLowerCase())));
  if(!present.length) return false;
  return present.every(v=>typeof v==='number' || (typeof v==='string' && v.trim()!=='' && !isNaN(Number(v))));
}

// Whether one filter matches one value. Shared by recomputeVisible (AND'ed
// across all active filters on an axis) and filterMatchCount (one filter in
// isolation, for the chip's "(N/M)" count) so the two can never drift apart.
function filterMatches(f, v){
  if(f.kind==='categorical'){
    const missing = v===null || v===undefined || v==='';
    const key = missing ? MISSING_KEY : String(v);
    return !f.excluded.includes(key);
  }
  if(v===null || v===undefined || v==='') return false;
  if(typeof v==='string' && MISSING_TOKENS.has(v.trim().toLowerCase())) return false;
  const n = Number(v);
  if(f.min!==null && n<f.min) return false;
  if(f.max!==null && n>f.max) return false;
  return true;
}

// How many entries on an axis one filter matches, ignoring any other active
// filters on that axis -- an independent/marginal count, not the running
// total after stacking. Avoids the count depending on filter order.
function filterMatchCount(axis, f){
  const entries = axis==='observation' ? meta.row_metadata : meta.col_metadata;
  const total = axis==='observation' ? meta.rows : meta.cols;
  let count = 0;
  for(let i=0;i<total;i++){
    const entry = entries && entries[i];
    if(filterMatches(f, entry ? entry[f.field] : null)) count++;
  }
  return {count, total};
}

// Recompute visObs/visSample from current axisState. Called whenever a sort
// or filter changes. Leaves the axis untouched (null) if nothing is active,
// keeping the cheap contiguous fetch path for the common case.
function recomputeVisible(axis){
  const state = axisState[axis];
  const entries = axis==='observation' ? meta.row_metadata : meta.col_metadata;
  const total = axis==='observation' ? meta.rows : meta.cols;
  // Pinned rows live in their own frozen block (see render()), not the
  // normal paged flow -- excluding them here, the same way a filter
  // already excludes rows, means rowsTotal()/pageBounds()/obsAt() all
  // keep working unmodified for everything downstream of visObs.
  const pinnedActive = axis==='observation' && pinnedObs.size>0;
  const active = state.filters.length>0 || state.sortDir!==0 || pinnedActive;
  let result = null;
  if(active){
    let idxs = [];
    for(let i=0;i<total;i++) idxs.push(i);
    state.filters.forEach(f=>{
      idxs = idxs.filter(i=>{
        const entry = entries && entries[i];
        return filterMatches(f, entry ? entry[f.field] : null);
      });
    });
    if(pinnedActive) idxs = idxs.filter(i=>!pinnedObs.has(i));
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

// --- search ---------------------------------------------------------------
let idxSamples=[], idxTaxa=[], idxRowFields=[], idxColFields=[], idxValues=[];

function buildSearchIndex(){
  idxSamples = meta.col_ids.map((id,i)=>({type:'sample', label:id, i}));
  idxTaxa = meta.row_ids.map((id,i)=>({type:'taxon', label:id, i}));
  idxRowFields = rowFields.map((f,i)=>({type:'rowField', label:f, i}));
  idxColFields = colFields.map((f,i)=>({type:'colField', label:f, i}));
  idxValues = [];
  (meta.row_metadata||[]).forEach((entry,i)=>{
    if(!entry) return;
    rowFields.forEach((f,fi)=>{
      const {text, cls} = formatMetaValue(entry[f]);
      if(cls==='mv-empty') return;
      idxValues.push({type:'rowValue', field:f, fi, value:String(text), i, id:meta.row_ids[i]});
    });
  });
  (meta.col_metadata||[]).forEach((entry,i)=>{
    if(!entry) return;
    colFields.forEach((f,fi)=>{
      const {text, cls} = formatMetaValue(entry[f]);
      if(cls==='mv-empty') return;
      idxValues.push({type:'colValue', field:f, fi, value:String(text), i, id:meta.col_ids[i]});
    });
  });
}

function escapeHtml(s){
  return String(s).replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

// startswith beats contains; -1 = no match
function matchScore(label, q){
  const li = String(label).toLowerCase().indexOf(q);
  return li<0 ? -1 : (li===0 ? 0 : 1);
}

// exact beats startswith beats contains; -1 = no match
function valueScore(value, q){
  const v = String(value).toLowerCase();
  if(v===q) return 0;
  const li = v.indexOf(q);
  return li<0 ? -1 : (li===0 ? 1 : 2);
}

// "field=value" or "field:value" -> {field, value}; null if q has no separator
function parseFieldQuery(q){
  const m = q.match(/^([^=:]+)[=:](.*)$/);
  if(!m) return null;
  const field = m[1].trim();
  const value = m[2].trim();
  if(!field || !value) return null;
  return {field, value};
}

let searchFlat=[], searchHiIdx=-1;
let searchGroups={}, searchTab='all';
// 'All' shows a taste of each type; a single-type tab shows the long list, which
// the panel scrolls. ponytail: plain slice, virtualize only if 200 rows drag.
const ALL_CAP = 6, TAB_CAP = 200;
const SEARCH_KINDS = [
  ['samples', 'Samples'], ['taxa', 'Taxa'],
  ['rowFields', 'Row fields'], ['colFields', 'Col fields'], ['values', 'Values'],
];

function searchRowHtml(e){
  return e.type==='rowValue' || e.type==='colValue'
    ? `<span class="sr-field">${escapeHtml(e.field)}:</span> ${escapeHtml(e.value)}  —  ${escapeHtml(e.id)}`
    : escapeHtml(e.label);
}

function runSearch(raw){
  const q = raw.trim().toLowerCase();
  const results = document.getElementById('searchResults');
  searchFlat = [];
  searchHiIdx = -1;
  if(!q){ results.classList.remove('open'); results.innerHTML=''; searchGroups={}; return; }

  const byLabel = arr => arr.map(e=>({e, s:matchScore(e.label, q)})).filter(x=>x.s>=0)
    .sort((a,b)=>a.s-b.s).map(x=>x.e);
  const byValue = (arr, valueQ) => arr.map(e=>({e, s:valueScore(e.value, valueQ)})).filter(x=>x.s>=0)
    .sort((a,b)=>a.s-b.s).map(x=>x.e);

  // direct field search, e.g. "subject_id=501" — restrict to matching fields, skip other kinds
  const fq = parseFieldQuery(q);
  if(fq){
    const fieldMatch = e => e.field.toLowerCase().includes(fq.field);
    searchGroups = {
      samples: [], taxa: [], rowFields: [], colFields: [],
      values: byValue(idxValues.filter(fieldMatch), fq.value),
    };
  } else {
    searchGroups = {
      samples: byLabel(idxSamples),
      taxa: byLabel(idxTaxa),
      rowFields: byLabel(idxRowFields),
      colFields: byLabel(idxColFields),
      values: byValue(idxValues, q),
    };
  }
  searchTab = 'all';
  renderSearchPanel();
}

function renderSearchPanel(){
  const results = document.getElementById('searchResults');
  searchFlat = [];
  searchHiIdx = -1;

  const live = SEARCH_KINDS.filter(([k])=>searchGroups[k] && searchGroups[k].length);
  const total = live.reduce((n,[k])=>n+searchGroups[k].length, 0);
  if(!total){
    results.innerHTML = '<div class="sr-empty">No matches</div>';
    results.classList.add('open');
    return;
  }

  let html = `<div class="stabs"><div class="stab${searchTab==='all'?' active':''}" data-tab="all">All<span class="n">${total}</span></div>`;
  live.forEach(([k,cap])=>{
    html += `<div class="stab${searchTab===k?' active':''}" data-tab="${k}">${cap}<span class="n">${searchGroups[k].length}</span></div>`;
  });
  html += `</div>`;

  const group = (k, cap, limit, moreTab)=>{
    const matches = searchGroups[k];
    if(!matches.length) return '';
    let h = `<div class="sg"><div class="sg-cap">${cap}</div>`;
    matches.slice(0, limit).forEach(e=>{
      h += `<div class="sr" data-i="${searchFlat.length}">${searchRowHtml(e)}</div>`;
      searchFlat.push(e);
    });
    const rest = matches.length - Math.min(limit, matches.length);
    if(rest) h += moreTab
      ? `<div class="sr-more" data-tab="${k}">+${rest} more — show all</div>`
      : `<div class="sr-more">+${rest} more — refine your search</div>`;
    return h + `</div>`;
  };

  html += searchTab==='all'
    ? live.map(([k,cap])=>group(k, cap, ALL_CAP, true)).join('')
    : group(searchTab, SEARCH_KINDS.find(([k])=>k===searchTab)[1], TAB_CAP, false);

  results.innerHTML = html;
  results.classList.add('open');
  results.querySelectorAll('.sr').forEach(el=>{
    el.addEventListener('click', ()=>selectSearchResult(parseInt(el.dataset.i)));
  });
  results.querySelectorAll('.stab,.sr-more[data-tab]').forEach(el=>{
    el.addEventListener('click', ()=>{ searchTab = el.dataset.tab; renderSearchPanel(); });
  });
}

// tab order for keyboard cycling: All, then the types that actually matched
function searchTabOrder(){
  return ['all', ...SEARCH_KINDS.filter(([k])=>searchGroups[k] && searchGroups[k].length).map(([k])=>k)];
}

function highlightResult(i){
  const els = document.querySelectorAll('#searchResults .sr');
  els.forEach(el=>el.classList.remove('hi'));
  searchHiIdx = i;
  if(i>=0 && els[i]){ els[i].classList.add('hi'); els[i].scrollIntoView({block:'nearest'}); }
}

function selectSearchResult(i){
  const e = searchFlat[i];
  if(!e) return;
  jumpTo(e);
  if(!searchPinned) document.getElementById('searchResults').classList.remove('open');
}

async function jumpTo(entry){
  document.getElementById('searchBox').blur();
  if(entry.type==='sample'){
    setMode('data');
    const pos = resolveAxisPosition('sample', entry.i);
    colPage = Math.floor(pos / colsPerPage());
    selR = null; selC = pos;
  } else if(entry.type==='taxon'){
    setMode('data');
    selectObservationRow(entry.i);
    selC = null;
  } else if(entry.type==='rowField'){
    setMode('row');
    colPage = Math.floor(entry.i / colsPerPage());
    selR = null; selC = entry.i;
  } else if(entry.type==='colField'){
    setMode('col');
    selectColField(colFields[entry.i]);
    selC = null;
  } else if(entry.type==='rowValue'){
    setMode('row');
    selectObservationRow(entry.i);
    colPage = Math.floor(entry.fi / colsPerPage());
    selC = entry.fi;
  } else if(entry.type==='colValue'){
    setMode('col');
    const pos = resolveAxisPosition('sample', entry.i);
    rowPage = Math.floor(entry.fi / rowsPerPage());
    colPage = Math.floor(pos / colsPerPage());
    selR = entry.fi; selC = pos;
  }
  await render();
  const label = entry.type==='rowValue' ? `${entry.id}  |  ${entry.field}  =  ${entry.value}`
    : entry.type==='colValue' ? `${entry.field}  |  ${entry.id}  =  ${entry.value}`
    : entry.label;
  showSelected(label);
}

async function render(){
  computeFit();
  const [r0,r1] = pageBounds(rowPage, rowsPerPage(), rowsTotal());
  const [c0,c1] = pageBounds(colPage, colsPerPage(), colsTotal());
  const rowWord = mode==='data' ? 'rows' : 'fields';
  document.getElementById('rowRange').textContent = `${rowWord} ${r0+1}-${r1} / ${rowsTotal()}`;
  document.getElementById('colRange').textContent = `cols ${c0+1}-${c1} / ${colsTotal()}`;
  // Red = a filter (not just a sort) actually shrank this axis below its
  // full count -- the fields axis (rowFields/colFields) is never filtered,
  // so only flag the id axis in the modes where it's actually on screen.
  document.getElementById('rowRange').classList.toggle('range-filtered',
    mode!=='col' && !!visObs && visObs.length<meta.rows);
  document.getElementById('colRange').classList.toggle('range-filtered',
    mode!=='row' && !!visSample && visSample.length<meta.cols);
  document.getElementById('rowUp').disabled = rowPage===0;
  document.getElementById('rowDown').disabled = r1>=rowsTotal();
  document.getElementById('colPrev').disabled = colPage===0;
  document.getElementById('colNext').disabled = c1>=colsTotal();

  // Pinned rows are scoped to data/row mode and already excluded from
  // visObs (see recomputeVisible) -- sorted by raw index for a stable,
  // predictable frozen-block order that doesn't reshuffle on pin/unpin.
  const pinnedRaw = (mode==='data'||mode==='row') ? [...pinnedObs].sort((a,b)=>a-b) : [];
  // 'col' mode's frozen rows are fields, not observations -- order follows
  // colFields' own (stable, delete/undelete-only) order rather than Set
  // insertion order, for the same reshuffle-avoidance reason as above.
  const pinnedFieldsOrdered = mode==='col' ? colFields.filter(f=>pinnedColFields.has(f)) : [];
  const pinnedCount = (mode==='data'||mode==='row') ? pinnedRaw.length : pinnedFieldsOrdered.length;

  let data = null, pinnedData = null;
  if(mode==='data'){
    const colIdxs = []; for(let j=c0;j<c1;j++) colIdxs.push(sampleAt(j));
    let bodyFetch;
    if(visObs || visSample){
      const rowIdxs = []; for(let i=r0;i<r1;i++) rowIdxs.push(obsAt(i));
      bodyFetch = window.pywebview.api.data_window_idx(rowIdxs, colIdxs);
    } else {
      bodyFetch = window.pywebview.api.data_window(r0, r1, c0, c1);
    }
    const pinnedFetch = pinnedRaw.length
      ? window.pywebview.api.data_window_idx(pinnedRaw, colIdxs)
      : Promise.resolve([]);
    [data, pinnedData] = await Promise.all([bodyFetch, pinnedFetch]);
  }

  // Stretch to fill availH x availW, but never past the auto-fit page size —
  // a partial last page keeps normal-height rows instead of ballooning.
  const renderedRows = r1-r0, renderedCols = c1-c0;
  const fieldExpandedIdx = (mode==='col' && !stripOnRows() && expandedFieldRow!=null
    && expandedFieldRow>=r0 && expandedFieldRow<r1) ? expandedFieldRow : null;
  let headerRowHPx, rowHeights = null;
  if(stripOnRows()){
    // Column headers stay short; only the field rows below need the tall
    // track, so the header doesn't compete with them for height. Frozen
    // fields get the same tall track in this view (see the frozen-block
    // build below), so their fixed pixel cost has to come out of the same
    // budget before the paged rows stretch to fill what's left.
    headerRowHPx = shortRowHPx();
    const pinnedBlockPx = pinnedCount * statRowH();
    rowHPx = Math.max(statRowH(), (availH - headerRowHPx - pinnedBlockPx) / Math.max(renderedRows, rowsPerPage()));
  } else if(fieldExpandedIdx!=null){
    // Only the expanded row gets the tall stat track; everyone else stays
    // at natural short height instead of stretching to fill availH. Frozen
    // fields are never the expanded one (pinning excludes a field from the
    // paged position space that expandedFieldRow indexes into), so they
    // always use the short track -- computeFit() already reserved that.
    headerRowHPx = shortRowHPx();
    rowHeights = [];
    for(let r=r0;r<r1;r++) rowHeights.push(r===fieldExpandedIdx ? statRowH() : headerRowHPx);
  } else {
    // Frozen rows use a fixed shortRowHPx() track (see gridTemplateRows
    // below), not this branch's stretchy rowHPx -- subtract their pixel
    // cost first so the paged rows' stretch target doesn't silently push
    // the grid's total height past availH by the frozen block's height.
    const pinnedBlockPx = pinnedCount * shortRowHPx()
      + (expandedPinnedField!=null ? statRowH() - shortRowHPx() : 0);
    rowHPx = (availH - pinnedBlockPx) / (Math.max(renderedRows, rowsPerPage())+1);
    headerRowHPx = rowHPx;
  }
  colWPx = availW/renderedCols;

  // Fetch stats for every visible row/column up front, in parallel, so the
  // grid below can be built synchronously once everything has arrived.
  const colStats = stripOnCols()
    ? await Promise.all(Array.from({length: renderedCols}, (_, k) => colStatsFetch(c0+k)))
    : null;
  const rowStats = stripOnRows()
    ? await Promise.all(Array.from({length: renderedRows}, (_, k) => window.pywebview.api.field_summary('sample', colFieldAt(r0+k), visSample)))
    : null;
  // Pinned fields render as stat rows too when the strip view is on (see
  // the frozen-block build below) -- fetch their stats the same way.
  const pinnedFieldStats = (stripOnRows() && pinnedFieldsOrdered.length)
    ? await Promise.all(pinnedFieldsOrdered.map(f => window.pywebview.api.field_summary('sample', f, visSample)))
    : null;
  const fieldExpandedStat = fieldExpandedIdx!=null
    ? await window.pywebview.api.field_summary('sample', colFieldAt(fieldExpandedIdx), visSample)
    : null;
  const pinnedFieldExpandedStat = (expandedPinnedField!=null && !stripOnRows())
    ? await window.pywebview.api.field_summary('sample', expandedPinnedField, visSample)
    : null;

  const grid = document.getElementById('grid');
  const statRowTrack = stripOnCols() ? `${statRowH()}px ` : '';
  const pinnedFieldRowH = stripOnRows() ? statRowH() : shortRowHPx();
  const pinnedTrack = pinnedRaw.length ? `repeat(${pinnedRaw.length}, ${shortRowHPx()}px) `
    : pinnedFieldsOrdered.length
      ? pinnedFieldsOrdered.map(f => `${f===expandedPinnedField ? statRowH() : pinnedFieldRowH}px`).join(' ') + ' '
      : '';
  const rowsTrack = rowHeights ? rowHeights.map(h=>`${h}px`).join(' ') : `repeat(${renderedRows}, ${rowHPx}px)`;
  grid.classList.toggle('col-stats', stripOnCols());
  grid.style.gridTemplateColumns = `${RHW}px repeat(${renderedCols}, ${colWPx}px)`;
  grid.style.gridTemplateRows = `${headerRowHPx}px ${statRowTrack}${pinnedTrack}${rowsTrack}`;
  grid.innerHTML = '';

  const corner = document.createElement('div');
  corner.className = 'cell hdr';
  grid.appendChild(corner);
  for(let c=c0;c<c1;c++){
    const label = colLabel(c);
    const h = document.createElement('div');
    h.className = 'cell hdr colhdr';
    h.title = label;
    h.dataset.c = c;
    h.textContent = label;
    if(mode==='row'){
      h.dataset.ctxAxis = 'observation';
      h.dataset.ctxField = rowFields[c];
    }
    h.addEventListener('click', (e)=>{
      selR=null; selPinnedRaw=null; selPinnedField=null; selC=c;
      showSelected(label);
      applyHighlight();
    });
    h.addEventListener('dblclick', ()=>{ toggleSummary(); });
    grid.appendChild(h);
  }
  if(stripOnCols()){
    grid.appendChild(fillerCell());
    colStats.forEach((s, i) => {
      const cell = statCell(s, colLabel(c0 + i));
      cell.dataset.c = c0 + i; // so applyHighlight() treats it as part of its column
      grid.appendChild(cell);
    });
  }
  // Frozen block: pinned rows always render here, above the paginated body,
  // regardless of which page rowPage is on -- they were already excluded
  // from visObs (see recomputeVisible), so there's no overlap to dedupe.
  pinnedRaw.forEach((rawIdx, pi) => {
    const label = meta.row_ids[rawIdx];
    const isLast = pi === pinnedRaw.length - 1;
    const rh = document.createElement('div');
    rh.className = 'cell rh' + (isLast ? ' pin-last' : '');
    rh.textContent = label;
    rh.title = label;
    rh.dataset.pinnedRaw = rawIdx;
    rh.dataset.ctxPinRaw = rawIdx;
    rh.addEventListener('click', (e)=>{
      selR=null; selC=null; selPinnedRaw=rawIdx; selPinnedField=null;
      showSelected(label);
      applyHighlight();
    });
    grid.appendChild(rh);
    for(let c=c0;c<c1;c++){
      const cell = document.createElement('div');
      cell.dataset.pinnedRaw = rawIdx; cell.dataset.c = c;
      if(mode==='data'){
        const v = pinnedData[pi][c-c0];
        cell.className = 'cell ' + (v===0 ? 'z' : 'nz') + (isLast ? ' pin-last' : '');
        cell.textContent = Number.isInteger(v) ? v : v.toFixed(3);
        cell.title = `${label}\n${colLabel(c)} = ${v}`;
        cell.addEventListener('click', ()=>{
          selR=null; selC=c; selPinnedRaw=rawIdx; selPinnedField=null;
          showSelected(`${label}  |  ${colLabel(c)}  =  ${v}`, v);
          applyHighlight();
        });
      } else {
        const raw = metaCellAtRaw(rawIdx, c);
        const {text, cls} = formatMetaValue(raw);
        cell.className = 'cell ' + cls + (isLast ? ' pin-last' : '');
        cell.textContent = text;
        cell.title = `${label}\n${colLabel(c)} = ${text}`;
        cell.addEventListener('click', ()=>{
          selR=null; selC=c; selPinnedRaw=rawIdx; selPinnedField=null;
          showSelected(`${label}  |  ${colLabel(c)}  =  ${text}`, raw);
          applyHighlight();
        });
      }
      grid.appendChild(cell);
    }
  });
  // Same idea, one axis over: pinned fields (col mode) always render here
  // too, using the same stat-strip-vs-plain branch as the paginated fields
  // below so a pinned field still shows its stats when that view is on --
  // never the single-expanded-field view, since a field can't be both
  // pinned (excluded from the paged position space) and expandedFieldRow
  // (a position within it) at once.
  pinnedFieldsOrdered.forEach((field, pi) => {
    const label = fieldDisplay('sample', field);
    const isLast = pi === pinnedFieldsOrdered.length - 1;
    const rh = document.createElement('div');
    rh.className = 'cell rh' + (isLast ? ' pin-last' : '');
    if(stripOnRows()){
      rh.classList.add('rh-stats');
      rh.innerHTML = `<div class="stat-line rh-label">${escapeHtml(label)}</div>` + statCellHtml(pinnedFieldStats[pi]);
      wireStatOther(rh, pinnedFieldStats[pi], label);
    } else if(field===expandedPinnedField){
      rh.classList.add('rh-stats');
      rh.innerHTML = `<div class="stat-line rh-label">${escapeHtml(label)}</div>` + statCellHtml(pinnedFieldExpandedStat);
      wireStatOther(rh, pinnedFieldExpandedStat, label);
    } else {
      rh.textContent = label;
      rh.dataset.ctxAxis = 'sample';
      rh.dataset.ctxField = field;
    }
    rh.title = label;
    rh.dataset.pinnedField = field;
    rh.dataset.ctxPinField = field;
    rh.addEventListener('click', (e)=>{
      selR=null; selC=null; selPinnedField=field; selPinnedRaw=null;
      showSelected(label);
      applyHighlight();
    });
    if(mode==='col') rh.addEventListener('dblclick', ()=>{ toggleFieldRowPinned(field); });
    grid.appendChild(rh);
    for(let c=c0;c<c1;c++){
      const cell = document.createElement('div');
      cell.dataset.pinnedField = field; cell.dataset.c = c;
      const raw = metaCellForField(field, c);
      const {text, cls} = formatMetaValue(raw);
      cell.className = 'cell ' + cls + (isLast ? ' pin-last' : '');
      cell.textContent = text;
      cell.title = `${label}\n${colLabel(c)} = ${text}`;
      cell.addEventListener('click', ()=>{
        selR=null; selC=c; selPinnedField=field; selPinnedRaw=null;
        showSelected(`${label}  |  ${colLabel(c)}  =  ${text}`, raw);
        applyHighlight();
      });
      grid.appendChild(cell);
    }
  });
  for(let r=r0;r<r1;r++){
    const label = rowLabel(r);
    const rh = document.createElement('div');
    rh.className = 'cell rh';
    if(stripOnRows()){
      rh.classList.add('rh-stats');
      rh.innerHTML = `<div class="stat-line rh-label">${escapeHtml(label)}</div>` + statCellHtml(rowStats[r-r0]);
      wireStatOther(rh, rowStats[r-r0], label);
    } else if(r===fieldExpandedIdx){
      rh.classList.add('rh-stats');
      rh.innerHTML = `<div class="stat-line rh-label">${escapeHtml(label)}</div>` + statCellHtml(fieldExpandedStat);
      wireStatOther(rh, fieldExpandedStat, label);
    } else if(mode==='col'){
      const field = colFieldAt(r);
      rh.textContent = label;
      rh.dataset.ctxAxis = 'sample';
      rh.dataset.ctxField = field;
      rh.dataset.ctxPinField = field;
    } else {
      rh.textContent = label;
      rh.dataset.ctxPinRaw = obsAt(r);
    }
    rh.title = label;
    rh.dataset.r = r;
    rh.addEventListener('click', (e)=>{
      selR=r; selC=null; selPinnedRaw=null; selPinnedField=null;
      showSelected(label);
      applyHighlight();
    });
    rh.addEventListener('dblclick', ()=>{
      if(mode==='col') toggleFieldRow(r);
      else toggleSummary(r);
    });
    grid.appendChild(rh);
    for(let c=c0;c<c1;c++){
      const cell = document.createElement('div');
      cell.dataset.r = r; cell.dataset.c = c;
      if(mode==='data'){
        const v = data[r-r0][c-c0];
        cell.className = 'cell ' + (v===0 ? 'z' : 'nz');
        cell.textContent = Number.isInteger(v) ? v : v.toFixed(3);
        cell.title = `${rowLabel(r)}\n${colLabel(c)} = ${v}`;
        cell.addEventListener('click', ()=>{
          selR=r; selC=c; selPinnedRaw=null; selPinnedField=null;
          showSelected(`${rowLabel(r)}  |  ${colLabel(c)}  =  ${v}`, v);
          applyHighlight();
        });
      } else {
        const raw = metaCellAt(r, c);
        const {text, cls} = formatMetaValue(raw);
        cell.className = 'cell ' + cls;
        cell.textContent = text;
        cell.title = `${rowLabel(r)}\n${colLabel(c)} = ${text}`;
        cell.addEventListener('click', ()=>{
          selR=r; selC=c; selPinnedRaw=null; selPinnedField=null;
          showSelected(`${rowLabel(r)}  |  ${colLabel(c)}  =  ${text}`, raw);
          applyHighlight();
        });
      }
      grid.appendChild(cell);
    }
  }
  applyHighlight();
}

// ponytail: pywebview's page isn't a secure context, so navigator.clipboard is
// undefined and reading .writeText threw — killing the click handler before it
// could highlight. Selecting the #selected input also makes plain Cmd+C work.
function copySelected(){
  const inp=document.getElementById('selected');
  inp.focus(); inp.select();
  let ok=false;
  try{ ok = document.execCommand('copy'); }catch(err){}
  if(!ok && navigator.clipboard) navigator.clipboard.writeText(inp.value).catch(()=>{});
  // Copy is already done by this point -- collapse the selection and drop
  // focus so the readout reads as a plain value display (Excel's cell-
  // reference box) instead of looking permanently "selected" like blue-
  // highlighted text. The user can still click in and drag-select manually.
  inp.setSelectionRange(0, 0);
  inp.blur();
}

// Same non-secure-context issue as copySelected: navigator.clipboard is
// undefined under pywebview, so every modal Copy button needs the
// execCommand fallback via a throwaway textarea instead of calling it directly.
function writeClipboard(text){
  if(navigator.clipboard){ navigator.clipboard.writeText(text).catch(()=>execCommandCopy(text)); }
  else{ execCommandCopy(text); }
}
function execCommandCopy(text){
  const ta=document.createElement('textarea');
  ta.value=text; ta.style.position='fixed'; ta.style.opacity='0';
  document.body.appendChild(ta);
  ta.focus(); ta.select();
  try{ document.execCommand('copy'); }catch(err){}
  document.body.removeChild(ta);
}

// `raw` is the underlying cell/field value alone (no "row | col =" framing) --
// what the expand button (⤢, ⌘⏎) shows full-size and pretty-printed if it's
// JSON. Falls back to `text` for calls (header clicks, status messages) that
// have no separate raw value.
let lastSelectedValue = '';
function showSelected(text, raw){
  lastSelectedValue = raw!==undefined ? raw : text;
  const inp=document.getElementById('selected');
  inp.value = text;
  copySelected();
  inp.classList.add('flash');
  clearTimeout(showSelected._t);
  showSelected._t = setTimeout(()=>inp.classList.remove('flash'), 700);
}

function prettyPrintValue(v){
  if(v && typeof v === 'object') return JSON.stringify(v, null, 2);
  const s = String(v);
  try{ return JSON.stringify(JSON.parse(s), null, 2); }
  catch(e){ return s; }
}

function openCellModal(){
  document.getElementById('cellBlock').textContent = prettyPrintValue(lastSelectedValue);
  document.getElementById('cellOverlay').classList.add('open');
}
document.getElementById('expandBtn').onclick = openCellModal;
document.getElementById('cellCopy').onclick = ()=>{
  writeClipboard(document.getElementById('cellBlock').textContent);
};
document.getElementById('cellClose').onclick = ()=>document.getElementById('cellOverlay').classList.remove('open');
document.getElementById('cellOverlay').addEventListener('click', (e)=>{
  if(e.target.id === 'cellOverlay') e.currentTarget.classList.remove('open');
});

let lastValuesText = '';
function openValuesModal(s, label){
  document.getElementById('valuesTitle').textContent = `${label} — all ${s.distinct} values`;
  document.getElementById('valuesBody').innerHTML = s.all
    .map(v=>`<div class="wm-row"><span>${escapeHtml(v.value)}</span><span class="wm-count">${v.count}</span></div>`)
    .join('');
  lastValuesText = s.all.map(v=>`${v.value}\t${v.count}`).join('\\n');
  document.getElementById('valuesOverlay').classList.add('open');
}
document.getElementById('valuesCopy').onclick = ()=>{
  writeClipboard(lastValuesText);
};
document.getElementById('valuesClose').onclick = ()=>document.getElementById('valuesOverlay').classList.remove('open');
document.getElementById('valuesOverlay').addEventListener('click', (e)=>{
  if(e.target.id === 'valuesOverlay') e.currentTarget.classList.remove('open');
});

function fmtNum(v){ return Number.isInteger(v) ? String(v) : v.toFixed(2); }

// The column axis is field-driven only in 'row' mode (observation metadata
// fields replace samples); everywhere else it's the sample axis, unchanged
// from data mode. Matches colLabel's own mode branch.
function colStatsFetch(j){
  return mode==='row'
    ? window.pywebview.api.field_summary('observation', rowFields[j], visObs)
    : window.pywebview.api.col_summary(sampleAt(j));
}

// Sort/filter/rename/pin used to live as four always-visible icon buttons
// crammed into every header cell -- decluttered per user request into a
// single right-click menu instead (see the 'contextmenu' listener below).
// Reads the ctxAxis/ctxField/ctxPinRaw/ctxPinField data attributes that
// render() stamps onto header cells rather than baking markup per-cell.
// `html` fields below are pre-escaped (the dynamic part is run through
// escapeHtml, then wrapped in markup) -- the menu renders them directly
// rather than escaping again, so a field name can never break out into
// real markup but the <code> styling still comes through.
function headerContextItems(el){
  const items = [];
  const axis = el.dataset.ctxAxis, field = el.dataset.ctxField;
  if(axis && field){
    const st = axisState[axis];
    const name = `<code>${escapeHtml(fieldDisplay(axis, field))}</code>`;
    const sortOn = st.sortField===field && st.sortDir!==0;
    const sortHtml = !sortOn ? `⇅ Sort by ${name} (ascending)`
      : st.sortDir===1 ? `⇅ Sort by ${name} (descending)` : `⇅ Clear sort on ${name}`;
    items.push({html: sortHtml, onClick: ()=>cycleSort(axis, field)});
    const filterOn = st.filters.some(f=>f.field===field);
    items.push({html: filterOn ? `🔽 Edit filter on ${name}…` : `🔽 Filter by ${name}…`,
      onClick: ()=>openFilterInput(axis, field, el)});
    items.push({html: `✏️ Rename or delete ${name}…`, onClick: ()=>openFieldPopover(axis, field, el)});
  }
  if(el.dataset.ctxPinRaw !== undefined){
    const rawIdx = parseInt(el.dataset.ctxPinRaw, 10);
    items.push({html: pinnedObs.has(rawIdx) ? '📌 Unpin' : '📌 Pin to top', onClick: ()=>togglePin(rawIdx)});
  }
  if(el.dataset.ctxPinField !== undefined){
    const f = el.dataset.ctxPinField;
    items.push({html: pinnedColFields.has(f) ? '📌 Unpin' : '📌 Pin to top', onClick: ()=>togglePinField(f)});
  }
  return items;
}

function cycleSort(axis, field){
  recordHistory();
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

// One-line human label for a single filter, shown on its own chip.
function filterChipLabel(axis, f){
  const display = fieldDisplay(axis, f.field);
  let desc;
  if(f.kind==='numeric'){
    if(f.min!==null && f.max!==null) desc = `${display}: ${f.min}–${f.max}`;
    else if(f.min!==null) desc = `${display}: ≥ ${f.min}`;
    else if(f.max!==null) desc = `${display}: ≤ ${f.max}`;
    else desc = display;
  } else if(f.excluded.length===1){
    const v = f.excluded[0]===MISSING_KEY ? '(missing)' : f.excluded[0];
    desc = `${display}: not ${v}`;
  } else {
    desc = `${display}: ${f.excluded.length} excluded`;
  }
  // (N/M) is this filter's own match count in isolation, not the running
  // total after stacking with other active filters on the same axis --
  // see filterMatchCount's comment for why.
  const {count, total} = filterMatchCount(axis, f);
  return `${desc} (${count}/${total})`;
}

function removeSort(axis){
  recordHistory();
  axisState[axis].sortField = null;
  axisState[axis].sortDir = 0;
  recomputeVisible(axis);
  if(axis==='observation'){ rowPage=0; } else { colPage=0; }
  render();
  renderAxisChips();
}

function removeFilter(axis, field){
  recordHistory();
  axisState[axis].filters = axisState[axis].filters.filter(f=>f.field!==field);
  recomputeVisible(axis);
  if(axis==='observation'){ rowPage=0; } else { colPage=0; }
  render();
  renderAxisChips();
}

function renameField(axis, field, newName){
  recordHistory();
  axisState[axis].renames[field] = newName;
  render();
  renderAxisChips();
}

function unrenameField(axis, field){
  recordHistory();
  delete axisState[axis].renames[field];
  render();
  renderAxisChips();
}

function deleteField(axis, field){
  recordHistory();
  const fieldsArr = axis==='observation' ? rowFields : colFields;
  const idx = fieldsArr.indexOf(field);
  if(idx>=0) fieldsArr.splice(idx, 1);
  axisState[axis].deletedFields.push(field);
  delete axisState[axis].renames[field];
  axisState[axis].filters = axisState[axis].filters.filter(f=>f.field!==field);
  axisState[axis].replacements = axisState[axis].replacements.filter(r=>r.field!==field);
  if(axisState[axis].sortField===field){ axisState[axis].sortField=null; axisState[axis].sortDir=0; }
  // A pinned field just got deleted out from under colFields -- drop it
  // from pinnedColFields too, else it lingers pointing at a field that no
  // longer exists (harmless in practice, but a stale ghost in the chip).
  if(axis==='sample' && pinnedColFields.has(field)){
    pinnedColFields.delete(field);
    if(selPinnedField===field) selPinnedField = null;
  }
  recomputeVisible(axis);
  rowPage=0; colPage=0;
  render();
  renderAxisChips();
}

function undeleteField(axis, field){
  recordHistory();
  axisState[axis].deletedFields = axisState[axis].deletedFields.filter(f=>f!==field);
  const fieldsArr = axis==='observation' ? rowFields : colFields;
  if(!fieldsArr.includes(field)) fieldsArr.push(field);
  rowPage=0; colPage=0;
  render();
  renderAxisChips();
}

// One chip per active sort and per active filter (not one combined chip per
// axis) so each can be read and removed independently -- a single "3
// filters" chip told you nothing about what was actually filtered.
function renderAxisChips(){
  const el = document.getElementById('axisChips');
  const chips = [];
  if(pinnedObs.size>0){
    chips.push(`<span class="chip">📌 ${pinnedObs.size} pinned` +
      `<button class="chip-x" data-kind="unpinAll" title="Unpin all">✕</button></span>`);
  }
  if(pinnedColFields.size>0){
    chips.push(`<span class="chip">📌 ${pinnedColFields.size} pinned field${pinnedColFields.size===1?'':'s'}` +
      `<button class="chip-x" data-kind="unpinAllFields" title="Unpin all">✕</button></span>`);
  }
  ['observation','sample'].forEach(axis=>{
    const st = axisState[axis];
    if(st.sortDir!==0){
      chips.push(`<span class="chip">⇅ ${axis}: <code>${escapeHtml(fieldDisplay(axis, st.sortField))}</code> ${st.sortDir===1?'▲':'▼'}` +
        `<button class="chip-x" data-kind="sort" data-axis="${axis}" title="Clear sort">✕</button></span>`);
    }
    st.filters.forEach(f=>{
      chips.push(`<span class="chip">🔽 ${axis}: ${escapeHtml(filterChipLabel(axis, f))}` +
        `<button class="chip-x" data-kind="filter" data-axis="${axis}" data-field="${escapeHtml(f.field)}" title="Remove filter">✕</button></span>`);
    });
    st.replacements.forEach(r=>{
      chips.push(`<span class="chip">🔁 ${axis}: <code>${escapeHtml(fieldDisplay(axis, r.field))}</code> "${escapeHtml(r.find)}"→"${escapeHtml(r.replace)}"` +
        `<button class="chip-x" data-kind="replace" data-axis="${axis}" data-field="${escapeHtml(r.field)}" title="Undo replacement">✕</button></span>`);
    });
    Object.entries(st.renames).forEach(([orig, newName])=>{
      chips.push(`<span class="chip">✏️ ${axis}: <code>${escapeHtml(orig)}</code> → <code>${escapeHtml(newName)}</code>` +
        `<button class="chip-x" data-kind="unrename" data-axis="${axis}" data-field="${escapeHtml(orig)}" title="Undo rename">✕</button></span>`);
    });
    st.deletedFields.forEach(f=>{
      chips.push(`<span class="chip">🗑 ${axis}: <code>${escapeHtml(f)}</code> deleted` +
        `<button class="chip-x" data-kind="undelete" data-axis="${axis}" data-field="${escapeHtml(f)}" title="Restore field">✕</button></span>`);
    });
  });
  if(chips.length>1){
    chips.push(`<button class="chip chip-clear-all" title="Clear everything above">Clear all ✕</button>`);
  }
  el.innerHTML = chips.join('');
  el.style.display = chips.length ? 'flex' : 'none';
  const clearAllBtn = el.querySelector('.chip-clear-all');
  if(clearAllBtn) clearAllBtn.onclick = clearAllChips;
  el.querySelectorAll('.chip-x').forEach(btn=>{
    const kind = btn.dataset.kind;
    if(kind==='sort') btn.onclick = ()=>removeSort(btn.dataset.axis);
    else if(kind==='replace') btn.onclick = ()=>removeReplacement(btn.dataset.axis, btn.dataset.field);
    else if(kind==='unrename') btn.onclick = ()=>unrenameField(btn.dataset.axis, btn.dataset.field);
    else if(kind==='undelete') btn.onclick = ()=>undeleteField(btn.dataset.axis, btn.dataset.field);
    else if(kind==='unpinAll') btn.onclick = ()=>{
      pinnedObs.clear();
      selPinnedRaw = null;
      recomputeVisible('observation');
      scheduleAutosave();
      render();
      renderAxisChips();
    };
    else if(kind==='unpinAllFields') btn.onclick = ()=>{
      pinnedColFields.clear();
      selPinnedField = null;
      scheduleAutosave();
      render();
      renderAxisChips();
    };
    else btn.onclick = ()=>removeFilter(btn.dataset.axis, btn.dataset.field);
  });
  updateViewsBtnLabel();
}

// renderAxisChips() already runs after every state-changing action in the
// app (sort/filter/pin/rename/undo/view-switch/etc), so piggybacking here
// is the one hook point that reliably keeps the label current without
// scattering calls across every mutator.
function updateViewsBtnLabel(){
  const btn = document.getElementById('viewsBtn');
  if(!lastAppliedViewName){
    btn.textContent = 'Views ▾';
    btn.title = 'Saved views';
    btn.classList.remove('views-active', 'views-dirty');
    return;
  }
  const view = savedViews.find(v => v.name===lastAppliedViewName);
  const dirty = !view || !viewStatesEqual(captureViewState(), viewStatePayload(view));
  btn.innerHTML = `<span class="views-current-name">${escapeHtml(lastAppliedViewName)}</span>` +
    (dirty ? `<span class="views-dirty-dot" title="Unsaved changes -- open Views to update">●</span>` : '') + ` ▾`;
  btn.title = dirty ? `${lastAppliedViewName} (unsaved changes -- open Views to update)` : lastAppliedViewName;
  btn.classList.add('views-active');
  btn.classList.toggle('views-dirty', dirty);
}

// One undo step for the whole chips row -- individual chip removers each
// call recordHistory() per action, but a bulk clear should collapse to a
// single ctrl-Z, not one undo per chip.
function clearAllChips(){
  recordHistory();
  axisState.observation = { sortField: null, sortDir: 0, filters: [], replacements: [], renames: {}, deletedFields: [] };
  axisState.sample = { sortField: null, sortDir: 0, filters: [], replacements: [], renames: {}, deletedFields: [] };
  pinnedObs.clear();
  pinnedColFields.clear();
  selPinnedRaw = null;
  selPinnedField = null;
  recomputeVisible('observation');
  recomputeVisible('sample');
  rowPage = 0; colPage = 0;
  scheduleAutosave();
  render();
  renderAxisChips();
}

// Generates illustrative pandas/biom-format code reproducing the current
// per-axis sort/filter as a standalone script -- not a byte-exact replay of
// filterMatches (e.g. missing-token strings like "n/a" become NaN via
// pd.to_numeric(errors='coerce')/isna() rather than a hardcoded token set),
// good enough for a user to paste and adapt.
function pyRepr(v){
  if(v===null || v===undefined) return 'None';
  if(typeof v==='number') return String(v);
  return JSON.stringify(String(v));
}
function pyList(arr){ return '[' + arr.map(pyRepr).join(', ') + ']'; }

function buildAxisExportCode(axis){
  const st = axisState[axis];
  const renameEntries = Object.entries(st.renames);
  const hasSortOrFilter = st.filters.length || st.sortDir!==0;
  const hasFieldOps = st.replacements.length || renameEntries.length || st.deletedFields.length;
  if(!hasSortOrFilter && !hasFieldOps) return null;
  const metaVar = axis==='observation' ? 'obs_meta' : 'samp_meta';
  const lines = [];
  lines.push(`# --- ${axis} axis${st.replacements.length ? ': '+st.replacements.length+' replacement(s)' : ''}${renameEntries.length ? ', '+renameEntries.length+' rename(s)' : ''}${st.deletedFields.length ? ', '+st.deletedFields.length+' deleted field(s)' : ''}${st.filters.length ? ', '+st.filters.length+' filter(s)' : ''}${st.sortDir ? ', sorted by '+st.sortField : ''} ---`);
  lines.push(`${metaVar} = table.metadata_to_dataframe('${axis}')`);
  st.replacements.forEach(r=>{
    const col = `${metaVar}[${pyRepr(r.field)}]`;
    lines.push(`${col} = ${col}.astype(str).str.replace(${pyRepr(r.find)}, ${pyRepr(r.replace)}, regex=False)`);
  });
  if(renameEntries.length){
    const mapping = renameEntries.map(([o,n])=>`${pyRepr(o)}: ${pyRepr(n)}`).join(', ');
    lines.push(`${metaVar} = ${metaVar}.rename(columns={${mapping}})`);
  }
  if(st.deletedFields.length){
    lines.push(`${metaVar} = ${metaVar}.drop(columns=${pyList(st.deletedFields)})`);
  }
  if(!hasSortOrFilter){
    lines.push(`table.add_metadata(${metaVar}.to_dict(orient='index'), axis='${axis}')`);
    const droppedKeys = st.deletedFields.concat(renameEntries.map(([o])=>o));
    if(droppedKeys.length) lines.push(`table.del_metadata(keys=${pyList(droppedKeys)}, axis='${axis}')`);
    return lines;
  }
  lines.push(`mask = pd.Series(True, index=${metaVar}.index)`);
  st.filters.forEach((f, i)=>{
    const col = `${metaVar}[${pyRepr(f.field)}]`;
    if(f.kind==='numeric'){
      const vals = `vals${i}`;
      lines.push(`${vals} = pd.to_numeric(${col}, errors='coerce')`);
      if(f.min!==null && f.max!==null) lines.push(`mask &= ${vals}.between(${f.min}, ${f.max})`);
      else if(f.min!==null) lines.push(`mask &= ${vals} >= ${f.min}`);
      else if(f.max!==null) lines.push(`mask &= ${vals} <= ${f.max}`);
    } else {
      const excluded = f.excluded.filter(k=>k!==MISSING_KEY);
      const dropMissing = f.excluded.includes(MISSING_KEY);
      lines.push(`excluded${i} = ${pyList(excluded)}`);
      lines.push(dropMissing
        ? `mask &= ~(${col}.isin(excluded${i}) | ${col}.isna())`
        : `mask &= ~${col}.isin(excluded${i})`);
    }
  });
  lines.push(`ids = ${metaVar}.index[mask]`);
  if(st.sortDir!==0){
    const numeric = fieldIsNumeric(axis, st.sortField);
    const col = `${metaVar}.loc[ids, ${pyRepr(st.sortField)}]`;
    lines.push(numeric
      ? `sort_key = pd.to_numeric(${col}, errors='coerce')`
      : `sort_key = ${col}.astype(str)`);
    lines.push(`ids = sort_key.sort_values(ascending=${st.sortDir===1}).index`);
  }
  lines.push(`table = table.filter(list(ids), axis='${axis}')`);
  if(st.sortDir!==0) lines.push(`table = table.sort_order(list(ids), axis='${axis}')`);
  return lines;
}

function buildExportCode(){
  const axesActive = ['observation','sample'].filter(a=>{
    const st = axisState[a];
    return st.filters.length || st.sortDir!==0 || st.replacements.length ||
      Object.keys(st.renames).length || st.deletedFields.length;
  });
  const lines = ['import biom'];
  if(axesActive.length) lines.push('import pandas as pd');
  lines.push('', `table = biom.load_table(${pyRepr(meta.filename)})`, '');
  if(!axesActive.length){
    lines.push('# No sort, filter, or find/replace currently active in the viewer.');
  } else {
    axesActive.forEach((axis, i)=>{
      lines.push(...buildAxisExportCode(axis));
      if(i < axesActive.length-1) lines.push('');
    });
  }
  return lines.join('\\n');
}

function openExportModal(){
  document.getElementById('codeBlock').textContent = buildExportCode();
  document.getElementById('codeOverlay').classList.add('open');
}
document.getElementById('codeCopy').onclick = ()=>{
  writeClipboard(document.getElementById('codeBlock').textContent);
};
document.getElementById('codeClose').onclick = ()=>document.getElementById('codeOverlay').classList.remove('open');
document.getElementById('codeOverlay').addEventListener('click', (e)=>{
  if(e.target.id === 'codeOverlay') e.currentTarget.classList.remove('open');
});

// Mirrors buildAxisExportCode's logic but as data for the backend (build_export_table
// in app.py) to actually apply and write out, rather than as a script for the user
// to run themselves.
function buildExportSpec(){
  const spec = {};
  ['observation','sample'].forEach(axis=>{
    const st = axisState[axis];
    const vis = axis==='observation' ? visObs : visSample;
    const rawIds = axis==='observation' ? meta.row_ids : meta.col_ids;
    spec[axis] = {
      ids: vis ? vis.map(i=>rawIds[i]) : null,
      replacements: st.replacements,
      renames: st.renames,
      deletedFields: st.deletedFields,
    };
  });
  return spec;
}

async function exportBiomFile(){
  try{
    const res = await window.pywebview.api.export_table(buildExportSpec());
    if(res && res.ok) showSelected(`Exported to ${res.path}`);
    else if(res && res.error) showSelected(`Export failed: ${res.error}`);
  } catch(err){
    showSelected(`Export failed: ${err}`);
  }
}

function closeFilterPopover(){
  const existing = document.getElementById('filterPopover');
  if(existing) existing.remove();
  return !!existing;
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
    document.body.appendChild(pop);
    pop.querySelector('.fp-min').focus();
  } else {
    pop.classList.add('fp-checklist');
    const values = distinctValues(axis, field);
    const excluded = new Set(existing ? existing.excluded : []);
    const rows = values.map(v =>
      `<label class="fp-row"><input type="checkbox" class="fp-check" value="${escapeHtml(v.key)}" ${excluded.has(v.key) ? '' : 'checked'}>` +
      `<span class="fp-val">${escapeHtml(v.label)}</span><span class="fp-count">${v.count}</span></label>`
    ).join('');
    pop.innerHTML =
      `<input class="fp-search" type="text" placeholder="Search values…">` +
      `<div class="fp-actions"><button class="fp-all">All</button><button class="fp-none">None</button></div>` +
      `<div class="fp-list">${rows}</div>` +
      `<div class="fp-buttons"><button class="fp-apply">Apply</button>${existing ? '<button class="fp-clear">Clear</button>' : ''}</div>`;
    document.body.appendChild(pop);

    const search = pop.querySelector('.fp-search');
    search.addEventListener('input', ()=>{
      const q = search.value.toLowerCase();
      pop.querySelectorAll('.fp-row').forEach(row=>{
        row.style.display = row.querySelector('.fp-val').textContent.toLowerCase().includes(q) ? '' : 'none';
      });
    });
    pop.querySelector('.fp-all').onclick = ()=>{
      pop.querySelectorAll('.fp-row:not([style*="display: none"]) .fp-check').forEach(cb=>cb.checked=true);
    };
    pop.querySelector('.fp-none').onclick = ()=>{
      pop.querySelectorAll('.fp-row:not([style*="display: none"]) .fp-check').forEach(cb=>cb.checked=false);
    };
    search.focus();
  }

  // Clamp to the viewport now that the popover has real content/size --
  // rect.bottom+4 alone can push a tall checklist off the bottom of the
  // window (no scrollbar to reveal it, position:fixed just clips silently).
  // Flip above the header if there's more room there than below.
  const margin = 6;
  const popRect = pop.getBoundingClientRect();
  if(rect.bottom + 4 + popRect.height > window.innerHeight - margin){
    const spaceAbove = rect.top - margin;
    const spaceBelow = window.innerHeight - margin - (rect.bottom + 4);
    pop.style.top = spaceAbove > spaceBelow
      ? Math.max(margin, rect.top - popRect.height - 4) + 'px'
      : (window.innerHeight - margin - popRect.height) + 'px';
  }
  if(rect.left + popRect.width > window.innerWidth - margin){
    pop.style.left = Math.max(margin, window.innerWidth - margin - popRect.width) + 'px';
  }

  const apply = ()=>{
    recordHistory();
    const filters = st.filters.filter(f=>f.field!==field);
    if(numeric){
      const minV = pop.querySelector('.fp-min').value;
      const maxV = pop.querySelector('.fp-max').value;
      filters.push({field, kind:'numeric', min: minV===''?null:Number(minV), max: maxV===''?null:Number(maxV)});
    } else {
      const newExcluded = [...pop.querySelectorAll('.fp-check')].filter(cb=>!cb.checked).map(cb=>cb.value);
      if(newExcluded.length) filters.push({field, kind:'categorical', excluded:newExcluded});
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
    recordHistory();
    st.filters = st.filters.filter(f=>f.field!==field);
    recomputeVisible(axis);
    if(axis==='observation'){ rowPage=0; } else { colPage=0; }
    closeFilterPopover();
    render();
    renderAxisChips();
  };
  if(numeric) pop.addEventListener('keydown', e=>{ if(e.key==='Enter') apply(); if(e.key==='Escape') closeFilterPopover(); });
  else pop.addEventListener('keydown', e=>{ if(e.key==='Escape') closeFilterPopover(); });
}

// Rename/delete a field inline, anchored to its header -- reuses the same
// #filterPopover singleton as openFilterInput (only one popover open at a
// time) so it gets the same outside-click-close and Escape handling for free.
function openFieldPopover(axis, field, anchorEl){
  closeFilterPopover();
  const pop = document.createElement('div');
  pop.id = 'filterPopover';
  const rect = anchorEl.getBoundingClientRect();
  pop.style.left = rect.left + 'px';
  pop.style.top = (rect.bottom + 4) + 'px';
  const current = fieldDisplay(axis, field);
  pop.innerHTML = `<input class="fp-text" type="text" value="${escapeHtml(current)}">` +
    `<button class="fp-apply">Rename</button>` +
    `<button class="fp-clear">Delete</button>`;
  document.body.appendChild(pop);
  const input = pop.querySelector('.fp-text');
  input.focus();
  input.select();
  const rename = ()=>{
    const val = input.value.trim();
    if(val && val!==field) renameField(axis, field, val);
    closeFilterPopover();
  };
  pop.querySelector('.fp-apply').onclick = rename;
  pop.querySelector('.fp-clear').onclick = ()=>{ deleteField(axis, field); closeFilterPopover(); };
  pop.addEventListener('keydown', e=>{ if(e.key==='Enter') rename(); if(e.key==='Escape') closeFilterPopover(); });
}

document.addEventListener('click', (e)=>{
  const pop = document.getElementById('filterPopover');
  if(pop && !pop.contains(e.target) && !e.target.closest('.ctx-item')) closeFilterPopover();
  const viewsPop = document.getElementById('viewsPopover');
  if(viewsPop && !viewsPop.contains(e.target) && !e.target.closest('#viewsBtn')) closeViewsPopover();
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
  const activeView = lastAppliedViewName ? savedViews.find(v => v.name===lastAppliedViewName) : null;
  const dirty = !!activeView && !viewStatesEqual(captureViewState(), viewStatePayload(activeView));
  const updateBanner = dirty
    ? `<button class="views-update-btn">● Update "${escapeHtml(lastAppliedViewName)}" with current changes</button>`
    : '';
  pop.innerHTML = updateBanner + `<div class="views-list">${rows}</div>` +
    `<div class="views-save"><input class="views-save-input" type="text" placeholder="Save current as…">` +
    `<button class="views-save-btn">Save</button></div>`;
  document.body.appendChild(pop);
  wireViewsPopover(pop);
  if(dirty) pop.querySelector('.views-update-btn').onclick = ()=> saveCurrentAsView(lastAppliedViewName);
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
  saveInput.addEventListener('keydown', e=>{ if(e.key==='Enter'){ e.stopPropagation(); doSave(); } if(e.key==='Escape'){ e.stopPropagation(); closeViewsPopover(); } });
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
  // Removing the input (via openViewsPopover -> closeViewsPopover) while it's
  // still focused fires a native blur, which would otherwise re-run commit()
  // a second time. Guard so each rename attempt only commits once, and let
  // Escape set the guard itself so the ensuing blur is a no-op that never
  // reads input.value or calls the API.
  let committed = false;
  const commit = async ()=>{
    if(committed) return;
    committed = true;
    const newName = input.value.trim();
    if(!newName || newName===oldName){ openViewsPopover(); return; }
    const result = await window.pywebview.api.rename_view(oldName, newName);
    if(!result.ok){ input.classList.add('error'); input.title = 'Name already taken'; committed = false; return; }
    if(lastAppliedViewName===oldName) lastAppliedViewName = newName;
    await refreshSavedViews();
    openViewsPopover();
  };
  input.addEventListener('keydown', e=>{
    if(e.key==='Enter'){ e.stopPropagation(); commit(); }
    if(e.key==='Escape'){ e.stopPropagation(); committed = true; openViewsPopover(); }
  });
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

function closeConfirmPopover(){
  const existing = document.getElementById('confirmPopover');
  if(existing) existing.remove();
  return !!existing;
}

function confirmDiscardCurrent(onConfirm){
  closeFilterPopover();
  closeViewsPopover();
  closeConfirmPopover();
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

function togglePinField(field){
  if(pinnedColFields.has(field)) pinnedColFields.delete(field); else pinnedColFields.add(field);
  if(selPinnedField===field) selPinnedField = null;
  const maxPage = Math.max(0, Math.ceil(rowsTotal()/rowsPerPage()) - 1);
  rowPage = Math.min(rowPage, maxPage);
  scheduleAutosave();
  render();
  renderAxisChips();
}

function closeContextMenu(){
  const existing = document.getElementById('ctxMenu');
  if(existing) existing.remove();
  return !!existing;
}

// The native right-click menu (WKWebView's default) doesn't offer a web
// search on macOS the way Safari does -- just "Services" and the like (see
// screenshot in the request this came from). A small in-page menu near the
// cursor is simpler and more portable than fighting the native menu's
// contents, and pywebview's cocoa backend only auto-opens external links
// for real <a> navigations, not window.open() -- see Api.open_url's comment
// for why the actual browser launch goes through Python instead.
document.addEventListener('contextmenu', (e)=>{
  const headerEl = e.target.closest('.rh, .hdr.colhdr');
  const headerItems = headerEl ? headerContextItems(headerEl) : [];

  const sel = window.getSelection().toString().trim();
  const cellEl = e.target.closest('.cell, .wm-row, #cellBlock, #codeBlock, #selected');
  const fallback = cellEl ? (cellEl.value !== undefined ? cellEl.value : cellEl.textContent).trim() : '';
  const text = sel || fallback;
  if(!headerItems.length && !text) return; // nothing relevant under the cursor -- let the native menu show
  e.preventDefault();
  closeContextMenu();
  const menu = document.createElement('div');
  menu.id = 'ctxMenu';
  menu.style.left = e.clientX + 'px';
  menu.style.top = e.clientY + 'px';
  let html = headerItems.map((it, i)=>`<button class="ctx-item" data-hi="${i}">${it.html}</button>`).join('');
  if(text){
    if(headerItems.length) html += `<div class="ctx-sep"></div>`;
    const short = text.length > 40 ? text.slice(0, 40) + '…' : text;
    html += `<button class="ctx-item" data-search="1">🔍 Search Google for <code>${escapeHtml(short)}</code></button>`;
  }
  menu.innerHTML = html;
  document.body.appendChild(menu);
  headerItems.forEach((it, i)=>{
    menu.querySelector(`[data-hi="${i}"]`).onclick = ()=>{ closeContextMenu(); it.onClick(); };
  });
  if(text){
    menu.querySelector('[data-search]').onclick = ()=>{
      window.pywebview.api.open_url('https://www.google.com/search?q=' + encodeURIComponent(text));
      closeContextMenu();
    };
  }
});
document.addEventListener('click', closeContextMenu);

function miniHist(histogram){
  if(!histogram.length) return '';
  const max = Math.max(...histogram.map(b=>b.count), 1);
  const bars = histogram.map(b =>
    `<span class="bar" style="height:${Math.max(4, b.count/max*100)}%" title="${fmtNum(b.lo)}–${fmtNum(b.hi)}: ${b.count}"></span>`
  ).join('');
  return `<div class="stat-bars">${bars}</div>`;
}

function topValueRows(top, presentTotal){
  return top.slice(0, 3).map(t => {
    const pct = presentTotal ? Math.round(t.count/presentTotal*100) : 0;
    return `<div class="stat-top-row" title="${escapeHtml(t.value)}: ${t.count}">
      <span class="fill" style="width:${pct}%"></span>
      <span class="lbl">${escapeHtml(t.value)}</span>
      <span class="pct">${pct}%</span>
    </div>`;
  }).join('');
}

// Compact Data-Wrangler-style stats block: presence line (missing or nonzero),
// then either a mini histogram + min/max (numeric) or distinct count + top
// values (categorical). Same shape for row_summary/col_summary/field_summary.
function statCellHtml(s){
  const presence = s.nonzero!==undefined
    ? `Nonzero <b>${s.nonzero}</b> (${(100-s.sparsity).toFixed(0)}%)`
    : `Missing <b>${s.missing}</b> (${s.n ? Math.round(s.missing/s.n*100) : 0}%)`;

  if(s.kind==='numeric'){
    const range = s.min===null ? '' : `<div class="stat-line">Min ${fmtNum(s.min)} · Max ${fmtNum(s.max)}</div>`;
    return `<div class="stat-line">${presence}</div>${miniHist(s.histogram)}${range}`;
  }

  const distinctPct = s.n ? Math.round(s.distinct/s.n*100) : 0;
  const presentTotal = s.n - s.missing;
  // The strip only ever renders the top 3 rows (topValueRows), regardless of
  // how many the backend sent in `top` -- so "how many more" has to be
  // counted against those 3, not against `top.length` or the backend's own
  // other_count (which is relative to its top-10 cutoff). Otherwise ranks
  // 4-10 silently vanish: neither shown above nor counted in the "+N" line.
  const shownCount = s.top.slice(0, 3).length;
  const otherDistinct = s.distinct - shownCount;
  const otherRows = presentTotal - s.top.slice(0, 3).reduce((a, t) => a + t.count, 0);
  const other = otherDistinct > 0
    ? `<div class="stat-line stat-other" title="View all ${s.distinct} values">+${otherDistinct} more (${otherRows} rows)</div>`
    : '';
  return `<div class="stat-line">${presence}</div>` +
    `<div class="stat-line">Distinct <b>${s.distinct}</b> (${distinctPct}%)</div>` +
    topValueRows(s.top, presentTotal) + other;
}

// Wires the "+N other" line's click after innerHTML is set (statCellHtml
// only builds markup, no field/axis context to close over) -- shared by the
// col-stats strip (via statCell) and the row-stats strip (baked into a
// bigger innerHTML alongside the row label, so wired separately there).
function wireStatOther(containerEl, s, label){
  if(!s.all) return;
  const el = containerEl.querySelector('.stat-other');
  if(el) el.onclick = (e)=>{ e.stopPropagation(); openValuesModal(s, label); };
}

function statCell(s, label){
  const cell = document.createElement('div');
  cell.className = 'cell stat-cell';
  cell.innerHTML = statCellHtml(s);
  wireStatOther(cell, s, label);
  return cell;
}

function fillerCell(){
  const cell = document.createElement('div');
  cell.className = 'cell hdr';
  return cell;
}

function applyHighlight(){
  document.querySelectorAll('#grid .hl-row,#grid .hl-col,#grid .hl-cell')
    .forEach(el=>el.classList.remove('hl-row','hl-col','hl-cell'));
  if(selR===null && selPinnedRaw===null && selPinnedField===null && selC===null) return;
  // Excel-style: a single selected cell (a row identity + selC both set)
  // only tints its row/column headers, not the whole row/column body — the
  // cell itself gets the outline instead. selR/selPinnedRaw/selPinnedField
  // are mutually-exclusive "which row" slots (paginated observations,
  // frozen observations, frozen fields) since none of their identities
  // share a common position space with the others.
  const rowSelected = selR!==null || selPinnedRaw!==null || selPinnedField!==null;
  const cellSelected = rowSelected && selC!==null;
  // Paginated cells/headers -- explicitly excludes frozen body cells (which
  // also carry data-c) since those are keyed by data-pinned-raw/-field, not
  // data-r, and would otherwise get miscounted as "headers" here for
  // lacking data-r.
  document.querySelectorAll('#grid [data-r],#grid [data-c]:not([data-pinned-raw]):not([data-pinned-field])').forEach(el=>{
    const r = el.dataset.r!==undefined ? parseInt(el.dataset.r) : null;
    const c = el.dataset.c!==undefined ? parseInt(el.dataset.c) : null;
    const isHeader = r===null || c===null;
    if(selR!==null && r===selR && (isHeader || !cellSelected)) el.classList.add('hl-row');
    if(selC!==null && c===selC && (isHeader || !cellSelected)) el.classList.add('hl-col');
    if(cellSelected && selR!==null && r===selR && c===selC) el.classList.add('hl-cell');
  });
  // Frozen observation rows (data/row mode) -- same shape as above, keyed
  // by pinned raw index instead of page position. Column highlight (hl-col)
  // still applies here even when the selected row is a paginated one, so a
  // column stays tinted across the whole grid including the frozen rows.
  document.querySelectorAll('#grid [data-pinned-raw]').forEach(el=>{
    const pr = parseInt(el.dataset.pinnedRaw);
    const c = el.dataset.c!==undefined ? parseInt(el.dataset.c) : null;
    const isHeader = c===null;
    if(selPinnedRaw!==null && pr===selPinnedRaw && (isHeader || !cellSelected)) el.classList.add('hl-row');
    if(selC!==null && c===selC && (isHeader || !cellSelected)) el.classList.add('hl-col');
    if(cellSelected && selPinnedRaw!==null && pr===selPinnedRaw && c===selC) el.classList.add('hl-cell');
  });
  // Frozen fields (col mode) -- same shape again, keyed by field name.
  document.querySelectorAll('#grid [data-pinned-field]').forEach(el=>{
    const pf = el.dataset.pinnedField;
    const c = el.dataset.c!==undefined ? parseInt(el.dataset.c) : null;
    const isHeader = c===null;
    if(selPinnedField!==null && pf===selPinnedField && (isHeader || !cellSelected)) el.classList.add('hl-row');
    if(selC!==null && c===selC && (isHeader || !cellSelected)) el.classList.add('hl-col');
    if(cellSelected && selPinnedField!==null && pf===selPinnedField && c===selC) el.classList.add('hl-cell');
  });
}

function rpFieldsFor(axis){ return axis==='observation' ? rowFields : colFields; }

function populateRpFields(){
  const axis = document.getElementById('rpAxis').value;
  const sel = document.getElementById('rpField');
  sel.innerHTML = rpFieldsFor(axis).map(f=>`<option value="${escapeHtml(f)}">${escapeHtml(fieldDisplay(axis, f))}</option>`).join('');
}

function renderRpList(){
  const items = [];
  ['observation','sample'].forEach(axis=>{
    axisState[axis].replacements.forEach(r=>{
      items.push(`<div class="rp-item"><span>${escapeHtml(axis)}: ${escapeHtml(fieldDisplay(axis, r.field))} — "${escapeHtml(r.find)}" → "${escapeHtml(r.replace)}"</span>` +
        `<button data-axis="${axis}" data-field="${escapeHtml(r.field)}">✕</button></div>`);
    });
  });
  const el = document.getElementById('rpList');
  el.innerHTML = items.join('');
  el.querySelectorAll('button').forEach(btn=>{
    btn.onclick = ()=> removeReplacement(btn.dataset.axis, btn.dataset.field);
  });
}

function removeReplacement(axis, field){
  recordHistory();
  axisState[axis].replacements = axisState[axis].replacements.filter(r=>r.field!==field);
  render();
  renderAxisChips();
  renderRpList();
}

function openReplaceModal(){
  populateRpFields();
  renderRpList();
  document.getElementById('replaceOverlay').classList.add('open');
  document.getElementById('rpFind').focus();
}
document.getElementById('rpAxis').addEventListener('change', populateRpFields);
document.getElementById('rpApply').onclick = ()=>{
  const axis = document.getElementById('rpAxis').value;
  const field = document.getElementById('rpField').value;
  const find = document.getElementById('rpFind').value;
  const replace = document.getElementById('rpReplace').value;
  if(!field || !find) return;
  recordHistory();
  axisState[axis].replacements = axisState[axis].replacements.filter(r=>r.field!==field);
  axisState[axis].replacements.push({field, find, replace});
  document.getElementById('rpFind').value = '';
  document.getElementById('rpReplace').value = '';
  render();
  renderAxisChips();
  renderRpList();
};
document.getElementById('replaceClose').onclick = ()=>document.getElementById('replaceOverlay').classList.remove('open');
document.getElementById('replaceOverlay').addEventListener('click', (e)=>{
  if(e.target.id === 'replaceOverlay') e.currentTarget.classList.remove('open');
});

// 'row' mode only swaps the column axis, 'col' mode only swaps the row axis —
// so reset just the axis whose meaning changed and keep your place on the other.
const rowAxisKey = m => m==='col' ? 'fields' : 'ids';
const colAxisKey = m => m==='row' ? 'fields' : 'ids';
modeBtns.forEach(b=>b.onclick = ()=>{
  const m = b.dataset.m;
  if(rowAxisKey(m)!==rowAxisKey(mode)){ rowPage = 0; selR = null; selPinnedRaw = null; selPinnedField = null; }
  if(colAxisKey(m)!==colAxisKey(mode)){ colPage = 0; selC = null; }
  setMode(m);
  render();
});

const searchBox = document.getElementById('searchBox');
let searchDebounce=null;
// Selecting a result blurs the box and closes the panel (jumpTo) without
// clearing the query -- re-focusing (a plain click, no typing) should bring
// the same results back rather than leaving the panel dead until the next
// keystroke.
searchBox.addEventListener('focus', ()=>{ if(searchBox.value.trim()) runSearch(searchBox.value); });

// Pinning keeps the results panel open across result clicks and clicks
// elsewhere in the grid, so you can work through a list of matches (e.g.
// jump to several samples in turn) without re-searching each time.
let searchPinned = false;
const searchPin = document.getElementById('searchPin');
searchPin.onclick = ()=>{
  searchPinned = !searchPinned;
  searchPin.classList.toggle('on', searchPinned);
  document.getElementById('searchResults').classList.toggle('pinned', searchPinned);
  if(searchPinned && searchBox.value.trim()) runSearch(searchBox.value);
};
searchBox.addEventListener('input', ()=>{
  clearTimeout(searchDebounce);
  searchDebounce = setTimeout(()=>runSearch(searchBox.value), 120);
});
searchBox.addEventListener('keydown', (e)=>{
  const results = document.getElementById('searchResults');
  if(!results.classList.contains('open')) return;
  if(e.key==='Tab'){
    e.preventDefault();
    const order = searchTabOrder();
    const at = order.indexOf(searchTab);
    searchTab = order[(at + (e.shiftKey ? -1 : 1) + order.length) % order.length];
    renderSearchPanel();
  }
  else if(e.key==='ArrowDown'){ e.preventDefault(); highlightResult(Math.min(searchHiIdx+1, searchFlat.length-1)); }
  else if(e.key==='ArrowUp'){ e.preventDefault(); highlightResult(Math.max(searchHiIdx-1, 0)); }
  else if(e.key==='Enter'){ e.preventDefault(); selectSearchResult(searchHiIdx>=0 ? searchHiIdx : 0); }
  else if(e.key==='Escape'){
    // Escape always dismisses, even pinned -- it's the explicit "get this
    // out of my way" gesture, so it also drops the pin rather than leaving
    // a pinned-but-hidden panel that won't reopen on the next focus.
    searchPinned = false;
    searchPin.classList.remove('on');
    results.classList.remove('open', 'pinned');
    searchBox.blur();
  }
});
document.addEventListener('click', (e)=>{
  if(searchPinned) return;
  // composedPath(), not searchWrap.contains(e.target): a click on something
  // like .sr-more ("show all") re-renders #searchResults.innerHTML first
  // (its own listener runs before this one, earlier in the bubble path),
  // detaching e.target from the tree -- contains() would then report it as
  // "outside" and immediately re-close the panel that render just reopened.
  // composedPath() is captured at dispatch time, so it's unaffected by that.
  if(!e.composedPath().includes(document.getElementById('searchWrap'))){
    document.getElementById('searchResults').classList.remove('open');
  }
});

document.getElementById('rowUp').onclick = ()=>{ rowPage--; render(); };
document.getElementById('rowDown').onclick = ()=>{ rowPage++; render(); };
document.getElementById('colPrev').onclick = ()=>{ colPage--; render(); };
document.getElementById('colNext').onclick = ()=>{ colPage++; render(); };

let resizeT=null;
window.addEventListener('resize', ()=>{
  clearTimeout(resizeT);
  resizeT = setTimeout(()=>{ rowPage=0; colPage=0; render(); }, 150);
});

const systemDark = window.matchMedia('(prefers-color-scheme: dark)');
function toggleTheme(){
  const dark = (document.documentElement.dataset.theme || (systemDark.matches ? 'dark' : 'light')) === 'dark';
  document.documentElement.dataset.theme = dark ? 'light' : 'dark';
}

function setFontSize(px){
  fontSize = Math.max(8, Math.min(28, px));
  document.documentElement.style.setProperty('--fs', fontSize+'px');
  rowPage=0; colPage=0; render();
}

document.addEventListener('keydown', (e)=>{
  const mod = e.metaKey || e.ctrlKey;
  if(mod){
    const k = e.key.toLowerCase();
    if(k==='f'){ e.preventDefault(); document.getElementById('searchBox').focus(); }
    else if(k==='r'){ e.preventDefault(); openReplaceModal(); }
    else if(k==='e'){ e.preventDefault(); openExportModal(); }
    else if(k==='s'){ e.preventDefault(); exportBiomFile(); }
    else if(k==='z' && e.shiftKey){ e.preventDefault(); redo(); }
    else if(k==='z'){ e.preventDefault(); undo(); }
    else if(k==='enter'){ e.preventDefault(); openCellModal(); }
    else if(e.key==='=' || e.key==='+'){ e.preventDefault(); setFontSize(fontSize+1); }
    else if(e.key==='-'){ e.preventDefault(); setFontSize(fontSize-1); }
    return;
  }
  if(e.key==='Escape'){
    let handled = false;
    if(closeFilterPopover()) handled = true;
    if(closeViewsPopover()) handled = true;
    if(closeContextMenu()) handled = true;
    ['codeOverlay','replaceOverlay','cellOverlay','valuesOverlay'].forEach(id=>{
      const el = document.getElementById(id);
      if(el.classList.contains('open')){ el.classList.remove('open'); handled = true; }
    });
    const results = document.getElementById('searchResults');
    if(results.classList.contains('open')){ results.classList.remove('open'); handled = true; }
    if(!handled && document.activeElement && document.activeElement !== document.body && document.activeElement.blur){
      document.activeElement.blur();
    }
  }
});

window.addEventListener('pywebviewready', loadMeta);
"""
