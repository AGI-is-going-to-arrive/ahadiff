
<!-- AHADIFF:BEGIN target=aider -->
## AhaDiff

Use AhaDiff as the learn-back layer for AI-written diffs:

- `ahadiff learn HEAD~1..HEAD` after a commit.
- `ahadiff learn --staged` before committing staged changes.
- `ahadiff quiz <run_id>` and `ahadiff review` for retention.
- `ahadiff verify <run_id>` when checking an existing run.

Keep explanations grounded in verified claims and file-line evidence. Store
provider secrets in environment variables, not repository files.
<!-- AHADIFF:END -->
