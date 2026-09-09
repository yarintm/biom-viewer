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
# calls (meta, field_summary, save_view, load_workspace, delete_view) touch
# window; only export_table/open_url do, and this server doesn't expose those.
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


mcp.tool()(list_fields)
mcp.tool()(field_summary)


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
