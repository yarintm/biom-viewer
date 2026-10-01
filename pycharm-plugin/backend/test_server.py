import json
import os
import subprocess
import sys
import tempfile

import biom
import numpy as np
from biom.util import biom_open

SERVER = os.path.join(os.path.dirname(__file__), "server.py")


def make_fixture():
    data = np.array([[0, 1, 0, 0], [2, 0, 0, 5], [0, 0, 0, 0]])
    table = biom.Table(data, ["obs1", "obs2", "obs3"], ["s1", "s2", "s3", "s4"])
    path = tempfile.mktemp(suffix=".biom")
    with biom_open(path, "w") as f:
        table.to_hdf5(f, "test")
    return path


def send(proc, req):
    proc.stdin.write(json.dumps(req) + "\n")
    proc.stdin.flush()
    return json.loads(proc.stdout.readline())


def test_meta_and_data_window_over_stdio():
    path = make_fixture()
    proc = subprocess.Popen(
        [sys.executable, SERVER, path],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        meta_resp = send(proc, {"id": 1, "method": "meta", "params": {}})
        assert meta_resp["ok"] is True
        assert meta_resp["result"]["rows"] == 3
        assert meta_resp["result"]["cols"] == 4

        window_resp = send(proc, {"id": 2, "method": "data_window", "params": {"r0": 0, "r1": 3, "c0": 0, "c1": 4}})
        assert window_resp["ok"] is True
        assert window_resp["result"] == [[0, 1, 0, 0], [2, 0, 0, 5], [0, 0, 0, 0]]
    finally:
        proc.kill()
        os.remove(path)


def test_unknown_method_returns_error_not_crash():
    path = make_fixture()
    proc = subprocess.Popen(
        [sys.executable, SERVER, path],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        resp = send(proc, {"id": 1, "method": "nope", "params": {}})
        assert resp["ok"] is False
        assert "nope" in resp["error"]
    finally:
        proc.kill()
        os.remove(path)
