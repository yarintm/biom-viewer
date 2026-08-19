#!/usr/bin/env python3
"""Dev-only local server: serves the app's real PAGE UI over HTTP with a JSON
API standing in for the pywebview bridge, so the UI can be driven with
ordinary browser automation (clicks, screenshots) instead of the native
window, which offers no such tooling. Not part of the shipped app.
"""
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

import biom

from biom_viewer import app as bv

# Defines window.pywebview.api to match the real pywebview bridge, backed by
# fetch() calls instead — the app's own script is served byte-for-byte
# unmodified, so what's tested here is exactly what ships.
SHIM = """
<script>
if(!window.pywebview){
  const post = (path, body) => fetch(path, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body||{})}).then(r=>r.json());
  window.pywebview = { api: {
    meta: () => post('/api/meta'),
    data_window: (r0,r1,c0,c1) => post('/api/data_window', {r0,r1,c0,c1}),
    row_summary: (r) => post('/api/row_summary', {r}),
    col_summary: (c) => post('/api/col_summary', {c}),
    field_summary: (axis, field) => post('/api/field_summary', {axis, field}),
  }};
  window.dispatchEvent(new Event('pywebviewready'));
}
</script>
"""

API = {
    "/api/meta": lambda body: bv.meta(),
    "/api/data_window": lambda body: bv.data_window(body["r0"], body["r1"], body["c0"], body["c1"]),
    "/api/row_summary": lambda body: bv.row_summary(body["r"]),
    "/api/col_summary": lambda body: bv.col_summary(body["c"]),
    "/api/field_summary": lambda body: bv.field_summary(body["axis"], body["field"]),
}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # ponytail: silence default request logging, not needed for a dev tool

    def do_GET(self):
        if self.path != "/":
            self.send_response(404)
            self.end_headers()
            return
        html = bv.PAGE.replace("</body>", SHIM + "</body>")
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        handler = API.get(self.path)
        if handler is None:
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        body = json.loads(raw) if raw else {}
        result = bv._json_safe(handler(body))
        payload = json.dumps(result).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def main():
    if len(sys.argv) < 2:
        print("Usage: dev_server.py <file.biom> [port]", file=sys.stderr)
        sys.exit(1)
    bv.TABLE = biom.load_table(sys.argv[1])
    bv.FILENAME = sys.argv[1]
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8765
    # Single-threaded on purpose: pywebview's real JS<->Python bridge
    # dispatches calls sequentially too, so this matches production
    # behavior rather than introducing concurrency the real app never has.
    server = HTTPServer(("127.0.0.1", port), Handler)
    print(f"Serving BiomViewer UI at http://127.0.0.1:{port}/  (Ctrl+C to stop)")
    server.serve_forever()


if __name__ == "__main__":
    main()
