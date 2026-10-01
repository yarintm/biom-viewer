package com.biomviewer.plugin

// ponytail: single hardcoded repo path -- this plugin only runs on the
// author's machine against this one repo checkout. Revisit if it ever needs
// to run against a different checkout or a real install.
const val BIOM_VIEWER_REPO_ROOT = "/Users/yarintamam/Code/biom-viewer"

// ponytail: reuses this repo's own dev venv (already has biom-format/numpy/
// scipy/pandas installed via `pip install -e .` -- see pyproject.toml)
// instead of bootstrapping a second one. Still fully independent of whatever
// interpreter a *viewed* project has configured in PyCharm, which is the
// actual constraint that mattered -- a from-scratch bootstrap turned out to
// hit real friction (macOS's bundled python3 ships pip 21.2.4, too old for
// PEP 660 editable installs of a pyproject.toml-only package) for no benefit
// over an env that already exists and already works.
object BiomEnvironment {
    fun pythonExecutable(): String = "$BIOM_VIEWER_REPO_ROOT/.venv/bin/python3"
}
