# Stage 6 Cross-Review Report: Tasks 14.5 / 18 / 19 / 20 / i18n-0 + CI Fix

> Date: 2026-04-24
> Reviewers: Claude Opus 4.6 (orchestrator + independent) / Claude team-reviewer agent / Codex CLI (review) / Codex CLI (adversarial)
> Verdict: **GO after remediation** (original review: 0 Critical, 1 High, 8 Medium, 5 Low)

---

## Review Scope

| Field | Value |
|-------|-------|
| Baseline | `1c3deb39adee45f77902a5805afac3ab5ba9c8e5` |
| HEAD | `a1301a5da1f609768d6fb37a5bd6f528734d51de` |
| Range | `1c3deb3..a1301a5` (8 commits) |
| Working tree | Clean at original review; this follow-up applies the remediation and documentation updates |
| CI status | `completed/success` on HEAD (run 24887881201) |
| llmdoc/ | Absent |

### Commits Under Review

| SHA | Message | Task |
|-----|---------|------|
| `ddfe54e` | Implement task 14.5 serve backend gate | Task 14.5 |
| `9ea5cea` | Fix backend CI runner sqlite gate | CI fix |
| `91242a1` | Use Homebrew Python for backend CI sqlite gate | CI fix |
| `8ccf9c5` | Implement task 19 install targets | Task 19 |
| `0dfba9c` | Implement task 20 github action install | Task 20 |
| `65022bb` | Implement task 18 benchmark suite | Task 18 |
| `a1301a5` | Implement i18n-0 backend locale schema | i18n-0 |
| `00b83f8` | Compact CLAUDE.md from 42.3k to 24.2k chars | Docs |

### Modules Covered

| Module | Files |
|--------|-------|
| `src/ahadiff/serve/` | `__init__.py`, `app.py`, `auth.py`, `middleware.py`, `routes_locale.py`, `routes_runs.py`, `routes_signals.py`, `state.py`, `static.py` |
| `src/ahadiff/install/` | `__init__.py`, `base.py`, `claude.py`, `codex.py`, `common.py`, `gemini.py`, `github_action.py`, `hooks.py`, `opencode.py`, `template_loader.py`, `templates/*.j2` |
| `src/ahadiff/i18n/` | `__init__.py`, `resolver.py`, `schemas.py` |
| `src/ahadiff/eval/` | `benchmark.py` |
| `src/ahadiff/contracts/` | `serve_app.py` |
| `.github/workflows/` | `ci.yml` |
| `src/ahadiff/cli.py` | serve/install/benchmark CLI commands |
| `src/ahadiff/core/config.py` | i18n config additions |
| Tests | `test_serve_app.py`, `test_install.py`, `test_github_action.py`, `test_i18n_resolver.py`, `tests/eval/*.py`, `tests/integration/*.py` |

---

## Post-Remediation Update

This section records the follow-up fixes applied after the original cross-review. It is based on the current source tree and the tests rerun in this session.

### Fixed

| Original item | Current status |
|---------------|----------------|
| **[H-1]** generate workflow env var mismatch | Fixed. `ahadiff-generate.yml.j2` now uses `AHADIFF_PROVIDER_API_KEY`, and tests assert the generated env/check text. |
| **[M-1]** token comparison not constant-time | Fixed. Token validation now uses `hmac.compare_digest()`. |
| **[M-2]** `AHADIFF_LANG` missing | Fixed. `resolve_locale()` now honors `AHADIFF_LANG` before `LANG`. |
| **[M-4]** `concepts.jsonl` symlink read | Fixed. Serve routes now reject/suppress symlinked concept files. |
| **[M-5]** empty `idempotency_key` | Fixed. Contract model now uses `Field(min_length=1)`. |
| **[M-6]** malformed JSON 500 | Fixed. `JSONDecodeError` is handled by the serve app error path. |
| **[M-7]** malformed `finalized.json` array crash | Fixed. Run listing now treats non-object finalized markers as invalid and continues. |
| **[M-8]** verify workflow coverage gate unreachable | Fixed by changing the generated verify workflow to run installed CLI verification (`uvx --from ahadiff ahadiff verify --ci`) instead of source-tree pytest/coverage. |

### Additional real fixes made during remediation

- Generated verify/generate workflows no longer assume the target repository has an AhaDiff source checkout.
- Generate workflow uploads `.ahadiff/` outputs as an artifact.
- Generate workflow exposes provider/model/base-url inputs and still keeps the provider secret in `AHADIFF_PROVIDER_API_KEY`.
- Benchmark validation now checks `ground_truth.md` against manifest `expected_concepts` instead of only checking file existence.
- Concept key normalization no longer collapses distinct Unicode terms into the same ASCII key.
- Lesson and quiz prompt payloads now carry the requested output-language instruction.
- Live judge default model order is now `gpt-5.3-codex-spark,gpt-5.4-mini`; `gpt-5.3-codex-spark` was tested directly.

### Still not fixed / not expanded

| Original item | Current status |
|---------------|----------------|
| **[M-3]** repository CI macOS-only | Not fixed in this session. It remains a cross-platform CI expansion item; Windows also needs a separate SQLite gate solution. |
| **[L-1]** hooks install is Unix-only | Not fixed. Still a v0.2 platform-support item. |
| **[L-2]** Jinja2 `autoescape=False` | Not fixed. Still low risk because current templates pass no user-controlled variables. |
| **[L-3]** full table scan in `_event_for_finalized_run` | Not fixed. Still a performance follow-up. |
| **[L-4]** `put_locale` replaces `ServeState` | Not fixed. Still a low-risk future cleanup. |
| **[L-5]** generated workflows macOS-only | Not fixed. Still intentional for the current SQLite/Homebrew path. |
| Workflow injection finding | Still classified as false positive; no code change made for it. |

---

## Findings

### High (1)

#### [H-1] `ahadiff-generate.yml.j2:23` -- Generate workflow env var name mismatch

- **Source**: Codex review (unique finding)
- **Evidence**: Template sets `AHADIFF_API_KEY: ${{ secrets.AHADIFF_API_KEY }}` (line 23) and checks `test -n "$AHADIFF_API_KEY"` (line 32). But the CLI reads `AHADIFF_PROVIDER_API_KEY` (cli.py lines 697, 1161, 1407, 1657, 2435). All 5 CLI references and all test references (`test_probe.py`) use `AHADIFF_PROVIDER_API_KEY`.
- **Impact**: Users who configure the GitHub secret as `AHADIFF_API_KEY` per the template's instructions will find that `ahadiff learn` silently fails to authenticate -- the API key is set in the environment under the wrong name.
- **Reproduction**: `ahadiff install github-action --layer2 --repo-root .` then trigger workflow_dispatch -- learn will fail with no API key.
- **Recommendation**: Change template `AHADIFF_API_KEY` to `AHADIFF_PROVIDER_API_KEY` in env, check, and error message.
- **Tests to add**: Assert generated YAML env block contains `AHADIFF_PROVIDER_API_KEY`.

---

### Medium (8)

#### [M-1] `serve/auth.py:25` -- Token comparison is not constant-time

- **Source**: All 3 reviewers (Claude C-1 / Codex-adversarial H-1 / Claude-orchestrator M)
- **Evidence**: `if not supplied or supplied != state.token:` uses Python `!=` which short-circuits on the first differing byte.
- **Risk assessment**: Downgraded from Critical/High because: (1) `bind_host` hard-gated to `127.0.0.1` at cli.py:1519-1520; (2) `/api/auth/token` GET endpoint already exposes the full token to any loopback request; (3) token generated with `secrets.token_urlsafe(24)` (192-bit entropy). Timing attack adds no additional attack surface beyond what's already exposed.
- **Recommendation**: One-line fix: `import hmac` + `hmac.compare_digest(supplied, state.token)`.

#### [M-2] `i18n/resolver.py:87` -- `AHADIFF_LANG` environment variable not implemented

- **Source**: Codex-adversarial H-3 / Claude-orchestrator M
- **Evidence**: `resolve_locale()` checks `env_map.get("LANG")` only. `grep -rn AHADIFF_LANG src/` returns zero hits outside cookie handling. CLAUDE.md documents `ENV(AHADIFF_*) -> CLI flag -> ...` as the priority chain.
- **Impact**: Users setting `AHADIFF_LANG=zh-CN` get no effect. Contract violation.
- **Recommendation**: Insert `ahadiff_lang = normalize_locale(env_map.get("AHADIFF_LANG"))` before the `LANG` fallback at resolver.py:87.
- **Tests to add**: `test_resolve_locale_ahadiff_lang_overrides_system_lang()`.

#### [M-3] `.github/workflows/ci.yml:19` -- CI runs only on macOS, no cross-platform matrix

- **Source**: Claude-reviewer W-5 / Claude-orchestrator M
- **Evidence**: `runs-on: macos-latest`, no matrix strategy. Linux/Windows paths, permissions, SQLite versions untested in CI.
- **Recommendation**: v0.2 add `ubuntu-latest` to matrix. Windows requires separate SQLite version gate solution.

#### [M-4] `serve/routes_runs.py:107` -- `concepts.jsonl` read has no symlink guard

- **Source**: Codex review H-1 (unique finding)
- **Evidence**: `get_concepts()` calls `concepts_path.read_text()` without checking `is_symlink()`. Other artifact reads (`_artifact_path_for_read`) properly reject symlinks and validate resolved paths.
- **Impact**: If `.ahadiff/concepts.jsonl` is a symlink (e.g., from a malicious git clone), the target file contents would be served. Mitigated by localhost-only binding.
- **Recommendation**: Add `if concepts_path.is_symlink(): content = ""`.

#### [M-5] `contracts/serve_app.py:93` -- `idempotency_key` accepts empty string

- **Source**: Codex review H-3 (unique finding)
- **Evidence**: `idempotency_key: str` has no `min_length` validator. The `_insert_signal()` helper manually rejects empty keys (line 92-93), but Pydantic-validated routes (`mark_wrong`, `srs_review`, `helpfulness`) pass empty keys through.
- **Impact**: First empty-key signal succeeds; all subsequent empty-key signals silently deduplicate.
- **Recommendation**: `idempotency_key: str = Field(min_length=1)`.

#### [M-6] Multiple routes return 500 on malformed JSON body

- **Source**: Codex review M-1 (unique finding)
- **Evidence**: `put_locale`, `mark_wrong`, `srs_review`, `helpfulness` call `await request.json()` which raises `JSONDecodeError` on malformed input. `JSONDecodeError` is not in `create_app()`'s `exception_handlers` dict (app.py).
- **Recommendation**: Add `JSONDecodeError: _handled_error` to `exception_handlers` in `create_app()`.

#### [M-7] `routes_runs.py:240` -- Corrupted `finalized.json` with JSON array crashes `/api/runs`

- **Source**: Codex review M-2 (unique finding)
- **Evidence**: `_load_valid_finalized_marker()` catches `(JSONDecodeError, OSError, UnicodeDecodeError)` but not `InputError`. `_load_json_object()` raises `InputError` for non-dict JSON. A single `finalized.json` containing `[]` propagates `InputError` to the handler, returning 400 for the entire listing.
- **Recommendation**: Add `InputError` to the except clause at line 243.

#### [M-8] `ahadiff-verify.yml.j2:39` -- Coverage gate 85% unreachable from integration tests alone

- **Source**: Codex review M-3 (unique finding)
- **Evidence**: `--cov=src/ahadiff --cov-fail-under=85` with only `test_learn_pipeline.py -m pinned` (10 tests). These 10 integration tests cannot cover 85% of the entire `src/ahadiff` package.
- **Impact**: Users who install the verify workflow via `ahadiff install github-action` will have CI that always fails the coverage gate.
- **Recommendation**: Narrow coverage scope to `--cov=src/ahadiff/eval --cov=src/ahadiff/git` or lower threshold, or run full unit tests for coverage.

---

### Low (5)

#### [L-1] `install/hooks.py:84,88` -- Hooks install is Unix-only

- **Source**: Claude-reviewer W-3 / Claude-orchestrator L
- **Evidence**: `#!/bin/sh` shebang (line 84) + `path.chmod(path.stat().st_mode | 0o111)` (line 88). No `sys.platform` check in the entire install module.
- **Recommendation**: v0.2 add platform guard; Windows: skip or use `.bat`.

#### [L-2] `install/template_loader.py:8` -- Jinja2 `autoescape=False`

- **Source**: Claude-reviewer C-2 / Codex-adversarial M-1 / Claude-orchestrator L
- **Evidence**: `Environment(autoescape=False, ...)`. All 11 `render_template()` calls across the install module pass zero user-controlled variables (verified via `grep -rn render_template src/ahadiff/install/`). Custom delimiters `[[`/`]]` further isolate.
- **Severity reconciliation**: Claude-reviewer rated Critical, Codex Medium, orchestrator Low. Downgraded to Low because there is no current injection path -- all templates are rendered without variables.
- **Recommendation**: Remove `**values: str` from function signature, or add YAML/shell-safe validation if parameterization is needed later.

#### [L-3] `serve/routes_runs.py:206` -- `_event_for_finalized_run` does full table scan

- **Source**: Claude-reviewer W-1 / Claude-orchestrator L
- **Evidence**: `load_result_events_from_db(db_path)` loads all events, iterates to find match. Called per artifact GET.
- **Recommendation**: Add `load_result_event_by_run_and_id(db_path, run_id, event_id)` with SQL WHERE clause.

#### [L-4] `serve/routes_locale.py:28` -- `put_locale` replaces entire `ServeState`

- **Source**: Claude-reviewer W-2 / Codex-adversarial M-4
- **Evidence**: Non-atomic ServeState replacement under async lock. CPython GIL makes attribute assignment atomic in practice.
- **Recommendation**: v0.2 consider mutable locale holder.

#### [L-5] Generated workflow templates run only on macOS

- **Source**: Claude-orchestrator
- **Evidence**: Both `ahadiff-verify.yml.j2` and `ahadiff-generate.yml.j2` use `runs-on: macos-latest` with Homebrew Python. Users on Linux/Windows repos get macOS-only CI.

---

### False Positive (1)

#### Codex-adversarial H-2 -- GitHub Action workflow injection via `inputs.diff_ref`

- **Claim**: `AHADIFF_DIFF_REF: ${{ inputs.diff_ref }}` in `env:` block allows YAML injection via newline in input.
- **Verdict**: **False positive**.
- **Evidence**: (1) GitHub Actions evaluates `${{ }}` expressions within parsed YAML scalar values -- newlines become part of the env var value, not new YAML keys. (2) The `run:` step uses `"$AHADIFF_DIFF_REF"` (env var indirection with double quotes), not direct `${{ inputs.diff_ref }}` -- bash does NOT perform command substitution on variable expansion results. (3) This is GitHub Security Lab's [recommended safe pattern](https://securitylab.github.com/resources/github-actions-preventing-pwn-requests/) for handling untrusted inputs.

---

## Cross Review Reconciliation

| Finding | Claude Orchestrator | Claude-reviewer | Codex Adversarial | Codex Review | Reconciled |
|---------|:---:|:---:|:---:|:---:|:---:|
| Env var mismatch | -- | -- | -- | **H-2** | **High** |
| Token timing | Medium | **Critical** C-1 | **High** H-1 | -- | **Medium** |
| AHADIFF_LANG missing | Medium | -- | **High** H-3 | -- | **Medium** |
| CI macOS-only | Medium | Warning W-5 | -- | -- | **Medium** |
| concepts.jsonl symlink | -- | -- | -- | **High** H-1 | **Medium** |
| Empty idempotency_key | -- | -- | -- | **High** H-3 | **Medium** |
| JSON decode 500 | -- | -- | -- | Medium M-1 | **Medium** |
| finalized.json array | -- | -- | -- | Medium M-2 | **Medium** |
| Coverage gate 85% | -- | -- | -- | Medium M-3 | **Medium** |
| Jinja2 autoescape | Low | **Critical** C-2 | Medium M-1 | -- | **Low** |
| Workflow injection | -- | -- | **High** H-2 | -- | **False positive** |
| put_locale race | -- | Warning W-2 | Medium M-4 | -- | **Low** |
| Hooks Unix-only | Low | Warning W-3 | -- | -- | **Low** |
| Full table scan | Low | Warning W-1 | -- | -- | **Low** |
| Generated WF macOS | Low | -- | -- | -- | **Low** |

### Severity Override Justifications

| Override | From | To | Reason |
|----------|------|----|--------|
| Token timing | Critical (Claude-reviewer) / High (Codex-adversarial) | Medium | Token already exposed via `/api/auth/token` GET; `bind_host` hard-locked to `127.0.0.1` (cli.py:1519); timing attack adds no additional attack surface |
| Jinja2 autoescape | Critical (Claude-reviewer) | Low | Zero user-controlled variables passed to any template render call (verified: 11 call sites, all `render_template("name.j2")` with no `**values`) |
| Workflow injection | High (Codex-adversarial) | False positive | Env var indirection pattern is GitHub Security Lab recommended safe practice; `${{ }}` in `env:` values does not enable YAML structure injection |
| concepts.jsonl symlink | High (Codex-review) | Medium | Localhost-only server; `.ahadiff/` is runtime-generated, not git-tracked; attack requires user filesystem write access |
| Empty idempotency_key | High (Codex-review) | Medium | Only affects edge case where client sends `""` -- legitimate clients always send proper keys; no data corruption, only silent dedup |

### Unique Findings by Reviewer

| Reviewer | Unique Findings |
|----------|----------------|
| Claude Orchestrator | Generated WF macOS-only (L-5) |
| Claude-reviewer | Benchmark 20-entry gate (Info), duplicate Request import (Info), loose dict casting in signals (Info), json.loads/dumps round-trip (Info), integration test cards.jsonl missing fields (Info) |
| Codex Adversarial | Workflow injection (false positive), auth_token endpoint exposure (Low, by design), symlink TOCTOU (mitigated by checksum) |
| Codex Review | **Env var mismatch (H-1)**, concepts.jsonl symlink (M-4), empty idempotency_key (M-5), JSON decode 500 (M-6), finalized.json array crash (M-7), coverage gate unreachable (M-8) |

---

## Validation Matrix

| Command | Result | Platform | Key Output |
|---------|--------|----------|------------|
| `pytest tests/unit/test_serve_app.py -q` | PASS | macOS | 18 passed |
| `pytest tests/unit/test_install.py -q` | PASS | macOS | 8 passed |
| `pytest tests/unit/test_github_action.py -q` | PASS | macOS | 7 passed |
| `pytest tests/eval -q` | PASS | macOS | 7 passed |
| `pytest tests/integration/test_learn_pipeline.py -m pinned -q` | PASS | macOS | 10 passed |
| `pytest tests/unit/test_i18n_resolver.py tests/unit/test_stage1_task1.py tests/unit/test_git_capture.py tests/unit/test_concepts.py tests/unit/test_claim_verify.py -q` | PASS | macOS | 89 passed |
| `python -m ahadiff benchmark --suite local --output /tmp/...` | PASS | macOS | Suite digest ok, mean 97.08, 14 comparable, 6 degraded excluded |
| `python -m ahadiff install --help` | PASS | macOS | 6 targets displayed |
| `python -m ahadiff install claude --help` | PASS | macOS | Positional arg, shows parent help |
| `python -m ahadiff install github-action --help` | PASS | macOS | Same as above |
| `python -m ahadiff serve --help` | PASS | macOS | port/no-browser/lang params |
| `python -m ahadiff learn --help` | PASS | macOS | --lang param present |
| `pytest tests/unit -q` | PASS | macOS | **455 passed** |
| `pytest tests -q` | PASS | macOS | **472 passed, 1 skipped** (live judge) |
| `ruff check src tests` | PASS | macOS | All checks passed |
| `ruff format --check src tests` | PASS | macOS | 147 files already formatted |
| `pyright` | PASS | macOS | 0 errors, 0 warnings, 0 informations |
| `uv build --wheel` | PASS | macOS | ahadiff-0.1.0a0-py3-none-any.whl |
| `python -m ahadiff --version` | PASS | macOS | ahadiff 0.1.0a0 |
| `uv sync --locked --dev` | PASS | macOS | Stable |
| `AHADIFF_LIVE_LLM_JUDGE=1 pytest tests/live/...` | PASS | macOS | 1 passed; `gpt-5.3-codex-spark` also passed when tested alone |
| `gh run view 24887881201` | PASS | CI | success, headSha=a1301a5 |

### Environment

- Python: 3.13.12
- SQLite: 3.51.0
- pyproject `requires-python`: `>=3.11`
- CI Python: 3.12 (Homebrew)

---

## Cross-Platform Matrix

| Platform | Method | Coverage | Remaining Risks |
|----------|--------|----------|-----------------|
| **macOS** | **Executed** | All 472 non-live tests, live judge smoke, lint, typecheck, wheel, CLI, CI runner | SQLite 3.51.0 via Homebrew; fully verified |
| **Linux** | Static review | pathlib usage confirmed; `os.replace()` atomic write cross-platform | No CI Linux matrix; Homebrew Python step invalid on Ubuntu; system SQLite may not meet >=3.51.3 gate |
| **Windows** | Static review | pathlib usage confirmed; `os.replace()` cross-platform | Hooks chmod/shebang no-op; `#!/bin/sh` not executable; SQLite gate needs conda or manual install; CRLF in patch parsing (existing `\r` preservation logic) |

### CI-Specific Observations

- Current CI: `macos-latest` single-platform only
- Generated verify/generate workflows: also macOS-only
- Node.js 20 deprecation: no impact (CI steps don't depend on Node)
- `uv sync --locked`: stable across platforms (uv native support)
- `requires-python = ">=3.11"` aligns with CI `python@3.12`

---

## Confirmed Security Mitigations

| Attack Vector | Mitigation | Location |
|---------------|-----------|----------|
| Path traversal via `run_id` | `validate_run_id()` regex `^[A-Za-z0-9._-]+$` + reject `.`/`..` | `core/paths.py:107-112` |
| Symlink in artifacts | `is_symlink()` reject + `resolve().relative_to()` | `routes_runs.py:264-272` |
| Finalized marker tampering | Recompute `finalized_artifact_digest()` + compare count + checksum | `routes_runs.py:240-261` |
| Host header injection | Hostname in `{"localhost", "127.0.0.1", "::1"}` + port matching | `middleware.py:14-48` |
| CSRF on write routes | Origin/Referer required for POST/PUT/PATCH/DELETE | `middleware.py:23-31` |
| External network binding | `bind_host` hard-gated to `127.0.0.1` | `cli.py:1519-1520` |
| Token entropy | `secrets.token_urlsafe(24)` = 192-bit entropy | `cli.py:1528` |
| Install overwrite protection | `AHADIFF:GENERATED` marker check before overwrite | `base.py:write_generated_file` |
| Install atomic writes | write-to-temp-then-rename pattern | `base.py:_atomic_write` |
| Manifest tampering | `verify_suite_digest()` SHA-256 over all fixtures + metadata | `benchmark.py` |
| SQL injection | Parameterized queries via Pydantic models | `review/database.py` |

---

## Stage Gate Verdict

### GO after remediation

| Metric | Original count | Current status |
|--------|----------------|----------------|
| Critical | 0 | 0 blocking |
| High | 1 | 0 blocking |
| Medium | 8 | 1 remaining non-blocking expansion item |
| Low | 5 | 5 remaining non-blocking follow-ups |

**Gate rule**: the original blocker **[H-1]** is fixed and re-verified. The other remediated Medium items are fixed. The remaining items are platform expansion / low-risk cleanup and do not block the next session.

---

## Reviewer Metadata

| Reviewer | Type | Duration | Token Usage |
|----------|------|----------|-------------|
| Claude Orchestrator | Independent analysis | ~15 min | (main context) |
| Claude team-reviewer | Background agent | ~4 min | 106k tokens, 52 tool uses |
| Codex CLI (review) | Background agent | ~20 min | 63k tokens, 11 tool uses |
| Codex CLI (adversarial) | Background agent | ~9 min | 85k tokens, 43 tool uses |
| Explore (doc-reader) | Background agent | ~1 min | 102k tokens, 11 tool uses |
