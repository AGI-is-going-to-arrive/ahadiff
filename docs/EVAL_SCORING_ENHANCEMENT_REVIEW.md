# AhaDiff 评估打分增强最终审查记录

日期：2026-05-24

结论：**GO for this change set**。本轮审查发现的真实问题已经修复，并用目标后端测试、前端 typecheck / Vitest / build、Run Detail 浏览器测试、a11y 浏览器测试和一次临时 run 复算验证过。

这不是发布级全绿。wheel、real-serve、live judge、远端 CI、Linux Docker gate、真实 Windows runner、全量后端 unit / integration / eval、全量 frontend Vitest 和完整 Playwright matrix 没有在本轮重跑。

## 审查范围

已按当前未提交 diff 读取并复核：

- `src/ahadiff/claims/verify.py`
- `src/ahadiff/eval/deterministic.py`
- `src/ahadiff/eval/evaluator.py`
- `src/ahadiff/eval/gates.py`
- `src/ahadiff/eval/ratchet.py`
- `src/ahadiff/serve/routes_runs.py`
- `viewer/src/api/schemas.ts`
- `viewer/src/api/types.ts`
- `viewer/src/components/ScoreBreakdown.tsx`
- `viewer/src/components/JudgeReport.tsx`
- `viewer/src/utils/hard-gates.ts`
- 相关 unit、Vitest、Playwright 和 serve mock fixture

`llmdoc/` 不存在，已按仓库规则跳过。

## 已确认的实现事实

- 无 spec 的 run 仍把 `spec_alignment` 写成 `0 / 0`，并从 deterministic overall 中排除；这不是扣分。
- LLM judge 仍是 advisory。`/api/run/{run_id}/score` 返回 deterministic score，`/api/run/{run_id}/judge` 返回独立 judge artifact；judge 高分不会改 `score.json.verdict`。
- Ratchet 在选择 ancestry / baseline 后，会先检查 `report.verdict != "PASS"` 或 hard gate 失败；命中时返回 `discard`，不会进入 `baseline` / `keep`。
- `select_baseline_event()` 现在会跳过历史 `verdict != "PASS"` 的 counted event，避免失败 run 被选成 baseline。
- Verifier 支持同文件同 side 的 multi-hunk region anchor，把可审计范围归一化成 hunk-bounded `SourceHunk`，并带上 `hunk_id` / `hunk_hash`。
- Verifier 仍拒绝 mode-only、binary、file-not-in-patch、side mismatch、hunk id mismatch、过宽范围和 truncated hunk 未捕获行；没有新增 `context_annotation` reason code，也没有新增 `SourceHunk` 字段。
- Hard gate payload 支持结构化 `policy`，前端 schema 仍保持 strict，只接受已声明字段。
- Run Detail Score tab 会本地化展示 adaptive gate policy；Score / Judge 中 `max_score = 0` 的维度显示为 N/A，不把 no-spec `spec_alignment` 渲染成失败。

## 本轮修复项

1. **Ratchet baseline 选择**

   历史 counted event 如果 `verdict != "PASS"`，现在不会作为 baseline。新增测试覆盖 failed historical baseline 被跳过。

2. **Truncated hunk 证据**

   Multi-hunk fallback 不再把 `120..121` 这类跨入 truncated 未捕获行的范围裁成 `120..120` 后当作有效 evidence。新增测试锁住该边界。

3. **Spec alignment 前端 schema**

   前端 `specAlignmentArtifactSchema` 接受后端真实写入的 `eval_bundle_version` 和 `rubric_version`，避免真实 artifact 因 strict parse 失败。

4. **Judge browser fixture**

   Run Detail Playwright mock 已更新到当前 `llm_judge` payload 形状，并覆盖 Judge tab 的 `N/A` 展示。

## 真实 run 复算

目标 run：

- `.ahadiff/runs/run_019e5596a965d091cd8fb6b4430ca29e`

原目录里的 `claims.jsonl` 是旧 verifier 已写入的 persisted artifact，本轮没有原地改写它。为了验证代码修复，审查时把 run 复制到临时目录，从 `claims.raw.jsonl` 重新执行 verifier，再 evaluate 临时 run。

临时复算结果：

```text
candidate_count = 24
statuses = 19 verified, 1 weak, 1 not_proven, 3 rejected
rejected_reasons = 3 evidence_missing
overall = 85.54
verdict = PASS
accuracy = 16.83 / 20
evidence = 15.22 / 18
diff_coverage = 9.11 / 14
spec_alignment = 0 / 0
failed_gates = []
```

## 验证

后端目标回归：

```bash
UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run pytest \
  tests/unit/test_ratchet.py \
  tests/unit/test_claim_verify.py \
  tests/unit/test_gate3_hardening.py \
  tests/unit/test_evaluator.py \
  tests/unit/test_gates.py \
  tests/unit/test_routes_judge.py \
  -q
# 158 passed
```

后端静态检查：

```bash
UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run ruff check src/ahadiff/claims/verify.py src/ahadiff/eval/ratchet.py tests/unit/test_claim_verify.py tests/unit/test_ratchet.py
UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run ruff format --check src/ahadiff/claims/verify.py src/ahadiff/eval/ratchet.py tests/unit/test_claim_verify.py tests/unit/test_ratchet.py
UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run pyright src/ahadiff/eval/ratchet.py src/ahadiff/claims/verify.py tests/unit/test_ratchet.py tests/unit/test_claim_verify.py
# ruff passed; format check passed; pyright 0 errors
```

前端目标验证：

```bash
pnpm --dir viewer run typecheck
pnpm --dir viewer exec vitest run tests/unit/i18n-parity.test.ts tests/unit/graph-schemas.test.ts src/components/ScoreBreakdown.test.tsx src/components/JudgeReport.test.ts
pnpm --dir viewer run build
# typecheck passed; 4 Vitest files / 41 tests passed; build passed
```

浏览器验证：

```bash
AHADIFF_VIEWER_E2E_PORT=5174 pnpm --dir viewer exec playwright test tests/e2e/run-detail.spec.ts --reporter=line
# 300 passed

AHADIFF_VIEWER_E2E_PORT=5175 pnpm --dir viewer exec playwright test tests/e2e/a11y.spec.ts --reporter=line
# 255 passed
```

Git hygiene：

```bash
git diff --check HEAD
# passed
```

## 未覆盖

- wheel build 未重跑。
- real-serve 未重跑。
- live judge 未重跑。
- 远端 CI 未重跑。
- Linux Docker gate 未重跑。
- 真实 Windows runner 未跑。
- 后端全量 unit / integration / eval、前端全量 Vitest、完整 Playwright matrix 未在本轮重跑。

## 最终判断

本轮审查发现的问题已经修复，改动面内没有剩余 Critical / High findings。当前代码可以进入提交；发布级判断仍需要后续按发布 gate 补齐未覆盖项。
