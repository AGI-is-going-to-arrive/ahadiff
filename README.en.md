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
- A **concept graph** of ideas introduced by this diff
- **Quiz** questions for active recall
- **SRS cards** for future spaced review
- A comparable **quality score history** (ratcheted; `review.sqlite` is the single source of truth, `results.tsv` is a human-readable export)

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

# Ratcheted self-improvement
ahadiff improve abc123 --rounds 6

# Install into your AI tool (v0.1: 4 core CLI targets)
ahadiff install claude    # Claude Code → .claude/skills/
ahadiff install codex     # Codex CLI → AGENTS.md
ahadiff install gemini    # Gemini CLI → GEMINI.md
ahadiff install opencode  # OpenCode → AGENTS.md + .opencode/agents/
# v0.2: cursor / copilot / windsurf / cline / amp / jules / aider
```

Output layout:

```text
.ahadiff/
├─ config.toml           # Per-repo config
├─ review.sqlite         # Single source of truth (SRS/results/signals)
├─ concepts.jsonl        # Concept graph (term_key-keyed upsert)
├─ runs/<run_id>/
│  ├─ lesson/
│  │  ├─ lesson.full.md
│  │  ├─ lesson.hint.md
│  │  └─ lesson.compact.md
│  ├─ claims.jsonl       # Verifiable assertions
│  ├─ quiz/
│  │  └─ quiz.jsonl      # Active-recall questions
│  ├─ cards.jsonl        # SRS review cards
│  └─ score.json         # 8-dimension score + verdict
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
├─ tests/unit/                  # Stage 0 + Stage 1 + Layer 1.5 + Stage 2 unit tests
├─ ui/                          # HTML prototypes v1–v6 (design history)
└─ CLAUDE.md                    # Project AI context index
```

## Status

**Stage 1 Task 1/2, Layer 1.5 / Task 7, and Stage 2 / Task 5-6 are now landed.** The repository now contains the contract freeze doc, a minimal importable contracts skeleton, `pyproject.toml`, an executable CLI scaffold (`ahadiff init` / `ahadiff doctor` / `ahadiff config show --resolved` / `ahadiff provider test` / `ahadiff maint clean-orphans` / `python -m ahadiff`), the safety-layer primitives under `src/ahadiff/safety/`, `src/ahadiff/llm/{provider,probe,cache,cost}.py` plus eight provider adapters, and `src/ahadiff/git/{__init__,repo,capture,parser,path_tokens,line_map,symbols,hunk_hash}.py`, `ahadiff learn --dry-run`, non-git `--patch` / `--compare` support that also reads workspace `.ahadiff/config.toml`, `ahadiff graph status|import|refresh`, `ahadiff unlock --force`, `line_map.json` / `symbols.json` / `artifact_set.json`, and the Stage 0 + Stage 1 + Layer 1.5 + Stage 2 unit tests. Evaluator and viewer runtime work are still pending.

This round also hardened a few runtime edges: `.ahadiffignore` is now wired into the capture path, cross-line secret / prompt-injection payloads are blocked, `--staged --unstaged` now emits an explicit `git_staged_unstaged` source kind, git-sourced patch reads enforce a byte cap, parser/path/symbol extraction handle stricter edge cases, and the provider concurrency plus audit rotation paths have been tightened.

Current minimal verification:

```bash
uv run pytest tests/unit
uv run ruff check src tests
uv run ruff format --check src tests
uv run pyright
uv build --wheel
uv run python -m ahadiff --version
uv run ahadiff init
uv run ahadiff doctor
uv run ahadiff config show --resolved
```

Actual result from this session: `uv run pytest tests/unit` finished with `198 passed`; `uv run pytest tests/unit/test_stage1_task1.py tests/unit/test_contracts.py -q` finished with `42 passed`; the focused safety suite `uv run pytest tests/unit/test_redact.py tests/unit/test_injection.py tests/unit/test_path_safety.py tests/unit/test_allowlist.py -q` finished with `35 passed`; `uv run pytest tests/unit/test_probe.py tests/unit/test_provider.py -q` finished with `43 passed`; and `uv run pytest tests/unit/test_hunk_hash.py tests/unit/test_diff_parser.py tests/unit/test_line_map.py tests/unit/test_symbol_extract.py tests/unit/test_git_capture.py -q` finished with `78 passed`. `uv run ruff check src tests` and `uv run pyright` both passed. Two real provider checks also passed: a local loopback provider succeeded with `AHADIFF_PROVIDER_API_KEY=... ahadiff provider test --name local-probe --base-url "$AHADIFF_PROVIDER_BASE_URL" --model gpt-5.4-mini`, and a real `generate()` call through the same provider also succeeded. The `base_url` here must be the API root, not `/v1/chat/completions`.

Roadmap:

- [ ] `v0.1` (MVP): CLI + Lesson + Evaluator + Ratchet end-to-end + React 19 WebUI (`ahadiff serve`) + 8 LLM Providers + 8 diff capture modes (incl. --unstaged / git show) + 4 CLI install targets + i18n + stage gates
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
