# RFC 2.3 — Diffity-style Learning Loop

**Status**: DRAFT — design only, no implementation
**Date**: 2026-05-12
**Authors**: Claude (orchestrator)
**Scope**: Optional hands-on track layered above existing `learn → quiz → review`; zero impact on N-file contract, evaluation bundle, or `result_events`.

## 1. Motivation & Target Users

AhaDiff verifies AI diffs via claims + quiz + FSRS (passive recall). Devs wanting **muscle-memory mastery** still need to re-derive the change by hand. RFC 2.3 adds an optional **build → tour → challenge → review → adapt** loop inspired by Diffity, targeting:

- Devs who passed `quiz` on a run and want hands-on consolidation.
- Code-review trainees reproducing a diff from a frozen baseline.
- AhaDiff dogfood: auto-generate challenges from runs with `score.json ≥ 80`.

Non-goal: replace `learn`/`quiz`/`review`. Opt-in, never gates release.

## 2. Five-Stage State Machine

| Stage | Purpose | Source | Output |
|-------|---------|--------|--------|
| **build** | Pre-stage challenge from a `run_id` | `runs/<run_id>/{patch.diff, claims.jsonl, lesson.md}` | `manifest.json` |
| **tour** | Read-only guided walkthrough | manifest + lesson `walkthrough_tldr` | UI state only |
| **challenge** | Learner edits baseline tree toward target | `.ahadiff/challenges/<id>/work/` | `attempts/<aid>/result.json` |
| **review** | Diff attempt vs canonical, map gaps to claims | attempt + claims | `attempts/<aid>/feedback.json` |
| **adapt** | Schedule weak claims into FSRS deck | feedback | rows in `review.sqlite` |

Transitions unidirectional; any stage may abort to `idle`. State persisted in `.ahadiff/challenges/<id>/state.json` with monotonic terminal logic mirroring `task_runner`.

## 3. Data Model

`ChallengeManifest` (Pydantic, `extra="forbid"`):
`challenge_id, source_run_id, baseline_sha, target_sha, hunks[], canonical_claim_ids[], created_at, schema_version=1`.

`AttemptResult`: `attempt_id, challenge_id, started_at, finished_at, learner_diff_path, status, gap_claim_ids[]`.

FSRS relationship: `adapt` only **inserts/updates** existing cards via the `signals` API (`mark-wrong`, `srs-review`). No new tables, no new card states; preserves `review.sqlite` v9. Gap claims map to concept ids via `concepts.jsonl`.

## 4. Security & Sandbox Boundary

- **No code execution.** Challenge is text-edit comparison; no `npm test`, no shell run. Learner edits files in `.ahadiff/challenges/<id>/work/`; `git diff` is parsed and structurally compared against canonical hunks.
- Worktree is gitignored, write-locked by the repo lock, removed on `adapt`. Reuses `improve/` no-follow / reparse / symlink-parent guards.
- All learner input flows through `UNTRUSTED_DIFF`: `redaction_pipeline()` before any prompt/log/render.
- No new auth surface; serve endpoints reuse `X-AhaDiff-Token`.

## 5. Local-First Privacy

All artifacts under `<repo>/.ahadiff/challenges/`. Zero network in stages 1–4; `adapt` writes only to local `review.sqlite`. Optional hints reuse the current privacy tier — `strict_local` disables them.

## 6. Cross-Platform

Manifests carry **structural hunks** (path + symbol + line offset), not shell commands. The single optional verify is `git diff --no-color` parsed by AhaDiff — no `bash`/`PowerShell` divergence. Copy actions reuse the POSIX/PowerShell split block.

## 7. Frontend Interaction

New `/#/challenge/<id>` route with five panels keyed to stages. Each is keyboard-navigable, exposes `aria-current="step"`, degrades to a list when canvas unavailable, follows existing motion/elevation tokens. SearchOverlay deep-links by challenge id.

## 8. Test Strategy

- **Unit**: state-machine transitions (legal/illegal edges), manifest schema, attempt diff matcher.
- **Integration**: build-from-run on a pinned fixture; assert `feedback.json` claim mapping.
- **E2E (Playwright)**: full five-stage flow on a synthetic 3-hunk diff.
- **Property**: `adapt → review` round-trip never corrupts existing FSRS rows.

## 9. Release Gate

Feature flag `ahadiff.challenge.enabled` (default OFF). All existing CLI/UI/serve routes unchanged when disabled. CI: existing `learn/quiz/review` suites stay green; no coverage regression; `pyright` 0 errors.

## 10. Out of Scope (Explicit NO)

- No online coding sandbox, no cloud execution, no remote build.
- No shell-command challenges, no test-runner integration.
- No new evaluation dimension; no change to 8-dim rubric or evaluation bundle.
- No new auth model; no new SQLite schema beyond reuse.
