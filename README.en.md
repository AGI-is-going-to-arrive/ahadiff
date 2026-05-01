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

The main line from Stage 0 / Task 0 through Stage 6 now has real shipped artifacts, and Stage 7 i18n signoff has also passed. The current code already ships Lesson / Claims / Quiz / Misconception Cards / Cards / Score / Ratchet. The review-flow SRS runtime, serve backend, install targets, GitHub Action templates, benchmark suite, improve-loop core, Task 17 targeted verification, Phase 2.5 runtime, i18n-0 backend, and the `viewer/` React SPA are all landed. The v0.1 frontend delivered Dashboard / Lesson / Diff / Quiz / ConceptGraph and went through R1-R5 five-round cross-model adversarial review (51 real findings fixed). v0.2 backend Gates 0-6 + frontend Phase 1-4 have all passed review; the current branch also lands section-level helpfulness / learning transfer, misconception cards, Graphify backend foundations plus deeper pieces (parser / matcher / linker / slicer / search / freshness / `/api/graph/status` / `/api/graph/concepts` / `graphify_node_id` linking / `commit_ancestry` derived index / `graph_nodes` FTS import / 500-node benchmark fixture), watch mode (`ahadiff watch` / `serve --watch` / `/api/watch/status`), the mid-tier serve APIs (`/api/search`, `/api/usage`, `/api/audit`, `/api/review/mastery`, `/api/concepts/weak`, `/api/spec/alignment`, `/api/stats/learning`), a low-level task-status surface, and repo-level CI/CD gates (PR unit+pinned + Windows runtime guard + nightly-eval + release coverage gate). This closure round also locks down the learn publish boundary, watcher restart/status behavior, concepts DB/JSONL cursors, public search rank ordering, the auth-token bootstrap contract, review queue-state API, ratchet `note_json` bounds, same-origin PWA manifest/service worker behavior, and the frontend `/api/learn` payload type. The earlier serve token bootstrap, thread-backed learn cancellation/shutdown, empty public IDs in DTOs, non-finite FSRS values, and proxy-trace hardening remain in place. The Phase 2 gate follow-up also closes the backend-contract prerequisites for Settings and ConceptGraph frontend work: providers, audit, doctor, install targets, usage, search, and graph concepts now have stable DTOs aligned with viewer schemas. SearchOverlay focus trapping, the Quiz peek guard, the 1024px drawer boundary, Diff path normalization, API error redaction, CSP, and the lazy chunk budget have also been fixed. Phase 4D Settings UI is now implemented in the V6 shape: 8-tab sidebar, mode summary card, privacy toggles, provider grid, last-20 audit table, API failure fallbacks, tabs keyboard/a11y, and forced-colors / reduced-motion / print / responsive coverage. The frontend is now 12 pages, with 20 TSX components + 20 component/page CSS files and 443/443 i18n key parity; in this session the frontend gate passed `typecheck`, `lint`, unit tests, and build, with unit at 60 passed, and `walkthrough.spec.ts` passed across the configured project matrix at 390 passed. The full Playwright 1245 passed baseline and 443/443 i18n parity are same-day historical proofs that were not rerun after the final review fixes. The current `pnpm run build` budget script reports 85,468 bytes of initial JS gzip and 117,137 bytes of Dashboard first-route JS gzip. Remaining Graphify v1.0 closure work is full provenance, per-run artifact policy, a large-repo performance gate, and 5E cross-page freshness polish.

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
| `prompts/*.md` | Agent | The only writable surface — a directory of prompts (agent edits prompts, never user code) |

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
├─ src/ahadiff/eval/            # Stage 3 / Task 11-12 evaluator + ratchet + results
├─ src/ahadiff/serve/           # Task 14.5 + v0.2 local serve API (incl. search/audit/usage/mastery/learning/tasks)
├─ src/ahadiff/install/         # Task 19/20 install targets + hooks no-follow + GitHub Action templates
├─ src/ahadiff/i18n/            # i18n-0 locale resolver / prompt language helper
├─ src/ahadiff/review/          # Task 15 + v0.2 review.sqlite schema / FSRS-6 / migration chain
├─ src/ahadiff/prompts/         # Prompt resources packaged into the wheel
├─ prompts/                     # Lesson / claim prompt templates
├─ src/ahadiff/improve/         # Stage 5 / Task 16/17 improve loop, targeted verify, Phase 2.5
├─ benchmarks/                  # Task 18 local benchmark fixtures + manifest + scripts + results
├─ tests/unit/                  # Stage 0-6 and i18n-0 unit tests
├─ tests/eval/                  # benchmark suite tests
├─ tests/integration/           # pinned integration fixtures
├─ tests/live/                  # Opt-in real LLM judge smoke
├─ viewer/                      # React 19 + Vite + Zustand + vanilla CSS frontend (12 pages / 20 TSX + 20 CSS / 443 i18n keys / 1245 Playwright)
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
- `ahadiff serve`: the localhost-only serve backend is available. Read routes expose finalized runs only; write routes require token plus Origin/Referer checks. `/api/auth/token` now requires a same-origin browser signal, keeps GET compatibility, and also supports POST bootstrap. The branch also adds `/api/search`, `/api/usage`, `/api/audit`, `/api/review/mastery`, `/api/concepts/weak`, `/api/spec/alignment`, `/api/stats/learning`, `/api/graph/status`, `/api/graph/concepts`, `POST /api/learn`, `POST /api/review/queue-state`, and `/api/watch/status`; the current route surface is 44 concrete `/api` Route objects plus 1 `/api` catchall (`Route(` total = 46, with `/healthz` as the extra non-API route); `/api/tasks*` and `/api/watch/status` remain low-level, internal/unstable status/progress surfaces and are not stable public APIs
- `ahadiff install`: Claude / Codex / Gemini / OpenCode / hooks / GitHub Action targets are available. Hooks are POSIX-shell targets and are explicitly rejected on Windows in v0.1. Existing hook files are now read through no-follow regular-file checks, so symlink / reparse-point hook paths are rejected. Generated GitHub workflows cover macOS + Linux; Windows remains deferred. The generate workflow uses `AHADIFF_PROVIDER_API_KEY` and uploads `.ahadiff/` outputs as an artifact
- `ahadiff benchmark`: the local benchmark manifest, 20 eval fixtures, 10 pinned integration fixtures, and `ground_truth.md` consistency checks are available
- the repo also now ships repo-level Backend CI / `nightly-eval` / `release` workflows: PR runs unit + pinned integration (`ubuntu py311/py312 + macOS py312`) with a separate Windows runtime guard, and the release gate now blocks on `doctor`, wheel install smoke, and coverage `>= 85%`. `pyproject.toml` also now carries `watchdog` / `tree-sitter` optional extras and `pytest-cov` as a dev dependency; `ahadiff watch`, `serve --watch`, and `/api/watch/status` are landed, while `/api/watch/status` is still marked internal/unstable. `tree-sitter` is no longer just optional wiring: the runtime consumer is now connected at the symbol-extraction layer for JS/TS/TSX + Go + Java + Rust + PHP + Ruby + C#; Python stays AST-first, unsupported languages still fall back to regex / section header, and no downstream lesson / quiz / claims business logic changed
- The Phase 0 follow-up is now reflected in the branch: the contract authority, the `safe_sqlite_connect` SQLite connection helper, reparse/hardlink protections, serve CORS and `X-Frame-Options` headers, CLI cold start, and local baseline scripts all have matching implementation
- i18n-0: the locale resolver supports cookie / Accept-Language / CLI / config / `AHADIFF_LANG` / `LANG` fallback, and lesson/quiz prompt payloads carry the requested output-language instruction
- `ahadiff improve --suite local --rounds N`, which currently supports only `--suite local`. It selects a baseline from an existing finalized run, edits only an allowlisted prompt in a git worktree, replays the same diff, and rescores the candidate; the candidate must improve the target dimension plus `accuracy`, `evidence`, and `safety_privacy`, and hard gates must still pass. Passing candidates are cherry-picked back when possible and recorded as `event_type=improve` / `status=targeted_verify`; non-improving rounds are recorded as `discard`; cherry-pick conflicts leave a pending worktree without finalizing the run; two consecutive `discard` rounds in the same session trigger one Phase 2.5 worktree rewrite
- `src/ahadiff/eval/{rubric,gates,deterministic,evaluator,results,ratchet}.py` for the 8-dimension scorer, hard gates, result persistence, ratchet selection, and export rebuilds
- `src/ahadiff/review/{database,scheduler,schemas,signal}.py` for review.sqlite schema / migration, FSRS-6 scheduling, the review queue, learning signals, and the review CLI backend
- `src/ahadiff/improve/{loop,program,targeted,rewrite}.py` for improve sessions, the immutable improve_program prompt, worktree isolation, the 5 mutable-prompt allowlist, replay-learn, targeted verification, Phase 2.5 triggering, cherry-pick ordering, session validation, and pending-worktree resume guards
- runtime resource lookup that works in both source checkout and installed wheel mode for `eval_bundle_version`, `prompt_version`, and packaged lesson prompts
- `keep_final` is still a manual full 8-dimension recheck via `ahadiff db finalize-targeted <event_id>`; the improve loop does not auto-promote it. The `viewer/` React SPA is complete through Phase A-E with R1-R5 five-round cross-model deep review; v0.2 frontend Phase 1-4 adds 6 new pages (Review / Ratchet / Landing / Settings / Onboarding / Skills), 66 v6 design tokens, Skeleton loading component, review-store, per-route ErrorBoundary, and shared utility extraction. The same-day historical baseline raises i18n to 443/443 parity and full Playwright to 1245 tests; after the final review fixes, the rerun e2e proof is the walkthrough matrix at 390 tests. The frontend also adds the 1024px drawer boundary, SearchOverlay dynamic focus trap / inert handling, Quiz peek guard, Diff path normalization, API error redaction, a route-closure JS budget, Phase 4D Settings 8-tab sidebar / provider grid / audit log / privacy toggles, ClaimInspector/Diff V6 follow-up, Ratchet note card, PWA offline shell, and Quiz Archive/Suspend review queue-state writes; the Quiz page now reads `misconception_cards.jsonl` and keeps open-answer rows without `review_card_id` renderable instead of routing them into SRS by mistake

This round also closed several runtime edges: `prompt_version` still tracks AhaDiff's own prompt resources instead of any target-workspace `prompts/`; lesson JSON parsing skips schema-mismatched example blocks before accepting a real answer; the lesson/quiz chain is now wired into `learn`; lesson-generation failures now clean up newly written `claims.raw.jsonl` / `claims.jsonl`, `quiz/`, and `concepts_local.jsonl` half-artifacts; successful `learn` runs now write a `learn` event plus `score.json`; manual `score` / `verify` still do not contaminate the learn baseline; `ReviewCard` now validates `last_rating` and `card_state/stale_reason`; fake quiz artifacts no longer pass as a complete Stage-3 result. The pinned integration fixture was also tightened after that: tests now write `symbols.json`, generate `cards.jsonl` through `generate_cards_for_run()`, and validate every row as `ReviewCard`, so hand-written partial cards can no longer bypass the production contract. Task 15 is also fully hardened in this round: legacy `cards` schemas now migrate `stale_reason` explicitly, schema-invalid `cards.jsonl` is downgraded to warnings, repeated regenerate runs no longer leave old active cards in the due queue, `regenerate --only quiz` restores the previous quiz/cards artifacts if `evaluate_run` fails and deletes stale `cards.jsonl` plus marks active cards `stale + staleness_unknown` on `FAIL`, lossy TSV import now runs as a single-connection whole-batch import with rollback on bad rows or duplicate identities, `rollback_result_event` now does delete + export-row selection in one connection, and a plain DB connect no longer creates parent directories silently on typo paths. Task 16/17 now covers the `lesson_hint.md` allowlist entry, session-id path validation, a 30-minute replay timeout, paired prompt temp+replace writes, non-conflict cherry-pick failure handling, no `finalized.json` for discard or pending-conflict runs, pending conflicts excluded from the next baseline, volatile staged/unstaged replay from the saved `patch.diff`, shorter worktree paths, a `--rounds` cap of 20, null-byte rejection, Ctrl+C after a completed round no longer appending a second crash event, targeted verification, one Phase 2.5 trigger per session, and OpenAI-compatible provider endpoint normalization. This cache-key hardening also closes the API-version boundary for LLM calls: different `api_family_version` values under the same `api_family` now produce different cache keys, so compatible gateways or API-version changes do not reuse stale results.

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

Latest verification (2026-05-01, this session): `UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run --frozen --no-sync pytest tests -q -p no:cacheprovider --tb=short` = `1655 passed, 1 skipped in 60.50s`; `UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run --frozen --no-sync ruff check src tests` passed; `UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run --frozen --no-sync pyright` = `0 errors, 0 warnings, 0 informations`. The frontend gate `pnpm run typecheck && pnpm run lint && pnpm run test:unit && pnpm run build` passed, with unit tests at `60 passed`; the supplemental e2e run `pnpm exec playwright test tests/e2e/walkthrough.spec.ts --reporter=line` was `390 passed`. `pnpm run build` also checked 85,468 bytes of initial JS gzip and 117,137 bytes of Dashboard first-route JS gzip. The full Playwright `1245 passed`, i18n `443/443`, PWA preview probe, and full-tree `ruff format --check src tests` are earlier same-day historical baselines and were not rerun after the final review fixes. This session did not rerun the coverage gate, wheel build, `uv lock --check`, or the live judge; older coverage/wheel/lock/live-judge results should not be treated as fresh validation.

Roadmap:

- [ ] `v0.1` (MVP): CLI + Lesson + Evaluator + Ratchet end-to-end + React 19 WebUI (`ahadiff serve`) + 8 LLM Providers + 8 diff capture modes (incl. --unstaged / git show) + 6 install targets + i18n + stage gates
- [ ] `v0.2`: --compare-dir + --patch-url + 7 IDE install targets + watchdog incremental regeneration + section-level helpfulness + Team features (done: backend Gates 0-6 + medium APIs + helpfulness / learning transfer + misconception cards + Graphify backend foundations plus concept linking / derived ancestry / graph_nodes FTS import / 500-node benchmark fixture + watch mode + frontend Phase 1-4 + Phase 4D Settings UI + 5D ConceptGraph core UI + 13 install targets + LLM cache + usage.sqlite + Phase 2 gate follow-up; remaining: Team / Graphify provenance, per-run artifact policy, large-repo perf gate / 5E cross-page freshness polish / deeper V6 frontend signoff)
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

TBD (planned: MIT).

---

> AhaDiff / 知返 — Δ知 ↺
