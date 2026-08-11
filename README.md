# biom-viewer

[![CI](https://github.com/yarintm/biom-viewer/actions/workflows/ci.yml/badge.svg)](https://github.com/yarintm/biom-viewer/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](pyproject.toml)

A lightweight, double-clickable viewer for **`.biom`** (Biological Observation
Matrix) files. Opens instantly, keeps its memory footprint tiny no matter how
large the file is, and never runs a manual `biom convert` for you.

<p align="center">
  <img src="docs/screenshot-dark.jpg" width="80%" alt="biom-viewer, dark mode">
</p>
<p align="center">
  <img src="docs/screenshot-light.jpg" width="80%" alt="biom-viewer, light mode">
</p>

## The problem

`.biom` files (HDF5) store biological observation data as **sparse
matrices** — mostly zeros, heavily compressed. That's great for storage, and
terrible for viewing:

- **Sparse-to-dense memory explosion.** Naively converting a `.biom` file to
  a dense 2D table (CSV, DataFrame, spreadsheet) forces every implicit zero
  to become an explicit one. A 50MB sparse file can expand into a 3GB+ dense
  matrix — enough to exhaust RAM on a laptop before you've seen a single row.
- **UI rendering bottleneck.** Even if you had the RAM, no table widget
  survives being handed a few million DOM rows.
- **Workflow friction.** The usual answer is `biom convert` to a flat file
  first, look at it, then throw the flat file away. That's a detour every
  single time you just want to peek at a file.

## How it avoids all three

**The table is never densified.** The backend loads the `.biom` file with
[`biom-format`](https://github.com/biocore/biom-format) and keeps it as a
`scipy` sparse matrix in memory, full stop. When the UI needs to show
something, the backend slices out *only the rows/columns currently on
screen* and densifies that tiny window — typically a few hundred cells,
regardless of whether the table has 500 columns or 500,000.

```python
# biom_viewer/app.py — the entire "engine"
def data_window(r0, r1, c0, c1):
    sub = TABLE.matrix_data[r0:r1, :].tocsc()[:, c0:c1]
    return sub.toarray().tolist()   # densify only this window
```

**The grid renders only what's on screen.** There's no virtual-scroll buffer
to manage — the UI is paginated (◀ ▶ / ▲ ▼), and row/column count auto-fits
to your window size, stretching cells to fill the space exactly. Move to the
next page and the frontend asks the backend for the next small window.

**No CLI conversion, no double-click friction.** Double-click a `.biom` file
and it just opens — see [macOS integration](#macos-double-click-integration)
below.

## Architecture

```
┌─────────────────────┐  window.pywebview.api.meta()  ┌──────────────────────┐
│                      │ ──────────────────────────▶  │                      │
│  Native OS window    │  {rows, cols, row_ids,        │  Python              │
│  (pywebview, system  │   col_ids, filename}          │                      │
│  WebKit — vanilla    │                                │  TABLE = sparse      │
│  JS, CSS Grid,       │  .data_window(r0,r1,c0,c1)    │  scipy matrix,       │
│  no framework)       │ ──────────────────────────▶  │  loaded once via     │
│  - paginated grid    │                                │  biom-format         │
│  - auto-fits window  │  [[...]]                       │                      │
│  - click = copy      │ ◀──────────────────────────  │                      │
│  - theme + font size │  (only the visible window       └──────────────────────┘
└─────────────────────┘   is ever densified)
```

No HTTP server, no port, no browser tab — the frontend calls Python
functions directly through pywebview's JS↔Python bridge (`js_api`), and
those calls never leave the process. The whole app is one Python file
(`biom_viewer/app.py`): a small `Api` class exposes `meta()` and
`data_window()`, and the HTML/CSS/JS for the grid is a string handed to
`webview.create_window()`. Two dependencies: `biom-format` (no stdlib
equivalent for parsing HDF5 BIOM tables) and `pywebview` (wraps the OS's
native webview — WKWebView on macOS — so there's no bundled Chromium).

## Install

```bash
pip install biom-viewer   # once published to PyPI
# or, from a clone:
pip install -e .
```

## Usage

```bash
biom-viewer path/to/table.biom
```

Opens a native window (not a browser tab — no address bar, no server, no
port). Closing the window ends the process.

### Controls

- **▲ / ▼** — page through rows · **◀ / ▶** — page through columns
- Rows/columns per page **auto-fit your window size** — resize the window
  and the grid re-flows to fill it, always leaving the same small gap at the
  edges
- Click any row label, column header, or cell — its full text (or
  `row | col = value`) is copied straight to your clipboard, and the row +
  column it belongs to are highlighted
- 🌙/☀️ toggles dark/light theme; **A-** / **A+** adjust font size

## macOS double-click integration

Skip the terminal entirely — make `.biom` files openable like any document.

```bash
pip install -e .                    # or: pip install biom-viewer
./scripts/install_macos_app.sh      # builds ~/Applications/BiomViewer.app
```

Then: right-click any `.biom` file → **Get Info** → **Open with** →
**BiomViewer** → **Change All…**. From then on, double-clicking a `.biom`
file opens it directly in its own window.

The generated app is a thin AppleScript wrapper that calls whatever
`biom-viewer` is on your `PATH` at install time — no hardcoded paths, so it
keeps working across virtualenvs and machines as long as you re-run the
script after reinstalling.

## Development

```bash
git clone https://github.com/yarintm/biom-viewer.git
cd biom-viewer
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the design constraints a PR
should respect (mainly: never densify the whole table).

## License

[MIT](LICENSE)
