#!/usr/bin/env python3
"""Lazy-loading BIOM viewer: native window (pywebview) + biom-format, sparse-window slicing, canvas grid UI."""
import math
import os
import sys
from collections import Counter

import biom
import webview

TABLE = None
FILENAME = ""


def _json_safe(v):
    # Real metadata (e.g. pandas-sourced sample sheets) is full of NaN/inf for
    # missing values. json.dumps emits those as bare NaN/Infinity tokens,
    # which is invalid JSON and makes JSON.parse throw on the JS side.
    if isinstance(v, float) and not math.isfinite(v):
        return None
    if isinstance(v, dict):
        return {k: _json_safe(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_json_safe(x) for x in v]
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


# ponytail: whole id list sent once (text-only, cheap even at ~1e5 rows); paginate if a table
# ever has >~500k ids and this becomes a multi-MB response.
def meta():
    obs_ids = TABLE.ids("observation").tolist()
    sample_ids = TABLE.ids("sample").tolist()
    obs_meta = TABLE.metadata(axis="observation")
    sample_meta = TABLE.metadata(axis="sample")
    return {
        "filename": FILENAME,
        "rows": TABLE.shape[0],
        "cols": TABLE.shape[1],
        "row_ids": obs_ids,
        "col_ids": sample_ids,
        "table_id": TABLE.table_id,
        "table_type": TABLE.type,
        "generated_by": TABLE.generated_by,
        "create_date": str(TABLE.create_date) if TABLE.create_date else None,
        "row_metadata": [_json_safe(dict(m)) for m in obs_meta] if obs_meta else None,
        "col_metadata": [_json_safe(dict(m)) for m in sample_meta] if sample_meta else None,
    }


def data_window(r0, r1, c0, c1):
    r1 = min(r1, TABLE.shape[0])
    c1 = min(c1, TABLE.shape[1])
    # Densify only the requested window, never the full matrix.
    sub = TABLE.matrix_data[r0:r1, :].tocsc()[:, c0:c1]
    return sub.toarray().tolist()


def _axis_summary(vec, total):
    values = [float(v) for v in vec.data if v != 0]
    summary = _numeric_summary(values, total)
    summary["nonzero"] = len(values)
    summary["sparsity"] = round((total - len(values)) / total * 100, 1) if total else 0.0
    return summary


def row_summary(r):
    return _axis_summary(TABLE.matrix_data.tocsr()[r, :], TABLE.shape[1])


_csc_cache = {"table": None, "matrix": None}


def _csc():
    if _csc_cache["table"] is not TABLE:
        _csc_cache["table"] = TABLE
        _csc_cache["matrix"] = TABLE.matrix_data.tocsc()
    return _csc_cache["matrix"]


def col_summary(c):
    return _axis_summary(_csc()[:, c], TABLE.shape[0])


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


def field_summary(axis, field):
    entries = TABLE.metadata(axis=axis)
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
    }


class Api:
    """Exposed to the frontend as window.pywebview.api.* — no HTTP server involved."""

    def meta(self):
        return meta()

    def data_window(self, r0, r1, c0, c1):
        return data_window(r0, r1, c0, c1)

    def row_summary(self, r):
        return row_summary(r)

    def col_summary(self, c):
        return col_summary(c)

    def field_summary(self, axis, field):
        return field_summary(axis, field)


PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>BIOM Viewer</title>
<style>
  /* ponytail: light-dark() + color-scheme does the whole thing natively —
     no system-mode listener, no duplicated dark/light var blocks. */
  :root{
    color-scheme: light dark;
    --bg:light-dark(#f5f5f5,#1e1e1e); --fg:light-dark(#222,#ddd);
    --dim:light-dark(#666,#999); --panel-bg:light-dark(#fff,#111);
    --accent:light-dark(#177245,#9f9);
    --border:light-dark(#ccc,#444); --input-bg:light-dark(#fff,#111);
    --input-border:light-dark(#bbb,#555);
    --cell-border:light-dark(#ddd,#333); --hdr-bg:light-dark(#e8e8e8,#252525);
    --hdr-fg:light-dark(#333,#aaa);
    --nz-bg:light-dark(#bfe8d3,#274b3a); --z-fg:light-dark(#aaa,#666);
    --hl:light-dark(#cfe0ff,#3a3a55); --sel-outline:var(--accent);
    --fs:11px;
    --row-meta:light-dark(#c96a1a,#e08a3c); --row-meta-bg:light-dark(#fde3c8,#4a3420);
    --row-meta-fg:light-dark(#5c3410,#2a1c0f);
    --col-meta:light-dark(#2266cc,#5b9bd5); --col-meta-bg:light-dark(#d6e6fa,#20344a);
    --col-meta-fg:light-dark(#0f2c54,#0f1c2a);
  }
  [data-theme="light"]{ color-scheme: light }
  [data-theme="dark"]{ color-scheme: dark }
  html,body{margin:0;height:100%;font:14px/1.3 -apple-system,sans-serif;background:var(--bg);color:var(--fg);overflow:hidden}
  body{display:flex;flex-direction:column}
  #info{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:8px 10px;
        background:var(--hdr-bg);border-bottom:1px solid var(--border)}
  #info #filename{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  #info #toolbar{display:flex;align-items:center;gap:8px;flex-shrink:0}
  #modeTag{display:none;font:700 10px/1 ui-monospace,monospace;padding:3px 7px;border-radius:10px;
           border:1px solid currentColor;letter-spacing:.03em;margin-left:8px}
  body.mode-row #modeTag{display:inline-block;color:var(--row-meta)}
  body.mode-col #modeTag{display:inline-block;color:var(--col-meta)}
  #modeGroup{display:flex;border:1px solid var(--input-border);border-radius:4px;overflow:hidden}
  #modeGroup button{background:var(--panel-bg);color:var(--fg);border:none;border-right:1px solid var(--input-border);
           padding:4px 10px;font-size:12px;cursor:pointer}
  #modeGroup button:last-child{border-right:none}
  #modeGroup button.active{background:var(--accent);color:var(--bg);font-weight:700}
  #modeGroup button[data-m="row"].active{background:var(--row-meta);color:var(--row-meta-fg)}
  #modeGroup button[data-m="col"].active{background:var(--col-meta);color:var(--col-meta-fg)}
  #searchWrap{position:relative}
  #searchBox{width:220px;box-sizing:border-box;background:var(--input-bg);color:var(--fg);
             border:1px solid var(--input-border);border-radius:4px;padding:5px 8px;font-size:12.5px;outline:none}
  #searchBox:focus{border-color:var(--sel-outline)}
  #searchResults{position:absolute;top:calc(100% + 4px);right:0;width:420px;max-height:60vh;overflow-y:auto;
             background:var(--panel-bg);border:1px solid var(--border);border-radius:6px;
             box-shadow:0 12px 30px rgba(0,0,0,.35);display:none;z-index:20}
  #searchResults.open{display:block}
  .stabs{position:sticky;top:0;z-index:1;display:flex;gap:2px;padding:5px 6px;overflow-x:auto;
             background:var(--panel-bg);border-bottom:1px solid var(--border)}
  .stabs::-webkit-scrollbar{display:none}
  .stab{flex:0 0 auto;padding:3px 8px;border-radius:4px;font-size:11.5px;color:var(--dim);
             cursor:pointer;white-space:nowrap;border:1px solid transparent}
  .stab:hover{background:var(--hl)}
  .stab.active{background:var(--hl);color:var(--fg);border-color:var(--sel-outline);font-weight:600}
  .stab .n{margin-left:5px;font-family:ui-monospace,monospace;font-size:10.5px;opacity:.75}
  .sg{padding:6px 0}
  .sg + .sg{border-top:1px solid var(--border)}
  .sg-cap{padding:2px 10px;font:700 10px/1.4 ui-monospace,monospace;color:var(--dim);letter-spacing:.04em;text-transform:uppercase}
  .sr{padding:5px 10px;font-size:12.5px;cursor:pointer;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .sr:hover,.sr.hi{background:var(--hl)}
  .sr .sr-field{color:var(--dim)}
  .sr-more{padding:3px 10px;font-size:11px;color:var(--dim);font-style:italic}
  .sr-more[data-tab]{cursor:pointer;text-decoration:underline}
  .sr-more[data-tab]:hover{color:var(--fg)}
  .sr-empty{padding:8px 10px;font-size:12.5px;color:var(--dim)}
  #selected{width:100%;box-sizing:border-box;margin:6px 0;padding:5px 8px;background:transparent;color:var(--dim);
             border:1px solid transparent;border-radius:4px;font-family:ui-monospace,monospace;outline:none;
             caret-color:transparent;transition:color .15s}
  #selected.flash{color:var(--fg)}
  button.nav,button.tool{background:var(--panel-bg);color:var(--fg);border:1px solid var(--input-border);border-radius:4px;padding:4px 10px;cursor:pointer;
             font-size:14px;line-height:1}
  button.nav:disabled{opacity:.35;cursor:default}
  #body{display:flex;flex:1;min-height:0;padding:0 10px}
  #rowNav{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:6px;padding-right:10px}
  #rowNav span{writing-mode:vertical-rl;color:var(--dim);white-space:nowrap}
  #main{flex:1;display:flex;flex-direction:column;overflow:hidden}
  #colNav{display:flex;align-items:center;justify-content:center;gap:10px;padding-bottom:6px}
  #colNav span{color:var(--dim)}
  #grid{display:grid;overflow:hidden;flex-shrink:0;align-self:flex-start}
  .cell{border:1px solid var(--cell-border);padding:3px 6px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:var(--fs)}
  .hdr{background:var(--hdr-bg);color:var(--hdr-fg)}
  .rh{background:var(--hdr-bg);color:var(--hdr-fg);cursor:pointer}
  .rh:hover{background:var(--input-border)}
  .hdr.colhdr{cursor:pointer}
  .hdr.colhdr:hover{background:var(--input-border)}
  .z{color:var(--z-fg)}
  .nz{background:var(--nz-bg)}
  .mv{color:var(--fg)}
  .mv-empty{color:var(--z-fg);font-style:italic}
  .cell:not(.rh):not(.colhdr).hl-row,.cell:not(.rh):not(.colhdr).hl-col{background:var(--hl) !important}
  .rh.hl-row,.colhdr.hl-col{box-shadow:inset 0 0 0 2px var(--sel-outline);font-weight:700}
  /* Plain .rh headers keep their own axis-color background under selection
     (border-only, no fill) — but .rh-stats is a combined header+stats block,
     not just a label, so it should fill solid like every other selected
     cell instead of leaving all that stats text sitting on a bare border. */
  .rh-stats.hl-row{background:var(--hl) !important}
  .hl-cell{outline:2px solid var(--sel-outline);outline-offset:-2px;position:relative;z-index:1}
  /* row axis (observation ids, leftmost column) orange; col axis (sample ids,
     top row) blue — in data mode both are on screen at once */
  body.mode-row .rh,body.mode-data .rh{background:var(--row-meta-bg);color:var(--row-meta);border-color:var(--row-meta)}
  body.mode-col .hdr.colhdr,body.mode-data .hdr.colhdr{background:var(--col-meta-bg);color:var(--col-meta);border-color:var(--col-meta)}
  #metaOverlay{position:fixed;inset:0;background:rgba(0,0,0,.45);display:none;
               align-items:center;justify-content:center;z-index:10}
  #metaOverlay.open{display:flex}
  #metaModal{background:var(--panel-bg);border:1px solid var(--border);border-radius:8px;
             width:360px;max-width:90vw;box-shadow:0 12px 40px rgba(0,0,0,.35)}
  #metaModal header{display:flex;align-items:center;justify-content:space-between;
                     padding:12px 14px;border-bottom:1px solid var(--border)}
  #metaModal header h3{margin:0;font-size:14px}
  #metaModal .x{cursor:pointer;color:var(--dim);font-size:16px;line-height:1;background:none;border:none}
  #metaModal .x:hover{color:var(--fg)}
  #metaModal .rows{padding:10px 14px 14px;display:grid;grid-template-columns:auto 1fr;
                    gap:6px 12px;font-size:12.5px;max-height:44vh;overflow-y:auto}
  #metaModal .rows dt{color:var(--dim);white-space:nowrap}
  #metaModal .rows dd{margin:0;font-family:ui-monospace,monospace;word-break:break-word}
  #metaModal .empty{padding:0 14px 14px;color:var(--dim);font-size:12.5px}
  .stat-cell,.rh-stats{background:var(--panel-bg);color:var(--dim);font-size:calc(var(--fs)*0.9);line-height:1.35;
             padding:4px 6px;display:flex;flex-direction:column;gap:3px;overflow:hidden;cursor:pointer;min-height:0}
  .rh-stats{white-space:normal}
  .rh-stats:hover{background:var(--panel-bg)}
  .rh-stats .rh-label{font-size:var(--fs);font-weight:700;color:var(--hdr-fg);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
             background:var(--hdr-bg);margin:-4px -6px 4px;padding:4px 6px;cursor:pointer}
  .rh-stats .rh-label:hover{background:var(--input-border)}
  /* The label bar's own opaque background paints over the parent cell's
     top edge, hiding the selection border there -- redraw just that edge
     on the label itself so the border reads as continuous when selected. */
  .rh-stats.hl-row .rh-label{box-shadow:inset 0 2px 0 var(--sel-outline)}
  .stat-line{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .stat-line b{color:var(--fg);font-weight:600}
  .stat-bars{display:flex;align-items:flex-end;gap:1px;height:calc(var(--fs)*1.8);margin:1px 0}
  .stat-bars .bar{flex:1;background:var(--accent);border-radius:1px;min-height:2px}
  .stat-top-row{position:relative;padding:1px 3px;border-radius:2px;overflow:hidden;display:flex;
                align-items:center;justify-content:space-between;gap:4px}
  .stat-top-row .fill{position:absolute;inset:0;background:var(--nz-bg);z-index:0}
  .stat-top-row .lbl,.stat-top-row .pct{position:relative;z-index:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .stat-top-row .pct{flex-shrink:0;font-family:ui-monospace,monospace}
</style></head>
<body class="mode-data">
<div id="info">
  <span style="display:flex;align-items:center;overflow:hidden">
    <span id="filename">loading…</span>
    <span id="modeTag"></span>
  </span>
  <span id="toolbar">
    <span id="searchWrap">
      <input id="searchBox" type="text" placeholder="Search…" autocomplete="off">
      <div id="searchResults"></div>
    </span>
    <span id="modeGroup">
      <button class="active" data-m="data">Data</button>
      <button data-m="row">Row metadata</button>
      <button data-m="col">Col metadata</button>
    </span>
    <button class="tool" id="metaBtn" title="Table metadata">ⓘ</button>
    <button class="tool" id="themeBtn">🌙 dark</button>
    <button class="tool" id="fontDown">A-</button>
    <button class="tool" id="fontUp">A+</button>
  </span>
</div>
<input id="selected" readonly value="Click a row, column, or cell to see its full text here (auto-copied to clipboard). Double-click a header to toggle summary stats.">

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
<div id="metaOverlay">
  <div id="metaModal">
    <header>
      <h3 id="metaTitle">Metadata</h3>
      <button class="x" id="metaClose">✕</button>
    </header>
    <dl class="rows" id="metaRows"></dl>
  </div>
</div>
<script>
window.onerror = (msg, url, line, col) => {
  const el = document.getElementById('filename');
  if(el) el.textContent = `JS error: ${msg} (line ${line}:${col})`;
};
let meta=null, rowPage=0, colPage=0, selR=null, selC=null, fontSize=11;
let autoRows=20, autoCols=8, rowHPx=22, colWPx=130;
let availH=0, availW=0;
let summaryVisible=false;
const GAP=14;
const COLW_TARGET=130, RHW=240;
function rowsPerPage(){ return autoRows; }
function colsPerPage(){ return autoCols; }

// The stats strip's row-track height. Scales with fontSize (like everything
// else driven by the A+/A- buttons) so it never clips as text grows.
// The row-header case (stripOnRows) prepends its own label line on top of
// statCellHtml's content, so it needs one extra line of budget over the
// top-strip case (stripOnCols), where the label is a separate cell above it.
function statRowH(){ return Math.round(fontSize*(7 + (stripOnRows() ? 1 : 0))) + 15; }

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

function computeFit(){
  // Derived from the font, never measured off a rendered cell: cell height is
  // set by the grid track we compute here, so measuring it feeds back and can
  // collapse the page to 2 giant rows after a partial page.
  const shortRowH = Math.round(fontSize*1.3) + 8; // 3px padding + 1px border, top and bottom
  const mainRect = document.getElementById('main').getBoundingClientRect();
  const colNavH = document.getElementById('colNav').getBoundingClientRect().height;
  availH = mainRect.height - colNavH - GAP - (stripOnCols() ? statRowH() : 0);
  availW = mainRect.width - RHW - GAP;

  if(stripOnRows()){
    // The column-header row stays short (it's just sample/observation ids,
    // same as ever) -- only the field rows below it need the tall track,
    // so only they should compete for the height budget.
    autoRows = Math.max(1, Math.floor((availH - shortRowH) / statRowH()));
  } else {
    const totalRowsTarget = Math.max(2, Math.floor(availH/shortRowH)); // includes header row
    autoRows = totalRowsTarget - 1;
  }

  autoCols = Math.max(1, Math.floor(availW/COLW_TARGET));
}

let mode='data'; // 'data' | 'row' (observation metadata) | 'col' (sample metadata)
let rowFields=[], colFields=[];
const modeBtns = [...document.querySelectorAll('#modeGroup button')];

function setMode(m){
  mode = m;
  modeBtns.forEach(x=>x.classList.toggle('active', x.dataset.m===m));
  document.body.className = 'mode-'+m;
  document.getElementById('modeTag').textContent =
    m==='col' ? 'COL METADATA' : m==='row' ? 'ROW METADATA' : '';
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

async function loadMeta(){
  try{
    meta = await window.pywebview.api.meta();
    rowFields = fieldUnion(meta.row_metadata);
    colFields = fieldUnion(meta.col_metadata);
    document.getElementById('filename').textContent =
      `${meta.filename}  —  ${meta.rows} rows x ${meta.cols} cols`;
    buildSearchIndex();
    render();
  } catch(err){
    document.getElementById('filename').textContent = `Failed to load: ${err}`;
    console.error(err);
  }
}

function pageBounds(page, perPage, total){
  const start = page*perPage;
  return [start, Math.min(start+perPage, total)];
}

// Row/column axis for the grid currently on screen — depends on mode.
// 'row' mode only swaps the COLUMN axis (fields replace samples); the row
// axis (observation ids) stays exactly as in 'data' mode.
// 'col' mode only swaps the ROW axis (fields replace observations); the
// column axis (sample ids) stays exactly as in 'data' mode.
function rowsTotal(){ return mode==='col' ? colFields.length : meta.rows; }
function colsTotal(){ return mode==='row' ? rowFields.length : meta.cols; }
function rowLabel(i){ return mode==='col' ? colFields[i] : meta.row_ids[i]; }
function colLabel(j){ return mode==='row' ? rowFields[j] : meta.col_ids[j]; }

function formatMetaValue(v){
  if(Array.isArray(v)) v = v.length ? v.join(', ') : null;
  else if(v && typeof v === 'object') v = Object.entries(v).map(([k,x])=>`${k}=${x}`).join(', ');
  if(v===null || v===undefined || v==='') return {text:'—', cls:'mv-empty'};
  return {text:v, cls:'mv'};
}

function metaCellAt(i, j){
  // i = row index (grid row), j = col index (grid col)
  if(mode==='row'){
    // row axis = observation i (unchanged), col axis = field j
    const entry = meta.row_metadata && meta.row_metadata[i];
    return entry ? entry[rowFields[j]] : null;
  }
  // mode==='col': row axis = field i, col axis = sample j (unchanged)
  const entry = meta.col_metadata && meta.col_metadata[j];
  return entry ? entry[colFields[i]] : null;
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
  document.getElementById('searchResults').classList.remove('open');
}

async function jumpTo(entry){
  document.getElementById('searchBox').blur();
  if(entry.type==='sample'){
    setMode('data');
    colPage = Math.floor(entry.i / colsPerPage());
    selR = null; selC = entry.i;
  } else if(entry.type==='taxon'){
    setMode('data');
    rowPage = Math.floor(entry.i / rowsPerPage());
    selR = entry.i; selC = null;
  } else if(entry.type==='rowField'){
    setMode('row');
    colPage = Math.floor(entry.i / colsPerPage());
    selR = null; selC = entry.i;
  } else if(entry.type==='colField'){
    setMode('col');
    rowPage = Math.floor(entry.i / rowsPerPage());
    selR = entry.i; selC = null;
  } else if(entry.type==='rowValue'){
    setMode('row');
    rowPage = Math.floor(entry.i / rowsPerPage());
    colPage = Math.floor(entry.fi / colsPerPage());
    selR = entry.i; selC = entry.fi;
  } else if(entry.type==='colValue'){
    setMode('col');
    rowPage = Math.floor(entry.fi / rowsPerPage());
    colPage = Math.floor(entry.i / colsPerPage());
    selR = entry.fi; selC = entry.i;
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
  document.getElementById('rowUp').disabled = rowPage===0;
  document.getElementById('rowDown').disabled = r1>=rowsTotal();
  document.getElementById('colPrev').disabled = colPage===0;
  document.getElementById('colNext').disabled = c1>=colsTotal();

  const data = mode==='data' ? await window.pywebview.api.data_window(r0, r1, c0, c1) : null;

  // Stretch to fill availH x availW, but never past the auto-fit page size —
  // a partial last page keeps normal-height rows instead of ballooning.
  const renderedRows = r1-r0, renderedCols = c1-c0;
  let headerRowHPx;
  if(stripOnRows()){
    // Column headers stay short; only the field rows below need the tall
    // track, so the header doesn't compete with them for height.
    headerRowHPx = Math.round(fontSize*1.3) + 8;
    rowHPx = (availH - headerRowHPx) / Math.max(renderedRows, rowsPerPage());
  } else {
    rowHPx = availH/(Math.max(renderedRows, rowsPerPage())+1);
    headerRowHPx = rowHPx;
  }
  colWPx = availW/renderedCols;

  // Fetch stats for every visible row/column up front, in parallel, so the
  // grid below can be built synchronously once everything has arrived.
  const colStats = stripOnCols()
    ? await Promise.all(Array.from({length: renderedCols}, (_, k) => colStatsFetch(c0+k)))
    : null;
  const rowStats = stripOnRows()
    ? await Promise.all(Array.from({length: renderedRows}, (_, k) => window.pywebview.api.field_summary('sample', colFields[r0+k])))
    : null;

  const grid = document.getElementById('grid');
  const statRowTrack = stripOnCols() ? `${statRowH()}px ` : '';
  grid.style.gridTemplateColumns = `${RHW}px repeat(${renderedCols}, ${colWPx}px)`;
  grid.style.gridTemplateRows = `${rowHPx}px ${statRowTrack}repeat(${renderedRows}, ${rowHPx}px)`;
  grid.innerHTML = '';

  const corner = document.createElement('div');
  corner.className = 'cell hdr';
  grid.appendChild(corner);
  for(let c=c0;c<c1;c++){
    const label = colLabel(c);
    const h = document.createElement('div');
    h.className = 'cell hdr colhdr';
    h.textContent = label;
    h.title = label;
    h.dataset.c = c;
    h.addEventListener('click', ()=>{
      selR=null; selC=c;
      showSelected(label);
      applyHighlight();
    });
    h.addEventListener('dblclick', ()=>{ toggleSummary(); });
    grid.appendChild(h);
  }
  if(stripOnCols()){
    grid.appendChild(fillerCell());
    colStats.forEach((s, i) => {
      const cell = statCell(s);
      cell.dataset.c = c0 + i; // so applyHighlight() treats it as part of its column
      grid.appendChild(cell);
    });
  }
  for(let r=r0;r<r1;r++){
    const label = rowLabel(r);
    const rh = document.createElement('div');
    rh.className = 'cell rh';
    if(stripOnRows()){
      rh.classList.add('rh-stats');
      rh.innerHTML = `<div class="stat-line rh-label">${escapeHtml(label)}</div>` + statCellHtml(rowStats[r-r0]);
    } else {
      rh.textContent = label;
    }
    rh.title = label;
    rh.dataset.r = r;
    rh.addEventListener('click', ()=>{
      selR=r; selC=null;
      showSelected(label);
      applyHighlight();
    });
    rh.addEventListener('dblclick', ()=>{ toggleSummary(r); });
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
          selR=r; selC=c;
          showSelected(`${rowLabel(r)}  |  ${colLabel(c)}  =  ${v}`);
          applyHighlight();
        });
      } else {
        const raw = metaCellAt(r, c);
        const {text, cls} = formatMetaValue(raw);
        cell.className = 'cell ' + cls;
        cell.textContent = text;
        cell.title = `${rowLabel(r)}\n${colLabel(c)} = ${text}`;
        cell.addEventListener('click', ()=>{
          selR=r; selC=c;
          showSelected(`${rowLabel(r)}  |  ${colLabel(c)}  =  ${text}`);
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
}

function showSelected(text){
  const inp=document.getElementById('selected');
  inp.value = text;
  copySelected();
  inp.classList.add('flash');
  clearTimeout(showSelected._t);
  showSelected._t = setTimeout(()=>inp.classList.remove('flash'), 700);
}

function fmtNum(v){ return Number.isInteger(v) ? String(v) : v.toFixed(2); }

// The column axis is field-driven only in 'row' mode (observation metadata
// fields replace samples); everywhere else it's the sample axis, unchanged
// from data mode. Matches colLabel's own mode branch.
function colStatsFetch(j){
  return mode==='row'
    ? window.pywebview.api.field_summary('observation', rowFields[j])
    : window.pywebview.api.col_summary(j);
}

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
  const other = s.other_count ? `<div class="stat-line">+${s.other_count} other</div>` : '';
  return `<div class="stat-line">${presence}</div>` +
    `<div class="stat-line">Distinct <b>${s.distinct}</b> (${distinctPct}%)</div>` +
    topValueRows(s.top, presentTotal) + other;
}

function statCell(s){
  const cell = document.createElement('div');
  cell.className = 'cell stat-cell';
  cell.innerHTML = statCellHtml(s);
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
  if(selR===null && selC===null) return;
  // Excel-style: a single selected cell (both selR and selC set) only tints
  // its row/column headers, not the whole row/column body — the cell itself
  // gets the outline instead.
  const cellSelected = selR!==null && selC!==null;
  document.querySelectorAll('#grid [data-r],#grid [data-c]').forEach(el=>{
    const r = el.dataset.r!==undefined ? parseInt(el.dataset.r) : null;
    const c = el.dataset.c!==undefined ? parseInt(el.dataset.c) : null;
    const isHeader = r===null || c===null;
    if(selR!==null && r===selR && (isHeader || !cellSelected)) el.classList.add('hl-row');
    if(selC!==null && c===selC && (isHeader || !cellSelected)) el.classList.add('hl-col');
    if(cellSelected && r===selR && c===selC) el.classList.add('hl-cell');
  });
}

function openMeta(title, fields){
  document.getElementById('metaTitle').textContent = title;
  const rows = document.getElementById('metaRows');
  rows.innerHTML = '';
  const entries = Object.entries(fields).filter(([,v])=>v!==null && v!==undefined && v!=='');
  if(!entries.length){
    rows.outerHTML = '<div class="empty" id="metaRows">No metadata.</div>';
  } else {
    entries.forEach(([k,v])=>{
      const dt = document.createElement('dt'); dt.textContent = k;
      const dd = document.createElement('dd');
      dd.textContent = Array.isArray(v) ? v.join(', ') : v;
      rows.append(dt, dd);
    });
  }
  document.getElementById('metaOverlay').classList.add('open');
}

document.getElementById('metaBtn').onclick = ()=>{
  openMeta('Table metadata', {
    table_id: meta.table_id,
    type: meta.table_type,
    generated_by: meta.generated_by,
    create_date: meta.create_date,
  });
};
document.getElementById('metaClose').onclick = ()=>document.getElementById('metaOverlay').classList.remove('open');
document.getElementById('metaOverlay').addEventListener('click', (e)=>{
  if(e.target.id === 'metaOverlay') e.currentTarget.classList.remove('open');
});

// 'row' mode only swaps the column axis, 'col' mode only swaps the row axis —
// so reset just the axis whose meaning changed and keep your place on the other.
const rowAxisKey = m => m==='col' ? 'fields' : 'ids';
const colAxisKey = m => m==='row' ? 'fields' : 'ids';
modeBtns.forEach(b=>b.onclick = ()=>{
  const m = b.dataset.m;
  if(rowAxisKey(m)!==rowAxisKey(mode)){ rowPage = 0; selR = null; }
  if(colAxisKey(m)!==colAxisKey(mode)){ colPage = 0; selC = null; }
  setMode(m);
  render();
});

const searchBox = document.getElementById('searchBox');
let searchDebounce=null;
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
  else if(e.key==='Escape'){ results.classList.remove('open'); searchBox.blur(); }
});
document.addEventListener('click', (e)=>{
  if(!document.getElementById('searchWrap').contains(e.target)){
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

const themeBtn = document.getElementById('themeBtn');
const systemDark = window.matchMedia('(prefers-color-scheme: dark)');
// label shows the theme in effect; follows the system until the user overrides
function themeLabel(){
  const t = document.documentElement.dataset.theme || (systemDark.matches ? 'dark' : 'light');
  themeBtn.textContent = t === 'dark' ? '🌙 dark' : '☀️ light';
}
themeBtn.onclick = ()=>{
  const dark = (document.documentElement.dataset.theme || (systemDark.matches ? 'dark' : 'light')) === 'dark';
  document.documentElement.dataset.theme = dark ? 'light' : 'dark';
  themeLabel();
};
systemDark.addEventListener('change', themeLabel);
themeLabel();

function setFontSize(px){
  fontSize = Math.max(8, Math.min(28, px));
  document.documentElement.style.setProperty('--fs', fontSize+'px');
  rowPage=0; colPage=0; render();
}
document.getElementById('fontUp').onclick = ()=>setFontSize(fontSize+1);
document.getElementById('fontDown').onclick = ()=>setFontSize(fontSize-1);

window.addEventListener('pywebviewready', loadMeta);
</script>
</body></html>
"""


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


def main():
    global TABLE, FILENAME
    if len(sys.argv) < 2:
        print("Usage: biom-viewer <file.biom>", file=sys.stderr)
        sys.exit(1)
    path = sys.argv[1]
    TABLE = biom.load_table(path)
    FILENAME = path

    title = f"BIOM Viewer — {os.path.basename(path)}"
    webview.create_window(title, html=PAGE, js_api=Api(), width=1280, height=820, min_size=(600, 400))
    _set_dock_icon()
    webview.start()


if __name__ == "__main__":
    main()
