# AhaDiff (知返)

> **Ship with AI. Learn it back.**
>
> Every AI-written git diff becomes a verified Aha lesson — with code-linked evidence, active-recall quizzes, spaced review, and a self-improving quality ratchet.

[中文](./README.md) · [Design docs](./doc/) · [UI prototypes](./ui/)

---

## What it is

**AhaDiff** is a **local-first learning layer for AI coding**.

It's not a PR summary, not a repo wiki, not yet another "code explainer." It reads every git diff and turns the change into:

- A **lesson** with `file:line` evidence chains
- A **claims** ledger where every assertion traces back to a hunk
- A comparable **quality score history** (ratcheted; `review.sqlite` is the single source of truth, `results.tsv` is a human-readable export)

The main line from Stage 0 / Task 0 through Stage 6 now has real shipped artifacts, and Stage 7 i18n signoff has also passed. The current code reliably produces Lesson / Claims / Quiz / Misconception Cards / Cards / Score / Ratchet. The review-flow SRS runtime, serve backend, install targets, GitHub Action templates, benchmark suite, improve-loop core, Task 17 targeted verification, Phase 2.5 runtime, i18n-0 backend, and the `viewer/` React SPA are all landed.

This v1.1 review-fix pass spans backend Python, the `viewer/` frontend, tests, benchmarks, and docs. Backend changes close the watch self-trigger worktree diff mode, harden provider model discovery against SSRF while preserving local provider discovery, expand URL embedded-secret redaction for OAuth query and fragment tokens, strengthen GraphProvenance validation, and guard concepts JSONL export against symlink / reparse targets. Frontend changes add Dashboard LLM Calls / Weak Concepts, ConceptGraph 500+ / 1000+ large-graph warnings with a 1000+ explicit render confirmation, a11y heading / tab-panel / nested-interactive fixes, accent contrast tokens, GraphifyCard V6 fidelity, and Skills focus restoration. This cleanup also aligns the Dashboard KPI E2E contract with the five-card UI, adds a real-click retry for the Diff claim selection E2E path, and adds the frontend CI workflow.

The previous v1.1 review-fix pass verified the changed surface: `UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run --frozen --no-sync pytest tests/unit -x -q` = `2055 passed`; `pytest tests/integration -q` = `11 passed`; `pytest tests/eval -q` = `9 passed`; `ruff check src tests`, `ruff format --check src tests`, and `pyright` passed; `uv build --wheel` passed; `cd viewer && pnpm typecheck`, `pnpm vitest run` (`21 files, 227 tests passed`), and `pnpm build` passed; full cross-browser Playwright = `2000 passed, 10 skipped`; `AHADIFF_LIVE_LLM_MODELS=gpt-5.5 pytest tests/live/test_llm_judge_live.py -q` = `1 passed`; Graphify 10k benchmark parse avg was `172.399ms`, peak memory was `42.435MiB`, and the gate passed. Coverage was not rerun in this pass.

The 2026-05-09 follow-up makes path-scoped learn an actual end-to-end path: `ahadiff learn --changed-path`, watch-triggered learn, `POST /api/learn` / `POST /api/learn/estimate`, and Learn Mode Dialog all pass the path scope down to capture. Capture only accepts it for staged / unstaged / working-tree inputs and treats glob characters as literal pathspec text. The frontend now uses EventSource task progress first with polling fallback; Learn Mode Dialog explains path scope, uncommon sources, and the three run options; the PWA manifest now has same-origin `id` / `scope` plus 192/512 PNG icons.

Targeted follow-up verification: backend path-scope regressions = `6 passed`; `cd viewer && pnpm vitest run tests/unit/learn-mode-dialog.test.ts tests/unit/manifest.test.ts src/state/learn-store.test.ts` = `3 files, 87 tests passed`; `cd viewer && pnpm typecheck` and `pnpm build` passed; `cd viewer && pnpm test:e2e:real-serve` = `1 passed`. The full backend unit suite, full Playwright matrix, live judge, and coverage were not rerun in this follow-up.

The second same-day integrations follow-up turns install tooling from a display surface into a protected WebUI write loop: `GET /api/install/targets` still returns install commands, uninstall commands, manifest previews, and `manifest_hash`; the new `POST /api/install/{target}/preview`, `POST /api/install/{target}`, and `POST /api/install/{target}/uninstall` routes write only for the repo that started `ahadiff serve`, require `confirmed_manifest_hash` plus `X-AhaDiff-Token`, and keep the existing Origin / Referer write gate, localhost-only boundary, and repo write lock. The shared install write layer now also guards no-follow, regular-file, reparse, and symlink-parent cases. Skills and Settings Integrations can preview, install, uninstall, show pending/success/error states, and re-detect after writes; Settings, Concepts, and Review deep links are also consumed by the target pages.

Second integrations follow-up verification: `UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run --frozen --no-sync pytest tests/unit/test_routes_install.py -q` = `19 passed`; `UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run --frozen --no-sync pytest tests/unit/test_install.py -q` = `37 passed`; `ruff check src tests`, `ruff format --check src tests`, and `pyright` passed; `cd viewer && pnpm typecheck` passed; `cd viewer && pnpm vitest run` = `22 files, 236 tests passed`; `cd viewer && pnpm build` passed; `cd viewer && pnpm exec playwright test tests/e2e/walkthrough.spec.ts -g "Skills|Settings integrations|Deep links" --reporter=line` = `75 passed`. No install / uninstall write was executed against the real current repo; write verification used temporary test repos and browser mocks. The full backend unit suite, live judge, and coverage were not rerun in this integrations follow-up.

The third same-day P1 read-only follow-up turns three browser surfaces into product paths: the Concepts page now has a Ledger tab backed by `GET /api/concepts/ledger`, with cursor pagination, run filtering, and `?tab=` / `?run=` / `?focus=` hash sync; Run Detail now has Score / Judge / Artifacts tabs, and `GET /api/run/{id}/judge` reads the `judge.json` artifact, with JudgeReport accepting both string and array notes; Ratchet now has a read-only Improve Preview tab backed by `GET /api/improve/preflight`, showing repo state, available anchor/baseline runs, provider status, mutable prompts, and existing sessions without starting a worktree write. The review-fix pass also tightened preflight finalized-marker checks, session JSON symlink/reparse/hardlink/oversize guards, untracked prompt dirty detection, frontend hash sync, run-filter races, strict Zod schemas, narrow-viewport wrapping, and accent contrast.

Third P1 follow-up verification: targeted backend route tests = `18 passed`; full backend unit suite = `2088 passed`; `ruff check src tests`, `ruff format --check src tests`, and `pyright` passed; `cd viewer && pnpm typecheck` passed; `cd viewer && pnpm vitest run` = `23 files, 245 tests passed`; `cd viewer && pnpm build` passed; the three P1 E2E specs across the full project matrix = `390 passed`; the specified mobile projects = `52 passed`; Concepts / Ratchet targeted axe-core audits = `2 passed`. Integration tests, eval tests, live judge, and coverage were not rerun in this P1 follow-up, and no real improve write was executed.

The 2026-05-10 review follow-up closes local diagnostics and browser surfaces: serve now has write-token-protected `POST /api/graph/refresh` and `POST /api/db/check`. The graph refresh route re-imports the Graphify artifact inside the repo write lock and validates the imported path; the DB check route uses a read-only DB check to report schema, `quick_check`, and event/card counts without initializing an empty database. Run Detail now has a Concepts tab that appears only when the run has `concepts.jsonl`; `?tab=concepts` falls back to Overview for runs without that artifact. Concepts now has a Graph refresh button, Onboarding shows DB check, and Provider placeholder i18n, LearnModeDialog / RatchetChart a11y, plus several container-query / 599px narrow-screen CSS paths are synced.

The same-day frontend review-fix closes the current uncommitted viewer / CI changes: `tokens.css` now has 13 compatibility aliases plus `color-scheme: dark`; Ratchet / Diff / Topbar / Skills / ClaimInspector / Onboarding / LearnModeDialog / SearchOverlay / Settings received dark-mode, container-query fallback, forced-colors, and narrow-screen fixes; Dashboard now shows stable concepts / last-run KPI; Run Detail adds metadata rows and localized degraded flags; Settings adds audit pagination, race cleanup, and a per-model usage table; SearchOverlay table filter chips now pass the `tables` parameter to `/api/search` and support ArrowLeft / ArrowRight / ArrowUp / ArrowDown / Home / End keyboard switching. Frontend CI now runs all 11 Chromium desktop specs plus Firefox desktop smoke/a11y.

Frontend review-fix verification: `cd viewer && pnpm typecheck` passed; `cd viewer && pnpm vitest run` = `23 files, 245 tests passed`; `cd viewer && pnpm build` passed; `cd viewer && pnpm exec playwright test tests/e2e/ --project=chromium-desktop --reporter=line` = `166 passed`; `cd viewer && pnpm exec playwright test tests/e2e/smoke.spec.ts tests/e2e/a11y.spec.ts --project=webkit-desktop --reporter=line` = `38 passed`; `cd viewer && pnpm exec playwright test tests/e2e/ --project=chromium-mobile --reporter=line` = `166 passed`; `UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run pytest tests/unit` = `2090 passed`; `ruff check src tests`, `ruff format --check src tests`, and `pyright src/ahadiff` passed; i18n parity = `EN:969 zh-CN:969 match:True`; `git diff --check` passed. Integration tests, eval tests, live judge, coverage, and wheel build were not rerun in this follow-up, and no real improve write was executed.

> Code Wiki explains a repo. AhaDiff teaches you what changed — and verifies every claim against the diff.

## Why

AI writes code faster, but developers know less about what they actually understood. "Vibe coding" sprints ahead; humans need to come back:

1. **AI ships, the understanding has to come back to humans** — a commit message isn't enough.
2. **Every claim must have evidence** — no hallucinated functions, no fabricated causality.
3. **Knowledge should compound** — when the same concept is touched again, the wiki should record evolution and backlinks.
4. **Quality should be comparable** — replace "looks fine" with an immutable evaluation bundle and a git ratchet.

## Core Philosophy (N-File Contract)

Extends the Karpathy / autoresearch three-file contract into an N-file variant:

| File | Who edits | Role |
|------|-----------|------|
| `program.md` | Human | Natural-language state machine for the improve loop |
| evaluation bundle | **Immutable** | `evaluator.py` + `rubric.py` + `rubric.yaml` + `gates.py` + `deterministic.py` (5 files, locked as a unit) |
| `prompts/*.md` | Agent | The improve loop edits only allowlisted generation prompts; `eval_judge.md` is a judge prompt resource, not part of that writable set |

LOOP: edit → commit → evaluate → keep if better, reset if worse → write to `review.sqlite` (single source of truth; `results.tsv` is an export view).

## Quickstart

The commands below match the current CLI. In a source checkout, use `uv run ahadiff ...`; after wheel / pipx installation, use `ahadiff ...` directly.

```bash
pipx install ahadiff

# Initialize .ahadiff/ for the current repo
ahadiff init
ahadiff doctor
ahadiff config show --resolved

# Learn the latest commit
ahadiff learn --last

# Learn a commit range
ahadiff learn HEAD~1..HEAD

# Learn staged changes
ahadiff learn --staged

# Learn unstaged worktree changes; include untracked files when needed
ahadiff learn --unstaged
ahadiff learn --unstaged --include-untracked

# Learn only selected paths from the current worktree; repeat for more paths
ahadiff learn --unstaged --include-untracked --changed-path src/app.py
ahadiff learn --changed-path src/app.py --changed-path viewer/src/App.tsx

# Learn from a patch file, URL patch, or directory comparison
ahadiff learn --patch change.diff
ahadiff learn --patch-url "https://example.com/change.diff"
ahadiff learn --compare old.py new.py
ahadiff learn --compare-dir old/ new/

# Review and browse
ahadiff quiz <run_id>
ahadiff review
ahadiff mark <claim_id> wrong
ahadiff serve
ahadiff serve --port 8765 --no-browser
ahadiff serve --watch

# Background watch mode (requires the watchdog extra)
ahadiff watch --debounce 2 --cooldown 30

# Ratcheted self-improvement; requires an existing finalized run and provider configuration
ahadiff improve --suite local --rounds 6
```

In a source checkout, use the equivalent local commands:

```bash
uv sync --locked --dev
uv run python -m ahadiff --version
uv run python -m ahadiff learn --last
```

When configuring a remote or local OpenAI-compatible provider, do not write real keys into commands, README files, manifests, or git-tracked files. Store only the environment-variable name. `provider test` sends a small probe request and persists the provider into `.ahadiff/config.toml`.

```bash
export AHADIFF_PROVIDER_BASE_URL="https://api.example.com/v1"
export AHADIFF_PROVIDER_API_KEY="<provider-api-key>"

ahadiff provider test \
  --name gpt55 \
  --provider-class openai_responses \
  --base-url "$AHADIFF_PROVIDER_BASE_URL" \
  --model gpt-5.5 \
  --api-key-env AHADIFF_PROVIDER_API_KEY \
  --privacy-mode explicit_remote

ahadiff learn --last --provider gpt55 --model gpt-5.5 --privacy-mode explicit_remote
```

The real LLM judge smoke is opt-in. To use GPT-5.5, pass it explicitly through environment variables; do not hardcode keys or real endpoints into docs:

```bash
AHADIFF_LIVE_LLM_JUDGE=1 \
AHADIFF_LIVE_LLM_API_KEY="$AHADIFF_LIVE_LLM_API_KEY" \
AHADIFF_LIVE_LLM_BASE_URL="$AHADIFF_LIVE_LLM_BASE_URL" \
AHADIFF_LIVE_LLM_MODELS="gpt-5.5" \
pytest tests/live/test_llm_judge_live.py -q
```

## AI Tool and Automation Installs

Use `--dry-run --manifest` first to see the exact file writes:

```bash
ahadiff install --detect
ahadiff install claude --dry-run --manifest

ahadiff install <target>
ahadiff uninstall <target>
```

The 13 targets write to these paths:

| target | command | write path |
|---|---|---|
| `aider` | `ahadiff install aider` | marked section in `CONVENTIONS.md` |
| `claude` | `ahadiff install claude` | `.claude/skills/ahadiff/SKILL.md` + marked section in `CLAUDE.md` |
| `cline` | `ahadiff install cline` | `.clinerules/ahadiff.md` |
| `codex` | `ahadiff install codex` | marked section in `AGENTS.md` |
| `continue` | `ahadiff install continue` | `.continue/rules/ahadiff.md` |
| `copilot` | `ahadiff install copilot` | marked section in `.github/copilot-instructions.md` |
| `cursor` | `ahadiff install cursor` | `.cursor/rules/ahadiff.mdc` |
| `gemini` | `ahadiff install gemini` | marked section in `GEMINI.md` |
| `github-action` | `ahadiff install github-action` | `.github/workflows/ahadiff-verify.yml`; with `--layer2`, also writes `.github/workflows/ahadiff-generate.yml` |
| `hooks` | `ahadiff install hooks` | git hooks path, usually `.git/hooks/post-commit` + `.git/hooks/pre-push`; Windows is rejected in v0.1 |
| `opencode` | `ahadiff install opencode` | marked section in `AGENTS.md` + `.opencode/agents/ahadiff.md` |
| `roo` | `ahadiff install roo` | `.roo/rules/ahadiff.md` |
| `windsurf` | `ahadiff install windsurf` | `.windsurf/rules/ahadiff.md` |

These targets currently generate rule files, hooks, or GitHub workflows. Tests cover template rendering, writes, overwrite protection, detection, and uninstall behavior; they do not launch each IDE/CLI to prove the tool loads the generated files. `hooks` is a non-blocking reminder, not an automatic `learn` runner. The GitHub Action verify workflow exits successfully with “no run artifacts found” when there are no `.ahadiff/runs` artifacts to verify.

In the WebUI, Skills and Settings → Integrations use the protected serve API for these same targets. The browser previews the manifest first and receives a hash; install / uninstall must send that hash back as `confirmed_manifest_hash` with the local write token. The endpoint writes only for the repo that started `ahadiff serve`; it does not accept an arbitrary repo path from the browser.

Advanced / maintenance commands are available, but they are meant for maintainers, CI, or users who understand the state files they touch:

```bash
# improve / targeted finalize
ahadiff improve --suite local --rounds 6
ahadiff improve --resume <session_id>
ahadiff db finalize-targeted <run_id>

# scoring, CI verification, and export
ahadiff score <run_id>
ahadiff verify <run_id>
ahadiff verify --ci
ahadiff export-results

# benchmark / DB / Graphify / concepts derived cache
ahadiff benchmark --suite local
ahadiff db check
ahadiff db backup
ahadiff db restore <backup_path>
ahadiff db import-results results.tsv --i-understand-this-is-lossy
ahadiff graph status
ahadiff graph import
ahadiff graph refresh
ahadiff concepts list
ahadiff concepts verify
ahadiff concepts sync
ahadiff concepts export
ahadiff concepts rollback --dry-run
ahadiff maint clean-orphans --dry-run
```

Current output layout:

```text
.ahadiff/
├─ config.toml           # Per-repo config
├─ review.sqlite         # Single source of truth (SRS/results/signals)
├─ concepts.jsonl        # Repo-global concept ledger for git-backed runs
├─ results.tsv           # Human-readable export rebuilt from review.sqlite
├─ runs/<run_id>/
│  ├─ patch.diff
│  ├─ metadata.json
│  ├─ line_map.json
│  ├─ symbols.json
│  ├─ artifact_set.json
│  ├─ before_text_by_path.json
│  ├─ after_text_by_path.json
│  ├─ claims.raw.jsonl   # Raw LLM claim candidates
│  ├─ claims.jsonl       # Verifiable assertions
│  ├─ score.json         # 8-dimension score + verdict
│  ├─ judge.json         # Optional LLM judge score, written when judge_provider is configured
│  ├─ finalized.json     # Publish marker for the run
│  ├─ concepts_local.jsonl   # Run-local concept ledger for non-git inputs (when needed)
│  ├─ lesson/
│     ├─ lesson.full.md
│     ├─ lesson.hint.md
│     ├─ lesson.compact.md
│     ├─ misconception.md
│     └─ not_proven.md
│  └─ quiz/
│     ├─ quiz.jsonl      # open-answer rows; review_card_id may be absent before cards exist
│     ├─ misconception_cards.jsonl
│     └─ cards.jsonl     # Only written for PASS / CAUTION runs, and backfills review_card_id
├─ improve/
│  ├─ <session_id>.json  # improve session state, including phase25_attempted
│  └─ wt/<12hex>-rN/     # temporary worktree kept for pending conflicts or Phase 2.5
├─ audit.jsonl           # LLM call audit log
├─ audit.private.jsonl   # strict_local local-only audit (gitignored)
├─ ahadiff.lock          # portalocker file lock
```

.ahadiffignore            # Repo-root path filter rules

## 8-Dimension Rubric

| # | Dimension | Weight | Hard gate |
|---|-----------|--------|-----------|
| 1 | Accuracy | 20 | < 14 → FAIL |
| 2 | Evidence | 18 | < 12 → FAIL |
| 3 | Diff Coverage | 14 | — |
| 4 | Learnability | 14 | — |
| 5 | Quiz Transfer | 10 | — |
| 6 | Spec Alignment | 10 | — |
| 7 | Conciseness | 8 | — |
| 8 | Safety & Privacy | 6 | Critical → FAIL |

Three verdicts: **PASS** ≥ 80 / **CAUTION** 60–80 / **FAIL** < 60.

## Repository Layout

```text
ahadiff/
├─ AhaDiff Warm v6.html         # Latest UI reference template
├─ AhaDiff-Blueprint.html       # 8-layer architecture visualization (i18n / VCR / 50+ CCs)
├─ AhaDiff-Competitors-Research.html  # Competitor matrix + 5 moats
├─ doc/                         # Design docs (Chinese)
│  ├─ contract-freeze.md        # Stage 0 architecture authority
│  ├─ ahadiff设计思路.md          # [ARCHIVED] Early architecture snapshot
│  ├─ 知返ahadiff改名后的后续方案.md  # [ARCHIVED] Rename transition plan
│  └─ AhaDiff_frontend_design_v1.1_revised.md  # Frontend design manual (v0.1=React 19+Vite)
├─ src/ahadiff/contracts/       # Stage 0 minimal importable and serializable contracts surface
├─ src/ahadiff/core/            # Stage 1 / Task 1 scaffold + task runner / watcher + Phase 0 JSON/SQLite safety helpers
├─ src/ahadiff/safety/          # Stage 1 / Task 2 safety primitives
├─ src/ahadiff/llm/             # Layer 1.5 / Task 7 provider + probe
├─ src/ahadiff/git/             # Stage 2 / Task 5-6 diff capture + structuring
├─ src/ahadiff/claims/          # Stage 2 / Task 8 claim extraction + verification + runtime
├─ src/ahadiff/lesson/          # Stage 3 / Task 8.5 + 9 learnability + lesson + helpfulness/transfer
├─ src/ahadiff/quiz/            # Stage 3 / Task 10 open-answer quiz + cards + misconception cards
├─ src/ahadiff/wiki/            # Stage 3 / Task 10 concepts ledger
├─ src/ahadiff/graphify/        # Current-branch Graphify backend: models/parser/matcher/linker/slicer/search/freshness plus concepts/FTS wiring
├─ src/ahadiff/eval/            # Stage 3 / Task 11-12 evaluator + ratchet + results + optional LLM judge
├─ src/ahadiff/serve/           # Task 14.5 + v0.2 local serve API (incl. search/audit/usage/mastery/learning/tasks)
├─ src/ahadiff/install/         # Task 19/20 install targets + hooks no-follow + GitHub Action templates
├─ src/ahadiff/i18n/            # i18n-0 locale resolver / prompt language helper
├─ src/ahadiff/review/          # Task 15 + v0.2 review.sqlite schema / FSRS-6 / migration chain
├─ src/ahadiff/prompts/         # Prompt resources packaged into the wheel, including eval_judge.md
├─ prompts/                     # Lesson / claim / quiz / eval judge prompt templates
├─ src/ahadiff/improve/         # Stage 5 / Task 16/17 improve loop, targeted verify, Phase 2.5
├─ benchmarks/                  # Task 18 local benchmark fixtures + manifest + scripts + results
├─ tests/unit/                  # Stage 0-6 and i18n-0 unit tests
├─ tests/eval/                  # benchmark suite tests
├─ tests/integration/           # pinned integration fixtures
├─ tests/live/                  # Opt-in real LLM judge smoke
├─ viewer/                      # React 19 + Vite + Zustand + vanilla CSS frontend (13 pages / 45 production page+component TSX / 38 page+component CSS / 969 i18n keys / v1.1 gate: Vitest 227 passed + full Playwright 2000 passed / 10 skipped; 05-09 follow-up: targeted Vitest 87 passed + real-serve E2E 1 passed; integrations follow-up: Vitest 236 passed + target Playwright 75 passed; P1 follow-up: Vitest 245 passed + P1 E2E 390 passed; 05-10 frontend review-fix: backend unit 2090 + Vitest 245 + Chromium desktop E2E 166 + WebKit smoke/a11y 38 + Chromium mobile E2E 166)
├─ ui/                          # HTML prototypes v1–v6 (design history)
└─ CLAUDE.md                    # Project AI context index
```

## Status

**Stage 0 / Task 0, Stage 1 Task 1/2, Layer 1.5 / Task 7, Stage 2 / Task 5/6/8, Stage 3 / Task 8.5/9/10/11/12, Stage 4 / Task 15, Stage 5 / Task 16/17, Stage 6 / Task 18/19/20, and the i18n-0 backend are now landed.** The current codebase already has:

- the `ahadiff learn` main path for git and non-git capture (`--patch` / `--compare`), followed by learnability gating, `claims.raw.jsonl -> claims.jsonl`, and full / hint / compact lesson output; worktree inputs also support repeatable `--changed-path` to learn only selected repo-relative paths
- `ahadiff quiz` for a minimal interactive quiz loop backed by `quiz.jsonl`, with source-claim and file-line evidence printed back to the user
- the quiz artifact chain writes both `quiz.jsonl` and `misconception_cards.jsonl`; scored PASS / CAUTION runs generate `cards.jsonl` and backfill `review_card_id`, while open-answer rows without `review_card_id` still render correctly in the viewer; git-backed runs write the repo-global `concepts.jsonl`, while non-git runs write `concepts_local.jsonl`
- `ahadiff score`, `ahadiff verify`, and `ahadiff export-results`, backed by `review.sqlite` as the single source of truth and `results.tsv` as an export view
- `ahadiff review`, `ahadiff mark <claim_id> wrong`, and `ahadiff db {backup,restore,check,import-results,finalize-targeted}` for the landed review.sqlite review / signals / result-events / lossy-import / targeted-finalize path
- `ahadiff serve`: the localhost-only serve backend is available. Read routes expose finalized runs only; write routes require token plus Origin/Referer checks. `/api/auth/token` requires a same-origin browser signal, keeps GET compatibility, and supports POST bootstrap. The current route surface is 61 concrete `/api/*` routes plus one `/api/{rest_of_path:path}` catchall, with `/healthz` outside the API surface. `POST /api/learn` has an in-memory 10 req/min sliding-window rate limit with `retry_after` / `Retry-After`; both `POST /api/learn` and `POST /api/learn/estimate` support `changed_paths` for worktree path scoping; Concepts Ledger, Run Detail Judge/Concepts, and Improve Preflight now have read-only routes; `POST /api/graph/refresh` re-imports the Graphify artifact inside the repo write lock and validates the imported path; `POST /api/db/check` returns schema/quick_check/event/card counts through a read-only DB check without initializing an empty database; install targets now have `GET /api/install/targets`, preview, install, and uninstall routes, with writes requiring a token plus confirmed manifest hash and applying only to the current serve repo; `/api/tasks*` is stable product API, and the viewer now consumes `/api/tasks/{id}/progress` SSE first with polling fallback; `/api/watch/status` remains internal/unstable. `GET/PUT /api/config` now includes `learnability_threshold` and `desired_retention`, and serve runtime reads config from the active workspace.
- `ahadiff install` / `ahadiff uninstall`: all 13 targets are available (Aider / Claude / Cline / Codex / Continue / Copilot / Cursor / Gemini / GitHub Action / hooks / OpenCode / Roo / Windsurf); the real write paths are listed in the install target table above. Hooks are POSIX-shell targets and are explicitly rejected on Windows in v0.1. Existing hook files are now read through no-follow regular-file checks, so symlink / reparse-point hook paths are rejected. The shared write layer also rejects unsafe reparse / symlink-parent paths. Generated GitHub workflows cover macOS + Linux; Windows remains deferred. The generate workflow uses `AHADIFF_PROVIDER_API_KEY` and uploads `.ahadiff/` outputs as an artifact. The WebUI Skills / Settings integration surfaces reuse the same install target contract: they preview the manifest first, then confirm install / uninstall with a hash plus token, and never accept an arbitrary repo path from the browser
- `ahadiff benchmark`: the local benchmark manifest, 20 eval fixtures, 11 pinned integration fixtures, and `ground_truth.md` consistency checks are available; the 11th fixture is a graph-present smoke fixture proving a Graphify-style `graph.json` is covered by the suite digest, parses through the real parser, and materializes `graphify_context.json` / `artifact_set.json` in the fixture path. The production per-run Graphify context path is covered by `test_git_capture.py`; this fixture is not proof of full real large Graphify export fidelity
- the repo also now ships repo-level Backend CI / `nightly-eval` / `release` workflows: PR runs unit + pinned integration (`ubuntu py311/py312 + macOS py312`) with a separate Windows runtime guard, and the release gate now blocks on `doctor`, wheel install smoke, and coverage `>= 85%`. This pass also adds `.github/workflows/frontend-ci.yml`: frontend PR/push checks run `pnpm typecheck`, `pnpm vitest run`, `pnpm build`, all 11 Chromium desktop E2E specs, and Firefox desktop smoke/a11y. `pyproject.toml` also now carries `watchdog` / `tree-sitter` optional extras and `pytest-cov` as a dev dependency; `ahadiff watch`, `serve --watch`, and `/api/watch/status` are landed, while `/api/watch/status` remains internal/unstable. `tree-sitter` is no longer just optional wiring: the runtime consumer is now connected at the symbol-extraction layer for JS/TS/TSX + Go + Java + Rust + PHP + Ruby + C#; Python stays AST-first, unsupported languages still fall back to regex / section header, and no downstream lesson / quiz / claims business logic changed
- The Phase 0 follow-up is now reflected in the branch: the contract authority, the `safe_sqlite_connect` SQLite connection helper, reparse/hardlink protections, serve CORS and `X-Frame-Options` headers, CLI cold start, and local baseline scripts all have matching implementation
- i18n-0: the locale resolver supports cookie / Accept-Language / CLI / config / `AHADIFF_LANG` / `LANG` fallback, and lesson/quiz prompt payloads carry the requested output-language instruction
- `ahadiff improve --suite local --rounds N`, which currently supports only `--suite local`. It selects a baseline from an existing finalized run, edits only an allowlisted prompt in a git worktree, replays the same diff, and rescores the candidate; the candidate must improve the target dimension plus `accuracy`, `evidence`, and `safety_privacy`, and hard gates must still pass. Passing candidates are cherry-picked back when possible and recorded as `event_type=improve` / `status=targeted_verify`; non-improving rounds are recorded as `discard`; cherry-pick conflicts leave a pending worktree without finalizing the run; two consecutive `discard` rounds in the same session trigger one Phase 2.5 worktree rewrite
- `src/ahadiff/eval/{rubric,gates,deterministic,evaluator,results,ratchet}.py` for the 8-dimension scorer, hard gates, result persistence, ratchet selection, and export rebuilds
- `src/ahadiff/review/{database,scheduler,schemas,signal}.py` for review.sqlite schema / migration, FSRS-6 scheduling, the review queue, learning signals, and the review CLI backend
- `src/ahadiff/improve/{loop,program,targeted,rewrite}.py` for improve sessions, the immutable improve_program prompt, worktree isolation, the 5 mutable-prompt allowlist, replay-learn, targeted verification, Phase 2.5 triggering, cherry-pick ordering, session validation, and pending-worktree resume guards
- runtime resource lookup that works in both source checkout and installed wheel mode for `eval_bundle_version`, `prompt_version`, and packaged lesson prompts
- `keep_final` is still a manual full 8-dimension recheck via `ahadiff db finalize-targeted <event_id>`; the improve loop does not auto-promote it. The `viewer/` React SPA still has 13 pages. The current learning surface is now closer to real use: SRSCard / Review / Quiz show only Good / Hard / Wrong in the v0.1 UI; the Topbar Learn Run button opens Learn Mode Dialog with 10 capture modes and preflight confirmation, and working / unstaged / staged modes can take one Path scope entry per line; the Dashboard empty state can open the same Learn Mode Dialog; Lesson recommends compact / hint / full from weak concepts and stability; Settings is now 7 tabs (Account / Provider / Capture / Privacy / Audit / Preferences / Integrations), with Preferences owning language, appearance, `learnability_threshold`, and `desired_retention`; Provider / Capture / Integrations `?tab=` links initialize and switch tabs; the Provider tab has distinct aria labels for generate/judge provider and model controls; Integrations supports preview/install/uninstall, command copy, manifest write-path preview, and re-detect after writes; Skills also supports server-provided install/uninstall commands, manifest preview/hash, pending/success/error states, and re-detect after writes; Review consumes `?card=`; Concepts is a Ledger / Graph dual-tab page, consumes `?focus=`, `?run=`, and `?tab=`, and can refresh the Graphify import from the Graph tab; Ratchet downloads `results.tsv` through a token-header blob request and has a read-only Improve Preview tab; Run Detail has Overview / Score / Judge / Concepts / Artifacts tabs, with Concepts shown only when the run has `concepts.jsonl`; Onboarding shows DB check independently from doctor; ConceptGraph now has only Graph / List views, defaults large graphs to List while still allowing Full graph, supports full-graph pan/zoom without hard viewport bounds, and strips local home/system prefixes from displayed node file paths; Dashboard loads runs / ratchet / stats / heatmap / learning through `Promise.allSettled`, so a learning-effectiveness failure no longer breaks the main page; long-running task progress now uses SSE first with polling fallback.

This round also closed several runtime edges: `prompt_version` still tracks AhaDiff's own prompt resources instead of any target-workspace `prompts/`; lesson JSON parsing skips schema-mismatched example blocks before accepting a real answer, and claims / quiz / misconception cards / LLM judge now choose schema-valid answers across provider envelopes, fenced JSON, JSONL, example blocks, and partially truncated JSON; the lesson/quiz chain is now wired into `learn`; lesson-generation failures now clean up newly written `claims.raw.jsonl` / `claims.jsonl`, `quiz/`, and `concepts_local.jsonl` half-artifacts; successful `learn` runs now write a `learn` event plus `score.json`; when `judge_provider` is configured, they also write the LLM judge's 8-dimension result to `judge.json`; manual `score` / `verify` still do not contaminate the learn baseline; `ReviewCard` now validates `last_rating` and `card_state/stale_reason`; fake quiz artifacts no longer pass as a complete Stage-3 result. The pinned integration fixture was also tightened after that: tests now write `symbols.json`, generate `cards.jsonl` through `generate_cards_for_run()`, and validate every row as `ReviewCard`, so hand-written partial cards can no longer bypass the production contract. Task 15 is also fully hardened in this round: legacy `cards` schemas now migrate `stale_reason` explicitly, schema-invalid `cards.jsonl` is downgraded to warnings, repeated regenerate runs no longer leave old active cards in the due queue, `regenerate --only quiz` restores the previous quiz/cards artifacts if `evaluate_run` fails and deletes stale `cards.jsonl` plus marks active cards `stale + staleness_unknown` on `FAIL`, lossy TSV import now runs as a single-connection whole-batch import with rollback on bad rows or duplicate identities, `rollback_result_event` now does delete + export-row selection in one connection, and a plain DB connect no longer creates parent directories silently on typo paths. Task 16/17 now covers the `lesson_hint.md` allowlist entry, session-id path validation, a 30-minute replay timeout, paired prompt temp+replace writes, non-conflict cherry-pick failure handling, no `finalized.json` for discard or pending-conflict runs, pending conflicts excluded from the next baseline, volatile staged/unstaged replay from the saved `patch.diff`, shorter worktree paths, a `--rounds` cap of 20, null-byte rejection, Ctrl+C after a completed round no longer appending a second crash event, targeted verification, one Phase 2.5 trigger per session, and OpenAI-compatible provider endpoint normalization. This cache-key hardening also closes the API-version boundary for LLM calls: different `api_family_version` values under the same `api_family` now produce different cache keys, so compatible gateways or API-version changes do not reuse stale results.

Current minimal verification:

```bash
source .venv/bin/activate && pytest tests/unit -q
source .venv/bin/activate && ruff check src tests
source .venv/bin/activate && pyright
source .venv/bin/activate && uv build --wheel
source .venv/bin/activate && python -m ahadiff quiz --help
source .venv/bin/activate && python -m ahadiff review --help
source .venv/bin/activate && python -m ahadiff improve --help
source .venv/bin/activate && python -m ahadiff db check --help
source .venv/bin/activate && python -m ahadiff install github-action --help
```

The live LLM judge smoke is opt-in. Its default model order is `gpt-5.3-codex-spark,gpt-5.4-mini`; each model tries OpenAI Responses before Chat Completions. To use GPT-5.5, set `AHADIFF_LIVE_LLM_MODELS` explicitly as shown in the quickstart:

```bash
AHADIFF_LIVE_LLM_JUDGE=1 \
AHADIFF_LIVE_LLM_API_KEY="$AHADIFF_LIVE_LLM_API_KEY" \
AHADIFF_LIVE_LLM_BASE_URL="$AHADIFF_LIVE_LLM_BASE_URL" \
AHADIFF_LIVE_LLM_MODELS="gpt-5.3-codex-spark,gpt-5.4-mini" \
pytest tests/live/test_llm_judge_live.py -q
```

Previous full gate (2026-05-08): `UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run --frozen --no-sync pytest tests/unit -x -q` = `2055 passed`; `UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run --frozen --no-sync pytest tests/integration -q` = `11 passed`; `UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run --frozen --no-sync pytest tests/eval -q` = `9 passed`; `UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run --frozen --no-sync ruff check src tests` passed; `UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run --frozen --no-sync ruff format --check src tests` passed; `UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run --frozen --no-sync pyright` = `0 errors`; `UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv build --wheel` passed; `cd viewer && pnpm typecheck` passed; `cd viewer && pnpm vitest run` = `21 files, 227 tests passed`; `cd viewer && pnpm build` passed; `cd viewer && pnpm exec playwright test --reporter=line` = `2000 passed, 10 skipped`; `AHADIFF_LIVE_LLM_MODELS=gpt-5.5 ... pytest tests/live/test_llm_judge_live.py -q` = `1 passed`; Graphify 10k benchmark gate passed (parse avg `172.399ms`, peak `42.435MiB`). Coverage was not rerun in this pass.

This follow-up (2026-05-09) reran only the changed surface: backend path-scope regressions `6 passed`; frontend Learn Mode Dialog / manifest / learn-store targeted Vitest `87 passed`; `pnpm typecheck` and `pnpm build` passed; real-serve Playwright contract `1 passed`. The second integrations follow-up also reran `test_routes_install.py = 19 passed`, `test_install.py = 37 passed`, `ruff check src tests`, `ruff format --check src tests`, `pyright`, full frontend Vitest `236 passed`, `pnpm typecheck`, `pnpm build`, and the Skills / Settings integrations / Deep links target Playwright run `75 passed`. The third P1 read-only follow-up reran targeted backend route tests `18 passed`, full backend unit `2088 passed`, ruff/format/pyright, full frontend Vitest `245 passed`, typecheck/build, the three P1 E2E specs across the full project matrix `390 passed`, specified mobile projects `52 passed`, and Concepts/Ratchet targeted axe-core audits `2 passed`. The 2026-05-10 review follow-up reran DB check targeted backend tests `2 passed`, full backend unit `2090 passed`, ruff/format/pyright, viewer typecheck, full frontend Vitest `245 passed`, viewer build, Run Detail + media targeted Playwright `500 passed, 10 skipped`, specified walkthrough/smoke/a11y/cross-browser/learn-task/media E2E `1760 passed, 10 skipped`, and `git diff --check`. The 2026-05-10 frontend review-fix then reran viewer typecheck, full frontend Vitest `245 passed`, viewer build, full Chromium desktop E2E `166 passed`, WebKit desktop smoke/a11y `38 passed`, full Chromium mobile E2E `166 passed`, backend unit `2090 passed`, ruff/format/pyright, i18n parity `969/969`, and `git diff --check`. Integration tests, eval tests, live judge, coverage, and wheel build were not rerun in the frontend review-fix. No real improve write was executed.

Roadmap:

- [ ] `v0.1` (MVP): CLI + Lesson + Evaluator + Ratchet end-to-end + React 19 WebUI (`ahadiff serve`) + 8 LLM Providers + 8 diff capture modes (incl. --unstaged / git show) + 13 install targets + i18n + stage gates
- [ ] `v0.2`: --compare-dir + --patch-url + 7 IDE install targets + watchdog incremental regeneration + section-level helpfulness + Team features (done: backend Gates 0-6 + medium APIs + helpfulness / learning transfer + misconception cards + Graphify backend foundations with concept linking / FTS / provenance / perf gate + watch mode + path-scoped learn + graph refresh API + DB check API + 13 install targets + install target WebUI safety loop + provider/model settings + Learn Mode Dialog + `/api/learn` rate limit + DNS pinning + LLM judge + current frontend learning-surface closure: three-button SRS UI, automatic scaffolding, retention settings, Ratchet TSV, ConceptGraph Graph/List views with unbounded full-graph interaction, Concepts Ledger, Run Detail judge artifact browser, Run Detail concepts artifact, Ratchet Improve Preview, Dashboard learning-metric isolation and empty-state Learn CTA, three-state sidebar, Diff large-file render budget, Dashboard source filters, container-query hardening, Settings/Lesson/Skills/Review heading and aria cleanup, Settings/Concepts/Review deep-link consumption, CSP hash / z-index token / favicon / runtime status / queue-state / signals / idempotency fallback hardening; remaining: Team / real large-repo signoff evidence / deeper V6 frontend signoff)
- [ ] `v1.0`: PWA offline-shell signoff + public benchmark suite (done: VitePWA build, manifest `id`/`scope`, SVG + 192/512 PNG icons, manifest unit test; remaining: offline-shell E2E and public benchmark signoff)

## Inspirations

- **karpathy/autoresearch** — N-file contract (three-file variant) + git ratchet
- **alchaincyf/darwin-skill** — 8-dimension rubric + Phase 2.5 rewrite
- **Evol-ai/SkillCompass** — PASS/CAUTION/FAIL + weakest-dimension-first
- **ZJU-REAL/SkillZero** — helpfulness-driven retention + compact context
- **safishamsi/graphify** — repo-level graph overlay
- **karpathy/llm-wiki** gist — persistent compounding wiki

## Design Axioms

1. **Evidence first** — every claim must trace back to `file:line`
2. **Learning over summary** — quizzes and review beat pretty summaries
3. **Local-first trust** — three privacy tiers (`strict_local` / `redacted_remote` / `explicit_remote`), defaults to `strict_local`
4. **Paper-like seriousness** — academic feel; no cool-purple SaaS gradients
5. **One accent per style** — warm paper background + a single accent color

## License

[MIT](./LICENSE)

---

> AhaDiff / 知返 — Δ知 ↺
