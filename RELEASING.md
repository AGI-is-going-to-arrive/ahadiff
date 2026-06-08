# Releasing AhaDiff to PyPI

Maintainer runbook for cutting a PyPI release of `ahadiff`. Every step below is grounded in
the real repo: `pyproject.toml` (hatchling + `force-include`), `scripts/check_wheel_webui.py`
(the wheel WebUI gate), `.github/workflows/release.yml` (the CI gate + publish job), and
`src/ahadiff/serve/static.py` (`_resolve_viewer_dist`).

The single most important property to preserve: a `pip install ahadiff` wheel must ship a
**working bundled WebUI**. The wheel bundles `viewer/dist` into `ahadiff/_webui` via
hatchling `force-include`, and `ahadiff serve` resolves that package-internal `_webui` at
runtime. If you build the wheel before building the viewer, the WebUI is missing and
`ahadiff serve` has nothing to serve. The build order in Section 2 exists to prevent exactly
this.

---

## 1. Prerequisites

- **PyPI account** with maintainer/owner rights on the existing `ahadiff` project.
  - Confirm the account, project-scoped API token, or Trusted Publisher can publish to the
    `ahadiff` project before building the final artifact.
- **PyPI OIDC Trusted Publisher** configured for this repo so CI publishes with no API token.
  - `.github/workflows/release.yml` already publishes via OIDC
    (`pypa/gh-action-pypi-publish@release/v1` with `permissions: id-token: write`). For that to
    work you must register a Trusted Publisher on PyPI:
    - PyPI → project `ahadiff` → *Settings* → *Publishing* → *Add a new publisher*.
    - Owner: `AGI-is-going-to-arrive` (per `[project.urls]` in `pyproject.toml`)
    - Repository name: `ahadiff`
    - Workflow filename: `release.yml`
    - Environment name: `pypi` (the `publish` job declares `environment: pypi`).
  - Register the same Trusted Publisher on **TestPyPI** if you want the TestPyPI rehearsal
    (Section 5) to use OIDC instead of a token.
- **GitHub Actions trigger policy**: packaging CI and release workflows keep `push` disabled;
  publish through `workflow_dispatch` or a tag run. The Pages workflow is the deliberate
  exception: it still deploys docs on pushes that touch `docs/**` or the Pages workflow file.
- **Local toolchain** for building and the clean-venv smoke test:
  - Node + `pnpm` (the viewer is built with pnpm; `viewer/pnpm-lock.yaml` is the lockfile).
  - `uv` (build backend driver; `uv build`, `uv publish`).
  - Python 3.11+ (`requires-python = ">=3.11"`).

> Credentials policy: never commit a PyPI token. CI uses OIDC (no token). For manual publish,
> pass credentials via environment variables or keyring only (Section 4B).

---

## 2. Build order (CRITICAL — do these in order)

This is the same sequence CI runs in `gate-linux` (viewer build → wheel build → wheel-content
check → install smoke). Run it locally before tagging.

### (a) Build the viewer (`viewer/dist`)

```bash
cd viewer
pnpm install --frozen-lockfile
pnpm build
cd ..
```

This produces `viewer/dist/` (the compiled SPA: `index.html`, `assets/`, `icons/`,
`registerSW.js`, `sw.js`, `manifest.json`, ...). The wheel bundles this directory; if it is
stale or missing, the published WebUI is wrong.

### (b) Build the distributions at the repo root

```bash
uv build
```

hatchling reads `[tool.hatch.build.targets.wheel.force-include]` and copies
`viewer/dist` → `ahadiff/_webui` inside the wheel. Output lands in `dist/*.whl` and
`dist/*.tar.gz`.

### (c) Validate the wheel's WebUI asset graph (MUST pass)

```bash
python scripts/check_wheel_webui.py dist/*.whl
```

`scripts/check_wheel_webui.py` is stdlib-only. It opens the wheel, asserts
`ahadiff/_webui/index.html` exists, parses it for `assets/*.js` / `assets/*.css` bundle
references, then transitively walks references from `index.html`, `registerSW.js`, `sw.js`,
the manifest, and CSS `url(...)` — failing if any referenced WebUI asset is missing from the
wheel. Exit code `0` = pass. This is the authoritative "the bundled WebUI is complete" gate
and is the same script CI runs in the *Gate - wheel content* step.

### (d) Clean-venv smoke (proves package-internal resolution)

Install the freshly built wheel into a throwaway venv, check the version, then start `serve`
**from an empty directory** (not the repo) and confirm `GET /` returns the bundled SPA. Running
from an empty dir is what proves the WebUI is resolved from the packaged `ahadiff/_webui` and
not from a local `viewer/dist`.

```bash
# fresh venv, install the wheel
python -m venv /tmp/ahadiff-smoke
source /tmp/ahadiff-smoke/bin/activate    # Windows: .\.tmp\ahadiff-smoke\Scripts\activate
python -m pip install --upgrade pip
python -m pip install dist/*.whl

# version must match the release version
ahadiff --version

# serve from an EMPTY dir so viewer/dist is not on disk; --no-browser stays in terminal
mkdir -p /tmp/ahadiff-empty
cd /tmp/ahadiff-empty
ahadiff serve --no-browser &
SERVE_PID=$!
sleep 3

# GET / must return the bundled SPA (expect <!doctype html> ... <div id="root">)
curl -fsS http://127.0.0.1:8765/ | head -n 20

kill "$SERVE_PID"
cd -
deactivate
```

Resolution order enforced by `_resolve_viewer_dist` (in `src/ahadiff/serve/static.py`):

1. `AHADIFF_VIEWER_DIST` env var, if it points at a valid dist (dir containing `index.html`).
2. Packaged `ahadiff/_webui` (the wheel bundle) — this is what the empty-dir smoke exercises.
3. Repo `viewer/dist` **only** when the cwd repo is the AhaDiff source checkout (detected by
   `src/ahadiff/__init__.py` present **and** `pyproject.toml` `project.name == "ahadiff"`).
4. Otherwise `None` (fail closed — `serve` mounts no SPA).

`serve` binds `127.0.0.1:8765` and auto-opens the browser; `--no-browser` suppresses that.

---

## 3. Version policy

- **Releases are GA** (normal, non-prerelease versions). Plain `pip install ahadiff` installs the latest
  — no `--pre` needed. There is no alpha/`aN` suffix anymore.
- The version is declared in these files that must always agree:
  - `pyproject.toml` → `[project]` `version`
  - `src/ahadiff/__init__.py` → `__version__`
  - `uv.lock` → editable project package version
  - `viewer/package.json` → viewer package version
  - `viewer/src/components/Sidebar.tsx` → visible WebUI version label
- For any future release, bump all declared versions to the same value before building. Use PEP
  440 ordering: `1.1.2`, `1.2.0`, `2.0.0` for GA; `1.2.0rc1` / `1.2.0a1` for pre-releases
  (those require `pip install --pre`).

---

## 4. Publish options

### (A) GitHub Actions — `release.yml` (preferred, OIDC, no token)

What the workflow **actually** does today (read from `.github/workflows/release.yml`):

- **Triggers**: only `workflow_dispatch` (with a `dry_run` boolean input, **default `true`**).
  The `push: tags: ["v*"]` trigger is present **but commented out** — this is intentional, so a
  plain push/tag does not auto-run the release workflow.
- **`gate-linux`** (ubuntu): builds SQLite with FTS5, `uv sync`, then runs the gates —
  pytest + coverage `--cov-fail-under=85`, Graphify perf bench, ruff check/format, pyright,
  `pnpm install --frozen-lockfile && pnpm build`, `uv build`,
  `python scripts/check_wheel_webui.py dist/*.whl`, CLI smoke, and a wheel-install smoke in a
  fresh venv. Uploads `dist/*` as the `distributions` artifact.
- **`gate-windows-runtime`** (windows): runs the cross-platform / SQLite / reparse-point guard
  tests.
- **`publish`** (ubuntu): `needs: [gate-linux, gate-windows-runtime]`, downloads the
  `distributions` artifact, and publishes via `pypa/gh-action-pypi-publish@release/v1` with
  `permissions: id-token: write` (OIDC Trusted Publishing — **no API token in CI**). It is
  guarded by:
  `if: startsWith(github.ref, 'refs/tags/v') && github.event.inputs.dry_run != 'true'`.

The tag push trigger is intentionally commented out. Do not re-enable it just to publish. For
OIDC publishing, create and push the tag for traceability, then dispatch the workflow on that
tag ref with `dry_run=false`:

```bash
# 1) bump all declared versions, commit, open PR, merge to main
# 2) tag the release commit and push the tag; push does not trigger release.yml
git tag v<ver>
git push origin v<ver>

# 3) manually dispatch the release workflow on the tag ref
gh workflow run release.yml --ref v<ver> -f dry_run=false
```

To dry-run the gates without publishing (works today), use the Actions UI → *Release* →
*Run workflow* with `dry_run = true` (the default), or run:

```bash
gh workflow run release.yml --ref main -f dry_run=true
```

### (B) Manual publish (from a verified local build)

Only after Section 2 (a)–(d) all pass on the artifact you intend to ship.

```bash
# uv (uses TWINE_/UV_PUBLISH_ env or keyring; never inline a token)
uv publish dist/*
```

or with twine:

```bash
python -m pip install --upgrade twine
python -m twine upload dist/*
```

Provide credentials via environment (`TWINE_USERNAME=__token__`, `TWINE_PASSWORD=<token>`) or
keyring. **Never commit a token or paste it into a file under version control.**

---

## 4.5 Create the GitHub Release

After PyPI publish and the tag push are done, create the matching GitHub Release so the
Releases tab shows the version. Attach only the local `dist/` artifacts that already passed the
Section 2 gates and whose `sha256` matches the files on PyPI — **never rebuild for the Release**.

```bash
gh release create v<ver> \
  --repo AGI-is-going-to-arrive/ahadiff \
  --title "AhaDiff v<ver>" \
  --notes-file notes.md \
  dist/ahadiff-<ver>-py3-none-any.whl \
  dist/ahadiff-<ver>.tar.gz
```

Write user-facing release notes based on the real changes in the tagged commits (highlights,
install steps, links); do not paste raw commit logs or invent metrics.

---

## 5. TestPyPI rehearsal (optional)

For a major packaging change, rehearse on TestPyPI first. Build and gate exactly as in
Section 2, then upload to TestPyPI and install from it in a clean venv.

If TestPyPI does not already have an `ahadiff` project, the first rehearsal must create the
project or resolve any package-name conflict before the install smoke can pass.

```bash
# (re)build + gate the distributions (Section 2 a–c)
cd viewer && pnpm install --frozen-lockfile && pnpm build && cd ..
uv build
python scripts/check_wheel_webui.py dist/*.whl

# upload to TestPyPI
uv publish --publish-url https://test.pypi.org/legacy/ dist/*
# or: python -m twine upload -r testpypi dist/*
```

Install from TestPyPI in a fresh venv. TestPyPI does not mirror PyPI, so allow real
dependencies to come from PyPI via `--extra-index-url`:

```bash
python -m venv /tmp/ahadiff-testpypi
source /tmp/ahadiff-testpypi/bin/activate
python -m pip install --upgrade pip
python -m pip install \
  --index-url https://test.pypi.org/simple/ \
  --extra-index-url https://pypi.org/simple/ \
  ahadiff
ahadiff --version            # expect the release version
deactivate
```

---

## 6. Post-publish verification (against real PyPI)

After publishing to PyPI, confirm a clean install works end to end, including the bundled
WebUI.

```bash
python -m venv /tmp/ahadiff-verify
source /tmp/ahadiff-verify/bin/activate
python -m pip install --upgrade pip

# plain install — no --pre; releases are GA
python -m pip install ahadiff
ahadiff --version            # expect the release version

# serve smoke from an empty dir → packaged WebUI must be served
mkdir -p /tmp/ahadiff-verify-empty
cd /tmp/ahadiff-verify-empty
ahadiff serve --no-browser &
SERVE_PID=$!
sleep 3
curl -fsS http://127.0.0.1:8765/ | head -n 20    # expect the bundled SPA HTML
kill "$SERVE_PID"
cd -
deactivate
```

If `GET /` returns the SPA HTML, the package-internal `ahadiff/_webui` resolution works for end
users and the release is good.

---

## Appendix: source / dev install (contributors)

Not a release step, but for reference — contributors run from a source checkout and build the
dev WebUI separately:

```bash
git clone https://github.com/AGI-is-going-to-arrive/ahadiff
cd ahadiff
uv tool install --editable .
cd viewer && pnpm install && pnpm build    # builds viewer/dist for the dev WebUI
```

In a source checkout, `_resolve_viewer_dist` resolves `viewer/dist` (step 3 of the resolution
order) because `pyproject.toml` `project.name == "ahadiff"` and `src/ahadiff/__init__.py` is
present.
