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
- A comparable **quality score history** (ratcheted; `review.sqlite` is the single source of truth, while `results.tsv` and JSON exports are views)

The main line from Stage 0 / Task 0 through Stage 6 now has real shipped artifacts, and Stage 7 i18n signoff has also passed. The current code reliably produces Lesson / Claims / Quiz / Misconception Cards / Cards / Score / Ratchet. The review-flow SRS runtime, serve backend, install targets, GitHub Action templates, benchmark suite, improve-loop core, Task 17 targeted verification, Phase 2.5 runtime, i18n-0 backend, and the `viewer/` React SPA are all landed.

This v1.1 review-fix pass spans backend Python, the `viewer/` frontend, tests, benchmarks, and docs. Backend changes close the watch self-trigger worktree diff mode, harden provider model discovery against SSRF while preserving local provider discovery, expand URL embedded-secret redaction for OAuth query and fragment tokens, strengthen GraphProvenance validation, and guard concepts JSONL export against symlink / reparse targets. Frontend changes add Dashboard LLM Calls / Weak Concepts, ConceptGraph 500+ / 1000+ large-graph warnings with a 1000+ explicit render confirmation, a11y heading / tab-panel / nested-interactive fixes, accent contrast tokens, GraphifyCard V6 fidelity, and Skills focus restoration. This cleanup also aligns the Dashboard KPI E2E contract with the five-card UI, adds a real-click retry for the Diff claim selection E2E path, and adds the frontend CI workflow.

The previous v1.1 review-fix pass verified the changed surface: `UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run --frozen --no-sync pytest tests/unit -x -q` = `2055 passed`; `pytest tests/integration -q` = `11 passed`; `pytest tests/eval -q` = `9 passed`; `ruff check src tests`, `ruff format --check src tests`, and `pyright` passed; `uv build --wheel` passed; `cd viewer && pnpm typecheck`, `pnpm vitest run` (`21 files, 227 tests passed`), and `pnpm build` passed; full cross-browser Playwright = `2000 passed, 10 skipped`; `AHADIFF_LIVE_LLM_MODELS=gpt-5.5 pytest tests/live/test_llm_judge_live.py -q` = `1 passed`; Graphify 10k benchmark parse avg was `172.399ms`, peak memory was `42.435MiB`, and the gate passed. Coverage was not rerun in this pass.

The 2026-05-12 Phase 2 follow-up continues after that security pass with the local learning loop surfaces: `review.sqlite` is now schema v10, with deterministic concept health lint for orphan / stale / contradicted concepts plus `concept_status` / `concept_lint_runs`; `ahadiff export preview` and `POST /api/export/preview` generate a local static preview bundle and deterministic zip manifest; the read-only MCP server now has a seventh tool, `ask_lesson`, which performs local lesson-fragment token search and does not call an LLM; Challenge loop is disabled by default and must be opted in, the CLI has only `build` / `status`, while WebUI/serve provide build/get/advance/abort/review/feedback, and review performs deterministic diff-gap comparison without executing code; APKG export now uses packaged CSS, but GUIDs still use `genanki.guid_for(card_id)` and are not namespaced yet. The frontend adds Challenge pages, the Export modal, Concept health badge/filtering, Ratchet locale-aware score/date formatting, and best-effort frontend API error redaction. The follow-up adversarial review then hardened Challenge rebuild/review atomicity, finite manifest scores, export-preview noindex / injection recheck / stale-cleanup TOCTOU handling, the MCP `ask_lesson` output contract and read-only path guards, concept-lint JSONL reads and path normalization, and non-finite review score rejection. Actual verification: `uv run pytest tests/unit -x -q` = `2409 passed`; `uv run pytest tests/integration -q` = `11 passed`; `uv run pytest tests/eval -q` = `9 passed`; `uv run ruff check src tests`, `uv run ruff format --check src tests`, and `uv run pyright` passed; `cd viewer && pnpm typecheck && pnpm vitest run && pnpm build` passed, with Vitest at `32 files, 326 tests passed`; i18n scalar keys are `1262/1262`; `git diff --check HEAD` passed. Live judge, wheel build, full Playwright, and remote GitHub Actions were not rerun in this pass.

The 2026-05-13 review-fix only touched that pass's backend contract and frontend learning surfaces. Backend `RunDetail` now has optional `learnability`, and missing `lesson` / `claims` / `quiz` artifacts return 404; the learnability projection accepts only finite numbers, real booleans, and `list[str]` reasons. Frontend search keeps the backend `primary_key` as the stable id, while graph-node results use plain-text `focusText` for Concepts Ledger focus; SearchOverlay still honors safe `#/` hrefs, dispatches `hashchange` manually only for same-hash navigation, and restores focus reliably on WebKit when the overlay closes. ConceptGraph keeps the Canvas renderer, but now preserves forced-colors visibility, matches focus by id/name/ledger key, and keeps focused selection when switching large graphs back to Graph view. ConceptLedger adds graph links, focus highlight, reduced-motion handling, and programmatic row focus. Lesson distinguishes run detail 404 from skipped lesson artifacts and clears stale claims when claims are missing. Actual verification in this pass covered only the changed surface: targeted backend `pytest` = `199 passed`, targeted `pyright` = 0 errors, targeted `ruff check` / `ruff format --check` passed; `cd viewer && pnpm typecheck && pnpm vitest run` = `33 files, 336 tests passed`; `cd viewer && pnpm exec playwright test tests/e2e/search-overlay.spec.ts --reporter=line` = `60 passed`; i18n scalar keys are `1271/1271`; `git diff --check HEAD` passed. Integration tests, eval tests, live judge, wheel build, viewer build, full Playwright, and remote GitHub Actions were not rerun in this pass.

The later 2026-05-13 frontend V6 alignment review-fix stays inside `viewer/src/` and covers the frontend shell, page styling, and learning-surface details. AppShell / Sidebar / Topbar now share the imported `components.css`; both Dashboard empty and full states disable global shortcuts while the Learn dialog is open; Landing and Lesson now expose `data-page` so scoped V6 CSS applies. Lesson adds the three-column TOC / prose / rail reader, an IntersectionObserver fallback, TOC `aria-current`, Scaffolding tabpanel wiring, and long-text wrapping. Settings / Dashboard / ProviderCard close forced-colors, reduced-motion, and long-error fallback gaps, and Landing feature cards now use responsive CSS instead of a fixed inline grid. Actual verification: `cd viewer && pnpm typecheck` passed; `cd viewer && pnpm vitest run` = `33 files, 336 tests passed`; `cd viewer && pnpm build` passed; i18n scalar keys are `1273/1273`; `git diff --check HEAD` passed. Backend tests, integration tests, eval tests, live judge, wheel build, full Playwright, and remote GitHub Actions were not rerun in this pass.

The 2026-05-14 Lesson reader follow-up again changes only the `viewer/` learning surface. The Lesson header now shows verdict / score, a print button, and a local "mark as learned" state. The right rail is derived from the current run's lesson, claims, concepts, and quiz artifacts: claim summary, wiki memory, evidence, learning progress, scaffolding, not-proven, rejected, and source lists are data-backed, not fixed static copy. Claims still render from the backend artifact status as verified / weak / not_proven / rejected; concepts come from the run-level concepts artifact; quiz only shows the question count and concept coverage that can be read from the artifact. "Mark as learned" is currently browser-session UI state only and does not write to `review.sqlite`. Actual verification: `cd viewer && pnpm typecheck` passed; `cd viewer && pnpm vitest run` = `33 files, 336 tests passed`; `cd viewer && pnpm build` passed; i18n scalar keys are `1297/1297`; `cd viewer && AHADIFF_VIEWER_E2E_PORT=5187 pnpm exec playwright test tests/e2e/walkthrough.spec.ts --project=chromium-desktop --grep "Lesson — content, scaffolding tabs, claims, evidence panel" --reporter=line` = `1 passed`. Backend tests, integration tests, eval tests, live judge, wheel build, full Playwright, and remote GitHub Actions were not rerun in this pass.

The 2026-05-14 Ratchet transparency follow-up wires the Ratchet page to real data. `GET /api/ratchet/transparency` projects recent rows directly from `review.sqlite/result_events`, and projects benchmark summaries from `benchmarks/manifest.json` plus `.ahadiff/benchmarks/local-report.json`; it requires `X-AhaDiff-Token`, and missing DB tables, empty events, corrupt benchmark files, symlinks, reparse points, hardlinks, or oversized files return empty data or warnings instead of mock fallback. The frontend consumes this route through Zod schemas and `apiFetch`: the results tab renders an inline `results.tsv` table from the transparency payload first and falls back to paged history only if transparency is unavailable. The Benchmark tab shows suite, digest, entry counts, language/group counts, comparable/degraded counts, mean score, claim rate, and sample entries. Phase 2.5 is shown according to the current improve semantics: two consecutive `discard` rounds can trigger it once per session, the final event is still `targeted_verify` or `discard`, and `note_json.phase25` marks the rewrite instead of a standalone `phase25_rewrite` event. Actual verification: targeted Ratchet transparency backend tests `5 passed`; the backend Ratchet/Phase2.5/benchmark target group `153 passed`; `ruff check`, `ruff format --check`, and `pyright` passed; viewer typecheck, Vitest `336 passed`, and build passed; Ratchet walkthrough Playwright `30 passed`; ratchet benchmark media-features Playwright `15 passed`; i18n scalar keys `1338/1338`; real serve/browser without mocks showed 33 real result rows and the `ahadiff-local-v1` benchmark; GPT-5.5 live judge smoke `1 passed`; a separate synthetic eval_judge smoke wrote an 8-dimension `judge.json`. Full Playwright, wheel build, and remote GitHub Actions were not rerun in this pass.

The 2026-05-14 Warm v6 / Blueprint follow-up turns the current uncommitted work into a verified baseline. The main learning pages outside Settings / Ratchet / Graph keep moving toward `AhaDiff Warm v6.html`, but the static template is not treated as product truth. Diff now has Unified / Split modes; Split keeps old/new claim markers and jumps separate, and ClaimInspector labels old/new references so the same file and line cannot be confused. Dashboard spec-alignment KPI now reads the finalized run's `score.json`; corrupt files, symlinks, reparse points, hardlinks, and oversized files degrade instead of using historical result-event averages as a substitute. `/api/graph/concepts?focus=` includes the focused node even when it is outside the page limit, Concepts Ledger graph links use real `graphify_node_id`, stale graph links are dropped, quiz generation is constrained to `guided` / `recall` / `transfer`, and generated review cards are imported into `review.sqlite` after learn. This pass also rechecked `AhaDiff-Blueprint.html`: the eight-layer architecture, diff capture, eight-dimension evaluation, Guide/Onboarding, export, MCP, and opt-in Challenge surfaces are backed by current code; unsupported items such as Amp/Jules/Junie install targets, a CherryIN provider, a DOMPurify dependency, and a fixed 29-step flow are not documented as implemented. Actual verification: backend unit `2434 passed`, integration `11 passed`, eval `9 passed`; `ruff check`, `ruff format --check`, `pyright`, and wheel build passed; viewer typecheck, Vitest `344 passed`, and build passed; full Playwright `2735 passed, 10 skipped`; i18n scalar keys `1392/1392`; `git diff --check HEAD` passed. Live judge and remote GitHub Actions were not rerun in this pass.

The later same-day follow-up updates the truth for this current uncommitted set: `learn --open` is now wired into the CLI. It prints the run lesson URL after learn and only attempts to open the browser when `serve.bind_host=127.0.0.1` and the process is not headless/CI. `--against-spec` writes `spec_alignment.json`; `--spec-semantic-review` is an explicit opt-in LLM semantic review layer, and failures mark that semantic review degraded instead of blocking the deterministic artifact. `.ipynb` git diffs now render a cell-aware source view that ignores outputs/metadata; parse failures fall back to the normal diff path and record degradation. Graphify-backed runs now write `graphify_signoff.json`, checking source/imported artifact presence, digest, counts, and freshness, then marking signoff as passed / degraded / unavailable. Serve adds per-run `spec-alignment` and `graphify-signoff` artifact routes, while `/api/spec/alignment` aggregates requirement, degraded-artifact, semantic-review, and disagreement counts. The benchmark runner also includes `bench_serve_read_routes.py`, covering runs / concepts / graph / search / ratchet transparency read-route p95 gates. Run Detail shows spec alignment and Graphify signoff, and the Dashboard/Ratchet/SearchOverlay mocks and schemas are synced. Actual verification: backend unit `2477 passed`, integration `11 passed`, eval `9 passed`; `ruff check`, `ruff format --check`, `pyright`, and wheel build passed; viewer typecheck, Vitest `345 passed`, and build passed; after fixing the smoke spec-alignment mock, full Playwright `2855 passed, 10 skipped`; i18n scalar keys `1439/1439`; `git diff --check HEAD` passed; after loading `.env.local`, live semantic alignment smoke `1 passed`. Remote GitHub Actions were triggered and monitored, but GitHub refused to start the jobs because of account billing / spending-limit status, so no runner logs were produced and this is not counted as a code-validation pass.

The 2026-05-15 review/test follow-up closes the current uncommitted set. When `/api/signals/srs-review` or `/api/review/rate` cannot find an active review card, the route now lazy-imports `runs/*/quiz/cards.jsonl` under the repo write lock and retries. That import skips symlink/reparse and bad UTF-8 artifacts, and an empty `cards.jsonl` marks old active cards from the same run as stale. Learn Step 10 now tries `graphify update <repo>`, force-imports the refreshed `.ahadiff/graphify/graph.json` on success, and only then appends concepts, so the current run can link to the updated graph. If the Graphify CLI is missing but `graphify-out/graph.json` already exists, AhaDiff keeps the older optional import path; if the CLI exists but update fails, it degrades and does not import a stale graph as if it refreshed. Graphify source import uses the parser's 50 MiB cap, `/api/graph/refresh` gets the 600s timeout only on the exact route, and date-only `git --since` values are normalized to UTC midnight to avoid platform parsing differences. The follow-up review also makes low-learnability skips publish a minimal run: result event, `score.json`, and `finalized.json`; if artifact publishing fails, the just-written result event is rolled back. Direct CLI `ahadiff learn` now matches the serve/orchestrator path. Quiz generation now has `quiz.quiz_question_count`, default 3 and range 1-10, wired through CLI, prompt, serve config API, and Settings. Frontend fixes keep open-answer Review cards unpeeked, add Diff file summary Prev/Next controls plus unified/split `+`/`-` markers, claim auto-scroll, and narrow/forced-colors styling, and restore run detail 404 on Lesson to fetch failed while keeping missing lesson artifacts as skipped. Actual verification: backend unit `2502 passed`, integration `11 passed`, eval `9 passed`; `ruff check`, `ruff format --check`, `pyright`, wheel build, viewer typecheck, Vitest `350 passed`, viewer build, full Playwright `2855 passed, 10 skipped`, i18n scalar keys `1447/1447`, and `git diff --check HEAD` passed. Live judge and remote GitHub Actions were not rerun in this pass.

A later same-day frontend polish pass only touches the `viewer/` Diff and Welcome learning entry surfaces: Diff claim selection no longer uses the accent ring and now uses a softer row-level band; unified/split claim-dot hover/focus, add/del selected-row backgrounds, the dot legend, and the selected-line hint are synced. The Welcome lesson demo now groups H2 sections into collapsible panels, preserves pre-H2 preamble content, falls back to flat prose when there is no H2, caps the demo panel height, and links to the latest finalized Lesson when one exists. A new `renderMarkdownCollapsible` unit test covers H2 grouping, preamble, no-H2 fallback, and H3 content inside the current section. Actual verification: `cd viewer && pnpm typecheck` passed; `cd viewer && pnpm vitest run` = `35 files, 353 tests passed`; `cd viewer && pnpm build` passed; `UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run pytest tests/unit -q` = `2502 passed`; i18n scalar keys are `1449/1449`; `git diff --check HEAD` passed. Integration tests, eval tests, ruff/format/pyright, wheel build, full Playwright, live judge, and remote GitHub Actions were not rerun in this frontend-polish pass.

The following Learn Mode / Diff aggregation hardening pass closes security, a11y, and dense-claim rendering edges. `git --since` / `--author` now reject leading dashes and control characters in both the capture layer and serve submit/estimate routes. `against_spec` still accepts only local files inside the current workspace. Learn Mode Dialog path scope rejects `..`, absolute paths, Windows drive/UNC forms, control characters, and more than 500 paths; `patch_url` accepts only http/https URLs without embedded credentials; revision rejects overlong, leading-dash, and control-character values. Closing the dialog aborts estimate / pending learn requests, pending payload state no longer stores patch bodies or patch URLs, and the dialog exposes `aria-busy`, a live region, and print hiding. Diff Viewer now aggregates multiple claims on the same line into one highest-severity dot with a count badge when needed; the default click target matches the dot color. Actual verification: `UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run pytest tests/unit/test_routes_learn.py tests/unit/test_git_capture.py -q` = `199 passed`; `cd viewer && pnpm run test -- --run learn-store learn-mode-dialog Diff` = `35 files, 360 tests passed`; `cd viewer && pnpm run typecheck` and `pnpm run build` passed; `uv run ruff check src tests`, `uv run ruff format --check src tests`, `uv run pyright`, and `uv build --wheel` passed; backend unit `2513 passed`; integration+eval `20 passed`; i18n scalar keys are `1454/1454`; `git diff --check HEAD` passed. Full Playwright, live judge, and remote GitHub Actions were not rerun in this pass.

The 2026-05-09 follow-up makes path-scoped learn an actual end-to-end path: `ahadiff learn --changed-path`, watch-triggered learn, `POST /api/learn` / `POST /api/learn/estimate`, and Learn Mode Dialog all pass the path scope down to capture. Capture only accepts it for staged / unstaged / working-tree inputs and treats glob characters as literal pathspec text. The frontend now uses EventSource task progress first with polling fallback; Learn Mode Dialog explains path scope, uncommon sources, and the three run options; the PWA manifest now has same-origin `id` / `scope` plus 192/512 PNG icons.

Targeted follow-up verification: backend path-scope regressions = `6 passed`; `cd viewer && pnpm vitest run tests/unit/learn-mode-dialog.test.ts tests/unit/manifest.test.ts src/state/learn-store.test.ts` = `3 files, 87 tests passed`; `cd viewer && pnpm typecheck` and `pnpm build` passed; `cd viewer && pnpm test:e2e:real-serve` = `1 passed`. The full backend unit suite, full Playwright matrix, live judge, and coverage were not rerun in this follow-up.

The second same-day integrations follow-up turns install tooling from a display surface into a protected WebUI write loop: `GET /api/install/targets` still returns write commands, remove commands, manifest previews, and `manifest_hash`; the new `POST /api/install/{target}/preview`, `POST /api/install/{target}`, and `POST /api/install/{target}/uninstall` routes write only for the repo that started `ahadiff serve`, require `confirmed_manifest_hash` plus `X-AhaDiff-Token`, and keep the existing Origin / Referer write gate, localhost-only boundary, and repo write lock. The shared install write layer now also guards no-follow, regular-file, reparse, and symlink-parent cases. Settings → AI Tool Guidance (the deep link is still `?tab=integrations`) now handles preview, project guidance writes, project guidance removal, pending/success/error states, and re-detect after writes; Guide only lists the workflow, commands, and supported integration targets, then deep-links to Settings. Settings, Concepts, and Review deep links are also consumed by the target pages.

Second integrations follow-up verification: `UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run --frozen --no-sync pytest tests/unit/test_routes_install.py -q` = `19 passed`; `UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run --frozen --no-sync pytest tests/unit/test_install.py -q` = `37 passed`; `ruff check src tests`, `ruff format --check src tests`, and `pyright` passed; `cd viewer && pnpm typecheck` passed; `cd viewer && pnpm vitest run` = `22 files, 236 tests passed`; `cd viewer && pnpm build` passed; `cd viewer && pnpm exec playwright test tests/e2e/walkthrough.spec.ts -g "Skills|Settings integrations|Deep links" --reporter=line` = `75 passed`. No install / uninstall write was executed against the real current repo; write verification used temporary test repos and browser mocks. The full backend unit suite, live judge, and coverage were not rerun in this integrations follow-up.

The third same-day P1 read-only follow-up turns three browser surfaces into product paths: the Concepts page now has a Ledger tab backed by `GET /api/concepts/ledger`, with cursor pagination, run filtering, and `?tab=` / `?run=` / `?focus=` hash sync; Run Detail now has Score / Judge / Artifacts tabs, and `GET /api/run/{id}/judge` reads the `judge.json` artifact, with JudgeReport accepting both string and array notes; Ratchet now has a read-only Improve Preview tab backed by `GET /api/improve/preflight`, showing repo state, available anchor/baseline runs, provider status, mutable prompts, and existing sessions without starting a worktree write. The review-fix pass also tightened preflight finalized-marker checks, session JSON symlink/reparse/hardlink/oversize guards, untracked prompt dirty detection, frontend hash sync, run-filter races, strict Zod schemas, narrow-viewport wrapping, and accent contrast.

Third P1 follow-up verification: targeted backend route tests = `18 passed`; full backend unit suite = `2088 passed`; `ruff check src tests`, `ruff format --check src tests`, and `pyright` passed; `cd viewer && pnpm typecheck` passed; `cd viewer && pnpm vitest run` = `23 files, 245 tests passed`; `cd viewer && pnpm build` passed; the three P1 E2E specs across the full project matrix = `390 passed`; the specified mobile projects = `52 passed`; Concepts / Ratchet targeted axe-core audits = `2 passed`. Integration tests, eval tests, live judge, and coverage were not rerun in this P1 follow-up, and no real improve write was executed.

The 2026-05-10 review follow-up closes local diagnostics and browser surfaces: serve now has write-token-protected `POST /api/graph/refresh` and `POST /api/db/check`. The graph refresh route re-imports the Graphify artifact inside the repo write lock and validates the imported path; the DB check route uses a read-only DB check to report schema, `quick_check`, and event/card counts without initializing an empty database. Run Detail now has a Concepts tab that appears only when the run has `concepts.jsonl`; `?tab=concepts` falls back to Overview for runs without that artifact. Concepts now has a Graph refresh button, Onboarding shows DB check, and Provider placeholder i18n, LearnModeDialog / RatchetChart a11y, plus several container-query / 599px narrow-screen CSS paths are synced.

The 05-10 frontend review-fix closes that day's viewer / CI changes: `tokens.css` now has 13 compatibility aliases plus `color-scheme: dark`; Ratchet / Diff / Topbar / Skills / ClaimInspector / Onboarding / LearnModeDialog / SearchOverlay / Settings received dark-mode, container-query fallback, forced-colors, and narrow-screen fixes; Dashboard now shows stable concepts / last-run KPI; Run Detail adds metadata rows and localized degraded flags; Settings adds audit pagination, race cleanup, and a per-model usage table; SearchOverlay table filter chips now pass the `tables` parameter to `/api/search` and support ArrowLeft / ArrowRight / ArrowUp / ArrowDown / Home / End keyboard switching. Frontend CI now runs all 11 Chromium desktop specs plus Firefox and WebKit desktop smoke/a11y.

Frontend review-fix verification: `cd viewer && pnpm typecheck` passed; `cd viewer && pnpm vitest run` = `23 files, 245 tests passed`; `cd viewer && pnpm build` passed; `cd viewer && pnpm exec playwright test tests/e2e/ --project=chromium-desktop --reporter=line` = `166 passed`; `cd viewer && pnpm exec playwright test tests/e2e/smoke.spec.ts tests/e2e/a11y.spec.ts --project=webkit-desktop --reporter=line` = `38 passed`; `cd viewer && pnpm exec playwright test tests/e2e/ --project=chromium-mobile --reporter=line` = `166 passed`; `UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run pytest tests/unit` = `2090 passed`; `ruff check src tests`, `ruff format --check src tests`, and `pyright src/ahadiff` passed; i18n parity = `EN:969 zh-CN:969 match:True`; `git diff --check` passed. Integration tests, eval tests, live judge, coverage, and wheel build were not rerun in this follow-up, and no real improve write was executed.

This compatibility and route-coverage follow-up continued from the then-current uncommitted code: Backend PR CI now includes `tests/eval` in the PR gate; frontend CI installs Chromium / Firefox / WebKit, keeps Chromium desktop full E2E plus Firefox smoke/a11y, and adds WebKit smoke/a11y. The viewer now centralizes `formatBytes` / `formatCompactNumber` in `viewer/src/utils/format.ts`; LearnTaskBanner and ProviderCard format byte/token counts with the current locale, and old Intl runtimes that ignore compact notation fall back to deterministic K/M/B output. The ConceptGraph implementation at that point measured the initial SVG width before using `ResizeObserver`; LearnTaskBanner has a plain-color fallback before its `color-mix()` gradient; Topbar renders `⌘K` on macOS and `Ctrl+K` elsewhere; at that point Settings and Diff skipped clipboard writes when the browser API was unavailable, while the later v1.1 security / cross-platform follow-up replaced this with the shared `copyToClipboard()` fallback. Backend route tests now cover review, signals, tasks, DB check, search, and `/api/concepts/weak` auth, empty-db, schema, valid-payload, and invalid-payload paths.

Compatibility follow-up verification: `UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run --frozen --no-sync pytest tests/unit -q` = `2130 passed`; `UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run --frozen --no-sync ruff check src tests` passed; `UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run --frozen --no-sync ruff format --check src tests` = `248 files already formatted`; `UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run --frozen --no-sync pyright src` = `0 errors, 0 warnings, 0 informations`; `cd viewer && pnpm typecheck` passed; `cd viewer && pnpm vitest run` = `24 files, 250 tests passed`; `cd viewer && pnpm vite build` passed; i18n parity = `969/969`; `cd viewer && pnpm exec playwright test tests/e2e/a11y.spec.ts --project=chromium-desktop --reporter=line` = `17 passed`; `cd viewer && pnpm exec playwright test tests/e2e/smoke.spec.ts --project=chromium-desktop --reporter=line` = `21 passed`; the real browser check covered Dashboard, Settings Provider/Integrations, Diff anchors, Concepts Graph, Topbar, Learn, Review, Search, and a 375px mobile viewport, with all 10 scenes passing; `git diff --check` passed. Integration tests, eval tests, live judge, coverage, wheel build, and remote GitHub Actions workflows were not rerun in this follow-up.

This error / locale / i18n hardening follow-up stabilizes API errors around 27 `ErrorCode` values and `{error_code,error,status,details?}` payloads: `AUTH_REQUIRED` remains 401, while loopback / write-origin denials remain 403. Serve run and artifact reads now resolve locale per request, and `PUT /api/locale` persists the choice to `.ahadiff/config.toml`. Claim extraction now receives the resolved `output_lang`, just like lesson and quiz generation. Git-facing code resolves `git` through `shutil.which("git")`, reports missing git clearly, bounds hook subprocesses with a timeout, and trims only CR/LF so paths with spaces survive. The generated verify workflow now includes Windows in the matrix; Linux-only SQLite build steps are guarded by `runner.os == 'Linux'`, and Windows runs a CLI load smoke while `verify --ci` stays non-Windows. The frontend maps `ApiError.errorCode` through `errors.*`, and byte/token formatting now uses localized `Format.*` labels.

This follow-up verification: targeted backend regression = `455 passed`; full backend unit suite = `2136 passed`; `ruff check src tests`, `ruff format --check src tests`, and `pyright` passed; `cd viewer && pnpm vitest run` = `253 passed`; `pnpm typecheck` and `pnpm build` passed; i18n scalar keys = `1011/1011`, `errors.*` covers `27/27` error codes, and `Format.*` covers 6 formatting labels; `git diff --check` passed. Integration tests, eval tests, live judge, coverage, wheel build, Playwright, and remote GitHub Actions workflows were not rerun in this follow-up, and no real improve write was executed.

This Skills → Guide follow-up replaces the old Skills page with a lighter Guide page: `/#/guide` shows the daily learning workflow, core commands, setup commands, advanced/maintenance commands, and all 13 supported integration targets; `/#/skills` now redirects with replace semantics to `/#/guide`. Guide does not import the install API and does not run install/uninstall; real preview / write / remove stays in Settings → AI Tool Guidance. Onboarding command snippets now use the shared `CommandBlock`; copy buttons have localized labels, prefer the Clipboard API, fall back to `execCommand('copy')`, and clean up the fallback textarea on error paths. Onboarding examples now split POSIX and PowerShell commands and use placeholder API keys only. Actual verification in this pass: Guide-targeted Playwright `7 passed`; `cd viewer && pnpm vitest run` = `253 passed`; `pnpm typecheck` and `pnpm build` passed; all Guide keys are used; the only old Skills reference left is the `/skills` redirect test; Guide/Onboarding/CommandBlock contain no real key, endpoint, or local absolute path examples; `git diff --check` passed. Backend tests, integration tests, eval tests, live judge, coverage, wheel build, full Playwright, and remote GitHub Actions workflows were not rerun in this pass.

The 2026-05-11 Onboarding / Guide QA follow-up only changes the frontend learning entry points and tests: it adds the shared `DiagnosticRow` component for doctor / DB check status icons, `sr-only` text, and `aria-live="polite"`; reshapes Onboarding stepper, doctor, DB check, preview, and CTA sections; adds coverage for HashRouter anchor scrolling, reduced motion, forced colors, 414px narrow screens, and renderToStaticMarkup assertions; keeps the SYSTEM sidebar order as Welcome → Get Started → Guide → Settings; shows Guide maintenance commands with `--dry-run` by default; restores a visible light-mode focus ring; and changes the WebKit Dashboard run-link E2E to assert URL after click instead of treating hash-SPA load waiting as a product failure.

This QA follow-up verification: full backend unit suite `2136 passed`; `ruff format --check src tests`, `ruff check src tests`, `pyright`, `uv build --wheel`, `python -m ahadiff --version`, and `ahadiff doctor` passed; `cd viewer && pnpm install --frozen-lockfile`, `pnpm typecheck`, `pnpm lint`, `pnpm vitest run` = `25 files, 268 tests passed`, `pnpm build`, and full Playwright = `2630 passed, 10 skipped` passed; i18n scalar keys = `1090/1090`, `errors.*` covers `27/27` error codes, and `Format.*` covers 6 formatting labels; Vite preview plus `ahadiff serve` `/` and `/healthz` local smoke checks had no security console errors or warnings; `git diff --check` passed. Integration tests, eval tests, live judge, coverage, and remote GitHub Actions workflows were not rerun in this follow-up.

This viewer review-fix only changes the frontend learning surfaces and tests: Learn Mode Dialog now defaults output language to the active viewer locale, while still allowing auto / en / zh-CN in the advanced section; Review restores the Again / Hard / Good / Easy four-rating surface, syncs keyboard shortcuts `1`-`4`, and adds the at-risk concept chip, forgetting-curve copy, and mastery warning / danger colors; Quiz adds Prev / Mark wrong / Next navigation, Guided / Recall / Transfer mode chips, a progress table, and mark-wrong idempotency. The Quiz SRSCard still keeps Good / Hard / Wrong plus the peek guard. The CSS also syncs the four-column / mobile 2x2 rating grid, touch targets, hover shadows, reduced-motion, forced-colors, and the shared `sr-only` helper. At that point, `viewer/src` was 13 pages, 47 production TSX files, 40 CSS files, and `1101/1101` i18n scalar keys.

This viewer review-fix verification: `cd viewer && pnpm typecheck` passed; `cd viewer && pnpm vitest run` = `25 files, 269 tests passed`; `cd viewer && pnpm build` passed; `cd viewer && pnpm exec playwright test --reporter=line` = `2630 passed, 10 skipped`; `git diff --check` passed. Playwright only printed the `NO_COLOR` / `FORCE_COLOR` environment warning, and the command exited 0. Backend tests, integration tests, eval tests, live judge, coverage, wheel build, and remote GitHub Actions workflows were not rerun in this pass.

This ConceptGraph Canvas migration and graph-hardening follow-up changes only the current graph path: backend `ConceptGraphEdge` now has `confidence`, `/api/graph/concepts` only passes through allowlisted `EXTRACTED` / `INFERRED` / `AMBIGUOUS` values, and node `metadata` continues to pass through. The Graphify parser now reads imported graphs through no-follow regular-file, reparse, size, and UTF-8 guards. The frontend ConceptGraph moved from SVG + d3-force to the `react-force-graph-2d` Canvas renderer while keeping Graph / List, large-graph List defaults, Full graph, node details, and cross-view search links. It also adds community fills, legend/filter UI, a Canvas accessibility list fallback, forced-colors styling, and Windows-safe path basenames. SearchOverlay / AppShell now share the same open-search event, Concepts graph refresh retries once after `409 LOCK_CONFLICT`, and Vite keeps graph-renderer dependencies in `vendor-graph` outside initial modulepreload. Current i18n scalar keys are `1131/1131`.

This ConceptGraph follow-up verification: `cd viewer && pnpm typecheck` passed; `cd viewer && pnpm vitest run` = `25 files, 270 tests passed`; `cd viewer && pnpm build` passed; `cd viewer && pnpm exec playwright test tests/e2e/media-features.spec.ts tests/e2e/walkthrough.spec.ts --project=chromium-desktop --reporter=line` = `62 passed`; `UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run --frozen --no-sync pytest tests/unit/test_routes_graph.py tests/unit/test_graphify.py -q` = `117 passed`; targeted `ruff check` and `pyright` passed; i18n scalar keys = `1131/1131`; `git diff --check` passed. Integration tests, eval tests, live judge, coverage, wheel build, full Playwright, and remote GitHub Actions workflows were not rerun in this pass.

This AI Tool Guidance / Ratchet export / Audit follow-up closes three product edges that were easy to misread. The visible Settings tab is now "AI Tool Guidance", while the deep link stays `#/settings?tab=integrations`; it writes repo-local guidance files for Claude, Codex, Aider, and similar tools, not another AhaDiff CLI install and not global user directories. Each target is shown as a card with current-project scope, write/remove commands, copy buttons, inline manifest preview, manifest hash, and the file actions that will run. Guide now also explains the difference between CLI install and project-level agent guidance. Ratchet can now download JSON through the same token-header blob path as TSV, and backend `GET /api/export/results?format=json` returns `{"format":"json","results":[...]}`. `GET /api/audit` now returns newest entries first, with pagination and field filtering applied after that ordering.

This follow-up verification: targeted backend regression `116 passed`; `ruff check src tests` and `pyright src tests` passed; `ruff format --check` passed on the Python files changed in this round; full `ruff format --check src tests` still reports that untouched `src/ahadiff/graphify/parser.py` would be reformatted, so it is not counted as a pass here; `cd viewer && pnpm typecheck`, `pnpm vitest run` (`25 files, 270 tests passed`), and `pnpm build` passed; i18n scalar keys = `1176/1176`; `cd viewer && pnpm exec playwright test tests/e2e/smoke.spec.ts tests/e2e/walkthrough.spec.ts --project=chromium-desktop --reporter=line` = `59 passed`. Integration tests, eval tests, live judge, coverage, wheel build, full Playwright, and remote GitHub Actions workflows were not rerun in this pass.

The earlier 2026-05-12 adversarial review fix closes a few user-facing edges. Full lessons now have `walkthrough_tldr`; older lesson JSON without the field still deserializes, and full lessons render it as `Walkthrough Summary` before the walkthrough. Ratchet can download `.apkg` from the WebUI: backend `GET /api/export/apkg` exports active review cards only, caps the deck at 10,000 cards, returns `501 FEATURE_UNAVAILABLE` when `genanki` is missing, and requires the optional `ahadiff[anki]` extra. A read-only stdio MCP server is now available at `ahadiff mcp-server --repo-root <repo>`; that pass shipped six read-only tools, and Phase 2 later added `ask_lesson`, so the current server has seven tools. The frontend pass also tightens SSE reconnect with exponential backoff plus polling fallback, SearchOverlay two-column results/preview and mobile back/Escape behavior, ErrorBoundary redacted diagnostics and non-HTTPS clipboard fallback, ConceptGraph dark canvas colors, V6 motion/elevation CSS primitives, and Vitest coverage config.

This pass was verified with real commands: `UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run --frozen --no-sync pytest tests/unit -x -q` = `2150 passed`; `uv run --frozen --no-sync ruff check src tests` passed; targeted `pyright` for the changed Python paths passed; `uv lock --check` passed; `cd viewer && pnpm install --frozen-lockfile`, `pnpm typecheck`, `pnpm vitest run` (`28 files, 310 tests passed`), `pnpm t` (also `28 files, 310 tests passed`), `pnpm vitest run --coverage`, and `pnpm build` passed. Coverage summary was `26.3%` statements/lines, `72.16%` branches, and `45.28%` functions. SearchOverlay desktop+mobile Playwright = `6 passed`; ErrorBoundary desktop+mobile Playwright = `4 passed`; `git diff --check HEAD` passed. Integration tests, eval tests, live judge, wheel build, full Playwright, and remote GitHub Actions were not rerun in this pass.

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

LOOP: edit → commit → evaluate → keep if better, reset if worse → write to `review.sqlite` (single source of truth; `results.tsv` and JSON exports are views).

## Quickstart

The commands below match the current CLI. In a source checkout, use `uv run ahadiff ...`; after wheel / pipx installation, use `ahadiff ...` directly.

```bash
pipx install ahadiff

# Needed only when downloading Anki .apkg from the WebUI
pipx install "ahadiff[anki]"

# Initialize .ahadiff/ for the current repo
ahadiff init
ahadiff doctor
ahadiff config show --resolved

# Learn the latest commit
ahadiff learn --last

# Learn the latest commit and open the local run lesson when the environment allows it
ahadiff learn --last --open

# Score the run against a local spec; semantic review is opt-in and uses the judge provider
ahadiff learn --last --against-spec SPEC.md
ahadiff learn --last --against-spec SPEC.md --spec-semantic-review

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

# Local static preview export and concept health checks
ahadiff export preview <run_id> --out .ahadiff/export-preview
ahadiff concepts lint --dry-run

# Challenge loop is disabled by default; after opt-in, build in CLI and finish challenge/review/adapt in the WebUI
ahadiff challenge build <run_id>
ahadiff challenge status

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

In the WebUI, Settings → AI Tool Guidance (URL still uses `?tab=integrations`) uses the protected serve API for these same targets. The browser previews the manifest first and receives a hash; write / remove actions must send that hash back as `confirmed_manifest_hash` with the local write token. The endpoint writes only for the repo that started `ahadiff serve`; it does not accept an arbitrary repo path from the browser. This writes repo-local AI tool guidance, not another AhaDiff CLI install. Guide is only a usage guide and entry point, so it does not call the install API directly.

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

# Read-only MCP stdio server for local MCP-capable agents
ahadiff mcp-server --repo-root .

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
├─ results.tsv           # Human-readable TSV export rebuilt from review.sqlite
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
│  ├─ spec_alignment.json    # Optional --against-spec deterministic/semantic alignment result
│  ├─ graphify_context.json  # Optional Graphify context summary
│  ├─ graphify_signoff.json  # Optional Graphify provenance/signoff checks
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
├─ src/ahadiff/lesson/          # Stage 3 / Task 8.5 + 9 learnability + lesson + walkthrough_tldr + helpfulness/transfer
├─ src/ahadiff/quiz/            # Stage 3 / Task 10 open-answer quiz + cards + misconception cards
├─ src/ahadiff/wiki/            # Stage 3 / Task 10 concepts ledger + deterministic health lint
├─ src/ahadiff/challenge/       # Phase 2 opt-in challenge state machine + deterministic diff-gap review
├─ src/ahadiff/export/          # Phase 2 local static preview export + deterministic zip writer
├─ src/ahadiff/graphify/        # Current-branch Graphify backend: models/parser/matcher/linker/slicer/search/freshness/cli plus concepts/FTS wiring
├─ src/ahadiff/eval/            # Stage 3 / Task 11-12 evaluator + spec alignment + ratchet + results + optional LLM judge
├─ src/ahadiff/mcp/             # read-only stdio MCP server exposing runs/cards/search/concepts/stats/ask_lesson
├─ src/ahadiff/serve/           # Task 14.5 + v0.2 local serve API (incl. search/audit/usage/mastery/learning/tasks/export/challenge)
├─ src/ahadiff/install/         # Task 19/20 install targets + hooks no-follow + GitHub Action templates
├─ src/ahadiff/i18n/            # i18n-0 locale resolver / prompt language helper
├─ src/ahadiff/review/          # Task 15 + v0.2 review.sqlite schema v10 / FSRS-6 / migration chain / APKG CSS resource
├─ src/ahadiff/prompts/         # Prompt resources packaged into the wheel, including eval_judge.md
├─ prompts/                     # Lesson / claim / quiz / eval judge prompt templates
├─ src/ahadiff/improve/         # Stage 5 / Task 16/17 improve loop, targeted verify, Phase 2.5
├─ benchmarks/                  # Task 18 local benchmark fixtures + manifest + scripts + results + serve read-route gate
├─ tests/unit/                  # Stage 0-6 and i18n-0 unit tests
├─ tests/eval/                  # benchmark suite tests
├─ tests/integration/           # pinned integration fixtures
├─ tests/live/                  # Opt-in real LLM judge smoke
├─ viewer/                      # React 19 + Vite + Zustand + vanilla CSS frontend (14 production page TSX / 52 non-test TSX / 47 CSS / 1454 i18n scalar keys; Phase 2: Challenge pages, Export modal, HealthBadge; latest hardening gate: backend unit 2513 + viewer Vitest 360 + i18n 1454; previous full Playwright gate remains 2855)
├─ ui/                          # HTML prototypes v1–v6 (design history)
└─ CLAUDE.md                    # Project AI context index
```

## Status

**Stage 0 / Task 0, Stage 1 Task 1/2, Layer 1.5 / Task 7, Stage 2 / Task 5/6/8, Stage 3 / Task 8.5/9/10/11/12, Stage 4 / Task 15, Stage 5 / Task 16/17, Stage 6 / Task 18/19/20, and the i18n-0 backend are now landed.** The current codebase already has:

- the `ahadiff learn` main path for git and non-git capture (`--patch` / `--compare`), followed by learnability gating, `claims.raw.jsonl -> claims.jsonl`, and full / hint / compact lesson output; worktree inputs also support repeatable `--changed-path` to learn only selected repo-relative paths; `--open` prints and tries to open the local run lesson after learn; `--against-spec` writes `spec_alignment.json`; `--spec-semantic-review` explicitly enables judge-provider semantic review; `.ipynb` git diffs render a cell-aware source view, ignore outputs/metadata, and degrade back to the normal diff path when parsing fails
- `ahadiff quiz` for a minimal interactive quiz loop backed by `quiz.jsonl`, with source-claim and file-line evidence printed back to the user
- the quiz artifact chain writes both `quiz.jsonl` and `misconception_cards.jsonl`; scored PASS / CAUTION runs generate `cards.jsonl` and backfill `review_card_id`, while open-answer rows without `review_card_id` still render correctly in the viewer; git-backed runs write the repo-global `concepts.jsonl`, while non-git runs write `concepts_local.jsonl`
- `ahadiff score`, `ahadiff verify`, and `ahadiff export-results`, backed by `review.sqlite` as the single source of truth and `results.tsv` as the CLI export view; the WebUI / serve API can also download a JSON view, and with `ahadiff[anki]` installed Ratchet can download an `.apkg` containing active review cards only, capped at 10,000 cards
- `ahadiff review`, `ahadiff mark <claim_id> wrong`, and `ahadiff db {backup,restore,check,import-results,finalize-targeted}` for the landed review.sqlite review / signals / result-events / lossy-import / targeted-finalize path
- `ahadiff serve`: the localhost-only serve backend is available. Read routes expose finalized runs only; write routes require token plus Origin/Referer checks. `/api/auth/token` requires a same-origin browser signal, keeps GET compatibility, and supports POST bootstrap. API error responses now use stable `{error_code,error,status,details?}` payloads; missing or invalid tokens map to `401/AUTH_REQUIRED`, loopback / write-origin denials stay `403/LOOPBACK_DENIED`, and unavailable optional features map to `501/FEATURE_UNAVAILABLE`. The current route surface is 72 concrete `/api/*` routes plus one `/api/{rest_of_path:path}` catchall, with `/healthz` outside the API surface. `GET /api/run/{id}` returns optional `learnability` when metadata is valid; missing `lesson` / `claims` / `quiz` / `spec_alignment` / `graphify_signoff` artifacts return 404 `artifact_not_found`; low-learnability lesson/quiz skips still publish minimal `score.json` and `finalized.json`, so run detail stays readable. `POST /api/review/rate` and `POST /api/signals/srs-review` now retry once after lazy-importing run cards when the requested active card is missing. `GET /api/spec/alignment` aggregates finalized-run spec requirements, degraded artifacts, semantic reviews, and disagreement counts. `GET /api/ratchet/transparency` requires the write token, reads result rows from `review.sqlite/result_events`, and projects transparency summaries from real benchmark manifest/report files; missing or corrupt benchmark files produce warnings, not mock data. `POST /api/learn` has an in-memory 10 req/min sliding-window rate limit with `retry_after` / `Retry-After`; both `POST /api/learn` and `POST /api/learn/estimate` support `changed_paths`, `against_spec`, and `spec_semantic_review`, and reject `since` / `author` leading dashes or control characters at the route layer; `against_spec` is resolved only as a local file inside the current workspace, with failures returned as `INPUT_VALIDATION`. Concepts Ledger, concept health, Run Detail Judge/Concepts/Spec Alignment/Graphify Signoff, and Improve Preflight now have read-only routes; `POST /api/export/preview` creates a strict-local static preview manifest behind the write token; Challenge build/get/advance/abort/review/feedback routes are protected by the `challenge.enabled` feature flag and return `FEATURE_UNAVAILABLE` while disabled; `POST /api/graph/refresh` re-imports the Graphify artifact inside the repo write lock, validates the imported path, and uses a 600s request timeout on the exact route; `POST /api/db/check` returns schema/quick_check/event/card counts through a read-only DB check without initializing an empty database; install targets now have `GET /api/install/targets`, preview, install, and uninstall routes, with writes requiring a token plus confirmed manifest hash and applying only to the current serve repo; `GET /api/export/apkg` downloads `ahadiff_review.apkg` through the same write-token model and returns 501 when `genanki` is not installed; `/api/tasks*` is stable product API, and the viewer now consumes `/api/tasks/{id}/progress` SSE first, retries transient disconnects up to 5 times in the background, and keeps polling fallback; `/api/watch/status` remains internal/unstable. `GET/PUT /api/config` now includes `learnability_threshold`, `desired_retention`, and `quiz_question_count`, and serve runtime reads config from the active workspace.
- `ahadiff install` / `ahadiff uninstall`: all 13 targets are available (Aider / Claude / Cline / Codex / Continue / Copilot / Cursor / Gemini / GitHub Action / hooks / OpenCode / Roo / Windsurf); the real write paths are listed in the install target table above. Hooks are POSIX-shell targets and are explicitly rejected on Windows in v0.1. Existing hook files are now read through no-follow regular-file checks, so symlink / reparse-point hook paths are rejected. The shared write layer also rejects unsafe reparse / symlink-parent paths. Hooks and repo git calls resolve `git` with `shutil.which("git")`, report missing git clearly, bound hook helper calls with a timeout, and preserve legitimate spaces in returned paths. Generated verify workflows cover macOS / Linux / Windows: Linux SQLite builds run only on Linux runners, Windows runs `ahadiff --version` as a CLI load smoke, and `verify --ci` still runs only on non-Windows runners. The generate workflow uses `AHADIFF_PROVIDER_API_KEY` and uploads `.ahadiff/` outputs as an artifact. The WebUI Settings → AI Tool Guidance surface reuses the same install target contract: it previews the manifest first, then confirms write / remove with a hash plus token, and never accepts an arbitrary repo path from the browser; Guide only shows commands and the integration entry point
- `ahadiff mcp-server --repo-root <repo>` starts a read-only stdio MCP server over that repo's `.ahadiff/review.sqlite`, runs, and concepts. Non-git roots validate `.ahadiff` with symlink/reparse guards. The seven available tools only read data: list runs, get a run summary, list due cards, search, page concepts, return stats, and local `ask_lesson` lesson-fragment search
- `ahadiff benchmark`: the local benchmark manifest, 20 eval fixtures, 11 pinned integration fixtures, and `ground_truth.md` consistency checks are available; the 11th fixture is a graph-present smoke fixture proving a Graphify-style `graph.json` is covered by the suite digest, parses through the real parser, and materializes `graphify_context.json` / `artifact_set.json` in the fixture path. The production per-run Graphify context and `graphify_signoff.json` paths are covered by `test_git_capture.py`; `run_all.sh` now also runs `bench_serve_read_routes.py`, using an internal fixture to check runs / concepts / graph / search / ratchet transparency read-route p95 and response shape; this fixture is not proof of full real large Graphify export fidelity
- the repo also now ships repo-level Backend CI / `nightly-eval` / `release` workflows: PR runs unit + pinned integration (`ubuntu py311/py312 + macOS py312`) with a separate Windows runtime guard, and the current PR CI also includes `tests/eval` in the same Python gate; the release gate now blocks on `doctor`, wheel install smoke, and coverage `>= 85%`. This pass also adds `.github/workflows/frontend-ci.yml`: frontend PR/push checks run `pnpm typecheck`, `pnpm vitest run`, `pnpm build`, all 11 Chromium desktop E2E specs, plus Firefox and WebKit desktop smoke/a11y. `pyproject.toml` also now carries `watchdog` / `tree-sitter` optional extras and `pytest-cov` as a dev dependency; `ahadiff watch`, `serve --watch`, and `/api/watch/status` are landed, while `/api/watch/status` remains internal/unstable. `tree-sitter` is no longer just optional wiring: the runtime consumer is now connected at the symbol-extraction layer for JS/TS/TSX + Go + Java + Rust + PHP + Ruby + C#; Python stays AST-first, unsupported languages still fall back to regex / section header, and no downstream lesson / quiz / claims business logic changed
- The Phase 0 follow-up is now reflected in the branch: the contract authority, the `safe_sqlite_connect` SQLite connection helper, reparse/hardlink protections, serve CORS and `X-Frame-Options` headers, CLI cold start, and local baseline scripts all have matching implementation
- i18n-0: the locale resolver supports cookie / Accept-Language / `AHADIFF_LANG` / CLI / config / `LANG` fallback; serve run/artifact reads resolve locale per request, `PUT /api/locale` persists to `.ahadiff/config.toml`, and claim extraction, lesson, and quiz prompt payloads all carry the requested output-language instruction
- `ahadiff improve --suite local --rounds N`, which currently supports only `--suite local`. It selects a baseline from an existing finalized run, edits only an allowlisted prompt in a git worktree, replays the same diff, and rescores the candidate; the candidate must improve the target dimension plus `accuracy`, `evidence`, and `safety_privacy`, and hard gates must still pass. Passing candidates are cherry-picked back when possible and recorded as `event_type=improve` / `status=targeted_verify`; non-improving rounds are recorded as `discard`; cherry-pick conflicts leave a pending worktree without finalizing the run; two consecutive `discard` rounds in the same session trigger one Phase 2.5 worktree rewrite. The current runtime does not write a separate `phase25_rewrite` event; the Phase 2.5 final result is still `targeted_verify` or `discard`, marked with `note_json.phase25`
- `src/ahadiff/eval/{rubric,gates,deterministic,evaluator,spec_alignment,results,ratchet}.py` for the 8-dimension scorer, hard gates, spec-alignment artifact / semantic review, result persistence, ratchet selection, and export rebuilds
- `src/ahadiff/review/{database,scheduler,schemas,signal}.py` for review.sqlite schema / migration, FSRS-6 scheduling, the review queue, learning signals, and the review CLI backend
- `src/ahadiff/improve/{loop,program,targeted,rewrite}.py` for improve sessions, the immutable improve_program prompt, worktree isolation, the 5 mutable-prompt allowlist, replay-learn, targeted verification, Phase 2.5 triggering, cherry-pick ordering, session validation, and pending-worktree resume guards
- runtime resource lookup that works in both source checkout and installed wheel mode for `eval_bundle_version`, `prompt_version`, and packaged lesson prompts
- `keep_final` is still a manual full 8-dimension recheck via `ahadiff db finalize-targeted <event_id>`; the improve loop does not auto-promote it. The `viewer/` React SPA now has 14 production page TSX files. The current learning surface is now closer to real use: Review shows Again / Hard / Good / Easy with `1`-`4` shortcuts, and open-answer reveal no longer marks the quiz peek guard; the Quiz SRSCard still keeps Good / Hard / Wrong plus the peek guard and now has Prev / Mark wrong / Next navigation, mode chips, and a progress table; backend quiz kind accepts only `guided` / `recall` / `transfer`; the Topbar Learn Run button opens Learn Mode Dialog, defaults output language to the active viewer locale, still offers 10 capture modes with preflight confirmation, and lets working / unstaged / staged modes take one Path scope entry per line; the frontend rejects traversal, absolute paths, Windows drive/UNC forms, control characters, and more than 500 paths, and aborts estimate / pending learn work when the dialog closes; Challenge pages provide the Build / Tour / Challenge / Review / Adapt memory-reconstruction flow; the Dashboard empty state can open Learn Mode Dialog, and the spec-alignment KPI reads finalized run `score.json` plus `spec_alignment.json` aggregates with semantic reviewed / degraded / disagreement counts; Diff Viewer has Unified and Split modes, with old/new claim markers and jumps kept side-aware in Split, file summary Prev / Next, `+` / `-` row markers, claim auto-scroll, and aggregated claim dots with count badges for multiple claims on the same line; Lesson recommends compact / hint / full from weak concepts and stability, and now shows a skipped empty state when the lesson artifact is missing; the Lesson reader header now has verdict / score, print, and local mark-as-learned controls, and the right rail is derived from the current run's lesson, claims, concepts, and quiz artifacts instead of static examples; Settings is now 7 tabs (Account / Provider / Capture / Privacy / Audit / Preferences / AI Tool Guidance), with Preferences owning language, appearance, `learnability_threshold`, `desired_retention`, and `quiz_question_count`; Provider / Capture / AI Tool Guidance `?tab=` links initialize and switch tabs; the Provider tab has distinct aria labels for generate/judge provider and model controls; AI Tool Guidance supports preview/write/remove, command copy, inline manifest plans, manifest write-path preview, and re-detect after writes; Guide replaces the old Skills page with workflow, command, maintenance, and supported integration sections, explains the difference between CLI install and project-level agent guidance, shows maintenance commands with `--dry-run` by default, and `/#/skills` redirects to `/#/guide`; SearchOverlay graph-node results jump to Concepts Ledger and focus the plain-text concept name; Review consumes `?card=` and shows at-risk concepts, forgetting-curve copy, and mastery tiers; Concepts is a Ledger / Graph dual-tab page, consumes `?focus=`, `?run=`, and `?tab=`, displays and filters health status for loaded concept entries, lets each row jump back to the Graph for the same concept, scrolls and highlights focused rows, can refresh the Graphify import from the Graph tab, includes the focused node outside the normal limit when `?focus=` is present, and retries once after a write-lock conflict; Ratchet downloads `results.tsv`, `results.json`, and APKG through the Export modal, can request a static preview manifest, and has a read-only Improve Preview tab; Ratchet's results tab now renders the transparency API's inline `results.tsv` table, the Phase 2.5 card reads `note_json.phase25` from final events, and the Benchmark tab reads real manifest/report summaries; Run Detail has Overview / Score / Judge / Concepts / Artifacts tabs, with Overview loading Spec Alignment and Graphify Signoff when those artifacts exist, and Concepts shown only when the run has `concepts.jsonl`; Onboarding shows DB check independently from doctor and uses `DiagnosticRow` for status icons, `sr-only` text, and `aria-live`; Onboarding and Guide share the `CommandBlock` copy component; ConceptGraph now has only Graph / List views, defaults large graphs to List while still allowing Full graph, uses the `react-force-graph-2d` Canvas renderer, and supports a botanical palette, community fills, legend/filter UI, forced-colors rendering, node details, id/name/ledger-key focus, cross-view search links, and an accessible list fallback while stripping local home/system prefixes from displayed node file paths; Dashboard loads runs / ratchet / stats / heatmap / learning through `Promise.allSettled`, so a learning-effectiveness failure no longer breaks the main page; long-running task progress now uses SSE first with polling fallback.

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

This follow-up (2026-05-09) reran only the changed surface: backend path-scope regressions `6 passed`; frontend Learn Mode Dialog / manifest / learn-store targeted Vitest `87 passed`; `pnpm typecheck` and `pnpm build` passed; real-serve Playwright contract `1 passed`. The second integrations follow-up also reran `test_routes_install.py = 19 passed`, `test_install.py = 37 passed`, `ruff check src tests`, `ruff format --check src tests`, `pyright`, full frontend Vitest `236 passed`, `pnpm typecheck`, `pnpm build`, and the Skills / Settings integrations / Deep links target Playwright run `75 passed`. The third P1 read-only follow-up reran targeted backend route tests `18 passed`, full backend unit `2088 passed`, ruff/format/pyright, full frontend Vitest `245 passed`, typecheck/build, the three P1 E2E specs across the full project matrix `390 passed`, specified mobile projects `52 passed`, and Concepts/Ratchet targeted axe-core audits `2 passed`. The 2026-05-10 review follow-up reran DB check targeted backend tests `2 passed`, full backend unit `2090 passed`, ruff/format/pyright, viewer typecheck, full frontend Vitest `245 passed`, viewer build, Run Detail + media targeted Playwright `500 passed, 10 skipped`, specified walkthrough/smoke/a11y/cross-browser/learn-task/media E2E `1760 passed, 10 skipped`, and `git diff --check`. The 2026-05-10 frontend review-fix then reran viewer typecheck, full frontend Vitest `245 passed`, viewer build, full Chromium desktop E2E `166 passed`, WebKit desktop smoke/a11y `38 passed`, full Chromium mobile E2E `166 passed`, backend unit `2090 passed`, ruff/format/pyright, i18n parity `969/969`, and `git diff --check`. The compatibility follow-up reran backend unit `2130 passed`, ruff/format/pyright, viewer typecheck, frontend Vitest `250 passed`, viewer build, i18n `969/969`, Chromium desktop smoke `21 passed`, Chromium desktop a11y `17 passed`, 10 real browser scenes, and `git diff --check`. The error / locale / i18n hardening follow-up reran targeted backend tests `455 passed`, full backend unit `2136 passed`, ruff/format/pyright, viewer typecheck, frontend Vitest `253 passed`, viewer build, i18n scalar keys `1011/1011`, `errors.* 27/27`, `Format.* 6/6`, and `git diff --check`. This Guide follow-up reran Guide-targeted Playwright `7 passed`, frontend Vitest `253 passed`, viewer typecheck, viewer build, Guide/i18n/secret static checks, and `git diff --check`. The 2026-05-11 Onboarding / Guide QA follow-up reran backend unit `2136 passed`, ruff/format/pyright, wheel, version, doctor, frontend Vitest `268 passed`, typecheck/lint/build, full Playwright `2630 passed, 10 skipped`, i18n `1090/1090`, Vite preview plus `ahadiff serve` local smoke, and `git diff --check`. This viewer review-fix reran `cd viewer && pnpm typecheck`, `pnpm vitest run = 25 files, 269 tests passed`, `pnpm build`, full Playwright `2630 passed, 10 skipped`, i18n `1101/1101`, and `git diff --check`. This ConceptGraph Canvas follow-up reran viewer typecheck, frontend Vitest `270 passed`, viewer build, target Playwright `62 passed`, graph route/parser backend target `117 passed`, targeted ruff/pyright, i18n `1131/1131`, and `git diff --check`. This AI Tool Guidance / Ratchet export / Audit follow-up reran backend target tests `116 passed`, `ruff check`, `pyright`, changed-Python-file format check, viewer typecheck, frontend Vitest `270 passed`, viewer build, i18n `1176/1176`, and target Playwright `59 passed`; full `ruff format --check` still reports untouched `src/ahadiff/graphify/parser.py` formatting drift, so it is not counted as a pass here. Integration tests, eval tests, live judge, coverage, wheel build, full Playwright, and remote GitHub Actions workflows were not rerun in this pass. No real improve write was executed.

The 2026-05-12 adversarial review fix reran full backend unit `2150 passed`, `ruff check`, targeted `pyright`, `uv lock --check`, viewer `pnpm install --frozen-lockfile`, typecheck, Vitest `310 passed`, `pnpm t`, coverage, build, SearchOverlay + ErrorBoundary target Playwright `10 passed`, and `git diff --check HEAD`. Integration tests, eval tests, live judge, wheel build, full Playwright, and remote GitHub Actions were still not rerun.

The 2026-05-12 v1.1 security / cross-platform follow-up then added version sync, git argument boundaries and environment cleanup, URL userinfo rejection, JSON input caps, the MCP table allowlist, broader zero-width prompt-injection detection, claim-artifact no-follow / reparse / hardlink / TOCTOU guards, the improve-preflight git wrapper, `.gitattributes`, `browserslist` / `build.target`, and shared clipboard fallback. The following Phase 2 pass adds schema v10 concept health lint, local static preview export, MCP `ask_lesson`, opt-in Challenge loop, APKG packaged CSS, and the Challenge / Export / HealthBadge frontend entry points. This adversarial review pass also hardens Challenge rebuild/review atomicity, finite manifest scores, export-preview noindex / injection recheck / stale-cleanup TOCTOU handling, the MCP `ask_lesson` output contract and read-only path guards, concept-lint JSONL reads and path normalization, and non-finite review score rejection. Actual verification: backend unit `2409 passed`; integration `11 passed`; eval `9 passed`; `ruff check`, `ruff format --check`, and `pyright` passed; viewer typecheck, Vitest `326 passed`, and build passed; i18n `1262/1262`; `git diff --check HEAD` passed. Live judge/wheel/full Playwright/remote GitHub Actions were not rerun in this pass.

The 2026-05-14 Lesson reader follow-up reran only the frontend changed surface: viewer typecheck, Vitest `336 passed`, viewer build, i18n `1297/1297`, and the Lesson walkthrough target E2E `1 passed`. Backend tests, integration tests, eval tests, live judge, wheel build, full Playwright, and remote GitHub Actions were not rerun in this pass.

The 2026-05-14 Ratchet transparency follow-up reran targeted backend tests `5 passed`, the backend Ratchet/Phase2.5/benchmark target group `153 passed`, `ruff check`, `ruff format --check`, `pyright`, viewer typecheck, Vitest `336 passed`, viewer build, Ratchet walkthrough Playwright `30 passed`, ratchet benchmark media Playwright `15 passed`, i18n `1338/1338`, real serve/browser without mocks, and GPT-5.5 live judge smoke `1 passed`. A separate synthetic eval_judge smoke wrote an 8-dimension `judge.json`; two synthetic learn smokes successfully called real GPT-5.5 claim extraction, but their synthetic diff claims were classified as weak by the deterministic verifier, so lesson/quiz were skipped by design. Full Playwright, wheel build, and remote GitHub Actions were not rerun in this pass.

The 2026-05-14 Warm v6 / Blueprint follow-up reran backend unit `2434 passed`, integration `11 passed`, eval `9 passed`, `ruff check`, `ruff format --check`, `pyright`, wheel build, viewer typecheck, Vitest `344 passed`, viewer build, full Playwright `2735 passed, 10 skipped`, i18n `1392/1392`, and `git diff --check HEAD`. Live judge and remote GitHub Actions were not rerun in this pass.

The 2026-05-14 spec alignment / Notebook follow-up reran backend unit `2477 passed`, integration `11 passed`, eval `9 passed`, `ruff check`, `ruff format --check`, `pyright`, wheel build, viewer typecheck, Vitest `345 passed`, viewer build, full Playwright `2855 passed, 10 skipped`, i18n `1439/1439`, and `git diff --check HEAD`. After loading `.env.local`, live semantic alignment smoke reran with a real LLM and passed (`1 passed`). Remote GitHub Actions were triggered and monitored, but GitHub refused to start the jobs because of account billing / spending-limit status, so no runner logs were produced and this is not counted as a code-validation pass.

The 2026-05-15 review/test follow-up reran backend unit `2502 passed`, integration `11 passed`, eval `9 passed`, `ruff check`, `ruff format --check`, `pyright`, wheel build, viewer typecheck, Vitest `34 files, 350 tests passed`, viewer build, full Playwright `2855 passed, 10 skipped`, i18n `1447/1447`, and `git diff --check HEAD`. Live judge and remote GitHub Actions were not rerun in this pass.

The 2026-05-15 Diff/Landing frontend polish reran viewer typecheck, Vitest `35 files, 353 tests passed`, viewer build, backend unit `2502 passed`, i18n `1449/1449`, and `git diff --check HEAD`. This pass only changes the `viewer/` learning entry surfaces; integration tests, eval tests, ruff/format/pyright, wheel build, full Playwright, live judge, and remote GitHub Actions were not rerun.

The 2026-05-15 Learn Mode / Diff aggregation hardening pass reran backend targets `199 passed`, backend unit `2513 passed`, integration+eval `20 passed`, `ruff check`, `ruff format --check`, `pyright`, wheel build, viewer typecheck, Vitest `35 files, 360 tests passed`, viewer build, i18n `1454/1454`, and `git diff --check HEAD`. Full Playwright, live judge, and remote GitHub Actions were not rerun in this pass.

Roadmap:

- [ ] `v0.1` (MVP): CLI + Lesson + Evaluator + Ratchet end-to-end + React 19 WebUI (`ahadiff serve`) + 8 LLM Providers + 8 diff capture modes (incl. --unstaged / git show) + 13 install targets + i18n + stage gates
- [ ] `v0.2`: --compare-dir + --patch-url + 7 IDE install targets + watchdog incremental regeneration + section-level helpfulness + Team features (done: backend Gates 0-6 + medium APIs + helpfulness / learning transfer + misconception cards + full-lesson `walkthrough_tldr` + Graphify backend foundations with concept linking / FTS / provenance / perf gate + Graphify signoff artifact + post-learn Graphify update/import + watch mode + path-scoped learn + `learn --open` + spec alignment deterministic artifact / opt-in semantic review + Notebook cell-aware diff + graph refresh API + DB check API + graph edge confidence DTO + Run Detail learnability + learning artifact 404 contract + APKG download + packaged APKG CSS + read-only MCP server / `ask_lesson` + 13 install targets + install target WebUI safety loop + provider/model settings + Learn Mode Dialog safety/a11y hardening + `/api/learn` rate limit / git filter injection guard + DNS pinning + LLM judge + concept health lint + local static preview export + opt-in Challenge loop + review card lazy import + current frontend learning-surface closure: three-button SRS UI, automatic scaffolding, retention settings, Ratchet TSV/JSON/APKG export, Ratchet inline results / Phase 2.5 / benchmark transparency, Export modal, ConceptGraph Graph/List views, Canvas renderer, community fills, forced-colors/focus persistence, accessible list fallback, Concepts Ledger/HealthBadge, ConceptLedger graph links/focus highlight, Run Detail judge/spec alignment/Graphify signoff artifact browser, Run Detail concepts artifact, Ratchet Improve Preview, Dashboard learning-metric isolation and empty-state Learn CTA, Challenge pages, Guide page, Project AI Tool Guidance page, three-state sidebar with real provider/config footer, Diff Unified/Split with side-aware claim jumps + aggregated claim count badges, Dashboard source filters, container-query hardening, Settings/Lesson/Guide/Review heading and aria cleanup, Settings/Concepts/Review deep-link consumption, SearchOverlay two-column preview and Ledger focus links, ErrorBoundary redacted diagnostics and copy fallback, CSP hash / z-index token / favicon / runtime status / queue-state / signals / idempotency fallback hardening; remaining: Team / stable APKG namespace GUID / real large-repo signoff evidence / finer frontend visual polish)
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
