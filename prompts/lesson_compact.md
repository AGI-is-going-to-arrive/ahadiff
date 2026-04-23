# Lesson Compact Prompt

You are writing the compact-tier lesson card from a redacted diff package.

## Output contract

- Return JSON only. No markdown, no surrounding commentary.
- The caller will render the final `lesson.compact.md` document from your JSON.
- Base every statement on the provided redacted diff package only.
- Do not rely on raw patch text, raw file-compare text, repo memory, external docs, or unstated author intent.
- Produce a compact concept card that stays under 500 tokens total.
- Keep the same section order as the full lesson conceptually, but compress every section to the minimum useful reminder.
- Prefer short bullets or sentence fragments. Avoid long paragraphs and avoid code fences.
- Return exactly one object with this shape:

```json
{
  "headline": "short title",
  "summary": ["..."],
  "concepts": ["..."],
  "sources": ["..."]
}
```

## Generation rules

- Treat the redacted diff package as the full evidence boundary.
- If the package is missing evidence, keep the reminder conservative inside `summary` instead of guessing.
- Keep only the highest-signal teaching points. Trim wording before dropping core reminders or source anchors.
- Use cautious language for weak claims: `may`, `appears`, `suggests`, `likely`.
- Never ship rejected claims as facts.
- A rejected claim must be excluded instead of being turned into a new section.
- `Sources` must list only evidence actually present in the package. Do not fabricate line numbers, hunk IDs, symbols, test results, performance data, or intent.
- Keep every list item self-contained and renderable as a markdown bullet.
- Avoid risky wording such as `always`, `never`, `safe`, `secure`, `faster`, `more reliable` unless the package directly proves it.
- Do not mention files, behaviors, benchmarks, runtime effects, or design intent outside the package.
