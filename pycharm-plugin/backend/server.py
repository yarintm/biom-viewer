import json
import os
import sys

import biom

from biom_viewer.app import PAGE, Api, build_export_table, write_biom_file


class PluginApi(Api):
    """The desktop Api, minus the one method that needs a pywebview window.

    Everything else -- meta, data windows, summaries, the whole workspace
    store -- is the same code the native app runs, so the plugin's UI is the
    native UI rather than a second implementation drifting alongside it.
    """

    def export_table(self, spec):
        # The native app opens a save dialog off its pywebview window; this
        # process has no GUI to hang one on. Write beside the source file
        # instead and report the path, which is what the frontend shows.
        # ponytail: fixed destination; wire a real dialog through the Kotlin
        # side if people ask to choose where exports land.
        path = os.path.splitext(self._filename)[0] + "_export.biom"
        try:
            write_biom_file(build_export_table(self._table, spec), path)
        except Exception as exc:  # noqa: BLE001 -- surface to the UI
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "path": path}


def main():
    path = sys.argv[1]
    api = PluginApi(biom.load_table(path), path)

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        request = json.loads(line)
        request_id = request.get("id")
        method_name = request.get("method") or ""
        # Dispatched by name off the Api instance so every method the frontend
        # knows about works without a second allow-list to keep in sync; the
        # leading-underscore guard keeps internals (and dunders) off the wire.
        # Resolution is a separate step from the call so an AttributeError
        # raised *inside* a real method isn't reported as "unknown method".
        fn = None if method_name.startswith("_") else getattr(api, method_name, None)
        if method_name == "page":
            fn = lambda: PAGE  # noqa: E731
        if not callable(fn):
            response = {"id": request_id, "ok": False, "error": f"unknown method: {method_name}"}
        else:
            try:
                result = fn(*request.get("params", {}).get("args", []))
                response = {"id": request_id, "ok": True, "result": result}
            except Exception as e:
                response = {"id": request_id, "ok": False, "error": str(e)}
        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
