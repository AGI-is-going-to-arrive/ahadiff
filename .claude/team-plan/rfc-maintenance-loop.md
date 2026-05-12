# RFC 2.1 — Karpathy LLM Wiki Maintenance Loop

**Status**: IMPLEMENTED SUBSET — deterministic lint + schema v10 landed; Option B (LLM-assisted) remains deferred
**Owner**: AhaDiff core
**Inspiration**: Karpathy LLM Wiki (append-only idea) + current AhaDiff concept snapshot + Graphify freshness projection
**Goal**: keep long-lived concepts from silently rotting. Detect stale / contradicted / orphan / missing concepts and surface them without violating local-first.

**Current-code truth (2026-05-12)**:
- `src/ahadiff/wiki/concepts.py` still treats `concepts.jsonl` as a snapshot: it loads existing concepts, merges by `term_key`, then rewrites via temp-file replace. It is **not** an append-only event log today.
- The implemented path chose snapshot + SQLite derived state, not event-log marker replay.
- `review.sqlite` is now schema version 10 with `concept_status` and `concept_lint_runs`.
- `ahadiff concepts lint` currently implements deterministic lint only: orphan, deleted-file stale, line drift, and contradicted claim. LLM-assisted NLI / Option B is not implemented.
- Current Graphify external projection is `fresh / stale / unavailable / disabled`; do not invent unimplemented public freshness states.

## 1. Target Users

| Persona | Trigger | Value |
|---|---|---|
| Long-term AhaDiff dev (>30 runs) | Graph drift from refactors | Self-cleaning concept graph |
| Multi-feature repo maintainer | Concepts contradict newer runs | Trustworthy review surface |
| Knowledge-graph reader | Stale labels on Concepts page | Clear staleness signal |

## 2. Non-Target Users

| Persona | Reason |
|---|---|
| One-time `ahadiff learn` user | <3 runs, no drift accumulated |
| Strict-local user refusing any background job | Loop is opt-in via CLI/UI |
| User running on CI ephemeral repos | No persistent `concepts.jsonl` |

## 3. Data Model

| Surface | Constraint | Maintenance Extension |
|---|---|---|
| `concepts.jsonl` | Current snapshot rewrite | keep snapshot behavior, or explicitly migrate to an event log before adding markers |
| `review.sqlite` | Derived state | implemented `concept_status` table rebuilt from snapshot + deterministic lint source |
| `review.sqlite` | — | implemented `concept_lint_runs` table for lint run metadata |
| Graphify projection | Current public values: fresh/stale/unavailable/disabled | read-only consumer; missing/orphan is a lint finding, not an existing Graphify public status |

Open design decision: marker storage can be a new JSONL event log or SQLite-only derived state. Do not claim reset == replay until this is chosen and tested.

## 4. State Transitions

| Current source signal | Action |
|---|---|
| Graphify `fresh` | no-op |
| Graphify `stale` | mark `stale` if concept has no newer supporting evidence |
| Graphify `unavailable` / `disabled` | log only; do not mark stale based solely on missing Graphify |
| concept has zero current references | mark `orphan` |
| newer claims contradict older concept evidence | mark `contradicted` (gated — see §5) |
| user dismisses a finding | append/store `dismissed` marker with reason and timestamp |

Trigger: explicit `ahadiff concepts lint` CLI, post-`improve` hook (opt-in), or viewer button. Never automatic on `learn`.

## 5. Security Boundary — DECIDED: Option B (LLM-assisted)

| Dimension | Option A: Deterministic-only | Option B: LLM-assisted |
|---|---|---|
| Stale detection | refcount + Graphify staleness + last-evidence-age | same |
| Orphan detection | reference counting | same |
| Contradiction detection | exact-string negation + claim-status flips (verified→contradicted) | semantic NLI over claim pairs |
| Cost | $0, fully offline | BYOK provider, budgeted (cost cap + rate cap per lint) |
| Privacy | strict_local OK | requires `redacted_remote` or `explicit_remote` |
| False-positive risk | misses paraphrased contradictions | model hallucination on borderline cases |
| Determinism | reproducible | non-deterministic; needs LLM judge cache |
| Implementation surface | claims index + sqlite joins | reuse `llm/provider.py` + `eval_judge.md`-style prompt |

**Shared invariant**: maintenance records markers + suggestions without silently deleting concept history. Current implementation stores derived state in SQLite and does not add an append-only marker JSONL.

Decision for future work: Option B can be added later for semantic contradiction detection, gated by the existing privacy tier. Current code does not call an LLM from concept lint.

## 6. Local-First Privacy

| Concern | Decision |
|---|---|
| Remote sync | NONE. Markers stay in per-repo `.ahadiff/` |
| Telemetry | NONE |
| Option B traffic | Subject to existing redaction pipeline + privacy tier |
| Cross-repo learning | Forbidden (per-repo truth principle) |

## 7. Cross-Platform Impact

Pure Python + SQLite, but not "no impact": schema migration must cover macOS/Linux/Windows. Required before implementation:

- schema v10 migration registered, with upgrade tests;
- Windows NTFS reparse / symlink guards on any new concept-state artifact;
- macOS case-insensitive path collisions tested for concept ids / source paths;
- Linux CI covers WAL / busy_timeout / rollback behavior.

## 8. Frontend Interaction

| Surface | Change |
|---|---|
| Concepts row | badge `Stale` / `Contradicted` / `Orphan` + tooltip (evidence run, ts) |
| Concepts filter | new "Health" facet (all / healthy / needs-attention) |
| Concept detail | marker history timeline |
| Settings | manual "Run concept lint" + last-lint summary |
| i18n | new `concepts.health.*` scalar keys; en/zh-CN parity required |
| Destructive UI | none. "Dismiss marker" itself appends a `dismissed` marker |

## 9. Test Strategy

| Layer | Coverage |
|---|---|
| unit | deterministic contradiction; orphan (refcount=0); Graphify unavailable/disabled does not become stale; marker idempotency; derived `concept_status` rebuilds exactly; event-log migration tests only if chosen |
| integration | seed → contradicting run → `concepts lint` → marker appended + viewer payload reflects badge; strict_local skips Option B |
| live (opt-in, Option B) | LLM judge smoke under `AHADIFF_LIVE_LLM_JUDGE=1` |

Excluded: no perf SLA in v1; benchmark deferred until refcount > 10k.

## 10. Release Gate

| Check | Status |
|---|---|
| Eval bundle impact | none (markers stay out of 8-dim rubric) |
| Frozen enum changes | none (`ClaimStatus`/`RunSource`/`EvalBundle`/`EventLog` untouched) |
| New ErrorCode | not approved yet. Either reuse existing stable ErrorCode values or make an explicit ErrorCode bump plan with status mapping, frontend/i18n, and tests |
| Schema migration | implemented as schema v10 with `concept_status` / `concept_lint_runs` |
| Docs sync | CLAUDE.md modules table + viewer pages list |

## 11. What NOT to Do

| Forbidden | Reason |
|---|---|
| Auto-merge concepts | silent semantic loss |
| Auto-delete concepts | same |
| Remote sync of markers | violates per-repo truth + local-first |
| Background daemon | out of scope; trigger must be explicit |
| Edit `concepts.jsonl` in place without a migration decision | current code rewrites snapshots; marker semantics must be explicit before implementation |
| Write back into Graphify | projection is read-only |
| Inflate eval bundle | markers are governance, not evaluation |
| Run Option B under `strict_local` or without a configured privacy/cost gate | violates the §5 decision boundary |

---

**Next step**: decide whether Option B is still worth implementing. If yes, produce the module plan + UNITS.csv for LLM-assisted contradiction detection, including the `strict_local` skip path and cost/rate gate tests.
