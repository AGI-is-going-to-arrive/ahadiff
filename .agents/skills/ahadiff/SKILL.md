---
name: ahadiff
description: "AhaDiff verified diff learning - learn back from AI-generated code changes"
---
<!-- AHADIFF:GENERATED -->
# AhaDiff

Use this Codex agent skill when a code change should be learned back from the
diff instead of explained from memory.

## Core Commands

- `ahadiff learn HEAD~1..HEAD` captures the latest commit.
- `ahadiff learn --staged` captures staged changes before commit.
- `ahadiff quiz <run_id>` reviews generated quiz questions.
- `ahadiff review` opens the due SRS queue backed by `review.sqlite`.
- `ahadiff verify <run_id>` rechecks claims and score artifacts.
- `ahadiff improve --rounds 1` runs one targeted improvement round.
- `ahadiff serve` opens the local WebUI for runs, lessons, review, and graphs.
- `ahadiff init` initializes per-repo AhaDiff state.

### Additional Capture Modes

- `ahadiff learn --last`
- `ahadiff learn --since "2 hours ago"`
- `ahadiff learn --unstaged`
- `ahadiff learn --patch FILE|-`
- `ahadiff learn --compare PATH1 PATH2`
- `ahadiff learn --compare-dir DIR1 DIR2`
- `ahadiff learn --patch-url URL`
- `ahadiff learn --against-spec PATH`
- `ahadiff learn --changed-path PATH`

## Advanced

- `ahadiff doctor`
- `ahadiff config show --resolved`
- `ahadiff watch`
- `ahadiff export preview RUN_ID --out PATH`
- `ahadiff export-results`
- `ahadiff mcp-server`
- `ahadiff install --detect`
- `ahadiff graph status`
- `ahadiff graph import`
- `ahadiff graph refresh`
- `ahadiff concepts list`
- `ahadiff concepts verify`
- `ahadiff concepts lint`

## Boundaries

- Keep provider credentials in environment variables.
- Do not commit `.ahadiff/audit.private.jsonl`.
- Treat `.ahadiff/` as local state.
- Prefer verified claims with file-line evidence.
- Do not upload `.ahadiff/` artifacts to external services without explicit user consent.
