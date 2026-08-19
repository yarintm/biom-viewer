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


def field_summary(axis, field):
    entries = TABLE.metadata(axis=axis)
    total = len(entries)
    raw = [(dict(e) if e else {}).get(field) for e in entries]
    present = [
        v for v in raw
        if v is not None and v != "" and not (isinstance(v, float) and not math.isfinite(v))
    ]
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
    --hl:light-dark(#cfe0ff,#3a3a55); --sel-outline:light-dark(#2266cc,#6cf);
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
  #selectedWrap{display:flex;align-items:center;gap:6px;margin:6px 10px}
  #selected{flex:1;box-sizing:border-box;padding:5px 8px;background:transparent;color:var(--dim);
             border:1px solid transparent;border-radius:4px;font-family:ui-monospace,monospace;outline:none;
             caret-color:transparent;transition:color .15s}
  #selected.flash{color:var(--fg)}
  #summaryBtn{display:none;flex-shrink:0}
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
  .hl-row,.hl-col{background:var(--hl) !important}
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
  #summaryExtra .sg-cap{padding:2px 14px 4px;font:700 10px/1.4 ui-monospace,monospace;color:var(--dim);letter-spacing:.04em;text-transform:uppercase}
  #summaryExtra .hist{padding:0 14px 12px}
  .hist-row{display:flex;align-items:center;gap:6px;font-size:11px;margin:3px 0}
  .hist-label{width:100px;flex-shrink:0;color:var(--dim);text-align:right;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .hist-bar-wrap{flex:1;background:var(--hdr-bg);border-radius:3px;overflow:hidden;height:12px}
  .hist-bar{height:100%;background:var(--accent)}
  .hist-count{width:32px;flex-shrink:0;color:var(--dim)}
  #summaryExtra .sr-more{padding:0 14px 12px;font-size:11px;color:var(--dim);font-style:italic}
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
<div id="selectedWrap">
  <input id="selected" readonly value="Click a row, column, or cell to see its full text here (auto-copied to clipboard).">
  <button class="tool" id="summaryBtn" title="Show summary of the selected row/column">Σ Summary</button>
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
<div id="metaOverlay">
  <div id="metaModal">
    <header>
      <h3 id="metaTitle">Metadata</h3>
      <button class="x" id="metaClose">✕</button>
    </header>
    <dl class="rows" id="metaRows"></dl>
    <div id="summaryExtra"></div>
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
const GAP=14;
const COLW_TARGET=130, RHW=240;
function rowsPerPage(){ return autoRows; }
function colsPerPage(){ return autoCols; }

function computeFit(){
  // Derived from the font, never measured off a rendered cell: cell height is
  // set by the grid track we compute here, so measuring it feeds back and can
  // collapse the page to 2 giant rows after a partial page.
  const rowHTarget = Math.round(fontSize*1.3) + 8; // 3px padding + 1px border, top and bottom
  const mainRect = document.getElementById('main').getBoundingClientRect();
  const colNavH = document.getElementById('colNav').getBoundingClientRect().height;
  availH = mainRect.height - colNavH - GAP;
  availW = mainRect.width - RHW - GAP;

  const totalRowsTarget = Math.max(2, Math.floor(availH/rowHTarget)); // includes header row
  autoRows = totalRowsTarget - 1;

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
  rowHPx = availH/(Math.max(renderedRows, rowsPerPage())+1);
  colWPx = availW/renderedCols;

  const grid = document.getElementById('grid');
  grid.style.gridTemplateColumns = `${RHW}px repeat(${renderedCols}, ${colWPx}px)`;
  grid.style.gridTemplateRows = `repeat(${renderedRows+1}, ${rowHPx}px)`;
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
    grid.appendChild(h);
  }
  for(let r=r0;r<r1;r++){
    const label = rowLabel(r);
    const rh = document.createElement('div');
    rh.className = 'cell rh';
    rh.textContent = label;
    rh.title = label;
    rh.dataset.r = r;
    rh.addEventListener('click', ()=>{
      selR=r; selC=null;
      showSelected(label);
      applyHighlight();
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
  document.getElementById('summaryExtra').innerHTML = '';
  openMeta('Table metadata', {
    table_id: meta.table_id,
    type: meta.table_type,
    generated_by: meta.generated_by,
    create_date: meta.create_date,
  });
};
document.getElementById('summaryBtn').onclick = openSummary;
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
