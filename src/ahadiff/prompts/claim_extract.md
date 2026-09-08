# Claim Extract Prompt

You are extracting verifiable claims from a redacted source package.

## Output contract

- Return JSON only. No markdown, no prose.
- Preferred envelope:

```json
{
  "claims": [
    {
      "claim_id": "optional-if-caller-fills",
      "run_id": "optional-if-caller-fills",
      "text": "Short factual claim grounded in the diff",
      "source_hunks": [
        {"file": "src/example.py", "start": 12, "end": 18, "side": "new"}
      ],
      "symbols": ["Example.run"],
      "hunk_ids": ["hunk_deadbeef1234"]
    }
  ]
}
```

## Extraction rules

- Only emit claims that can be grounded in the provided diff/package.
- Each diff claim must cite at least one `source_hunk` or supplied `source_anchor`.
- Each `source_hunk` must include `side`:
  - use `"new"` for added/modified post-change lines,
  - use `"old"` for deleted lines or rename-from references,
  - use `"either"` only when old/new cannot be disambiguated from the provided evidence and the verifier can infer it from path/hunk context,
  - use `"new"` for rename-to references.
- Use `symbols` only when the diff or symbol index actually supports them.
- Prefer narrow factual claims over broad interpretations.
- Do not cover every file mechanically.
- Cover the visible diff by high-signal change clusters: behavior changes, contracts,
  safety/privacy changes, persistence/data flow changes, tests that prove behavior, and
  cross-file wiring.
- For low-signal scaffolding or repeated mechanical edits, prefer one grouped factual claim
  with representative `source_hunks` instead of per-file claims.
- Do not cite omitted files or files outside the provided patch/package.
- Do not mention files outside the provided patch.
- Avoid risky wording such as `always`, `never`, `secure`, `faster` unless the diff directly supports it.
- If the diff only shows deletion or rename, make that explicit in `text`.

## Format-aware evidence and independent documents

- When supplied, copy complete objects from `Validated source anchors` into
  `source_anchors`. Preserve every field, including the side, locator, line range,
  quote and content hash. Never invent an anchor or cite the auxiliary reviewer context.
- `assertion_kind` distinguishes `source_fact` (text actually present), `semantic`
  (interpretation or intent), and `runtime_effect` (execution or operational outcome).
- A `source_fact` is deterministically verified only for a faithful full quote:
  set `text` to exactly the anchor's complete `quote`. Do not attach an additional
  conclusion to the quote. A truncated quote or text fallback remains weak.
- Semantic explanations stay weak. Runtime effects stay not_proven without
  execution evidence. A heading, cell id or configuration key alone proves no outcome.
- If `source_kind` is `document`, the input is one independent Markdown source.
  There is no before/after comparison. Use `source_anchors`, `source_hunks: []`,
  `symbols: []` and `hunk_ids: []`; do not invent a patch or a code change.
  Cover the supplied sections and paragraphs with faithful source quotes and
  clearly classified interpretations. The document itself may be factually wrong:
  source_fact only verifies what the document says, not that the statement is true.
- Optional auxiliary reviewer context may explain intent. It cannot establish
  source facts, override contradictory evidence, or increase a claim's status.
