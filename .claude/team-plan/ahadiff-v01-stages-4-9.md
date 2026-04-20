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
  1. 定义 `QuizQuestion`, `QuizSet`, `ReviewCard` schema
  2. 编写 `quiz_generate.md` prompt
  3. 实现 `generate_quiz()` → `quiz.jsonl`（每题含 source_claims / concepts / file:line evidence）
  4. 实现 `generate_cards()` → `cards.jsonl`（SRS 复习卡，每张 <500 token）
  5. 实现 `ahadiff quiz <run_id>` CLI 子命令（交互式答题）
- **验收标准**: `ahadiff quiz <run_id>` 能做题，每题可回链到 source_claims 和 file:line

---

## 第五段：score + verifier hard gates + results.tsv

### Task 11: 评估体系（evaluator.py immutable）

- **类型**: 后端（Codex 实现）
- **文件范围**:
  - `src/ahadiff/eval/evaluator.py`（**IMMUTABLE after first commit**）
  - `src/ahadiff/eval/rubric.py`
  - `src/ahadiff/eval/gates.py`
  - `src/ahadiff/eval/deterministic.py`
  - `evals/rubric.yaml`
  - `tests/unit/test_evaluator.py`
  - `tests/unit/test_gates.py`
- **依赖**: Task 7（LLM Provider）+ Task 8（Claim）
- **实施步骤**:
  1. 实现 8 维 rubric 评分（accuracy/evidence/diff_coverage/learnability/quiz_transfer/spec_alignment/conciseness/safety_privacy = 100 分）
  2. 实现硬门禁：Accuracy<14 FAIL, Evidence<12 FAIL, contradicted claims FAIL, secret leak FAIL, injection unresolved FAIL
  3. 实现 PASS(≥80) / CAUTION(60-79) / FAIL(<60) verdict 计算
  4. 实现机械化打分（R10）：evidence 从 claims.jsonl 统计 verified/weak 比例；safety_privacy 从 redaction_report.json 统计
  5. 生成 `score.json`（8 维明细 + verdict + hard_gates + weakest_dim）
  6. 跨模型强制：生成用大模型，评估用小模型
  7. `evaluator.py` 首次 commit 后标记为 immutable，后续修改需要 `[rubric-bump]` PR 标签
- **验收标准**: `ahadiff verify <run_id>` 和 `ahadiff score <run_id>` 输出 PASS/CAUTION/FAIL 及最弱维度

### Task 12: results.tsv + Ratchet 机制

- **类型**: 后端（Codex 实现）
- **文件范围**:
  - `src/ahadiff/eval/ratchet.py`
  - `src/ahadiff/eval/results.py`
  - `tests/unit/test_ratchet.py`
  - `tests/unit/test_results.py`
- **依赖**: Task 11（评估体系）
- **实施步骤**:
  1. 实现 10 列 results.tsv append-only 写入（timestamp/run_id/head_sha/prompt_version/rubric_version/overall/verdict/status/weakest_dim/note）
  2. status 枚举化：`baseline | keep | discard | rollback | crash | targeted_verify | keep_final`
  3. 实现 ratchet 决策逻辑：score 提升且 hard gate 全过 → keep；否则 → discard + git reset
  4. 实现 Phase 2.5 检测：连续 2 个优化目标在首轮即 discard → 触发 structural rewrite
  5. 简洁性准则：0.001 分提升 + 20 行 hacky prompt → 不值得
- **验收标准**: results.tsv 正确追加，ratchet keep/discard/crash 三路径单测全绿

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
- **依赖**: Task 9（Lesson）+ Task 11（Score）
- **实施步骤**:
  1. 从 Warm v6 HTML 原型提取 CSS 变量和布局结构
  2. 实现 Jinja2 五层模板架构（base → layouts → partials → components → pages）
  3. 实现 `data_bundle.py`：构建 `<script id="aha-data" type="application/json">` 注入的 JSON
  4. data_bundle schema：context(run_id/head_sha/theme) + verdict(overall/status) + rubric_scores + claims + lesson + ratchet_history
  5. 实现 `_rubric_bar.html` 组件：自动根据 score/max 映射 PASS/CAUTION/FAIL 语义色（P1 from Gemini）
  6. 确保 `file://` 打开兼容（所有资源内联，无 CDN）
  7. 移除外部字体依赖和硬编码 demo 数据
- **验收标准**: `ahadiff learn HEAD~1..HEAD --open` 打开本地 HTML，视觉接近 Warm v6 原型
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
  5. Claim Inspector 侧边栏：verified(绿)/weak(黄)/not_proven(灰)/contradicted(红) 状态标识
  6. 移动端：Claim Inspector 降级为 Drawer 浮层（P2 from Gemini）
  7. 打印样式：保留证据链，隐藏 UI chrome
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
  1. 创建 `review.sqlite` schema：`cards`(id/concept/run_id/due_date/interval/ease/reps)、`result_events`(从 results.tsv 入库的查询视图)、`learning_signals`(用户行为日志)
  2. 实现 SM-2 SRS 调度算法
  3. 实现 `ahadiff review` CLI：展示 due cards，记录答题结果
  4. 实现 `ahadiff mark <claim_id> wrong` CLI：用户标记 claim 错误 → 写入 learning-signal.jsonl
  5. 实现 `results.tsv → result_events` 入库契约：
     - `result_events` 是**物理表**（非视图），schema 与 results.tsv 10 列一一对应
     - **写入责任**归属 `eval/results.py`（Task 12）：每次 `append_result()` 时同步调用 `review/database.py` 的 `sync_result_event()` 写入 SQLite
     - 字段映射：results.tsv 的 `weakest_dim` → SQLite 的 `weakest_dim`（统一用短名）
     - 事务时机：results.tsv 写入成功后立即同步，失败时 results.tsv 回滚
  6. 实现 `targeted_verify → keep_final` 升级规则：
     - `ahadiff improve` 中 targeted verification 通过后 status=`targeted_verify`
     - 全 8 维 recheck 通过后由 `ahadiff improve --finalize <run_id>` 升级为 `keep_final`
     - 升级时写入新 result_event 行（status=keep_final），不修改原行
     - 升级失败（全 8 维 recheck 分数下降）则 status 保持 `targeted_verify`，不回滚
  7. 实现 `ahadiff regenerate --only quiz <run_id>` CLI：只重新生成 quiz，不重跑 lesson
  8. 索引：`(run_id UNIQUE)`, `(head_sha, timestamp DESC)`, `(prompt_version, rubric_version)`, `(verdict, status)`, `(weakest_dim, timestamp DESC)`
- **验收标准**: `ahadiff review` 显示 due cards，wrong concepts 写入 learning-signal.jsonl；`result_events` 与 results.tsv 行数一致

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
  3. 实现 Phase 2.5 structural rewrite：连续 2 个优化目标在首轮即 discard → `git stash` → 从头重写 → 评估 → 更好则采用，否则 `git stash pop`
  4. Phase 2.5 结果写入 results.tsv，status=`keep` 或 `discard`，note 前缀 `PHASE25:`
- **验收标准**: targeted verification 降低 ~50% token 消耗；Phase 2.5 在连续卡住时正确触发

### Task 18: Benchmark Suite（本地版）

- **类型**: 后端（Codex 实现）
- **文件范围**:
  - `benchmarks/` 目录
  - `src/ahadiff/eval/benchmark.py`
  - `tests/eval/test_benchmark.py`
- **依赖**: Task 11（Evaluator）
- **实施步骤**:
  1. 构建 10 份 pinned benchmark diff（覆盖 Python/TypeScript/Rust/Go 等多语言）
  2. 每份含：`diff.patch` + `ground_truth.md` + `qa_probe.jsonl` + `expected_concepts.json`
  3. 实现 `ahadiff benchmark --suite local` CLI
  4. 输出 benchmark report：mean score / claim verification rate / 各维度均值
- **验收标准**: `ahadiff benchmark --suite local` 跑通 10 份 diff，输出结构化报告

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
Layer 8 (串行):  Task 19 (仅依赖 Task 1)
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
- index.md / concepts.jsonl 增量 wiki → v0.2
- Claim Inspector 独立页面 → 已合并到 Diff+Evidence Viewer 侧边栏
- Spec Alignment 页面 → v0.2
- Benchmark Transparency 页面 → v0.2
- Agent Skill Hub viewer 页面 → v0.2
- public benchmark suite → v0.2（v0.1 只做 local）
- `--level beginner/intermediate/senior` → v0.2
- `git show` / PR patch / staged changes 输入 → v0.2（v0.1 只支持 ref range）

## 预计时间

- Layer 4: ~2 天（Lesson + Quiz + Evaluator 并行）
- Layer 5: ~2 天（Ratchet + Viewer 并行）
- Layer 6: ~1 天（Review）
- Layer 7: ~2 天（Improve + Targeted + Benchmark 并行）
- Layer 8: ~1 天（Install + GitHub Action 并行）

**总计：~8 天**，加上 Layer 1-3 的 ~3 天 = **v0.1 完整开发周期 ~11 天**
