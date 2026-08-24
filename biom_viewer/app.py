#!/usr/bin/env python3
"""Lazy-loading BIOM viewer: native window (pywebview) + biom-format, sparse-window slicing, canvas grid UI."""
import math
import os
import socket
import sys
import threading
import webbrowser
from collections import Counter

import biom
import numpy as np
import webview
from webview.menu import Menu, MenuAction, MenuSeparator


def _json_safe(v):
    # Real metadata (e.g. pandas-sourced sample sheets) is full of NaN/inf for
    # missing values. json.dumps emits those as bare NaN/Infinity tokens,
    # which is invalid JSON and makes JSON.parse throw on the JS side.
    if isinstance(v, float) and not math.isfinite(v):
        return None
    if isinstance(v, dict):
        return {k: _json_safe(x) for k, x in v.items()}
    # biom-format reads list-valued metadata (e.g. a taxonomy lineage) back
    # as a numpy object array of bytes, not a plain list of str -- neither
    # of which json.dumps can serialize on its own.
    if isinstance(v, np.ndarray):
        return [_json_safe(x) for x in v.tolist()]
    if isinstance(v, (list, tuple)):
        return [_json_safe(x) for x in v]
    if isinstance(v, bytes):
        return v.decode("utf-8", "replace")
    if isinstance(v, np.generic):
        return _json_safe(v.item())
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


def _axis_summary(vec, total):
    values = [float(v) for v in vec.data if v != 0]
    summary = _numeric_summary(values, total)
    summary["nonzero"] = len(values)
    summary["sparsity"] = round((total - len(values)) / total * 100, 1) if total else 0.0
    return summary


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


def field_summary(table, axis, field, idxs=None):
    entries = table.metadata(axis=axis)
    if idxs is not None:
        entries = [entries[i] for i in idxs]
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
        # Full ranked list, for the "+N other" viewer -- already computed
        # above (ranked), so this is free beyond JSON size. Bounded by the
        # axis length, same as `top`/`other_count` already are.
        "all": [{"value": v, "count": c} for v, c in ranked],
    }


def build_export_table(table, spec):
    # spec: {'observation': {...}, 'sample': {...}}, each with:
    #   ids: list[str] | None (filtered/sorted id order; None = unchanged)
    #   replacements: [{field, find, replace}]
    #   renames: {orig_field: new_field}
    #   deletedFields: [field, ...]
    # Mirrors the frontend's buildAxisExportCode -- see that function's
    # comment for why replacements/renames/deletes go through add_metadata
    # (merge-by-key) plus an explicit del_metadata for the keys that should
    # actually disappear (add_metadata alone never removes a key).
    table = table.copy()
    for axis in ("observation", "sample"):
        s = spec.get(axis) or {}
        ids = s.get("ids")
        if ids is not None:
            table = table.filter(ids, axis=axis)
            table = table.sort_order(ids, axis=axis)

        replacements = s.get("replacements") or []
        if replacements:
            md = {}
            for id_, entry in zip(table.ids(axis=axis), table.metadata(axis=axis) or ()):
                if not entry:
                    continue
                changed = {}
                for r in replacements:
                    field = r["field"]
                    if field in entry and entry[field] is not None:
                        changed[field] = str(entry[field]).replace(r["find"], r["replace"])
                if changed:
                    md[id_] = changed
            if md:
                table.add_metadata(md, axis=axis)

        renames = s.get("renames") or {}
        if renames:
            md = {}
            for id_, entry in zip(table.ids(axis=axis), table.metadata(axis=axis) or ()):
                if not entry:
                    continue
                for orig, new in renames.items():
                    if orig in entry:
                        md.setdefault(id_, {})[new] = entry[orig]
            if md:
                table.add_metadata(md, axis=axis)
            table.del_metadata(keys=list(renames.keys()), axis=axis)

        deleted = s.get("deletedFields") or []
        if deleted:
            table.del_metadata(keys=deleted, axis=axis)

        # to_hdf5() requires every id on an axis to have the exact same
        # metadata *keys* (not just non-null values) -- real-world biom
        # files routinely have per-id metadata dicts that disagree (an
        # optional field present on some ids, absent on others), which
        # to_hdf5() rejects outright rather than writing a partial file.
        # It also requires each key's column to be internally homogeneous:
        # every value a str, or every value a list (of str) -- bare None is
        # the only mix it tolerates. Real files break this in both
        # directions (a list-valued lineage field sitting next to bare None
        # for ids missing it; a list of ints instead of strs; an int field
        # with some ids None). Since the write is not transactional, hitting
        # any of this mid-write used to leave a truncated, unopenable .biom
        # at the destination.
        #
        # Fix by normalizing per *column* rather than per entry, and only
        # where the column actually needs it -- a clean uniform-numeric
        # column (no None) already round-trips fine as numbers via to_hdf5's
        # own dtype inference, and stringifying it unnecessarily would lose
        # that. Only list-valued columns (always, since elements might not
        # be str) and columns that mix None with a non-str type (which
        # to_hdf5 can't reconcile into one dtype) get coerced.
        entries = table.metadata(axis=axis)
        if entries:
            ids = table.ids(axis=axis)
            all_keys = set()
            for e in entries:
                if e:
                    all_keys.update(e.keys())
            columns = {}
            for k in all_keys:
                values = [(e or {}).get(k) for e in entries]
                non_none_types = {type(v) for v in values if v is not None}
                has_none = any(v is None for v in values)
                if non_none_types <= {list, tuple}:
                    columns[k] = [
                        [] if v is None else ["" if x is None else str(x) for x in v]
                        for v in values
                    ]
                elif non_none_types <= {str} or (
                    len(non_none_types) <= 1 and not has_none
                    and next(iter(non_none_types), str) in (str, int, float, bool)
                ):
                    columns[k] = values
                else:
                    columns[k] = [None if v is None else str(v) for v in values]
            filled = {id_: {k: columns[k][i] for k in all_keys} for i, id_ in enumerate(ids)}
            table.add_metadata(filled, axis=axis)

    return table


def write_biom_file(table, path):
    # Write to a sibling temp file and rename into place only on success --
    # to_hdf5() is not transactional, so a mid-write failure (see
    # build_export_table's docstring) must never leave a truncated file
    # sitting at the destination the user picked.
    tmp_path = path + ".tmp"
    try:
        with biom.util.biom_open(tmp_path, "w") as f:
            table.to_hdf5(f, "biom-viewer export")
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


class Api:
    """Exposed to the frontend as window.pywebview.api.* — no HTTP server involved.

    One instance per open file/window (see open_window()) -- table and
    filename are instance state, not module globals, so multiple windows in
    the same process each stay bound to their own file.
    """

    def __init__(self, table, filename):
        self._table = table
        self._filename = filename
        self.window = None  # set by open_window() once create_window() returns
        self._csc_matrix = None

    # ponytail: id list sent once (text-only, cheap even at ~1e5 rows); paginate if a table
    # ever has >~500k ids and this becomes a multi-MB response.
    def meta(self):
        table = self._table
        obs_ids = table.ids("observation").tolist()
        sample_ids = table.ids("sample").tolist()
        obs_meta = table.metadata(axis="observation")
        sample_meta = table.metadata(axis="sample")
        return {
            "filename": self._filename,
            "rows": table.shape[0],
            "cols": table.shape[1],
            "row_ids": obs_ids,
            "col_ids": sample_ids,
            "table_id": table.table_id,
            "table_type": table.type,
            "generated_by": table.generated_by,
            "create_date": str(table.create_date) if table.create_date else None,
            "row_metadata": [_json_safe(dict(m)) for m in obs_meta] if obs_meta else None,
            "col_metadata": [_json_safe(dict(m)) for m in sample_meta] if sample_meta else None,
        }

    def data_window(self, r0, r1, c0, c1):
        table = self._table
        r1 = min(r1, table.shape[0])
        c1 = min(c1, table.shape[1])
        # Densify only the requested window, never the full matrix.
        sub = table.matrix_data[r0:r1, :].tocsc()[:, c0:c1]
        return sub.toarray().tolist()

    def data_window_idx(self, row_idxs, col_idxs):
        # Gather arbitrary (unsorted, non-contiguous) row/col index lists —
        # used once either axis has an active sort or filter, since the
        # visible page no longer maps to a contiguous matrix range. Densify
        # only the requested submatrix, same as data_window.
        sub = self._table.matrix_data.tocsr()[row_idxs, :].tocsc()[:, col_idxs]
        return sub.toarray().tolist()

    def row_summary(self, r):
        return _axis_summary(self._table.matrix_data.tocsr()[r, :], self._table.shape[1])

    def _csc(self):
        if self._csc_matrix is None:
            self._csc_matrix = self._table.matrix_data.tocsc()
        return self._csc_matrix

    def col_summary(self, c):
        return _axis_summary(self._csc()[:, c], self._table.shape[0])

    def field_summary(self, axis, field, idxs=None):
        return field_summary(self._table, axis, field, idxs)

    def open_url(self, url):
        # The right-click "Search Google" menu builds this URL itself (see
        # openContextMenu in the frontend) rather than accepting an arbitrary
        # one from anywhere else, so there's no untrusted-input surface here.
        # Routed through Python's webbrowser rather than a JS window.open()/
        # <a target=_blank> click because pywebview's cocoa backend only
        # intercepts real link-navigation events for its "open externally"
        # behavior, not window.open() -- this works regardless of backend.
        webbrowser.open(url)

    def export_table(self, spec):
        default_name = os.path.splitext(os.path.basename(self._filename))[0] + "_export.biom"
        result = self.window.create_file_dialog(
            webview.FileDialog.SAVE,
            save_filename=default_name,
            file_types=("BIOM file (*.biom)", "All files (*.*)"),
        )
        if not result:
            return {"ok": False}
        path = result[0] if isinstance(result, (list, tuple)) else result
        try:
            table = build_export_table(self._table, spec)
            write_biom_file(table, path)
        except Exception as exc:  # noqa: BLE001 -- surface to the UI instead of silently dropping
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "path": path}


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
    --hl:light-dark(#cdf0dc,#274b3a); --sel-outline:var(--accent);
    --fs:11px;
    --row-meta:light-dark(#c96a1a,#e08a3c); --row-meta-bg:light-dark(#fde3c8,#4a3420);
    --row-meta-fg:light-dark(#5c3410,#2a1c0f);
    --col-meta:light-dark(#2266cc,#5b9bd5); --col-meta-bg:light-dark(#d6e6fa,#20344a);
    --col-meta-fg:light-dark(#0f2c54,#0f1c2a);
    --danger:light-dark(#c0392b,#ff6b6b);
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
  #searchWrap{position:relative;display:flex;align-items:center;gap:4px}
  #searchBox{width:220px;box-sizing:border-box;background:var(--input-bg);color:var(--fg);
             border:1px solid var(--input-border);border-radius:4px;padding:5px 8px;font-size:12.5px;outline:none}
  #searchBox:focus{border-color:var(--sel-outline)}
  #searchPin{padding:4px 7px;font-size:12px;opacity:.45}
  #searchPin.on{opacity:1;border-color:var(--accent);background:var(--hl)}
  #searchResults{position:absolute;top:calc(100% + 4px);right:0;width:420px;max-height:60vh;overflow-y:auto;
             background:var(--panel-bg);border:1px solid var(--border);border-radius:6px;
             box-shadow:0 12px 30px rgba(0,0,0,.35);display:none;z-index:20}
  #searchResults.open{display:block}
  #searchResults.pinned{outline:2px solid var(--accent);outline-offset:2px}
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
  #selectedWrap{display:flex;align-items:center;gap:4px;margin:6px 0}
  #selected{flex:1;min-width:0;box-sizing:border-box;padding:5px 8px;background:transparent;color:var(--dim);
             border:1px solid transparent;border-radius:4px;font-family:ui-monospace,monospace;outline:none;
             caret-color:transparent;transition:color .15s}
  #selected.flash{color:var(--fg)}
  #expandBtn{flex:none}
  button.nav,button.tool{background:var(--panel-bg);color:var(--fg);border:1px solid var(--input-border);border-radius:4px;padding:4px 10px;cursor:pointer;
             font-size:14px;line-height:1}
  button.nav:disabled{opacity:.35;cursor:default}
  #body{display:flex;flex:1;min-height:0;padding:0 10px}
  #rowNav{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:6px;padding-right:10px}
  #rowNav span{writing-mode:vertical-rl;color:var(--dim);white-space:nowrap}
  #main{flex:1;display:flex;flex-direction:column;overflow:hidden}
  #colNav{display:flex;align-items:center;justify-content:center;gap:10px;padding-bottom:6px}
  #colNav span{color:var(--dim)}
  #rowNav span.range-filtered,#colNav span.range-filtered{color:var(--danger);font-weight:700}
  #grid{display:grid;overflow:hidden;flex-shrink:0;align-self:flex-start}
  .cell{border:1px solid var(--cell-border);padding:3px 6px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:var(--fs)}
  .hdr{background:var(--hdr-bg);color:var(--hdr-fg)}
  .rh{background:var(--hdr-bg);color:var(--hdr-fg);cursor:pointer}
  .rh:hover{background:var(--input-border)}
  .hdr.colhdr{cursor:pointer}
  .hdr.colhdr:hover{background:var(--input-border)}
  .hdr.colhdr:has(.axis-ctl),.rh:has(.axis-ctl){display:flex;align-items:center}
  .hdr-label{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1;min-width:0}
  .axis-ctl{display:flex;gap:2px;margin-left:4px;flex:none}
  .axis-ctl button{background:none;border:none;color:var(--dim);cursor:pointer;font-size:calc(var(--fs)*0.95);
             padding:0 2px;line-height:1}
  .axis-ctl button:hover{color:var(--fg)}
  .axis-ctl button.on{color:var(--accent);font-weight:700}
  #filterPopover{position:fixed;z-index:30;background:var(--panel-bg);border:1px solid var(--border);
             border-radius:6px;box-shadow:0 8px 24px rgba(0,0,0,.3);padding:6px;display:flex;gap:4px;align-items:center}
  #filterPopover input{width:70px;box-sizing:border-box;background:var(--input-bg);color:var(--fg);
             border:1px solid var(--input-border);border-radius:4px;padding:3px 6px;font-size:12px}
  #filterPopover button{background:var(--panel-bg);color:var(--fg);border:1px solid var(--input-border);
             border-radius:4px;padding:3px 8px;font-size:12px;cursor:pointer}
  #filterPopover.fp-checklist{flex-direction:column;align-items:stretch;width:220px}
  #filterPopover.fp-checklist input.fp-search{width:100%}
  .fp-actions{display:flex;gap:4px}
  .fp-actions button{flex:1}
  #ctxMenu{position:fixed;z-index:40;background:var(--panel-bg);border:1px solid var(--border);
             border-radius:6px;box-shadow:0 8px 24px rgba(0,0,0,.3);padding:4px;min-width:160px}
  .ctx-item{display:block;width:100%;text-align:left;background:none;border:none;color:var(--fg);
             padding:6px 10px;border-radius:4px;cursor:pointer;font-size:12.5px;white-space:nowrap;
             overflow:hidden;text-overflow:ellipsis}
  .ctx-item:hover{background:var(--hl)}
  .fp-list{max-height:220px;overflow-y:auto;border:1px solid var(--input-border);border-radius:4px}
  .fp-row{display:flex;align-items:center;gap:6px;padding:3px 6px;font-size:12px;cursor:pointer}
  .fp-row:hover{background:var(--hl)}
  .fp-row .fp-val{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .fp-row .fp-count{color:var(--dim);font-family:ui-monospace,monospace;font-size:10.5px}
  .fp-buttons{display:flex;gap:4px}
  .fp-buttons button{flex:1}
  #axisChips{display:none;gap:6px;padding:4px 10px;flex-wrap:wrap}
  .chip{display:inline-flex;align-items:center;gap:5px;background:var(--hl);color:var(--fg);
             border-radius:10px;padding:3px 8px;font-size:11.5px}
  .chip-x{background:none;border:none;color:var(--dim);cursor:pointer;font-size:10px;padding:0;line-height:1}
  .chip-x:hover{color:var(--fg)}
  .z{color:var(--z-fg)}
  .nz{background:var(--nz-bg)}
  .mv{color:var(--fg)}
  .mv-empty{color:var(--z-fg);font-style:italic}
  .cell:not(.rh):not(.colhdr):not(.stat-cell).hl-row,.cell:not(.rh):not(.colhdr):not(.stat-cell).hl-col{background:var(--hl) !important}
  .rh.hl-row,.colhdr.hl-col{box-shadow:inset 0 0 0 2px var(--sel-outline);font-weight:700}
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
  body.mode-row .rh,body.mode-data .rh{background:var(--row-meta-bg);color:var(--row-meta);border-color:var(--row-meta)}
  body.mode-col .hdr.colhdr,body.mode-data .hdr.colhdr{background:var(--col-meta-bg);color:var(--col-meta);border-color:var(--col-meta)}
  #replaceOverlay{position:fixed;inset:0;background:rgba(0,0,0,.45);display:none;
               align-items:center;justify-content:center;z-index:10}
  #replaceOverlay.open{display:flex}
  #replaceModal{background:var(--panel-bg);border:1px solid var(--border);border-radius:8px;
             width:420px;max-width:92vw;box-shadow:0 12px 40px rgba(0,0,0,.35)}
  #replaceModal header{display:flex;align-items:center;justify-content:space-between;
                     padding:12px 14px;border-bottom:1px solid var(--border)}
  #replaceModal header h3{margin:0;font-size:14px}
  #replaceModal .x{cursor:pointer;color:var(--dim);font-size:16px;line-height:1;background:none;border:none}
  #replaceModal .x:hover{color:var(--fg)}
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
  .wm-overlay{position:fixed;inset:0;background:rgba(0,0,0,.45);display:none;
               align-items:center;justify-content:center;z-index:10}
  .wm-overlay.open{display:flex}
  .wm-modal{background:var(--panel-bg);border:1px solid var(--border);border-radius:8px;
             width:640px;max-width:92vw;box-shadow:0 12px 40px rgba(0,0,0,.35);
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
</style></head>
<body class="mode-data">
<div id="info">
  <span style="display:flex;align-items:center;overflow:hidden">
    <span id="filename">loading…</span>
    <span id="modeTag"></span>
  </span>
  <span id="toolbar">
    <span id="modeGroup">
      <button class="active" data-m="data">Data</button>
      <button data-m="row">Row metadata</button>
      <button data-m="col">Col metadata</button>
    </span>
    <span id="searchWrap">
      <input id="searchBox" type="text" placeholder="Search…" autocomplete="off">
      <button class="tool" id="searchPin" title="Keep search results open">📌</button>
      <div id="searchResults"></div>
    </span>
  </span>
</div>
<div id="axisChips"></div>
<div id="selectedWrap">
  <input id="selected" readonly value="Click a row, column, or cell to see its full text here (auto-copied to clipboard). Double-click a header to toggle summary stats.">
  <button class="tool" id="expandBtn" title="View full content in a window (⌘⏎)">⤢</button>
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
<div id="replaceOverlay">
  <div id="replaceModal">
    <header>
      <h3>Find &amp; Replace</h3>
      <button class="x" id="replaceClose">✕</button>
    </header>
    <div class="rp-form">
      <select id="rpAxis">
        <option value="observation">Observation (row) metadata</option>
        <option value="sample">Sample (col) metadata</option>
      </select>
      <select id="rpField"></select>
      <input id="rpFind" type="text" placeholder="Find…">
      <input id="rpReplace" type="text" placeholder="Replace with…">
      <button class="tool" id="rpApply">Apply</button>
    </div>
    <div id="rpList"></div>
  </div>
</div>
<div id="codeOverlay" class="wm-overlay">
  <div class="wm-modal">
    <header>
      <h3>Export as Python</h3>
      <button class="tool" id="codeCopy">Copy</button>
      <button class="x" id="codeClose">✕</button>
    </header>
    <pre id="codeBlock" class="wm-body"></pre>
  </div>
</div>
<div id="cellOverlay" class="wm-overlay">
  <div class="wm-modal">
    <header>
      <h3 id="cellTitle">Cell content</h3>
      <button class="tool" id="cellCopy">Copy</button>
      <button class="x" id="cellClose">✕</button>
    </header>
    <pre id="cellBlock" class="wm-body"></pre>
  </div>
</div>
<div id="valuesOverlay" class="wm-overlay">
  <div class="wm-modal">
    <header>
      <h3 id="valuesTitle">All values</h3>
      <button class="tool" id="valuesCopy">Copy</button>
      <button class="x" id="valuesClose">✕</button>
    </header>
    <div id="valuesBody" class="wm-body wm-list"></div>
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
// In 'col' mode, double-clicking one row header expands just that field's
// row to a stat summary (instead of summaryVisible's "expand every row").
let expandedFieldRow=null;
function anyFieldRowExpanded(){ return stripOnRows() || (mode==='col' && expandedFieldRow!=null); }
// Expanding/collapsing a row changes rowsPerPage() (the expanded row eats
// extra height budget), which shifts which fields "page N" covers -- so the
// clicked row can silently scroll off the page it was just clicked on.
// Recompute fit and re-center on r first, same fix toggleSummary already
// needed for the same reason.
function toggleFieldRow(r){
  expandedFieldRow = (expandedFieldRow===r) ? null : r;
  computeFit();
  const maxPage = Math.max(0, Math.ceil(rowsTotal()/rowsPerPage()) - 1);
  rowPage = Math.min(Math.floor(r/rowsPerPage()), maxPage);
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

function computeFit(){
  // Derived from the font, never measured off a rendered cell: cell height is
  // set by the grid track we compute here, so measuring it feeds back and can
  // collapse the page to 2 giant rows after a partial page.
  const shortRowH = Math.round(fontSize*1.3) + 8; // 3px padding + 1px border, top and bottom
  const mainRect = document.getElementById('main').getBoundingClientRect();
  const colNavH = document.getElementById('colNav').getBoundingClientRect().height;
  availH = mainRect.height - colNavH - GAP - (stripOnCols() ? statRowH() : 0);
  RHW = computeRHW();
  availW = mainRect.width - RHW - GAP;

  if(stripOnRows()){
    // The column-header row stays short (it's just sample/observation ids,
    // same as ever) -- only the field rows below it need the tall track,
    // so only they should compete for the height budget.
    autoRows = Math.max(1, Math.floor((availH - shortRowH) / statRowH()));
  } else if(mode==='col' && expandedFieldRow!=null){
    // One field row is expanded to a stat block; the rest stay short. This
    // reserves the budget even if the expanded row isn't on the current
    // page -- ponytail: slightly conservative, avoids a fit/page chicken-egg.
    autoRows = Math.max(1, Math.floor((availH - shortRowH - statRowH()) / shortRowH) + 1);
  } else {
    const totalRowsTarget = Math.max(2, Math.floor(availH/shortRowH)); // includes header row
    autoRows = totalRowsTarget - 1;
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
function recordHistory(){
  historyPast.push(snapshotState());
  if(historyPast.length>50) historyPast.shift();
  historyFuture = [];
}
function restoreState(snap){
  axisState = snap.axisState;
  rowFields = snap.rowFields.slice();
  colFields = snap.colFields.slice();
  recomputeVisible('observation');
  recomputeVisible('sample');
  rowPage=0; colPage=0;
  render();
  renderAxisChips();
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
  axisState[axis].sortField = null;
  axisState[axis].sortDir = 0;
  axisState[axis].filters = [];
  recomputeVisible(axis);
  renderAxisChips();
  return rawIdx;
}

const modeBtns = [...document.querySelectorAll('#modeGroup button')];

function setMode(m){
  mode = m;
  if(m!=='col') expandedFieldRow = null;
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

// Row/column axis for the grid currently on screen — depends on mode.
// 'row' mode only swaps the COLUMN axis (fields replace samples); the row
// axis (observation ids) stays exactly as in 'data' mode.
// 'col' mode only swaps the ROW axis (fields replace observations); the
// column axis (sample ids) stays exactly as in 'data' mode.
function rowsTotal(){ return mode==='col' ? colFields.length : (visObs ? visObs.length : meta.rows); }
function colsTotal(){ return mode==='row' ? rowFields.length : (visSample ? visSample.length : meta.cols); }
function fieldDisplay(axis, field){ return axisState[axis].renames[field] || field; }
function rowLabel(i){ return mode==='col' ? fieldDisplay('sample', colFields[i]) : meta.row_ids[obsAt(i)]; }
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
  const entry = meta.col_metadata && meta.col_metadata[sampleAt(j)];
  const field = colFields[i];
  return entry ? applyReplacements('sample', field, entry[field]) : null;
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
  const active = state.filters.length>0 || state.sortDir!==0;
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
    const pos = resolveAxisPosition('observation', entry.i);
    rowPage = Math.floor(pos / rowsPerPage());
    selR = pos; selC = null;
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
    const pos = resolveAxisPosition('observation', entry.i);
    rowPage = Math.floor(pos / rowsPerPage());
    colPage = Math.floor(entry.fi / colsPerPage());
    selR = pos; selC = entry.fi;
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

  // Stretch to fill availH x availW, but never past the auto-fit page size —
  // a partial last page keeps normal-height rows instead of ballooning.
  const renderedRows = r1-r0, renderedCols = c1-c0;
  const fieldExpandedIdx = (mode==='col' && !stripOnRows() && expandedFieldRow!=null
    && expandedFieldRow>=r0 && expandedFieldRow<r1) ? expandedFieldRow : null;
  let headerRowHPx, rowHeights = null;
  if(stripOnRows()){
    // Column headers stay short; only the field rows below need the tall
    // track, so the header doesn't compete with them for height.
    headerRowHPx = Math.round(fontSize*1.3) + 8;
    rowHPx = Math.max(statRowH(), (availH - headerRowHPx) / Math.max(renderedRows, rowsPerPage()));
  } else if(fieldExpandedIdx!=null){
    // Only the expanded row gets the tall stat track; everyone else stays
    // at natural short height instead of stretching to fill availH.
    headerRowHPx = Math.round(fontSize*1.3) + 8;
    rowHeights = [];
    for(let r=r0;r<r1;r++) rowHeights.push(r===fieldExpandedIdx ? statRowH() : headerRowHPx);
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
    ? await Promise.all(Array.from({length: renderedRows}, (_, k) => window.pywebview.api.field_summary('sample', colFields[r0+k], visSample)))
    : null;
  const fieldExpandedStat = fieldExpandedIdx!=null
    ? await window.pywebview.api.field_summary('sample', colFields[fieldExpandedIdx], visSample)
    : null;

  const grid = document.getElementById('grid');
  const statRowTrack = stripOnCols() ? `${statRowH()}px ` : '';
  const rowsTrack = rowHeights ? rowHeights.map(h=>`${h}px`).join(' ') : `repeat(${renderedRows}, ${rowHPx}px)`;
  grid.classList.toggle('col-stats', stripOnCols());
  grid.style.gridTemplateColumns = `${RHW}px repeat(${renderedCols}, ${colWPx}px)`;
  grid.style.gridTemplateRows = `${headerRowHPx}px ${statRowTrack}${rowsTrack}`;
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
    if(mode==='row'){
      h.innerHTML = `<span class="hdr-label">${escapeHtml(label)}</span>${axisControlsHtml('observation', rowFields[c])}`;
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
  if(stripOnCols()){
    grid.appendChild(fillerCell());
    colStats.forEach((s, i) => {
      const cell = statCell(s, colLabel(c0 + i));
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
      wireStatOther(rh, rowStats[r-r0], label);
    } else if(r===fieldExpandedIdx){
      rh.classList.add('rh-stats');
      rh.innerHTML = `<div class="stat-line rh-label">${escapeHtml(label)}</div>` + statCellHtml(fieldExpandedStat);
      wireStatOther(rh, fieldExpandedStat, label);
    } else if(mode==='col'){
      rh.innerHTML = `<span class="hdr-label">${escapeHtml(label)}</span>${axisControlsHtml('sample', colFields[r])}`;
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
          selR=r; selC=c;
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
          selR=r; selC=c;
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
  navigator.clipboard.writeText(document.getElementById('cellBlock').textContent);
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
  navigator.clipboard.writeText(lastValuesText);
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

function axisControlsHtml(axis, field){
  const st = axisState[axis];
  const arrow = st.sortField===field ? (st.sortDir===1 ? '▲' : st.sortDir===-1 ? '▼' : '⇅') : '⇅';
  const sortOn = st.sortField===field && st.sortDir!==0;
  const filterOn = st.filters.some(f=>f.field===field);
  const display = fieldDisplay(axis, field);
  return `<span class="axis-ctl">` +
    `<button class="axis-sort${sortOn?' on':''}" data-axis="${axis}" data-field="${escapeHtml(field)}" title="Sort by ${escapeHtml(display)}">${arrow}</button>` +
    `<button class="axis-filter${filterOn?' on':''}" data-axis="${axis}" data-field="${escapeHtml(field)}" title="Filter by ${escapeHtml(display)}">⏷</button>` +
    `<button class="axis-edit" data-axis="${axis}" data-field="${escapeHtml(field)}" title="Rename or delete ${escapeHtml(display)}">✎</button>` +
  `</span>`;
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
  ['observation','sample'].forEach(axis=>{
    const st = axisState[axis];
    if(st.sortDir!==0){
      chips.push(`<span class="chip">${axis} sorted: ${escapeHtml(fieldDisplay(axis, st.sortField))} ${st.sortDir===1?'▲':'▼'}` +
        `<button class="chip-x" data-kind="sort" data-axis="${axis}">✕</button></span>`);
    }
    st.filters.forEach(f=>{
      chips.push(`<span class="chip">${axis}: ${escapeHtml(filterChipLabel(axis, f))}` +
        `<button class="chip-x" data-kind="filter" data-axis="${axis}" data-field="${escapeHtml(f.field)}">✕</button></span>`);
    });
    st.replacements.forEach(r=>{
      chips.push(`<span class="chip">${axis}: ${escapeHtml(fieldDisplay(axis, r.field))} "${escapeHtml(r.find)}"→"${escapeHtml(r.replace)}"` +
        `<button class="chip-x" data-kind="replace" data-axis="${axis}" data-field="${escapeHtml(r.field)}">✕</button></span>`);
    });
    Object.entries(st.renames).forEach(([orig, newName])=>{
      chips.push(`<span class="chip">${axis}: ${escapeHtml(orig)} → ${escapeHtml(newName)}` +
        `<button class="chip-x" data-kind="unrename" data-axis="${axis}" data-field="${escapeHtml(orig)}">✕</button></span>`);
    });
    st.deletedFields.forEach(f=>{
      chips.push(`<span class="chip">${axis}: deleted ${escapeHtml(f)}` +
        `<button class="chip-x" data-kind="undelete" data-axis="${axis}" data-field="${escapeHtml(f)}">✕</button></span>`);
    });
  });
  el.innerHTML = chips.join('');
  el.style.display = chips.length ? 'flex' : 'none';
  el.querySelectorAll('.chip-x').forEach(btn=>{
    const kind = btn.dataset.kind;
    if(kind==='sort') btn.onclick = ()=>removeSort(btn.dataset.axis);
    else if(kind==='replace') btn.onclick = ()=>removeReplacement(btn.dataset.axis, btn.dataset.field);
    else if(kind==='unrename') btn.onclick = ()=>unrenameField(btn.dataset.axis, btn.dataset.field);
    else if(kind==='undelete') btn.onclick = ()=>undeleteField(btn.dataset.axis, btn.dataset.field);
    else btn.onclick = ()=>removeFilter(btn.dataset.axis, btn.dataset.field);
  });
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
  navigator.clipboard.writeText(document.getElementById('codeBlock').textContent);
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
  if(pop && !pop.contains(e.target) && !e.target.closest('.axis-filter') && !e.target.closest('.axis-edit')) closeFilterPopover();
});

document.getElementById('grid').addEventListener('click', (e)=>{
  const sortBtn = e.target.closest('.axis-sort');
  if(sortBtn){ e.stopPropagation(); cycleSort(sortBtn.dataset.axis, sortBtn.dataset.field); return; }
  const filterBtn = e.target.closest('.axis-filter');
  if(filterBtn){ e.stopPropagation(); openFilterInput(filterBtn.dataset.axis, filterBtn.dataset.field, filterBtn); return; }
  const editBtn = e.target.closest('.axis-edit');
  if(editBtn){ e.stopPropagation(); openFieldPopover(editBtn.dataset.axis, editBtn.dataset.field, editBtn); return; }
});

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
  const sel = window.getSelection().toString().trim();
  const cellEl = e.target.closest('.cell, .wm-row, #cellBlock, #codeBlock, #selected');
  const fallback = cellEl ? (cellEl.value !== undefined ? cellEl.value : cellEl.textContent).trim() : '';
  const text = sel || fallback;
  if(!text) return; // nothing relevant under the cursor -- let the native menu show
  e.preventDefault();
  closeContextMenu();
  const menu = document.createElement('div');
  menu.id = 'ctxMenu';
  menu.style.left = e.clientX + 'px';
  menu.style.top = e.clientY + 'px';
  const short = text.length > 40 ? text.slice(0, 40) + '…' : text;
  menu.innerHTML = `<button class="ctx-item">Search Google for "${escapeHtml(short)}"</button>`;
  document.body.appendChild(menu);
  menu.querySelector('.ctx-item').onclick = ()=>{
    window.pywebview.api.open_url('https://www.google.com/search?q=' + encodeURIComponent(text));
    closeContextMenu();
  };
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
  if(rowAxisKey(m)!==rowAxisKey(mode)){ rowPage = 0; selR = null; }
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


def open_window(path):
    table = biom.load_table(path)
    title = f"BIOM Viewer — {os.path.basename(path)}"
    api = Api(table, path)
    window = webview.create_window(title, html=PAGE, js_api=api, width=1280, height=820, min_size=(600, 400))
    api.window = window
    return window


# One shared IPC socket per user so double-clicking another .biom file opens
# a new window in the already-running app instead of a whole new process
# (and a second Dock icon) -- macOS delivers each double-click as a fresh
# process launch (see build_macos_app.sh's launcher comment), so the second
# process has to detect the first and hand its file off instead of running.
def _ipc_path():
    return f"/tmp/biom-viewer-{os.getuid()}.sock"


def _send_to_running_instance(path):
    sock_path = _ipc_path()
    if not os.path.exists(sock_path):
        return False
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(2)
            s.connect(sock_path)
            s.sendall(path.encode("utf-8"))
        return True
    except OSError:
        return False  # stale socket file (instance crashed) -- fall through and become the instance


def _listen_for_files():
    sock_path = _ipc_path()
    if os.path.exists(sock_path):
        os.remove(sock_path)
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(sock_path)
    server.listen(5)
    try:
        while True:
            conn, _ = server.accept()
            with conn:
                data = conn.recv(65536)
            # create_window() from a background thread inserts the window
            # into the already-running GUI loop immediately; called from the
            # main thread it would just queue until that loop starts. See
            # https://pywebview.flowrl.com's create_window() source.
            if data:
                open_window(data.decode("utf-8"))
    finally:
        server.close()
        if os.path.exists(sock_path):
            os.remove(sock_path)


def main():
    if len(sys.argv) < 2:
        print("Usage: biom-viewer <file.biom>", file=sys.stderr)
        sys.exit(1)
    path = sys.argv[1]

    if _send_to_running_instance(path):
        return  # handed off to the already-running instance -- nothing left to do

    open_window(path)
    _set_dock_icon()
    threading.Thread(target=_listen_for_files, daemon=True).start()

    def js(code):
        # Not the window that happened to create this menu -- the one
        # currently focused, so File/Edit/View act on whichever window the
        # user is actually looking at (there can be several now).
        return lambda: (webview.active_window() or webview.windows[0]).evaluate_js(code)

    # Replaces pywebview's default Edit/View menus (Cut/Copy/Paste/Fullscreen)
    # with the app's own actions -- native menu items can't carry a Cocoa key
    # equivalent through pywebview's public API, so ⌘-shortcuts stay bound in
    # the page's own keydown listener; these menu items are for discovery/click.
    webview.settings["SHOW_DEFAULT_MENUS"] = False
    menu = [
        Menu("File", [
            MenuAction("Export as Python…", js("openExportModal()")),
            MenuAction("Export View as .biom…", js("exportBiomFile()")),
        ]),
        Menu("Edit", [
            MenuAction("Undo", js("undo()")),
            MenuAction("Redo", js("redo()")),
            MenuSeparator(),
            MenuAction("Find…", js("document.getElementById('searchBox').focus()")),
            MenuAction("Find & Replace…", js("openReplaceModal()")),
        ]),
        Menu("View", [
            MenuAction("Toggle Theme", js("toggleTheme()")),
            MenuSeparator(),
            MenuAction("Increase Font Size", js("setFontSize(fontSize+1)")),
            MenuAction("Decrease Font Size", js("setFontSize(fontSize-1)")),
            MenuSeparator(),
            MenuAction("Expand Selected Cell…", js("openCellModal()")),
        ]),
    ]
    webview.start(menu=menu)


if __name__ == "__main__":
    main()
