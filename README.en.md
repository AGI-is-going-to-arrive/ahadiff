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

The current code already ships Lesson / Claims / Quiz / Cards / Score / Ratchet. The review-flow SRS runtime, serve backend, install targets, GitHub Action templates, benchmark suite, improve-loop core, Task 17 targeted verification, Phase 2.5 runtime, and i18n-0 backend are landed. React Viewer remains in a later stage.

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

# Plan-then-implement-then-learn loop
ahadiff plan "add OAuth login"
ahadiff learn HEAD~1..HEAD --against .ahadiff/specs/oauth-login/SPEC.md

# Review
ahadiff quiz abc123
ahadiff review

# Interactive browser UI (Quiz/SRS/Dashboard)
ahadiff serve

# Ratcheted self-improvement (Task 16/17 backend is landed; requires an existing finalized run and provider configuration)
ahadiff improve --suite local --rounds 6

# Install into AI tools and automation (v0.1: 6 targets)
ahadiff install claude    # Claude Code → .claude/skills/
ahadiff install codex     # Codex CLI → AGENTS.md
ahadiff install gemini    # Gemini CLI → GEMINI.md
ahadiff install opencode  # OpenCode → AGENTS.md + .opencode/agents/
ahadiff install hooks     # git hooks
ahadiff install github-action          # verify-only workflow
ahadiff install github-action --layer2 # opt-in generate workflow (requires provider secret)
# v0.2: cursor / copilot / windsurf / cline / amp / jules / aider
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
│     ├─ quiz.jsonl
│     └─ cards.jsonl     # Only written for PASS / CAUTION runs
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
├─ src/ahadiff/contracts/       # Stage 0 minimal contracts skeleton
├─ src/ahadiff/core/            # Stage 1 / Task 1 scaffold
├─ src/ahadiff/safety/          # Stage 1 / Task 2 safety primitives
├─ src/ahadiff/llm/             # Layer 1.5 / Task 7 provider + probe
├─ src/ahadiff/git/             # Stage 2 / Task 5-6 diff capture + structuring
├─ src/ahadiff/claims/          # Stage 2 / Task 8 claim extraction + verification + runtime
├─ src/ahadiff/lesson/          # Stage 3 / Task 8.5 + 9 learnability + lesson generation
├─ src/ahadiff/quiz/            # Stage 3 / Task 10 quiz + cards
├─ src/ahadiff/wiki/            # Stage 3 / Task 10 concepts ledger
├─ src/ahadiff/eval/            # Stage 3 / Task 11-12 evaluator + ratchet + results
├─ src/ahadiff/serve/           # Task 14.5 local serve API / finalized run gate
├─ src/ahadiff/install/         # Task 19/20 install targets + GitHub Action templates
├─ src/ahadiff/i18n/            # i18n-0 locale resolver / prompt language helper
├─ src/ahadiff/prompts/         # Prompt resources packaged into the wheel
├─ prompts/                     # Lesson / claim prompt templates
├─ src/ahadiff/improve/         # Stage 5 / Task 16/17 improve loop, targeted verify, Phase 2.5
├─ benchmarks/                  # Task 18 local benchmark fixtures + manifest
├─ tests/unit/                  # Stage 0-6 and i18n-0 unit tests
├─ tests/eval/                  # benchmark suite tests
├─ tests/integration/           # pinned integration fixtures
├─ tests/live/                  # Opt-in real LLM judge smoke
├─ ui/                          # HTML prototypes v1–v6 (design history)
└─ CLAUDE.md                    # Project AI context index
```

## Status

**Stage 1 Task 1/2, Layer 1.5 / Task 7, Stage 2 / Task 5/6/8, Stage 3 / Task 8.5/9/10/11/12, Stage 4 / Task 15, Stage 5 / Task 16/17, Stage 6 / Task 18/19/20, and the i18n-0 backend are now landed.** The current codebase already has:

- the `ahadiff learn` main path for git and non-git capture (`--patch` / `--compare`), followed by learnability gating, `claims.raw.jsonl -> claims.jsonl`, and full / hint / compact lesson output
- `ahadiff quiz` for a minimal interactive quiz loop backed by `quiz.jsonl`, with source-claim and file-line evidence printed back to the user
- `cards.jsonl` / `concepts.jsonl`: cards are generated for scored PASS / CAUTION runs; git-backed runs write the repo-global `concepts.jsonl`, while non-git runs write `concepts_local.jsonl`
- `ahadiff score`, `ahadiff verify`, and `ahadiff export-results`, backed by `review.sqlite` as the single source of truth and `results.tsv` as an export view
- `ahadiff review`, `ahadiff mark <claim_id> wrong`, and `ahadiff db {backup,restore,check,import-results,finalize-targeted}` for the landed review.sqlite review / signals / result-events / lossy-import / targeted-finalize path
- `ahadiff serve`: the localhost-only serve backend is available. Read routes expose finalized runs only; write routes require token plus Origin/Referer checks
- `ahadiff install`: Claude / Codex / Gemini / OpenCode / hooks / GitHub Action targets are available. The generate workflow uses `AHADIFF_PROVIDER_API_KEY` and uploads `.ahadiff/` outputs as an artifact
- `ahadiff benchmark`: the local benchmark manifest, 20 eval fixtures, 10 pinned integration fixtures, and `ground_truth.md` consistency checks are available
- i18n-0: the locale resolver supports cookie / Accept-Language / CLI / config / `AHADIFF_LANG` / `LANG` fallback, and lesson/quiz prompt payloads carry the requested output-language instruction
- `ahadiff improve --suite local --rounds N`, which currently supports only `--suite local`. It selects a baseline from an existing finalized run, edits only an allowlisted prompt in a git worktree, replays the same diff, and rescores the candidate; the candidate must improve the target dimension plus `accuracy`, `evidence`, and `safety_privacy`, and hard gates must still pass. Passing candidates are cherry-picked back when possible and recorded as `event_type=improve` / `status=targeted_verify`; non-improving rounds are recorded as `discard`; cherry-pick conflicts leave a pending worktree without finalizing the run; two consecutive `discard` rounds in the same session trigger one Phase 2.5 worktree rewrite
- `src/ahadiff/eval/{rubric,gates,deterministic,evaluator,results,ratchet}.py` for the 8-dimension scorer, hard gates, result persistence, ratchet selection, and export rebuilds
- `src/ahadiff/review/{database,scheduler,schemas,signal}.py` for review.sqlite schema / migration, FSRS-6 scheduling, the review queue, learning signals, and the review CLI backend
- `src/ahadiff/improve/{loop,program,targeted,rewrite}.py` for improve sessions, the immutable improve_program prompt, worktree isolation, the 5 mutable-prompt allowlist, replay-learn, targeted verification, Phase 2.5 triggering, cherry-pick ordering, session validation, and pending-worktree resume guards
- runtime resource lookup that works in both source checkout and installed wheel mode for `eval_bundle_version`, `prompt_version`, and packaged lesson prompts
- `keep_final` is still a manual full 8-dimension recheck via `ahadiff db finalize-targeted <event_id>`; the improve loop does not auto-promote it. React Viewer is not implemented yet

This round also closed several runtime edges: `prompt_version` still tracks AhaDiff's own prompt resources instead of any target-workspace `prompts/`; lesson JSON parsing skips schema-mismatched example blocks before accepting a real answer; the lesson/quiz chain is now wired into `learn`; lesson-generation failures now clean up newly written `claims.raw.jsonl` / `claims.jsonl`, `quiz/`, and `concepts_local.jsonl` half-artifacts; successful `learn` runs now write a `learn` event plus `score.json`; manual `score` / `verify` still do not contaminate the learn baseline; `ReviewCard` now validates `last_rating` and `card_state/stale_reason`; fake quiz artifacts no longer pass as a complete Stage-3 result. Task 15 is also fully hardened in this round: legacy `cards` schemas now migrate `stale_reason` explicitly, schema-invalid `cards.jsonl` is downgraded to warnings, repeated regenerate runs no longer leave old active cards in the due queue, `regenerate --only quiz` restores the previous quiz/cards artifacts if `evaluate_run` fails and deletes stale `cards.jsonl` plus marks active cards `stale + staleness_unknown` on `FAIL`, lossy TSV import now runs as a single-connection whole-batch import with rollback on bad rows or duplicate identities, `rollback_result_event` now does delete + export-row selection in one connection, and a plain DB connect no longer creates parent directories silently on typo paths. Task 16/17 now covers the `lesson_hint.md` allowlist entry, session-id path validation, a 30-minute replay timeout, paired prompt temp+replace writes, non-conflict cherry-pick failure handling, no `finalized.json` for discard or pending-conflict runs, pending conflicts excluded from the next baseline, volatile staged/unstaged replay from the saved `patch.diff`, shorter worktree paths, a `--rounds` cap of 20, null-byte rejection, Ctrl+C after a completed round no longer appending a second crash event, targeted verification, one Phase 2.5 trigger per session, and OpenAI-compatible provider endpoint normalization.

Current minimal verification:

```bash
source .venv/bin/activate && pytest tests/unit -q
source .venv/bin/activate && ruff check src tests
source .venv/bin/activate && ruff format --check src tests
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

Actual result from this session: `uv run --frozen --no-sync pytest tests/unit -q` finished with `455 passed`; `uv run --frozen --no-sync pytest tests/eval -q` finished with `7 passed`; `uv run --frozen --no-sync pytest tests/integration/test_learn_pipeline.py -m pinned -q` finished with `10 passed`; `PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run --frozen --no-sync pytest -p no:cacheprovider tests -q` finished with `472 passed, 1 skipped` (the live judge smoke is skipped by default); the explicit live judge smoke finished with `1 passed`, and `gpt-5.3-codex-spark` was verified on its own; `uv run --frozen --no-sync ruff check --no-cache src tests`, `uv run --frozen --no-sync ruff format --check --no-cache src tests`, `uv run --frozen --no-sync pyright`, `uv build --wheel`, and `uv run --frozen --no-sync python -m ahadiff install github-action --help` all passed.

Roadmap:

- [ ] `v0.1` (MVP): CLI + Lesson + Evaluator + Ratchet end-to-end + React 19 WebUI (`ahadiff serve`) + 8 LLM Providers + 8 diff capture modes (incl. --unstaged / git show) + 6 install targets + i18n + stage gates
- [ ] `v0.2`: --compare-dir + --patch-url + 7 IDE install targets + watchdog incremental regeneration + section-level helpfulness + Team features
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
