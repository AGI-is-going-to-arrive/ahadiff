# AhaDiff (知返)

> **Ship with AI. Learn it back.**
>
> Every AI-written git diff becomes a verified Aha lesson, with code-linked evidence, active-recall quizzes, spaced review, and a self-improving quality ratchet.

[中文](./README.zh.md) · [User Guide](./docs/USER_GUIDE.en.html) · [English tutorial video](./docs/video/output/ahadiff-tutorial.en.burned-subtitles.mp4) · [Chinese tutorial video](./docs/video/output/ahadiff-tutorial.zh.burned-subtitles.mp4)

---

## What it is

**AhaDiff** is a **local-first learning layer for AI coding**.

It is not a PR summary, not a repo wiki, and not another generic code explainer. It reads a git diff and turns the change into:

- A **lesson** that teaches what changed and why
- A **claims ledger** where conclusions trace back to `file:line` evidence
- A **quiz and review loop** so the knowledge comes back later
- A **quality history** that makes runs comparable over time

All data lives in `.ahadiff/` per repo. `review.sqlite` is the single source of truth.

> Code Wiki explains a repo. AhaDiff teaches you what changed, and verifies every claim against the diff.

## Why

AI writes code faster, but developers can understand less of what actually changed. AhaDiff exists to close that loop:

1. **AI ships, understanding returns to humans** — a commit message is not enough.
2. **Every claim needs evidence** — no hallucinated functions, no fabricated causality.
3. **Knowledge should compound** — repeated concepts should build history and backlinks.
4. **Quality should be comparable** — replace "looks fine" with a stable score and ratchet.

## Prerequisites

- Python 3.11+
- git (on PATH)
- [uv](https://docs.astral.sh/uv/) — install with `curl -LsSf https://astral.sh/uv/install.sh | sh` or `brew install uv`
- An LLM provider: remote (OpenAI / Anthropic / Gemini / Azure / any OpenAI-compatible) with API key, or local (LM Studio / Ollama, no key needed)

## Install

AhaDiff is not on PyPI yet. Install from source:
```bash
git clone https://github.com/agi-is-coming/ahadiff.git
cd ahadiff
uv tool install --editable .
ahadiff --version   # should print ahadiff 1.1.0a0
```

## Configure a provider

AhaDiff needs an LLM to generate lessons. Set up once per repo:
```bash
ahadiff init

# Register and test a provider (example: OpenAI)
export OPENAI_API_KEY="sk-..."
ahadiff provider test \
  --name default \
  --provider-class openai \
  --base-url https://api.openai.com/v1 \
  --api-key-env OPENAI_API_KEY
```
`provider test` sends a small probe request. If it succeeds, the provider is saved to `.ahadiff/config.toml`.

Supported provider classes: `openai`, `openai_responses`, `gemini`, `anthropic`, `azure`, `newapi`, `lmstudio`, `ollama`. See [User Guide](./docs/USER_GUIDE.en.html) for details.
> AhaDiff defaults to strict_local privacy — nothing leaves your machine unless you explicitly configure a remote provider.

## Your first lesson

```bash
# Learn from your latest commit
ahadiff learn --last

# Open the local web UI to read your lesson
ahadiff serve
```
Open http://localhost:8765 in your browser. You'll see the Dashboard with your first run — click through to Lesson, Diff, and Quiz.

Two more things to try:
```bash
ahadiff quiz <run_id>    # test yourself on what you just learned
ahadiff review           # spaced-repetition review of past cards
```
See the [User Guide](./docs/USER_GUIDE.en.html) for all 9 diff capture modes, export options, concept graphs, and advanced commands.

## Features

- **Learn**: `ahadiff learn` supports 9 diff capture modes: git commit, range, time-window (`--since`), staged, unstaged, patch, patch URL, file compare, and directory compare.
- **Evidence-linked claims**: every lesson conclusion is tied to `file:line` evidence, with verification states such as verified, weak, not proven, contradicted, and rejected.
- **Quiz and review**: `ahadiff quiz` tests the run you just learned; `ahadiff review` brings back older cards with spaced repetition. Quiz count is fixed by default and can adapt to diff size when enabled.
- **Scoring**: each run gets an 8-dimension score, with an optional LLM judge when configured.
- **WebUI**: `ahadiff serve` opens Dashboard, Lesson, Diff, Quiz, Review, Concepts, Run Detail, Settings, and Guide.
- **Export**: export results as TSV / JSON, Anki `.apkg`, or a local static preview bundle.
- **Concept graph**: AhaDiff extracts cross-diff concepts and shows them in a Canvas graph with health checks.
- **AI tool integration**: project-level guidance for Claude, Cursor, Copilot, Codex, Gemini, Aider, and more.
- **Auto-iteration**: `ahadiff improve` optimizes prompts in an isolated worktree and keeps only better results.
- **MCP server**: read-only stdio MCP server for local MCP-capable agents.
- **Privacy**: three tiers: strict_local, redacted_remote, explicit_remote. The default is strict_local.
- **i18n**: English and Chinese across CLI, WebUI, and prompt output language.
- **Cross-platform**: macOS, Linux, Windows, Python 3.11+.
- **Security**: URL secret redaction, provider URL validation, input validation, prompt injection detection, and safety hard gates.

## Screenshots

<p align="center">
  <img src="./docs/video/public/screenshots/en/en-dashboard.png" alt="Dashboard — runs, scores, ratchet trajectory" width="800">
</p>

<details>
<summary>Lesson — AI-generated lesson from your diff</summary>
<img src="./docs/video/public/screenshots/en/en-lesson.png" alt="Lesson page" width="800">
</details>

<details>
<summary>Diff Viewer — claim-linked code evidence</summary>
<img src="./docs/video/public/screenshots/en/en-diff.png" alt="Diff viewer with claim highlights" width="800">
</details>

<details>
<summary>Quiz — active recall from the lesson</summary>
<img src="./docs/video/public/screenshots/en/en-quiz.png" alt="Quiz page" width="800">
</details>

<details>
<summary>Review — spaced repetition cards</summary>
<img src="./docs/video/public/screenshots/en/en-review.png" alt="Review page" width="800">
</details>

<details>
<summary>Concept Graph — cross-diff knowledge map</summary>
<img src="./docs/video/public/screenshots/en/en-concepts-graph.png" alt="Concept graph" width="800">
</details>

<details>
<summary>Run Detail — scores and evaluation breakdown</summary>
<img src="./docs/video/public/screenshots/en/en-rundetail-overview.png" alt="Run detail overview" width="800">
</details>

<details>
<summary>Settings — provider and preferences</summary>
<img src="./docs/video/public/screenshots/en/en-settings.png" alt="Settings page" width="800">
</details>

## AI tool integration

AhaDiff writes project-level guidance into your AI tool so it knows about your learning history:
```bash
ahadiff install --detect        # auto-detect your tools
ahadiff install claude          # also: cursor, copilot, codex, gemini, aider, windsurf, cline, roo, continue, ...
```
13 targets supported. Run `ahadiff install --help` for the full list, or configure in the WebUI under Settings → AI Tool Guidance.

## 8-Dimension Rubric

| # | Dimension | Weight | Hard gate |
|---|-----------|--------|-----------|
| 1 | Accuracy | 20 | < 14 → FAIL |
| 2 | Evidence | 18 | < 12 → FAIL |
| 3 | Diff Coverage | 14 | < 7.70 → FAIL |
| 4 | Learnability | 14 | — |
| 5 | Quiz Transfer | 10 | — |
| 6 | Spec Alignment | 10 | — |
| 7 | Conciseness | 8 | — |
| 8 | Safety & Privacy | 6 | Unmitigated Critical → FAIL |

Three verdicts: **PASS** ≥ 80 / **CAUTION** 60–80 / **FAIL** < 60.

## Repository Layout

```text
ahadiff/
├─ src/ahadiff/         # Python source
├─ viewer/              # React 19 frontend
├─ tests/               # Test suite
├─ prompts/             # LLM prompt templates
├─ benchmarks/          # Eval benchmark fixtures
├─ docs/                # Landing page, user guides, tutorial videos
├─ .github/workflows/   # CI/CD
├─ pyproject.toml       # Python package config
└─ LICENSE              # MIT
```

## Core Philosophy (N-File Contract)

AhaDiff extends the Karpathy / autoresearch three-file contract into an N-file variant:

| File | Who edits | Role |
|------|-----------|------|
| `program.md` | Human | Natural-language state machine for the improve loop |
| evaluation bundle | **Immutable** | `evaluator.py` + `rubric.py` + `rubric.yaml` + `gates.py` + `deterministic.py`, locked as a unit |
| `prompts/*.md` | Agent | The improve loop edits only allowlisted generation prompts; `eval_judge.md` is a judge prompt resource, not part of that writable set |

Loop: edit → commit → evaluate → keep if better, reset if worse → record the result for review and future runs.

## Inspirations, Design Axioms, and License

### Inspirations

- **karpathy/autoresearch** — N-file contract and git ratchet
- **alchaincyf/darwin-skill** — 8-dimension rubric and Phase 2.5 rewrite
- **Evol-ai/SkillCompass** — PASS / CAUTION / FAIL and weakest-dimension-first
- **ZJU-REAL/SkillZero** — helpfulness-driven retention and compact context
- **safishamsi/graphify** — repo-level graph overlay
- **karpathy/llm-wiki** gist — persistent compounding wiki

### Design Axioms

1. **Evidence first** — every claim must trace back to `file:line`
2. **Learning over summary** — quizzes and review beat pretty summaries
3. **Local-first trust** — privacy tiers are explicit, and local stays local by default
4. **Paper-like seriousness** — academic feel, not a loud SaaS landing page
5. **One accent per style** — warm paper background plus a single accent color

### License

[MIT](./LICENSE)

---

> AhaDiff / 知返 — Δ知 ↺
