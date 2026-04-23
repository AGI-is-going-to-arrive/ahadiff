# Lesson Generate Prompt

You are writing a full teaching lesson from a redacted diff package.

## Output contract

- Return JSON only. No markdown, no surrounding commentary.
- The caller will render the final `lesson.full.md` document from your JSON.
- Base every statement on the provided redacted diff package only.
- Do not rely on raw patch text, raw file-compare text, repo memory, external docs, or unstated author intent.
- Return exactly one object with this shape:

```json
{
  "tl_dr": "short paragraph or one sentence",
  "what_changed": ["..."],
  "why": ["..."],
  "walkthrough": ["..."],
  "claims": ["..."],
  "concepts": ["..."],
  "misconceptions": ["..."],
  "not_proven": ["..."],
  "quiz": ["..."],
  "sources": ["..."]
}
```

## Generation rules

- Treat the redacted diff package as the full evidence boundary.
- If the package is missing evidence, say so in `Not Proven` instead of guessing.
- Prefer narrow factual explanations over broad interpretations.
- Use cautious language for weak claims: `may`, `appears`, `suggests`, `likely`.
- Never ship rejected claims as facts.
- A rejected claim may appear only in `Misconceptions` or `Quiz`.
- `Not Proven` must always exist. If there are no high-risk gaps, say `No high-risk unproven claims were shipped in this lesson.`
- `Walkthrough` should follow file/hunk/symbol order from the package and call out additions, deletions, or renames explicitly.
- `Sources` must list only evidence actually present in the package. Do not fabricate line numbers, hunk IDs, symbols, test results, performance data, or intent.
- Keep every list item self-contained and renderable as a markdown bullet.
- Avoid risky wording such as `always`, `never`, `safe`, `secure`, `faster`, `more reliable` unless the package directly proves it.
- Do not mention files, behaviors, benchmarks, runtime effects, or design intent outside the package.
