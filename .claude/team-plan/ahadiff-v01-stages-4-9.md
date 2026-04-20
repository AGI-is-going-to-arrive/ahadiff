# AhaDiff v0.1 开发计划 — 第 4-9 段 Task 拆分

> 生成时间：2026-04-20
> 基于：ahadiff-v01-revision.md + Codex 技术审查 + Gemini 前端评审
> 依赖：Layer 1-3（Task 1-8）全部完成

---

## 段落顺序说明

采用 Codex 建议的调整顺序（与原方案第五/六/七/八段重排）：

```
原顺序                    新顺序（Codex 建议）
第四段 lesson + quiz      → 第四段 lesson + quiz（不变）
第五段 Warm HTML viewer   → 第五段 score + verifier hard gates + results.tsv
第六段 score + verifier   → 第六段 Warm HTML viewer
第七段 review + learning  → 第七段 review + learning signal
第八段 improve loop       → 第八段 improve loop + targeted verification + Phase 2.5
第九段 agent install      → 第九段 agent & automation install（扩展为 6 工具 + hooks + Action）
```

理由：score/evaluator 是 improve loop 的前置依赖，必须在 viewer 之前就绪；viewer 需要 score.json 来驱动 Rubric 展示。

---

## 第四段：lesson + quiz

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
- **依赖**: Task 7（LLM Provider）+ Task 8（Claim 提取）
- **实施步骤**:
  1. 定义 Pydantic schema：`LessonFull`, `LessonHint`, `LessonCompact`
  2. 编写 `lesson_generate.md` prompt（遵循 §11 lesson 设计规范）
  3. 实现 `generate_lesson()` → 生成 `lesson.full.md`（完整解释）
  4. 实现 `generate_hint()` → 生成 `lesson.hint.md`（关键提示）
  5. 实现 `generate_compact()` → 生成 `lesson.compact.md`（<500 token 概念卡）
  6. 实现 `not_proven.md` 和 `misconception.md` 分离输出
  7. 每篇 lesson 必须包含 TL;DR / What Changed / Why / Walkthrough / Claims / Concepts / Misconceptions / Not Proven / Quiz / Sources
- **验收标准**: `ahadiff learn HEAD~1..HEAD` 生成 `runs/<run_id>/lesson/` 下的 full/hint/compact 三个文件

### Task 10: Quiz 生成 + SRS 卡片

- **类型**: 后端（Codex 实现）
- **文件范围**:
  - `src/ahadiff/quiz/generator.py`
  - `src/ahadiff/quiz/schemas.py`
  - `src/ahadiff/quiz/cards.py`
  - `prompts/quiz_generate.md`
  - `tests/unit/test_quiz_generator.py`
- **依赖**: Task 9（Lesson）+ Task 8（Claim）
- **实施步骤**:
  1. 定义 `QuizQuestion`, `QuizSet`, `ReviewCard` schema。ReviewCard 必须包含 anchor 元数据：`source_ref`、`path`、`hunk_id`、`hunk_hash`、`symbol`、`change_kind`
  2. 编写 `quiz_generate.md` prompt
  3. 实现 `generate_quiz()` → `quiz.jsonl`（每题含 source_claims / concepts / file:line evidence）
  4. 实现 `generate_cards()` → `cards.jsonl`（SRS 复习卡，每张 <500 token）
  5. 实现 `ahadiff quiz <run_id>` CLI 子命令（交互式答题）
  6. **Quiz staleness 惰性检测**（Anki 无此能力，AhaDiff 创新点）：`CardState = active | stale | archived`。当 `ahadiff review` 或 `ahadiff quiz` 取卡时，用当前 HEAD 重新解析 card 的 anchor（path + hunk_hash + symbol）。解析失败 → 标记 `stale` + `stale_reason`（file_deleted/symbol_removed/line_drifted），移出正常 due 队列，CLI 提示 `ahadiff regenerate --only quiz <run_id>` 或 `ahadiff card archive <card_id>`。rename/move 场景优先用 symbol 判定，path 失效但 symbol 可解析时判为 `moved` 而非 stale。非 git 输入（patch/compare）标记 `staleness_unknown`，不误报
- **验收标准**: `ahadiff quiz <run_id>` 能做题，每题可回链到 source_claims 和 file:line；stale card 不更新 ease/interval

---

## 第五段：score + verifier hard gates + results.tsv

### Task 11: 评估体系（Evaluation Bundle — 整体 immutable）

- **类型**: 后端（Codex 实现）
- **文件范围**:
  - `src/ahadiff/eval/evaluator.py`（**evaluation bundle 成员，整体 IMMUTABLE**）
  - `src/ahadiff/eval/rubric.py`（**evaluation bundle 成员**）
  - `src/ahadiff/eval/gates.py`（**evaluation bundle 成员**）
  - `src/ahadiff/eval/deterministic.py`（**evaluation bundle 成员**）
  - `evals/rubric.yaml`（**evaluation bundle 成员**）
  - `tests/unit/test_evaluator.py`
  - `tests/unit/test_gates.py`
- **依赖**: Task 0（Schema Freeze）+ Task 7（LLM Provider）+ Task 8（Claim）
- **实施步骤**:
  1. 实现 8 维 rubric 评分（accuracy/evidence/diff_coverage/learnability/quiz_transfer/spec_alignment/conciseness/safety_privacy = 100 分）
  2. 实现硬门禁：Accuracy<14 FAIL, Evidence<12 FAIL, contradicted claims FAIL, secret leak FAIL, injection unresolved FAIL
  3. 实现 PASS(≥80) / CAUTION(60-79) / FAIL(<60) verdict 计算
  4. 实现机械化打分（R10）：evidence 从 claims.jsonl 统计 verified/weak 比例；safety_privacy 从 redaction_report.json 统计
  5. 生成 `score.json`（8 维明细 + verdict + hard_gates + weakest_dim + `eval_bundle_version` + `degraded_flags`）
  6. 跨模型强制：生成用大模型，评估用小模型
  7. **Evaluation bundle 整体 immutable**：`evaluator.py` + `rubric.py` + `rubric.yaml` + `gates.py` + `deterministic.py` 共 5 文件的联合 hash 为 `eval_bundle_version`。任一文件变更视为新评估版本，需更新 `rubric_version`，自动触发 VCR cassette 失效，并在 results 中记录新版本号。v0.1 期间允许迭代但必须版本化
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
  1. **写入顺序**：先写 review.sqlite `result_events`（有事务保护），成功后 append results.tsv。TSV 仅作为人类可读的 audit trail，**review.sqlite 为唯一真相源**。TSV 写入失败仅 warn，不阻塞主流程
  2. results.tsv 11 列 append-only（timestamp/run_id/source_ref/base_ref/prompt_version/rubric_version/overall/verdict/status/weakest_dim/note_json）。`source_ref` 为当前评估的来源标识（git 场景为 commit SHA，patch 场景为文件 hash，compare 场景为路径对 hash），`base_ref` 为 ratchet 比较的基线标识（首次 baseline 时为空）。Phase 2.5 rewrite 时 note_json 字段记录 `{"phase25": true, "worktree_path": "<path>"}`
  3. `result_events` 主键为 `event_id`（UUID v7，全局唯一），唯一索引 `(run_id, event_type, timestamp)`，二级索引 `(source_ref, timestamp DESC)` + `(verdict, status)` + `(weakest_dimension, timestamp DESC)`。同一 run_id 可有多行事件（如 keep → targeted_verify → keep_final）
  4. 实现 `append_result()` 的幂等保证：写入前检查 `event_id` 是否已存在，存在则跳过
  5. 提供 `ahadiff export-results` 从 review.sqlite 重建 results.tsv
  6. status 枚举化（从 Task 0 contracts 导入）：`baseline | keep | discard | rollback | crash | targeted_verify | keep_final | phase25_rewrite`
  7. 实现 ratchet 决策逻辑：score 提升且 hard gate 全过 → keep（cherry-pick 回主分支）；否则 → discard（删除 worktree）。降级 run（`degraded_flags` 非空）的 ratchet 比较需标记 `ratchet_note=degraded_comparison`，不直接丢弃
  8. 实现 Phase 2.5 检测：连续 2 个优化目标在首轮即 discard → 触发 structural rewrite
  9. 简洁性准则：0.001 分提升 + 20 行 hacky prompt → 不值得
  10. 实现 PID lockfile 检查（复用 Task 5 的 `.ahadiff/ahadiff.lock`）：ratchet 写入前验证锁持有
- **验收标准**: review.sqlite result_events 正确写入，ratchet keep/discard/crash 三路径单测全绿；`ahadiff export-results` 重建的 TSV 与直接 append 的 TSV 一致

---

## 第六段：Warm HTML viewer

### Task 13: Jinja2 Viewer 基础架构

- **类型**: 前端（Claude 实现，Gemini 评审）
- **文件范围**:
  - `src/ahadiff/viewer/builder.py`
  - `src/ahadiff/viewer/data_bundle.py`
  - `viewer/templates/base.html`
  - `viewer/templates/layouts/app.html`
  - `viewer/templates/partials/_sidebar.html`
  - `viewer/templates/partials/_topbar.html`
  - `viewer/templates/components/_badge.html`
  - `viewer/templates/components/_rubric_bar.html`
  - `viewer/templates/components/_diff_row.html`
  - `viewer/static/style.css`
- **依赖**: Task 9（Lesson）+ Task 11（Score）+ Task 12（Ratchet History，只读依赖 — data_bundle 含 ratchet_history 字段）
- **实施步骤**:
  1. 从 Warm v6 HTML 原型提取 CSS 变量和布局结构
  2. 实现 Jinja2 五层模板架构（base → layouts → partials → components → pages）
  3. 实现 `data_bundle.py`：构建 `<script id="aha-data" type="application/json">` 注入的 JSON
  4. data_bundle schema：context(run_id/source_ref/source_kind/capability_level/theme/**locale**) + verdict(overall/status) + rubric_scores + claims + lesson + ratchet_history
  5. 实现 `_rubric_bar.html` 组件：自动根据 score/max 映射 PASS/CAUTION/FAIL 语义色（P1 from Gemini）
  6. 实现 `data_bundle.py` 数据裁剪：ratchet_history 仅保留 score 趋势 + run_id，丢弃废弃版本的全量 payload；diff 行数超过 soft_limit (500行) 时启用折叠截断；hard_limit 2000 行时截断并附注 `[truncated: N lines omitted]`，确保单页 HTML 不超过 2MB
  7. 确保 `file://` 打开兼容（所有资源内联，无 CDN）
  8. 移除外部字体依赖和硬编码 demo 数据，转向 System Font Stack（`system-ui, -apple-system, 'Segoe UI', 'PingFang SC', 'Noto Sans SC', 'Microsoft YaHei', 'Sarasa Gothic SC', sans-serif`）确保中英文覆盖（经 Codex 交叉审查确认纯 system-ui 中文覆盖不足）
  9. 实现 i18n 基础：`viewer/i18n/loader.py` JSON catalog loader + Jinja2 `_()` 全局翻译函数 + `<html lang="{{ locale }}">`
  10. Topbar 右侧添加语言切换按钮（zh/EN）+ 环境探针标识（Static/Serve badge）
- **验收标准**:
  - `ahadiff learn HEAD~1..HEAD --open` 打开本地 HTML，视觉接近 Warm v6 原型
  - data_bundle 裁剪：>500 行 diff 启用折叠，>2000 行截断，单页 HTML ≤ 2MB
  - 无障碍基线：所有可交互元素有 `tabindex="0"` 或语义 HTML（`<button>`），焦点可见（`:focus-visible`），ARIA `role` 标注完整
- **Review**: Claude 实现后 → Gemini(gemini-3.1-pro-preview) + Codex 交叉 review

### Task 14: Viewer 核心页面（v0.1 必须的 4 页）

- **类型**: 前端（Claude 实现，Gemini 评审）
- **文件范围**:
  - `viewer/templates/pages/dashboard.html`（Runs Dashboard）
  - `viewer/templates/pages/lesson_reader.html`（Lesson Reader）
  - `viewer/templates/pages/diff_viewer.html`（Diff + Evidence Viewer + Claim Inspector）
  - `viewer/templates/pages/ratchet_lab.html`（Ratchet Lab）
  - `viewer/templates/partials/_claim_inspector.html`
- **依赖**: Task 13（Viewer 基础）
- **实施步骤**:
  1. **Runs Dashboard**: 显示所有 run 的 verdict/score/时间线
  2. **Lesson Reader**: 渲染 lesson.full.md + 右栏 Claims/Evidence/Quiz 状态，支持 full/hint/compact 切换
  3. **Diff + Evidence Viewer**: 点击 diff 行 → 高亮相关 claim；点击 claim → 滚动到 source hunk（核心交互）
  4. **Ratchet Lab**: score before/after、weakest dimension、keep/discard 历史、results.tsv 可视化
  5. Claim Inspector 侧边栏：verified(绿 `#2F6F4F`)/weak(黄 `#B4791F`)/not_proven(灰 `#6B6B6B`)/contradicted(红 `#A33D2B`)/rejected(紫 `#7B5EA7`) 五态色彩标识
  6. 移动端：Claim Inspector 降级为 Drawer 浮层（P2 from Gemini）
  7. 打印样式：保留证据链，隐藏 UI chrome
  8. **Viewer 双模式声明**：前端交互按钮（如 Mark wrong/Good/Hard）的行为通过 `data-mode` 属性区分：(a) 在 `ahadiff serve` 模式下直接调用后端 API；(b) 在 `file://` 静态模式下显示可复制的 CLI 命令提示（如 `ahadiff mark wrong c020`）。v0.1 同时实现 (a) 和 (b)，通过 Progressive Enhancement 自动切换。serve 后端的完整规格见评估报告 Task 14.5 段落（`.claude/team-plan/ahadiff-v01-comprehensive-evaluation-research.md`）。
- **验收标准**: 4 个页面在 375px/768px/1024px/1440px 四个视口正常显示
- **Review**: Gemini(gemini-3.1-pro-preview) 评审

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
  1. 创建 `review.sqlite` schema（**启用 WAL mode + busy_timeout=5000**）：`schema_version`(整数版本号，每次 migration 递增)、`cards`(id/concept/run_id/due_date/interval/ease/reps)、`result_events`(物理事件表，SQLite 为唯一真相源)、`learning_signals`(用户行为日志)。schema_version 嵌入 DB，不匹配时通过顺序 SQL migration 自动升级
  2. 实现 SM-2 SRS 调度算法
  3. 实现 `ahadiff review` CLI：展示 due cards，记录答题结果
  4. 实现 `ahadiff mark <claim_id> wrong` CLI：用户标记 claim 错误 → 写入 learning-signal.jsonl
  5. 实现 `results.tsv → result_events` 入库契约：
     - `result_events` 是多行事件表，同一 run_id 可有多行（如 keep → targeted_verify → keep_final）。主键为 `event_id`（UUID v7，全局唯一），`run_id`/`event_type`/`timestamp` 为二级索引
     - `result_events` 是**物理表**（非视图），schema 与 results.tsv 列一一对应 + `event_id` + `eval_bundle_version`
     - **写入责任**归属 `eval/results.py`（Task 12）：每次 `append_result()` 时同步调用 `review/database.py` 的 `sync_result_event()` 写入 SQLite，写入前检查 `event_id` 幂等
     - 字段映射：results.tsv 的 `weakest_dim` → SQLite 的 `weakest_dim`（统一用短名）
     - **写入顺序**：先写 SQLite（有事务保护），成功后 append TSV。TSV 仅作为人类可读的 audit trail，SQLite 为唯一真相源。TSV 写入失败仅 warn，不阻塞主流程。提供 `ahadiff export-results` 从 SQLite 重建 TSV
  6. 实现 `targeted_verify → keep_final` 升级规则：
     - `ahadiff improve` 中 targeted verification 通过后 status=`targeted_verify`
     - 全 8 维 recheck 通过后由 `ahadiff improve --finalize <run_id>` 升级为 `keep_final`
     - 升级时写入新 result_event 行（status=keep_final），不修改原行
     - 升级失败（全 8 维 recheck 分数下降）则 status 保持 `targeted_verify`，不回滚
  7. 实现 `ahadiff regenerate --only quiz <run_id>` CLI：只重新生成 quiz，不重跑 lesson
  8. 索引：`event_id` 主键, `(run_id, event_type, timestamp)` 唯一索引, `(source_ref, timestamp DESC)`, `(prompt_version, rubric_version)`, `(verdict, status)`, `(weakest_dim, timestamp DESC)`
  9. 实现 `ahadiff db upgrade`：每个 migration 脚本在 `BEGIN EXCLUSIVE ... COMMIT` 事务中执行，失败时自动回滚到备份。升级前自动生成一致性备份（使用 SQLite backup API 或 `VACUUM INTO`，**不要直接 cp**）
  10. 实现 `ahadiff db backup` / `ahadiff db restore <backup_path>`：手动备份/恢复
  11. **取消 TSV 无损 repair 承诺**：`ahadiff db repair` 更名为 `ahadiff db import-results --lossy`，仅作为最后手段，显式声明为有损导入（合成 event_id，event_type 标记为 `imported_from_tsv`）。默认隐藏，需 `--i-understand-this-is-lossy` flag
  12. 实现 `ahadiff db check`：验证 SQLite schema_version 与期望一致、WAL 完整性、event_id 唯一性
- **验收标准**: `ahadiff review` 显示 due cards，wrong concepts 写入 learning-signal.jsonl；upgrade 前有 .bak 备份；migration 失败自动回滚

---

## 第八段：improve loop + targeted verification + Phase 2.5

### Task 16: Improve Loop 核心

- **类型**: 后端（Codex 实现）
- **文件范围**:
  - `src/ahadiff/improve/loop.py`
  - `src/ahadiff/improve/program.py`
  - `src/ahadiff/improve/targeted.py`
  - `src/ahadiff/improve/rewrite.py`
  - `prompts/improve_program.md`
  - `tests/unit/test_improve_loop.py`
- **依赖**: Task 11（Evaluator）+ Task 12（Ratchet）+ Task 15（Review SQLite）
- **实施步骤**:
  1. 实现 `improve_program.md`（自然语言状态机，人类写，agent 解释执行）
  2. 实现 `ahadiff improve --suite local --rounds N` CLI
  3. 可写边界严格约束：**只允许改 `prompts/*.md`**，禁止改 evaluator.py/rubric.yaml/viewer 模板/test fixtures/source code
  4. 实现 weakest-dimension-first 选择（从 review.sqlite.result_events 查询最近记录）
  5. 实现 prompt versioning：`prompt_version = prompts/ 目录的 tree hash 前 7 位`
  6. 简洁性准则写入 improve_program.md
  7. **Improve 隔离策略（统一 worktree）**：常规 improve loop 和 Phase 2.5 均在 `git worktree add` 创建的临时 worktree 中执行，不触碰用户主分支工作区。keep 时从 worktree cherry-pick 回主分支；discard 时删除 worktree。cherry-pick 冲突时自动 abort 并保持 worktree 状态，输出冲突文件列表供人工解决，不强制覆盖主分支。improve loop 启动前检查主分支 `prompts/` 是否有未提交修改，有则提前警告用户。
  8. 禁止并发 improve：复用 PID lockfile（`.ahadiff/ahadiff.lock`），第二个 improve 实例被拒绝
- **验收标准**: `ahadiff improve --suite local --rounds 6` 跑完，results.tsv 正确追加 6 行

### Task 17: Targeted Verification + Phase 2.5

- **类型**: 后端（Codex 实现）
- **文件范围**:
  - `src/ahadiff/improve/targeted.py`（与 Task 16 共享）
  - `src/ahadiff/improve/rewrite.py`（与 Task 16 共享）
  - `tests/unit/test_targeted_verify.py`
  - `tests/unit/test_phase25.py`
- **依赖**: Task 16（Improve Loop）
- **实施步骤**:
  1. 实现 Targeted Verification（R11）：improve 后不重跑全 8 维，只验证 **目标维度 + accuracy + evidence + safety_privacy**（4 维）
  2. 通过则 status=`targeted_verify`，最终确认后升级为 `keep_final`
  3. 实现 Phase 2.5 structural rewrite：连续 2 个优化目标在首轮即 discard → 在新 worktree 中从头重写 → 评估 → 更好则 cherry-pick 回主分支，否则删除 worktree。**Phase 2.5 最多触发 1 次/session**（设置 `phase25_attempted=true` 标志，防止无限重写循环）
  4. Phase 2.5 触发时 status=`phase25_rewrite`（结构化枚举，非自由文本）。note 字段记录 `stash_ref=<ref>;trigger_reason=<consecutive_discard_count>`。最终结果写入 results.tsv，status=`keep` 或 `discard`，note 前缀 `PHASE25:`
- **验收标准**: targeted verification 降低 ~50% token 消耗；Phase 2.5 在连续卡住时正确触发

### Task 18: Benchmark Suite（本地版）

- **类型**: 后端（Codex 实现）
- **文件范围**:
  - `benchmarks/` 目录
  - `src/ahadiff/eval/benchmark.py`
  - `tests/eval/test_benchmark.py`
- **依赖**: Task 11（Evaluator）
- **实施步骤**:
  1. 构建 10 份 pinned benchmark diff：
     - **Python 主套件**（7 份）：全功能验证（AST + regex + section_header）
     - **Non-Python 降级套件**（3 份，TypeScript/Rust/Go 各 1）：仅验证 regex + section_header 降级路径
     - 两套件独立出 recall/precision 报告，不混成单一基线
     - Non-Python 套件的期望 recall 显式低于 Python 套件（标注 `degraded=true`）
  2. 每份含：`diff.patch` + `ground_truth.md` + `qa_probe.jsonl` + `expected_concepts.json`
  3. 实现 `ahadiff benchmark --suite local` CLI
  4. 输出 benchmark report：mean score / claim verification rate / 各维度均值
- **验收标准**: `ahadiff benchmark --suite local` 跑通 10 份 diff，输出结构化报告
- **VCR cassette 管理（双层版本策略）**：
  - **run 级**：`prompt_version = tree hash(prompts/)` 不变，用于 results/ratchet 一致性
  - **cassette 级**：`prompt_fingerprint = hash(top_level_prompt_file + declared_includes + schema_version)`。每个 LLM 调用按 `prompt_fingerprint + model_id + rubric_version + output_lang` 四元组命名 cassette 文件。修改 `lesson_generate.md` 只失效 lesson 相关 cassette，不影响 quiz/claim cassette
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
  - `src/ahadiff/install/codex.py`（复用于 amp/jules；Junie 作为 JetBrains 插件共享 AGENTS.md，无独立 install 命令）
  - `src/ahadiff/install/gemini.py`
  - `src/ahadiff/install/opencode.py`
  - `src/ahadiff/install/cursor.py`
  - `src/ahadiff/install/copilot.py`
  - `src/ahadiff/install/windsurf.py`
  - `src/ahadiff/install/cline.py`
  - `src/ahadiff/install/aider.py`
  - `src/ahadiff/install/hooks.py`
  - `src/ahadiff/install/templates/*.j2`
  - `src/ahadiff/cli.py`（新增 install/uninstall 子命令）
  - `tests/unit/test_install.py`
- **依赖**: Task 1（工程骨架）
- **实施步骤**:
  1. 实现 `InstallTarget` protocol：`detect() → bool`, `preview() → str`, `write() → list[Path]`, `uninstall() → list[Path]`
  2. 实现 11 个 target：claude / codex / gemini / opencode / cursor / copilot / windsurf / cline / amp / aider / jules
     其中 AGENTS.md 系（codex/opencode/amp/jules）共享模板
  3. 实现 Git hooks：post-commit（非阻塞提示）、pre-push（未学习 diff 警告）
  4. 实现 `--detect` 自动检测已安装工具
  5. 实现 `--dry-run` 预览、`--force` 覆盖、`uninstall` 清理
  6. 实现 safe merge 规则：检测目标文件是否已存在用户内容，存在则追加 section 而非覆盖；冲突时 diff 展示并询问
  7. 所有配置通过 Jinja2 模板化生成
  8. 默认不改用户全局配置，不默认启用阻断式 hook
- **验收标准**: 11 个 target + hooks 的 `--dry-run` 全部正确输出将写入的文件列表
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
  1. Layer 1 verify-only（默认，无需密钥）：校验已存在 artifacts
  2. Layer 2 generate-on-CI（显式 opt-in，需 `AHADIFF_API_KEY`）：PR push 时生成 lesson
  3. 实现 `ahadiff install github-action [--layer2]` CLI
- **验收标准**: 生成的 workflow YAML 语法正确，`ahadiff verify --ci` 可在 CI 环境运行

---

## 文件冲突检查

⚠️ 基本隔离，存在以下已知共享：
- Task 19 与 Task 1 共享 `cli.py`（Task 1 已完成，串行无冲突）
- Task 16 与 Task 17 共享 `improve/targeted.py` 和 `improve/rewrite.py`（设计为串行）
- Task 19 与 Task 20 共享 `install/templates/` 目录（通配符重叠，但文件名不同）

| Task | 主要文件范围 |
|------|------------|
| Task 9 | `lesson/*`, `prompts/lesson_*.md` |
| Task 10 | `quiz/*`, `prompts/quiz_*.md` |
| Task 11 | `eval/evaluator.py`, `eval/rubric.py`, `eval/gates.py`, `evals/rubric.yaml` |
| Task 12 | `eval/ratchet.py`, `eval/results.py` |
| Task 13 | `viewer/builder.py`, `viewer/data_bundle.py`, `viewer/templates/{base,layouts,partials,components}` |
| Task 14 | `viewer/templates/pages/*` |
| Task 15 | `review/*` |
| Task 16 | `improve/loop.py`, `improve/program.py`, `prompts/improve_program.md` |
| Task 17 | `improve/targeted.py`, `improve/rewrite.py` |
| Task 18 | `benchmarks/*`, `eval/benchmark.py` |
| Task 19 | `install/*`, `cli.py`（新增子命令） |
| Task 20 | `install/github_action.py`, `install/templates/*.yml.j2` |

**注意**：Task 19 需要修改 `cli.py`（与 Task 1 共享），但 Task 1 已完成，不构成并行冲突。

## 并行分组

```
Layer 4 (并行):  Task 9 (依赖 Layer 3)
                 Task 11 (可与 Task 9 并行，仅依赖 Task 7)
   ↓
Layer 5 (串行+并行):
                 Task 10 (依赖 Task 9，串行)
                 Task 12 (依赖 Task 11，与 Task 10 并行)
                 Task 13 (依赖 Task 9 + Task 11，与 Task 10/12 并行)
   ↓
Layer 6 (串行):  Task 14 (依赖 Task 13，串行)
                 Task 15 (依赖 Task 10 + Task 12，与 Task 14 并行)
   ↓
Layer 7 (串行):  Task 16 (依赖 Task 11 + Task 12 + Task 15)
   ↓             Task 17 (依赖 Task 16，串行)
                 Task 18 (依赖 Task 11，可与 Task 16 并行)
   ↓
Layer 8 (串行):  Task 19 (依赖 CLI 接口冻结：Task 9+10+11+15+16)
                 Task 20 (依赖 Task 19，串行)
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
  - **存储**：repo 级 `.ahadiff/concepts.jsonl`，append-only 日志
  - **每条记录**：`{concept, source_ref, branch_hint, introduced_by_run, updated_by_runs[], related_claims[], file_refs[]}`
  - **读取时 branch 过滤**：`load_visible_concepts(head_ref)` 只返回 `source_ref` 是当前 HEAD ancestor 的记录（`git merge-base --is-ancestor`）；不可达概念保留在日志但默认隐藏
  - **merge 语义**：feature-A 合并到 main 后，若原 commit 仍可达，概念自动重新可见；squash/cherry-pick 导致原 SHA 不可达时为已知限制，等待后续 run 再次引入
  - **去重**：`append_concepts()` 时按 concept 名称（normalized: lowercase + strip）检查已存在，存在则合并 `updated_by_runs` 和 `file_refs`
  - **非 git 输入**：概念仅在 run-local 视图展示，不进入全局 concepts
  - **实现文件**：`src/ahadiff/wiki/concepts.py`（~120-180 行）
- Claim Inspector 独立页面 → 已合并到 Diff+Evidence Viewer 侧边栏
- Spec Alignment 页面 → v0.2
- Benchmark Transparency 页面 → v0.2
- Agent Skill Hub viewer 页面 → v0.2
- public benchmark suite → v0.2（v0.1 只做 local）
- `--level beginner/intermediate/senior` → v0.2
- `git show` / PR patch 输入 → v0.2
- `--staged` 已纳入 v0.1（`git diff --cached`，实现简单，与 Blueprint 一致）

## 第十段：i18n 全链路国际化（新增）

> 依赖：Task 0（Schema Freeze）+ 各层 Task 并行集成
> 估时：~3.75 天（可与 Layer 4-8 并行）

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
- **验收标准**: `resolve_locale()` 在 CLI/serve/static 三种模式下都返回正确 locale

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

### Task i18n-3: Jinja2 模板 i18n

- **类型**: 前端（Claude 实现，Gemini 评审）
- **文件范围**: `viewer/templates/**` 所有模板文件
- **依赖**: Task i18n-1 + Task 13（Viewer 基础架构存在后才能改模板）
- **实施步骤**:
  1. 在 `viewer/templates/base.html` 注入 `_()` 全局翻译函数
  2. 所有硬编码中文/英文文案替换为 `{{ _("Nav.dashboard") }}` 调用
  3. `<html lang="{{ locale }}">`
  4. Static 模式：`_()` 在构建时解析，语言烘焙进 HTML
  5. Serve 模式：`_()` 在请求时解析，读 cookie `ahadiff_lang`
  6. 数字/日期格式按 locale 格式化
- **验收标准**: 同一页面在 zh-CN 和 en 下所有文案正确切换

### Task i18n-4: 前端语言切换 UI

- **类型**: 前端（Claude 实现，Gemini 评审）
- **文件范围**:
  - `viewer/templates/partials/_topbar.html` — 语言切换按钮
  - `viewer/static/style.css` — 按钮样式
  - `src/ahadiff/viewer/serve_app.py` — API endpoint
- **依赖**: Task i18n-3 + Task 14（Viewer 页面存在）+ Task 14.5（Serve 存在）
- **实施步骤**:
  1. Topbar 右侧添加 zh/EN 切换按钮（紧邻主题切换按钮）
  2. 点击后：Serve 模式写 cookie `ahadiff_lang` + 页面重载；Static 模式 toggle 降级为 disabled 状态 + tooltip "运行 `ahadiff serve` 以切换语言，或 `ahadiff learn --lang en` 重新生成"（**不嵌入双语 JSON，保持单语烘焙**，经 Codex 交叉审查确认）
  3. Serve API: `GET /api/locale` 返回当前 locale，`PUT /api/locale` 设置 locale
  4. 按钮样式：当前语言高亮，非当前语言降低不透明度
- **验收标准**: 在 serve 模式下点击 zh/EN 按钮后页面立即切换语言

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
  1. cassette key 从三元组扩展为四元组：`prompt_version + model_id + rubric_version + output_lang`
  2. 语言变更自动失效对应 cassette
  3. 测试：同一 diff 在 en/zh-CN 下生成不同 cassette
- **验收标准**: `output_lang` 变更时仅失效对应语言的 cassette，不影响其他语言

---

## i18n Task 依赖图

```
Task 0 (Schema Freeze)
  └─> Task i18n-0 (i18n Schema)
        ├─> Task i18n-1 (JSON Catalog)
        │     ├─> Task i18n-3 (Jinja2 模板 i18n) ──> Task i18n-4 (语言切换 UI)
        │     └─> Task i18n-5 (CLI 语言)
        └─> Task i18n-2 (Prompt 语言指令) ──> Task i18n-6 (VCR Key 扩展)
```

## 预计时间（修订）

- Layer 4: ~2 天（Lesson + Quiz + Evaluator 并行）
- Layer 5: ~2 天（Ratchet + Viewer 并行）
- Layer 6: ~1 天（Review）
- Layer 7: ~2 天（Improve + Targeted + Benchmark 并行）
- Layer 8: ~1 天（Install + GitHub Action 并行）
- **i18n: ~3.75 天（可与 Layer 4-8 并行，不增加关键路径）**

**总计：~8 天**（主线）+ i18n 并行，加上 Layer 1-3 的 ~3 天 = **v0.1 完整开发周期 ~11-12 天**
