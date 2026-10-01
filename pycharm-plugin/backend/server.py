import json
import sys

import biom

from biom_viewer.app import Api


def main():
    path = sys.argv[1]
    table = biom.load_table(path)
    api = Api(table, path)
    methods = {"meta": api.meta, "data_window": api.data_window}

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        request = json.loads(line)
        request_id = request.get("id")
        method_name = request.get("method")
        try:
            fn = methods[method_name]
            result = fn(**request.get("params", {}))
            response = {"id": request_id, "ok": True, "result": result}
        except KeyError:
            response = {"id": request_id, "ok": False, "error": f"unknown method: {method_name}"}
        except Exception as e:
            response = {"id": request_id, "ok": False, "error": str(e)}
        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
