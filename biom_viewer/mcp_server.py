"""MCP server exposing biom_viewer's Api as tools an LLM can call to build
and save views (filters, sort, pinned rows/fields) from a natural-language
request, without going through the GUI.

Run: biom-viewer-mcp path/to/table.biom
"""
from __future__ import annotations

import sys

import biom
from mcp.server.mcpserver import MCPServer

from biom_viewer.app import Api

mcp = MCPServer("biom-viewer")

# Set by main() at process start. A headless Api bound to one table/file —
# ok that Api.window stays None here, since none of the methods this module
# calls (meta, field_summary, save_view, load_workspace, delete_view,
# move_view) touch window; only export_table/open_url do, and this server
# doesn't expose those.
_api: Api | None = None


def _get_api() -> Api:
    if _api is None:
        raise RuntimeError("mcp_server._api not set — call main() or set it in a test")
    return _api


def list_fields(axis: str) -> list[str]:
    """Metadata field names available on `axis` ('observation' or 'sample')."""
    meta = _get_api().meta()
    key = "row_metadata" if axis == "observation" else "col_metadata"
    rows = meta[key] or []
    fields: set[str] = set()
    for row in rows:
        fields.update(row.keys())
    return sorted(fields)


def field_summary(axis: str, field: str) -> dict:
    """Histogram (numeric field) or top-value counts (categorical field) for
    `field` on `axis` ('observation' or 'sample') — use this to pick sane
    filter thresholds or categorical values before calling create_view."""
    return _get_api().field_summary(axis, field)


def _axis_state(filters: list[dict] | None, sort: dict | None) -> dict:
    return {
        "sortField": sort["field"] if sort else None,
        "sortDir": sort["dir"] if sort else 0,
        "filters": filters or [],
        "replacements": [],
        "renames": {},
        "deletedFields": [],
        "columnSets": [],
    }


def create_view(
    name: str,
    mode: str = "data",
    row_fields: list[str] | None = None,
    col_fields: list[str] | None = None,
    observation_filters: list[dict] | None = None,
    sample_filters: list[dict] | None = None,
    observation_sort: dict | None = None,
    sample_sort: dict | None = None,
    pinned_observation_ids: list[int] | None = None,
    pinned_column_fields: list[str] | None = None,
) -> dict:
    """Build and save one named view. Overwrites any existing view with the
    same name.

    mode: 'data' | 'row' (observation-metadata mode) | 'col' (sample-metadata mode).
    *_filters: list of
      {"field": str, "kind": "numeric", "min": float, "max": float} or
      {"field": str, "kind": "categorical", "text": str}
    observation_sort / sample_sort: {"field": str, "dir": 1 or -1} or None.
    pinned_observation_ids: raw observation row indices to freeze on screen
      (get these from meta()'s row_ids order, index 0-based).
    pinned_column_fields: metadata field names to freeze in col-metadata mode,
      e.g. ["diagnosis"].
    """
    payload = {
        "mode": mode,
        "axisState": {
            "observation": _axis_state(observation_filters, observation_sort),
            "sample": _axis_state(sample_filters, sample_sort),
        },
        "rowFields": row_fields or [],
        "colFields": col_fields or [],
        "pinnedObs": pinned_observation_ids or [],
        "pinnedColFields": pinned_column_fields or [],
    }
    _get_api().save_view(name, payload)
    return payload


def create_views(specs: list[dict]) -> list[dict]:
    """Create several views in one call — e.g. "one view per diagnosis
    value". Each item in `specs` is a kwargs dict for create_view (must
    include "name")."""
    return [create_view(**spec) for spec in specs]


def list_views() -> list[dict]:
    """Name, save timestamp, and folder (null if ungrouped) of every saved view."""
    workspace = _get_api().load_workspace()
    return [{"name": v["name"], "saved_at": v["savedAt"], "folder": v.get("folder")} for v in workspace["views"]]


def delete_view(name: str) -> dict:
    """Delete a saved view by name."""
    _get_api().delete_view(name)
    return {"ok": True}


def move_view(name: str, folder: str | None = None) -> dict:
    """File a saved view into a folder, or take it out.

    A folder isn't a separate object — it's just a label on a view — so
    filing the first view into a new folder name creates that folder, and
    `folder=None` moves the view back out to the ungrouped top level. Folder
    names group by exact string match across views (case-sensitive).
    """
    _get_api().move_view(name, folder)
    return {"ok": True}


mcp.tool()(list_fields)
mcp.tool()(field_summary)
mcp.tool()(create_view)
mcp.tool()(create_views)
mcp.tool()(list_views)
mcp.tool()(delete_view)
mcp.tool()(move_view)


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: biom-viewer-mcp <path-to-biom>", file=sys.stderr)
        raise SystemExit(1)
    global _api
    table = biom.load_table(sys.argv[1])
    _api = Api(table, sys.argv[1])
    mcp.run()


if __name__ == "__main__":
    main()
