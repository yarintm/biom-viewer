"""Browser-driven regression tests for grid-paging state (rowPage/colPage).

Runs the app's real, unmodified PAGE/SCRIPT (via scripts/dev_server.py's
HTTP+JSON shim for the pywebview bridge) under a real browser, using
Playwright against the system Chrome install (channel="chrome") rather than
a downloaded browser -- no extra binaries, no network fetch at test time.

Skipped automatically if Playwright or a Chrome install isn't available, so
the fast `pytest` suite (tests/test_app.py etc.) never depends on this.
Install with: pip install -e ".[ui]"

These four bugs all shipped and were only caught by manually poking the
running app -- the paging state is pure client-side JS with no prior test
coverage at all. Each test here pins down the exact regression it covers.
"""
import contextlib
import importlib.util
import socket
import sys
import threading
from http.server import HTTPServer
from pathlib import Path

import biom
import numpy as np
import pytest

playwright_sync_api = pytest.importorskip("playwright.sync_api")
sync_playwright = playwright_sync_api.sync_playwright

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_dev_server():
    spec = importlib.util.spec_from_file_location("dev_server", REPO_ROOT / "scripts" / "dev_server.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["dev_server"] = mod
    spec.loader.exec_module(mod)
    return mod


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _make_table(tmp_path):
    # Deliberately long, taxonomy-shaped observation IDs and short sample
    # metadata field names -- a short-ID fixture doesn't stress the
    # row-header-width computation enough to exercise the resize/mode-switch
    # paging paths realistically (see the "moving between data view..." bug).
    # Enough observations/samples that a single page never fits all of them
    # regardless of window size, and that paging in ~20 columns deep (see
    # test_mode_switch_keeps_the_previously_visible_sample_in_view) doesn't
    # run past the last page.
    n_obs, n_samp = 200, 300
    rng = np.random.default_rng(0)
    data = rng.random((n_obs, n_samp))
    obs_ids = [
        f"k__Bacteria;p__Firmicutes;c__Clostridia;o__Lachnospirales;"
        f"f__Lachnospiraceae;g__Blautia;s__obscura_{i}"
        for i in range(n_obs)
    ]
    samp_ids = [f"SRR{6468520 + i}" for i in range(n_samp)]
    samp_md = [{"assay_type": "WGS" if i % 2 == 0 else "AMPLICON"} for i in range(n_samp)]
    table = biom.Table(data, obs_ids, samp_ids, sample_metadata=samp_md)
    path = tmp_path / "ui_test.biom"
    with biom.util.biom_open(str(path), "w") as f:
        table.to_hdf5(f, "ui-test")
    return path


@pytest.fixture(scope="module")
def served_url(tmp_path_factory):
    dev_server = _load_dev_server()
    tmp_path = tmp_path_factory.mktemp("ui-paging")
    biom_path = _make_table(tmp_path)

    dev_server.API_INSTANCE = dev_server.bv.Api(
        biom.load_table(str(biom_path)),
        str(biom_path),
        workspace_store=dev_server.bv.WorkspaceStore(tmp_path / "state.json"),
    )
    port = _free_port()
    server = HTTPServer(("127.0.0.1", port), dev_server.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}/"
    finally:
        server.shutdown()
        thread.join(timeout=5)


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        try:
            b = p.chromium.launch(channel="chrome", headless=True)
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"no usable Chrome install for Playwright: {exc}")
        yield b
        b.close()


@pytest.fixture
def page(browser, served_url):
    pg = browser.new_page(viewport={"width": 1400, "height": 700})
    pg.goto(served_url)
    pg.wait_for_function("window.meta !== null", timeout=10000)
    yield pg
    pg.close()


def _dump(page):
    return page.evaluate(
        "() => ({mode, rowPage, colPage, "
        "rowRange: document.getElementById('rowRange').textContent, "
        "colRange: document.getElementById('colRange').textContent})"
    )


def test_switching_to_sample_metadata_preserves_observation_page(page):
    """Regression: data(rowPage>0) -> Sample metadata -> data used to reset
    rowPage to 0, even though Sample metadata never touches the observation
    axis at all."""
    page.click("#rowDown")
    page.click("#rowDown")
    before = _dump(page)
    assert before["rowPage"] == 2

    page.click('[data-m="col"]')
    page.wait_for_timeout(200)
    page.click('[data-m="data"]')
    page.wait_for_timeout(200)
    after = _dump(page)
    assert after["rowPage"] == before["rowPage"]
    assert after["rowRange"] == before["rowRange"]


def test_switching_to_observation_metadata_preserves_sample_page(page):
    """Regression: the symmetric bug -- data(colPage>0) -> Observation
    metadata -> data used to reset colPage to 0."""
    page.click("#colNext")
    page.click("#colNext")
    before = _dump(page)
    assert before["colPage"] == 2

    page.click('[data-m="row"]')
    page.wait_for_timeout(200)
    page.click('[data-m="data"]')
    page.wait_for_timeout(200)
    after = _dump(page)
    assert after["colPage"] == before["colPage"]
    assert after["colRange"] == before["colRange"]


def test_mode_switch_keeps_the_previously_visible_sample_in_view(page):
    """colsPerPage() legitimately differs between modes -- row-header width
    depends on mode-specific content (a short id in 'data' mode vs. a long
    field name like "geo_loc_name_country_continent_calc" in 'col' mode) --
    so keeping the literal page *number* identical across a switch isn't
    enough once you're several pages in: a real user file hit this at
    page 47, where a 1-sample-per-page difference in colsPerPage compounded
    into "samples 612-624" landing on a completely disjoint "samples
    565-576" after switching to Sample metadata. Anchor on the actual
    visible item instead: whatever sample was first-visible before the
    switch must still be somewhere in view afterward, regardless of how the
    page math shakes out.
    """
    for _ in range(20):  # page in deep enough for a small perPage delta to matter
        page.click("#colNext")
    first_visible_before = page.evaluate("sampleAt(colPage * colsPerPage())")

    page.click('[data-m="col"]')
    page.wait_for_timeout(200)
    c0, c1 = page.evaluate(
        "[colPage * colsPerPage(), Math.min(colPage * colsPerPage() + colsPerPage(), colsTotal())]"
    )
    assert c0 <= first_visible_before < c1, (
        f"sample {first_visible_before} was visible before switching modes "
        f"but fell outside the new visible range [{c0}, {c1})"
    )


def test_window_resize_does_not_reset_the_page(page):
    """Regression: any window resize used to hard-reset both rowPage and
    colPage to 0 unconditionally, discarding your position for an unrelated
    layout change."""
    page.click("#rowDown")
    page.click("#rowDown")
    page.click("#colNext")
    before = _dump(page)
    assert before["rowPage"] > 0 and before["colPage"] > 0

    page.set_viewport_size({"width": 1000, "height": 700})
    page.wait_for_timeout(400)  # resize handler debounces 150ms
    after_shrink = _dump(page)
    assert after_shrink["rowPage"] == before["rowPage"]
    assert after_shrink["colPage"] == before["colPage"]

    page.set_viewport_size({"width": 1400, "height": 700})
    page.wait_for_timeout(400)
    after_restore = _dump(page)
    assert after_restore["rowPage"] == before["rowPage"]
    assert after_restore["colPage"] == before["colPage"]


def test_header_context_menu_full_when_summary_expanded(page):
    """Regression: right-clicking a row header whose double-click-expanded
    summary panel (Missing/Distinct/histogram) was open used to find none of
    the ctx* dataset the menu is built from, and fell back to a single,
    mangled 'Search Google for <the whole stats panel's text>' item instead
    of the normal Sort/Filter/Rename/Delete/Pin menu.

    Only 'col' mode's row headers are metadata fields (Sort/Filter/Rename/
    Delete only make sense for a field, not a bare observation), which is
    the case the original bug screenshot showed.
    """
    page.click('[data-m="col"]')
    page.wait_for_timeout(200)

    header = page.locator(".rh").first
    header.dblclick()  # expand this field row's summary panel
    page.wait_for_timeout(200)
    assert page.locator(".rh.rh-stats").count() > 0, "summary panel did not expand"

    page.locator(".rh.rh-stats").first.click(button="right")
    page.wait_for_timeout(100)
    menu_text = page.locator("#ctxMenu").inner_text()
    assert "Sort by" in menu_text
    assert "Pin to top" in menu_text
