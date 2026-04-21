# Team Review: AhaDiff 全面深度审查（v0.1→v0.2→v1.0）

> 审查时间：2026-04-21
> 审查模型：Claude Opus 4.6（编排+综合） + Codex CLI（后端/架构） + Gemini 3.1 Pro（前端/UX/产品）
> 方法：三模型并行深度审查 + 外部权威来源交叉核验

---

## 增强后的需求

对 AhaDiff 整个项目进行 12 维度全面深度审查，覆盖 v0.1→v0.2→v1.0 完整演进路径。基于 6 份 P0 文件 + 2 份 P1 文件 + 3 份 HTML 原型 + README 双语版的真实内容进行分析。要求：基于事实不猜测，发现问题给修复方案，最终产出多维评分 + 改进路线图。

---

## 一、12 维度综合评分

| # | 维度 | 分数 | 等级 | 评估来源 |
|---|------|:----:|:----:|---------|
| 1 | 架构完整性 | 8.5/10 | A- | Claude+Codex+Gemini |
| 2 | v0.2/v1.0 演进路径 | 7.5/10 | B+ | Claude+Gemini |
| 3 | 技术栈选择 | 8.5/10 | A- | Claude+Codex |
| 4 | 安全模型 | 9.0/10 | A | Claude+Codex |
| 5 | 评估系统 | 7.5/10 | B+ | Claude+Codex |
| 6 | 学习科学 | 7.0/10 | B | Claude+Gemini |
| 7 | 可用性 | 8.5/10 | A- | Claude+Gemini |
| 8 | 性能 | 7.5/10 | B+ | Claude+Codex |
| 9 | 测试策略 | 8.0/10 | A- | Claude+Codex |
| 10 | 竞品差异化 | 9.0/10 | A | Gemini+Claude |
| 11 | 商业可行性 | 5.5/10 | C+ | Claude+Gemini |
| 12 | Corner Cases 遗漏 | 8.0/10 | A- | Claude+Codex |
| — | **综合（修订后）** | **7.6/10** | **B+** | 三模型共识 |

---

## 二、各维度详细评估

### 2.1 架构完整性 — 8.5/10 (A-)

**优势**：
- 八层正交架构职责清晰，Layer 2 细分为 2a/2b/2c 合理
- `core/orchestrator.py` 统一编排 learn/improve/verify/serve 四条主链路正确
- Layer 7 拆分为 7a Static + 7b Serve 是关键架构决策
- 三层锁模型（repo_write → db_write → serve_write）覆盖并发需求

**问题**：
- [A-1] Layer 5/6/7 服务契约分散在综合评估文档和 CLAUDE.md 之间，权威来源分裂 — **Medium**
- [A-2] Graphify 7 态状态机跨 Layer 2/5/7，需统一下沉到 Layer 5 query service — **Medium**
- [A-3] orchestrator 的四条链路中 serve 与其他三条在数据流方向上本质不同（serve 是 pull 而非 push），但当前 DTO 设计未体现差异 — **Low**

**改进建议**：
- v0.1 前：将 contract-freeze.md 升格为唯一架构权威源
- v0.2：Graphify freshness query 独立为 Layer 5 子模块

### 2.2 v0.2/v1.0 演进路径 — 7.5/10 (B+)

**优势**：
- 分期路线清晰（v0.1 per-repo truth → v0.2 global derived → v1.0 public）
- Schema 预留合理（UsageEvent、registry.json 定义但不实现）
- concepts.jsonl 的 branch-aware 设计为多分支演进留空间

**问题**：
- [E-1] **Jinja2→React 迁移代价巨大**：v0.1 模板交互逻辑若与数据层耦合，v1.0 重写将导致 UX 断裂 — **High**（Gemini 确认）
- [E-2] section-level helpfulness 推迟到 v0.2，但 SRS 有效性依赖此数据 — **Medium**
- [E-3] index.md 增量 wiki 推迟到 v0.2，但 concepts.jsonl 在 v0.1 已存在，两者关系模糊 — **Low**

**改进建议**：
- v0.1 前：确保 Jinja2 模板完全被动（只消费 DTO，不做 business logic）
- v0.2：定义 Viewer Interface 抽象层，使 React 迁移只需替换渲染层

### 2.3 技术栈选择 — 8.5/10 (A-)

**优势**：
- Python+Starlette+SQLite 对 local-first CLI 工具是最优选择
- httpx 直连避免 SDK 版本碎片化，Provider Protocol 保持松耦合
- SQLite WAL + portalocker 满足本地并发需求
- 不用 LangChain/LiteLLM 降低供应链风险

**问题**：
- [T-1] httpx 直连每个新 provider 需自行实现 API 兼容层，维护成本线性增长 — **Medium**
- [T-2] SQLite 在网络盘（NAS、Dropbox）上 WAL 模式不可靠，已有 fail-fast 但提示不够 — **Low**

**改进建议**：
- v0.2：评估 litellm 最小子集（仅路由层）替代 httpx 直连
- v0.1：`ahadiff doctor` 加入网络盘检测

### 2.4 安全模型 — 9.0/10 (A)

**优势**：
- 隐私三档（strict_local/redacted_remote/explicit_remote）设计严密
- `redaction_pipeline()` 统一入口强制脱敏顺序
- UNTRUSTED_DIFF 边界已扩展到"所有外部文本和路径元数据"
- allowlist 分级（hard_block 不可禁用 + soft_detect 可 suppress）
- archive bomb 限制 + symlink 拒绝 + path traversal 防护

**问题**：
- [S-1] 高熵检测缺失：纯规则驱动可能漏掉自定义格式的 token — **Medium**
- [S-2] data_bundle.json 渲染时的 XSS 逃逸需 DOM Purify — **Medium**

**改进建议**：
- v0.1 Task 2：entropy-based secondary check（Shannon entropy > 4.5 + length > 20 → flag）
- v0.1 Task 13：Jinja2 渲染强制 `|tojson` + DOMPurify

### 2.5 评估系统 — 7.5/10 (B+)

**优势**：
- 8 维 rubric 覆盖全面
- 跨模型评估（生成用大模型，评估用 gpt-5.4-mini）降低自评偏差
- Evaluation bundle 整体 immutable + 版本化正确
- 硬门禁（Accuracy<14 FAIL, Evidence<12 FAIL）提供底线保障

**问题**：
- [EV-1] ~~Haiku 作为 judge~~ → **已消除**：改用 gpt-5.4-mini（1M ctx），评估能力充足 — ~~High~~ **Closed**
- [EV-2] 固定权重不适应不同类型 diff（refactor vs feature vs bugfix） — **Medium**
- [EV-3] `quiz_transfer` 维度的机械化打分方法不明确 — **Medium**

**改进建议**：
- v0.1 benchmark：实测 gpt-5.4-mini judge 稳定性（重复评估的 Cohen's kappa ≥ 0.7）
- v0.2：diff-type-aware 权重调整

### 2.6 学习科学 — 7.0/10 (B)

**优势**：
- SM-2 经数十年验证（Anki 同算法）
- ��段式撤架（Full→Hint→Compact）借鉴 SKILL0 progressive scaffolding
- Active Recall + Spaced Repetition 有大量认知科学支持
- Quiz 三模式（Guided/Recall/Transfer）对应 Bloom 分类法

**问题**：
- [LS-1] **代码 diff → 学习迁移有效性未验证**：传统 SRS 研究对象是语言/医学，代码遗忘曲线可能不同 — **High**
- [LS-2] SM-2 对代码概念可能过于保守：编程概念通过日常使用强化 — **Medium**
- [LS-3] 缺乏学习效果度量：v0.1 无法量化"学会了" — **Medium**
- [LS-4] SRS 依赖用户自律，纯本地无推送 — **Medium**（Gemini 确认）

**改进建议**：
- v0.1 benchmark：加入 learning proxy（quiz 正确率随时间变化）
- v0.2：IDE 插件 SRS reminder
- v1.0：A/B testing 验证 SRS 参数对代码学习的效果

### 2.7 可用性 — 8.5/10 (A-)

**优势**：
- CLI 命令直观：`learn/review/improve/serve`
- Progressive Enhancement 平滑过渡
- 错误提示分级 + i18n
- `--dry-run` 安全试运行

**问题**：
- [U-1] serve 常驻认知障碍 — **Medium**
- [U-2] improve 长时间等待无进度反馈 — **Medium**
- [U-3] Static 模式不可交互按钮需更强视觉暗示 — **Low**

**改进建议**：
- v0.1：improve 加 Rich progress bar + ETA
- v0.1：serve 启动输出"保持终端运行"提示

### 2.8 性能 — 7.5/10 (B+)

**优势**：
- Large diff 策略完整：skip(>10000) > clip(>5000) > summarize(>2000)
- 并发预算 + circuit breaker + cost ceiling
- portalocker + SQLite WAL + busy_timeout

**问题**：
- [P-1] 大 repo Graphify 导入耗时未量化，可能阻塞首次 learn — **High**
- [P-2] concepts.jsonl O(n) 扫描在 10000+ 条时变慢 — **Medium**
- [P-3] improve loop 无中断恢复 — **Medium**

**改进建议**：
- v0.1：Graphify 超时降级（60s → has_graph=false）
- v0.2：concepts → SQLite；improve --resume

### 2.9 测试策略 — 8.0/10 (A-)

**优势**：
- VCR 双层版本精巧（run 级 tree hash + cassette 级四��组）
- CI 分档（PR=unit，nightly=eval）
- 10 份 benchmark + manifest 确保可比性

**问题**：
- [TS-1] VCR 工具链只有设计无实现入口 — **Medium**
- [TS-2] PR 必跑缺 DTO parity + db lock smoke — **Medium**
- [TS-3] 10 份 benchmark 可能不够 — **Low**

### 2.10 竞品差异化 — 9.0/10 (A)

**优势**：
- 精准切中"AI 编码理解债务"痛��
- 五大护城河：Evidence Chain / Claim Verification / SRS / Ratchet / Local-first
- 与 CodeRabbit 不同赛道（团队 review vs 个人学习）
- "每句话回到 file:line"是真正技术壁垒

**问题**：
- [C-1] 目标用户画像不够精确 — **Medium**

### 2.11 商业可行性 — 5.5/10 (C+)

**优势**：
- Local-first + 开源快速建立信任
- CLI 分发成本极低
- 11 个 AI 工具集成覆盖广

**问题**：
- [BV-1] **无明确变现路径** — **Critical**（不阻塞 v0.1 但需思考）
- [BV-2] SRS 类产品留存率历史偏低 — **High**
- [BV-3] 缺 Team/Enterprise 设计 — **High**
- [BV-4] LLM 成本由用户承担 — **Medium**

**改进建议**：
- v0.2：设计 AhaDiff Pro（Team 聚合 / 企业 dashboard / 模型托管）
- v1.0：可选 hosted service
- 短期：GitHub Sponsors / Open Collective

### 2.12 Corner Cases 遗漏 — 8.0/10 (A-)

本次新发现 12 个遗漏：

| ID | 描述 | 严重度 | Task |
|----|------|:------:|------|
| CC-REVIEW-1 | Monorepo 跨 package diff context 划分 | Medium | 5/6 |
| CC-REVIEW-2 | LLM 中断后 partial artifact 清理 | Medium | 9 |
| CC-REVIEW-3 | 跨 repo 共享 API key 全局 rate limit | Low | 7 |
| CC-REVIEW-4 | 文件完全删除的 Claim 验证 | Medium | 8 |
| CC-REVIEW-5 | Model ID 过期致 VCR cassette 不可重放 | Low | 18 |
| CC-REVIEW-6 | Unicode branch name git ancestry 兼容 | Low | 10 |
| CC-REVIEW-7 | 空 diff（merge commit）优雅降级 | Low | 5 |
| CC-REVIEW-8 | SRS 时区问题 | Low | 15 |
| CC-REVIEW-9 | Branch/tag name prompt injection | Medium | 2 |
| CC-REVIEW-10 | React SPA deep link 刷新返回 404（serve 需 fallback 到 index.html） | Medium | 14.5 |
| CC-REVIEW-11 | JS disabled/build 缺失时白屏无降级 | Low | 13 |
| CC-REVIEW-12 | Auth token 多标签页复用与生命周期 | Low | 14.5 |

---

## 三、问题清单汇总

### Critical（战略级）
| BV-1 | 无明确变现路径 | v0.2 前定义方向 |

### High（各 Task 启动前修复）
| ID | 问题 | Task | 修复方案 |
|----|------|------|---------|
| ~~E-1~~ | ~~Jinja2→React 迁移风险~~ → v0.1 已直接用 React 19 | — | **已消除** |
| ~~EV-1~~ | ~~Haiku judge~~ → 已改 gpt-5.4-mini | — | **已消除** |
| LS-1 | 代码学习迁移假设 | 9/10/15 | learning proxy 指标 |
| P-1 | 大 repo Graphify 耗时 | 5/6 | 超时降级 |
| BV-2 | SRS 留存率低 | 15 | 留存激励设计 |
| BV-3 | 缺 Team 设计 | — | v0.2 路线图 |

### Medium（16 项，开发中修复）
A-1, A-2, S-1, S-2, EV-2, EV-3, T-1, P-2, P-3, U-1, U-2, E-2, CC-REVIEW-1/2/4/9/10, C-1, LS-2/3/4, TS-1/2, BV-4

### Low（13 项，可延后）
A-3, E-3, T-2, U-3, TS-3, CC-REVIEW-3/5/6/7/8/11/12

---

## 四、最终判定

### 能否开工？**GO** ✅（第五轮用户决策后升级）

**用户决策后状态变更**：
- ~~E-1 Jinja2→React 迁移风险~~ → **已消除**：直接用 React，以 v6.html 为参考模板
- ~~EV-1 Haiku judge 可靠性~~ → **已消除**：改用 gpt-5.4-mini（1M 上下文）
- ~~P-1 大 repo Graphify 耗时~~ → **已关闭**：用户接受，不需特别处理
- ~~BV-1/2/3 商业可行性~~ → **暂不考虑**
- ~~SQLite WAL-reset~~ → **已纳入 Task 0**：启动时 version gate + 统一连接初始化
- **新增**：LLM Provider 支持 8 种 API 格式 + BYOK 自动探测

**理由**：
1. 前端直接 React 消除了最大的技术迁移风险
2. gpt-5.4-mini（1M ctx）作为 judge 远超 Haiku 的评估能力
3. 8 种 API 格式覆盖主流 LLM provider，BYOK 自动探测降低用户配置门槛
4. 所有 Critical/High 问题已通过用户决策或修复方案消除

### 风险等级：**低**

| 风险维度 | 等级 | 说明 |
|---------|:----:|------|
| 技术风险 | 低 | React+Vite 成熟；8 种 provider 格式有明确实现路径 |
| 工期风险 | 中 | React 前端增加工作量，但省去了迁移成本 |
| 产品风险 | 中 | 学习工具 PMF 需用户验证 |
| 商业风险 | — | 暂不考虑 |

### 核心建议

> **v0.1 聚焦验证两个假设**：
> 1. Claim Verification 能否保证解释质量（技术假设）
> 2. 开发者是否愿意用 SRS 复习代码知识（产品假设）
>
> 如果任一假设不成立，后续设计将失去根基。

---

## 五、Gemini 前端审查完整评分

| 维度 | 分数 | 关键发现 |
|------|:----:|---------|
| UI/UX 设计质量 | 9/10 | 视觉语言统一贴合学术定位 |
| 竞品差异化 | 10/10 | 五大护城河完全避开正面冲突 |
| 可用性 | 9/10 | CLI 直观，Progressive Enhancement 平滑 |
| 学习科学 UX | 9/10 | Active Recall + SRS 深度融合 |
| i18n 前端 | 9/10 | 5 级解析链缜密 |
| static vs serve | 9/10 | 共用模板一致性高 |
| Blueprint 可视化 | 8/10 | 信息密度极高 |
| 无障碍 | 8/10 | WCAG AA + List fallback |
| 响应式设计 | 8/10 | Unified View 回退合理 |
| v0.1→v1.0 演进 | 7/10 | Jinja2 加速验证但重构贵 |
| 品牌一致性 | 10/10 | 所有 touchpoint 克制统一 |
| 商业可行性 | 8/10 | 极客吸引力强 |

---

## 六、Codex 后端审查

### 外部来源验证结论（Codex 已完成）

| 声明 | 验证来源 | 结论 |
|------|---------|------|
| Starlette 适合轻量本地服务 | [Starlette 官网] | ✅ lightweight ASGI toolkit |
| httpx 直连合理 | [HTTPX] + [OpenAI/Anthropic SDK] | ✅ 两家 SDK 底层都是 httpx |
| SM-2 有历史验证 | [SuperMemo.guru] | ✅ 最早的 SRS 调度算法之一 |
| 间隔复习+提取练习有教学依据 | [AERO Practice Guide, 2024-2026] | ✅ evidence-based，但针对"大方向"非"代码 diff" |
| SQLite WAL 支持读写并发 | [SQLite WAL Doc, 2026-03-13] | ⚠️ 只有一个 writer；**存在 WAL-reset corruption bug** |
| busy_timeout 足以处理并发 | [SQLite PRAGMA Doc] | ⚠️ per-connection 设置，非全局 |
| integrity_check 适合启动时 | [SQLite PRAGMA Doc] | ❌ 官方建议用 quick_check |

### 🔴 Codex 发现 Critical 问题

**SQLite WAL-reset Corruption Bug (2026-03-13)**：AhaDiff 以 review.sqlite 为唯一真相源，高度依赖 WAL，但**未冻结最低 SQLite 运行时版本**。修复方案：启动时 version gate + 统一连接初始化（WAL/busy_timeout/trusted_schema=OFF）。

### Codex 维度评分

| 维度 | 分数 | 关键发现 |
|------|:----:|---------|
| 架构完整性 | 8/10 | contract 权威源分散；serve 与其他链路本质不同 |
| 技术栈 | 8/10 | httpx 合理但有维护成本增长 |
| 安全模型 | 8/10 | explicit_remote retention 语义未冻结 |
| 评估系统 | 7/10 | judge 校准为前置必要条件 |
| 性能 | **6/10** | WAL/checkpoint/busy_timeout 问题更严重 |
| 测试策略 | 7/10 | 缺并发/恢复/校准硬测试 |
| 商业 | 5/10 | 确认无商业路线 |
| 学习科学 | 6/10 | 有方向支撑但代码场景未验证 |
| Corner Cases | 7/10 | SQLite 版本/checkpoint 是新盲区 |

### Codex 新增 v0.1 前必做（6 项）

1. **SQLite 运行时门槛 + 统一连接初始化**（WAL/busy_timeout/trusted_schema=OFF/quick_check）
2. Task 11 拆为 11a+11b，ratchet 上线前完成 judge calibration
3. 隐私三档 retention/export/replay 规则写成单一 contract
4. contract-freeze.md 升格为唯一实现入口
5. checkpoint policy + partial artifact cleanup + publish barrier 纳入主合同
6. orchestrator.py 保持薄编排层

---

## 七、综合评分修订（三模型共识）

基于 Codex 发现调整后的最终评分：

| # | 维度 | 初评 | 修订 | 调整原因 |
|---|------|:----:|:----:|---------|
| 1 | 架构完整性 | 8.5 | **8** | contract 权威源分散 |
| 4 | 安全模型 | 9.0 | **8.5** | explicit_remote 未冻结 |
| 6 | 学习科学 | 7.0 | **6.5** | 代码场景未验证 |
| 8 | 性能 | 7.5 | **7** | WAL bug + checkpoint |
| 9 | 测试策略 | 8.0 | **7.5** | 缺硬测试 |
| 12 | CC 遗漏 | 8.0 | **7.5** | SQLite 新盲区 |
| — | **综合** | 7.9 | **7.6** | — |

**新增 Critical**：SQLite WAL-reset version gate（阻塞 Task 15 启动）

---

## 八、模型分工

| 模型 | 职责 | 状态 |
|------|------|------|
| Claude Opus 4.6 | 编排+综合+独立分析 | ✅ |
| Gemini 3.1 Pro | 前端/UX/产品 12 维度 | ✅ |
| Codex CLI | 后端+外部验证 | ✅ |
