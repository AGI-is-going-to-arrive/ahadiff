# Task 16 (Improve Loop) Deep Code Review

**Reviewer**: Claude Opus 4.6 (independent)
**Date**: 2026-04-24
**Files reviewed**: `src/ahadiff/improve/{__init__,loop,program}.py`, `src/ahadiff/cli.py` (improve section), `src/ahadiff/eval/results.py`, `prompts/improve_program.md`, `src/ahadiff/prompts/improve_program.md`, `tests/unit/test_improve_loop.py`, `doc/contract-freeze.md`

---

## Post-fix Addendum (Codex session)

The review body below is preserved as the original independent review. Current code has since been changed.

- `lesson_hint.md` is now part of the explicit 5-file mutable prompt allowlist.
- `session_id` is validated before file access and payload load; traversal and hidden-name inputs are rejected.
- replay subprocesses now have a 30-minute timeout.
- improve session JSON now persists `outcome_statuses`, `interrupted_round`, and `interrupted_stage`; older JSON missing those fields still loads as `None`/empty defaults.
- `--resume` now distinguishes an interrupted worktree it can safely clean up from a generic pending worktree that must still be rejected.
- discard and pending-conflict runs do not write `finalized.json`; pending-conflict runs are also excluded from the next improve baseline.
- Task 17 targeted verification and Phase 2.5 runtime have since landed. `keep_final` still remains the manual full 8-dimension recheck path through `db finalize-targeted`.
- prompt writes are temp+replace, cherry-pick non-conflict failures raise `InputError`, worktree fallback cleanup prunes git worktree metadata, volatile staged/unstaged replay uses the saved `patch.diff`, `--rounds` is capped at 20, and null-byte LLM content is rejected.
- tests expanded from 4 to 14 improve-loop cases.

Current live verification from this session:

| Command | Result |
|---------|--------|
| `pytest tests/unit/test_targeted_verify.py tests/unit/test_phase25.py tests/unit/test_improve_loop.py tests/unit/test_ratchet.py tests/unit/test_results.py tests/unit/test_probe.py -q` | 56 passed |
| `AHADIFF_LIVE_LLM_JUDGE=1 ... pytest tests/live/test_llm_judge_live.py -q` | 1 passed |
| `UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run --frozen --no-sync pytest tests -q --tb=long` | 1420 passed, 1 skipped |
| `UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run --frozen --no-sync pytest --cov=src/ahadiff --cov-report=term-missing --cov-fail-under=85 tests -q --tb=long` | 1420 passed, 1 skipped; total coverage 87.37% |
| `UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run --frozen --no-sync pyright` | 0 errors, 0 warnings, 0 informations |
| `ruff check src tests` / `ruff format --check src tests` / `uv build --wheel` | passed |
| `python -m ahadiff provider test --help` | passed |

---

## A. STATE MACHINE CORRECTNESS

**Verdict: PASS with 1 High finding**

- `append_result()` is called with `event_type="improve"` at `loop.py:243` -- correct, never uses `"keep"`.
- `"keep"` is restricted to learn pipeline only -- confirmed by contract-freeze.md line 81: "keep 只用于 learn 链路".
- Success path status is `"targeted_verify"` (`loop.py:236`) -- matches contract-freeze.md line 82: "targeted_verify -> keep_final 只用于 improve 链路".
- Discard path writes `status="discard"` (`loop.py:223,247`).
- Interrupt path writes `status="crash"` (`loop.py:294`).

### Finding A-1 [High] `targeted_verify` is not in contract-freeze terminal states

- **File**: `loop.py:236` vs `contract-freeze.md:85-92`
- **Description**: contract-freeze.md section 2.3 lists terminal states as: `baseline, keep, discard, crash, keep_final, non_ratcheted`. The status `targeted_verify` is NOT listed as a terminal state -- it is a transitional status that should eventually become `keep_final`. However, the improve loop writes `targeted_verify` and terminates. There is no code anywhere in the improve module that transitions `targeted_verify` to `keep_final`. The `finalize_targeted_verify_event` function exists in `review/database.py` (per Task 15 cross-review report), but the improve loop never calls it.
- **Trigger**: Every successful improve round that beats baseline leaves the event in a non-terminal `targeted_verify` state forever, unless the user manually runs `ahadiff db finalize-targeted`.
- **Impact**: The state machine is incomplete; `targeted_verify` events accumulate without progressing to `keep_final`. Ratchet calculations include `targeted_verify` in `_BASELINE_STATUSES` (loop.py:42), so functionally it works, but the contract is violated.

### Finding A-2 [Medium] `_BASELINE_STATUSES` includes `targeted_verify` -- silent self-healing

- **File**: `loop.py:42`
- **Description**: `_BASELINE_STATUSES = frozenset({"baseline", "keep", "targeted_verify", "keep_final", "non_ratcheted"})` includes `targeted_verify`. This means an un-finalized improve result can itself become the baseline for the next improve round. While pragmatically useful, this is an undocumented deviation from contract-freeze.md which says only `baseline, keep, keep_final` count for ratchet (line 94-98). `targeted_verify` and `non_ratcheted` are not listed in the ratchet-counting set, yet both appear in `_BASELINE_STATUSES`.
- **Trigger**: Run `ahadiff improve --rounds 2` -- round 2 will use round 1's `targeted_verify` result as baseline.

---

## B. PROMPT VERSION INTEGRITY

**Verdict: CORRECT with important nuance**

- `compute_prompt_version()` in `results.py:156-160` calls `_prompt_hash_chunks(repo_root)`.
- `_prompt_hash_chunks()` at `results.py:302` first checks `repo_root / "src" / "ahadiff" / "prompts"`. If that exists (which it will in a worktree), it reads from there.
- In improve mode, `loop.py:210` calls `compute_prompt_version(worktree_path)` -- this correctly reads from the WORKTREE copy of prompts, so modified prompts produce a new `prompt_version`.
- The `prompt_version_override` parameter (`loop.py:245`) ensures the worktree-computed version is used when writing to the main repo's DB.

### Finding B-1 [Medium] Contract-freeze says prompt_version should NOT read workspace prompts

- **File**: `results.py:302` vs `contract-freeze.md:187`
- **Description**: contract-freeze.md line 187 states: "prompt_version 记录的是 AhaDiff 自带 prompt 资源 的 tree hash，不读取目标工作区自己的 prompts/". However, `_prompt_hash_chunks()` reads from `repo_root / "src" / "ahadiff" / "prompts"` when that directory exists. In a worktree, this IS the workspace. The improve loop explicitly relies on this behavior (computing prompt_version from the worktree). This is a deliberate and correct design decision for improve, but contradicts the contract text. The contract needs updating to carve out the improve case.
- **Trigger**: Any improve round.

---

## C. SESSION PERSISTENCE

**Verdict: PASS -- solid design**

- Session file: JSON at `.ahadiff/improve/<session_id>.json` (`program.py:72-73`).
- Fields persisted: `session_id, suite, anchor_run_id, phase25_attempted, rounds_completed, worktree_path, created_at, updated_at, last_status, outcome_statuses, interrupted_round, interrupted_stage` (`program.py:43-56`).
- Atomic write via temp-then-rename pattern (`program.py:79-87`).
- Crash safety: `rounds_completed` is updated AFTER each round completes, so on crash resume starts from last completed + 1 (`loop.py:161`).
- Pending worktree detection on resume: if `interrupted_round` + `interrupted_stage` are present, resume can first decide whether to clean up and continue; otherwise an existing `session.worktree_path` still raises `InputError`.

### Finding C-1 [Medium] Session does not record round-level outcomes

- **File**: `program.py:32-41`
- **Description**: `ImproveSessionState` only tracks `rounds_completed` (a count) and `last_status`, not the full list of round outcomes. After a crash, the session can resume from `rounds_completed + 1`, but all outcome details from prior rounds are lost (they were only in the `ImproveLoopResult.outcomes` tuple which is ephemeral). Individual round results ARE persisted in `result_events` DB, but there's no session-level record linking session_id to its ordered sequence of run_ids.
- **Trigger**: Crash during round 3 of a 5-round improve session. Resume will proceed from round 4 but the caller receives no history for rounds 1-3.

### Finding C-2 [Low] `_utc_now()` in `program.py:226` strips timezone info

- **File**: `program.py:226`
- **Description**: `.replace("+00:00", "Z")` produces valid ISO 8601, but the same pattern is duplicated in `results.py:386`. Minor DRY violation.

---

## D. WORKTREE LIFECYCLE

**Verdict: PASS with 1 Medium finding**

- Creation: `_create_worktree()` at `loop.py:364-368` uses `git worktree add --detach <path> HEAD`. Branch name pattern: `<session_id>-r<round_index>` for the path, detached HEAD (no branch created).
- Learn replay: `_run_replay_learn_subprocess()` at `loop.py:494-547` runs `ahadiff learn` as a subprocess in the worktree.
- Artifacts copied back: `_copy_candidate_run_to_state()` at `loop.py:557-568` uses `shutil.copytree` with temp-then-rename, and removes `quiz/cards.jsonl`.
- Cleanup in finally: `loop.py:311-313` checks if `session.worktree_path is None` and the path exists, then removes it. The outer finally at `loop.py:314-315` restores signal handler.
- `_remove_worktree()` at `loop.py:371-376` has a two-phase cleanup: `git worktree remove --force` then `shutil.rmtree` as fallback. Both use `ignore_errors`.

### Finding D-1 [Medium] Worktree cleanup finally block has a race condition

- **File**: `loop.py:311-313`
- **Description**: The cleanup check is `if session.worktree_path is None and worktree_path.exists()`. But if the round succeeds and the cherry-pick has a conflict (`cherry_pick_pending=True`), `session.worktree_path` is set to `str(worktree_path)` (line 259), so the finally block skips cleanup (correct). However, if an exception occurs BETWEEN `_create_worktree()` (line 179) and `update_improve_session(..., worktree_path=str(worktree_path))` (line 177), the session's `worktree_path` is already set (line 177-178 runs BEFORE `_create_worktree`), so the finally block would skip cleanup even though the round failed. This is actually safe because the worktree_path IS set in session -- but it means the orphaned worktree persists until the next resume attempt, which will fail with `_PENDING_WORKTREE_NOTE`.
- **Trigger**: Exception during `_mutate_prompt_in_worktree()` -- worktree is created but never cleaned up until explicit session resume.

### Finding D-2 [Low] `_create_worktree` pre-removes existing worktree

- **File**: `loop.py:365-366`
- **Description**: If `worktree_path.exists()`, it removes and recreates. This is defensive but could silently destroy a worktree from a previous crashed round. Not a bug per se, but worth documenting.

---

## E. CHERRY-PICK ORDERING

**Verdict: PASS -- correct order**

The code sequence at `loop.py:225-246`:
1. Check if candidate score > baseline AND no hard gate failures (line 225-228)
2. Call `_cherry_pick_prompt_commit(repo_root, commit_sha)` (line 229)
3. If cherry-pick conflicts, set `cherry_pick_pending=True` and abort cherry-pick (inside `_cherry_pick_prompt_commit` at line 585)
4. Set `status = "targeted_verify"` (line 236)
5. THEN call `append_result()` with the status (line 238-246)

This is the correct order: git operation first, status write second.

### Finding E-1 [High] Cherry-pick conflict aborts but still writes `targeted_verify`

- **File**: `loop.py:229-236`
- **Description**: When `_cherry_pick_prompt_commit` detects a conflict, it runs `git cherry-pick --abort` (line 585) and returns `_CherryPickResult(pending_conflict=True)`. The calling code at line 230-236 then sets `cherry_pick_pending=True` BUT ALSO sets `status = "targeted_verify"`. This means a FAILED cherry-pick (conflict detected and aborted) still records `status="targeted_verify"` in the database. The prompt changes were NOT applied to the main branch. The note_payload does record `cherry_pick_pending: true`, but the status itself is misleading -- it suggests the improvement was accepted and needs verification, when in reality the cherry-pick was aborted.
- **Trigger**: LLM modifies a prompt that has been manually edited on the main branch, causing a merge conflict.
- **Impact**: The `targeted_verify` status is written for a change that was NOT applied. The worktree is preserved (line 255-261), but there is no mechanism to retry the cherry-pick or transition the status. Subsequent improve rounds will see this as a successful baseline.

---

## F. RESULT CONSISTENCY

**Verdict: PASS with 1 Medium finding**

- `append_result()` is called with `event_type="improve"` -- correct.
- `write_finalized=True` by default in `append_result()` (`results.py:61`), so `finalized.json` is written.
- However, the improve loop's `append_result` call at `loop.py:238-246` does NOT pass `write_finalized=False`, so it defaults to `True`. This writes a `finalized.json` inside the imported candidate run.

### Finding F-1 [Medium] Improve loop writes `finalized.json` inside candidate runs

- **File**: `loop.py:238-246`, `results.py:103-112`
- **Description**: `append_result()` defaults to `write_finalized=True`. The improve loop does not override this. This means every improve round (even discarded ones) gets a `finalized.json` in its run directory. For discarded runs, this is misleading -- the run was not accepted. The learn pipeline explicitly controls this via `_persist_evaluated_run()` which calls `publish_result_artifacts()` separately. The improve loop should probably pass `write_finalized=False` for discarded runs.
- **Trigger**: Any improve round that produces a discard.

### Finding F-2 [Low] Double `append_result` on interrupt

- **File**: `loop.py:238-246` and `loop.py:291-303`
- **Description**: When an interrupt is requested after a successful round, both the round's result (line 238, status=`targeted_verify`/`discard`) AND the crash event (line 291, status=`crash`) are written. This produces two result events for the same round. The crash event uses the same `imported_run_path` and `candidate_report`, creating two events for one run_id. This is actually fine for audit purposes but may confuse ratchet calculations.

---

## G. PROMPT WHITELIST

**Verdict: PASS -- well-designed**

- Whitelist computed from `_MUTABLE_PROMPT_BY_DIMENSION` values (`program.py:44-46`): `claim_extract.md`, `quiz_generate.md`, `lesson_generate.md`, `lesson_compact.md` (deduplicated). Plus `lesson_hint.md` which maps from no dimension -- wait, checking again...
- Actually, `_MUTABLE_PROMPT_BY_DIMENSION` at `program.py:16-25` maps 8 dimensions to 4 files: `claim_extract.md`, `quiz_generate.md`, `lesson_generate.md`, `lesson_compact.md`. The function `mutable_prompt_names()` returns only these 4 deduplicated values.

### Finding G-1 [High] `lesson_hint.md` is in the contract whitelist but NOT in the code whitelist

- **File**: `program.py:16-25` vs `contract-freeze.md:178`
- **Description**: contract-freeze.md line 178 lists the whitelist as: `lesson_generate.md, lesson_hint.md, lesson_compact.md, quiz_generate.md, claim_extract.md` (5 files). But `_MUTABLE_PROMPT_BY_DIMENSION` in `program.py:16-25` maps dimensions to only 4 files. `lesson_hint.md` has no dimension mapping and is NOT included in the set returned by `mutable_prompt_names()`. This means `lesson_hint.md` is immutable in practice despite the contract saying it should be mutable.
- **Trigger**: If the weakest dimension optimization ever needed to modify `lesson_hint.md`, the code would reject it.
- **Impact**: Contract violation. Either add a dimension mapping for `lesson_hint.md` or update the contract.

### Finding G-2 [Medium] No path traversal or symlink protection on prompt filenames

- **File**: `loop.py:401-402`, `program.py:189-192`
- **Description**: `validate_mutable_prompt_name()` checks membership in a frozen set, which provides strong allowlist protection. However, the LLM response's `target_file` field is validated against this set at `loop.py:457` but the actual file paths at `loop.py:401-402` are constructed via `worktree_root / "prompts" / target_prompt`. If `target_prompt` contained `../`, the membership check would reject it (it's not in the set). So the allowlist IS the traversal protection. This is adequate but relies on the invariant that the allowlist contains only simple filenames. No explicit symlink check on the prompt files themselves (e.g., if someone replaced `prompts/lesson_generate.md` with a symlink to `/etc/passwd`).
- **Trigger**: Attacker creates a symlink at `prompts/lesson_generate.md` pointing outside the repo, then runs improve. The improve loop would overwrite the symlink target.

---

## H. PROMPT FILE CONSISTENCY

**Verdict: PASS**

- `diff` command confirms `prompts/improve_program.md` and `src/ahadiff/prompts/improve_program.md` are identical (empty diff output).
- Test `test_improve_program_prompt_parity()` at `test_improve_loop.py:183-189` explicitly verifies parity between the repo copy and the package copy.
- The improve loop writes to BOTH locations in `_mutate_prompt_in_worktree()` at `loop.py:465-466`.
- `_commit_prompt_change()` at `loop.py:480-482` commits both `prompts/<target>` and `src/ahadiff/prompts/<target>`.

---

## I. CROSS-PLATFORM

**Verdict: PASS with 2 Medium findings**

### Finding I-1 [Medium] `signal.SIGINT` handler is not Windows-safe in all scenarios

- **File**: `loop.py:81-107`
- **Description**: `_InterruptController` installs a `SIGINT` handler. On Windows, `signal.signal(signal.SIGINT, handler)` works for console applications but may not work in all contexts (e.g., when running as a subprocess). The code does NOT handle `SIGTERM` or `SIGBREAK` (Windows). The `_detached_subprocess_kwargs()` at `loop.py:550-554` correctly uses `CREATE_NEW_PROCESS_GROUP` on Windows, which is good. But the parent process's SIGINT handler won't propagate to children in a new process group, which is actually the desired behavior.
- **Trigger**: Ctrl+C on Windows when running as a background service.

### Finding I-2 [Medium] Forward slash in `_commit_prompt_change` path strings

- **File**: `loop.py:480-482`
- **Description**: `repo_relative_paths` uses forward slashes: `f"prompts/{target_prompt}"`, `f"src/ahadiff/prompts/{target_prompt}"`. Git on all platforms accepts forward slashes, so this is correct. No issue found.
- **Status**: No issue.

- No `shell=True` found (confirmed by grep).
- `shutil.copytree` and `Path.replace` are cross-platform.
- Atomic rename via `temp_path.replace(target)` works cross-platform (Python handles this).

---

## J. TEST COVERAGE

**Verdict: 4 tests covering core happy/sad paths; significant gaps remain**

### Tests present (test_improve_loop.py):

1. `test_build_replay_learn_args_prefers_git_range` -- verifies replay arg construction for git range
2. `test_improve_program_prompt_parity` -- verifies prompt file consistency
3. `test_run_improve_loop_records_targeted_verify_and_cherry_picks` -- full happy path: improve beats baseline, cherry-pick succeeds, verifies event_type/status/artifacts
4. `test_run_improve_loop_records_discard_without_cherry_pick` -- sad path: candidate score < baseline, verifies discard status and no cherry-pick

### Finding J-1 [High] Missing test scenarios

- **File**: `tests/unit/test_improve_loop.py`
- **Description**: The following scenarios have NO test coverage:
  - **Crash recovery / session resume**: No test for `--resume` parameter
  - **Cherry-pick conflict**: No test for `_CherryPickResult(pending_conflict=True)` path
  - **Interrupt handling**: No test for `_InterruptController` behavior (first Ctrl+C = graceful, second = SystemExit)
  - **Multi-round improve**: No test for `--rounds 2+` (round 2 using round 1's result as baseline)
  - **`build_replay_learn_args` other source kinds**: Only `git_ref` is tested; `git_staged`, `git_unstaged`, `git_staged_unstaged`, and patch fallback are untested
  - **Session suite mismatch**: No test for resume with wrong suite
  - **Pending worktree on resume**: No test for the `_PENDING_WORKTREE_NOTE` rejection path
  - **LLM response parsing errors**: No test for malformed JSON, wrong target_file, empty content
  - **`_copy_candidate_run_to_state`**: No test for duplicate run_id collision
  - **Concurrent runs**: No test for two improve loops running simultaneously
  - **Windows path patterns**: No test for path separators on Windows
  - **`lesson_hint.md` whitelist gap**: No test asserting all contract-listed prompts are in the whitelist

---

## Summary by Severity

| Severity | Count | IDs |
|----------|-------|-----|
| Critical | 0 | -- |
| High | 3 | A-1, E-1, G-1 |
| Medium | 5 | A-2, B-1, C-1, D-1, F-1 |
| Low | 3 | C-2, D-2, F-2 |
| Info (test gaps) | 1 | J-1 |

### High findings detail:

1. **A-1**: `targeted_verify` is never transitioned to `keep_final` by the improve module. The `finalize_targeted_verify_event` function exists in review/database.py but is never called from the improve loop. Events accumulate in a non-terminal state.

2. **E-1**: Cherry-pick conflicts still write `status="targeted_verify"`, even though the cherry-pick was aborted and the prompt change was NOT applied to the main branch. The worktree is preserved but there's no retry mechanism.

3. **G-1**: `lesson_hint.md` is listed in the contract whitelist (contract-freeze.md:178) but has no dimension mapping in `_MUTABLE_PROMPT_BY_DIMENSION` (program.py:16-25), making it effectively immutable despite the contract.

### Gate recommendation: **CONDITIONAL GO**

0 Critical, 3 High findings. The High findings are:
- A-1: Document the expected user flow (manual `ahadiff db finalize-targeted`) or add auto-finalization
- E-1: Write `targeted_verify` only when cherry-pick succeeds; use a different status (e.g., `cherry_pick_failed`) for conflicts, or write `discard`
- G-1: Add `lesson_hint.md` to a dimension mapping or update contract-freeze.md

All 3 High findings require resolution before Stage 5 signoff.
