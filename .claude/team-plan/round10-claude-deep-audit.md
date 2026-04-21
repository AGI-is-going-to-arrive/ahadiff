# Round 10 Claude Deep Audit — Cross-Document Logical Analysis

> Auditor: Claude Opus 4.6
> Date: 2026-04-21
> Files reviewed: CLAUDE.md + 7 team-plan documents (all read in full)
> Focus: Cross-document contradictions, implicit dependency gaps, completeness gaps, numerical consistency, timing hazards

---

## Finding Summary

| Severity | Count |
|----------|-------|
| High | 3 |
| Medium | 8 |
| Low | 5 |
| Info | 3 |
| **Total** | **19** |

---

## High Findings

### H-1: `rubric.yaml` path inconsistency across evaluation bundle — `evals/` vs `eval/`

**Severity**: High
**Files**: `stages-4-9.md` Task 11 line 126, `kickoff.md` Task 0 step 4
**Evidence**:
- Task 11 file scope lists `evals/rubric.yaml` (with 's')
- Task 11 file conflict table (line 450) lists `evals/rubric.yaml`
- Task 0 step 4 hash algorithm pseudo-code shows path `eval/deterministic.py`, `eval/evaluator.py` (without 's')
- The other 4 bundle files are under `src/ahadiff/eval/` (without 's')

**Impact**: The eval_bundle_version hash is computed from sorted file paths. If `rubric.yaml` lives at `evals/rubric.yaml` (repo root) while the other 4 live at `src/ahadiff/eval/*.py`, the hash algorithm's path prefix will be inconsistent. More critically, `rubric.yaml` would be outside the `src/` package tree, making it non-importable via Python packaging and easy to miss in `pip install`.

**Fix**: Decide authoritatively whether rubric.yaml lives at `evals/rubric.yaml` (repo root) or `src/ahadiff/eval/rubric.yaml` (inside package). Freeze this in `contract-freeze.md` Task 0. Recommended: `src/ahadiff/eval/rubric.yaml` for package inclusion.

---

### H-2: `fsrs_card_json` vs `fsrs_state` field name still not unified

**Severity**: High
**Files**: `ahadiff-fsrs-decision.md` line 176 vs line 192; `stages-4-9.md` Task 10 step 1 line 103; `stages-4-9.md` Task 15 step 1 line 293
**Evidence**:
- FSRS decision Pydantic model uses `fsrs_card_json: str` (line 176)
- FSRS decision SQL schema uses `fsrs_state TEXT` (line 192)
- stages-4-9.md Task 10 step 1 uses `fsrs_state: str` (line 103)
- stages-4-9.md Task 15 step 1 SQL uses `fsrs_state TEXT` (line 293)
- Round 9 review (`ahadiff-round9-ultimate-review.md` line 99) flagged this as R9-4 Low and said "统一 fsrs_card_json → fsrs_state" but the FSRS decision doc was **never actually patched**

**Impact**: Implementer reading the FSRS decision doc will use `fsrs_card_json`; implementer reading stages doc will use `fsrs_state`. Contract freeze must pick one.

**Fix**: Patch `ahadiff-fsrs-decision.md` line 176 to use `fsrs_state` (matching the majority usage). The Pydantic field name must match the SQL column name for ORM clarity.

---

### H-3: Task 9 (Lesson) missing explicit dependency on Task 2 (Safety/Redaction)

**Severity**: High
**Files**: `stages-4-9.md` Task 9 line 74; `kickoff.md` Task 2; `diff-input-expansion.md` pipeline diagram
**Evidence**:
- Task 9 declares dependencies: `Task 7 (LLM Provider) + Task 8 (Claim extraction)`
- Task 9 `generate_lesson()` sends parsed diff content to LLM for explanation generation
- CLAUDE.md design decision #6 states: "raw input -> secret scan -> redact -> THEN log/cache/model/render"
- The capture pipeline (`diff-input-expansion.md` lines 43-66) shows redaction happens at step 4, before `learn pipeline` at step 6
- BUT: the redaction logic lives in Task 2 (`safety/redact.py`). Task 5 integrates it at capture time. Task 9's dependency chain is Task 7+8, meaning it transitively depends on Task 5 (which depends on Task 2). So the dependency is **implicitly satisfied** through Task 8 -> Task 6 -> Task 5 -> (uses Task 2 at runtime)

**Impact**: The transitive dependency works, but it is fragile. If someone refactors Task 9 to accept raw diff input directly (bypassing the capture pipeline), they could accidentally send unredacted content to the LLM. The dependency should be made explicit in the DAG or enforced architecturally.

**Fix**: Add a note to Task 9: "CONSTRAINT: `generate_lesson()` must only accept `RedactedDiff` type (not raw patch), enforced by type signature. Redaction is handled by Task 5/Task 2 in the capture pipeline." This is an architectural guardrail, not a DAG dependency change.

---

## Medium Findings

### M-1: `ahadiff doctor` has unbounded responsibilities across 6+ Tasks

**Files**: kickoff.md Task 0 step 9 (orphaned worktree), Task 0 step 19 (SQLite version), Task 0 step 20 (deep check), Task 1 step 7-8 (network path + config diagnostics), Task 7 step 12 (audit .tmp cleanup), data-scope.md (allowlist scan, config secret detection, VCR GC)
**Evidence**: doctor is assigned at least 9 distinct responsibilities:
1. Orphaned worktree cleanup
2. SQLite runtime version + source path reporting
3. `--deep` integrity_check + foreign_key_check
4. Network/UNC path detection
5. Config unknown key warnings + secret-in-config detection
6. Audit `.tmp` file cleanup after interrupted rotation
7. Run `.tmp/` directory cleanup (`ahadiff clean-orphans`)
8. Allowlist wide-rule scan and warning
9. VCR cassette pruning (`--prune-cassettes`)

**Impact**: No single Task owns doctor implementation end-to-end. Task 1 creates the initial `doctor_cmd()` skeleton, but responsibilities #2-9 are added by Tasks 0, 7, 14.5, 15, and data-scope features. There is no integration test that validates all doctor sub-checks work together.

**Fix**: Create an explicit "doctor registry" pattern in Task 1: `register_check(name, callable)`. Each downstream Task registers its own checks. Add an integration test in Stage 2 gate that runs `ahadiff doctor` and validates all registered checks execute.

---

### M-2: Config precedence chain has 5 layers in CLAUDE.md but serve/request adds a 6th layer

**Files**: CLAUDE.md line 70 vs kickoff.md Task 0 step 14 line 74
**Evidence**:
- CLAUDE.md defines 5 layers: `ENV → CLI flag → per-repo config.toml → global config.toml → defaults`
- kickoff.md Task 0 step 14 defines the same 5 layers, PLUS a separate "Serve/request" chain: `cookie → Accept-Language → CLI session → per-repo → global → system → defaults`
- The serve/request chain has **7 layers** (not 5), and includes `system` (LANG env var) which is not in the main 5-layer chain
- CLAUDE.md i18n section (line 151) describes: `manual switch (cookie) → browser detect → CLI --lang → config.toml → system LANG → fallback en` — this is 6 layers
- data-scope-architecture.md Section I repeats the 5-layer chain identically to CLAUDE.md

**Impact**: The config and i18n locale chains are conceptually different subsystems but share some layers. The "system LANG" layer appears in the i18n chain but not in the general config chain. This is probably intentional (general config has no system-level source), but it is never explicitly stated that they are different chains.

**Fix**: Add a clarifying note in Task 0 contract-freeze: "The 5-layer config precedence chain applies to ALL config keys EXCEPT locale. Locale resolution uses a separate 6-layer chain (cookie → Accept-Language → CLI → config → system LANG → en) documented in i18n schema."

---

### M-3: Task 13 (React Viewer) score.json schema dependency on Task 11 is implicit

**Files**: stages-4-9.md Task 13 line 187 vs Task 14 line 227
**Evidence**:
- Task 13 declares dependency: `Task 0 (Schema Freeze)` only
- Task 14 (DashboardPage) step 1 needs to display `verdict/score/timeline + Ratchet trend graph` — this requires `score.json` schema from Task 11
- Task 14 declares dependency: `Task 13 (Viewer base)` only
- The DAG (line 472) shows Task 13 at Layer 5 and Task 14 at Layer 6a, while Task 11 is at Layer 4
- So Task 11 will be complete before Task 13 starts — the implicit dependency is **satisfied by ordering**

**Impact**: Low actual risk since DAG ordering handles it. But the mock/proxy strategy for Task 13 development (line 187: "API through mock/proxy decoupling") means the mock must match Task 11's score.json schema. If Task 11 changes the schema during development, the mock becomes stale.

**Fix**: Task 13's mock data fixtures should be generated FROM Task 0's frozen schema contracts, not hand-coded. Add this to Task 13 step 5: "API mock fixtures must use TypeScript types generated from Task 0 Pydantic contracts."

---

### M-4: `--compare` mode omitted from Task 14.5 Serve API endpoint list

**Files**: stages-4-9.md Task 14.5 step 4 line 265; diff-input-expansion.md
**Evidence**:
- Task 14.5 lists these read endpoints: `/api/runs`, `/api/run/:id`, `/api/run/:id/lesson`, `/api/run/:id/claims`, `/api/run/:id/quiz`, `/api/run/:id/diff`, `/api/concepts`, `/api/ratchet/history`
- Runs created via `--compare` or `--patch` have `capability_level` 1 or 2, meaning they lack some features (no ratchet, no git ancestry)
- The `/api/ratchet/history` endpoint will return empty or partial data for non-git runs
- No endpoint filters runs by `source_kind` or `capability_level`
- No endpoint exposes `degraded_flags` to the frontend

**Impact**: The Dashboard will show `--compare` runs alongside git runs in the ratchet trend graph, potentially confusing users (non_ratcheted runs mixed with ratcheted ones). The frontend has no way to distinguish them via API.

**Fix**: Add `capability_level` and `source_kind` fields to the `/api/runs` response. Add an optional `?source_kind=git_ref` filter parameter. Task 14 DashboardPage should filter non_ratcheted runs out of the trend graph by default.

---

### M-5: Learnability Gate threshold (0.3) not included in contract-freeze scope

**Files**: stages-4-9.md line 47 (Learnability Gate); kickoff.md Task 0 (no mention)
**Evidence**:
- The Learnability Gate with `LEARNABILITY_THRESHOLD = 0.3` and three-factor weighting (complexity 0.4 / novelty 0.3 / pattern 0.3) is defined in stages-4-9.md
- Task 0 (Schema Freeze) does not mention Learnability Gate at all
- The threshold and weights are configurable via `config.toml [learn].learnability_threshold`
- CLAUDE.md changelog mentions "Learnability Gate design frozen" but the contract-freeze Task 0 steps do not include it

**Impact**: Without freezing the default threshold and factor weights in contract-freeze.md, different implementations could use different defaults, making benchmark comparisons invalid.

**Fix**: Add to Task 0: "Step 22: Freeze LearnabilityGate defaults — threshold=0.3, weights={complexity:0.4, novelty:0.3, pattern:0.3}. These are config-overridable but the defaults are frozen."

---

### M-6: FSRS card creation trigger point undefined

**Files**: stages-4-9.md Task 10 step 1-4; ahadiff-fsrs-decision.md Section 3.3
**Evidence**:
- Task 10 step 4: `generate_cards() → cards.jsonl (SRS review cards)`
- Task 10 step 1: ReviewCard schema includes FSRS fields
- Task 15 step 2: FSRS scheduling implementation
- NOWHERE is it defined: at what point in the `ahadiff learn` pipeline does a card enter the SRS queue?
  - After lesson generation? After score >= 80 (PASS)? Always?
  - If a run gets FAIL verdict (score < 60), are cards still created?
  - If a run gets CAUTION (60-79), are cards created?

**Impact**: If cards are always created regardless of verdict, users get SRS cards for potentially incorrect lessons (FAIL runs). If cards are only created for PASS, users miss learning from CAUTION runs.

**Fix**: Define explicitly in Task 10: "Cards are created for PASS and CAUTION runs. FAIL runs do not generate cards (lesson quality too low for reliable SRS). If a previously-PASS run is later `discard`ed by ratchet, its cards are marked `stale` with `stale_reason=run_discarded`."

---

### M-7: `result_events` table indexes are defined in BOTH Task 12 and Task 15

**Files**: stages-4-9.md Task 12 step 3 (line 152) vs Task 15 step 8 (line 309)
**Evidence**:
- Task 12 step 3 defines indexes: `(run_id, event_type, timestamp)` unique, `(source_ref, timestamp DESC)`, `(verdict, status)`, `(weakest_dimension, timestamp DESC)`
- Task 15 step 8 defines indexes: `event_id` PK, `(run_id, event_type, timestamp)` unique, `(source_ref, timestamp DESC)`, `(prompt_version, rubric_version)`, `(verdict, status)`, `(weakest_dim, timestamp DESC)`
- Task 15 adds `(prompt_version, rubric_version)` which Task 12 does not mention
- Task 12 uses `weakest_dimension` (full name), Task 15 uses `weakest_dim` (short name)

**Impact**: Index definitions are split across two Tasks with inconsistencies. The column name (`weakest_dimension` vs `weakest_dim`) is a naming conflict that will cause SQL errors if not resolved.

**Fix**: Move ALL `result_events` index definitions to Task 15 exclusively (since Task 15 creates the schema). Task 12 should only define the write logic. Standardize column name to `weakest_dim` (matching Task 15 step 5 which says "统一用短名").

---

### M-8: Prompt files count incomplete — missing `claim_extract.md` from file ownership table

**Files**: CLAUDE.md line 198; kickoff.md Task 8 line 372; stages-4-9.md Task 16 line 328
**Evidence**: Collecting all distinct prompt files across all Tasks:
1. `prompts/claim_extract.md` — Task 8
2. `prompts/lesson_generate.md` — Task 9
3. `prompts/lesson_hint.md` — Task 9
4. `prompts/lesson_compact.md` — Task 9
5. `prompts/quiz_generate.md` — Task 10
6. `prompts/improve_program.md` — Task 16

Total: 6 prompt files. But the CLAUDE.md file ownership table (line 198) only assigns `prompts/*.md` to "Claude writes, Claude+Codex review". The improve loop "only modifies prompts/*.md" — but `improve_program.md` is the state machine that CONTROLS the improve loop, not a target of modification by it. The actual modification targets are `lesson_generate.md`, `lesson_hint.md`, `lesson_compact.md`, `quiz_generate.md`, and `claim_extract.md`.

**Impact**: If the improve loop modifies `improve_program.md` (the state machine itself), it violates the N-file contract (program.md should be human-written). But no document explicitly lists which prompt files are mutable by the improve loop and which are not.

**Fix**: Add to Task 16 step 3: "Mutable prompt files (improve loop can modify): `lesson_generate.md`, `lesson_hint.md`, `lesson_compact.md`, `quiz_generate.md`, `claim_extract.md`. Immutable prompt files (human-only): `improve_program.md`. The improve loop MUST NOT modify improve_program.md."

---

## Low Findings

### L-1: Evidence hard gate asymmetry (12/18 = 67% vs Accuracy 14/20 = 70%)

**Files**: stages-4-9.md Task 11 step 2 (line 132)
**Numerical check**: Accuracy weight=20, gate=14 (70%). Evidence weight=18, gate=12 (66.7%). The 3.3% asymmetry appears intentional (evidence scoring has more variance from LLM judge vs deterministic accuracy checks), but is never documented as a design choice.
**Fix**: Add a comment in rubric.yaml: "Evidence gate set at 67% (vs 70% for Accuracy) because evidence scoring has higher LLM-judge variance."

### L-2: Rubric weights sum verification

**Check**: 20+18+14+14+10+10+8+6 = 100. **CORRECT**. No finding.

### L-3: PASS/CAUTION/FAIL vs hard gates edge case

**Analysis**: A run could score Accuracy=14 (exactly at gate), Evidence=12 (exactly at gate), and all other dimensions at 0. Total = 14+12 = 26, which is FAIL (<60). Hard gates pass but overall FAIL. This is correct behavior — hard gates are necessary but not sufficient conditions. No fix needed, but worth documenting as expected behavior.

### L-4: Write order crash recovery gap between SQLite commit and TSV append

**Files**: stages-4-9.md Task 12 step 1 (line 150)
**Evidence**: Write order is: artifact → SQLite commit → TSV append → finalized.json → rename. If crash between SQLite commit and TSV append, SQLite has the data but TSV does not. Recovery: `ahadiff export-results` rebuilds TSV from SQLite. This is documented and correct. However, if crash between finalized.json write and rename, the run directory stays as `.tmp/` and `ahadiff doctor` handles it. **No gap** — recovery is complete.

### L-5: `VCR cassette key` — Round 9 R9-4 suggested 5-tuple but closure-checklist FIX-15 still says 4-tuple

**Files**: closure-checklist-29.md FIX-15 line 73
**Evidence**: FIX-15 says "cassette 级四元组扩展为五元组" (adding api_family_version). But stages-4-9.md Task 18 VCR section (line 379) still defines cassette key as 4-tuple: `prompt_fingerprint + model_id + rubric_version + output_lang`. The 5th element (`api_family_version`) is not added there.
**Fix**: Patch stages-4-9.md Task 18 VCR section to explicitly add `api_family_version` as the 5th cassette key component.

---

## Info Findings

### I-1: Serve is correctly distinguished from learn/improve/verify

kickoff.md Task 0 step 11 (line 82) explicitly states: "serve is pull/read mode... run_serve() does not return OrchestratorResult, instead starts an ASGI long-running process. DTO has command=serve with ServeConfig, not RunConfig." This is consistent across all documents.

### I-2: Evaluation bundle file list is consistently 5 files everywhere

Verified across CLAUDE.md, README.md, README.en.md, kickoff.md, stages-4-9.md, competitors-research.md. All say: `evaluator.py + rubric.py + rubric.yaml + gates.py + deterministic.py`. One early document (`ahadiff-v01-team-review-research.md` line 338) listed only 4 (missing rubric.py), but this was from before Round 2 added rubric.py and is superseded.

### I-3: cherry-pick → status write order is consistently frozen

stages-4-9.md Task 12 step 7 line 164: "禁止：先写 status 再 cherry-pick". kickoff.md is consistent. CLAUDE.md changelog confirms "cherry-pick→status 写入顺序冻结". No contradiction found.

---

## Recommendations for Task 0 Contract Freeze

1. **Resolve rubric.yaml path** (H-1): freeze to `src/ahadiff/eval/rubric.yaml`
2. **Unify fsrs_state field name** (H-2): patch FSRS decision doc
3. **Add RedactedDiff type constraint** (H-3): architectural guardrail for Task 9
4. **Add LearnabilityGate defaults to contract** (M-5)
5. **Define card creation trigger** (M-6): PASS+CAUTION only
6. **Consolidate result_events indexes in Task 15** (M-7)
7. **Enumerate mutable vs immutable prompt files** (M-8)
8. **Add VCR 5-tuple to stages doc** (L-5)
