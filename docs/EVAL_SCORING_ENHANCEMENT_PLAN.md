# Eval Scoring Enhancement Implementation Plan

日期：2026-05-24

本计划取代同名旧草案，并以执行前读取到的真实代码、旧落盘 run artifact、浏览器探测和目标测试结果为依据。旧草案里“直接把 `rejected + line_outside_hunk + low` 排除出 accuracy / evidence 分母”的做法不得执行；该条件过宽，会把 mode-only、side mismatch、真实无效 evidence 一并放过。

## 实施收口

2026-05-24 本计划已按真实代码落地并完成一轮 Codex 对抗式审查 / 修复。最终实现没有新增 `context_annotation` reason code，也没有新增 `SourceHunk` 公共字段；核心修复是 verifier 支持同文件同 side 的 multi-hunk region anchor，并继续拒绝 mode-only、binary、file-not-in-patch、side mismatch、hunk id mismatch、过宽范围和 truncated hunk 未捕获行。Ratchet 也补上显式防线：`verdict != "PASS"` 或 hard gate 失败时不会进入 `baseline` / `keep`。

需要注意：目标 run 目录里已有的 `claims.jsonl` 没有被原地改写；直接读取旧 persisted artifact 仍会看到旧分数。实际收口验证是在临时目录复制该 run 后，从 `claims.raw.jsonl` 重新执行 verifier 并再跑 evaluator：`24` 条 candidate 变成 `19 verified + 1 weak + 1 not_proven + 3 rejected`，`overall = 85.54`，`verdict = PASS`，accuracy `16.83 / 20`，evidence `15.22 / 18`，没有 failed hard gates。

本轮真实验证覆盖：

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

```bash
UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run ruff check src/ahadiff/claims/verify.py src/ahadiff/eval/ratchet.py tests/unit/test_claim_verify.py tests/unit/test_ratchet.py
UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run ruff format --check src/ahadiff/claims/verify.py src/ahadiff/eval/ratchet.py tests/unit/test_claim_verify.py tests/unit/test_ratchet.py
UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run pyright src/ahadiff/eval/ratchet.py src/ahadiff/claims/verify.py tests/unit/test_ratchet.py tests/unit/test_claim_verify.py
# ruff passed; format check passed; pyright 0 errors
```

```bash
pnpm --dir viewer run typecheck
pnpm --dir viewer exec vitest run tests/unit/i18n-parity.test.ts tests/unit/graph-schemas.test.ts src/components/ScoreBreakdown.test.tsx src/components/JudgeReport.test.ts
pnpm --dir viewer run build
AHADIFF_VIEWER_E2E_PORT=5174 pnpm --dir viewer exec playwright test tests/e2e/run-detail.spec.ts --reporter=line
AHADIFF_VIEWER_E2E_PORT=5175 pnpm --dir viewer exec playwright test tests/e2e/a11y.spec.ts --reporter=line
# typecheck passed; Vitest 4 files / 41 tests passed; build passed; Run Detail Playwright 300 passed; a11y Playwright 255 passed
```

未在本轮重跑：wheel、real-serve、live judge、远端 CI、Linux Docker gate、真实 Windows runner、全量后端 unit / integration / eval、全量 frontend Vitest 和完整 Playwright matrix。

## 0. 修复前问题真相

目标 run 的旧落盘 artifact：

- `run_019e5596a965d091cd8fb6b4430ca29e`
- WebUI：`http://127.0.0.1:8765/#/run/run_019e5596a965d091cd8fb6b4430ca29e?tab=judge`
- 本地产物目录：`.ahadiff/runs/run_019e5596a965d091cd8fb6b4430ca29e/`

修复前诊断结论：

1. 这次 run 没通过，是因为 deterministic `score.json` 的 hard gates 失败：
   - `accuracy = 12.29 / 20 < 14`
   - `evidence = 11.01 / 18 < 12`
   - `overall = 75.07`
   - `verdict = FAIL`
2. `spec_alignment = 0 / 0` 是正确的“不适用”语义，不是扣分：
   - 本 run 的 `metadata.source_detail.type = "last"`，没有 `against_spec` / `spec_path` / `spec_ref`。
   - run 目录没有 `spec_alignment.json`。
   - `dimension_score_from_artifact()` 在无 spec 约束时返回 `applicable=False`。
   - `build_deterministic_scores()` 会把非适用维度的 `max_score` 设为 `0.0`。
   - `_resolve_overall()` 会排除 `max_score <= 0` 的维度。
3. LLM judge 只是 advisory，不覆盖 deterministic verdict：
   - `judge.json` 给了 `overall = 87.78`、`accuracy = 18`、`evidence = 16.5`。
   - `run_llm_judge_for_run()` 对 deterministic `max_score = 0` 的维度保留 `0 / 0`。
4. 低分的直接原因是 claims 分布：
   - `14 verified + 1 weak + 9 rejected`
   - 9 条 rejected 全是 `reason_code = "line_outside_hunk"`、`confidence = "low"`。
   - 当时 `_claim_weighted_score()` 用全部 claims 作分母，rejected 权重为 `0`。
   - 公式近似：`(14 * 1 + 1 * 0.75 + 9 * 0) / 24 * 20 = 12.29`。
   - evidence 同理再乘 `_source_hunk_bonus(claims)`，得到 `11.01`。
5. 这些 rejected 里有大量“一个 claim 锚到同文件多段 diff hunk 的宽范围”的形态，例如同一 `SourceHunk` 覆盖多段相邻 provider / UI 改动。修复前 verifier 只接受单 hunk 范围，导致宽范围 claim 被整条 reject。

已执行的最小验证：

```bash
UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run pytest \
  tests/unit/test_evaluator.py::test_spec_alignment_without_spec_is_not_applicable_score_zero \
  tests/unit/test_evaluator.py::test_run_llm_judge_for_run_writes_judge_artifact \
  tests/unit/test_gate3_hardening.py::test_gate3_deterministic_scores_handle_empty_and_unicode_claims \
  tests/unit/test_ratchet.py::test_git_input_keeps_when_score_improves_over_ancestor \
  -q
# 4 passed
```

```bash
python3 - <<'PY'
import json, pathlib, collections
run = pathlib.Path('.ahadiff/runs/run_019e5596a965d091cd8fb6b4430ca29e')
claims = [json.loads(line) for line in (run / 'claims.jsonl').read_text().splitlines() if line.strip()]
print(len(claims), collections.Counter(claim['status'] for claim in claims))
PY
# 24 Counter({'verified': 14, 'rejected': 9, 'weak': 1})
```

## 1. 执行契约

本计划必须按用户指定的真实工具路由执行，不得把 Codex / Antigravity 当成 Claude 子代理角色名。

### 1.1 Claude 职责

Claude 只负责总编排：

- 拆分 phase / sprint / gate。
- 分派真实 Antigravity 和真实 Codex。
- 聚合结果、判断是否进入下一阶段。
- 维护 checklist、风险记录、测试结果。
- 不直接修改代码。

如果 Antigravity 连续多次 429、超时或不可用，前端实现是否改由 Claude 兜底与“Claude 不改代码”存在冲突。默认处理方式是：Claude 先停在该 gate，记录失败证据并请求用户确认；没有用户确认前，不由 Claude 直接改前端。

### 1.2 Codex 调用规则

Codex 必须通过 Claude Code 已安装的 `codex-plugin-cc` 调用，使用默认模型：

- 实现 / 修复 / 调查：`/codex:rescue --background "..."`
- 常规审查：`/codex:review --background "..."`
- 对抗式审查：`/codex:adversarial-review --background "..."`
- 状态：`/codex:status`
- 结果：`/codex:result`
- 取消：`/codex:cancel`

禁止：

- 禁止附带 `--model` / `--effort`，除非用户另行明确要求。
- 禁止通过 `Skill(codex:review)` 调用。
- 禁止用 `codeagent-wrapper` 代替 `codex-plugin-cc` 调 Codex。

Codex 任务内部应在安全前提下尽量使用 sub-agents / multi-agents：

- 只读审查可按 backend scoring、verifier、serve API、tests、cross-platform 拆分并行。
- 写入任务必须按 disjoint write set 拆分；同一文件写入串行。
- 任一 phase 写完后，必须由独立 Codex 对抗式审查复核。

### 1.3 Antigravity 调用规则

所有前端 UI / UX / 交互 / 浏览器 / i18n 展示相关任务交给真实 Antigravity：

- 涉及 `viewer/`、CSS、React component、Zod schema、Playwright、前端 i18n 的实现或设计评审，默认分派给 Antigravity。
- Antigravity 需要覆盖 Chromium / Firefox / WebKit、desktop / mobile、English / zh-CN。
- Antigravity 不得修改 backend Python；如发现 backend API 不足，输出阻塞项，由 Claude 转交 Codex。

本仓库已存在 `codeagent-wrapper`，但该 plan 不假设固定 Antigravity 命令名。Claude 执行时必须使用当前 CCG 环境中真实 Antigravity 入口；如果入口不可用，记录命令、退出码和 stderr，再进入 fallback 决策。

### 1.4 每阶段 gate

每个 Phase 完成后必须按顺序执行：

1. Owner 自测。
2. Codex adversarial review。
3. 修复 Critical / High；Warning 需记录并决定是否进入下一阶段。
4. 浏览器实测（如果触及 viewer 或用户可见评分展示）。
5. Claude + Codex 交叉 review。
6. 产出本阶段 evidence block，再进入下一阶段。

任何阶段出现以下情况必须停下：

- hard gate 失败仍进入 `baseline` / `keep`。
- 无 spec run 的 `spec_alignment` 被计入总分。
- `judge.json` 覆盖 deterministic verdict。
- 前端 strict schema 因新增字段拒收 score payload。
- zh-CN / English 文案不一致。
- Windows / macOS / Linux 任一必需 gate 未跑且未标明原因。

## 2. 实现路线总览

执行顺序：

1. Phase 0：锁定现有失败 run 的诊断回归。
2. Phase 1：修复 learn ratchet 对 failed hard gates 的接受漏洞。
3. Phase 2：修复 verifier 对 multi-hunk region anchor 的过度 reject。
4. Phase 3：保守调整 deterministic scoring 解释和边界测试，不做宽泛 rejected 豁免。
5. Phase 4：引入可审计 adaptive accuracy / evidence gates，并保留 rubric contract。
6. Phase 5：Antigravity 更新前端评分展示、i18n 和跨浏览器测试。
7. Phase 6：端到端验证、cross-review、真实问题 run 复算。

不要先做 Phase 4。Adaptive gate 是兜底策略，不应掩盖 verifier 对宽范围证据锚点的误判。

## 3. Phase 0：诊断回归和不变量

Owner：Codex via `/codex:rescue --background`

目标：

- 把修复前失败原因固定成测试和 fixture，防止未来误判。
- 明确 `spec_alignment 0/0`、LLM judge advisory、deterministic hard gate 的边界。

需要新增或扩展测试：

- `tests/unit/test_evaluator.py`
  - 保留并扩展 `test_spec_alignment_without_spec_is_not_applicable_score_zero()`。
  - 新增 no-spec + judge 高分 invariant：LLM judge 给 `spec_alignment = 10` 时，最终 `judge.json` 仍写 `0 / 0`。
  - 新增 deterministic verdict invariant：`judge.json` 高分不能改变 `score.json.verdict`。
- `tests/unit/test_gate3_hardening.py`
  - 新增修复前 run 形态的 synthetic fixture：`14 verified + 1 weak + 9 rejected`。
  - 断言旧公式下会低于 hard gate，作为后续修复的对照。
- `tests/unit/test_routes_judge.py` 或 Run Detail 相关测试
  - 断言 `/api/run/{run_id}/score` 返回 deterministic score。
  - 断言 `/api/run/{run_id}/judge` 是 advisory artifact。

Gate：

```bash
UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run pytest \
  tests/unit/test_evaluator.py \
  tests/unit/test_gate3_hardening.py \
  tests/unit/test_routes_judge.py \
  -q
```

Codex review：

```text
/codex:adversarial-review --background "Review Phase 0 diagnostic invariants for eval scoring. Verify no-spec 0/0, judge advisory behavior, and deterministic hard gate ownership against current code and tests."
```

## 4. Phase 1：Ratchet hard gate 修复

Owner：Codex via `/codex:rescue --background`

真实代码依据：

- `src/ahadiff/eval/evaluator.py::_resolve_verdict()`：`not hard_gates.passed` 时返回 `FAIL`。
- `src/ahadiff/eval/ratchet.py::decide_learn_ratchet()`：修复前会在无 baseline 时直接 `baseline`，有 baseline 时只比较 `overall`。
- 目标 run 当时已经最终 `status = discard`，但代码层仍缺少显式防线；必须用测试锁住。

改动要求：

- 在 `decide_learn_ratchet()` 中，完成 ancestry 和 baseline selection 后，先检查：
  - `report.verdict != "PASS"`，或
  - `not report.hard_gates.passed`
- 命中时返回 `RatchetDecision(status="discard", ...)`。
- `note_payload` 必须包含：
  - `ratchet_reason = "verdict_or_hard_gate_failed"`
  - `verdict`
  - `failed_gates`
  - 若存在 baseline，包含 `baseline_overall`
- 该 check 必须早于：
  - `baseline is None -> baseline`
  - `degraded_comparison -> keep`
  - `overall >= baseline.overall -> keep`

测试要求：

- `tests/unit/test_ratchet.py`
  - failed gate + no prior baseline -> `discard`
  - failed gate + score improves -> `discard`
  - `verdict = "CAUTION"` + gates pass -> `discard`
  - failed gate overrides `degraded_comparison`

Gate：

```bash
UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run pytest tests/unit/test_ratchet.py -q
UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run ruff check src/ahadiff/eval/ratchet.py tests/unit/test_ratchet.py
UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run ruff format --check src/ahadiff/eval/ratchet.py tests/unit/test_ratchet.py
UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run pyright src/ahadiff/eval/ratchet.py tests/unit/test_ratchet.py
```

## 5. Phase 2：Verifier 支持 multi-hunk region anchor

Owner：Codex via `/codex:rescue --background`

本阶段是核心修复。不要用宽泛 scoring exemption 代替 verifier 修复。

### 5.1 当前缺陷

`src/ahadiff/claims/verify.py` 修复前行为：

- `_match_source_hunks()` 遇到 `_MatchFailure` 会整条 claim 变成 `rejected`。
- 所有 `_MatchFailure` 产出的 rejected claim 都是 `confidence = "low"`。
- 多种语义都会落到 `line_outside_hunk`：
  - 真正行号超出文件。
  - requested side 不存在或混合 old/new side。
  - mode-only / binary / no hunks。
  - 同一个 source range 覆盖多个 diff hunks，中间带 context gaps。

因此，`rejected + line_outside_hunk + low` 不能作为 scoring-exempt 的充分条件。

### 5.2 新行为

新增一个 verifier 匹配路径：multi-hunk region anchor。

当单个 `SourceHunk` 满足全部条件时，不应 reject：

- file 能解析到当前 patch 的 `FileLineMap`。
- requested side 可以解析为 `old` 或 `new`。
- start / end 在该 side 的真实文件文本范围内。
- source range 与同一 side 的一个或多个 diff hunks 有交集。
- range span 不超过安全上限，例如 `120` 行；超过上限必须继续 rejected 或降级为 not_proven，不得直接验证。
- 不是 mode-only / binary / no-hunk 文件。
- 不是 old/new side 混合才产生的伪匹配。

匹配成功时：

- 将宽范围 `SourceHunk` 归一化为多个 hunk-bounded `SourceHunk`。
- 每个归一化 hunk 必须填入 `hunk_id` 和可用的 `hunk_hash`。
- 后续 claim status 仍走现有 `classify_claim_status()` / negative scan 路径。
- 不新增 `context_annotation` reason code。
- 不新增 SourceHunk 公共字段，除非 Codex 能证明没有更小兼容方案。

### 5.3 保持 rejected 的情况

以下仍必须 rejected，不得通过 scoring 绕过：

- mode-only 文件没有 diff hunk。
- binary / no text 文件。
- line outside file。
- range 跨越 requested side 不存在的 old/new 行。
- file not in patch。
- hunk id mismatch。
- source range 过宽，无法作为可审计证据。

### 5.4 测试

更新 `tests/unit/test_claim_verify.py`：

- multi-hunk same-file same-side range 可以归一化为多个 matched hunks。
- multi-hunk range 中间有 context gap 但两端命中 diff hunks，仍可通过归一化。
- old/new side 混合 range 仍 rejected，保持现有 `test_verify_claim_rejects_source_range_that_only_matches_mixed_old_new_lines()` 语义。
- mode-only 文件仍 rejected，保持 `test_gate3_claim_extraction_passes_mode_only_file_to_verifier()` 语义。
- 过宽 range 仍 rejected，避免 `1..9999` 通过。

更新 `tests/unit/test_gate3_hardening.py`：

- 修复前 synthetic run：9 条宽范围 claim 经 multi-hunk normalization 后，不再全部作为 rejected 分母惩罚。
- 断言 normalized source hunks 能提升 diff coverage / evidence 可解释性，但不能伪造未命中的文件。

Gate：

```bash
UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run pytest \
  tests/unit/test_claim_verify.py \
  tests/unit/test_gate3_hardening.py \
  -q
UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run ruff check src/ahadiff/claims/verify.py tests/unit/test_claim_verify.py tests/unit/test_gate3_hardening.py
UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run ruff format --check src/ahadiff/claims/verify.py tests/unit/test_claim_verify.py tests/unit/test_gate3_hardening.py
UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run pyright src/ahadiff/claims/verify.py tests/unit/test_claim_verify.py tests/unit/test_gate3_hardening.py
```

## 6. Phase 3：Deterministic scoring 边界收口

Owner：Codex via `/codex:rescue --background`

目标：

- 不再把所有 `line_outside_hunk + low` 从分母排除。
- 如果 Phase 2 后仍需要 scoring exemption，只允许使用明确、窄化、可审计的 verifier diagnostic。

允许的最小改动：

- `_claim_weighted_score()` 可以内部构造 `scoreable_claims`，但过滤条件必须来自 Phase 2 明确生成的窄化诊断，而不是裸 `reason_code == "line_outside_hunk"`。
- numerator、denominator、empty behavior、`_source_hunk_bonus()` 必须使用同一 `scoreable_claims` 集合。
- `_diff_coverage_score()` 默认继续使用所有已验证或归一化后的 source hunks；如果要过滤，必须给出单独测试证明不会降低真实 coverage。
- contradicted claim hard gate 继续使用所有 claims。

推荐实现顺序：

1. 先跑 Phase 2 后的目标 run synthetic fixture。
2. 如果 accuracy / evidence 已通过，不做 scoring exemption。
3. 如果仍低于 gate，再引入窄化 exemption，并把 reason 写清楚。

必须新增测试：

- no claims -> 仍为 `0`，reason 不变或更清楚。
- all non-scoreable claims -> 不除以 0，reason 明确。
- rejected `evidence_missing` / `hunk_id_mismatch` 仍降低 accuracy / evidence。
- mode-only / side mismatch rejected 仍降低分数。
- normalized multi-hunk region 不再被当作 rejected 低权重。

Gate：

```bash
UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run pytest \
  tests/unit/test_gate3_hardening.py \
  tests/unit/test_evaluator.py \
  -q
```

## 7. Phase 4：Adaptive accuracy / evidence gates

Owner：Codex via `/codex:rescue --background`

目标：

- 大 diff 下，accuracy / evidence gate 可以有保守 adaptive threshold。
- 这只是大 diff 规模噪声的兜底，不应掩盖 verifier 错误或无效 evidence。

### 7.1 后端策略

新增 accuracy / evidence gate policy，建议复用 diff size basis：

- normal：`visible_hunks <= 20 and visible_changed_lines <= 400`，ratio `1.00`
- medium：`visible_hunks <= 80 and visible_changed_lines <= 1200`，ratio `0.95`
- large：`visible_hunks <= 160 and visible_changed_lines <= 3000`，ratio `0.90`
- very_large：否则，ratio `0.85`

但必须加质量约束：

- 如果 rejected ratio 仍高于 `25%` 且 rejected 不是 Phase 2 定义的 safe diagnostic，不能仅靠 adaptive gate 通过。
- 如果 `contradicted_claims`、`secret_leak`、`injection_unresolved`、`critical_safety_findings` 失败，adaptive gate 不得覆盖。
- `RUBRIC_WEIGHTS` 和 `rubric.yaml` 的 hard gate contract 不变；adaptive threshold 是 runtime policy。

### 7.2 Payload 设计

旧草案只把 policy 写进英文 `detail` 字符串。这个方案不够好，因为前端 i18n 会直接显示英文。

推荐新增结构化字段：

```python
HardGatePolicy = {
    "kind": "adaptive_threshold",
    "ratio": 0.85,
    "regime": "very_large",
    "basis": {
        "visible_files": 44,
        "visible_hunks": 164,
        "visible_changed_lines": 2756,
        "rejected_ratio": 0.12,
    },
}
```

`HardGateResult.as_payload()` 继续保留 `detail`，但新增可选 `policy`：

```json
{
  "passed": true,
  "detail": "accuracy score 12.40 >= 11.90; adaptive_ratio=0.85; regime=very_large",
  "score": 12.4,
  "threshold": 11.9,
  "policy": {
    "kind": "adaptive_threshold",
    "ratio": 0.85,
    "regime": "very_large",
    "basis": {
      "visible_files": 44,
      "visible_hunks": 164,
      "visible_changed_lines": 2756
    }
  }
}
```

如果 Codex 判断新增字段风险过高，则必须改为 backend only `detail`，并同步让 Antigravity 在前端明确显示“后端英文详情为 raw audit detail”；这种 fallback 不能作为最终产品态。

### 7.3 后端测试

更新 `tests/unit/test_gates.py`：

- unavailable basis -> threshold 仍是 `14.00` / `12.00`。
- medium / large / very_large -> threshold 分别为：
  - accuracy：`13.30` / `12.60` / `11.90`
  - evidence：`11.40` / `10.80` / `10.20`
- score 等于 rounded threshold 时 pass。
- rejected ratio quality constraint 生效。
- policy payload 字段只在 adaptive gate 上出现。

更新 `tests/unit/test_evaluator.py`：

- `evaluate_run()` 将 `visible_files`、`visible_hunks`、`visible_changed_lines` 传入 accuracy / evidence policy。
- 目标 run 形态 `44 files / 164 hunks / 2756 lines` 走 `very_large`。
- no-spec run 仍 `spec_alignment 0/0` 且不参与 overall。

Gate：

```bash
UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run pytest \
  tests/unit/test_gates.py \
  tests/unit/test_evaluator.py \
  tests/unit/test_gate3_hardening.py \
  -q
```

## 8. Phase 5：前端评分展示与 i18n

Owner：Antigravity

触发条件：

- Phase 4 新增 `hard_gates.*.policy` 字段，或
- accuracy / evidence / evidence_coverage 的用户可见 detail 需要本地化展示。

Antigravity 负责：

- `viewer/src/api/schemas.ts`
  - 扩展 `scoreHardGateSchema`，接受可选 `policy`。
  - 保持 `.strict()`，不要用 `.passthrough()` 放宽整个 payload。
- `viewer/src/api/types.ts`
  - 增加显式 TypeScript 类型。
  - 禁止 `any`。
- `viewer/src/utils/hard-gates.ts`
  - 用 `policy` 生成本地化文案。
  - 不再只对 `evidence_coverage` 特判。
- `viewer/src/components/ScoreBreakdown.tsx`
  - 展示 adaptive regime、ratio、basis。
  - N/A 维度显示为 “N/A”，不要显示成红色 `0.0/0`。
  - passed gate detail 不得因为低 opacity 或浅色 token 触发 contrast failure。
  - Score panel 的 heading 层级必须与 Run Detail 页面结构一致，不能让备注标题跳级。
- `viewer/src/components/JudgeReport.tsx`
  - LLM judge 中 `max_score = 0` 的维度显示为 N/A。
  - 保留 advisory note，避免用户误解 judge 高分等于通过。
  - 使用 `DIMENSION_ORDER` 渲染八维顺序，避免 judge JSON insertion order 与 score tab 不一致。
  - Judge panel 的 heading 层级必须通过 axe。
- `viewer/src/i18n/messages/en.json`
- `viewer/src/i18n/messages/zh-CN.json`
  - 中英文 key 必须完全对齐。
- `viewer/src/components/ScoreBreakdown.css` / `viewer/src/components/JudgeReport.css`
  - 修复 Run Detail score / judge tab 的 contrast 和 mobile wrapping。
  - 禁止用仅靠 opacity 降低重要 gate detail 的可读性。
- `viewer/tests/e2e/a11y.spec.ts`
  - 增加 Run Detail score tab 和 judge tab axe 覆盖。
- `viewer/tests/e2e/cross-browser.spec.ts` 或 `viewer/tests/e2e/run-detail.spec.ts`
  - 增加 console error / warning 检查，特别是 Firefox 下 CSP 阻止 runtime eval 的噪声。

前端测试：

- `viewer/tests/unit/i18n-parity.test.ts`
- `viewer/src/api/__tests__/*schema*.test.ts`
- `viewer/src/components` 或 `viewer/src/pages` 相关 Vitest：
  - hard gate policy 被解析。
  - zh-CN / English 都显示 localized adaptive detail。
  - no-spec `spec_alignment` 显示 N/A。
  - judge tab 的 `spec_alignment` N/A 不误导为失败。
- `viewer/tests/e2e/run-detail.spec.ts`
  - score tab 显示 localized adaptive gate。
  - judge tab 显示 advisory + N/A。
  - 目标 run 形态不会出现文本重叠。
- `viewer/tests/e2e/a11y.spec.ts`
  - Run Detail score tab 无 `color-contrast` serious violation。
  - Run Detail score / judge tab 无 heading-order regression。
- Cross-browser console check：
  - Chromium / Firefox / WebKit 访问 Run Detail score / judge tab 时不能有产品错误。
  - 如果仍存在 `Content Security Policy ... eval`，必须先判断来源；若来自 Zod/依赖 runtime eval，需要选择 jitless 替代、构建配置修复，或记录明确安全取舍后请求用户确认。

Gate：

```bash
pnpm --dir viewer run typecheck
pnpm --dir viewer exec vitest run
pnpm --dir viewer run build
AHADIFF_VIEWER_E2E_PORT=5174 pnpm --dir viewer exec playwright test viewer/tests/e2e/run-detail.spec.ts --reporter=line
AHADIFF_VIEWER_E2E_PORT=5174 pnpm --dir viewer exec playwright test viewer/tests/e2e/a11y.spec.ts --reporter=line
```

跨浏览器 gate：

```bash
AHADIFF_VIEWER_E2E_PORT=5174 pnpm --dir viewer exec playwright test --reporter=line
```

如果全量 Playwright 出现单点 flake：

- 记录失败 browser / viewport / test。
- 目标复跑同一 project。
- 只有目标复跑通过时，才能标记为 flake；不能写成完整 matrix 全绿。

## 9. Phase 6：集成验证与真实 run 复算

Owner：Claude 编排；Codex + Antigravity 分别执行各自范围。

后端完整 gate：

```bash
UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run pytest tests/unit -q
UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run pytest tests/integration -q
UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run pytest tests/eval -q
UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run ruff check src tests
UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run ruff format --check src tests
UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run pyright
```

前端完整 gate：

```bash
pnpm --dir viewer run typecheck
pnpm --dir viewer exec vitest run
pnpm --dir viewer run build
AHADIFF_VIEWER_E2E_PORT=5174 pnpm --dir viewer exec playwright test --reporter=line
```

i18n gate：

```bash
pnpm --dir viewer exec vitest run viewer/tests/unit/i18n-parity.test.ts
UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run pytest tests/unit/test_i18n_resolver.py -q
```

真实 run 复算：

旧 persisted artifact 检查可以直接读 `claims.jsonl`，但它只反映当时已经写入的旧 verifier 结果，不会自动变成新分数。要验证本计划的修复效果，必须在临时目录复制 run，从 `claims.raw.jsonl` 重新 verify，再 evaluate 临时 run，避免污染 `.ahadiff/runs/`。

```bash
UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run python - <<'PY'
from pathlib import Path
from ahadiff.eval.evaluator import evaluate_run

run_path = Path('.ahadiff/runs/run_019e5596a965d091cd8fb6b4430ca29e')
report = evaluate_run(run_path)
print(report.verdict, report.overall, report.hard_gates.failed_names())
for dim in report.dimensions:
    print(dim.name, dim.score, dim.max_score, dim.reason)
PY
```

本轮收口使用的是临时目录 reverify 口径；结果为 `PASS 85.54`，failed gates 为空。原目录中的旧 `claims.jsonl` 没有被改写。

浏览器实测：

- 打开 `http://127.0.0.1:8765/#/run/run_019e5596a965d091cd8fb6b4430ca29e?tab=score`。
- 打开 `http://127.0.0.1:8765/#/run/run_019e5596a965d091cd8fb6b4430ca29e?tab=judge`。
- 检查：
  - Score tab 中 hard gate 原因可解释。
  - Judge tab 中 advisory 和 N/A 语义清楚。
  - Score / Judge tab 的 heading order 和 color contrast 通过 axe。
  - zh-CN / English 切换后无 key 泄漏。
  - desktop / mobile 无重叠。
  - console 无产品错误；Firefox 不应再出现未解释的 CSP eval issue。

跨平台：

- macOS：本机执行上述 gate。
- Linux：至少执行 unit/eval + viewer build，优先复用现有 Docker smoke 入口。
- Windows：必须有真实 Windows runner 或明确标记“未验证”。不能用 macOS 本机推断 Windows 通过。

Git hygiene：

```bash
git diff --check HEAD
git status --short
```

## 10. 阶段交叉审查模板

每个 phase 的 Claude 编排记录必须包含：

```markdown
## Phase N Evidence

- Owner: Codex / Antigravity
- Files changed:
- Commands run:
- Browser evidence:
- i18n evidence:
- Cross-platform evidence:
- Codex review:
- Codex adversarial review:
- Remaining Warning / Info:
- Decision: GO / NO-GO
```

Codex 对抗式审查 prompt 模板：

```text
/codex:adversarial-review --background "
Review Phase N of Eval Scoring Enhancement in /Users/yangjunjie/Desktop/ahadiff.
Use current code and tests only. Do not invent findings.
Focus on correctness, security, cross-platform behavior, i18n, browser/API contract,
and whether failed hard gates can still be accepted.
Use Codex sub-agents/multi-agents where safe.
Report Critical/High with exact file:line evidence and required tests.
"
```

Codex 修复 prompt 模板：

```text
/codex:rescue --background "
Implement Phase N of docs/EVAL_SCORING_ENHANCEMENT_PLAN.md.
Use the default Codex model via codex-plugin-cc; do not set --model or --effort.
Use sub-agents/multi-agents where write scopes are independent; serialize same-file edits.
Run the phase gate commands and report exact results.
"
```

## 11. 成功判据

必须同时满足：

- 当前 no-spec run 仍显示 `spec_alignment` 为 N/A / `0 max_score`，且不参与 overall。
- LLM judge 高分仍只是 advisory。
- failed hard gates 或 `verdict != "PASS"` 永远不能成为 learn ratchet `baseline` / `keep`。
- 当前 create lesson learn 的宽范围 multi-hunk claims 不再被无差别打成 9 条 rejected。
- accuracy / evidence gate 放宽有结构化 policy、可审计、可本地化。
- `line_outside_hunk` 的 mode-only、side mismatch、line outside file 等无效 evidence 仍会失败。
- `score.json` API payload 通过前端 strict schema。
- Run Detail score / judge tab 通过 axe contrast 和 heading-order 检查。
- zh-CN / English 文案对齐。
- Chromium / Firefox / WebKit 无未解释 console error；Firefox CSP eval issue 必须被修复或作为显式安全取舍记录。
- Chromium / Firefox / WebKit 至少 run-detail 相关场景通过；完整 matrix 失败必须有目标复跑证据。
- macOS / Linux 已验证；Windows 未跑时必须明示，不得写成全平台已通过。

## 12. 不做事项

- 不修改 `RUBRIC_WEIGHTS` 的 8 维权重。
- 不把 `spec_alignment` 无 spec 情况改成 `10/10` 或参与总分。
- 不让 `judge.json` 覆盖 deterministic `score.json`。
- 不把所有 `rejected + line_outside_hunk + low` 直接排除出分母。
- 不把前端 schema 改成宽松 passthrough。
- 不自动更新 llmdoc / 项目总文档；如需同步，最后单独选择：`使用 recorder agent 更新项目文档`。
