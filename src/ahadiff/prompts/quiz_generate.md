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
      "quiz_kind": "recall",
      "answer_mode": "multiple_choice",
      "choices": [
        {
          "label": "A",
          "text": "It now loops across attempts and continues after exceptions.",
          "is_correct": true
        },
        {
          "label": "B",
          "text": "It retries only once after a successful response.",
          "is_correct": false
        },
        {
          "label": "C",
          "text": "It removes exception handling from the retry path.",
          "is_correct": false
        },
        {
          "label": "D",
          "text": "It changes the helper to skip retry attempts.",
          "is_correct": false
        }
      ],
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
- Set `quiz_kind` to `guided`, `recall`, or `transfer`. Use `transfer` only when the question asks the learner to apply the diff concept to a new but evidence-compatible scenario.
- Every question must link back to at least one `source_claim`.
- Every question must include at least one concrete evidence anchor in `evidence`.
- Set `answer_mode` to `multiple_choice` for every generated question.
- Every question must include `choices`: exactly 4 options ordered A, B, C, D.
- Exactly one choice must have `is_correct=true`.
- The correct choice text must exactly match `expected_answer`.
- Distractors must be plausible, same-topic misunderstandings based on the diff or lesson.
- Do not use all of the above, none of the above, both A and B, joke choices, duplicates, or near-duplicates.
- Keep `expected_answer` and choice text short and checkable. Avoid essay-style answers.
- Use `concepts` for reusable ideas, not file names.
- Prefer "what changed", "why this matters in the diff", and "what would be wrong to overclaim" style questions.
- Do not invent behavior, benchmarks, safety guarantees, performance claims, or author intent that the package does not prove.
- If a claim is weak or not proven, test that boundary explicitly instead of turning it into a fact.
