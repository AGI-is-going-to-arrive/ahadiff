# AhaDiff Improve Program

You are revising one mutable AhaDiff prompt file to improve lesson quality.

Immutable rules:

- Modify exactly one target file from this allowlist:
  - `lesson_generate.md`
  - `lesson_hint.md`
  - `lesson_compact.md`
  - `quiz_generate.md`
  - `claim_extract.md`
- Never modify `improve_program.md`, evaluator files, rubric files, tests, viewer files, or source code.
- Return JSON only with this shape:

```json
{
  "target_file": "lesson_generate.md",
  "content": "full replacement markdown content"
}
```

Quality bar:

- Optimize for the requested weakest dimension first.
- Preserve the existing prompt's scope and output contract.
- Keep edits minimal and explainable through the diff itself.
- Prefer one strong improvement over several speculative ones.
- Avoid prompt bloat, repeated instructions, and verbose style guidance.
- If the current prompt is already adequate, make the smallest safe revision that could still improve the target dimension.
