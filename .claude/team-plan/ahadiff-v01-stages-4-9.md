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
  8. **三段式撤架降级触发条件**（学习科学补齐）：
     - **自动降级**：`ahadiff review` 展示 lesson 时，根据 SRS 复习阶段选择版本：首次展示=Full，interval≥3天=Hint，interval≥14天=Compact
     - **手动切换**：UI 提供 Full/Hint/Compact 三个标签页，用户可随时手动切换（不受自动规则约束）
     - **Quiz 表现反馈**：若 quiz 答错率>50%，下次 review 自动回退一级（Compact→Hint 或 Hint→Full）
     - 降级选择写入 `ReviewCard.scaffolding_level` 字段（`full|hint|compact`），影响 SRS 调度但不改变 lesson 内容本身
- **验收标准**: `ahadiff learn HEAD~1..HEAD` 生成 `runs/<run_id>/lesson/` 下的 full/hint/compact 三个文件；`ahadiff review` 根据 interval 自动选择展示版本

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
  1. 定义 `QuizQuestion`, `QuizSet`, `ReviewCard` schema。ReviewCard 必须包含 anchor 元数据：`source_ref`、`file_id`（稳定标识，与 EvidenceAnchor 统一）、`display_path`（用户可见路径）、`hunk_id`、`hunk_hash`、`symbol`、`change_kind`。**注意**：`path` 字段已废弃，统一使用 `file_id + display_path` 二元组（与 CC-NEW-3 闭合方案一致）
  2. 编写 `quiz_generate.md` prompt
  3. 实现 `generate_quiz()` → `quiz.jsonl`（每题含 source_claims / concepts / file:line evidence）
  4. 实现 `generate_cards()` → `cards.jsonl`（SRS 复习卡，每张 <500 token）
  5. 实现 `ahadiff quiz <run_id>` CLI 子命令（交互式答题）
  6. **Quiz staleness 惰性检测**（Anki 无此能力，AhaDiff 创新点）：`CardState = active | stale | archived`。当 `ahadiff review` 或 `ahadiff quiz` 取卡时，用当前 HEAD 重新解析 card 的 anchor（`file_id` → 反查当前路径 + hunk_hash + symbol）。解析失败 → 标记 `stale` + `stale_reason`（file_deleted/symbol_removed/line_drifted），移出正常 due 队列，CLI 提示 `ahadiff regenerate --only quiz <run_id>` 或 `ahadiff card archive <card_id>`。rename/move 场景优先用 symbol 判定，path 失效但 symbol 可解析时判为 `moved` 而非 stale。非 git 输入（`patch_file`/`patch_stdin`/`file_compare`）标记 `staleness_unknown`，不误报
  7. **concepts.jsonl 实现**（~120-180 行）：实现 `src/ahadiff/wiki/concepts.py`，包含 `append_concepts(run_id, concepts_list)`、`load_visible_concepts(head_ref)` 函数。存储为 repo 级 `.ahadiff/concepts.jsonl`（append-only 日志格式，允许同一 term_key 多行存在）。每条记录：`{concept, term_key, source_refs[], branch_hint, introduced_by_run, updated_by_runs[], related_claims[], file_refs[]}`。**存储模型：每个 term_key 恰好一行**（upsert 语义）。`append_concepts()` 写入时按 term_key 查找已有行：存在则原地更新该行字段（合并 `updated_by_runs`/`file_refs`，追加 `source_refs[]`）；不存在则追加新行。文件整体保持 JSONL 格式但**每个 term_key 唯一**。**读取时过滤**：`load_visible_concepts(head_ref)` 扫描所有行，检查 `source_refs[]` 中是否有**任一** ref 是当前 HEAD 的 ancestor（`any(is-ancestor)`），有则可见。**non-git 输入守卫**：当 `source_kind` 为 `patch_file`/`patch_stdin`/`file_compare` 时，`source_ref` 为内容 hash 而非 git commit，此时概念仅在 run-local 视图展示（写入 `runs/<run_id>/concepts_local.jsonl`），不进入全局 `concepts.jsonl`
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
  6. 跨模型评估：生产环境生成与评估用不同模型；**开发测试阶段统一 gpt-5.4-mini**（跨模型约束暂时放松），生产环境生成切大模型
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
  6. status 枚举化（从 Task 0 `contracts/event_log.py` 单点导入 `RunStatus`）：`baseline | keep | discard | rollback | crash | targeted_verify | keep_final | phase25_rewrite | non_ratcheted`。**`non_ratcheted` 判定条件**：`has_git_ancestry == false`（即无法通过 `git merge-base` 确认 baseline 关系）。Level 1/2 输入（patch/file_compare）虽然有 `source_ref`（content hash），但没有 git ancestry，因此无法 ratchet 回滚。写入时 status 直接标记为 `non_ratcheted`，不进入 keep/discard 决策。**注意区分**：`has_source_ref`（所有输入都有）≠ `has_git_ancestry`（仅 Level 3 git 输入有）
  7. 实现 ratchet 决策逻辑 + **improve 状态机统一定义**：
     - **learn 链路**（`ahadiff learn`，非 improve）：score 评估后直接写入 `status=baseline`（首次）或 `status=keep`（后续 ratchet 提升）/ `status=discard`（退步）。learn 不涉及 cherry-pick（直接在主分支上运行）
     - **improve 链路**（`ahadiff improve`，在 worktree 中）：
       (a) 评估通过（score 提升 + hard gate 全过）→ 先执行 `git cherry-pick` → 成功后写 `status=targeted_verify`（不是 `keep`）
       (b) cherry-pick 失败（冲突）→ 写 `status=targeted_verify` + `note_json={"cherry_pick_pending": true, "worktree_path": "..."}`，保留 worktree 供人工 resolve
       (c) 评估未通过 → 写 `status=discard`，删除 worktree
       (d) `ahadiff improve --finalize <run_id>` 全 8 维 recheck 通过 → 升级为 `status=keep_final`
     - **边界定义**：`keep` 仅出现在 learn 链路（直接 ratchet 判定）；`targeted_verify → keep_final` 仅出现在 improve 链路。两者不混用。Phase 2.5 最终结果也走 improve 链路：通过写 `targeted_verify`，不通过写 `discard`
     - **禁止**：先写 status 再 cherry-pick（避免状态与 git 不一致）
     - 降级 run（`degraded_flags` 非空）的 ratchet 比较需标记 `ratchet_note=degraded_comparison`，不直接丢弃
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
- **依赖**: Task 0（Schema Freeze）；开发时 API 通过 mock/proxy 解耦（Vite dev server proxy），不硬依赖 Task 14.5（Task 14.5 同属 Stage 4 并行开发）
- **实施步骤**:
  1. 初始化 Vite + React 19 + TypeScript 项目
  2. 以 `AhaDiff Warm v6.html` 为设计参考模板，提取设计 token（颜色、字体、间距）
  3. 实现 Warm 风格 CSS 设计系统（vanilla CSS custom properties + CSS Modules，不用 CSS 框架）
  4. 实现基础 layout：sidebar nav + main content area + responsive breakpoints
  5. 实现 API client：连接 `ahadiff serve` 的 REST API
  6. **i18n 架构（Gemini 审查修正）**：使用 Zustand 原子 store 而非顶层 React Context。`useLocale()` hook 返回当前 locale，`useT()` hook 返回翻译函数。DiffView 等重渲染组件通过 `React.memo` + `useMemo(messages[key])` 隔离，语言切换时仅 re-render 含文案的轻组件（Nav/Sidebar/Footer），不触发 DiffView/EvidencePanel 重建
  7. 实现语言切换 UI + cookie 持久化 + 浏览器检测降级
  8. **防 FOUC 阻塞脚本（Gemini 审查新增）**：在 `index.html` `<head>` 中注入内联 `<script>`（非 defer/async），在 React bundle 加载前读取 `localStorage.getItem('ahadiff_lang')` 和 `localStorage.getItem('ahadiff_theme')` 并设置 `<html lang="..." data-theme="...">`。配合 CSS Variables 实现 0 闪烁。脚本体积 < 500 bytes
  9. 实现 print CSS（@media print）。`break-inside: avoid` 仅作用于 `.claim-card` 和 `<table>` 等小块级元素，不作用于 `<article>` 或长 `<pre>`（避免大面积空白）
  10. 实现 WCAG AA 无障碍：焦点管理、aria-label、键盘导航
  11. 配置 Vite build：`ahadiff serve` 开发时 proxy API，生产时 serve 静态 build
  12. 实现 XSS 防护：所有用户数据渲染用 React 自动 escape，data_bundle 用 DOMPurify
  13. 字体策略：Google Fonts（Newsreader/Inter/JetBrains Mono/Noto Serif SC）+ 系统字体回退链
  14. **DiffView 渲染隔离（性能约束）**：DiffView 组件整体用 `React.memo(DiffView, shallowEqual)` 包裹，props 仅接收 `runId` + `highlightedClaimId`。内部使用虚拟列表（`@tanstack/react-virtual`）渲染 5000+ 行。i18n/theme 切换不传入 DiffView props，通过 CSS Variables + `data-lang` 属性处理静态文案
  15. `<noscript>` 提示：JS 禁用时显示 "AhaDiff requires JavaScript" 友好提示
- **验收标准**: 
  - `cd viewer && npm run build` 成功
  - `ahadiff serve` 启动后自动打开浏览器，显示 Warm 风格首页
  - WCAG AA 合规（axe-core 零 critical）
  - 中英文切换无闪烁、无 FOUC（清空缓存后首次加载验证）
  - DiffView 5000 行渲染 FCP < 500ms（虚拟列表验证）
  - 语言切换时 DiffView 不触发 re-render（React DevTools Profiler 验证）

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
  2. **LessonPage**: 渲染 lesson.full.md + 右栏 Claims/Evidence/Quiz 状态，支持 full/hint/compact 三标签切换（三段式撤架 UI）。**命名统一**：权威枚举为 `full|hint|compact`（v6.html 中的 "Quiz-only" 为旧命名，Task 13 实现时统一为 compact，前端设计手册同步更新）
  3. **DiffViewerPage**: 点击 diff 行 → 高亮相关 claim；点击 claim → 滚动到 source hunk（核心交互）。**移动端双向联动（Gemini Critical 修复 + 二轮验证修正）**：≤768px 时不使用全屏 Sheet/Drawer 展示 Claim 详情。改为：(a) Diff 行号旁显示 Claim Avatar 小圆点（按状态色编码）；(b) 点击后屏幕底部弹出 Bottom Mini-Panel，采用**三段 Snap Points 吸附设计**：默认 25vh（~167px，摘要视图）/ 手指上滑到 50vh（详情视图）/ 继续上滑到 90vh（近全屏，Back 手势返回）。`min-height: min(25vh, 180px)` 确保 iPhone SE 可用；(c) Mini-Panel 内显示 Claim 摘要，50vh 以上显示完整证据链；(d) 从 Mini-Panel 点击 "跳转到代码" 时，收起 Panel 到 25vh + 自动滚动到目标行
  4. **QuizPage**: Quiz 交互（Guided/Recall/Transfer 三类题型），答题结果通过 API 写入后端
  5. **ClaimBadge**: verified(绿 `#2F6F4F`)/weak(黄 `#B4791F`)/not_proven(灰 `#6B6B6B`)/contradicted(红 `#A33D2B`)/rejected(紫 `#7B5EA7`) 五态色彩标识
  6. **EvidencePanel**: file:line 证据链面板，点击跳转到 DiffViewer 对应 hunk
  7. **SRSCard**: 翻牌动画 + Good/Hard/Wrong 按钮，直接调用 `ahadiff serve` API 写入
  8. **ConceptGraph**: 概念图谱（SVG 力导向图 + List fallback for 无障碍）。**大集合聚类（Gemini 审查新增 + 二轮触屏修正）**：节点数>20 时默认按文件路径（File）分组为 Cluster 节点，每个 Cluster 显示文件名 + `+N` 概念数徽标（视觉暗示可展开）；**单击** Cluster 展开细节概念（不用双击——双击在触屏上不可发现且被浏览器缩放拦截）。节点数≤20 时正常展示全部节点。用户可通过 "展开全部/折叠为文件" 按钮切换。触屏长按 Cluster 弹出操作菜单（展开/隐藏/高亮关联 claims）
  9. 移动端：EvidencePanel 在≤768px 使用步骤 3 的 Bottom Mini-Panel 模式（不用全屏 Drawer）
  10. 打印样式：保留证据链，隐藏 UI chrome
- **验收标准**: 
  - 4 个页面在 375px/768px/1024px/1440px 四个视口正常显示
  - 375px 视口点击 Claim Avatar，底部 Mini-Panel 弹出且 Diff 代码仍可滚动查看
  - ConceptGraph 50 节点时渲染流畅（聚类后实际渲染≤20 节点）
  - Ratchet 趋势图在仅 1 次 run 时显示 KPI 卡片（非空坐标轴）
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
  1. 实现 Starlette app 工厂，`bind=127.0.0.1:8765`（**仅绑定回环地址，拒绝外网连接**）
  2. 实现路由鉴权矩阵：
     - 读路由（`GET /api/*`）：无需 token，默认开放
     - 写路由（`POST /api/signals/*`, `PUT /api/locale`）：需 `X-AhaDiff-Token` header
     - token 在 `ahadiff serve` 启动时自动生成，React 前端从 `GET /api/auth/token` 获取（仅限 localhost）
  3. 实现 `Host` + `Origin/Referer` 双校验中间件：只允许 `localhost`/`127.0.0.1`/`[::1]`
  4. 实现 JSON 数据 API：`GET /api/runs`、`GET /api/run/:id`、`GET /api/run/:id/lesson`、`GET /api/run/:id/claims`、`GET /api/run/:id/quiz`、`GET /api/run/:id/diff`、`GET /api/concepts`、`GET /api/ratchet/history`（只读，直接查 review.sqlite）
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
  1. 创建 `review.sqlite` schema（**启用 WAL mode + busy_timeout=5000**）：`schema_version`(整数版本号，每次 migration 递增)、`cards`(id/concept/run_id/due_date/interval/ease/reps)、`result_events`(物理事件表，SQLite 为唯一真相源)、`learning_signals`(用户行为日志)。schema_version 嵌入 DB，不匹配时通过顺序 SQL migration 自动升级
  2. 实现 SM-2 SRS 调度算法
  3. 实现 `ahadiff review` CLI：展示 due cards，记录答题结果
  4. 实现 `ahadiff mark <claim_id> wrong` CLI：用户标记 claim 错误 → 写入 review.sqlite `learning_signals` 表
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
- **验收标准**: `ahadiff review` 显示 due cards，wrong concepts 写入 review.sqlite `learning_signals` 表；upgrade 前有 .bak 备份；migration 失败自动回滚

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
  8. 禁止并发 improve：复用 repo_write_lock（`.ahadiff/ahadiff.lock`，portalocker），第二个 improve 实例被拒绝
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
  4. Phase 2.5 触发时 status=`phase25_rewrite`（结构化枚举，非自由文本）。note 字段记录 `stash_ref=<ref>;trigger_reason=<consecutive_discard_count>`。最终结果写入 results.tsv：通过=`targeted_verify`（走 improve 链路，后续可升级为 `keep_final`），不通过=`discard`，note 前缀 `PHASE25:`。**注意**：Phase 2.5 属于 improve 链路，不使用 `keep` 状态（与 Task 12 step 7 状态机统一定义一致）
- **验收标准**: targeted verification 降低 ~50% token 消耗；Phase 2.5 在连续卡住时正确触发

### Task 18: Benchmark Suite（本地版）

- **类型**: 后端（Codex 实现）
- **文件范围**:
  - `benchmarks/` 目录
  - `src/ahadiff/eval/benchmark.py`
  - `tests/eval/test_benchmark.py`
- **依赖**: Task 11（Evaluator）
- **实施步骤**:
  1. **冻结 `benchmarks/manifest.json`**（数据范围架构新增）：定义 `suite_id`（如 "ahadiff-local-v1"）、`suite_digest`（全部 fixture 的联合 SHA-256）、`visibility`（"private"|"public"）、entries 列表。只有 `suite_digest + eval_bundle_version + model_id` 全匹配时 benchmark 结果才可比
  2. 构建 10 份 pinned benchmark diff：
     - **Python 主套件**（7 份）：全功能验证（AST + regex + section_header）
     - **Non-Python 降级套件**（3 份，TypeScript/Rust/Go 各 1）：仅验证 regex + section_header 降级路径
     - 两套件独立出 recall/precision 报告，不混成单一基线
     - Non-Python 套件的期望 recall 显式低于 Python 套件（标注 `degraded=true`）
  3. 每份含：`diff.patch` + `ground_truth.md` + `qa_probe.jsonl` + `expected_concepts.json`
  4. 实现 `ahadiff benchmark --suite local` CLI
  5. 输出 benchmark report：mean score / claim verification rate / 各维度均值 + `suite_id` + `suite_digest`
- **验收标准**: `ahadiff benchmark --suite local` 跑通 10 份 diff；`benchmarks/manifest.json` 存在且 `suite_digest` 可验证；报告含 suite_id
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
  - `src/ahadiff/install/codex.py`
  - `src/ahadiff/install/gemini.py`
  - `src/ahadiff/install/opencode.py`
  - `src/ahadiff/install/hooks.py`
  - `src/ahadiff/install/templates/*.j2`
  - `src/ahadiff/cli.py`（新增 install/uninstall 子命令）
  - `tests/unit/test_install.py`
- **依赖**: Task 1（工程骨架）
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
  1. 实现 `viewer/src/i18n/I18nProvider.tsx`：React Context 提供 `t()` 翻译函数
  2. 实现 `useTranslation()` hook，组件内调用 `t("Nav.dashboard")` 获取翻译
  3. 所有硬编码中文/英文文案替换为 `t()` 调用
  4. `<html lang={locale}>` 动态设置
  5. 语言切换时通过 Context 触发 re-render，无需页面刷新
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
  2. 点击后：写 cookie `ahadiff_lang` + 通过 React Context 触发 i18n re-render（无需页面刷新）
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
