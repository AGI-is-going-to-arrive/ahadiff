# AhaDiff v0.1 设计方案 — 三模型交叉审查报告

> 审查日期：2026-04-20
> 审查模型：**Codex CLI**（后端工程） + **Gemini CLI** (`gemini-3.1-pro-preview`，前端/UX） + **Claude**（架构/编排）
> 审查范围：6 份核心设计文档 + UI 原型 + 竞品源码交叉验证
> 方法论：三模型独立审查 → 去重收敛 → 人工校正 → 分级综合

---

## ⚠️ 校正说明

原始审查中 Codex + Claude 独立将 **git ratchet 操作**标记为 Critical（"销毁用户未提交修改"）。经人工校正，此发现**严重性被高估**：

AhaDiff **不修改用户源码**。核心定位是 *读取 git diff → 生成学习笔记*：
- `ahadiff learn`：**只读**用户 git diff，产物写入 `.ahadiff/` 目录
- `ahadiff improve`：可写边界严格限于 `prompts/*.md`（AhaDiff 自身的 prompt 模板），**禁止改** evaluator/viewer/test/source code
- ratchet 的 keep/discard 对象是 **prompt 模板的改进版本**，不是用户代码

因此 `git reset --hard` 在 improve loop 中回滚的是 AhaDiff 自身的 prompt 文件改动，而非用户的工作区。此问题从 🔴 Critical **降级为** 🟡 Warning（仅需确保 improve 在独立 branch/worktree 执行，不影响用户主分支）。

---

## 审查报告

### 🔴 Critical (6 issues) — 必须修复

#### C1. Claim 状态枚举已漂移 [Codex+Claude 独立发现]
- **文件**: `CLAUDE.md:46`, `kickoff.md:244-245`
- **问题**: 顶层设计定义 **4 态**（verified/weak/not_proven/contradicted），但 Task 8 验收引入 `rejected_contradicted`（第 5 态），`diff-input-expansion.md` 引入 `non_ratcheted`。核心状态机在设计阶段已不一致，下游 score/viewer/quiz/review 无法稳定消费。
- **修复建议**:
  - [ ] 冻结 `ClaimStatus` 为 5 态：`verified | weak | not_proven | contradicted | rejected`
  - [ ] 拆分 `rejected_contradicted` 为 `status=rejected` + `reason_code=file_not_in_patch`
  - [ ] `non_ratcheted` 属于 `RunStatus`，不混入 `ClaimStatus`
  - [ ] 在 `claims/schema.py` 中用 `Pydantic Literal` 冻结

#### C2. 8 维 rubric 权重双版本未收敛 [Codex+Claude 独立发现]
- **文件**: `borrow-points-decision.md:196-205`, `CLAUDE.md`, `kickoff.md:33`
- **问题**: 仓内存在**两组权重**：
  - 版本 A（旧）: evidence=15, diff_coverage=15, safety=7, hard gate Accuracy<15
  - 版本 B（新）: evidence=18, diff_coverage=14, safety=6, hard gate Accuracy<14
  - 维度命名漂移：`quiz_transfer` vs `Recall Transfer`
- **修复建议**:
  - [ ] Task 3 冻结时全仓 grep 确认只保留版本 B（20/18/14/14/10/10/8/6）
  - [ ] 删除所有旧版权重引用，README 和前端设计稿同步更新
  - [ ] evaluator.py 的 immutable 边界扩展为 `evaluator.py + rubric.yaml + gates.py` 版本化单元

#### C3. result_events 表 UNIQUE 索引与 append-only 事件流矛盾 [仅 Codex 发现]
- **文件**: `stages-4-9.md:193`
- **问题**: Task 15 要求 `result_events` 行数与 `results.tsv` 一致 + 每次 `append_result()` 同步落库 + `targeted_verify → keep_final` 追加新事件。但 `run_id` 加了 UNIQUE 索引——append-only 事件流与 UNIQUE 不可共存。
- **修复建议**:
  - [ ] 改为 `(run_id, event_type, timestamp)` 复合主键
  - [ ] 或显式改成 upsert 模型，放弃 append-only 要求

#### C4. results.tsv 只记一个 SHA，ratchet 审计链断裂 [仅 Codex 发现]
- **文件**: `stages-4-9.md:105`
- **问题**: `results.tsv` 只有 `head_sha`，但 ratchet/Phase 2.5 涉及 baseline SHA、候选 SHA、最终 SHA 三个状态。无法回答"评估了哪个版本、丢弃了哪个版本"。
- **修复建议**:
  - [ ] 补足 `base_sha` + `candidate_sha` + `applied_sha`
  - [ ] 或将 TSV 降级为导出视图，主真相源迁到 SQLite 事件流

#### C5. Task 5/6 假并行 [仅 Claude 发现]
- **文件**: `kickoff.md:266`
- **问题**: Task 5（Git Diff Capture）和 Task 6（Diff Parser + Symbol Extract）标为 Layer 2 并行，但 Task 6 的步骤 1 直接消费 Task 5 的 `capture_patch()` 输出。**不能真并行**。
- **修复建议**:
  - [ ] 并行分组改为：Layer 2a = Task 5 + Task 7（真并行）；Layer 2b = Task 6（依赖 Task 5）
  - [ ] 或在 Task 6 提供 fixture `patch.diff` 做开发解耦

#### C6. 静态 HTML 无法实现 Quiz/SRS 交互闭环 [仅 Gemini 发现]
- **文件**: `stages-4-9.md:133`, `CLAUDE.md:49`
- **问题**: 纯 `file://` 模式下，Quiz 按钮（Mark wrong/Good/Hard）和 SRS 状态更新无法写回 SQLite。全局 Dashboard 和 SRS Review 需要跨 Run 聚合数据，与 per-run 静态生成策略冲突。
- **修复建议**:
  - [ ] 明确 Viewer 的**只读边界**：前端按钮仅复制 CLI 命令
  - [ ] 或提供 `ahadiff serve` 启动轻量 ASGI Server 实现真交互
  - [ ] 全局视图（Dashboard/SRS）通过 CLI 执行后全量重建 `index.html`

---

### 🟡 Warning (12 issues) — 建议修复

| # | 发现者 | 维度 | 描述 | 文件 |
|---|--------|------|------|------|
| W1 | Codex | logic | fuzzy match 缺 parent scope/hunk overlap 再确认，同文件重名 helper 误判 | `kickoff.md:233` |
| W2 | Codex | logic | negative evidence scan 对非 Python 太弱，性能/安全 claim 无法由结构存在性推出 | `kickoff.md:237` |
| W3 | Codex | testing | benchmark 混合 Python 和 non-Python 质量基线，regex 降级噪音掩盖真实上限 | `ast-lsp-research.md:94` |
| W4 | Codex | performance | LLM Provider 缺全局 rate limiting、并发预算、circuit breaker | `kickoff.md:204` |
| W5 | Codex | testing | VCR cassette 缺失效策略（prompt 改一字全部失效） | `CLAUDE.md:78` |
| W6 | Codex | data_model | Phase 2.5 遥测挤进自由文本 note，无结构化 phase/mode 字段 | `competitors-research.md:169` |
| W7 | Claude | architecture | Layer 2 Context 承载 4 个正交职责（repo/graphify/privacy/budget）应拆分 | `CLAUDE.md:44` |
| W8 | Claude | data_model | results.tsv + SQLite 双写一致性，TSV append-only 无事务回滚 | `revision.md:34` |
| W9 | Claude | feasibility | 3 天 MVP 估时过于乐观，Task 8 复杂度被低估，建议 5-7 天 | `kickoff.md:293` |
| W10 | Gemini | accessibility | UI 原型自定义元素缺 ARIA Role、tabindex、键盘导航 | `Warm v6.html:472` |
| W11 | Gemini | maintainability | HTML 残留大量内联样式，阻塞 Jinja2 模块化转化 | `Warm v6.html:86` |
| W12 | Codex+Claude | security | ~~原 C1~~ **降级**：ratchet `git reset --hard` 回滚的是 `prompts/*.md` 而非用户代码。但仍建议 improve 在独立 branch/worktree 执行，Phase 2.5 stash 流程增加 crash recovery | `stages-4-9.md:232` |

---

### 🔵 Info (3 issues) — 可选

| # | 发现者 | 描述 |
|---|--------|------|
| I1 | Gemini | JSON 数据注入（`<script type="application/json">`）大 Diff 页面可能体积暴增 |
| I2 | Claude | 七层架构缺显式 Orchestration Layer，编排逻辑散落 cli.py |
| I3 | Claude | Task 19 Install 真正依赖是 CLI 接口冻结，非仅 Task 1 |

---

### ✅ 已通过检查（三模型一致确认）

- ✅ autoresearch 三文件契约映射准确（`prepare.py` → `evaluator.py` 概念改编）
- ✅ Phase 2.5 归因 darwin-skill 有 `SKILL.md:L187` 源码实测支持
- ✅ SkillCompass 6 维→AhaDiff 8 维自研声明经 R3 修订后准确
- ✅ AST/LSP 三层方案（Python ast → tree-sitter → LSP opt-in）与竞品实测一致
- ✅ tree-sitter 是 AI 代码工具事实标准（aider + graphify 验证）
- ✅ 无竞品在核心路径使用 LSP
- ✅ `.ahadiff/runs/<run_id>` 存储 + `commits/<sha>/latest.json` 索引设计合理
- ✅ Deterministic verifier 先行 + LLM judge 后置策略正确
- ✅ 禁止 LiteLLM，统一 `llm/provider.py` 供应链边界清晰
- ✅ Improve loop 可写范围限制 `prompts/*.md` 正确
- ✅ 37 条借鉴点决策经三轮三模型 review 有理有据
- ✅ Warm v6 色彩系统/排版节奏/打印支持/WCAG AA 对比度达标
- ✅ 竞品差异化定位（Diff-Learning/Claim-Evidence/Ratchet/Local-first）论证充分

---

## 收敛分析

| 问题 | Codex | Gemini | Claude | 校正后 | 置信度 |
|------|:-----:|:------:|:------:|:------:|:------:|
| ~~git ratchet 破坏用户代码~~ | ✅ | — | ✅ | **降级 W12**（不涉及用户代码） | ~~极高~~ → 低 |
| Claim 状态枚举漂移 | ✅ | — | ✅ | **C1 维持** | **极高** |
| rubric 权重/immutable 边界 | ✅ | — | ✅ | **C2 维持** | **极高** |
| 双存储一致性 + UNIQUE 冲突 | ✅ | — | ✅ | **C3 维持** | **高** |
| results.tsv SHA 不足 | ✅ | — | — | **C4 维持** | 中 |
| Task 5/6 假并行 | — | — | ✅ | **C5 维持** | 中 |
| 静态 HTML 交互闭环 | — | ✅ | — | **C6 维持** | 中 |

**人工校正要点**：三个模型均将 AhaDiff 类比为 autoresearch（会修改 `train.py` 代码），但忽略了 AhaDiff 的核心差异——**不改用户代码，只改自身 prompt 模板**。ratchet 的 `git reset` 操作范围仅限 `prompts/*.md`，不涉及用户工作区。这体现了多模型审查中**领域知识误移植**的典型盲区：三个模型都从 autoresearch 的"改代码"模式推断风险，而非从 AhaDiff 的"改 prompt"模式评估。

**校正后最高置信问题**：C1 枚举漂移、C2 权重未收敛。

---

## 开发前必须完成的 3 件事

1. **冻结 Claim/Score/Results 的单一 Schema**
   - ClaimStatus 5 态枚举 + Pydantic Literal
   - 8 维权重单一真相源（20/18/14/14/10/10/8/6）
   - results.tsv 补足 base_sha/candidate_sha 或降级为导出视图
   - result_events 表改为 `(run_id, event_type, timestamp)` 复合主键

2. **明确 Viewer 只读边界 + improve 隔离策略**
   - Viewer 是只读展示层，Quiz/SRS 状态变更通过 CLI 命令
   - improve loop 在独立 branch 执行 prompt 迭代，不混入用户主分支
   - Phase 2.5 建议使用 worktree 隔离（保险但非必须——因为只改 prompt 文件）

3. **并行分组和估时修正**
   - Task 5/6 改为串行
   - Task 7 提前到 Layer 1.5
   - MVP 估时从 3 天调整为 5-7 天

---

## 审查元数据

| 模型 | 发现数 | 用时 | Session ID |
|------|--------|------|------------|
| Codex CLI | 5C + 6W | ~8 min | `019da901-7f1a-7071-b78b-08998567008a` |
| Gemini CLI | 2C + 3W + 1I | ~3 min | `bc64a88c-b5aa-41ab-a9de-dda65a18b67d` |
| Claude | 4C + 4W + 2I | ~3 min | (in-process) |
| **去重合计（校正前）** | **7C + 11W + 3I** | — | — |
| **去重合计（校正后）** | **6C + 12W + 3I** | — | C1→W12 降级 |
