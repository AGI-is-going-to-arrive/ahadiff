# AhaDiff v0.1 开发计划 — 第 4-9 段 Task 拆分

> 生成时间：2026-04-20（第四轮终审更新：2026-04-21）
> 基于：ahadiff-v01-revision.md + Codex 技术审查 + Gemini 前端评审
> 依赖：Layer 1-3（Task 1-8）全部完成
> **阶段门禁**：每个 Stage 完成后必须通过 Codex+Claude 交叉审查（含前端的 Stage 加 Gemini），详见 CLAUDE.md "阶段门禁" 章节

---

## 段落顺序说明

采用 Codex 建议的调整顺序（与原方案第五/六/七/八段重排）：

```
原顺序                    新顺序（Codex 建议）
第四段 lesson + quiz      → 第四段 lesson + quiz（不变）
第五段 Warm HTML viewer   → 第五段 score + verifier hard gates + results.tsv
第六段 score + verifier   → 第六段 React Viewer
第七段 review + learning  → 第七段 review + learning signal
第八段 improve loop       → 第八段 improve loop + targeted verification + Phase 2.5
第九段 agent install      → 第九段 agent & automation install（扩展为 6 工具 + hooks + Action）
```

理由：score/evaluator 是 improve loop 的前置依赖，必须在 viewer 之前就绪；viewer 需要 score.json 来驱动 Rubric 展示。

## 与 CLAUDE.md Stage 的对应关系

- **第四段 + 第五段**（Task 8.5-12）对应 `CLAUDE.md` 的 **Stage 3**
- **第六段 Task 13/14 + 第七段 Task 15** 对应 **Stage 4**
- **第六段 Task 14.5 + 第八段 Task 16/17** 对应 **Stage 5**
- **第八段 Task 18 + 第九段 Task 19/20** 对应 **Stage 6**
- **第十段 i18n-0~6** 是跨 Stage 3-6 的 overlay，不是新的独立 Stage；最终只在 `CLAUDE.md` 的 **Stage 7** 做 parity/signoff gate
- **Graphify 边界**：Graphify 的 backend / CLI / detect / import / sanitize / freshness 以及对应 backend tests 归前半段 `Stage 2`（Task 5/6 及相关测试）处理；本文只承接 Viewer 和 Serve 数据契约侧的回流

---

## 第四段：lesson + quiz

### Task 8.5: Learnability Gate（Task 9 前置）

> **来源**：Gemini R8 D15 + D17 发现。琐碎提交（typo/formatting/deps bump）全量生成 lesson+quiz 会造成认知疲劳和 SRS 题库爆炸。

- **类型**: 后端（Codex 实现）
- **文件范围**:
  - `src/ahadiff/lesson/learnability.py`
  - `tests/unit/test_learnability.py`
- **依赖**: Task 6（ParsedDiff）+ Task 8（Claim 提取）
- **实施步骤**:
  1. 在 `ahadiff learn` 的 capture→parse 之后、lesson 生成之前，增加 **learnability scoring** 前置判定
  2. 实现 `compute_learnability_score()`，输出 0.0-1.0 浮点数
  3. 默认权重为 `complexity=0.4 / novelty=0.3 / pattern=0.3`，**说明为 heuristic defaults**，非科学结论；在首批 50 份 pinned diff benchmark 后可重新校准
  4. 默认阈值 `LEARNABILITY_THRESHOLD = 0.3`，支持 `config.toml [learn].learnability_threshold` 覆盖
  5. score ≥ 阈值：正常生成 lesson + quiz；score < 阈值：默认跳过 lesson/quiz，CLI 输出低学习价值提示，`--force-learn` 可覆盖
  6. learnability_score 与 skip 决策写入 `metadata.json`；当 run 后续进入评分写库时，learnability metadata 一并写入 `result_events.note_json`
- **设计**：

```python
# src/ahadiff/lesson/learnability.py
def compute_learnability_score(parsed_diff: ParsedDiff) -> float:
    """基于三因子评分，0.0-1.0。低于阈值跳过 lesson/quiz 生成。"""
    factors = {
        "complexity": _diff_complexity(parsed_diff),     # 变更复杂度（非空行数/函数级变更/跨文件引用）
        "novelty": _file_type_novelty(parsed_diff),      # 文件类型新颖度（.py/.ts=高, .lock/.json=低）
        "pattern": _change_pattern(parsed_diff),          # 变更模式（新增逻辑=高, 纯格式化=低, deps bump=低）
    }
    return weighted_average(factors, weights={"complexity": 0.4, "novelty": 0.3, "pattern": 0.3})

LEARNABILITY_THRESHOLD = 0.3  # config.toml [learn].learnability_threshold 可覆盖
```

**低学习价值变更的典型模式**：
- 纯 whitespace/formatting 变更
- package-lock.json / yarn.lock / go.sum 等依赖锁文件
- 自动生成的文件（.pb.go / .d.ts / migration 文件）
- 单行 typo 修正
- 版本号 bump（pyproject.toml version 字段变更）

- **验收标准**: `pytest tests/unit/test_learnability.py` 通过；`ahadiff learn` 在 typo/lockfile diff 上默认跳过 lesson/quiz；`--force-learn` 能覆盖跳过逻辑

### Task 9: Lesson 生成（三段式撤架）

- **类型**: 后端（Codex 实现）
- **文件范围**:
  - `src/ahadiff/lesson/generator.py`
  - `src/ahadiff/lesson/scaffolding.py`
  - `src/ahadiff/lesson/schemas.py`
  - `prompts/lesson_generate.md`
  - `prompts/lesson_hint.md`
  - `prompts/lesson_compact.md`
  - `tests/unit/test_lesson_generator.py`
- **依赖**: Task 7（LLM Provider）+ Task 8（Claim 提取）+ Task 8.5（Learnability Gate）。**输入约束**：Task 9 只能消费由 Task 5/Task 2 capture→redaction 链路产出的 `RedactedDiff` / 脱敏后 parsed diff DTO，不得接受 raw patch 或 raw file-compare 文本
- **实施步骤**:
  1. 定义 Pydantic schema：`LessonFull`, `LessonHint`, `LessonCompact`
  2. 编写 `lesson_generate.md` prompt（遵循 §11 lesson 设计规范）
  3. 实现 `generate_lesson()` → 生成 `lesson.full.md`（完整解释）。`generate_lesson()` 的类型签名只接受 `RedactedDiff`（或等价的已脱敏 parsed diff DTO），不允许旁路接入原始 patch 文本
  4. 实现 `generate_hint()` → 生成 `lesson.hint.md`（关键提示）
  5. 实现 `generate_compact()` → 生成 `lesson.compact.md`（<500 token 概念卡）
  6. 实现 `not_proven.md` 和 `misconception.md` 分离输出
  7. 每篇 lesson 必须包含 TL;DR / What Changed / Why / Walkthrough / Claims / Concepts / Misconceptions / Not Proven / Quiz / Sources
  8. **三段式撤架触发条件**（与 FSRS 契约统一）：
     - **自动默认层级**：`ahadiff review` 展示 lesson 时，必须复用 `compute_scaffolding_level()` 的统一规则：`full = Learning/Relearning 或 stability < 3d`，`hint = Review 且 3d <= stability < 14d`，`compact = stability >= 14d 且最近 2 次成功回忆`
     - **手动切换**：UI 提供 Full/Hint/Compact 三个标签页，用户可随时手动切换（不受自动默认层级约束）
     - **Quiz/Review 反馈路径**：答题表现通过本轮 `rating`、`misconception` 卡生成和 `peek_guard` 进入 FSRS 状态机；**禁止**再单独定义 “答错率 > 50% 直接回退一级” 这类旁路 heuristic
     - `ReviewCard.scaffolding_level` 记录的是**当前由 FSRS state 推导出的 UI 展示层级**，影响下次默认展开层，但**不直接修改 FSRS optimizer 输入**
- **验收标准**: `ahadiff learn HEAD~1..HEAD` 生成 `runs/<run_id>/lesson/` 下的 full/hint/compact 三个文件；`ahadiff review` 根据 FSRS state/stability 自动选择默认展示版本

### Task 10: Quiz 生成 + SRS 卡片

- **类型**: 后端（Codex 实现）
- **文件范围**:
  - `src/ahadiff/quiz/generator.py`
  - `src/ahadiff/quiz/schemas.py`
  - `src/ahadiff/quiz/cards.py`
  - `src/ahadiff/wiki/concepts.py`
  - `prompts/quiz_generate.md`
  - `tests/unit/test_quiz_generator.py`
  - `tests/unit/test_concepts.py`
- **依赖**: Task 9（Lesson）+ Task 8（Claim）
- **实施步骤**:
  1. 定义 `QuizQuestion`, `QuizSet`, `ReviewCard` schema。ReviewCard 必须包含 anchor 元数据：`source_ref`、`file_id`（稳定标识，与 EvidenceAnchor 统一）、`display_path`（用户可见路径）、`hunk_id`、`hunk_hash`、`symbol`、`change_kind`。**注意**：`path` 字段已废弃，统一使用 `file_id + display_path` 二元组（与 CC-NEW-3 闭合方案一致）。**FSRS 字段（Codex R8 交叉审查修复）**：ReviewCard 必须包含 `fsrs_state: str`（FSRS Card JSON 序列化）、`scaffolding_level: Literal["full", "hint", "compact"] = "full"`、`last_rating: int | None = None`（1-4 对应 Again/Hard/Good/Easy）、`card_state: Literal["active", "stale", "archived", "suspended"] = "active"`、`peeked_this_session: bool = False`（session-local，切下一张卡时重置）。**持久化边界冻结**：`scheduler_preset_id`、`desired_retention`、`last_review_utc` 属于 `review.sqlite.cards` 的 persisted-only 字段，不写入生成态 `cards.jsonl`；Task 15 在首次入库时注入默认 preset/retention，并在第一次 review 后写入 `last_review_utc`。**删除 SM-2 字段**：不再使用 `ease_factor`/`interval`/`reps`
  2. 编写 `quiz_generate.md` prompt
  3. 实现 `generate_quiz()` → `quiz.jsonl`（每题含 source_claims / concepts / file:line evidence）
  4. 实现 `generate_cards()` → `cards.jsonl`（SRS 复习卡，每张 <500 token）。**触发点冻结**：仅 `PASS` 和 `CAUTION` runs 生成 cards；`FAIL` runs 不生成 cards。若一个已生成 cards 的 run 后续在 ratchet 中变为 `discard`，其 cards 统一转为 `stale` 并移出正常 due 队列，discard provenance 继续记录在 `result_events/note_json`，不为 v0.1 额外扩张新的 `StaleReason` 枚举
  5. 实现 `ahadiff quiz <run_id>` CLI 子命令（交互式答题）
  6. **Quiz staleness 惰性检测**（Anki 无此能力，AhaDiff 创新点）：`CardState = active | stale | archived | suspended`。当 `ahadiff review` 或 `ahadiff quiz` 取卡时，用当前 HEAD 重新解析 card 的 anchor（`file_id` → 反查当前路径 + hunk_hash + symbol）。解析失败 → 标记 `stale` + `stale_reason`（file_deleted/symbol_removed/line_drifted），移出正常 due 队列，CLI 提示 `ahadiff regenerate --only quiz <run_id>`、`ahadiff card archive <card_id>` 或 `ahadiff card suspend <card_id>`。`archived` 表示永久退役，`suspended` 表示用户因题目质量/当前无学习价值而临时移出 due 队列。rename/move 场景优先用 symbol 判定，path 失效但 symbol 仍可解析时不单独引入新 `stale_reason`，直接按可继续使用处理。非 git 输入（`patch_file`/`patch_stdin`/`file_compare`）标记 `staleness_unknown`，不误报
  7. **concepts.jsonl 实现**（~120-180 行）：实现 `src/ahadiff/wiki/concepts.py`，包含 `append_concepts(run_id, concepts_list)`、`load_visible_concepts(head_ref)` 函数。存储为 repo 级 `.ahadiff/concepts.jsonl` 的 **JSONL upsert ledger**：文件格式保持 JSONL，但**逻辑模型冻结为每个 `term_key` 恰好一行**，不允许重复 `term_key`。每条记录：`{concept, term_key, source_refs[], branch_hint, introduced_by_run, updated_by_runs[], related_claims[], file_refs[]}`。`append_concepts()` 写入时按 term_key 查找已有行：存在则原地更新该行字段（合并 `updated_by_runs`/`file_refs`，追加 `source_refs[]`）；不存在则追加新行。**读取时过滤**：`load_visible_concepts(head_ref)` 扫描所有行，检查 `source_refs[]` 中是否有**任一** ref 是当前 HEAD 的 ancestor（`any(is-ancestor)`），有则可见。**non-git 输入守卫**：当 `source_kind` 为 `patch_file`/`patch_stdin`/`file_compare` 时，`source_ref` 为内容 hash 而非 git commit，此时概念仅在 run-local 视图展示（写入 `runs/<run_id>/concepts_local.jsonl`），不进入全局 `concepts.jsonl`
  8. **concept 去重**（CC-NEW-5 闭合方案）：`compute_term_key()` 使用 NFKD + lowercase + strip + slug 归一化。`append_concepts()` 时按 term_key 检查已存在，存在则合并 `updated_by_runs`、`file_refs`，**并将当前 run 的 commit 追加到 `source_refs[]` 数组**（保留所有引入过该概念的 commit，确保任何分支上只要有一个 source_ref 可达即可见；解决 squash/cherry-pick 和多分支并行问题）
  9. **concepts.jsonl crash-atomicity**（Codex 审查发现）：upsert 操作采用 write-to-temp-then-rename 策略：(1) 读取现有 concepts.jsonl 到内存；(2) 执行 term_key 匹配/合并；(3) 写入完整内容到 `.ahadiff/concepts.jsonl.tmp`；(4) `os.replace()` 原子替换原文件。中断恢复：启动时检测 `.tmp` 残留 → 若 `.tmp` 大小 > 0 且合法 JSONL 则 replace 生效（完成中断的 rename），否则删除 `.tmp`（回退到原文件）。**并发保护**：`append_concepts()` 必须在 `repo_write_lock` 内调用；`ahadiff serve` 的读路径（`load_visible_concepts`）无需锁（读取原子性由 OS rename 保证）
- **验收标准**: `ahadiff quiz <run_id>` 能做题，每题可回链到 source_claims 和 file:line；stale card 不更新 ease/interval；`concepts.jsonl` 可正确追加/去重/按 branch 过滤可见概念

---

## 第五段：score + verifier hard gates + results.tsv

### Task 11: 评估体系（Evaluation Bundle — 整体 immutable）

- **类型**: 后端（Codex 实现）
- **文件范围**:
  - `src/ahadiff/eval/evaluator.py`（**evaluation bundle 成员，整体 IMMUTABLE**）
  - `src/ahadiff/eval/rubric.py`（**evaluation bundle 成员**）
  - `src/ahadiff/eval/gates.py`（**evaluation bundle 成员**）
  - `src/ahadiff/eval/deterministic.py`（**evaluation bundle 成员**）
  - `src/ahadiff/eval/rubric.yaml`（**evaluation bundle 成员**）
  - `tests/unit/test_evaluator.py`
  - `tests/unit/test_gates.py`
- **依赖**: Task 0（Schema Freeze）+ Task 7（LLM Provider）+ Task 8（Claim）
- **实施步骤**:
  1. 实现 8 维 rubric 评分（accuracy/evidence/diff_coverage/learnability/quiz_transfer/spec_alignment/conciseness/safety_privacy = 100 分）
  2. 实现硬门禁：Accuracy<14 FAIL, Evidence<12 FAIL, contradicted claims FAIL, secret leak FAIL, injection unresolved FAIL。**补充说明**：Evidence gate 取 12/18（67%）而不是 Accuracy 的 14/20（70%），是因为 evidence 维度含更高的 LLM-judge 波动；该不对称是有意设计，不是算错
  3. 实现 PASS(≥80) / CAUTION(60-79) / FAIL(<60) verdict 计算。**补充说明**：hard gates 只是必要条件，不是充分条件；即使 Accuracy/Evidence 恰好过线，总分仍可因其余维度过低而得到 FAIL
  4. 实现机械化打分（R10）：evidence 从 claims.jsonl 统计 verified/weak 比例；safety_privacy 从 redaction_report.json 统计
  5. 生成 `score.json`（8 维明细 + verdict + hard_gates + weakest_dim + `eval_bundle_version` + `degraded_flags`）
  6. 跨模型评估：生产环境生成与评估用不同模型；**开发测试阶段统一 gpt-5.4-mini**（跨模型约束暂时放松），生产环境生成切大模型
  7. **Evaluation bundle 整体 immutable**：`evaluator.py` + `rubric.py` + `rubric.yaml` + `gates.py` + `deterministic.py` 共 5 文件的联合 hash 为 `eval_bundle_version`。**路径口径冻结**：5 个成员统一位于 `src/ahadiff/eval/`，其中 rubric 的磁盘路径为 `src/ahadiff/eval/rubric.yaml`，逻辑 hash 标签使用 `eval/rubric.yaml`。任一文件变更视为新评估版本，自动产生新的 `eval_bundle_version`、自动触发 VCR cassette 失效，并在 results 中记录新版本号。`rubric_version` 仅保留为派生显示字段。v0.1 期间允许迭代但必须版本化
- **验收标准**: `ahadiff verify <run_id>` 和 `ahadiff score <run_id>` 输出 PASS/CAUTION/FAIL 及最弱维度；score.json 包含 eval_bundle_version

### Task 12: Ratchet 机制 + results 写入

- **类型**: 后端（Codex 实现）
- **文件范围**:
  - `src/ahadiff/eval/ratchet.py`
  - `src/ahadiff/eval/results.py`
  - `tests/unit/test_ratchet.py`
  - `tests/unit/test_results.py`
- **依赖**: Task 0（Schema Freeze — RunStatus/EventLog 契约）+ Task 11（评估体系）
- **实施步骤**:
  1. **写入顺序（按当前代码真值）**：lesson/score artifact 先写临时文件并校验 → SQLite `result_events` commit（有事务保护）→ 成对发布 `score.json` + `finalized.json`。**可见性冻结**：SQLite `result_events` 是评分/ratchet 的唯一真相源；Serve 的 run-scoped 读接口（`/api/runs`, `/api/run/:id/*`）只暴露已完成二阶段发布、目录内含 `finalized.json` 的 runs。Dashboard 聚合指标可以查 SQLite，但不得把未 finalized 的临时 run 直接暴露给前端。`results.tsv` 只是导出视图，可从 SQLite 重建；如果 `score.json` / `finalized.json` 发布失败，必须回滚刚写入的 event 并重建 `results.tsv`
  2. results.tsv 11 列 append-only（timestamp/run_id/source_ref/base_ref/prompt_version/rubric_version/overall/verdict/status/weakest_dim/note_json）。`source_ref` 为当前评估的来源标识（git 场景为 commit SHA，patch 场景为文件 hash，compare 场景为路径对 hash），`base_ref` 为 ratchet 比较的基线标识（首次 baseline 时为空）。Phase 2.5 rewrite 时 note_json 字段记录 `{"phase25": true, "worktree_path": "<path>"}`
  3. `result_events` 契约字段/索引以 Task 0 `contract-freeze.md` 为准；Task 12 只按该物理形状写入事件，不单独拥有 DDL。实际建表/索引落地统一归 Task 15 migration：主键为 `event_id`（UUID v7，全局唯一），唯一索引 `(run_id, event_type, timestamp)`，二级索引 `(source_ref, timestamp DESC)` + `(verdict, status)` + `(weakest_dim, timestamp DESC)`。同一 run_id 可有多行事件（如 keep → targeted_verify → keep_final）
  4. 实现 `append_result()` 的幂等保证：写入前检查 `event_id` 是否已存在，存在则跳过
  5. 提供 `ahadiff export-results` 从 review.sqlite 重建 results.tsv
  6. status 枚举化（从 Task 0 `contracts/event_log.py` 单点导入 `RunStatus`）：`baseline | keep | discard | crash | targeted_verify | keep_final | phase25_rewrite | non_ratcheted`。**`non_ratcheted` 判定条件**：`has_git_ancestry == false`（即无法通过 `git merge-base` 确认 baseline 关系）。Level 1/2 输入（patch/file_compare）虽然有 `source_ref`（content hash），但没有 git ancestry，因此无法 ratchet 回滚。写入时 status 直接标记为 `non_ratcheted`，不进入 keep/discard 决策。**注意区分**：`has_source_ref`（所有输入都有）≠ `has_git_ancestry`（仅 Level 3 git 输入有）
  7. 实现 ratchet 决策逻辑 + **improve 状态机统一定义**：
     - **learn 链路**（`ahadiff learn`，非 improve）：lesson 生成完成后再做 score 评估，并写入 `event_type=learn` + `status=baseline`（首次）或 `status=keep`（后续 ratchet 提升）/ `status=discard`（退步）。learn 不涉及 cherry-pick（直接在主分支上运行）
     - **improve 链路**（`ahadiff improve`，在 worktree 中）：
       (a) 评估通过（score 提升 + hard gate 全过）→ 先执行 `git cherry-pick` → 成功后写 `status=targeted_verify`（不是 `keep`）
       (b) cherry-pick 失败（冲突）→ 写 `status=targeted_verify` + `note_json={"cherry_pick_pending": true, "worktree_path": "..."}`，保留 worktree 供人工 resolve
       (c) 评估未通过 → 写 `status=discard`，删除 worktree
       (d) `ahadiff db finalize-targeted <event_id>` 全 8 维 recheck 通过 → 升级为 `status=keep_final`
     - **边界定义**：`keep` 仅出现在 learn 链路（直接 ratchet 判定）；manual `score` / `verify` 不参与 learn baseline 选择；`targeted_verify → keep_final` 仅出现在 improve 链路。两者不混用。Phase 2.5 最终结果也走 improve 链路：通过写 `targeted_verify`，不通过写 `discard`
     - **禁止**：先写 status 再 cherry-pick（避免状态与 git 不一致）
     - 降级 run（`degraded_flags` 非空）的 ratchet 比较需标记 `ratchet_note=degraded_comparison`，不直接丢弃；带 `degraded_flags` 的历史事件不参与 baseline 选择
  8. 实现 Phase 2.5 检测：连续 2 个优化目标在首轮即 discard → 触发 structural rewrite
  9. 简洁性准则：0.001 分提升 + 20 行 hacky prompt → 不值得
  10. 实现 repo_write_lock 检查（复用 Task 5 的 `.ahadiff/ahadiff.lock`，portalocker）：ratchet 写入前验证锁持有
- **验收标准**: review.sqlite result_events 正确写入，ratchet keep/discard/crash 三路径单测全绿；`ahadiff export-results` 重建的 TSV 与直接 append 的 TSV 一致

---

## 第六段：React Viewer

### Task 13: React Viewer 基础架构

- **类型**: 前端（Claude 实现）
- **文件范围**:
  - `viewer/` 目录（React + Vite 项目）
  - `viewer/package.json`
  - `viewer/vite.config.ts`
  - `viewer/src/App.tsx`
  - `viewer/src/components/` — 通用组件
  - `viewer/src/styles/` — CSS（vanilla CSS，不用 Tailwind）
  - `viewer/src/api/` — API client
  - `viewer/src/i18n/` — 国际化
- **依赖**: Task 0（Schema Freeze）；开发时 API 通过 mock/proxy 解耦（Vite dev server proxy），不硬依赖 Task 14.5。按 `CLAUDE.md` 的外层 gate，Task 14.5 归 `Stage 5`；这里的 Task 13 只在开发时通过 mock/proxy 提前并行
- **实施步骤**:
  1. 初始化 Vite + React 19 + TypeScript 项目
  2. 以根级 `AhaDiff Warm v6.html` 为设计参考模板，提取设计 token（颜色、字体、间距），并补齐 v6.2 polish layer 的语义 token：soft/tint/hairline/surface/ring/duration/easing；同时吸收当前 v6.x `editorial-terminal` overlay 中真正需要工程化的部分：字体 weight ramp、FOLIO / verified 印章 / serif page-head / tabular numerals / inkstone CTA 等视觉语言，但保持 additive-only，不把 ornament 当成结构依赖
  3. 实现 Warm 风格 CSS 设计系统（vanilla CSS custom properties + CSS Modules，不用 CSS 框架）
4. 实现基础 layout：sidebar nav + main content area + responsive breakpoints
5. 实现 API client：连接 `ahadiff serve` 的 REST API。**Graphify 口径统一**：Viewer 的图谱数据与其他 run 数据走同一套本地 API/data contract，不再单独保留旧静态 viewer 的 `file://` 获取路径。开发期 mock/proxy fixtures 必须从 Task 0 冻结 DTO 和 Task 11 的 score/result contract 生成，不允许手写漂移副本
5a. Graphify 进入 Viewer 的最小能力：存在导入产物时显示 repo-level context；不存在时不报错，并按 `full / learning_only / empty` 三态降级
6. **i18n 架构（Gemini 审查修正）**：使用 Zustand 原子 store 而非顶层 React Context。`useLocale()` hook 返回当前 locale，`useT()` hook 返回翻译函数。DiffView 等重渲染组件通过 `React.memo` + `useMemo(messages[key])` 隔离，语言切换时仅 re-render 含文案的轻组件（Nav/Sidebar/Footer），不触发 DiffView/EvidencePanel 重建
  7. 实现语言切换 UI + cookie 持久化 + 浏览器检测降级
  8. **防 FOUC 阻塞脚本（Gemini 审查新增）**：在 `index.html` `<head>` 中注入内联 `<script>`（非 defer/async），在 React bundle 加载前读取 `localStorage.getItem('ahadiff_lang')` 和 `localStorage.getItem('ahadiff_theme')` 并设置 `<html lang="..." data-theme="...">`。配合 CSS Variables 实现 0 闪烁。脚本体积 < 500 bytes
  8a. 补齐浏览器与移动端 meta：`viewport-fit=cover`、`theme-color`（light）、`color-scheme=light`、`format-detection=telephone=no`，保证安全区、状态栏和阅读体验稳定
  9. 实现 print CSS（@media print）。`break-inside: avoid` 仅作用于 `.claim-card` 和 `<table>` 等小块级元素，不作用于 `<article>` 或长 `<pre>`（避免大面积空白）；补 `widows/orphans` 控制，并在打印时为外链追加 URL 文本
  10. 实现 WCAG AA 无障碍：焦点管理、aria-label、键盘导航。`focus-visible` 使用高对比 ring；`forced-colors: active` 下保持结构可读，不依赖阴影和浅色边框
  11. 配置 Vite build：`ahadiff serve` 开发时 proxy API，生产时 serve 静态 build
  12. 实现 XSS 防护：所有用户数据渲染用 React 自动 escape，data_bundle 用 DOMPurify
  13. 字体策略：Google Fonts（Newsreader/Inter/JetBrains Mono/Noto Serif SC）+ 系统字体回退链
  14. **DiffView 渲染隔离（性能约束）**：DiffView 组件整体用 `React.memo(DiffView, shallowEqual)` 包裹，props 仅接收 `runId` + `highlightedClaimId`。内部使用虚拟列表（`@tanstack/react-virtual`）渲染 5000+ 行。i18n/theme 切换不传入 DiffView props，通过 CSS Variables + `data-lang` 属性处理静态文案。**虚拟列表 dynamic measuring（Gemini R8 H-3 修复）**：因 Claim 标注注入导致行高动态变化，必须开启 `@tanstack/react-virtual` 的 `measureElement` + `estimateSize` 动态测量模式，绑定 `ResizeObserver` 获取真实行高。禁止使用固定 `itemSize`，否则 Claim 展开时滚动条跳动
  14a. **Bottom Mini-Panel Scroll Chaining 修复（Gemini R8 H-4）**：Evidence 列表面板使用 `overscroll-behavior: contain` 防止滚动事件穿透到 Diff 区域。触控设备使用 `touch-action: pan-y` + gesture 库（`@use-gesture/react` 或 `framer-motion`）严格接管触控事件传播边界，防止面板上滑手势与内部列表滚动冲突
  14b. 页面级增加 `scrollbar-gutter: stable` 与 `overscroll-behavior-y: none`，减少滚动条抖动和移动端回弹穿透；coarse pointer 下核心交互元素（button/tab/chip/claim actions）最小高度 44px
  14c. 对依赖 blur 的浮层补 `prefers-reduced-transparency: reduce` 降级，回退到纯色背景，不影响信息层级
  15. `<noscript>` 提示：JS 禁用时显示 "AhaDiff requires JavaScript" 友好提示
- **验收标准**: 
  - `cd viewer && npm run build` 成功
  - `cd viewer && npm run build` 成功；开发态通过 Vite dev server + mock/proxy 能显示 Warm 风格首页
  - WCAG AA 合规（axe-core 零 critical）
  - 中英文切换无闪烁、无 FOUC（清空缓存后首次加载验证）
  - DiffView 5000 行渲染 FCP < 500ms（Playwright trace + 固定 fixture 验证）
  - 语言切换时 DiffView render-count 增量 ≤1，commit-count 增量 ≤1（测试态 `window.__AHADIFF_DEBUG__.diffViewRenderCount` + Playwright 断言）
  - iPhone 安全区下顶部/底部不被裁切；触控设备关键交互目标高度 ≥44px
  - `forced-colors` / `prefers-reduced-transparency` / print 模式下页面结构仍可读，打印版外链可见 URL

### Task 14: Viewer 核心页面（v0.1 必须的 4 页）

- **类型**: 前端（Claude 实现，Gemini 评审）
- **文件范围**:
  - `viewer/src/pages/LessonPage.tsx` — Lesson 全文 + Evidence 侧边栏
  - `viewer/src/pages/DiffViewerPage.tsx` — Diff + Claim 标注
  - `viewer/src/pages/QuizPage.tsx` — Quiz 交互（Guided/Recall/Transfer）
  - `viewer/src/pages/DashboardPage.tsx` — 历史 + Ratchet 趋势图
  - `viewer/src/components/ClaimBadge.tsx` — 5 态 Claim 状态标签
  - `viewer/src/components/EvidencePanel.tsx` — file:line 证据链
  - `viewer/src/components/SRSCard.tsx` — SRS 翻牌卡片
  - `viewer/src/components/ConceptGraph.tsx` — 概念图谱（SVG + List fallback）
- **依赖**: Task 13（Viewer 基础）
- **实施步骤**:
  1. **DashboardPage**: 显示所有 run 的 verdict/score/时间线 + Ratchet 趋势图。**冷启动降级（Gemini 审查新增）**：runs≤2 时隐藏 Line Chart，渲染为 KPI 卡片对比视图（Score Before → Score After 两个大号数字）；runs=1 时仅显示单次 Score 卡片 + "完成更多学习以查看趋势" 提示
  2. **LessonPage**: 渲染 lesson.full.md + 右栏 Claims/Evidence/Quiz 状态，支持 full/hint/compact 三标签切换（三段式撤架 UI）。**命名统一**：权威枚举为 `full|hint|compact`；旧原型中的第三档旧名已废弃，前端设计手册同步更新为 `compact`
  3. **DiffViewerPage**: 点击 diff 行 → 高亮相关 claim；点击 claim → 滚动到 source hunk（核心交互）。**移动端双向联动（Gemini Critical 修复 + 二轮验证修正）**：≤768px 时不使用全屏 Sheet/Drawer 展示 Claim 详情。改为：(a) Diff 行号旁显示 Claim Avatar 小圆点（按状态色编码）；(b) 点击后屏幕底部弹出 Bottom Mini-Panel，采用**三段 Snap Points 吸附设计**：默认 25vh（~167px，摘要视图）/ 手指上滑到 50vh（详情视图）/ 继续上滑到 90vh（近全屏，Back 手势返回）。`min-height: min(25vh, 180px)` 确保 iPhone SE 可用；(c) Mini-Panel 内显示 Claim 摘要，50vh 以上显示完整证据链；(d) 从 Mini-Panel 点击 "跳转到代码" 时，收起 Panel 到 25vh + 自动滚动到目标行
  4. **QuizPage**: Quiz 交互（Guided/Recall/Transfer 三类题型），答题结果通过 API 写入后端
  5. **ClaimBadge**: verified(绿 `#2F6F4F`)/weak(黄 `#B4791F`)/not_proven(灰 `#6B6B6B`)/contradicted(红 `#A33D2B`)/rejected(紫 `#7B5EA7`) 五态色彩标识
  6. **EvidencePanel**: file:line 证据链面板，点击跳转到 DiffViewer 对应 hunk
  7. **SRSCard**: 翻牌动画 + Good/Hard/Wrong 主按钮，直接调用 `ahadiff serve` API 写入；卡片右上角提供 `Archive` / `Suspend` 次级动作。`Archive` / `Suspend` 只更新 `card_state`，不写入 FSRS rating
  7a. **SRS peek guard**：当用户在同一 review session 内手动从 Hint/Compact 切回 Full 或主动展开完整答案时，置 `peeked_this_session=true`。此时 `Good` 按钮禁用，用户最多只能选择 `Hard` 或 `Wrong`；切到下一张卡时重置该标志
8. **ConceptGraph**: 概念图谱（SVG 力导向图 + List fallback for 无障碍）。**大集合聚类（Gemini 审查新增 + 二轮触屏修正）**：节点数>20 时默认按文件路径（File）分组为 Cluster 节点，每个 Cluster 显示文件名 + `+N` 概念数徽标（视觉暗示可展开）；**单击** Cluster 展开细节概念（不用双击——双击在触屏上不可发现且被浏览器缩放拦截）。节点数≤20 时正常展示全部节点。用户可通过 "展开全部/折叠为文件" 按钮切换。每个 Cluster 提供可见的 `⋮` 菜单按钮（触屏/鼠标共用），单击呼出展开/隐藏/高亮关联 claims，不依赖长按
8a. **Graphify 三态降级**：有导入产物时走 full 模式（repo-level context + learning overlay）；无 Graphify 但有学习数据时走 learning_only；两者都无时显示 empty state。Graphify 缺失不得阻塞 Dashboard / Lesson / Diff / Quiz 主路径
8b. **Graphify Source Card + Filter 显隐**：图谱区显示 Graphify Source Card，用于说明当前 graph source 与导入可用性；过滤器包含 `All / This Diff / Learning Memory / Weak Claims`，full 模式下额外显示 `From Graphify`，learning_only / empty 模式隐藏 `From Graphify`
  9. 移动端：EvidencePanel 在≤768px 使用步骤 3 的 Bottom Mini-Panel 模式（不用全屏 Drawer）
  10. 打印样式：保留证据链，隐藏 UI chrome
- **验收标准**: 
  - 4 个页面在 375px/768px/1024px/1440px 四个视口正常显示
- 375px 视口点击 Claim Avatar，底部 Mini-Panel 弹出且 Diff 代码仍可滚动查看
- ConceptGraph 50 节点时，聚类后实际渲染节点数 ≤20；Playwright trace 记录首屏渲染 <300ms，cluster 展开/折叠响应 <100ms，且无 >50ms long task
- Ratchet 趋势图在仅 1 次 run 时显示 KPI 卡片（非空坐标轴）
- Graphify 缺失时页面仍可正常工作，并明确显示 learning_only / empty 状态
- Graphify Source Card 在有/无导入产物两类场景下表现正确，不冻结具体 badge 文案；`From Graphify` 过滤器只在 full 模式显示
- **Review**: Gemini(gemini-3.1-pro-preview) 评审

### Task 14.5: Serve Backend（REST API for React 前端）

- **类型**: 后端（Codex 实现）
- **文件范围**:
  - `src/ahadiff/serve/app.py`
  - `src/ahadiff/serve/middleware.py`
  - `src/ahadiff/serve/routes_signals.py`
  - `src/ahadiff/serve/routes_locale.py`
  - `src/ahadiff/serve/routes_runs.py`
  - `src/ahadiff/serve/auth.py`
  - `src/ahadiff/serve/static.py` — 服务 React build 产物
  - `tests/unit/test_serve_app.py`
- **依赖**: Task 0（serve_app contract）+ Task 15（review.sqlite schema，signals/result 路由需要其表结构）。注：与 Task 14 并行开发，不阻塞等待 Task 14 完成
- **实施步骤**:
  0. **Run 目录二阶段发布协议（Codex R8 CX-3 修复）**：API 只暴露 finalized runs，防止前端读到 half-written artifact。协议：(a) learn/improve 写入 `runs/<run_id>.tmp/` 临时目录；(b) 所有文件写入完成后 `fsync` 每个文件；(c) 写入 `runs/<run_id>.tmp/finalized.json`（含 `{"finalized_at": "...", "artifact_count": N, "checksum": "..."}`）；(d) `os.rename("runs/<run_id>.tmp/", "runs/<run_id>/")` 原子发布。API `GET /api/runs` 只列出含 `finalized.json` 的 run 目录，并在返回 `RunSummary`/`RunDetail` 时可 join SQLite `result_events` 做聚合补充，但不得暴露未 finalized 临时 run。中断恢复：当前 v0.1 只要求 API 隐藏 `.tmp/` run 目录；清理面单独走 `ahadiff maint clean-orphans`，不并入 `doctor`
  1. 实现 Starlette app 工厂，`bind=127.0.0.1:8765`（**仅绑定回环地址，拒绝外网连接**）
  2. 实现路由鉴权矩阵：
     - 读路由（`GET /api/*`）：无需 token，默认开放
     - 写路由（`POST /api/signals/*`, `PUT /api/locale`）：需 `X-AhaDiff-Token` header
     - token 在 `ahadiff serve` 启动时自动生成，React 前端从 `GET /api/auth/token` 获取（仅限 localhost）
  3. 实现 `Host` + `Origin/Referer` 双校验中间件：只允许 `localhost`/`127.0.0.1`/`[::1]`
  4. 实现 JSON 数据 API：`GET /api/runs`、`GET /api/run/:id`、`GET /api/run/:id/lesson`、`GET /api/run/:id/claims`、`GET /api/run/:id/quiz`、`GET /api/run/:id/diff`、`GET /api/concepts`、`GET /api/ratchet/history`（只读，直接查 review.sqlite）。`GET /api/runs` 的最小摘要字段必须包含 `source_kind`、`capability_level`、`degraded_flags`、`status`，并支持可选 `?source_kind=` 过滤，供 Dashboard 默认把 `file_compare` / `patch_*` / `non_ratcheted` runs 排除在 ratchet 趋势图外。**Graphify DTO 口径**：`GET /api/run/:id` 需要返回给 Task 14 渲染三态图谱和 Graphify Source Card 所需的数据；字段命名与 shape 以 `doc/contract-freeze.md` 和对应 contract 文件为准，本文不在这里提前冻结成具体 JSON key
  5. 实现写入端点：`POST /api/signals/mark-wrong`、`POST /api/signals/quiz-answer`、`POST /api/signals/srs-review`、`POST /api/signals/helpfulness`
  6. 集成 `LocaleMiddleware`（CC-NEW-7 方案）：`GET /api/locale`、`PUT /api/locale`
  7. 实现 React 静态资源服务：`viewer/dist/` 目录通过 Starlette `StaticFiles` 挂载，SPA fallback 到 `index.html`
  8. 实现 `ahadiff serve [--port PORT] [--no-browser]` CLI 子命令。启动时自动调用 `webbrowser.open(f"http://localhost:{port}")` 打开浏览器，`--no-browser` 禁用此行为
- **验收标准**:
  - `ahadiff serve` 启动后自动打开浏览器，显示 React 前端
  - `curl -H "X-AhaDiff-Token: <token>" -X POST localhost:8765/api/signals/mark-wrong` 返回 200
  - `GET /api/runs` 返回 JSON 格式的 runs 列表
  - 外网 IP 连接被拒绝
  - 无 token 的写请求返回 403
- **Review**: Claude + Codex 交叉 review

---

## 第七段：review 与 learning signal

### Task 15: Review 系统（review.sqlite + SRS）

- **类型**: 后端（Codex 实现）
- **文件范围**:
  - `src/ahadiff/review/database.py`
  - `src/ahadiff/review/scheduler.py`
  - `src/ahadiff/review/signal.py`
  - `src/ahadiff/review/schemas.py`
  - `tests/unit/test_review.py`
- **依赖**: Task 10（Quiz）+ Task 12（Results）
- **实施步骤**:
  1. 创建 `review.sqlite` schema（**必须先复用 Task 0 的 SQLite 版本门禁 ≥3.51.3 和统一连接初始化**，含 WAL mode + busy_timeout=5000 + DBCONFIG_DEFENSIVE + quick_check）：`schema_version`(整数版本号，每次 migration 递增)、`cards`(**FSRS schema，Codex R8+FSRS 调研改进**：id/concept/run_id/fsrs_state TEXT NOT NULL（opaque Card JSON）/card_state TEXT NOT NULL DEFAULT 'active'（`active|stale|archived|suspended`）/scheduler_preset_id TEXT NOT NULL DEFAULT 'default' REFERENCES scheduler_presets(preset_id)/scheduler_version TEXT NOT NULL/desired_retention REAL DEFAULT 0.9/due_date TEXT NOT NULL（UTC）/stability REAL NOT NULL/difficulty REAL NOT NULL/reps INTEGER DEFAULT 0/lapses INTEGER DEFAULT 0/scaffolding_level TEXT DEFAULT 'full'/last_rating INTEGER/last_review_utc TEXT/source_ref/file_id/display_path/hunk_id/hunk_hash/symbol/change_kind/created_at_utc TEXT NOT NULL/archived_at_utc TEXT/suspended_at_utc TEXT)、`scheduler_presets`(preset_id/weights TEXT（opaque JSON array，不写死数量）/desired_retention/scheduler_version/total_reviews/last_optimized_utc/created_at_utc)、`review_logs`(id/card_id/rating/reviewed_at_utc/elapsed_days/scheduled_days/state，供 Optimizer 训练用)、`result_events`(物理事件表，SQLite 为唯一真相源)、`learning_signals`(event_id/idempotency_key UNIQUE/signal_type/payload_json/created_at，用户行为日志)。schema_version 嵌入 DB，不匹配时通过顺序 SQL migration 自动升级。**所有时间戳统一 UTC**（py-fsrs 强制）。**版本门禁验收**：低于 3.51.3 且不在 backport 白名单时拒绝创建/打开 DB
  2. 实现 **FSRS-6 SRS 调度算法**（替代 SM-2，详见 `ahadiff-fsrs-decision.md`）：使用 `py-fsrs` 库（`pip install fsrs`，v6.3.1+）。默认 `desired_retention=0.9`，`maximum_interval=365`，`enable_fuzzing=True`。ReviewCard 存储 FSRS Card JSON 序列化（`fsrs_state` 字段，opaque）而非 SM-2 的 ease/interval/reps。**v0.1 UI 只暴露 Good/Hard/Wrong 三按钮**（不暴露 Easy）：答对=Good(3)，犹豫答对=Hard(2)，答错/mark-wrong=Again(1)。安全/误解题答错额外生成 misconception 卡。`Archive` / `Suspend` 是队列控制动作，不映射为 rating，也不直接修改 stability/difficulty。**peek guard**：若 `peeked_this_session=true`，本轮最多只能提交 `Hard` 或 `Again`，不得提交 `Good`。冷启动用默认 weights + desired_retention=0.90（不运行 optimizer）；**≥500-1000 次有效 review** 后支持 `ahadiff review --optimize` 运行 Optimizer。**重训双门槛**：距上次训练 ≥30 天 **或** 新增 review 数 ≥ max(512, 上次样本量×50%)。**三段式撤架由 FSRS stability 驱动**：full=Learning/Relearning 或 stability<3d，hint=Review 且 3d≤stability<14d，compact=stability≥14d 且最近 2 次成功。保留 `--scheduler sm2` feature-flag fallback（不做默认路径）
  3. 实现 `ahadiff review` CLI：展示 due cards，记录答题结果
  4. 实现 `ahadiff mark <claim_id> wrong` CLI：用户标记 claim 错误 → 写入 review.sqlite `learning_signals` 表
  5. 实现 `results.tsv → result_events` 入库契约：
     - `result_events` 是多行事件表，同一 run_id 可有多行（如 keep → targeted_verify → keep_final）。主键为 `event_id`（UUID v7，全局唯一），`run_id`/`event_type`/`timestamp` 为二级索引
     - `result_events` 是**物理表**（非视图），列集是 `results.tsv` 导出视图的 superset：除 TSV 字段外，还显式保存 `event_id`、`event_type`、`eval_bundle_version`。`results.tsv` 继续保持 11 列导出形状，不要求与事件表逐列同构
     - **写入责任**归属 `eval/results.py`（Task 12）：每次 `append_result()` 时同步调用 `review/database.py` 的 `sync_result_event()` 写入 SQLite，写入前检查 `event_id` 幂等
     - 字段映射：results.tsv 的 `weakest_dim` → SQLite 的 `weakest_dim`（统一用短名）
     - **写入顺序**：先写 SQLite（有事务保护），成功后 append TSV。TSV 仅作为人类可读的 audit trail，SQLite 为唯一真相源。TSV 写入失败仅 warn，不阻塞主流程。提供 `ahadiff export-results` 从 SQLite 重建 TSV
  6. 实现 `targeted_verify → keep_final` 升级规则：
     - `ahadiff improve` 中 targeted verification 通过后 status=`targeted_verify`
     - 全 8 维 recheck 通过后由 `ahadiff db finalize-targeted <event_id>` 升级为 `keep_final`（Task 15 已提供手动入口；Task 17 当前 runtime 仍保留这个人工收口点）
     - 升级时写入新 result_event 行（status=keep_final），不修改原行
     - 升级失败（全 8 维 recheck 分数下降）则 status 保持 `targeted_verify`，不回滚
  7. 实现 `ahadiff regenerate --only quiz <run_id>` CLI：只重新生成 quiz，不重跑 lesson
  8. 索引（Task 15 为唯一 DDL owner，与 Task 0/Task 12 口径一致）：`event_id` 主键, `(run_id, event_type, timestamp)` 唯一索引, `(source_ref, timestamp DESC)`, `(prompt_version, eval_bundle_version)`, `(verdict, status)`, `(weakest_dim, timestamp DESC)`
  9. 实现 `ahadiff db upgrade`：每个 migration 脚本在 `BEGIN EXCLUSIVE ... COMMIT` 事务中执行，失败时自动回滚到备份。升级前自动生成一致性备份（使用 SQLite backup API 或 `VACUUM INTO`，**不要直接 cp**）
  10. 实现 `ahadiff db backup` / `ahadiff db restore <backup_path>`：手动备份/恢复
  11. **取消 TSV 无损 repair 承诺**：`ahadiff db repair` 更名为 `ahadiff db import-results --lossy`，仅作为最后手段，显式声明为有损导入（合成 event_id，event_type 标记为 `imported_from_tsv`）。默认隐藏，需 `--i-understand-this-is-lossy` flag
  12. 实现 `ahadiff db check`：验证 SQLite schema_version 与期望一致、WAL 完整性、event_id 唯一性
- **验收标准**: `ahadiff review` 显示 due cards，wrong concepts 写入 review.sqlite `learning_signals` 表；upgrade 前有 .bak 备份；migration 失败自动回滚

---

## 第八段：improve loop + targeted verification + Phase 2.5

### Task 16: Improve Loop 核心

- **类型**: 后端（Codex 实现）
- **文件范围**:
  - `src/ahadiff/improve/__init__.py`
  - `src/ahadiff/improve/loop.py`
  - `src/ahadiff/improve/program.py`
  - `prompts/improve_program.md`
  - `src/ahadiff/prompts/improve_program.md`
  - `tests/unit/test_improve_loop.py`
- **依赖**: Task 11（Evaluator）+ Task 12（Ratchet）+ Task 15（Review SQLite）
- **实施步骤**:
  1. 实现 `improve_program.md`（自然语言状态机，人类写，agent 解释执行）
  2. 实现 `ahadiff improve --suite local --rounds N` CLI；当前只支持 `--suite local`，`--rounds` 限制为 1..20，并支持 `--resume <session_id>`
  3. 可写边界严格约束：improve loop **只允许改** `prompts/lesson_generate.md`、`prompts/lesson_hint.md`、`prompts/lesson_compact.md`、`prompts/quiz_generate.md`、`prompts/claim_extract.md`。`prompts/improve_program.md` 是 human-written immutable state machine，**禁止**被 improve loop 修改；同样禁止改 evaluator.py/rubric.yaml/viewer 模板/test fixtures/source code
  4. 实现 weakest-dimension-first 选择（从 review.sqlite.result_events 查询最近记录）
  5. 实现 prompt versioning：`prompt_version = AhaDiff 自带 prompt 资源 tree hash 前 7 位`。source checkout / improve worktree 读取 `src/ahadiff/prompts`，wheel 安装态读取包内 `ahadiff/prompts`，目标仓库顶层 `prompts/` 不参与哈希
  6. 简洁性准则写入 improve_program.md
  7. **Improve 隔离策略（统一 worktree）**：常规 improve loop 和后续 Phase 2.5 均在 `git worktree add` 创建的临时 worktree 中执行，不触碰用户主分支工作区。Task 16 当前 worktree 路径为 `.ahadiff/improve/wt/<12hex>-rN`，避免深路径超长；keep 候选先从 worktree cherry-pick 回主分支，再写 result event；discard 删除 worktree 且不写 `finalized.json`。cherry-pick 冲突时自动 abort，保留 pending worktree，输出冲突文件列表供人工解决，不强制覆盖主分支；该 pending run 写 `targeted_verify` event 但不 finalized，也不作为下一轮 baseline。improve loop 启动前检查主分支 `prompts/` 是否有未提交修改，有则提前警告用户。**Ctrl+C 行为（Task 16 当前代码）**：improve loop 注册 `signal.SIGINT` handler；当前 round 已写入结果后收到 interrupt，只停止后续 round，不再追加第二条 crash event；未完成 round 的异常路径仍记录 crash。非主线程安装 handler 时直接 no-op，避免 API server 未来调用崩溃。**session 语义冻结**：每次 `ahadiff improve` 生成 `improve_session_id`，校验为简单文件名，并把 `phase25_attempted`、`rounds_completed`、`worktree_path` 持久化到 `.ahadiff/improve/<session_id>.json`；同一 session 重启/`--resume` 时必须恢复该状态，遇到 pending worktree 会先拒绝继续，防止重复写入或误删
  8. 禁止并发 improve：复用 repo_write_lock（`.ahadiff/ahadiff.lock`，portalocker），第二个 improve 实例被拒绝
- **当前验收**: Task 14.5/16/17 后端 runtime 已落地；Task 18/19/20 与 i18n-0 后端也已落地并完成本轮 review 修复。`uv run --frozen --no-sync pytest tests/unit -q` 为 461 passed；`uv run --frozen --no-sync pytest tests/eval -q` 为 7 passed；`uv run --frozen --no-sync pytest tests/integration/test_learn_pipeline.py -m pinned -q` 为 10 passed；全量 `tests` 为 478 passed, 1 skipped（live judge 默认跳过）；显式 live judge 为 1 passed，并单独确认 `gpt-5.3-codex-spark` 可用；`ruff check` / `ruff format --check` / `pyright` / `uv build --wheel` / `python -m ahadiff install github-action --help` 均通过。macOS+Ubuntu CI / workflow、Windows hooks 明确拒绝、static-only install template render、serve artifact SQL 查询与 `ServeState.with_locale()` 运行时字段复用也已补齐；尚未把 Windows CI 或真实 provider 下的 6 轮 E2E 写成已完成事实

### Task 17: Targeted Verification + Phase 2.5

- **类型**: 后端（Codex 实现）
- **文件范围**:
  - `src/ahadiff/improve/targeted.py`（与 Task 16 共享）
  - `src/ahadiff/improve/rewrite.py`（与 Task 16 共享）
  - `tests/unit/test_targeted_verify.py`
  - `tests/unit/test_phase25.py`
- **依赖**: Task 16（Improve Loop）
- **当前状态（2026-04-24）**: 已新增 `improve/targeted.py` 与 `improve/rewrite.py`，并接入 `improve/loop.py`。当前实现比较目标维度 + `accuracy` + `evidence` + `safety_privacy` 四个维度的合计分，且要求 hard gates 通过；同一 session 连续两次 `discard` 会触发一次 Phase 2.5 worktree rewrite。`keep_final` 仍通过全 8 维 recheck 后的 `ahadiff db finalize-targeted <event_id>` 手动收口，不在 improve loop 内自动升级
- **实施步骤**:
  1. 实现 Targeted Verification（R11）：improve 后不重跑全 8 维，只验证 **目标维度 + accuracy + evidence + safety_privacy**（4 维）
  2. 通过则 status=`targeted_verify`；最终 `keep_final` 仍走手动 `db finalize-targeted` 的全 8 维 recheck
  3. 实现 Phase 2.5 structural rewrite：连续 2 个优化目标在首轮即 discard → 在新 worktree 中从头重写 → 评估 → 更好则 cherry-pick 回主分支，否则删除 worktree。**Phase 2.5 最多触发 1 次/session**（设置 `phase25_attempted=true` 标志，持久化在 improve session 文件中，防止无限重写循环）
  4. Phase 2.5 触发时 status=`phase25_rewrite`（结构化枚举，非自由文本）。`note_json` 字段记录 `phase25=true`、`phase25_note`、`stash_ref`、`trigger_reason`。最终结果写入 results：通过=`targeted_verify`（走 improve 链路，后续可手动升级为 `keep_final`），不通过=`discard`。**注意**：Phase 2.5 属于 improve 链路，不使用 `keep` 状态（与 Task 12 step 7 状态机统一定义一致）
- **当前验收**: `tests/unit/test_targeted_verify.py`、`tests/unit/test_phase25.py` 已覆盖 targeted 维度选择、hard gate、discard 触发、Phase 2.5 单次触发、rewrite 事件与最终状态；本次 targeted suite 为 56 passed。token 节省比例尚未做 benchmark 度量，不能写成已验证事实

### Task 18: Benchmark Suite（本地版）

- **类型**: 后端（Codex 实现）
- **文件范围**:
  - `benchmarks/` 目录
  - `src/ahadiff/eval/benchmark.py`
  - `tests/eval/test_benchmark.py`
  - `tests/eval/test_judge_stability.py`
  - `tests/integration/test_learn_pipeline.py`
- **依赖**: Task 11（Evaluator）
- **实施步骤**:
  1. **冻结 `benchmarks/manifest.json`**（数据范围架构新增）：定义 `suite_id`（如 "ahadiff-local-v1"）、`suite_digest`（全部 fixture 的联合 SHA-256）、`visibility`（"private"|"public"）、entries 列表。只有 `suite_digest + eval_bundle_version + model_id + api_family_version` 全匹配时 benchmark 结果才可比
  2. 构建 **20 份 pinned eval diff**：
     - **Benchmark 主套件**（10 份）：7 份 Python 全功能验证（AST + regex + section_header）+ 3 份 Non-Python 降级路径（TypeScript/Rust/Go）
     - **Judge stability / edge regression 套件**（10 份）：覆盖 `patch_file` / `patch_stdin` / `file_compare` / `git_since`、`binary_only` / `file_count_exceeded` / `token_exceeded`、redaction / injection / i18n / `non_ratcheted` 等关键边界
     - 两套件独立出 recall/precision 与稳定性报告，不混成单一基线
     - Non-Python 套件的期望 recall 显式低于 Python 套件（标注 `degraded=true`）
  3. 额外构建 **10 份 pinned integration diff**：覆盖 `learn -> claim -> lesson -> quiz -> results.tsv/review.sqlite` 主链路，fixture 必须带 `expected_artifacts_manifest.json`
  3a. 额外保留一层 **live smoke**：基于一个外部参考私有仓库（文档中统一记为 `<REFERENCE_REPO>`）运行真实 diff / provider / 主链路最小冒烟；如需连通本机开发 provider，可使用 loopback OpenAI-compatible endpoint。live smoke 结果只做连通性与回归兜底，不写入 `suite_digest` 可比基线
  4. benchmark / judge-stability fixture 每份含：`diff.patch` + `ground_truth.md` + `qa_probe.jsonl` + `expected_concepts.json`
  5. integration fixture 每份含：repo fixture 或 patch fixture + `expected_artifacts_manifest.json` + `expected_results_snapshot.json`
  6. 实现 `ahadiff benchmark --suite local` CLI（运行 20 份 eval diff）
  7. 实现 `pytest tests/integration/test_learn_pipeline.py -m pinned`（运行 10 份 pinned E2E）
  8. 输出 benchmark report：mean score / claim verification rate / 各维度均值 + `suite_id` + `suite_digest`
- **验收标准**: `ahadiff benchmark --suite local` 跑通 20 份 eval diff；`pytest tests/integration/test_learn_pipeline.py -m pinned` 跑通 10 份 pinned E2E；live smoke 至少覆盖 1 个真实仓库 diff + 1 次 loopback provider 探测；`benchmarks/manifest.json` 存在且 `suite_digest` 可验证；报告含 `suite_id` 与 `api_family_version`
- **VCR cassette 管理（双层版本策略）**：
  - **run 级**：`prompt_version = tree hash(AhaDiff 自带 prompts)` 不变，用于 results/ratchet 一致性
  - **cassette 级**：`prompt_fingerprint = hash(top_level_prompt_file + declared_includes + schema_version)`。每个 LLM 调用按 `prompt_fingerprint + model_id + api_family_version + eval_bundle_version + output_lang` 五元组命名 cassette 文件。修改 `lesson_generate.md` 只失效 lesson 相关 cassette，不影响 quiz/claim cassette；修改 evaluation bundle 任一文件时自动生成新 key；不同 API family/version 或兼容网关不得共享 cassette
  - **实现**：`src/ahadiff/prompts/loader.py` 新增 `load_prompt_bundle(name) → (text, deps, fingerprint)` 和 `compute_prompt_fingerprint()`。`tests/helpers/vcr_keys.py` 提供 `make_cassette_key()`。prompt 文件通过 frontmatter `includes: [shared/base.md]` 声明依赖
  - **CI 分档**：PR 触发 `tests/unit`（无 LLM，全 mock），nightly 触发 `tests/eval`（有 LLM，VCR 录制）。月均 LLM 成本预算 $50
  - **edge case**：共享 partial 改动 → 所有显式依赖它的 cassette 失效；prompt rename → path 纳入 fingerprint，rename 会失效（by design）；judge/generator cassette 严格分开

---

## 第九段：agent & automation install

### Task 19: Install 统一架构

- **类型**: 后端（Codex 实现）
- **文件范围**:
  - `src/ahadiff/install/base.py`（InstallTarget protocol）
  - `src/ahadiff/install/registry.py`
  - `src/ahadiff/install/claude.py`
  - `src/ahadiff/install/codex.py`
  - `src/ahadiff/install/gemini.py`
  - `src/ahadiff/install/opencode.py`
  - `src/ahadiff/install/hooks.py`
  - `src/ahadiff/install/templates/*.j2`
  - `src/ahadiff/cli.py`（新增 install/uninstall 子命令）
  - `tests/unit/test_install.py`
- **依赖**: CLI 接口冻结（Task 9 + Task 10 + Task 11 + Task 15 + Task 16）
- **实施步骤**:
  1. 实现 `InstallTarget` protocol：`detect() → bool`, `preview() → str`, `write() → list[Path]`, `uninstall() → list[Path]`
  2. **v0.1 只实现 4 个核心 CLI target**：
     - `claude` — 写入 `.claude/skills/ahadiff/SKILL.md` + 追加 `CLAUDE.md` section
     - `codex` — 写入 `AGENTS.md`（AAIF 标准）
     - `gemini` — 追加 `GEMINI.md` 段落
     - `opencode` — 写入 `AGENTS.md` + `.opencode/agents/ahadiff.md`
     其中 codex/opencode 共享 AGENTS.md 模板
  3. **v0.2 扩展 7 个 IDE/复用 target**：cursor / copilot / windsurf / cline / amp / jules / aider
  4. 实现 Git hooks：post-commit（非阻塞提示）、pre-push（未学习 diff 警告）
  5. 实现 `--detect` 自动检测已安装工具
  6. 实现 `--dry-run` 预览、`--force` 覆盖、`uninstall` 清理
  7. 实现 safe merge 规则：检测目标文件是否已存在用户内容，存在则追加 section 而非覆盖；冲突时 diff 展示并询问
  8. 所有配置通过 Jinja2 模板化生成
  9. 默认不改用户全局配置，不默认启用阻断式 hook
- **验收标准**: 4 个核心 CLI target + hooks 的 `--dry-run` 全部正确输出将写入的文件列表
- **v0.2 验收标准**: 额外 7 个 target 的 `--dry-run` 全部正确
- **规则文件对照**: 详见 `.claude/team-plan/ahadiff-agent-rules-registry.md`

### Task 20: GitHub Action 集成

- **类型**: 后端（Codex 实现）
- **文件范围**:
  - `src/ahadiff/install/github_action.py`
  - `src/ahadiff/install/templates/ahadiff-verify.yml.j2`
  - `src/ahadiff/install/templates/ahadiff-generate.yml.j2`
  - `tests/unit/test_github_action.py`
- **依赖**: Task 19（Install 架构）
- **实施步骤**:
  1. Layer 1 verify-only（默认，无需密钥）：生成的 workflow 通过 `uvx --from ahadiff ahadiff verify --ci` 校验已存在 artifacts，不假设仓库里有 AhaDiff 源码 checkout
  2. Layer 2 generate-on-CI（显式 opt-in，需 `AHADIFF_PROVIDER_API_KEY`）：PR push 时生成 lesson，并上传 `.ahadiff/` outputs artifact
  3. 实现 `ahadiff install github-action [--layer2]` CLI
- **验收标准**: 生成的 workflow YAML 语法正确，`ahadiff verify --ci` 可在 CI 环境运行；默认 verify workflow 不再运行源码测试或 coverage gate

---

## 文件冲突检查

⚠️ 基本隔离，存在以下已知共享：
- Task 19 与 Task 1 共享 `cli.py`（Task 1 已完成，串行无冲突）
- Task 17 已新增 `improve/targeted.py` 和 `improve/rewrite.py`，并依赖 Task 16 的 `improve/loop.py` / `improve/program.py` 串行接入
- Task 19 与 Task 20 共享 `install/templates/` 目录（通配符重叠，但文件名不同）

| Task | 主要文件范围 |
|------|------------|
| Task 9 | `lesson/*`, `prompts/lesson_*.md` |
| Task 10 | `quiz/*`, `prompts/quiz_*.md` |
| Task 11 | `eval/evaluator.py`, `eval/rubric.py`, `eval/gates.py`, `eval/rubric.yaml` |
| Task 12 | `eval/ratchet.py`, `eval/results.py` |
| Task 13 | `viewer/package.json`, `viewer/vite.config.ts`, `viewer/src/{App,components,styles,api,i18n}` |
| Task 14 | `viewer/src/pages/*`, `viewer/src/components/{ClaimBadge,EvidencePanel,SRSCard,ConceptGraph}` |
| Task 15 | `review/*` |
| Task 16 | `improve/loop.py`, `improve/program.py`, `prompts/improve_program.md` |
| Task 17 | `improve/targeted.py`, `improve/rewrite.py` |
| Task 18 | `benchmarks/*`, `eval/benchmark.py` |
| Task 19 | `install/*`, `cli.py`（新增子命令） |
| Task 20 | `install/github_action.py`, `install/templates/*.yml.j2` |

**注意**：Task 19 需要修改 `cli.py`（与 Task 1 共享），但 Task 1 已完成，不构成并行冲突。

## 并行分组

```
Layer 4 (并行):  Task 9 (依赖 Task 7 + Task 8)
                 Task 11 (依赖 Task 0 + Task 7，可与 Task 9 并行)
   ↓
Layer 5 (串行+并行):
                 Task 10 (依赖 Task 9 + Task 8，串行)
                 Task 12 (依赖 Task 0 + Task 11，与 Task 10 并行)
                 Task 13 (依赖 Task 0，API 通过 mock/proxy 解耦，与 Task 10 并行)
   ↓
Layer 6a (并行): Task 14 (依赖 Task 13)
                 Task 15 (依赖 Task 10 + Task 12，与 Task 14 并行)
   ↓
Layer 6b (串行): Task 14.5 (依赖 Task 0 + Task 13 + **Task 15**，必须等 Task 15 完成 DB schema)
                 ⚠️ 注意：Task 14.5 不能与 Task 15 真正并行（signals 路由需要 review.sqlite schema）
   ↓
Layer 7 (串行):  Task 16 (依赖 Task 11 + Task 12 + Task 15)
   ↓             Task 17 (依赖 Task 16，串行)
                 Task 18 (依赖 Task 11，可与 Task 16 并行)
   ↓
Layer 8 (串行):  Task 19 (依赖 CLI 接口冻结：Task 9+10+11+15+16)
                 Task 20 (依赖 Task 19，串行)

注：Task 11 的 Claim 消费能力（步骤 4 机械化打分读 claims.jsonl）
    可延迟到 Task 8 产物可用时填充，不阻塞 evaluator 骨架实现。
```

## 模型分工

| Task | 实现 | Review |
|------|------|--------|
| Task 9 Lesson | Codex | Claude + Codex |
| Task 10 Quiz | Codex | Claude + Codex |
| Task 11 Evaluator | Codex | Claude + Codex |
| Task 12 Ratchet | Codex | Claude + Codex |
| Task 13 Viewer 基础 | Claude | Gemini + Codex |
| Task 14 Viewer 页面 | Claude | Gemini + Codex |
| Task 15 Review | Codex | Claude + Codex |
| Task 16 Improve | Codex | Claude + Codex |
| Task 17 Targeted | Codex | Claude + Codex |
| Task 18 Benchmark | Codex | Claude + Codex |
| Task 19 Install | Codex | Claude + Codex |
| Task 20 GitHub Action | Codex | Claude + Codex |

## Codex 覆盖遗漏处理

以下功能**明确推迟到 v0.2+**（不在 v0.1 scope 内）：
- Spec-before-code（`ahadiff plan`）→ v0.2
- section-level helpfulness → v0.2（先用 file-level）
- uncertainty report → 已合并到 lesson 的 Not Proven 段落
- Socratic follow-up → v0.2
- forgetting-risk dashboard → v0.2
- shareable result cards（`ahadiff card`）→ v0.2
- index.md 增量 wiki → v0.2
- **concepts.jsonl 最小版提前到 v0.1**（branch-aware 方案）：
  - **存储**：repo 级 `.ahadiff/concepts.jsonl`，JSONL 格式但每个 term_key 恰好一行（upsert 语义，非纯追加）
  - **每条记录**：`{concept, term_key, source_refs[], branch_hint, introduced_by_run, updated_by_runs[], related_claims[], file_refs[]}`
  - **读取时 branch 过滤**：`load_visible_concepts(head_ref)` 只返回 `source_refs[]` 中有任一 ref 是当前 HEAD ancestor 的记录（`any(is-ancestor)`）；全部不可达的概念保留在日志但默认隐藏
  - **merge 语义**：feature-A 合并到 main 后，若原 commit 仍可达，概念自动重新可见；squash/cherry-pick 导致原 SHA 不可达时，后续 run 会追加新 source_ref 到 `source_refs[]` 使概念重新可达
  - **去重**：`append_concepts()` 时按 `compute_term_key(concept)` 检查已存在（NFKD + lowercase + slug 归一化），存在则合并 `updated_by_runs`、`file_refs`，并追加当前 commit 到 `source_refs[]`
  - **非 git 输入**：概念仅在 run-local 视图展示，不进入全局 concepts
  - **实现文件**：`src/ahadiff/wiki/concepts.py`（~120-180 行）
- Claim Inspector 独立页面 → 已合并到 Diff+Evidence Viewer 侧边栏
- Spec Alignment 页面 → v0.2
- Benchmark Transparency 页面 → v0.2
- Agent Skill Hub viewer 页面 → v0.2
- public benchmark suite → v0.2（v0.1 只做 local）
- `--level beginner/intermediate/senior` → v0.2
- `--staged` 已纳入 v0.1（`git diff --cached`，实现简单，与 Blueprint 一致）
- `--unstaged` 已纳入 v0.1（`git diff`，AI coding 后最高频场景）
- `git show <sha>` 已纳入 v0.1（单 commit 学习，复用 git_ref source_kind）
- PR patch / 平台 URL 输入 → v0.2（`--patch-url`，httpx GET 薄封装）

## 第十段：i18n 全链路国际化（新增）

> 依赖：Task 0（Schema Freeze）+ 各层 Task 并行集成
> 估时：~3.75 天（可与 Layer 4-8 并行）
> 口径：这是跨 `CLAUDE.md Stage 3-6` 的 overlay，不是新的独立 Stage；最终只在 `Stage 7` 做 signoff

### Task i18n-0: i18n Schema 冻结

- **类型**: 后端（Codex 实现）
- **文件范围**:
  - `src/ahadiff/i18n/resolver.py` — locale 解析优先级链
  - `src/ahadiff/config.py` — UserConfig 加 `lang` 字段
- **依赖**: Task 0（Schema Freeze Gate）
- **实施步骤**:
  1. 实现 locale 解析链：手动切换(cookie) → 浏览器 Accept-Language → CLI `--lang` → config.toml `[general] lang` → 系统 `LANG` 环境变量 → 降级 `en`
  2. UserConfig 加 `lang: Literal["auto", "en", "zh-CN"] = "auto"`
  3. RunRecord 加 `content_lang: str`（记录生成时的解析语言）
  4. ConceptNode 加 `term_key: str`（slug 归一化稳定身份）+ `term: str`（规范英文）+ `display_name: str`（本地化）+ `lang: str` + `aliases: list[str]`（CC-NEW-5 闭合方案回流）
  5. EvidenceAnchor 加 `file_id: str`（SHA-256 前缀，脱敏前分配）+ `display_path: str`（脱敏后显示路径）（CC-NEW-3 闭合方案回流）
  5. config.toml 加 `[general] lang = "auto"` + `[llm] prompt_lang = "auto"` + `[llm] output_lang = "auto"`
- **验收标准**: `resolve_locale()` 在 CLI 和 serve 两种模式下都返回正确 locale

### Task i18n-1: JSON Catalog + Loader

- **类型**: 前端+后端（Claude 实现）
- **文件范围**:
  - `messages/en.json` — 英文消息目录（扩展为 12+ 类别）
  - `messages/zh-CN.json` — 中文消息目录
  - `src/ahadiff/i18n/catalog.py` — JSON catalog loader
- **依赖**: Task i18n-0
- **实施步骤**:
  1. 扩展消息目录类别：Brand/Nav/Claim/Verdict/Rubric/Quiz/SRS/Serve/Settings/CLI/Error/Accessibility
  2. 实现 `load_catalog(locale: str) -> dict` 函数
  3. 实现 `translate(key: str, locale: str, **kwargs) -> str`（支持 `{variable}` 插值）
  4. CLI 使用 Rich 输出本地化消息
- **验收标准**: `translate("Nav.dashboard", "zh-CN")` 返回 "运行"

### Task i18n-2: Prompt 语言指令

- **类型**: 后端（Claude 编写 prompt，Codex review）
- **文件范围**: `prompts/*.md` 所有 prompt 文件头部
- **依赖**: Task i18n-0 + Task 9（Lesson prompt 存在后才能加指令）
- **实施步骤**:
  1. 所有 prompt 文件头部添加 `## Language Directive` 段落
  2. 使用 `{{OUTPUT_LANGUAGE}}` 模板变量（由 `llm/provider.py` 注入）
  3. 中文规则：技术术语保留英文原文，首次出现时括注中文
  4. 英文规则：All explanations in English
  5. 代码片段、文件路径、变量名：NEVER translate
- **验收标准**: lesson 生成在 `--lang zh` 时输出中文解释，`--lang en` 时输出英文解释

### Task i18n-3: React 组件 i18n

- **类型**: 前端（Claude 实现，Gemini 评审）
- **文件范围**: `viewer/src/**/*.tsx` 所有 React 组件
- **依赖**: Task i18n-1 + Task 13（React Viewer 基础架构存在后才能改组件）
- **实施步骤**:
  1. 实现 `viewer/src/i18n/locale-store.ts`：Zustand store 提供 `locale`、`messages`、`setLocale()` 与 `t()` 翻译函数
  2. 实现 `useTranslation()` hook，组件内调用 `t("Nav.dashboard")` 获取翻译；重量级组件禁止直接订阅整个 locale store
  3. 所有硬编码中文/英文文案替换为 `t()` 调用
  4. `<html lang={locale}>` 动态设置
  5. 语言切换时通过 Zustand 的细粒度 selector 触发局部 re-render，无需页面刷新；`DiffView`、`EvidencePanel` 等组件不得因 locale 切换整树重建
  6. 数字/日期格式按 locale 格式化（使用 `Intl.DateTimeFormat` / `Intl.NumberFormat`）
- **验收标准**: 同一页面在 zh-CN 和 en 下所有文案正确切换，切换无闪烁

### Task i18n-4: 前端语言切换 UI

- **类型**: 前端（Claude 实现，Gemini 评审）
- **文件范围**:
  - `viewer/src/components/LanguageSwitcher.tsx` — 语言切换按钮组件
  - `viewer/src/styles/language-switcher.css` — 按钮样式
  - `src/ahadiff/serve/app.py` — locale API endpoint（统一 serve 模块路径）
- **依赖**: Task i18n-3 + Task 14（Viewer 页面存在）+ Task 14.5（Serve 存在）
- **实施步骤**:
  1. Topbar 右侧添加 zh/EN 切换按钮组件（紧邻主题切换按钮）
  2. 点击后：写 cookie `ahadiff_lang` + 调用 Zustand `setLocale()` 触发局部 i18n re-render（无需页面刷新）
  3. 同时调用 Serve API `PUT /api/locale` 持久化选择
  4. 初始化时：读 cookie → 浏览器 `navigator.language` → 降级 `en`
  5. 按钮样式：当前语言高亮，非当前语言降低不透明度
- **验收标准**: 点击 zh/EN 按钮后页面立即切换语言，无闪烁无刷新

### Task i18n-5: CLI 语言支持

- **类型**: 后端（Codex 实现）
- **文件范围**:
  - `src/ahadiff/cli.py` — `--lang` 全局参数
  - Rich console 输出本地化
- **依赖**: Task i18n-1
- **实施步骤**:
  1. 添加 `--lang` 全局 Typer Option（`auto|en|zh-CN`）
  2. Rich 进度条、状态消息、错误消息使用 `translate()` 函数
  3. `ahadiff learn --lang zh HEAD~1..HEAD` 生成中文 lesson
- **验收标准**: CLI 在 `--lang zh` 和 `--lang en` 下所有提示信息正确

### Task i18n-6: VCR Cassette Key 扩展

- **类型**: 后端（Codex 实现）
- **文件范围**: `src/ahadiff/eval/vcr.py`
- **依赖**: Task i18n-2 + Task 18（VCR/Benchmark 存在）
- **实施步骤**:
  1. 在 Task 18 的 base key 基础上冻结语言维度：最终 cassette key 为五元组 `prompt_fingerprint + model_id + api_family_version + eval_bundle_version + output_lang`
  2. 语言变更仅失效对应语言 cassette；`api_family_version` 变更也必须失效对应 cassette
  3. 测试：同一 diff 在 en/zh-CN 下生成不同 cassette；同一 `model_id` 但不同 `api_family_version` 也必须生成不同 cassette
- **验收标准**: `output_lang` 或 `api_family_version` 变更时仅失效对应 cassette，不影响其他语言或其他 provider family

---

## i18n Task 依赖图

```
Task 0 (Schema Freeze)
  └─> Task i18n-0 (i18n Schema)
        ├─> Task i18n-1 (JSON Catalog)
        │     ├─> Task i18n-3 (React 组件 i18n) ──> Task i18n-4 (语言切换 UI)
        │     └─> Task i18n-5 (CLI 语言)
        └─> Task i18n-2 (Prompt 语言指令) ──> Task i18n-6 (VCR Key 扩展)
```

## 预计时间（修订）

- Layer 4: ~2 天（Lesson + Quiz + Evaluator 并行）
- Layer 5: ~2 天（Ratchet + Viewer 基础 并行）
- Layer 6a: ~1.5 天（Viewer 页面 + Review DB 并行）
- Layer 6b: ~1 天（Serve Backend，等待 Task 15 DB schema）
- Layer 7: ~2 天（Improve + Targeted + Benchmark 并行）
- Layer 8: ~1 天（Install + GitHub Action 并行）
- **i18n: ~3.75 天（理论并行，实际因渗透集成可能需串行）**

**总计：~8 天**（主线）+ i18n + 集成开销，加上 Layer 1-3 的 ~5-7 天 = **v0.1 完整开发周期修正估计 ~14-16 天**（原估 11-12 天偏乐观，第四轮终审修正）
