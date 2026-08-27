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
    --hdr-bg-sel:light-dark(#dcdcd8,#34343a);
    --hdr-fg:light-dark(#3a3a3d,#b8b8bd);
    --nz-bg:light-dark(#c9ecd9,#1f4636); --z-fg:light-dark(#86868b,#7c7c82);
    /* The full-strength end of the magnitude ramp (see .nz1-.nz6). Chosen
       so cell text still clears 4.5:1 against it at full strength -- 7.0:1
       with #1c1c1e in light, 5.1:1 with #e8e8ea in dark -- since the
       darkest cells are exactly the ones carrying the biggest numbers. */
    --heat:light-dark(#4cb98a,#2c6b50);
    /* Search matches used to be painted in --nz-bg, i.e. the exact green
       that means "this matrix cell is non-zero" everywhere else on screen.
       Find-highlighting has its own near-universal colour and no competing
       meaning in this app, so it gets its own token. */
    --match-bg:light-dark(#ffe9a3,#6b5410); --match-fg:light-dark(#3d2f00,#ffe9a3);
    --hl:light-dark(#d7f2e3,#26493a); --sel-outline:var(--accent);
    /* Same tint at roughly a third of the strength, for the one place a
       selection has to paint an unusually large area (see
       .cell-expanded-row) -- perceived colour intensity scales with area,
       so a tint tuned for a 20px row reads as a solid block at 130px. */
    --hl-soft:light-dark(#eef9f3,#1c3529);
    --fs:11px;
    --radius-sm:6px; --radius-md:8px; --radius-lg:12px;
    --shadow-sm:light-dark(0 1px 2px rgba(0,0,0,.06),0 1px 2px rgba(0,0,0,.4));
    --shadow-md:light-dark(0 8px 24px rgba(0,0,0,.12),0 8px 28px rgba(0,0,0,.55));
    --shadow-lg:light-dark(0 20px 48px rgba(0,0,0,.18),0 20px 56px rgba(0,0,0,.6));
    --ease:cubic-bezier(.2,.8,.2,1); --dur:.14s;
    /* The light tints used to be far more saturated than their dark
       counterparts -- dark's #4a3216/#1e3455 sit a small step off a #19191b
       background, while light's #f7d3a2/#bcdaff were a big chromatic jump
       off #f7f7f5, so the same design read as restrained in dark mode and as
       a wall of peach and blue in light mode. Matched to the dark side's
       restraint, which also fixed a real contrast failure: #b3590a on
       #f7d3a2 measured 3.40:1, under the 4.5:1 minimum for text this size.
       #8a4408 on #fbe6cd is 5.9:1; the column pair is 6.3:1. */
    --row-meta:light-dark(#8a4408,#f0b578); --row-meta-bg:light-dark(#fbe6cd,#4a3216);
    --col-meta:light-dark(#0d4fb0,#8fc0ff); --col-meta-bg:light-dark(#dcebff,#1e3455);
    /* One step deeper than the resting tint, for "your selection is in this
       row/column". Text contrast holds: 5.1:1 on the row pair, 5.4:1 on the
       column pair. */
    --row-meta-bg-sel:light-dark(#f5d3a8,#6b4a20);
    --col-meta-bg-sel:light-dark(#c4dcff,#2e4d7d);
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
  /* Only the directory half gives way. Truncating the label as one string
     ate the basename first (the whole path is one run, so the ellipsis
     lands at the end) and a narrow window was left showing "/Users/..." --
     the document's own name, the one thing the title has to carry, gone.
     The basename is flex:none so it survives to the last pixel; the dir
     shrinks around it. */
  #info #filename{display:flex;align-items:baseline;overflow:hidden;letter-spacing:-.01em;min-width:60px}
  /* flex-shrink 100 vs 1: the directory gives up ~100px for every 1px the
     basename does, so it is effectively gone before the name starts to
     ellipsise, instead of both shrinking together and neither being
     readable. */
  .file-dir{color:var(--dim);font-weight:400;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;flex:0 100 auto;min-width:0}
  .file-base{color:var(--fg);font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;flex:0 1 auto;min-width:0}
  #dims{flex-shrink:0;white-space:nowrap;margin-left:10px;color:var(--dim);font-size:11.5px;font-family:ui-monospace,monospace;
             background:var(--panel-bg);border:1px solid var(--border);border-radius:10px;padding:2px 8px}
  /* Below this the top row can't hold the path, the dimensions pill, the
     mode tag and the mode switcher at once, and flex was resolving it by
     clipping the pills mid-glyph -- "60 x 24" showing as a lone "6". The
     path and the mode controls are what you steer by; the pills are a
     readout, and the mode tag only ever restates the highlighted button
     two inches to its right. Both come back when the window widens. */
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
  /* The pin only means anything while results are on screen. Parked in the
     toolbar as a bare 40%-opacity emoji it was the least legible control in
     the app -- unlabelled, and at that opacity it read as *disabled* rather
     than "off" (relying on opacity alone to signal state is exactly what
     accessibility guidance warns against). Docked into the results panel's
     tab strip with a word next to it, it appears when it's relevant and
     says what it does. */
  #searchPin{display:none}
  /* z-index has to clear #searchResults' own 20 -- they're siblings in the
     same stacking context, so the panel paints over anything below it. */
  /* Keyed off .stabs, not .open: the panel is also "open" when it holds
     just "No matches", and there is nothing to keep open then -- the pin
     was floating over that one line of text. .stabs exists only when there
     are results. */
  #searchWrap:has(#searchResults.open .stabs) #searchPin{position:absolute;z-index:21;
             top:calc(100% + 11px);right:8px;display:flex;align-items:center;gap:4px;
             padding:3px 8px;font-size:11.5px;line-height:1.4;color:var(--dim);
             background:none;border:1px solid transparent}
  #searchWrap #searchPin:hover{color:var(--fg);background:var(--hl)}
  #searchWrap #searchPin.on{color:var(--fg);background:var(--hl);border-color:var(--sel-outline)}
  #searchResults{position:absolute;top:calc(100% + 6px);right:0;width:420px;max-height:60vh;overflow-y:auto;
             background:var(--panel-raised);border:1px solid var(--border);border-radius:var(--radius-md);
             box-shadow:var(--shadow-md);display:none;z-index:20}
  #searchResults.open{display:block}
  /* Pinned state used to be an accent outline around the whole panel --
     the same 2px accent box the grid uses for "this is the selected cell",
     meaning two unrelated things in one screen. The toggle's own on-state
     carries it now. */
  .stabs{position:sticky;top:0;z-index:1;display:flex;gap:2px;padding:5px 96px 5px 6px;overflow-x:auto;
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
  .sr mark{background:var(--match-bg);color:var(--match-fg);border-radius:2px;padding:0 1px;font-weight:700}
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
  #selected::placeholder{font:12.5px -apple-system,BlinkMacSystemFont,sans-serif;color:var(--dim);opacity:1}
  #copiedBadge{flex:none;font-size:10.5px;font-weight:700;letter-spacing:.02em;
             color:var(--accent);opacity:0;transition:opacity var(--dur) var(--ease);
             pointer-events:none;white-space:nowrap}
  #copiedBadge.on{opacity:1}
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
  /* "58 of 60 rows" is a state you asked for, not a fault -- but it was
     painted in --danger, the same red as Delete and Discard, so a working
     filter announced itself in the app's error colour. Each range takes its
     own axis colour instead, which is the language the headers already use
     for "this is the row axis" / "this is the column axis". */
  #rowNav span.range-filtered{color:var(--row-meta);font-weight:700}
  #colNav span.range-filtered{color:var(--col-meta);font-weight:700}
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
  /* A frozen-pane divider is structure, not state -- it was drawn in the
     accent green that everywhere else means "selected", so the pinned block
     read as though it were highlighted. Excel draws this line in plain
     window chrome; --dim is this app's equivalent. */
  .pin-last{border-bottom:2px solid var(--dim)}
  #filterPopover,#ctxMenu,#viewsPopover,#confirmPopover{background:var(--panel-raised);border:1px solid var(--border);
             box-shadow:var(--shadow-md);border-radius:var(--radius-md)}
  #filterPopover{position:fixed;z-index:30;padding:7px;display:flex;gap:4px;align-items:center}
  /* :not([type=checkbox]) -- this 70px is for the numeric min/max fields,
     but it was also hitting the checklist's checkboxes, padding each one
     into a 70px box and stranding every value label half an inch away from
     the box that ticks it. */
  #filterPopover input:not([type=checkbox]){width:70px;box-sizing:border-box;background:var(--input-bg);color:var(--fg);
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
  .fp-title{font-size:11.5px;color:var(--dim);padding:1px 2px 3px}
  .fp-title b{color:var(--fg)}
  /* The one action the popover exists to perform reads as the default:
     everything else in it (All/None/Clear/the search box) is a way of
     setting up the state that Apply commits. */
  #filterPopover .fp-apply{background:var(--accent);color:var(--bg);border-color:var(--accent);font-weight:600}
  #filterPopover .fp-apply:hover{filter:brightness(1.08);background:var(--accent)}
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
  /* The base state isn't a saved view -- it can't be renamed or deleted and
     it's always present -- so it sits above a rule as a separate group
     rather than pretending to be the first item in the saved list. */
  .views-row-base{border-bottom:1px solid var(--border);border-radius:5px 5px 0 0;margin-bottom:2px;padding-bottom:6px}
  .views-base-hint{color:var(--dim);font-size:10.5px;flex:none}
  .views-x{background:none;border:none;color:var(--dim);cursor:pointer;font-size:10px;padding:0;line-height:1}
  .views-x:hover{color:var(--danger)}
  .views-save{display:flex;gap:4px;border-top:1px solid var(--border);padding-top:6px}
  .views-save-input,.views-rename-input{flex:1;box-sizing:border-box;background:var(--input-bg);color:var(--fg);
    border:1px solid var(--input-border);border-radius:5px;padding:3px 6px;font-size:12px}
  .views-rename-input.error{border-color:var(--danger)}
  #confirmPopover{position:fixed;z-index:40;left:50%;top:40%;transform:translate(-50%,-50%);padding:14px;
    display:flex;flex-direction:column;gap:10px}
  /* A dimming layer, so a question about losing work reads as a decision
     that blocks rather than as a note floating over a still-live grid. It
     has to be a sibling, not a ::before on the dialog: #confirmPopover is
     centred with a transform, and a transformed element becomes the
     containing block for its own position:fixed descendants -- an
     inset:0 child would have covered the dialog and nothing else. */
  #confirmBackdrop{position:fixed;inset:0;z-index:39;
             background:light-dark(rgba(0,0,0,.18),rgba(0,0,0,.45))}
  .confirm-msg{font-size:13px;max-width:320px}
  .confirm-buttons{display:flex;gap:6px;justify-content:flex-end}
  .confirm-discard{border-color:var(--danger)!important;color:var(--danger)}
  /* flex:1 so it claims the height #main would otherwise leave empty --
     without it the grid shrink-wraps its one child and the "centred"
     message sits in the top-left corner. */
  /* flex:1 for the height #main would otherwise leave empty, align-self
     stretch for the width -- the grid normally sets align-self:flex-start
     so its tracks size it, and with no tracks left it shrink-wrapped the
     message into the top-left corner. */
  #grid.grid-empty-state{display:flex;flex:1;min-height:0;align-self:stretch;
             align-items:center;justify-content:center;border:none}
  .grid-empty{display:flex;flex-direction:column;align-items:center;gap:10px;color:var(--dim)}
  .grid-empty-msg{font-size:13px}
  /* Kept selectable and monospace: when this is a load failure the detail
     is an exception the user may well want to paste somewhere. */
  .grid-empty-detail{font:11.5px/1.45 ui-monospace,monospace;color:var(--z-fg);
             max-width:min(560px,80vw);text-align:center;white-space:pre-wrap;
             overflow-wrap:anywhere;-webkit-user-select:text;user-select:text}
  .z{color:var(--z-fg)}
  /* Every non-zero used to be painted the same green, so a 0.001 and a
     4,800 were visually identical and the only thing the grid could tell
     you at a glance was where data existed -- not how much. Six steps of
     the same hue turn the matrix into a picture of its own distribution.
     Six, not a continuous ramp: the eye can't rank more than a handful of
     shades of one hue anyway, and buckets keep the theming in CSS instead
     of scattering computed colours into inline styles on 200 cells a
     render. The scale is log-spaced -- see heatBucket(). */
  #heatLegend{display:flex;align-items:center;gap:2px;margin-left:14px;
             font:10px/1 ui-monospace,monospace;color:var(--dim)}
  #heatLegend:empty{display:none}
  #heatLegend b{font-weight:400}
  #heatLegend b:first-child{margin-right:4px}
  #heatLegend b:last-child{margin-left:4px}
  #heatLegend i{width:11px;height:11px;border-radius:2px;border:1px solid var(--cell-border)}
  .nz{background:color-mix(in srgb, var(--heat) 45%, transparent)}
  .nz1{background:color-mix(in srgb, var(--heat) 16%, transparent)}
  .nz2{background:color-mix(in srgb, var(--heat) 31%, transparent)}
  .nz3{background:color-mix(in srgb, var(--heat) 47%, transparent)}
  .nz4{background:color-mix(in srgb, var(--heat) 64%, transparent)}
  .nz5{background:color-mix(in srgb, var(--heat) 82%, transparent)}
  .nz6{background:var(--heat)}
  .mv{color:var(--fg)}
  .mv-empty{color:var(--z-fg);font-style:italic}
  /* :not(.nz) -- a shaded cell's background *is* its value now, so painting
     the selection tint over it would erase the number's magnitude at
     exactly the moment you selected the row to read it. Zeros carry no
     magnitude, so they take the tint and the row still reads as a band;
     the deepened row/column header carries the rest. Metadata cells are
     never .nz, so those grids are unaffected. */
  .cell:not(.rh):not(.colhdr):not(.stat-cell):not(.nz).hl-row,
  .cell:not(.rh):not(.colhdr):not(.stat-cell):not(.nz).hl-col{background:var(--hl) !important}
  /* Must out-specify the rule above, not just follow it -- both are
     !important, so the longer :not() chain there would otherwise win. */
  .cell:not(.rh):not(.colhdr):not(.stat-cell).cell-expanded-row.hl-row,
  .cell:not(.rh):not(.colhdr):not(.stat-cell).cell-expanded-row.hl-col{background:var(--hl-soft) !important}
  /* Which row and column you are in is exactly what a header highlight is
     for in a 10,000-row grid -- but every previous attempt at it competed
     with the cell's own marker instead of supporting it. A 2px accent box
     on each header painted three equally-weighted outlines for one click,
     and swapping the boxes for bold text just moved the distraction into
     the type. Both were the *same* signal repeated three times.
     Headers now step their own resting tint one shade deeper -- the Excel
     idiom. It reads instantly, changes one property, and can't compete for
     focus with the accent outline because it isn't the same kind of mark.
     .hl-cell's outline stays the single "this exact cell" indicator. */
  /* Each axis takes the deeper shade of whatever tint it already wears in
     this mode -- the orange/blue axis tints where the header *is* the
     observation or sample axis, the neutral header grey where it is a list
     of metadata field names (col mode's rows, row mode's columns). Picking
     the deeper shade of the wrong palette would assert an axis identity the
     header doesn't have. */
  .rh.hl-row,.colhdr.hl-col{background:var(--hdr-bg-sel) !important}
  body.mode-row .rh.hl-row,body.mode-data .rh.hl-row{background:var(--row-meta-bg-sel) !important}
  body.mode-col .colhdr.hl-col,body.mode-data .colhdr.hl-col{background:var(--col-meta-bg-sel) !important}
  /* A stats cell is a summary panel that happens to sit in the header slot,
     not an axis label -- it keeps its panel background and lets the label
     bar alone carry the selection. .rh-label paints its own opaque
     background over the parent (negative margins stretch it edge to edge),
     so the tint has to be repeated on it either way. */
  .rh-stats.hl-row{background:var(--panel-bg) !important}
  .rh-stats.hl-row .rh-label{background:var(--hdr-bg-sel)}
  body.mode-row .rh-stats.hl-row .rh-label,body.mode-data .rh-stats.hl-row .rh-label{background:var(--row-meta-bg-sel)}
  /* When the column stats strip is showing, .colhdr and the .stat-cell
     directly below it read as one merged header block, so they take the
     tint together and the seam between them is hidden. */
  #grid.col-stats .stat-cell.hl-col{background:var(--col-meta-bg-sel);border-top-color:transparent}
  .hl-cell{outline:2px solid var(--sel-outline);outline-offset:-2px;position:relative;z-index:1}
  /* row axis (observation ids, leftmost column) orange; col axis (sample ids,
     top row) blue — in data mode both are on screen at once */
  /* Border stays the neutral cell border rather than the axis colour: a
     coloured 1px box on all four sides of every header cell drew the axis
     as a stack of outlined boxes. The tinted fill plus the 3px inset bar
     below already say "this is the row axis" without the chain of frames. */
  body.mode-row .rh,body.mode-data .rh{background:var(--row-meta-bg);color:var(--row-meta);font-weight:700}
  /* The :not(.hl-row) guard here was only ever protecting against the
     selection outline, which was also a box-shadow and would have replaced
     this bar wholesale. Selection is a background change now, so the axis
     bar can stay put -- it used to blink out of the one row you clicked. */
  body.mode-row .rh,body.mode-data .rh{box-shadow:inset 3px 0 0 var(--row-meta)}
  body.mode-col .hdr.colhdr,body.mode-data .hdr.colhdr{background:var(--col-meta-bg);color:var(--col-meta);font-weight:700}
  body.mode-col .hdr.colhdr,body.mode-data .hdr.colhdr{box-shadow:inset 0 -3px 0 var(--col-meta)}
  #replaceModal{width:420px;border-radius:var(--radius-lg)}
  #replaceModal header{justify-content:space-between}
  #replaceModal header h3{margin-right:0}
  #replaceModal .rp-form{padding:12px 14px;display:flex;flex-wrap:wrap;gap:6px}
  #replaceModal .rp-form select, #replaceModal .rp-form input{background:var(--input-bg);color:var(--fg);
             border:1px solid var(--input-border);border-radius:4px;padding:4px 6px;font-size:12.5px}
  #replaceModal .rp-form select{flex:1 1 100%}
  .rp-label{flex:1 1 100%;font-size:11px;color:var(--dim);margin-bottom:-3px}
  /* Bottom-right and accent-filled: it is the only action in the dialog
     that changes anything, and it was sitting bottom-left looking exactly
     like the toolbar buttons that don't. */
  #replaceModal .rp-form #rpApply{margin-left:auto;background:var(--accent);color:var(--bg);
             border-color:var(--accent);font-weight:600}
  #replaceModal .rp-form #rpApply:hover{filter:brightness(1.08);background:var(--accent)}
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
  /* min-width:0 so a taxonomy string in the title truncates instead of
     shoving Copy and the close button off the edge of the dialog. */
  .wm-modal header h3{margin:0;font-size:14px;margin-right:auto;min-width:0;
             overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  /* This one is a row/column identity rather than a dialog name, so it is
     set like the data it points at. */
  /* Wraps rather than truncating: it reads "<row> | <column>", and
     ellipsising the tail cut off the column id -- the half that says which
     of 217 samples this is. The dialog has the width to just show both. */
  #cellTitle{font:600 12px/1.4 ui-monospace,monospace;white-space:normal;overflow-wrap:anywhere;overflow:visible}
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
  /* This used to redraw the accent selection border along the label bar's
     edges, since the bar's opaque background paints over the parent cell's
     own. There is no accent border on a selected header any more -- it was
     the box that drew the complaint -- and the tint that replaced it is set
     further up the sheet; this rule only survived to undo it. */
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

  /* Last in the sheet on purpose: these override plain id selectors of the
     same specificity, and a media query adds none of its own -- placed
     earlier they simply lose to whatever comes after. */
  @media (max-width:820px){
    /* Below this the top row can't hold the path, the dimensions pill, the
       mode tag and the mode switcher at once, and flex was resolving it by
       clipping the pills mid-glyph -- "60 x 24" showing as a lone "6". The
       path and the mode controls are what you steer by; the pills are a
       readout, and the mode tag only ever restates the highlighted button
       two inches to its right. Both come back when the window widens. */
    #dims,#modeTag{display:none !important}
    /* The search field held a fixed 220px no matter how little was left,
       so at the app's own minimum window size it squeezed the document
       title down to a dozen characters to keep room it wasn't using. */
    #searchBox{width:130px}
    #searchResults{width:min(420px,90vw)}
  }
"""
