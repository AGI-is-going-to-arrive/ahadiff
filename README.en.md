# AhaDiff (知返)

> **Ship with AI. Learn it back.**
>
> Every AI-written git diff becomes a verified Aha lesson — with code-linked evidence, active-recall quizzes, spaced review, and a self-improving quality ratchet.

[中文](./README.md) · [User Guide](./docs/USER_GUIDE.en.html) · [Chinese tutorial video](./docs/video/output/ahadiff-tutorial.zh.burned-subtitles.mp4) · [English tutorial video](./docs/video/output/ahadiff-tutorial.en.burned-subtitles.mp4) · [Design docs](./doc/) · [UI prototypes](./ui/)

---

## What it is

**AhaDiff** is a **local-first learning layer for AI coding**.

It's not a PR summary, not a repo wiki, not yet another "code explainer." It reads every git diff and turns the change into:

- A **lesson** with `file:line` evidence chains
- A **claims** ledger where every assertion traces back to a hunk
- A comparable **quality score history** (ratcheted; `review.sqlite` is the single source of truth, while `results.tsv` and JSON exports are views)

The current code reliably produces Lesson / Claims / Quiz / Cards / Score / Ratchet, including SRS review, WebUI, 13 AI tool install targets, 8-dimension scoring + LLM judge, en/zh i18n, and `improve` auto-iteration.

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

The commands below match the current CLI. AhaDiff is not published on PyPI yet. In a source checkout, use `uv run ahadiff ...`, or install the local CLI with `uv tool install --editable .`. After a local editable install or a local wheel install, use `ahadiff ...` directly.

```bash
# Install the local CLI from an AhaDiff source checkout
uv tool install --editable .

# Or run directly from the source checkout
uv run ahadiff --version

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
ahadiff serve --watch  # requires the watchdog extra

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

ahadiff learn --last

# Pass explicit provider/model flags only for a one-off override
ahadiff learn --last --provider gpt55 --model gpt-5.5
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
│  ├─ contract-freeze.md        # Architecture contract authority
│  ├─ ahadiff设计思路.md          # [ARCHIVED] Early architecture snapshot
│  ├─ 知返ahadiff改名后的后续方案.md  # [ARCHIVED] Rename transition plan
│  └─ AhaDiff_frontend_design_v1.1_revised.md  # Frontend design manual
├─ src/ahadiff/contracts/       # Enums, DTOs, error types
├─ src/ahadiff/core/            # Config, paths, IDs, JSON/SQLite safety helpers, task runner
├─ src/ahadiff/safety/          # Redaction, injection detection, safety gates
├─ src/ahadiff/llm/             # LLM provider + probe + cache
├─ src/ahadiff/git/             # Diff capture + structured parsing
├─ src/ahadiff/claims/          # Claim extraction + verification + runtime
├─ src/ahadiff/lesson/          # Learnability gate + three-tier lesson generation
├─ src/ahadiff/quiz/            # Quiz + cards + misconception cards
├─ src/ahadiff/wiki/            # concepts.jsonl + health lint
├─ src/ahadiff/challenge/       # Opt-in challenge mode + diff gap review
├─ src/ahadiff/export/          # Local static preview + deterministic zip
├─ src/ahadiff/graphify/        # Concept graph backend
├─ src/ahadiff/eval/            # 8-dimension scorer + spec alignment + ratchet + LLM judge
├─ src/ahadiff/mcp/             # Read-only MCP server (7 tools)
├─ src/ahadiff/serve/           # Local WebUI serve API (72 routes)
├─ src/ahadiff/install/         # 13 install targets + hooks
├─ src/ahadiff/i18n/            # Locale resolver + prompt language
├─ src/ahadiff/review/          # review.sqlite / FSRS-6 / APKG export
├─ src/ahadiff/prompts/         # Prompt resources packaged into the wheel
├─ prompts/                     # Lesson / claim / quiz / eval judge prompt templates
├─ src/ahadiff/improve/         # Improve loop, targeted verify, Phase 2.5
├─ benchmarks/                  # Benchmark fixtures + manifest + scripts
├─ tests/unit/                  # Unit tests
├─ tests/eval/                  # benchmark suite tests
├─ tests/integration/           # pinned integration fixtures
├─ tests/live/                  # Opt-in real LLM judge smoke
├─ viewer/                      # React 19 + Vite + Zustand + vanilla CSS frontend (14 production page TSX / 52 non-test TSX / 47 CSS / 1490 i18n scalar keys; Phase 2: Challenge pages, Export modal, HealthBadge; latest completion audit: backend unit 2530 + viewer Vitest 365 + i18n 1490; full Playwright gate is 2945 passed / 10 skipped)
├─ ui/                          # HTML prototypes v1–v6 (design history)
└─ CLAUDE.md                    # Project AI context index
```

## Feature Status

Available features:

- **Learn**: `ahadiff learn` supports 8 diff capture modes (git commit/range/staged/unstaged/patch/patch-url/compare/compare-dir), with Notebook cell-aware diffs and path scoping
- **Claim verification**: Every lesson conclusion is bound to `file:line` evidence, with five verification states (verified/weak/not_proven/contradicted/rejected)
- **Quiz & review**: `ahadiff quiz` for active-recall testing + `ahadiff review` for spaced repetition (FSRS-6 algorithm)
- **Scoring**: 8-dimension rubric (accuracy/evidence/diff_coverage/learnability/quiz_transfer/spec_alignment/conciseness/safety_privacy), with optional LLM judge
- **WebUI**: `ahadiff serve` launches a local web interface with Dashboard / Lesson / Diff / Quiz / Review / Concepts / Run Detail / Settings / Guide (14 pages total)
- **Export**: TSV / JSON / Anki `.apkg` export + local static preview bundles
- **Concept graph**: Automatic cross-diff concept extraction with Canvas visualization and health lint
- **AI tool integration**: 13 install targets (Claude / Cursor / Copilot / Codex / Gemini and more), one-command project-level AI tool guidance
- **Auto-iteration**: `ahadiff improve` optimizes prompts in an isolated worktree — quality only goes up
- **MCP Server**: Read-only stdio MCP server with 7 tools, consumable by Claude / Cursor and other AI tools
- **Privacy**: Three tiers (strict_local / redacted_remote / explicit_remote), defaults to strict_local
- **i18n**: Full English/Chinese support across CLI, WebUI, and prompt output language
- **Cross-platform**: macOS / Linux / Windows, Python 3.11+
- **Security**: URL secret redaction, DNS pinning, input validation, prompt injection detection, `safety_findings.json` hard gate

Current minimal verification:

```bash
uv run pytest tests/unit -q
uv run ruff check src tests
uv run pyright
uv build --wheel
uv run ahadiff quiz --help
uv run ahadiff review --help
uv run ahadiff improve --help
uv run ahadiff db check --help
uv run ahadiff install github-action --help
```

The live LLM judge smoke is opt-in. The example below uses GPT-5.5; if `AHADIFF_LIVE_LLM_MODELS` is omitted, the test uses the default model order from the code:

```bash
AHADIFF_LIVE_LLM_JUDGE=1 \
AHADIFF_LIVE_LLM_API_KEY="$AHADIFF_LIVE_LLM_API_KEY" \
AHADIFF_LIVE_LLM_BASE_URL="$AHADIFF_LIVE_LLM_BASE_URL" \
AHADIFF_LIVE_LLM_MODELS="gpt-5.5" \
pytest tests/live/test_llm_judge_live.py -q
```

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
