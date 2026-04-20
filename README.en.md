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
- A comparable **quality score history** (`results.tsv`, ratcheted)

> Code Wiki explains a repo. AhaDiff teaches you what changed — and verifies every claim against the diff.

## Why

AI writes code faster, but developers know less about what they actually understood. "Vibe coding" sprints ahead; humans need to come back:

1. **AI ships, the understanding has to come back to humans** — a commit message isn't enough.
2. **Every claim must have evidence** — no hallucinated functions, no fabricated causality.
3. **Knowledge should compound** — when the same concept is touched again, the wiki should record evolution and backlinks.
4. **Quality should be comparable** — replace "looks fine" with an immutable evaluator and a git ratchet.

## Core Philosophy (Three-Layer Asymmetry)

Inherits the Karpathy / autoresearch design philosophy:

| File | Who edits | Role |
|------|-----------|------|
| `program.md` | Human | Natural-language state machine for the improve loop |
| `evaluator.py` | **Immutable** | The ruler — emits one scalar `lesson_score` |
| `generator_prompt.md` | Agent | The only "creative strategy" the agent may optimize |

LOOP: edit → commit → evaluate → keep if better, reset if worse → append to `results.tsv`.

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

# Ratcheted self-improvement
ahadiff improve abc123 --rounds 6

# Install into your AI tool (11 targets supported)
ahadiff install claude    # Claude Code → .claude/skills/
ahadiff install codex     # Codex CLI → AGENTS.md
ahadiff install cursor    # Cursor → .cursor/rules/
ahadiff install copilot   # GitHub Copilot
ahadiff install gemini    # Gemini CLI → GEMINI.md
ahadiff install windsurf  # Windsurf → .windsurf/rules/
# Also: opencode / cline / amp / jules / aider
```

Output layout:

```text
.ahadiff/
├─ index.md
├─ concepts.md
├─ commits/<sha>/
│  ├─ lesson.md          # Lesson with evidence chain
│  ├─ claims.jsonl       # Verifiable assertions
│  ├─ quiz.md            # Active-recall questions
│  └─ score.json         # 8-dimension score + verdict
├─ results.tsv           # Ratchet history (untracked)
└─ specs/<feature>/      # Plan → implement → learn loop
```

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
├─ AhaDiff Warm v6.html         # Latest UI prototype
├─ doc/                         # Design docs (Chinese)
│  ├─ ahadiff设计思路.md          # Full architecture (MVP → v1.0)
│  ├─ 知返ahadiff改名后的后续方案.md  # Brand redefinition + product upgrade
│  └─ AhaDiff_frontend_design_v1.1_revised.md  # Frontend design manual
├─ ui/                          # HTML prototypes v1–v6 (design history)
└─ CLAUDE.md                    # Project AI context index
```

## Status

**Pre-engineering (design phase).** The repository currently contains only design documents and HTML prototypes; the CLI, evaluator, and Skill packages have not yet been coded.

Roadmap:

- [ ] `v0.1` (3-day MVP): CLI + Lesson + Evaluator + Ratchet end-to-end
- [ ] `v0.2`: HTMX dashboard + watchdog incremental regeneration
- [ ] `v0.3`: Textual TUI + section-level helpfulness
- [ ] `v1.0`: Next.js + React 19 full UI + Benchmark Transparency page

## Inspirations

- **karpathy/autoresearch** — three-file contract + git ratchet
- **alchaincyf/darwin-skill** — 8-dimension rubric + Phase 2.5 rewrite
- **Evol-ai/SkillCompass** — PASS/CAUTION/FAIL + weakest-dimension-first
- **ZJU-REAL/SkillZero** — helpfulness-driven retention + compact context
- **safishamsi/graphify** — repo-level graph overlay
- **karpathy/llm-wiki** gist — persistent compounding wiki

## Design Axioms

1. **Evidence first** — every claim must trace back to `file:line`
2. **Learning over summary** — quizzes and review beat pretty summaries
3. **Local-first trust** — offline by default, every LLM call surfaced
4. **Paper-like seriousness** — academic feel; no cool-purple SaaS gradients
5. **One accent per style** — warm paper background + a single accent color

## License

TBD (planned: MIT).

---

> AhaDiff / 知返 — Δ知 ↺
