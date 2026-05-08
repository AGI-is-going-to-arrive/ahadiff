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

This round is scoped to the `viewer/` frontend. The Topbar "Learn Run" button now opens a lazy-loaded Learn Mode Dialog where users can choose among 10 capture modes: working tree, unstaged, staged, last commit, since, revision, patch URL, compare, compare dir, or pasted patch. The dialog uses the existing `/api/learn/estimate` preflight path, supports force / Graphify / dry-run / output language / privacy mode options, and now has focus trap, Escape close, inert background handling, patch-size limits, and touch-target hardening. ConceptGraph only changed for privacy in this round: local absolute file paths are shortened before display so usernames and local filesystem roots are not exposed in node details or List view. The full-graph interaction itself was not changed again in this round. Settings / Lesson / Onboarding / Skills / markdown heading changes are accessibility and heading-outline cleanup. Backend code did not change.

This session verified the changed surface: `pnpm exec vitest run tests/unit/learn-mode-dialog.test.ts --reporter=dot` = `28 passed`; `pnpm vitest run` = `21 files, 226 tests passed`; `pnpm typecheck` and `pnpm build` passed; `npx playwright test tests/e2e/learn-task.spec.ts --project=chromium-desktop` = `10 passed`; i18n catalog parity is `783/783`; and `git diff --check -- viewer` passed. Backend tests, the full Playwright suite, and the live LLM judge smoke were not rerun for this frontend-only change.

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

## Quickstart (Planned)

```bash
pipx install ahadiff

# Learn the last commit
ahadiff learn HEAD~1..HEAD

# Learn staged changes
ahadiff learn --staged

# Learn against a spec
ahadiff learn HEAD~1..HEAD --against .ahadiff/specs/oauth-login/SPEC.md

# Review
ahadiff quiz abc123
ahadiff review

# Interactive browser UI (Quiz/SRS/Dashboard)
ahadiff serve

# Ratcheted self-improvement (Task 16/17 backend is landed; requires an existing finalized run and provider configuration)
ahadiff improve --suite local --rounds 6

# Install into AI tools and automation (13 targets)
ahadiff install claude    # Claude Code → .claude/skills/
ahadiff install codex     # Codex CLI → AGENTS.md
ahadiff install gemini    # Gemini CLI → GEMINI.md
ahadiff install opencode  # OpenCode → AGENTS.md + .opencode/agents/
ahadiff install hooks     # POSIX shell git hooks (Windows is rejected in v0.1)
ahadiff install github-action          # verify-only workflow
ahadiff install github-action --layer2 # opt-in generate workflow (requires provider secret)
ahadiff install cursor    # Cursor → .cursor/rules/
ahadiff install windsurf  # Windsurf → .windsurf/rules/
ahadiff install copilot   # GitHub Copilot → .github/copilot-instructions.md
ahadiff install continue  # Continue → .continue/rules/
ahadiff install aider     # Aider → .aider.conf.yml
ahadiff install cline     # Cline → .clinerules
ahadiff install roo       # Roo Code → .roo/rules/
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
├─ viewer/                      # React 19 + Vite + Zustand + vanilla CSS frontend (12 pages / 37 production page+component TSX / 24 page+component CSS / 783 i18n keys / this session: LearnModeDialog unit 28 passed + full frontend Vitest 226 passed + Learn E2E 10 passed)
├─ ui/                          # HTML prototypes v1–v6 (design history)
└─ CLAUDE.md                    # Project AI context index
```

## Status

**Stage 0 / Task 0, Stage 1 Task 1/2, Layer 1.5 / Task 7, Stage 2 / Task 5/6/8, Stage 3 / Task 8.5/9/10/11/12, Stage 4 / Task 15, Stage 5 / Task 16/17, Stage 6 / Task 18/19/20, and the i18n-0 backend are now landed.** The current codebase already has:

- the `ahadiff learn` main path for git and non-git capture (`--patch` / `--compare`), followed by learnability gating, `claims.raw.jsonl -> claims.jsonl`, and full / hint / compact lesson output
- `ahadiff quiz` for a minimal interactive quiz loop backed by `quiz.jsonl`, with source-claim and file-line evidence printed back to the user
- the quiz artifact chain writes both `quiz.jsonl` and `misconception_cards.jsonl`; scored PASS / CAUTION runs generate `cards.jsonl` and backfill `review_card_id`, while open-answer rows without `review_card_id` still render correctly in the viewer; git-backed runs write the repo-global `concepts.jsonl`, while non-git runs write `concepts_local.jsonl`
- `ahadiff score`, `ahadiff verify`, and `ahadiff export-results`, backed by `review.sqlite` as the single source of truth and `results.tsv` as an export view
- `ahadiff review`, `ahadiff mark <claim_id> wrong`, and `ahadiff db {backup,restore,check,import-results,finalize-targeted}` for the landed review.sqlite review / signals / result-events / lossy-import / targeted-finalize path
- `ahadiff serve`: the localhost-only serve backend is available. Read routes expose finalized runs only; write routes require token plus Origin/Referer checks. `/api/auth/token` requires a same-origin browser signal, keeps GET compatibility, and supports POST bootstrap. The current route surface is 53 concrete `/api/*` routes plus one `/api/{rest_of_path:path}` catchall, with `/healthz` outside the API surface. `POST /api/learn` has an in-memory 10 req/min sliding-window rate limit with `retry_after` / `Retry-After`; `/api/tasks*` is stable product API, while `/api/watch/status` remains internal/unstable. `GET/PUT /api/config` now includes `learnability_threshold` and `desired_retention`, and serve runtime reads config from the active workspace.
- `ahadiff install`: Claude / Codex / Gemini / OpenCode / hooks / GitHub Action targets are available. Hooks are POSIX-shell targets and are explicitly rejected on Windows in v0.1. Existing hook files are now read through no-follow regular-file checks, so symlink / reparse-point hook paths are rejected. Generated GitHub workflows cover macOS + Linux; Windows remains deferred. The generate workflow uses `AHADIFF_PROVIDER_API_KEY` and uploads `.ahadiff/` outputs as an artifact
- `ahadiff benchmark`: the local benchmark manifest, 20 eval fixtures, 11 pinned integration fixtures, and `ground_truth.md` consistency checks are available; the 11th fixture is a graph-present smoke fixture proving a Graphify-style `graph.json` is covered by the suite digest, parses through the real parser, and materializes `graphify_context.json` / `artifact_set.json` in the fixture path. The production per-run Graphify context path is covered by `test_git_capture.py`; this fixture is not proof of full real large Graphify export fidelity
- the repo also now ships repo-level Backend CI / `nightly-eval` / `release` workflows: PR runs unit + pinned integration (`ubuntu py311/py312 + macOS py312`) with a separate Windows runtime guard, and the release gate now blocks on `doctor`, wheel install smoke, and coverage `>= 85%`. `pyproject.toml` also now carries `watchdog` / `tree-sitter` optional extras and `pytest-cov` as a dev dependency; `ahadiff watch`, `serve --watch`, and `/api/watch/status` are landed, while `/api/watch/status` remains internal/unstable. `tree-sitter` is no longer just optional wiring: the runtime consumer is now connected at the symbol-extraction layer for JS/TS/TSX + Go + Java + Rust + PHP + Ruby + C#; Python stays AST-first, unsupported languages still fall back to regex / section header, and no downstream lesson / quiz / claims business logic changed
- The Phase 0 follow-up is now reflected in the branch: the contract authority, the `safe_sqlite_connect` SQLite connection helper, reparse/hardlink protections, serve CORS and `X-Frame-Options` headers, CLI cold start, and local baseline scripts all have matching implementation
- i18n-0: the locale resolver supports cookie / Accept-Language / CLI / config / `AHADIFF_LANG` / `LANG` fallback, and lesson/quiz prompt payloads carry the requested output-language instruction
- `ahadiff improve --suite local --rounds N`, which currently supports only `--suite local`. It selects a baseline from an existing finalized run, edits only an allowlisted prompt in a git worktree, replays the same diff, and rescores the candidate; the candidate must improve the target dimension plus `accuracy`, `evidence`, and `safety_privacy`, and hard gates must still pass. Passing candidates are cherry-picked back when possible and recorded as `event_type=improve` / `status=targeted_verify`; non-improving rounds are recorded as `discard`; cherry-pick conflicts leave a pending worktree without finalizing the run; two consecutive `discard` rounds in the same session trigger one Phase 2.5 worktree rewrite
- `src/ahadiff/eval/{rubric,gates,deterministic,evaluator,results,ratchet}.py` for the 8-dimension scorer, hard gates, result persistence, ratchet selection, and export rebuilds
- `src/ahadiff/review/{database,scheduler,schemas,signal}.py` for review.sqlite schema / migration, FSRS-6 scheduling, the review queue, learning signals, and the review CLI backend
- `src/ahadiff/improve/{loop,program,targeted,rewrite}.py` for improve sessions, the immutable improve_program prompt, worktree isolation, the 5 mutable-prompt allowlist, replay-learn, targeted verification, Phase 2.5 triggering, cherry-pick ordering, session validation, and pending-worktree resume guards
- runtime resource lookup that works in both source checkout and installed wheel mode for `eval_bundle_version`, `prompt_version`, and packaged lesson prompts
- `keep_final` is still a manual full 8-dimension recheck via `ahadiff db finalize-targeted <event_id>`; the improve loop does not auto-promote it. The `viewer/` React SPA still has 12 pages. The current learning surface is now closer to real use: SRSCard / Review / Quiz show only Good / Hard / Wrong in the v0.1 UI; the Topbar Learn Run button opens Learn Mode Dialog with 10 capture modes and preflight confirmation; Lesson recommends compact / hint / full from weak concepts and stability; Settings is now 7 tabs (Account / Provider / Capture / Privacy / Audit / Preferences / Integrations), with Preferences owning language, appearance, `learnability_threshold`, and `desired_retention`, and the Provider tab has distinct aria labels for generate/judge provider and model controls; Ratchet downloads `results.tsv` through a token-header blob request; ConceptGraph now has only Graph / List views, defaults large graphs to List while still allowing Full graph, supports full-graph pan/zoom without hard viewport bounds, and strips local home/system prefixes from displayed node file paths; Dashboard loads runs / ratchet / stats / heatmap / learning through `Promise.allSettled`, so a learning-effectiveness failure no longer breaks the main page.

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

The live LLM judge smoke is opt-in. Its default model order is `gpt-5.3-codex-spark,gpt-5.4-mini`; each model tries OpenAI Responses before Chat Completions:

```bash
AHADIFF_LIVE_LLM_JUDGE=1 \
AHADIFF_LIVE_LLM_API_KEY="$AHADIFF_LIVE_LLM_API_KEY" \
AHADIFF_LIVE_LLM_BASE_URL="$AHADIFF_LIVE_LLM_BASE_URL" \
AHADIFF_LIVE_LLM_MODELS="gpt-5.3-codex-spark,gpt-5.4-mini" \
pytest tests/live/test_llm_judge_live.py -q
```

Latest verification (2026-05-08, this session): `cd viewer && pnpm exec vitest run tests/unit/learn-mode-dialog.test.ts --reporter=dot` = `28 passed`; `cd viewer && pnpm vitest run` = `21 files, 226 tests passed`; `cd viewer && pnpm typecheck` passed; `cd viewer && pnpm build` passed (observed values: initial JS gzip `95,037` bytes, Dashboard first-route JS gzip `137,118` bytes; no hard cap); `cd viewer && npx playwright test tests/e2e/learn-task.spec.ts --project=chromium-desktop` = `10 passed`; i18n catalog parity is `783/783`; `git diff --check -- viewer` passed. Full backend tests, `ruff`, `pyright`, wheel build, coverage, the full Playwright suite, and the live LLM judge smoke were not rerun for this viewer frontend change.

Roadmap:

- [ ] `v0.1` (MVP): CLI + Lesson + Evaluator + Ratchet end-to-end + React 19 WebUI (`ahadiff serve`) + 8 LLM Providers + 8 diff capture modes (incl. --unstaged / git show) + 6 install targets + i18n + stage gates
- [ ] `v0.2`: --compare-dir + --patch-url + 7 IDE install targets + watchdog incremental regeneration + section-level helpfulness + Team features (done: backend Gates 0-6 + medium APIs + helpfulness / learning transfer + misconception cards + Graphify backend foundations with concept linking / FTS / provenance / perf gate + watch mode + 13 install targets + provider/model settings + Learn Mode Dialog + `/api/learn` rate limit + DNS pinning + LLM judge + current frontend learning-surface closure: three-button SRS UI, automatic scaffolding, retention settings, Ratchet TSV, ConceptGraph Graph/List views with unbounded full-graph interaction, Dashboard learning-metric isolation, three-state sidebar, Diff large-file render budget, Dashboard source filters, container-query hardening, Settings/Lesson/Skills heading and aria cleanup; remaining: Team / real large-repo signoff evidence / deeper V6 frontend signoff)
- [ ] `v1.0`: PWA + public benchmark suite

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
