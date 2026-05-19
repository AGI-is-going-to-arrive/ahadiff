# Claim Extract Prompt

You are extracting verifiable claims from a redacted diff package.

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
- Each claim must cite at least one `source_hunk`.
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
