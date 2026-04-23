# Lesson Hint Prompt

You are writing the hint-tier lesson from a redacted diff package.

## Output contract

- Return JSON only. No markdown, no surrounding commentary.
- The caller will render the final `lesson.hint.md` document from your JSON.
- Base every statement on the provided redacted diff package only.
- Do not rely on raw patch text, raw file-compare text, repo memory, external docs, or unstated author intent.
- Assume the reader has already seen the full lesson once.
- Keep the same teaching boundaries as the full lesson, but compress the content into high-signal hints and recall cues.
- Prefer bullets over paragraphs and keep the whole lesson short enough to skim in one pass.
- Return exactly one object with this shape:

```json
{
  "tl_dr": "short paragraph or one sentence",
  "key_points": ["..."],
  "watch_fors": ["..."],
  "claims": ["..."],
  "sources": ["..."]
}
```

## Generation rules

- Treat the redacted diff package as the full evidence boundary.
- If the package is missing evidence, record the uncertainty in `watch_fors` instead of guessing.
- Prefer hints, anchors, and recall cues over full narrative explanation.
- Use cautious language for weak claims: `may`, `appears`, `suggests`, `likely`.
- Never ship rejected claims as facts.
- A rejected claim may appear only as a caution inside `watch_fors`, never as a confirmed claim.
- Point the reader to the most important hunks or symbols first, without retelling every detail.
- `Sources` must list only evidence actually present in the package. Do not fabricate line numbers, hunk IDs, symbols, test results, performance data, or intent.
- Keep every list item self-contained and renderable as a markdown bullet.
- Avoid risky wording such as `always`, `never`, `safe`, `secure`, `faster`, `more reliable` unless the package directly proves it.
- Do not mention files, behaviors, benchmarks, runtime effects, or design intent outside the package.
