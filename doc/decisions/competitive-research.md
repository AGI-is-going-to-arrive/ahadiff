# Competitive Research — Feature Gap Summary (2026-05-10)

## Top 13 Actionable Features (prioritized)

| # | Feature | Source | Effort | Priority |
|---|---------|--------|--------|----------|
| 1 | AnkiConnect / `.apkg` export | Anki | S (1-2d) | High |
| 2 | Cloze deletion quiz type | Anki/SuperMemo | M (3-4d) | High |
| 3 | Easy Days + deeper retention tuning | Anki FSRS | S (1d) | High |
| 4 | Freshness → review priority weight | CogDebt + Graphify | S (1-2d) | High |
| 5 | Image Occlusion (diff hunk masking) | SuperMemo | M (4-5d) | High |
| 6 | `ahadiff summarize <commit-range>` PR mode | Copilot PR summary | M (3-4d) | High |
| 7 | `ahadiff concepts compact` wiki synthesis | Karpathy LLM Wiki | M (4-5d) | High |
| 8 | Q&A endpoint with citations | Notion Q&A | M (3-4d) | High |
| 9 | Local graph view (per-concept) | Obsidian | S (2d) | High |
| 10 | FSRS personal optimizer | Anki | M (3d) | Medium |
| 11 | Hunk-level lesson split | GitButler | L (1wk) | Medium |
| 12 | `ahadiff onboard <repo>` onboarding mode | code-archaeologist | L (1-2wk) | Medium |
| 13 | Diff sandbox quiz (interactive) | GitByBit | L (2wk) | Low |

## Explicit "Not Doing"
- Virtual branches / Git client features
- AI commit message generation
- Multi-user collaboration / cloud sync
- Native mobile app (PWA is sufficient)
- Autonomous agents beyond improve loop

## Current Session Status

These features are logged for future planning. They are not claimed as landed by
this research note.

This session landed a narrower hardening slice instead:

- stable API error codes and frontend error localization
- per-request locale plus locale persistence
- claim extraction `output_lang` threading
- git executable detection and hook subprocess hardening
- generated verify workflow Windows smoke coverage
- localized byte/token formatting

External source links were not re-fetched during this docs sync.
