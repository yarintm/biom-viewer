import contextlib
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


@contextlib.contextmanager
def server():
    path = make_fixture()
    proc = subprocess.Popen(
        [sys.executable, SERVER, path],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        yield proc
    finally:
        proc.kill()
        os.remove(path)


def call(proc, method, *args):
    proc.stdin.write(json.dumps({"id": 1, "method": method, "params": {"args": list(args)}}) + "\n")
    proc.stdin.flush()
    return json.loads(proc.stdout.readline())


def test_meta_and_data_window_over_stdio():
    with server() as proc:
        meta = call(proc, "meta")
        assert meta["ok"] is True
        assert meta["result"]["rows"] == 3
        assert meta["result"]["cols"] == 4

        # Positional args, because the frontend calls these as plain JS
        # functions (window.pywebview.api.data_window(r0, r1, c0, c1)).
        window = call(proc, "data_window", 0, 3, 0, 4)
        assert window["ok"] is True
        assert window["result"] == [[0, 1, 0, 0], [2, 0, 0, 5], [0, 0, 0, 0]]


def test_page_returns_the_desktop_apps_full_html():
    with server() as proc:
        resp = call(proc, "page")
        assert resp["ok"] is True
        page = resp["result"]
        assert "<!doctype html>" in page
        assert "#grid" in page  # the desktop stylesheet
        assert "pywebviewready" in page  # the desktop script


def test_any_api_method_dispatches_without_an_allow_list():
    # The whole point of generic dispatch: a method nobody listed anywhere in
    # the plugin still reaches the desktop Api.
    with server() as proc:
        resp = call(proc, "cell_matches", ">", 1)
        assert resp["ok"] is True


def test_unknown_method_returns_error_not_crash():
    with server() as proc:
        resp = call(proc, "nope")
        assert resp["ok"] is False
        assert "nope" in resp["error"]


def test_private_attributes_are_not_callable_over_the_wire():
    with server() as proc:
        for name in ("_table", "__class__", "_csc"):
            resp = call(proc, name)
            assert resp["ok"] is False, name


def test_error_inside_a_real_method_is_not_reported_as_unknown_method():
    with server() as proc:
        resp = call(proc, "data_window", 0, 1)  # too few args
        assert resp["ok"] is False
        assert "unknown method" not in resp["error"]
