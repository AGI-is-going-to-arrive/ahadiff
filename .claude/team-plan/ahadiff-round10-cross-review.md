# AhaDiff 第十轮三模型交叉审查报告

> **审查模型**：Codex CLI 0.122.0 + Gemini CLI 0.38.1 (gemini-3.1-pro-preview) + Claude Opus 4.6 (team-reviewer)
> **审查日期**：2026-04-21
> **前置**：基于 Round 9 审查报告（GO 判定）的深度交叉验证
> **方法**：三模型各覆盖不同维度（共 17 子维度），互不重叠

---

## 一、三模型审查结果汇总

### Gemini 3.1 Pro — 前端/学习科学（5 维度）

| 维度 | 评分 | 关键发现 |
|------|------|---------|
| D1. React 架构稳健性 | 9/10 | ResizeObserver 需 RAF 节流；shallowEqual 需确保 props 为基本类型 |
| D2. 移动端交互 | 8/10 | **[High] 触屏长按操作菜单可发现性极差**，需改为可见图标触发 |
| D3. FSRS 撤架交互 | 9/10 | **[Medium] 偷看惩罚缺失**：手动展开 Full 后答题应封锁 Good 按钮 |
| D4. i18n 全链路 | 7/10 | **[Critical] 语言检测必须先剔除代码块再计算 CJK/Latin 比例** |
| D5. 学习科学 | 7/10 | **[Critical] 必须补 Archive/Suspend Card 机制防 LLM 劣质题** |

**Gemini 判定**：**CONDITIONAL GO**（需修正语言检测算法 + 补 card archive 功能）

### Claude Team-Reviewer — 架构一致性（6 维度）

| 维度 | 评分 | 关键发现 |
|------|------|---------|
| D1. DAG 隐性依赖 | 7/10 | **[High] Task 5 → Task 2 未声明依赖**（Task 5 step 4 调用 redaction_pipeline） |
| D2. 契约交叉引用 | 8/10 | 11 条设计决策全部有 Task 落地；FSRS-6 缺独立决策条目 |
| D3. 枚举一致性 | 9/10 | **[Low] `rollback` RunStatus 无任何 Task 产生**（可能残留） |
| D4. 文件所有权 | 9/10 | 无真正并行写冲突 |
| D5. 验收可测试性 | 7/10 | **[Medium] 3 项验收标准不可自动化**（DiffView FCP/re-render/ConceptGraph 流畅度） |
| D6. Round 9 盲点 | 7/10 | 漏掉 Task 5→Task 2 依赖；Learnability Gate 无独立 Task ID |

**Claude 判定**：**CONDITIONAL GO**（7.8/10，需修复 Task 5 依赖声明）

### Codex CLI 0.122.0 — 后端/数据层（6 维度）

| 维度 | 评分 | 关键发现 |
|------|------|---------|
| D1. Contract 完备性 | 6/10 | **[Critical] result_events/EventLog 契约列集冲突**：Task 0 要求 event_type 列 + 唯一索引，但 Task 15 写"与 results.tsv 一一对应"而 TSV 无 event_type；weakest_dimension/weakest_dim 混用 |
| D2. SQLite 数据模型 | 5/10 | **[High] cards 表缺 hunk_id/hunk_hash/symbol/change_kind anchor 列**（quiz staleness 依赖）；scheduler_preset_id 无外键；**learning_signals 完全没 schema** |
| D3. LLM Provider | 6/10 | **[High] cache key 缺 eval_bundle_version/output_lang/api_family/privacy_mode**，会跨语言跨 adapter 误复用；circuit breaker 粒度不够 |
| D4. Ratchet 状态机 | 7/10 | learn/improve 分轨不死锁；**[Medium] rollback 孤儿态 + Phase 2.5 session 恢复语义不清** |
| D5. 安全模型 | 6/10 | **[Medium] context_bundle 无内容 hash pinning 存在 TOCTOU**；entropy>4.5 会误报 UUID/hash/minified |
| D6. 测试策略 | 5/10 | **[High] VCR 依赖人工 bump rubric_version 而非绑定 eval_bundle_version**；benchmark 仅 10 份 |

**Codex 均分**：**5.8/10**（三模型中最严格）
**Codex 判定**：**CONDITIONAL GO**（不同意 Round 9 的 GO，核心阻断：result_events 契约 + SQLite 关系模型 + cache key）

---

## 二、Round 9 盲点清单（三模型交叉发现）

Round 9 评分 8.2/10 给出 GO 判定。三模型交叉审查发现以下 Round 9 遗漏：

### Critical（3 项）

| ID | 问题 | 发现者 | 修复方案 | 影响 Task |
|----|------|--------|---------|----------|
| **X-C1** | 混合语言检测算法在代码密集场景误判 | Gemini | 检测前用正则剔除 ` ```...``` ` 和 `` `...` `` 代码块 | Task i18n-2 / CC-NEW-2 |
| **X-C2** | 无 Archive/Suspend Card 机制，LLM 劣质题无法永久隐藏 | Gemini | Task 10 补 CardState 枚举加 `suspended`；Task 14 SRSCard 补 Archive 按钮 | Task 10 + 14 |
| **X-C3** | **result_events/EventLog 契约列集冲突**：Task 0 要求 event_type + 唯一索引 (run_id,event_type,timestamp)，但 Task 15 写"与 results.tsv 一一对应"而 TSV 无 event_type 列；weakest_dimension vs weakest_dim 命名不统一 | Codex | Task 0 冻结 result_events 完整 DDL（含 event_type 列 + 统一 weakest_dim）；Task 15 删除"与 TSV 一一对应"措辞 | Task 0 + 15 |

### High（5 项）

| ID | 问题 | 发现者 | 修复方案 | 影响 Task |
|----|------|--------|---------|----------|
| **X-H1** | Task 5 → Task 2 存在未声明的隐性依赖 | Claude | kickoff.md Task 5 依赖行补入 "Task 1 + Task 2" | Task 5 |
| **X-H2** | 触屏长按操作菜单（ConceptGraph Cluster）可发现性极差 | Gemini | Cluster 节点旁增加 ⋮ 图标，单击呼出操作菜单 | Task 14 |
| **X-H3** | cards 表缺 hunk_id/hunk_hash/symbol/change_kind 列，quiz staleness 无法工作；scheduler_preset_id 无外键；**learning_signals 完全没 schema** | Codex | FSRS decision 的 cards DDL 补齐 anchor 列 + FK + learning_signals 完整 DDL | Task 0 + 15 |
| **X-H4** | cache key 缺 eval_bundle_version/output_lang/api_family/privacy_mode，会跨语言跨 adapter 误复用 | Codex | Task 7 cache key 契约补入 4 个缺失维度 | Task 7 |
| **X-H5** | VCR 依赖人工 bump rubric_version 而非直接绑定 eval_bundle_version hash | Codex | VCR cassette key 自动包含 eval_bundle_version（由 hash 驱动，非人工 bump） | Task 18 |

### Medium（5 项）

| ID | 问题 | 发现者 | 修复方案 |
|----|------|--------|---------|
| **X-M1** | 偷看惩罚缺失：手动切换到 Full 后答对不应计为 Good | Gemini | Task 15 SRS 调度增加 peeked_this_session flag |
| **X-M2** | 3 项前端验收标准不可自动化测试 | Claude | Task 13/14 验收标准补充 Playwright perf tracing 具体指标 |
| **X-M3** | Learnability Gate 无独立 Task ID | Claude | 作为 Task 9 step 0 显式定义，补验收标准 |
| **X-M4** | rollback 孤儿态 + Phase 2.5 session 边界和重启恢复语义未冻结 | Codex | Task 0 明确 rollback 产生条件或从枚举移除；Task 17 补 session 恢复语义 |
| **X-M5** | context_bundle 无内容 hash pinning 存在 TOCTOU；entropy>4.5 会误报 UUID/hash/minified | Codex | Task 2 entropy scan 标记为 soft_detect + context_bundle hash pinning |

### Low（3 项）

| ID | 问题 | 发现者 |
|----|------|--------|
| **X-L1** | `rollback` RunStatus 无产生逻辑（可能残留枚举值） | Claude + Codex |
| **X-L2** | Learnability Gate 权重 0.4/0.3/0.3 无科学依据 | Gemini |
| **X-L3** | Task 0 验收标准仍写"9 个契约"但实际已远超 9 个 | Codex |

---

## 三、与 Round 9 对比

| 指标 | Round 9 | Round 10（本轮交叉） | 变化 |
|------|---------|---------------------|------|
| 审查模型 | Claude 单模型 + 2 代理 | Codex + Gemini + Claude 三独立模型 | ↑3 独立视角 |
| Critical | 0 | **3**（Gemini 2 + Codex 1） | ↑3 |
| High | 2 | **5**（Claude 1 + Gemini 1 + Codex 3） | ↑3 |
| Medium | 7 | 5（新增） | — |
| Low | 5 | 3（新增） | — |
| 总新增问题 | — | **16**（不含 Round 9 已有项） | +16 |
| GO 判定 | GO | **CONDITIONAL GO** | ↓降级 |

**降级原因**：
1. **Codex 发现 1 个 Critical**：result_events 契约列集冲突（event_type 在 Task 0/12/15 间不自洽），直接阻塞后端 schema 落地
2. **Gemini 发现 2 个 Critical**：语言检测误判 + 无 card archive，是产品级缺陷
3. **Codex 整体评分 5.8/10**（最严格），SQLite 数据模型仅 5/10，暴露了 Round 9 对后端细节审查不足

---

## 四、最终三模型共识判定

| 模型 | 判定 | 均分 | 关键条件 |
|------|------|------|---------|
| Gemini | CONDITIONAL GO | ~8.0 | 语言检测修正 + card archive |
| Claude | CONDITIONAL GO | 7.8 | Task 5→Task 2 依赖修复 |
| Codex | **CONDITIONAL GO** | **5.8** | result_events 契约 + SQLite 关系模型 + cache key |
| **三模型共识** | **CONDITIONAL GO** | **~7.2** | 8 项必修（3C + 5H） |

### CONDITIONAL GO 条件（~5h 可完成）

**必修项 — Critical（开工前必须修复）**：

| # | ID | 修复内容 | 预计 | 负责 |
|---|-----|---------|------|------|
| 1 | X-C1 | CC-NEW-2 `detect_output_language()` 增加代码块剔除预处理 | 0.5h | Claude |
| 2 | X-C2 | Task 10 CardState 加 `suspended`；Task 14 SRSCard 补 Archive 按钮 | 1h | Claude |
| 3 | X-C3 | Task 0 冻结 result_events 完整 DDL（含 event_type + 统一 weakest_dim）；修正 Task 15 措辞 | 1h | Claude |

**必修项 — High（对应 Task 启动前修复）**：

| # | ID | 修复内容 | 预计 |
|---|-----|---------|------|
| 4 | X-H1 | kickoff.md Task 5 依赖补入 Task 2 | 0.5h |
| 5 | X-H2 | Task 14 ConceptGraph Cluster 补 ⋮ 图标替代长按 | 0.5h |
| 6 | X-H3 | cards DDL 补 anchor 列 + FK + learning_signals 完整 DDL | 0.5h |
| 7 | X-H4 | Task 7 cache key 补 eval_bundle_version/output_lang/api_family/privacy_mode | 0.5h |
| 8 | X-H5 | VCR cassette key 自动绑定 eval_bundle_version hash | 0.5h |

**建议修项（对应 Task 启动前）**：

| # | ID | 修复内容 |
|---|-----|---------|
| 9 | X-M1 | Task 15 补 peeked_this_session flag |
| 10 | X-M2 | Task 13/14 验收标准量化（Playwright perf tracing） |
| 11 | X-M3 | Learnability Gate 作为 Task 9 step 0 |
| 12 | X-M4 | rollback 产生条件明确化 + Phase 2.5 session 恢复 |
| 13 | X-M5 | entropy scan 标为 soft_detect + context_bundle hash pinning |

### 信心水平

| 阶段 | Round 9 | Round 10 | 变化原因 |
|------|---------|----------|---------|
| v0.1 可开工 | 高 | **中**（8 项必修后升为高） | Codex 暴露后端契约缺口 |
| v0.2 路径 | 中高 | 中高 | 不变 |
| 学习科学 | 中高 | **中**（quiz 质量无审核是产品硬伤） | Gemini 观点有效 |
| 后端数据层 | 高（Round 9 未单独评估） | **中低**（Codex 5.8/10） | SQLite schema + cache key 需补齐 |

---

## 五、Codex CLI 审查原文摘要

> Codex CLI 0.122.0, 207,499 tokens consumed, full-auto mode

**核心判断原文**：

> "这套方案总体方向对，但 Round 9 的 GO 我不同意，原因不是'大方向错'，而是还有几处会直接影响数据契约落地和测试可执行性的文档级缺口。"

**Codex 独有发现（Gemini/Claude 未覆盖）**：

1. **result_events 列集冲突**（Critical）：Task 0 定义 EventLog 含 event_type，但 Task 15 说"与 results.tsv 一一对应"，而 TSV 无 event_type 列。两份文档无法同时为真
2. **cards 表缺 anchor 列**（High）：Task 10 冻结了 ReviewCard 含 hunk_id/hunk_hash/symbol/change_kind，但 FSRS decision 的 SQL DDL 未包含这些列。quiz staleness 检测会因缺少 anchor 而无法工作
3. **learning_signals 无 schema**（High）：stages-4-9.md 仅提及表名，未给出任何列定义或索引。corner-cases-closure-8.md CC-NEW-4 给了部分定义但未回流到 Task 15
4. **cache key 维度不足**（High）：当前 7 元素缺少 eval_bundle_version/output_lang/api_family/privacy_mode，会导致跨语言、跨 adapter、跨评估版本的缓存误命中
5. **VCR 人工 bump 风险**（High）：eval bundle 变更应自动驱动 cassette 失效，而非依赖开发者手动更新 rubric_version

**Codex 六维评分**：D1=6, D2=5, D3=6, D4=7, D5=6, D6=5, **均分 5.8/10**

---

## 六、三模型交叉验证矩阵

| 问题 | Gemini | Claude | Codex | 共识 |
|------|--------|--------|-------|------|
| 语言检测代码块误判 | **Critical** | 未发现 | 未发现 | Critical（Gemini 独有，有效） |
| Card Archive/Suspend | **Critical** | 未发现 | 未发现 | Critical（Gemini 独有，有效） |
| result_events 契约冲突 | 未发现 | 未发现 | **Critical** | Critical（Codex 独有，有效） |
| Task 5→Task 2 依赖 | 未发现 | **High** | 未发现 | High（Claude 独有，有效） |
| cards 缺 anchor 列 | 未发现 | 未发现 | **High** | High（Codex 独有，有效） |
| cache key 维度不足 | 未发现 | 未发现 | **High** | High（Codex 独有，有效） |
| rollback 孤儿态 | 未发现 | **Low** | **Medium** | Medium（双模型确认） |
| 验收标准不可自动化 | 未发现 | **Medium** | 未发现 | Medium（Claude 独有，有效） |

**关键洞察**：三模型各自发现了不同维度的盲点，**几乎没有重叠**。这证明单模型审查（即使是 Round 9 的 Claude + 代理模式）的覆盖面存在结构性局限，三模型交叉审查确实发现了单模型遗漏的 Critical/High 级问题。

---

## 七、下一步路径

```
本轮 CONDITIONAL GO
  └─> 修复 8 项必修（3C + 5H），预计 ~5h
        └─> 修复完成后由 Codex 复核后端契约（重点验证 X-C3/X-H3/X-H4）
              └─> GO → /ccg:team-plan ahadiff-v01 → 生成可执行计划 → 开工
```

---

## 八、修复结果（2026-04-21 完成）

**全部 16 项（3C+5H+5M+3L）已修复并验证**，CONDITIONAL GO 升级为 **GO**。

修复落地文件：
- `ahadiff-v01-kickoff.md`：RunStatus 移除 rollback（8 态）、result_events 列集冻结、Task 5 补 Task 2 依赖、Task 0 step 22 冻结 LearnabilityGate defaults、cache key 10 元素、entropy_scan=soft_detect
- `ahadiff-v01-stages-4-9.md`：Task 8.5 独立定义、Task 10 CardState 四态 + peeked_this_session、Task 9 依赖补 Task 8.5、Task 13/14 验收标准量化、ConceptGraph ⋮ 菜单、cards DDL 补 anchor 列 + FK
- `ahadiff-fsrs-decision.md`：fsrs_card_json → fsrs_state、Pydantic 补 card_state + peeked_this_session、cards SQL 补 anchor 列 + card_state + FK、非评分动作定义
- `corner-cases-closure-8.md`：CC-NEW-2 补 `_strip_code_for_language_detection()` 实现 + 测试
- `ahadiff-v01-comprehensive-evaluation-research.md`：CardState 三态→四态
- `ahadiff-v01-comprehensive-review-research.md`：cassette key rubric_version→eval_bundle_version、CardState 四态
- `doc/AhaDiff_frontend_design_v1.1_revised.md`：Review 底部按钮 + 卡片状态动作 + ⋮ 菜单
- `CLAUDE.md`：N-文件契约 eval_bundle_version 描述、VCR cassette key、Stage 3 含 Task 8.5
