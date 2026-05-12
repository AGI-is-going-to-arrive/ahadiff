# RFC 2.1 — Karpathy LLM Wiki Maintenance Loop

**Status**: DRAFT — §5 DECIDED: Option B (LLM-assisted) per user decision 2026-05-12
**Owner**: AhaDiff core
**Inspiration**: Karpathy LLM Wiki (append-only) + Graphify 7-state freshness
**Goal**: keep long-lived `concepts.jsonl` from silently rotting. Detect stale / contradicted / orphan / missing concepts and surface them without violating append-only or local-first.

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
| `concepts.jsonl` | Append-only (Karpathy) | never edit/delete; append `concept_marker` `{concept_id, marker: stale\|contradicted\|orphan\|dismissed, evidence_run_id, ts, suggested_successor?}` |
| `review.sqlite` | Derived state | new `concept_status` (concept_id PK, latest_marker, stale_since, contradicted_by_run, refcount, updated_at) — rebuilt from JSONL |
| `review.sqlite` | — | new `concept_lint_run` (lint_id PK, started_at, finished_at, mode, findings_count) |
| Graphify projection | 4-value (fresh/aging/stale/missing) | read-only consumer |

Append-only preserved: markers are *new* records pointing at old ids. Reset == replay JSONL.

## 4. State Transitions

| Graphify 7-state | Action |
|---|---|
| fresh / verified-fresh | no-op |
| aging | warn after N runs without re-evidence |
| stale | append `stale` marker (auto) |
| missing | append `orphan` marker (auto) |
| contradicted | append `contradicted` marker (gated — see §5) |
| unknown | log only |
| superseded | append `stale` + `suggested_successor` (no merge) |

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

**Shared invariant**: maintenance only appends markers + suggestions — never edits or deletes existing records. Data integrity comes from append-only, independent of detection mode.

Decision: use Option B for semantic contradiction detection, gated by the existing privacy tier. `strict_local` skips remote-assisted NLI; `redacted_remote` and `explicit_remote` may use the configured BYOK provider with per-lint cost/rate caps and cacheable judge inputs.

## 6. Local-First Privacy

| Concern | Decision |
|---|---|
| Remote sync | NONE. Markers stay in per-repo `.ahadiff/` |
| Telemetry | NONE |
| Option B traffic | Subject to existing redaction pipeline + privacy tier |
| Cross-repo learning | Forbidden (per-repo truth principle) |

## 7. Cross-Platform Impact

None special. Pure Python writes via existing `json_util` / `sqlite_util` (WAL, busy_timeout) under the repo write lock. No new fs primitives or shell-outs.

## 8. Frontend Interaction

| Surface | Change |
|---|---|
| Concepts row | badge `Stale` / `Contradicted` / `Orphan` + tooltip (evidence run, ts) |
| Concepts filter | new "Health" facet (all / healthy / needs-attention) |
| Concept detail | marker history (append-only timeline) |
| Settings | manual "Run concept lint" + last-lint summary |
| i18n | new `concepts.health.*` scalar keys; en/zh-CN parity required |
| Destructive UI | none. "Dismiss marker" itself appends a `dismissed` marker |

## 9. Test Strategy

| Layer | Coverage |
|---|---|
| unit | deterministic contradiction; orphan (refcount=0); missing (Graphify=missing); marker idempotency; JSONL replay rebuilds `concept_status` exactly; append-only mutation attempts fail fast |
| integration | seed → contradicting run → `concepts lint` → marker appended + viewer payload reflects badge; strict_local skips Option B |
| live (opt-in, Option B) | LLM judge smoke under `AHADIFF_LIVE_LLM_JUDGE=1` |

Excluded: no perf SLA in v1; benchmark deferred until refcount > 10k.

## 10. Release Gate

| Check | Status |
|---|---|
| Eval bundle impact | none (markers stay out of 8-dim rubric) |
| Frozen enum changes | none (`ClaimStatus`/`RunSource`/`EvalBundle`/`EventLog` untouched) |
| New ErrorCode | +1 `CONCEPT_LINT_BLOCKED` (fit stable-28 cap or bump policy) |
| Schema migration | sqlite additive, forward-compatible |
| Docs sync | CLAUDE.md modules table + viewer pages list |

## 11. What NOT to Do

| Forbidden | Reason |
|---|---|
| Auto-merge concepts | breaks append-only; silent semantic loss |
| Auto-delete concepts | same |
| Remote sync of markers | violates per-repo truth + local-first |
| Background daemon | out of scope; trigger must be explicit |
| Edit `concepts.jsonl` in place | breaks Karpathy invariant |
| Write back into Graphify | projection is read-only |
| Inflate eval bundle | markers are governance, not evaluation |
| Run Option B under `strict_local` or without a configured privacy/cost gate | violates the §5 decision boundary |

---

**Next step**: produce the module plan + UNITS.csv for Option B, including the `strict_local` skip path and cost/rate gate tests.
