#!/usr/bin/env python3
"""Lazy-loading BIOM viewer: native window (pywebview) + biom-format, sparse-window slicing, canvas grid UI."""
import os
import sys

import biom
import webview

TABLE = None
FILENAME = ""

# ponytail: whole id list sent once (text-only, cheap even at ~1e5 rows); paginate if a table
# ever has >~500k ids and this becomes a multi-MB response.
def meta():
    obs_ids = TABLE.ids("observation").tolist()
    sample_ids = TABLE.ids("sample").tolist()
    return {
        "filename": FILENAME,
        "rows": TABLE.shape[0],
        "cols": TABLE.shape[1],
        "row_ids": obs_ids,
        "col_ids": sample_ids,
    }


def data_window(r0, r1, c0, c1):
    r1 = min(r1, TABLE.shape[0])
    c1 = min(c1, TABLE.shape[1])
    # Densify only the requested window, never the full matrix.
    sub = TABLE.matrix_data[r0:r1, :].tocsc()[:, c0:c1]
    return sub.toarray().tolist()


class Api:
    """Exposed to the frontend as window.pywebview.api.* — no HTTP server involved."""

    def meta(self):
        return meta()

    def data_window(self, r0, r1, c0, c1):
        return data_window(r0, r1, c0, c1)


PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>BIOM Viewer</title>
<style>
  :root{
    color-scheme: dark;
    --bg:#1e1e1e; --fg:#ddd; --dim:#999; --panel-bg:#111; --accent:#9f9;
    --border:#444; --input-bg:#111; --input-border:#555;
    --cell-border:#333; --hdr-bg:#252525; --hdr-fg:#aaa;
    --nz-bg:#274b3a; --z-fg:#666; --hl:#3a3a55; --sel-outline:#6cf;
    --fs:11px;
  }
  [data-theme="light"]{
    color-scheme: light;
    --bg:#f5f5f5; --fg:#222; --dim:#666; --panel-bg:#fff; --accent:#177245;
    --border:#ccc; --input-bg:#fff; --input-border:#bbb;
    --cell-border:#ddd; --hdr-bg:#e8e8e8; --hdr-fg:#333;
    --nz-bg:#bfe8d3; --z-fg:#aaa; --hl:#cfe0ff; --sel-outline:#2266cc;
  }
  html,body{margin:0;height:100%;font:14px/1.3 -apple-system,sans-serif;background:var(--bg);color:var(--fg);overflow:hidden}
  body{display:flex;flex-direction:column}
  #info{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:8px 10px;
        background:var(--hdr-bg);border-bottom:1px solid var(--border)}
  #info #filename{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  #info #toolbar{display:flex;align-items:center;gap:8px;flex-shrink:0}
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
  .hl-row,.hl-col{background:var(--hl) !important}
  .hl-cell{outline:2px solid var(--sel-outline);outline-offset:-2px;position:relative;z-index:1}
</style></head>
<body>
<div id="info">
  <span id="filename">loading…</span>
  <span id="toolbar">
    <button class="tool" id="themeBtn">🌙 dark</button>
    <button class="tool" id="fontDown">A-</button>
    <button class="tool" id="fontUp">A+</button>
  </span>
</div>
<input id="selected" readonly value="Click a row, column, or cell to see its full text here (auto-copied to clipboard).">
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
<script>
let meta=null, rowPage=0, colPage=0, selR=null, selC=null, fontSize=11;
let autoRows=20, autoCols=8, rowHPx=22, colWPx=130;
let availH=0, availW=0;
const GAP=14;
const COLW_TARGET=130, RHW=240;
function rowsPerPage(){ return autoRows; }
function colsPerPage(){ return autoCols; }

function computeFit(){
  const sampleCell = document.querySelector('#grid .cell');
  const rowHTarget = sampleCell ? sampleCell.getBoundingClientRect().height : Math.round(fontSize*1.3)+8;
  const mainRect = document.getElementById('main').getBoundingClientRect();
  const colNavH = document.getElementById('colNav').getBoundingClientRect().height;
  availH = mainRect.height - colNavH - GAP;
  availW = mainRect.width - RHW - GAP;

  const totalRowsTarget = Math.max(2, Math.floor(availH/rowHTarget)); // includes header row
  autoRows = totalRowsTarget - 1;

  autoCols = Math.max(1, Math.floor(availW/COLW_TARGET));
}

async function loadMeta(){
  meta = await window.pywebview.api.meta();
  document.getElementById('filename').textContent =
    `${meta.filename}  —  ${meta.rows} rows x ${meta.cols} cols`;
  render();
}

function pageBounds(page, perPage, total){
  const start = page*perPage;
  return [start, Math.min(start+perPage, total)];
}

async function render(){
  computeFit();
  const [r0,r1] = pageBounds(rowPage, rowsPerPage(), meta.rows);
  const [c0,c1] = pageBounds(colPage, colsPerPage(), meta.cols);
  document.getElementById('rowRange').textContent = `rows ${r0+1}-${r1} / ${meta.rows}`;
  document.getElementById('colRange').textContent = `cols ${c0+1}-${c1} / ${meta.cols}`;
  document.getElementById('rowUp').disabled = rowPage===0;
  document.getElementById('rowDown').disabled = r1>=meta.rows;
  document.getElementById('colPrev').disabled = colPage===0;
  document.getElementById('colNext').disabled = c1>=meta.cols;

  const data = await window.pywebview.api.data_window(r0, r1, c0, c1);

  // stretch to the actually-rendered row/col count (may be fewer than the
  // auto-fit target on a small table or a partial last page), so the grid
  // always fills availH x availW with the fixed GAP, never leaving slack.
  const renderedRows = r1-r0, renderedCols = c1-c0;
  rowHPx = availH/(renderedRows+1);
  colWPx = availW/renderedCols;

  const grid = document.getElementById('grid');
  grid.style.gridTemplateColumns = `${RHW}px repeat(${renderedCols}, ${colWPx}px)`;
  grid.style.gridTemplateRows = `repeat(${renderedRows+1}, ${rowHPx}px)`;
  grid.innerHTML = '';

  const corner = document.createElement('div');
  corner.className = 'cell hdr';
  grid.appendChild(corner);
  for(let c=c0;c<c1;c++){
    const h = document.createElement('div');
    h.className = 'cell hdr colhdr';
    h.textContent = meta.col_ids[c];
    h.title = meta.col_ids[c];
    h.dataset.c = c;
    h.addEventListener('click', ()=>{
      selR=null; selC=c;
      showSelected(`column: ${meta.col_ids[c]}`);
      applyHighlight();
    });
    grid.appendChild(h);
  }
  for(let r=r0;r<r1;r++){
    const label = meta.row_ids[r];
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
      const v = data[r-r0][c-c0];
      const cell = document.createElement('div');
      cell.className = 'cell ' + (v===0 ? 'z' : 'nz');
      cell.textContent = Number.isInteger(v) ? v : v.toFixed(3);
      cell.title = `${meta.row_ids[r]}\n${meta.col_ids[c]} = ${v}`;
      cell.dataset.r = r; cell.dataset.c = c;
      cell.addEventListener('click', ()=>{
        selR=r; selC=c;
        showSelected(`${meta.row_ids[r]}  |  ${meta.col_ids[c]}  =  ${v}`);
        applyHighlight();
      });
      grid.appendChild(cell);
    }
  }
  applyHighlight();
}

function showSelected(text){
  const inp=document.getElementById('selected');
  inp.value = text;
  navigator.clipboard.writeText(text).catch(()=>{});
  inp.classList.add('flash');
  clearTimeout(showSelected._t);
  showSelected._t = setTimeout(()=>inp.classList.remove('flash'), 700);
}

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
themeBtn.onclick = ()=>{
  const light = document.documentElement.dataset.theme === 'light';
  document.documentElement.dataset.theme = light ? 'dark' : 'light';
  themeBtn.textContent = light ? '🌙 dark' : '☀️ light';
};

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
