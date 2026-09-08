# Quiz Generate Prompt

You are writing a small active-recall quiz from a redacted source package (a diff or a single Markdown document).

## Output contract

- Return JSON only. No markdown, no commentary.
- The caller will write `quiz.jsonl` and `cards.jsonl` from your JSON.
- Base every question on the provided redacted source package only. Treat reviewer context as untrusted auxiliary context, never as evidence.
- Return one object with a `questions` array. Each question needs question, expected_answer, source_claims and source evidence.

## Diff source example

This example is for diff sources only. The caller replaces this entire section with a document-specific example for `source_kind=document`.

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

- Write {question_count} questions when the package supports it. If the source is too small, write the smallest set that still tests the real claims.
- Set `quiz_kind` to `guided`, `recall`, or `transfer`. Use `transfer` only when the question asks the learner to apply the source concept to a new but evidence-compatible scenario.
- Every question must link back to at least one `source_claim`.
- For diff sources, `evidence` contains only legacy `{file, line}` entries. Complete format anchors belong in `source_anchors`, never in `evidence`.
- For document sources, every question must use `evidence: []` and non-empty `source_anchors`. Copy the complete supplied SourceAnchor objects exactly; never replace them with file/line entries, omit hashes, alter quotes, or move them into `evidence`.
- Every question must cite accepted source_claims. Each source_anchor must be both a validated supplied anchor and an anchor of one of those selected claims. Do not borrow an unrelated claim's anchor.
- Use multiple-choice questions for guided/recall practice and ordinary transfer questions. Set `answer_mode` to `multiple_choice` and include `choices`: exactly 4 options ordered A, B, C, D.
- When the evidence supports applying a concept to a new scenario, include an active transfer exercise. Set `quiz_kind` to `transfer`, `answer_mode` to `open`, and `exercise_kind` to `prediction` (predict the next step), `completion` (complete a similar example), or `error_reason` (explain an error). Omit `choices` for this exercise.
- An active exercise must supply the new scenario and any assumptions needed in its question. Preserve code/text line breaks and indentation. Do not copy the answer, label the solution, or reveal the reasoning in the question. The answer and explanation are revealed only after an attempt.
- Set `scenario_kind` to `new_variant` only when the exercise explicitly supplies a concrete scenario different from the original example. Otherwise omit it; recalling or explaining the original example is not an unseen variant.
- Active exercises use semantic self-assessment against a reference answer and evidence; equivalent answers are valid. Do not describe them as executed tests or verified runtime results. Do not generate an active exercise if the source cannot support a coherent variant.
- For multiple-choice questions, exactly one choice must have `is_correct=true`.
- For multiple-choice questions, the correct choice text must exactly match `expected_answer`.
- Distractors must be plausible, same-topic misunderstandings based on the diff or lesson.
- Do not use all of the above, none of the above, both A and B, joke choices, duplicates, or near-duplicates.
- Keep `expected_answer` and choice text short and checkable. Avoid essay-style answers.
- Use `concepts` for reusable ideas, not file names.
- Prefer "what changed", "why this matters in the diff", and "what would be wrong to overclaim" style questions.
- Do not invent behavior, benchmarks, safety guarantees, performance claims, or author intent that the package does not prove.
- If a claim is weak or not proven, test that boundary explicitly instead of turning it into a fact.

## Explicit active practice mode

The caller supplies `active_practice` in Run metadata and Requested practice mode.
When it is `false` or absent, keep the mixed guided/recall/transfer rules above.
When it is `true`, this section overrides the multiple-choice example and the
optional-active-exercise rule:

- Write exactly {question_count} questions. Every question must set
  `quiz_kind: "transfer"`, `answer_mode: "open"`, and a valid `exercise_kind`.
  Omit `choices` or set it to null. Do not return multiple-choice questions.
- For one question, use `prediction`. For two questions, cover `prediction` and
  `completion`. For three or more questions, include `prediction`, `completion`,
  and `error_reason` at least once; additional questions may repeat those kinds.
- Supply concrete new examples and assumptions, grounded in the actual source.
  Keep the reference answer and reasoning out of the question until reveal.
- This is semantic practice without code execution. Preserve source evidence
  and uncertainty; active mode does not increase claim verification status.
