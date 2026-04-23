# Quiz Generate Prompt

You are writing a small active-recall quiz from a redacted diff package.

## Output contract

- Return JSON only. No markdown, no commentary.
- The caller will write `quiz.jsonl` and `cards.jsonl` from your JSON.
- Base every question on the provided redacted diff package only.
- Return exactly one object with this shape:

```json
{
  "questions": [
    {
      "question": "What changed in the retry helper?",
      "expected_answer": "It now loops across attempts and continues after exceptions.",
      "source_claims": ["claim_deadbeef1234"],
      "concepts": ["retry loop"],
      "evidence": [{"file": "src/app.py", "line": 3}],
      "explanation": "Optional short explanation for answer reveal."
    }
  ]
}
```

## Generation rules

- Write 3 questions when the package supports it. If the diff is too small, write the smallest set that still tests the real claims.
- Every question must link back to at least one `source_claim`.
- Every question must include at least one concrete evidence anchor in `evidence`.
- Keep the answer short and checkable. Avoid essay-style answers.
- Use `concepts` for reusable ideas, not file names.
- Prefer "what changed", "why this matters in the diff", and "what would be wrong to overclaim" style questions.
- Do not invent behavior, benchmarks, safety guarantees, performance claims, or author intent that the package does not prove.
- If a claim is weak or not proven, test that boundary explicitly instead of turning it into a fact.
