"""Inline CSS for the BIOM Viewer webview page (biom_viewer/app.py's PAGE).

Kept as a plain string constant in its own module rather than a real static
asset file: pywebview gets handed one in-memory HTML string (no HTTP server),
and PyInstaller bundles this via normal Python import analysis with zero
build-script changes -- a real .css file would need explicit --add-data
wiring and a runtime read from the frozen bundle's resource path instead.
"""

STYLE = """
  /* ponytail: light-dark() + color-scheme does the whole thing natively —
     no system-mode listener, no duplicated dark/light var blocks. */
  :root{
    color-scheme: light dark;
    --bg:light-dark(#f7f7f5,#19191b); --fg:light-dark(#1c1c1e,#e8e8ea);
    --dim:light-dark(#6b6b70,#9b9ba1); --panel-bg:light-dark(#fff,#232326);
    --panel-raised:light-dark(#fff,#2a2a2e);
    --accent:light-dark(#0f7a52,#34d399);
    --border:light-dark(#e2e2e0,#38383c); --input-bg:light-dark(#fff,#1e1e21);
    --input-border:light-dark(#d3d3d0,#47474c);
    --cell-border:light-dark(#e6e6e4,#2c2c30); --hdr-bg:light-dark(#eeeeec,#242427);
    --hdr-fg:light-dark(#3a3a3d,#b8b8bd);
    --nz-bg:light-dark(#c9ecd9,#1f4636); --z-fg:light-dark(#86868b,#7c7c82);
    --hl:light-dark(#d7f2e3,#26493a); --sel-outline:var(--accent);
    --fs:11px;
    --radius-sm:6px; --radius-md:8px; --radius-lg:12px;
    --shadow-sm:light-dark(0 1px 2px rgba(0,0,0,.06),0 1px 2px rgba(0,0,0,.4));
    --shadow-md:light-dark(0 8px 24px rgba(0,0,0,.12),0 8px 28px rgba(0,0,0,.55));
    --shadow-lg:light-dark(0 20px 48px rgba(0,0,0,.18),0 20px 56px rgba(0,0,0,.6));
    --ease:cubic-bezier(.2,.8,.2,1); --dur:.14s;
    --row-meta:light-dark(#b3590a,#f0b578); --row-meta-bg:light-dark(#f7d3a2,#4a3216);
    --col-meta:light-dark(#0d4fb0,#8fc0ff); --col-meta-bg:light-dark(#bcdaff,#1e3455);
    --danger:light-dark(#c3392b,#ff7a70);
  }
  [data-theme="light"]{ color-scheme: light }
  [data-theme="dark"]{ color-scheme: dark }
  *{scrollbar-color:var(--input-border) transparent}
  html,body{margin:0;height:100%;font:14px/1.3 -apple-system,BlinkMacSystemFont,sans-serif;background:var(--bg);color:var(--fg);overflow:hidden}
  body{display:flex;flex-direction:column}
  button,input,select{font-family:inherit}
  button:focus-visible,input:focus-visible,select:focus-visible{outline:2px solid var(--sel-outline);outline-offset:1px}
  #info{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:10px 14px;
        background:var(--hdr-bg);border-bottom:1px solid var(--border);border-top:3px solid var(--accent);
        transition:border-top-color var(--dur) var(--ease)}
  body.mode-row #info{border-top-color:var(--row-meta)}
  body.mode-col #info{border-top-color:var(--col-meta)}
  /* min-width matters here, not just cosmetic: a flex item with
     overflow:hidden has an automatic minimum size of 0 per spec, so
     without a floor this collapses to a fully invisible 0px at narrow
     window widths instead of truncating down to some readable minimum
     (verified in the live preview harness at the app's own min_size). */
  #info #filename{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;letter-spacing:-.01em;min-width:60px}
  .file-dir{color:var(--dim);font-weight:400}
  .file-base{color:var(--fg);font-weight:700}
  #dims{flex-shrink:0;white-space:nowrap;margin-left:10px;color:var(--dim);font-size:11.5px;font-family:ui-monospace,monospace;
             background:var(--panel-bg);border:1px solid var(--border);border-radius:10px;padding:2px 8px}
  #info #toolbar{display:flex;align-items:center;gap:10px;flex-shrink:0}
  #modeTag{display:none;white-space:nowrap;flex-shrink:0;font:700 10px/1 ui-monospace,monospace;padding:3px 7px;border-radius:10px;
           border:1px solid currentColor;letter-spacing:.03em;margin-left:8px}
  body.mode-row #modeTag{display:inline-block;color:var(--row-meta)}
  body.mode-col #modeTag{display:inline-block;color:var(--col-meta)}
  #modeGroup{display:flex;background:var(--input-bg);border:1px solid var(--input-border);border-radius:var(--radius-sm);overflow:hidden;padding:2px}
  #modeGroup button{background:transparent;color:var(--dim);border:none;border-radius:5px;
           padding:4px 11px;font-size:12px;cursor:pointer;transition:background var(--dur) var(--ease),color var(--dur) var(--ease)}
  #modeGroup button:hover:not(.active){color:var(--fg);background:var(--hl)}
  #modeGroup button.active{background:var(--accent);color:var(--bg);font-weight:700}
  #modeGroup button[data-m="row"].active{background:var(--row-meta);color:var(--bg)}
  #modeGroup button[data-m="col"].active{background:var(--col-meta);color:var(--bg)}
  #searchWrap{position:relative;display:flex;align-items:center;gap:4px}
  #searchBox{width:220px;box-sizing:border-box;background:var(--input-bg);color:var(--fg);
             border:1px solid var(--input-border);border-radius:var(--radius-sm);padding:5px 9px;font-size:12.5px;outline:none;
             transition:border-color var(--dur) var(--ease)}
  #searchBox:focus{border-color:var(--sel-outline)}
  #searchPin,#searchPin:hover{border-color:transparent}
  #searchPin{padding:4px 6px;font-size:13px;opacity:.4;background:none}
  #searchPin:hover{opacity:.75;background:var(--hl)}
  #searchPin.on{opacity:1;background:var(--hl)}
  #searchResults{position:absolute;top:calc(100% + 6px);right:0;width:420px;max-height:60vh;overflow-y:auto;
             background:var(--panel-raised);border:1px solid var(--border);border-radius:var(--radius-md);
             box-shadow:var(--shadow-md);display:none;z-index:20}
  #searchResults.open{display:block}
  #searchResults.pinned{outline:2px solid var(--accent);outline-offset:2px}
  .stabs{position:sticky;top:0;z-index:1;display:flex;gap:2px;padding:5px 6px;overflow-x:auto;
             background:var(--panel-raised);border-bottom:1px solid var(--border)}
  .stabs::-webkit-scrollbar{display:none}
  .stab{flex:0 0 auto;padding:3px 8px;border-radius:var(--radius-sm);font-size:11.5px;color:var(--dim);
             cursor:pointer;white-space:nowrap;border:1px solid transparent;transition:background var(--dur) var(--ease)}
  .stab:hover{background:var(--hl)}
  .stab.active{background:var(--hl);color:var(--fg);border-color:var(--sel-outline);font-weight:600}
  .stab .n{margin-left:5px;font-family:ui-monospace,monospace;font-size:10.5px;opacity:.75}
  .sg{padding:6px 0}
  .sg + .sg{border-top:1px solid var(--border)}
  .sg-cap{padding:2px 10px;font:700 10px/1.4 ui-monospace,monospace;color:var(--dim);letter-spacing:.04em;text-transform:uppercase}
  .sr{padding:5px 10px;font-size:12.5px;cursor:pointer;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .sr:hover,.sr.hi{background:var(--hl)}
  .sr .sr-field{color:var(--dim)}
  .sr mark{background:var(--nz-bg);color:inherit;border-radius:2px;padding:0 1px;font-weight:700}
  .sr-more{padding:3px 10px;font-size:11px;color:var(--dim);font-style:italic}
  .sr-more[data-tab]{cursor:pointer;text-decoration:underline}
  .sr-more[data-tab]:hover{color:var(--fg)}
  .sr-empty{padding:8px 10px;font-size:12.5px;color:var(--dim)}
  #selectedWrap{display:flex;align-items:center;gap:6px;margin:8px 14px;background:var(--panel-bg);
             border:1px solid var(--border);border-radius:var(--radius-sm);padding:1px}
  #selected{flex:1;min-width:0;box-sizing:border-box;padding:6px 9px;background:transparent;color:var(--dim);
             border:1px solid transparent;border-radius:5px;font-family:ui-monospace,monospace;outline:none;
             caret-color:transparent;transition:color .15s}
  #selected.flash{color:var(--fg)}
  #expandBtn{flex:none;margin-right:3px}
  button.nav,button.tool{background:var(--panel-bg);color:var(--fg);border:1px solid var(--input-border);border-radius:var(--radius-sm);padding:4px 10px;cursor:pointer;
             font-size:14px;line-height:1;transition:background var(--dur) var(--ease),border-color var(--dur) var(--ease)}
  button.nav:hover:not(:disabled),button.tool:hover{background:var(--hl);border-color:var(--sel-outline)}
  button.nav:active:not(:disabled),button.tool:active{transform:translateY(.5px)}
  button.nav:disabled{opacity:.35;cursor:default}
  #viewsBtn{max-width:380px;flex-shrink:0}
  .views-current-name{font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
             max-width:340px;display:inline-block;vertical-align:bottom}
  .views-dirty-dot{color:var(--row-meta);font-size:8px;margin:0 1px;vertical-align:middle}
  /* Deliberately no color for the plain "a view is active" state -- the
     name in the button already says that. Color is reserved for the one
     state that needs it (unsaved changes), so it isn't fighting the green
     used elsewhere (chips, selection, accent) for attention. */
  .views-dirty-banner{background:var(--row-meta-bg);border:1px solid var(--row-meta);border-radius:6px;
             padding:7px 8px;margin-bottom:6px}
  .views-dirty-msg{color:var(--row-meta);font-size:11.5px;font-weight:600;margin-bottom:6px}
  .views-dirty-actions{display:flex;gap:4px}
  .views-dirty-actions button{flex:1;border-radius:5px;padding:4px 0;font-size:12px;cursor:pointer;
             transition:filter var(--dur) var(--ease)}
  .views-update-btn{background:var(--row-meta);color:var(--bg);border:1px solid var(--row-meta);font-weight:600}
  .views-revert-btn{background:none;color:var(--row-meta);border:1px solid var(--row-meta)}
  .views-dirty-actions button:hover{filter:brightness(0.95)}
  #body{display:flex;flex:1;min-height:0;padding:0 14px 10px}
  #rowNav{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:6px;padding-right:10px}
  #rowNav span{writing-mode:vertical-rl;color:var(--dim);white-space:nowrap;font-size:11.5px}
  #main{flex:1;display:flex;flex-direction:column;overflow:hidden}
  #colNav{display:flex;align-items:center;justify-content:center;gap:10px;padding-bottom:8px}
  #colNav span{color:var(--dim);font-size:11.5px}
  #rowNav span.range-filtered,#colNav span.range-filtered{color:var(--danger);font-weight:700}
  #grid{display:grid;overflow:hidden;flex-shrink:0;align-self:flex-start;border-radius:var(--radius-sm);box-shadow:var(--shadow-sm)}
  .cell{border:1px solid var(--cell-border);padding:3px 6px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:var(--fs);transition:background .1s var(--ease)}
  .hdr{background:var(--hdr-bg);color:var(--hdr-fg)}
  .rh{background:var(--hdr-bg);color:var(--hdr-fg);cursor:pointer}
  .rh:hover{background:var(--input-border)}
  .hdr.colhdr{cursor:pointer}
  .hdr.colhdr:hover{background:var(--input-border)}
  /* Row-header identifiers in Data/Row mode (taxonomy strings like
     "k__Bacteria|p__...|s__species") share a long common prefix and differ
     only near the end -- truncating from the end (the default) makes most
     rows look identical. Truncating from the start instead keeps the
     actually-distinguishing tail visible. Standard CSS trick: flip the box
     to rtl so text-overflow's "end" is the left edge -- the Latin text
     itself still renders left-to-right because it forms its own embedded
     LTR run inside the rtl paragraph (default unicode-bidi:normal); adding
     unicode-bidi:plaintext here is a trap, not a refinement -- it makes
     the browser auto-detect paragraph direction from the *content*, which
     is Latin, so it silently overrides direction:rtl and the whole trick
     does nothing. Verified in a live preview harness after this shipped
     with plaintext and the truncation direction turned out unchanged from
     before the "fix". Scoped to Data/Row mode only -- in Col mode .rh
     holds metadata *field names* (English text), which read better with
     normal end-truncation. */
  body.mode-data .rh,body.mode-row .rh{direction:rtl;text-align:left}
  .pin-last{border-bottom:2px solid var(--accent)}
  #filterPopover,#ctxMenu,#viewsPopover,#confirmPopover{background:var(--panel-raised);border:1px solid var(--border);
             box-shadow:var(--shadow-md);border-radius:var(--radius-md)}
  #filterPopover{position:fixed;z-index:30;padding:7px;display:flex;gap:4px;align-items:center}
  #filterPopover input{width:70px;box-sizing:border-box;background:var(--input-bg);color:var(--fg);
             border:1px solid var(--input-border);border-radius:5px;padding:3px 6px;font-size:12px}
  #filterPopover button,.fp-buttons button,.confirm-buttons button,.views-save-btn{
             background:var(--panel-bg);color:var(--fg);border:1px solid var(--input-border);
             border-radius:5px;padding:3px 9px;font-size:12px;cursor:pointer;transition:background var(--dur) var(--ease)}
  #filterPopover button:hover,.fp-buttons button:hover,.confirm-buttons button:hover,.views-save-btn:hover{background:var(--hl)}
  #filterPopover.fp-checklist{flex-direction:column;align-items:stretch;width:220px}
  #filterPopover.fp-checklist input.fp-search{width:100%}
  .fp-actions{display:flex;gap:4px}
  .fp-actions button{flex:1}
  #ctxMenu{position:fixed;z-index:40;padding:4px;min-width:200px}
  .ctx-sep{height:1px;background:var(--border);margin:4px 2px}
  .ctx-item{display:block;width:100%;text-align:left;background:none;border:none;color:var(--fg);
             padding:6px 10px;border-radius:5px;cursor:pointer;font-size:12.5px;white-space:nowrap;
             overflow:hidden;text-overflow:ellipsis;transition:background var(--dur) var(--ease)}
  .ctx-item:hover{background:var(--hl)}
  .ctx-item code{font-family:ui-monospace,monospace;font-size:11px;background:var(--hdr-bg);
             color:var(--hdr-fg);padding:1px 5px;border-radius:4px}
  .fp-list{max-height:220px;overflow-y:auto;border:1px solid var(--input-border);border-radius:5px}
  .fp-row{display:flex;align-items:center;gap:6px;padding:3px 6px;font-size:12px;cursor:pointer}
  .fp-row:hover{background:var(--hl)}
  .fp-row .fp-val{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .fp-row .fp-count{color:var(--dim);font-family:ui-monospace,monospace;font-size:10.5px}
  .fp-buttons{display:flex;gap:4px}
  .fp-buttons button{flex:1}
  /* Always visible now (not gated on chips.length) -- Views lives here as
     the first item, and it needs to stay reachable even with zero other
     chips, not disappear along with them. */
  #axisChips{display:flex;align-items:flex-start;gap:6px;padding:8px 14px;background:var(--panel-bg);border-bottom:1px solid var(--border)}
  #axisChipsList{display:flex;gap:6px;flex-wrap:wrap;align-items:center}
  /* Deliberately neutral -- the icon per chip type (📌 ⇅ 🔽 ✏️ 🗑) already
     tells them apart, so a uniform accent color here wasn't conveying
     anything beyond "this app uses green a lot everywhere." */
  .chip{display:inline-flex;align-items:center;gap:6px;background:var(--panel-bg);color:var(--fg);
             border:1px solid var(--border);border-radius:12px;padding:4px 6px 4px 10px;font-size:11.5px;
             box-shadow:var(--shadow-sm)}
  .chip code{font-family:ui-monospace,monospace;font-size:10.5px;background:var(--panel-bg);
             padding:1px 4px;border-radius:3px}
  .chip-x{background:var(--panel-bg);border:none;color:var(--dim);cursor:pointer;font-size:10px;
             width:16px;height:16px;border-radius:50%;line-height:1;display:inline-flex;
             align-items:center;justify-content:center;transition:background var(--dur) var(--ease),color var(--dur) var(--ease)}
  .chip-x:hover{color:var(--danger);background:var(--panel-raised)}
  .chip-clear-all{background:none;color:var(--dim);border-style:dashed;border-color:var(--input-border);
             font-weight:600;cursor:pointer;padding:4px 10px;box-shadow:none}
  .chip-clear-all:hover{color:var(--danger);border-color:var(--danger);background:var(--panel-raised)}
  #viewsPopover{position:fixed;z-index:30;padding:7px;display:flex;flex-direction:column;gap:4px;width:220px}
  .views-list{display:flex;flex-direction:column;gap:2px;max-height:260px;overflow-y:auto}
  .views-empty{color:var(--dim);font-size:12px;padding:4px 6px}
  .views-row{display:flex;align-items:center;gap:6px;padding:4px 6px;border-radius:5px;cursor:pointer;transition:background var(--dur) var(--ease)}
  .views-row:hover{background:var(--hl)}
  .views-row.active{background:var(--hl);font-weight:700}
  .views-name{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:12px}
  .views-x{background:none;border:none;color:var(--dim);cursor:pointer;font-size:10px;padding:0;line-height:1}
  .views-x:hover{color:var(--danger)}
  .views-save{display:flex;gap:4px;border-top:1px solid var(--border);padding-top:6px}
  .views-save-input,.views-rename-input{flex:1;box-sizing:border-box;background:var(--input-bg);color:var(--fg);
    border:1px solid var(--input-border);border-radius:5px;padding:3px 6px;font-size:12px}
  .views-rename-input.error{border-color:var(--danger)}
  #confirmPopover{position:fixed;z-index:40;left:50%;top:40%;transform:translate(-50%,-50%);padding:14px;
    display:flex;flex-direction:column;gap:10px}
  .confirm-msg{font-size:13px}
  .confirm-buttons{display:flex;gap:6px;justify-content:flex-end}
  .confirm-discard{border-color:var(--danger)!important;color:var(--danger)}
  .z{color:var(--z-fg)}
  .nz{background:var(--nz-bg)}
  .mv{color:var(--fg)}
  .mv-empty{color:var(--z-fg);font-style:italic}
  .cell:not(.rh):not(.colhdr):not(.stat-cell).hl-row,.cell:not(.rh):not(.colhdr):not(.stat-cell).hl-col{background:var(--hl) !important}
  /* A plain click used to paint THREE equally-weighted 2px outline boxes
     (the cell, its row header, its column header) -- competing for
     attention instead of showing one clear focal point. Headers now only
     go bold, keeping their own orange/row-meta or blue/col-meta identity
     background intact, so .hl-cell's outline is the only "this is the
     exact selection" signal left; bold text on the headers is just
     "...and this is the row/column it's in" -- present but quieter. */
  .rh.hl-row,.colhdr.hl-col{font-weight:700}
  /* When the column stats strip is showing, .colhdr (field/sample label)
     and the .stat-cell directly below it are two separate grid cells that
     read as one merged header block -- so their shared border must not
     double up into two stacked boxes. colhdr keeps top/left/right only,
     stat-cell keeps bottom/left/right only, and the seam's native cell
     border is hidden so nothing shows between them. */
  #grid.col-stats .colhdr.hl-col{box-shadow:inset 0 2px 0 var(--sel-outline),inset 2px 0 0 var(--sel-outline),inset -2px 0 0 var(--sel-outline)}
  #grid.col-stats .stat-cell.hl-col{box-shadow:inset 0 -2px 0 var(--sel-outline),inset 2px 0 0 var(--sel-outline),inset -2px 0 0 var(--sel-outline);border-top-color:transparent}
  .hl-cell{outline:2px solid var(--sel-outline);outline-offset:-2px;position:relative;z-index:1}
  /* row axis (observation ids, leftmost column) orange; col axis (sample ids,
     top row) blue — in data mode both are on screen at once */
  body.mode-row .rh,body.mode-data .rh{background:var(--row-meta-bg);color:var(--row-meta);border-color:var(--row-meta);font-weight:700}
  body.mode-row .rh:not(.hl-row),body.mode-data .rh:not(.hl-row){box-shadow:inset 3px 0 0 var(--row-meta)}
  body.mode-col .hdr.colhdr,body.mode-data .hdr.colhdr{background:var(--col-meta-bg);color:var(--col-meta);border-color:var(--col-meta);font-weight:700}
  body.mode-col .hdr.colhdr:not(.hl-col),body.mode-data .hdr.colhdr:not(.hl-col){box-shadow:inset 0 -3px 0 var(--col-meta)}
  #replaceModal{width:420px;border-radius:var(--radius-lg)}
  #replaceModal header{justify-content:space-between}
  #replaceModal header h3{margin-right:0}
  #replaceModal .rp-form{padding:12px 14px;display:flex;flex-wrap:wrap;gap:6px}
  #replaceModal .rp-form select, #replaceModal .rp-form input{background:var(--input-bg);color:var(--fg);
             border:1px solid var(--input-border);border-radius:4px;padding:4px 6px;font-size:12.5px}
  #replaceModal .rp-form select{flex:1 1 100%}
  #replaceModal .rp-form input{flex:1 1 45%;min-width:0}
  #replaceModal .rp-form button{flex:0 0 auto}
  #rpList{padding:0 14px 14px;display:flex;flex-direction:column;gap:4px;max-height:30vh;overflow-y:auto}
  #rpList .rp-item{display:flex;align-items:center;justify-content:space-between;gap:8px;
             background:var(--hl);border-radius:6px;padding:4px 8px;font-size:12px}
  #rpList .rp-item button{background:none;border:none;color:var(--dim);cursor:pointer;font-size:12px}
  #rpList .rp-item button:hover{color:var(--fg)}
  .wm-overlay{position:fixed;inset:0;background:rgba(0,0,0,.4);backdrop-filter:blur(6px);display:none;
               align-items:center;justify-content:center;z-index:10}
  .wm-overlay.open{display:flex}
  .wm-modal{background:var(--panel-raised);border:1px solid var(--border);border-radius:var(--radius-lg);
             width:640px;max-width:92vw;box-shadow:var(--shadow-lg);
             /* pywebview disables selection app-wide by default (text_select=False,
                see its injected `body{user-select:none}`) so the grid's own
                click-to-copy paradigm doesn't fight drag-selection -- but content
                in these windows exists specifically to be read/selected/copied,
                so re-enable it here; a class selector beats that plain `body` one. */
             -webkit-user-select:text;user-select:text;cursor:auto}
  .wm-modal header{display:flex;align-items:center;justify-content:flex-end;gap:8px;
                     padding:12px 14px;border-bottom:1px solid var(--border)}
  .wm-modal header h3{margin:0;font-size:14px;margin-right:auto}
  .wm-modal .x{cursor:pointer;color:var(--dim);font-size:16px;line-height:1;background:none;border:none}
  .wm-modal .x:hover{color:var(--fg)}
  .wm-body{margin:0;padding:14px;font-family:ui-monospace,monospace;font-size:12px;
             white-space:pre;overflow:auto;max-height:60vh}
  .wm-body.wm-list{white-space:normal;display:flex;flex-direction:column;gap:2px}
  .wm-list .wm-row{display:flex;justify-content:space-between;gap:10px;padding:2px 4px;border-radius:3px}
  .wm-list .wm-row:hover{background:var(--hl)}
  .wm-list .wm-row .wm-count{color:var(--dim);flex:none}
  .stat-cell,.rh-stats{background:var(--panel-bg);color:var(--dim);font-size:calc(var(--fs)*0.9);line-height:1.35;
             padding:4px 6px;display:flex;flex-direction:column;gap:3px;overflow:hidden;cursor:pointer;min-height:0}
  .rh-stats{white-space:normal}
  .rh-stats:hover{background:var(--panel-bg)}
  .rh-stats .rh-label{font-size:var(--fs);font-weight:700;color:var(--hdr-fg);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
             background:var(--hdr-bg);margin:-4px -6px 4px;padding:4px 6px;cursor:pointer;flex-shrink:0}
  .rh-stats .rh-label:hover{background:var(--input-border)}
  /* The label bar's own opaque background paints over the parent cell's
     top/left/right edges (its negative margins stretch it to the cell
     border), hiding the selection border there -- redraw those edges on
     the label itself so the border reads as continuous when selected. */
  .rh-stats.hl-row .rh-label{box-shadow:inset 0 2px 0 var(--sel-outline),inset 2px 0 0 var(--sel-outline),inset -2px 0 0 var(--sel-outline)}
  /* flex-shrink:0: without it, if the stat block's fixed-height grid track
     (see statRowH()) is even a hair short of the flex column's natural
     content height, every line shrinks below its own line-height to fit --
     and since each line also clips its own overflow, that shaves the
     bottom few px off EVERY line (descenders like g/y sliced flat), not
     just whatever's at the container's bottom edge. Forcing full natural
     height per line means a measurement shortfall clips at most the last
     line instead of shaving every line a little. */
  .stat-line{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;flex-shrink:0}
  .stat-line b{color:var(--fg);font-weight:600}
  .stat-other{cursor:pointer;text-decoration:underline}
  .stat-other:hover{color:var(--fg)}
  .stat-bars{display:flex;align-items:flex-end;gap:1px;height:calc(var(--fs)*1.8);margin:1px 0;flex-shrink:0}
  .stat-bars .bar{flex:1;background:var(--accent);border-radius:1px;min-height:2px}
  .stat-top-row{position:relative;padding:1px 3px;border-radius:2px;overflow:hidden;display:flex;
                align-items:center;justify-content:space-between;gap:4px;flex-shrink:0}
  .stat-top-row .fill{position:absolute;inset:0;background:var(--nz-bg);z-index:0}
  .stat-top-row .lbl,.stat-top-row .pct{position:relative;z-index:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .stat-top-row .pct{flex-shrink:0;font-family:ui-monospace,monospace}
"""
