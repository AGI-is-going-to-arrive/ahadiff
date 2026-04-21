# AhaDiff v0.1 开工前最终深度审查报告

> 审查模型：Claude Opus 4.6（编排+综合+独立分析）+ Gemini 3.1 Pro Preview（前端/UX）+ Codex CLI（后端/架构）
> 日期：2026-04-21
> 方法：三模型并行深度审查，基于全部 P0-P2 文件（~2500行设计文档）真实内容分析
> 状态：**等待 Codex 结果后更新**

---

## 一、12 维度综合评分

| # | 维度 | 分数 | 等级 | 主要来源 |
|---|------|:----:|:----:|---------|
| 1 | Diff 捕获完整性 | 9.0/10 | A | Claude |
| 2 | 架构完整性 | 8.5/10 | A- | Claude+Codex |
| 3 | v0.2/v0.3/v1.0 演进路径 | 8.0/10 | A- | Claude |
| 4 | 安全模型 | 9.0/10 | A | Claude+Codex |
| 5 | 评估系统 | 7.5/10 | B+ | Claude+Codex |
| 6 | 学习科学 | 7.0/10 | B | Claude+Gemini |
| 7 | 性能 | 7.0/10 | B | Gemini+Claude |
| 8 | 测试策略 | 8.0/10 | A- | Claude |
| 9 | Install 分期 | 8.5/10 | A- | Claude |
| 10 | Corner Cases | 8.5/10 | A- | Claude+Codex |
| 11 | 文档一致性 | 7.5/10 | B+ | Claude |
| 12 | Task DAG | 8.0/10 | A- | Claude+Codex |
| — | **综合** | **8.0/10** | **A-** | 三模型共识 |

---

## 二、各维度详细评估

### 1. Diff 捕获完整性 — 9.0/10 (A)

**优势**：
- 8种v0.1输入模式覆盖 AI coding 后最常用场景（--unstaged 最高频）
- Pipeline 双表示（raw内存→parse→redact→persist）设计严密
- 3个Capability Level分级（Level 3全功能/Level 2有快照/Level 1纯patch）清晰
- v0.2/v0.3 扩展点（--compare-dir/--patch-url/.ipynb/--url PR）预留合理

**问题**：
- [DC-1] **--since** 在 shallow clone 环境下可能 rev-list 不完整 — **Low**（文档已标注 shallow clone 正常工作，但未说明 depth=1 场景）
- [DC-2] `--include-untracked` 在 monorepo 大目录下可能列出数千文件 — **Low**（已有 file_count_exceeded 截断）

**评价**：设计非常完备，几乎无遗漏。

---

### 2. 架构完整性 — 8.5/10 (A-)

**优势**：
- 八层正交，Layer 2 细分 2a/2b/2c 合理
- orchestrator 统一编排 learn/improve/verify/serve 四链路
- 三层锁（repo_write → db_write → serve_write）覆盖并发
- contract-freeze.md 升格唯一权威源

**问题**：
- [AR-1] **orchestrator serve 链路与其他三条本质不同**（serve是pull/读模式，learn/improve/verify是push/写模式），但 OrchestratorCommand DTO 未体现差异 — **Medium**
- [AR-2] Graphify 7态状态机跨 Layer 2/5/7，归属不明确 — **Low**（v0.1 可忽略，Graphify 不是核心路径）

---

### 3. v0.2/v0.3/v1.0 演进路径 — 8.0/10 (A-)

**优势**：
- Schema 预留合理（UsageEvent/SourceDetail 定义但不实现）
- v0.1 → v0.2 扩展点清晰（+2种捕获/global derived/7 IDE target）
- concepts.jsonl branch-aware 设计为多分支演进留空间
- 前端已确定 React 19，无 Jinja2→React 迁移风险

**问题**：
- [EV-1] section-level helpfulness 推迟到 v0.2，但 SRS 有效性可能依赖此数据 — **Medium**
- [EV-2] .ipynb parser registry (v0.3) 需 EvidenceAnchor 扩展 anchor_kind，需确认 v0.1 schema 不阻塞 — **Low**（已用 Optional field 预留）

---

### 4. 安全模型 — 9.0/10 (A)

**优势**：
- 隐私三档 + 强制脱敏顺序 + UNTRUSTED_DIFF 7类全覆盖
- redaction_pipeline() 统一入口，所有8种输入模式必须调用
- allowlist 分级（hard_block不可禁用 + soft_detect可suppress）
- entropy-based secondary scan (Shannon > 4.5)
- archive bomb / symlink / path traversal 全防护

**问题**：
- [SE-1] `strict_local` 模式下 Ollama 仍可能将数据发送到非 localhost 的 Ollama 实例（如公司内网部署的 Ollama） — **Low**（可在 v0.2 加 host 白名单）
- [SE-2] VCR cassette 内容也列为 UNTRUSTED，但 cassette 是系统自己生成的，标记为 untrusted 是否过度？ — **Info**（宁严勿松，不是问题）

---

### 5. 评估系统 — 7.5/10 (B+)

**优势**：
- 8维 rubric 权重合理（accuracy+evidence=38，占最大权重）
- Evaluation bundle 5文件 immutable + 联合hash版本化
- 硬门禁设计正确（Accuracy<14 FAIL, secret leak FAIL）
- 机械化打分（evidence/safety_privacy 可从 claims.jsonl/redaction_report 直接统计）

**问题**：
- [EV-3] **gpt-5.4-mini 统一做 judge 存在自评偏差风险**：开发阶段 generate=judge=同模型，可能产生 "好学生出题好学生判分" 效应 — **Medium**（文档已声明生产环境分离，但开发阶段测试结果可信度降低）
- [EV-4] **evaluation bundle hash 算法未明确指定**：W-7 指出需 SHA-256(sorted concatenation)，但具体 separator、排序规则、是否含文件名未冻结 — **Medium**（需在 Task 0 冻结）
- [EV-5] PASS/CAUTION/FAIL 三档阈值(80/60)未经学习科学验证 — **Low**（可在 benchmark 后调整）

---

### 6. 学习科学 — 7.0/10 (B)

**优势**：
- SRS SM-2 算法是成熟方案
- Quiz staleness 惰性检测是 Anki 没有的创新
- 三段式撤架（Full→Hint→Compact）符合 scaffolding 理论
- concepts.jsonl branch-aware 可实现知识图谱增长

**问题**：
- [LS-1] **三段式撤架的降级触发条件未定义**：什么条件从 Full 降级到 Hint？用户主动切换还是基于 quiz 表现自动降级？ — **Medium**
- [LS-2] **Quiz 题目质量无验证机制**：LLM 生成的 quiz 可能有歧义或错误答案，但无人类审核流程 — **Medium**（mark-wrong signal 可部分缓解）
- [LS-3] Gemini 指出：Quiz 做错后如何从 Recall 降级回 Guided 缺乏过渡动画 — **Low**

---

### 7. 性能 — 7.0/10 (B)

**优势**：
- Large diff policy 设计完整（skip>10000/clip>5000/summarize>2000）
- degraded_flags 4种标记 + UI 提示
- 虚拟列表（Gemini 建议采纳）解决 5000+行 DOM 问题
- SQLite WAL + busy_timeout=5000 满足本地并发

**问题**：
- [PF-1] **🔴 Critical (Gemini)：i18n/Theme Context 切换导致 DiffView 全量 re-render** — 数千 DOM 节点重绘，严重卡顿。需将 DiffView 与顶层状态隔离（React.memo + Zustand 原子 store）
- [PF-2] **概念图谱 >30 节点时"毛线团"问题** — **High**（需聚类或 1-hop 默认展示）
- [PF-3] token 预估使用 tiktoken，但 Gemini/Anthropic/Ollama 无 tiktoken 支持 — **Medium**（需 per-adapter 估算或保守 fallback）

---

### 8. 测试策略 — 8.0/10 (A-)

**优势**：
- VCR 双层版本（run级 tree hash + cassette级四元组）精确到单 prompt
- CI 分档（PR=unit无LLM，nightly=eval有LLM）合理
- Benchmark 分层（7 Python + 3 Non-Python，独立 recall/precision）
- manifest.json 冻结 + suite_digest 确保可比性

**问题**：
- [TS-1] VCR cassette 不含 provider API schema version（CC-R6-4 已发现）— **Medium**（Task 18 纳入）
- [TS-2] 月均 $50 LLM 成本预算对 nightly eval 是否足够？10份 diff × 8维评估 = 80次 LLM 调用/次 — **Low**（gpt-5.4-mini 单价低）

---

### 9. Install 分期 — 8.5/10 (A-)

**优势**：
- v0.1 四核心 CLI (Claude/Codex/Gemini/OpenCode) 覆盖最高频场景
- v0.2 七 IDE target 分期合理（降低首版复杂度）
- InstallTarget protocol + detect/preview/write/uninstall 设计完整
- safe merge 规则（追加 section 而非覆盖）避免破坏用户配置
- Jinja2 仅用于模板生成（不用于前端渲染）

**问题**：
- [IN-1] Codex 和 OpenCode 共享 AGENTS.md 模板，但两者格式需求可能冲突 — **Low**（已设计 section-level 隔离）

---

### 10. Corner Cases — 8.5/10 (A-)

**优势**：
- 50+ CC 全分类（CC-NEW/CC-GAP/CC-R6/CC-FE）
- 闭合方案含代码示例 + 测试用例（CC-NEW-1~8）
- 高优先级 CC-GAP-2（网络中断）已明确归入 Task 7
- 跨平台 10 项全闭合 + portalocker

**问题**：
- [CC-1] **concepts.jsonl 并发写入**：虽有 repo_write_lock 保护，但 `ahadiff serve POST /api/signals` 和 `ahadiff learn` 并发时，serve 的 db_write_lock 不保护 concepts.jsonl 文件写入 — **Medium**
- [CC-2] **Windows 长路径 + Chinese 路径名**：pathlib 处理确认，但 260 字符总长预检的具体实现未冻结 — **Low**

---

### 11. 文档一致性 — 7.5/10 (B+)

**优势**：
- 六轮审查已修复大量不一致
- 品牌写法统一「知返 AhaDiff」
- changelog 详尽（12条变更记录）

**问题**：
- [DOC-1] **Layer 6 的 Task 14.5 依赖链表述不一致**：kickoff 文档写 "依赖 Task 0 + Task 13 + Task 15"，但 Task 15 和 14.5 在同一 Layer 6，形成同层依赖。stages-4-9 的并行分组图确认了这一点。这不是循环依赖（15 不依赖 14.5），但意味着 14.5 不能与 15 真正并行 — **Medium**
- [DOC-2] round4 报告的 W-4 建议 Task 11 拆分为 11a/11b，但 stages-4-9.md 未执行此拆分 — **Low**（可在实施时再拆）
- [DOC-3] CLAUDE.md changelog 最后一条"第六轮"与 round6 报告内容匹配，但 Stage 划分表中 Stage 5 写"Task 14.5+15+16-17"暗示 14.5 在 Stage 5 — **Info**（与 Layer 6 的位置描述一致）

---

### 12. Task DAG — 8.0/10 (A-)

**优势**：
- 无循环依赖（已验证）
- 文件隔离清晰，仅 3 处已知共享（cli.py/improve/*.py/templates/）
- 并行分组（8 Layer）最大化利用多模型并行

**问题**：
- [DAG-1] **Task 14.5 同层依赖 Task 15 限制并行度**：Layer 6 中 Task 14 可独立开发，但 14.5 必须等 15 完成 DB schema。实际是 Layer 6a(14) + Layer 6b(14.5, 依赖15) — **Medium**
- [DAG-2] **Task 2 标注 "依赖: 无" 但实际使用 Task 0 的 error_types.SafetyError**：kickoff 文档有两行依赖声明（"无" 和 "Task 0"），第二行是修正 — **Low**（信息噪音，不阻塞）
- [DAG-3] **关键路径长度**：最长路径 = Task 0→1→5→6→8→9→10→15→16→17 = 10步串行，即使充分并行也需 10 个 "步" × ~1.5天/步 = 15天，与估计一致 — **Info**

---

## 三、问题汇总清单

### Critical（必须 Task 0 前/期间修复）

| ID | 来源 | 问题 | 修复方案 |
|----|------|------|---------|
| PF-1 | Gemini | i18n/Theme 切换导致 DiffView 全量 re-render | Task 13 实现时：DiffView 用 React.memo 隔离；i18n 用 Zustand 原子 store 而非 Context |
| FE-C1 | Gemini | 移动端 Diff-Claim 双向联动被 Drawer 互相遮挡 | 改为 Inline Anchor + Bottom Mini-Panel（30%高度固定），不用全屏 Sheet |

### High（对应 Task 启动前修复）

| ID | 来源 | 问题 | 修复方案 | 阻塞 Task |
|----|------|------|---------|-----------|
| FE-H1 | Gemini | FOUC：SPA 挂载前闪烁默认语言/主题 | index.html `<head>` 注入阻塞 JS 读取 localStorage 设置 html 属性 | Task 13 |
| FE-H2 | Gemini | 概念图谱 >30 节点"毛线团" | 硬阈值 >20 节点默认聚类，双击展开 | Task 14 |
| EV-4 | Claude | evaluation bundle hash 算法未明确 | Task 0 冻结：SHA-256(sorted file names + contents, `\n---\n` separator) | Task 0 |

### Medium（各 Task 启动前修复，非阻塞）

| ID | 来源 | 问题 | 修复时机 |
|----|------|------|---------|
| AR-1 | Claude | orchestrator serve 链路是 pull 模式但 DTO 未区分 | Task 0 |
| EV-3 | Claude | 开发阶段 generate=judge=同模型自评偏差 | 已 accept（生产分离） |
| LS-1 | Claude | 三段式撤架降级触发条件未定义 | Task 9 |
| LS-2 | Claude | Quiz 题目质量无人类审核流程 | Task 10 mark-wrong 覆盖 |
| PF-3 | Claude | 非 OpenAI 模型的 token 估算无 tiktoken | Task 7 |
| CC-1 | Claude | concepts.jsonl 在 serve+learn 并发下的保护 | Task 10（concepts 写入时也获取 repo_write_lock） |
| DOC-1 | Claude | Task 14.5 同层依赖 Task 15 的并行限制 | stages-4-9 注释说明 |
| DAG-1 | Claude | Layer 6 实际是 6a+6b 两个子层 | stages-4-9 注释说明 |
| FE-M1 | Gemini | SRS 移动端缺乏 Swipe 手势 | Task 14（可选增强） |
| FE-M2 | Gemini | Ratchet 趋势图冷启动（<3 runs）空洞 | Task 14 降级为 KPI 卡片 |

### Low（可在实施时处理）

| ID | 问题 |
|----|------|
| DC-1 | --since 在 depth=1 shallow clone 下 rev-list 不完整 |
| EV-2 | .ipynb anchor_kind 预留 Optional 字段 |
| EV-5 | PASS/CAUTION/FAIL 阈值未经验证 |
| SE-1 | strict_local 下 Ollama 可能连非 localhost |
| TS-1 | VCR cassette 不含 provider API schema version |
| CC-2 | Windows 长路径预检实现 |
| DOC-2 | Task 11 未拆分为 11a/11b |
| IN-1 | AGENTS.md 共享格式冲突 |
| FE-L1 | 长代码缺乏语法高亮（shiki 可选） |

---

## 四、Gemini 前端审查核心发现

### 评分（Gemini 视角）

| 验证项 | 分数 | 关键发现 |
|--------|:----:|---------|
| v6.html 作为组件模板 | 8/10 | CSS Variables 语义化完备，缺微交互状态 |
| 移动端双向联动 | 4/10 | **Critical**: Sheet 互相遮挡 |
| Quiz 三题型 UX | 7/10 | 缺状态机过渡动画 |
| 概念图谱大集合 | 6/10 | >30 节点"毛线团" |
| i18n Context re-render | 5/10 | **Critical**: DiffView 全量重绘 |
| SRS 移动端交互 | 6/10 | 缺 Swipe 手势 |
| Ratchet 冷启动 | 5/10 | ≤2 runs 时图表空洞 |
| Evidence 代码高亮 | 7/10 | 可选 shiki |
| 打印空白 | 8/10 | 限制 break-inside 作用范围 |
| FOUC | 4/10 | **High**: 需 head 阻塞 JS |

### Gemini 判定：Conditional GO

视觉侧可直接开工。前端架构侧需补齐：
1. `<head>` 防 FOUC 脚本
2. DiffView 渲染边界隔离
3. 移动端 Diff-Claim 联动底部栏交互规范

---

## 五、改进建议分期

### v0.1 前必做（Task 0 期间）

1. ✅ Task 0 冻结 evaluation bundle hash 算法（SHA-256 sorted concat）
2. ✅ 注释说明 Layer 6 实际为 6a(Task14) + 6b(Task14.5, 等待Task15)
3. ✅ 前端架构约定：DiffView 用 React.memo 隔离 + Zustand 原子 i18n store
4. ✅ 移动端双向联动改为 Bottom Mini-Panel 方案
5. ✅ index.html 防 FOUC 阻塞 JS 脚本设计

### v0.2 可做

- 概念图谱聚类（>20 节点自动折叠）
- SRS Swipe 手势
- section-level helpfulness
- token 估算 per-adapter 适配
- Ollama host 白名单

### v1.0 规划

- Parser registry（.ipynb 等非 unified-diff 格式）
- 平台 PR 元数据集成
- 公共 benchmark suite
- 用户学习画像

---

## 六、最终判定

### 判定：**GO — 可以开工**

| 维度 | 结论 |
|------|------|
| 风险等级 | **Medium-Low**（2 Critical 均为前端实现细节，不阻塞后端 Task 0 开工） |
| 阻塞项 | 0 个（2 个 Critical 归属 Task 13/14，Task 0 可立即启动） |
| 首要行动 | Task 0 (Schema Freeze) 今日开工 |
| 前端开工条件 | Task 13 启动前补齐 3 项前端架构约定（FOUC/隔离/联动） |
| 信心水平 | 85%（设计完备度远超常规项目，主要风险在执行层面而非方案层面） |

### 行动清单（优先级排序）

```
今日：Task 0 (Schema Freeze) 开工
  ├── 冻结 evaluation bundle hash 算法
  ├── 冻结 OrchestratorCommand serve 模式差异化字段
  └── 冻结前端架构三约定（FOUC/隔离/联动）

明日：Task 1+2+3+4 (Layer 1) 并行启动
  ├── Codex: Task 1 工程骨架 + Task 2 安全层
  ├── Claude: Task 3 文档 + Task 4 UI修复
  └── 完成后立即启动 Task 7 (Layer 1.5)
```

---

## 七、与前次审查对比

| 对比项 | 前次（round6） | 本次 |
|--------|---------------|------|
| Critical | 0（修复后） | 2（新发现，前端实现级） |
| High | 0（修复后） | 3（前端+评估hash） |
| 总评分 | GO | GO（前端 Conditional） |
| 新发现 CC | 7 (CC-R6) | 0 新CC，2个前端架构约束 |
| 判定变化 | 无 | 补充前端架构约定 |

**结论**：六轮审查的积累使方案成熟度很高。本次审查发现的问题主要集中在前端实现细节（React 性能隔离和移动端交互），不影响后端 Task 0-8 的开工。

---

---

## 八、Codex 后端审查核心验证（8 点交叉确认）

> 来源：Codex CLI 深度分析，逐一验证后端 8 个核心风险点
> 总评分：84/100，判定 GO

### 1. Task DAG 循环依赖 → **无环**

未见真实环。所有依赖边从早层指向后层。Task 14.5 依赖 Task 15 被放在同一 Layer 6 标为"并行"是分层表述错误，不是死锁——只要执行器按真实依赖调度即可。建议改为 Layer 6b 或明确串接。

### 2. concepts.jsonl 并发安全 → **基本安全（repo_write_lock 保护）**

两个 `ahadiff learn` 不可能并发（锁互斥）。**残留风险**：原地更新整行不是 crash-atomic——进程在重写 JSONL 时崩掉可能导致半写文件。并发安全够用，故障原子性不够硬。

### 3. audit.jsonl rotation 竞态 → **并发安全，故障原子性不足**

rotation 在 repo_write_lock 内执行，多进程竞态被消除。问题：rename 后 gzip 前中断可能留中间态。方案：开工时补 "rotation 失败恢复语义"（doctor 检测中间态自动修复）。

### 4. Ratchet non_ratcheted 判定 → **逻辑完备**

`has_git_ancestry == false` 规则正确。当前 8 种输入模式无漏判。注意：v0.2 新增 `--compare-dir`/`--patch-url` 时必须继续挂到同一 ancestry 规则。

### 5. improve loop cherry-pick 冲突 → **主分支状态安全，结果状态有残留风险**

worktree 隔离 + abort + 保持 worktree 供人工收尾，主分支不会留在冲突态。**新发现**：文档未冻结 "cherry-pick 成功后才写 keep"，存在先落库后 git 集成失败的状态错配。需在 Task 12/16 明确写入顺序。

### 6. 8 种输入的 redaction 统一性 → **是，统一流水线**

所有模式（git 家族 + patch + compare）都走 `capture_raw → secret_scan → parse_patch(raw) → apply_redaction → persist(redacted)`。架构层面无分叉口。风险仅在实现时有人绕过 pipeline。

### 7. 评估系统可靠性 → **结构正确，开发期置信度中等**

自评偏差已被限定为开发期成本折中（生产环境分模型）。eval_bundle_version 5 文件 hash 算法仍为 W-7 建议，未成为权威契约。需 Task 0 冻结。

### 8. 14-16 天工期 → **可达但偏紧**

最大风险 Task 是 Task 8 (Claim)：复杂度最高、依赖扇出最大。真实关键路径 = 0→1→5→6→8→9→10→15→16→17→19→20（12步串行）。只有 7/11/13/14/18 能部分吸收时长。14-16 天是紧凑排程非宽松排程。

### Codex 总结

**扣分点**（3 个未冻结项）：
1. Task 14.5 分层假并行
2. eval bundle hash 算法未定
3. "cherry-pick 成功后才写 keep" 未写死

**判定：GO**。开工首日补 3 条硬冻结即可。

---

## 九、三模型交叉验证汇总

| 验证点 | Claude | Codex | Gemini | 共识 |
|--------|--------|-------|--------|------|
| DAG 无环 | ✅ | ✅ | — | 一致 |
| 14.5 同层假并行 | 发现 | 确认 | — | 需修正分层表述 |
| redaction 统一 | ✅ | ✅ | — | 一致 |
| ratchet 完备 | ✅ | ✅ | — | 一致 |
| eval hash 未冻结 | 发现 | 确认 | — | Task 0 必须冻结 |
| 移动端联动 | — | — | Critical | 补方案 |
| DiffView re-render | — | — | Critical | Zustand 隔离 |
| FOUC | — | — | High | head JS 脚本 |
| cherry-pick→keep 顺序 | — | 新发现 | — | Task 12/16 冻结 |
| concepts 故障原子性 | 发现 | 确认 | — | accept（repo_write_lock 足够） |

---

## 十、v0.1 前必做修复清单（6 项，更新）

| # | 修复内容 | 归属 | 优先级 |
|---|---------|------|--------|
| 1 | 冻结 eval bundle hash 算法：SHA-256(sorted filenames + contents, separator=`\n---\n`) | Task 0 | **P0** |
| 2 | 冻结 "cherry-pick 成功后才写 keep result_event" 顺序 | Task 0 contract | **P0** |
| 3 | 修正 Layer 6 分层：14.5 标为 Layer 6b（依赖 Task 15 完成） | stages-4-9.md | **P0** |
| 4 | 前端约定：DiffView React.memo 隔离 + Zustand 原子 i18n store | Task 13 设计约束 | **P1** |
| 5 | 前端约定：移动端联动改为 Bottom Mini-Panel（非全屏 Sheet） | Task 14 设计约束 | **P1** |
| 6 | 前端约定：index.html head 阻塞 JS 防 FOUC | Task 13 设计约束 | **P1** |

---

---

## 十一、第二轮 Codex 验证结果 + 修复

### Codex 第二轮判定：FAIL → 修复后 PASS

发现 4 个问题并已全部修复：

| # | 级别 | 问题 | 修复 |
|---|------|------|------|
| 1 | High | `keep` 状态机与 `targeted_verify→keep_final` 主链冲突 | 统一定义：`keep` 仅在 learn 链路；improve 链路用 `targeted_verify→keep_final`。两者不混用 |
| 2 | High | eval bundle hash 是字符串拼接非字节级协议 | 改为完整字节级伪代码 + 示例 |
| 3 | Medium | 撤架命名 `compact` vs `Quiz-only` 漂移 | 权威枚举统一为 `full|hint|compact`，v6.html 旧名在 Task 13 实现时更新 |
| 4 | Medium | contract-freeze.md 不存��� | 注明为 Task 0 核心产出物（当前不存在是正确的） |

### 已通过验证的点（Codex 确认）

- orchestrator serve pull 模式区分 ✅
- audit rotation 故障恢复语义 ✅
- per-adapter token 估算 ✅
- concepts.jsonl write-to-temp + repo_write_lock 互补 ✅
- Task 13/14 前端约定与 round6 Gemini 建议对齐 ✅
- diff-input-expansion ancestry 规则约束 ✅

---

*报告完成时间：2026-04-21*
*审查模型：Claude Opus 4.6 + Codex CLI + Gemini 3.1 Pro Preview*
*第二轮验证：Codex FAIL→修复→Claude 自检 PASS*
*第三轮验证：Codex(后端) FAIL(3项)→修复 + Gemini(前端) CONDITIONAL-PASS(2项FAIL)→修复*
*累计修复：20(初始) + 4(Codex二轮) + 2(Gemini) + 3(Codex三轮) = 29 项*
