# Contributing

Bug reports and PRs are welcome.

## Dev setup

```bash
git clone https://github.com/yarintm/biom-viewer.git
cd biom-viewer
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## Running tests

```bash
pytest
```

## Design constraints worth knowing before you send a PR

- **Never densify the full table.** All rendering must go through windowed
  slices of the sparse matrix (`data_window`). A PR that materializes the
  whole table defeats the point of this tool.
- **Stdlib-first.** The backend intentionally uses `http.server` instead of a
  web framework, and the frontend is vanilla JS. Please don't introduce
  Flask/FastAPI/React/etc. unless there's a concrete reason the stdlib can't
  do it.
- Keep `biom_viewer/app.py` a single file if you can — it's meant to stay
  readable top to bottom.
