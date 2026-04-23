# Task 8 Claims Pipeline — 双轮交叉审查报告

> 日期: 2026-04-23
> 审查模型: Claude Opus 4.6 + Codex CLI (codex-plugin-cc)
> 审查轮次: 2 轮（R1 五代理并行 + R2 双路验证）
> Verdict: **CONDITIONAL GO**

---

## 一、审查范围

```
 M src/ahadiff/cli.py                      (+85 lines)
?? src/ahadiff/claims/                      (new module)
?? prompts/claim_extract.md                 (new prompt)
?? tests/unit/test_claim_verify.py          (new test)
?? tests/unit/test_negative_scan.py         (new test)
?? tests/unit/test_claim_classify.py        (new test)
?? tests/unit/test_claim_extract.py         (new test)
```

依赖检查范围: `contracts/`, `git/`, `llm/`, `core/`, `tests/unit/` 既有回归

---

## 二、审查方法

### 第一轮 (R1) — 五代理并行

| 代理 | 类型 | 职责 | 耗时 |
|------|------|------|------|
| claude-primary-review | Explore | 8 维度全量代码审查 | ~150s |
| test-runner | General | Task 8 测试 → 静态检查 → 全量套件 → 回归 | ~64s |
| codex-adversarial | Codex Rescue | 对抗性 corner case 攻击 | ~966s |
| codex-regular | Codex Rescue | 常规正确性/结构/回归审查 | ~1024s |
| smoke-tester | General | 真实本地 LLM 端到端冒烟测试 | ~409s |

### 第二轮 (R2) — 双路验证

| 代理 | 类型 | 职责 | 耗时 |
|------|------|------|------|
| claude-round2-verify | Explore | 逐一验证 R1 findings 是否误报 + 检查漏报 | ~113s |
| codex-adversarial-r2 | Codex CLI | 挑战设计选择和假设 | ~bg |

---

## 三、测试执行结果

| 类别 | 命令 | 结果 | 方式 |
|------|------|------|------|
| Task 8 专项 | `pytest test_claim_{verify,classify,extract} test_negative_scan` | **16 passed** | macOS 实测 |
| ruff check | `ruff check src tests` | **All passed** | macOS 实测 |
| ruff format | `ruff format --check src tests` | **All passed** | macOS 实测 |
| pyright | `pyright` | **0 errors, 0 warnings** | macOS 实测 |
| 全量套件 | `pytest tests/unit -q` | **214 passed, 0 failed** | macOS 实测 |
| Stage 0+1 回归 | `test_contracts + test_stage1_task1` | **42 passed** | macOS 实测 |
| Task 2 安全 | `test_redact + test_injection + test_path_safety + test_allowlist` | **35 passed** | macOS 实测 |
| Provider | `test_probe + test_provider` | **43 passed** | macOS 实测 |
| Diff 结构化 | `test_git_capture + test_diff_parser + test_hunk_hash + test_line_map + test_symbol_extract` | **78 passed** | macOS 实测 |
| Provider probe | `ahadiff provider test` on 8318 | **PASS** (openai, 1M ctx) | macOS 实测 |
| LLM extraction | `generate()` + `claim_extract.md` | **PASS** (2 claims) | macOS 实测 |
| Deterministic verify | `verify_claim_candidates()` | **PASS** | macOS 实测 |
| claims.jsonl 落盘 | run 目录检查 | **PASS** | macOS 实测 |

**回归**: 198 prior tests 全通过，0 regressions。

---

## 四、最终 Findings（去重合并、双轮校准后）

### HIGH (3)

#### H1: 零证据 claim 默认为 `"verified"` — classify.py:36-38

**确认源**: Claude R1+R2, Codex-Adv R1+R2, Codex-Reg R1 (全票)

```python
# classify.py:36-38
if matched_symbols:
    return "verified"
return "verified"  # ← zero evidence also returns "verified"
```

**复现路径**: claim 无 symbols + CLI 不传 before/after text → `unmatched_symbols=()`, `negative_evidence=()`, `matched_symbols=()` → line 38 fallthrough → `"verified"`

**影响**: 语义错误。`resolve_claim_confidence` 会返回 `"low"` 部分缓解，但 status 字段是 verified 仍具误导性。

**建议修复**: line 38 改为 `return "weak"` 或 `return "not_proven"`

---

#### H2: CLI `claims` 命令未传递 before/after text — cli.py:554-558

**确认源**: Claude R1+R2, Codex-Adv R1+R2, Codex-Reg R1 (全票)

```python
# cli.py:554-558
verified = verify_claim_candidates(
    candidates,
    line_maps=line_maps,
    symbols=symbols,
    # before_text_by_path 和 after_text_by_path 未传递
)
```

**影响**: `negative_scan.py` 中 `missing_retry_structure` / `missing_test_structure` / `missing_import_structure` / `missing_security_structure` 四个结构检测在 CLI 路径完全失效。`_resolve_text_for_path` 对空 dict 总返回 None。

**根因**: `capture.py` 的 `write_input_artifacts()` 不持久化 before/after text maps 为独立 artifact。CLI 无法从 run 目录重建这些数据。

**建议修复**: 持久化 redacted before/after text，或文档化为 deferred + CLI 输出 warning。

---

#### H3: `ClaimRecord.extractor` 字段永远为 null — verify.py:46-56,98-112

**确认源**: Claude R1+R2 (Codex 双轮均遗漏)

所有三处 `ClaimRecord` 构造（lines 46-55, 63-73, 99-108）均未填充 `extractor` 字段。`claim_status.py:83` 定义为 `ClaimExtractor | None = None`（可选），但 `contract-freeze.md` 将其列为最小必填字段。

**影响**: 契约违规。下游消费者无法知道 claim 的提取方式。

**建议修复**: 从 `SymbolRecord.extractor` 或 extraction context 传递。

---

### MEDIUM (6)

#### M1: 无界 hunk span 可导致 OOM — verify.py:160-162

**确认源**: Codex R2 新发现

```python
required_lines = set(range(source_hunk.start, source_hunk.end + 1))
```

`SourceHunk` 仅校验 `end >= start`。恶意或错误的 LLM 输出 `(start=1, end=999_999_999)` 可分配 ~8GB set。

**建议修复**: 在 `SourceHunk` 或 `_match_source_hunks` 入口加 span 上限守卫（如 10000 行）。

---

#### M2: fuzzy basename 匹配可绑同名异 scope symbol — verify.py:216-225

**确认源**: Codex-Adv R1(HIGH) → Claude R2 降为 MEDIUM

`rsplit(".", 1)[-1]` 匹配 basename。`Foo.bar` 和 `Baz.bar` 均可命中 claim "bar"。`_pick_best_symbol` 按 confidence/hunk 数排序，非语义消歧。

**缓解**: lines 202-208 的 scope filtering（限定 source_hunk paths + matched hunk_ids）显著缩小候选池，实际碰撞概率低。

---

#### M3: rename-only diff 的 claim 总被拒 — verify.py:160-174

**确认源**: Codex-Adv R1 + Claude R2

纯 rename 无内容变更 → `FileLineMap.hunks` 为空 → `_match_source_hunks` 找不到匹配 hunk → `line_outside_hunk` 拒绝。设计选择而非 bug，但应文档化。

---

#### M4: `missing_test_structure` 未归入硬负面信号 — classify.py:21-31

**确认源**: Claude R1 + Codex-Reg R1

`missing_retry_structure` / `missing_import_structure` / `missing_security_structure` 均为硬信号（→ contradicted），但 `missing_test_structure` 缺失，只能走 line 34 → weak。不一致。

---

#### M5: artifact loader 不校验 `schema_version` — extract.py:84-87

**确认源**: Codex-Reg R1 + Claude R2

`load_line_map_records()` 和 `load_symbol_records()` 只校验 schema name，不校验 version。当前只有 version 1，无即时风险，但版本演进时会静默接受不兼容数据。

---

#### M6: CLAUDE.md 未更新 — 文档漂移

**确认源**: Claude R1

`claims/` 模块和 `ahadiff claims` CLI 命令未在 CLAUDE.md 模块索引、运行验证、当前阶段描述中记录。

---

### LOW (7)

| # | 描述 | 来源 |
|---|------|------|
| L1 | `RejectReasonCode.symbol_not_found` / `evidence_missing` 无生产路径（死枚举值，无运行时害） | R1 HIGH → R2 降为 LOW |
| L2 | `claims.jsonl` 不在 `artifact_set.json`（by design，artifact_set 是 input-only manifest） | R1 MEDIUM → R2 降为 LOW |
| L3 | CLI `run_id` 与 claim 内嵌 `run_id` 可不匹配（`setdefault` 只填缺失值） | Claude R2 新发现 |
| L4 | Ctrl+C 期间 `write_text()` 可留半写 claims.jsonl（非原子写入） | Claude R2 新发现 |
| L5 | Duplicate `claim_id` 未校验去重 | Claude R2 新发现 |
| L6 | `_normalize_symbol_name` verify.py vs symbols.py 语义不同（前者更激进） | Claude R1 |
| L7 | `_hunk_line_numbers` 合并 old/new 行号，理论上 old-side 行号可满足 new-side 引用 | Claude R1 |

---

## 五、误报/漏报核查

### 第一轮误报（R2 纠正）

| 原始 Finding | R1 级别 | R2 裁定 | 原因 |
|-------------|---------|---------|------|
| 死 enum 值 (symbol_not_found/evidence_missing) | HIGH | **→ LOW** | 死 Literal 变体无运行时伤害，保留为前向兼容合理 |
| fuzzy scope 错绑 | HIGH | **→ MEDIUM** | lines 202-208 scope filtering 显著缩小候选池 |
| claims.jsonl 不在 artifact_set | MEDIUM | **→ LOW** | artifact_set.json 是 input-only manifest，by design |
| confidence KeyError (Codex-Adv R1) | HIGH | **→ LOW** | `SymbolRecord.confidence` 有 `Literal["high","medium","low"]` 类型约束 |

### 第一轮漏报（R2 补全）

| 新 Finding | 级别 | 发现者 |
|-----------|------|--------|
| 无界 hunk span OOM (M1) | MEDIUM | Codex R2 |
| run_id 不匹配 (L3) | LOW | Claude R2 |
| Ctrl+C 半写 (L4) | LOW | Claude R2 |
| Duplicate claim_id (L5) | LOW | Claude R2 |

### Codex 双轮均遗漏

| Finding | 级别 | 说明 |
|---------|------|------|
| extractor 未填充 (H3) | HIGH | 仅 Claude 两轮发现。Codex 两轮均未标记此契约违规。 |

---

## 六、跨平台结论

| 平台 | 方式 | 结论 |
|------|------|------|
| **macOS** | **实际执行** | 214 tests pass, smoke 全通过，无平台特定问题 |
| **Windows** | **静态推断** | NFC+casefold+utf-8 ✓; portalocker ✓; `write_text("\n")` text mode 下 `\n` → `\r\n`（JSONL 消费端需能处理 `\r\n`） |
| **Linux** | **静态推断** | case-sensitive 文件系统 + `casefold` 在 `path_identity_key` 中可造成 false collision（`File.py` 和 `file.py` 映射到同一 key），已知设计权衡 |

---

## 七、Verdict

### CONDITIONAL GO

| 维度 | 计数 |
|------|------|
| CRITICAL | 0 |
| HIGH | 3 |
| MEDIUM | 6 |
| LOW | 7 |
| 测试通过 | 214/214 |
| 回归 | 0 |
| 静态检查 | 全绿 |

### 必修项（Stage Gate 前）

1. **H1** `classify.py:38` — 零证据 fallback 改为 `"weak"`
2. **H2** `cli.py:554-558` — 接入 before/after text 或文档化 deferred + warning
3. **H3** `verify.py` — 所有 `ClaimRecord` 构造补 `extractor` 字段

### 建议修项（Stage Gate 前优先）

4. **M1** `verify.py:160` — span 上限守卫防 OOM
5. **M4** `classify.py:21-31` — `missing_test_structure` 归入硬负面信号集
6. **M6** CLAUDE.md 更新

### 可延后项

- M2 (fuzzy scope), M3 (rename-only), M5 (schema_version)
- L1-L7 均可延后
