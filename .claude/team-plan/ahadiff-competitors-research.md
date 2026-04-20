# Team Research: 知返 AhaDiff 竞品对比研究

> 调研日期：2026-04-20
> 研究类型：ccg:team-research（约束集 + 成功判据）
> 数据来源：
> - 内部：`doc/` 10 份设计文档 + `.claude/team-plan/` 2 份 kickoff
> - 灵感项目源码：`repo/{autoresearch, darwin-skill, SkillCompass, graphify}/`
> - 外部竞品：10 款产品 × 5 象限（Exa + Grok + 官网 + GitHub）
> 衍生产出：
> - `doc/知返设计坐标.md`（内部设计坐标）
> - `doc/competitive-analysis-2026-04.md`（外部竞品对照）
> - 灵感项目实测报告（本文件「Part A.2」节汇总）

---

## 增强后的需求

**原始诉求**：对比竞品与本项目设计方案，基于真实代码+文档。

**增强后的结构化需求**：

| 维度 | 明确化 |
|------|--------|
| 目标 | 为知返 AhaDiff 绘制竞争地形图，产出差异化护城河清单 + 威胁预警 + 被否决路径 |
| 竞品范围 | ① 内部 `repo/` 下 4 个灵感项目真实源码；② 外部 5 象限真实商业/开源产品（AI Code Wiki / PR Review / 编程 SRS / Claude Skill / Diff-aware 工具） |
| 技术约束 | 禁止编造；每个竞品至少 1 条 URL 或 file:line；每条与本项目对比的陈述有双向证据（本项目设计文档 + 竞品源码/官网） |
| 对比维度 | 聚焦 Diff、Claim→证据绑定、Local-first、SRS/主动回忆、Git Ratchet、产品形态、授权模式 |
| 验收标准 | ≥10 个真实竞品、4 个差异化空白、3+ 威胁预警、完整的硬约束清单驱动后续 planning |
| 范围边界 | 不进入 planning / coding 决策；只产出约束集 |

---

## Part A：对比证据（压缩摘要）

### A.1 知返设计坐标（内部）

**核心定位**：local-first verified diff learning layer（`CLAUDE.md`:L5-7）。Code Wiki 解释整仓，知返解释**这次 diff**；且每句话回到代码证据（`doc/知返ahadiff改名后的后续方案.md`:L109-113）。

**七层架构**：Diff Capture → Context → Lesson Generation → Verification → Ratchet → Learning → Wiki+UI（`CLAUDE.md`:L44-54）。

**三文件契约**（概念改编自 autoresearch，非原版映射）：
- `program.md` 自然语言状态机（人写，agent 解释）
- `evaluator.py` IMMUTABLE 评估器，`evaluate_wiki(path) → wiki_score ∈ [0,1]`，stdout 固定 `^wiki_score:` 前缀
- `generator_prompt.md` agent 唯一可改资产

**Claim 五状态**：verified / weak / not_proven / contradicted / rejected。deterministic verifier（file/line/hunk/symbol + risky words）**先行**，LLM judge 只判因果合理性（`改名方案.md`:L457-492）。

**棘轮**：
- keep：`wiki_score_new > wiki_score_old` → `git commit`
- discard：否则 `git reset --hard HEAD~1`（默认）或 `git revert HEAD`（`--audit` 模式）
- Phase 2.5：**连续 2 个优化目标在首轮即无增益** → `git stash` → 从头重写 → 评估 → 超过则采纳（**完全源自 darwin-skill `SKILL.md`:L187**，非 autoresearch）

**8 维 rubric（完全自研，100 分）**：
accuracy(20) · evidence(18) · diff_coverage(14) · learnability(14) · quiz_transfer(10) · spec_alignment(10) · conciseness(8) · safety_privacy(6)
三档：PASS ≥80 / CAUTION 60-79 / FAIL <60（或 accuracy <14 硬 gate）。SkillCompass 原版 70/50，本项目调高为 80/60。

**Local-first 边界**：所有产物存 `.ahadiff/`；出本机仅 LLM API prompt，受 `.ahadiffignore` / `safety/redact.py` / `config.toml[offline_only]` / `audit.jsonl` 四道闸控制。

### A.2 灵感项目源码实测（`repo/`）

| 项目 | 产品形态 | 评估机制 | Ratchet 实现 | Claim 绑证据 | 学习闭环 | 与 AhaDiff 重叠度 |
|---|---|---|---|---|---|---|
| **autoresearch** | Python 脚本 `uv run train.py` | 单指标 `val_bpb`，Python 数学计算（`prepare.py:343-365`） | 自然语言指令（`program.md`:L103-104 git reset） | ❌ | ❌ | 仅骨架（三文件 + ratchet 概念） |
| **darwin-skill** | **纯 Markdown Skill**（零 `.py`/`.js`） | 8 维 LLM-as-judge（结构 60+效果 40） | `git revert HEAD`（SKILL.md:L165-170） | ❌ | ❌ | 仅骨架（Phase 2.5 触发条件） |
| **SkillCompass** | npm 包（Node.js）+ Skill | 6 维混合（D3 JS 代码 + D1/2/4/5/6 LLM judge） | SHA-256 snapshot + 回归 >2 分自动 discard（`eval-improve.md`:L89-101） | ❌ | ❌ | 仅骨架（阈值框架） |
| **graphify** | PyPI（`pip install graphifyy`）+ Skill | 无 rubric（只有边 confidence 标签） | ❌ | 部分（边 EXTRACTED/INFERRED/AMBIGUOUS） | 可选 `--wiki` | 互补（repo-map vs. diff-overlay） |

**关键结论：灵感项目 ≠ 竞品**。它们借的是"骨架"（三文件契约、ratchet 概念、rubric 框架、图谱），**没有一个评估"学习笔记质量"，也没有一个做 Diff→Learning 闭环**。

**需修订的 CLAUDE.md 表述**（源码实测发现 6 项）：

- **[M-1]** CLAUDE.md:L99「三文件契约=program.md+evaluator.py+generator_prompt.md」映射为 autoresearch 原版。**偏差**：autoresearch 原版是 `program.md + prepare.py + train.py`，AhaDiff 的 `evaluator.py`/`generator_prompt.md` 名称是自研命名，非原版映射
- **[M-2]** darwin-skill「连续 2 个 skill 在 round 1 就 break」在 `SKILL.md`:L187 精确对上 — ✅ 无需修订
- **[M-3]** SkillCompass 阈值 PASS≥70 / FAIL<50 在 `shared/scoring.md`:L28-35 对上 — ✅ 无需修订
- **[M-4]** darwin-skill「零可执行代码」经 Glob 验证 — ✅ 无需修订
- **[M-5]** graphify 是「repo-level map」经源码验证 — ✅ 无需修订
- **[M-6]** autoresearch「keep/discard 全在自然语言中」经 `program.md` 验证 — ✅ 无需修订

### A.3 外部真实竞品矩阵（`doc/competitive-analysis-2026-04.md`）

| 产品 | 象限 | 聚焦 Diff | Claim→证据 | Local-first | SRS | Ratchet | 授权 | Overlap 风险 |
|---|---|:---:|:---:|:---:|:---:|:---:|---|:---:|
| DeepWiki (Cognition) | Code Wiki | ❌ 整仓 | ❌ | ❌ SaaS | ❌ | ❌ | Freemium | 低 |
| Greptile | PR Review | ✅ PR | 部分 | ❌ SaaS $30 | ❌ | ❌ | SaaS | 中 |
| **CodeRabbit** | PR Review | ✅ PR | 部分 | 仅 Enterprise | ❌ | ❌ | SaaS $24/$48 | **中高** |
| Qodo PR-Agent | PR Review | ✅ PR | ❌ | ✅ 可自部署 | ❌ | ❌ | Apache-2.0 | 中 |
| Execute Program | SRS 学习 | ❌ 预制课程 | ❌ | ❌ SaaS | ✅ | ❌ | SaaS $19-39 | 低 |
| RemNote | 通用 SRS | ❌ 笔记 | ❌ | 部分离线 | ✅ SM-2/FSRS | ❌ | Freemium | 低 |
| Anthropic Skills | Skill 框架 | ❌ | ❌ | 部分 | ❌ | ❌ | 开源 | 低（生态入口） |
| awesome-claude-skills | Skill 汇编 | ❌ | ❌ | ✅ | ❌ | ❌ | MIT | 低（发行通道） |
| What The Diff | Diff 摘要 | ✅ PR | ❌ | ❌ SaaS | ❌ | ❌ | Freemium | 中 |
| Unblocked | 代码上下文 | 部分 | ❌ | ❌ SaaS | ❌ | ❌ | SaaS | 低中 |

**4 个差异化空白（护城河）**：
- **空白 A：Diff-to-Learning 闭环** — 没有产品把 git diff 作为输入同时输出 SRS 复习
- **空白 B：Claim-Evidence 结构化验证** — 所有竞品都是"自然语言带行号"，无人做 5 状态机
- **空白 C：Quality Ratchet for learning notes** — 仅 autoresearch 有 ratchet，但用于 ML 训练非学习笔记
- **空白 D：Local-first 学习数据** — PR Review 全是 SaaS；AhaDiff 学习数据留本机

---

## Part B：约束集

### B.1 硬约束（Hard Constraints）— 不可违反

| ID | 约束 | 来源 |
|---|---|---|
| HC-1 | 所有产物存 `.ahadiff/`；源码/diff/claim/quiz/review 不得上传第三方；仅 LLM API prompt 可出本机 | 内部设计：`CLAUDE.md`:L5；竞品对标：CodeRabbit/Greptile 全 SaaS |
| HC-2 | `evaluator.py` 必须 IMMUTABLE（agent 禁改）；`generator_prompt.md` 是唯一可改资产；三文件物理分离 | 内部设计：`设计思路.md`:L146-180；灵感项目：autoresearch `prepare.py` 同构 |
| HC-3 | 每条 claim 必须能回到 `file:line`，附 `source_hunks / changed_symbols / concepts`；deterministic verifier 先于 LLM judge | 内部设计：`改名方案.md`:L457-485；竞品空白 B |
| HC-4 | 评估模型 ≠ 生成模型；禁止同模型自评（生成用 Sonnet，judge 用 Haiku） | 内部设计：`CLAUDE.md`:L22 |
| HC-5 | 首版 UI 只用 Jinja2 静态 HTML；禁止 Next.js / React / Node 构建链 | 内部设计：`CLAUDE.md`:L30；`kickoff.md`:L40-43 |
| HC-6 | 禁止依赖 LiteLLM（2026-03-24 `1.82.7/8` 供应链事件） | 内部设计：`设计思路.md`:L10 |
| HC-7 | 禁止 f-string 拼长 prompt；prompt 必须独立 `.md` 文件 | 内部设计：`CLAUDE.md`:L52 |
| HC-8 | 所有 LLM 调用走 `llm/provider.py` 单一出口；禁止直接 `import anthropic/openai` | 内部设计：`CLAUDE.md`:L51 |
| HC-9 | Phase 2.5 触发条件：**连续 2 个优化目标在首轮即无增益**（sentence 对齐 darwin-skill `SKILL.md`:L187，非"连续 2 轮"、非"连续 3 次" | 灵感项目源码实测 [M-2] |
| HC-10 | `wiki_score ∈ [0,1]`，higher-better；stdout 协议固定 `^wiki_score:` 前缀 | 内部设计：`SOURCE-CODE-VERIFICATION-REPORT.md`:L53-54 |
| HC-11 | 不做整库 wiki（避免与 DeepWiki / Code Wiki 同质） | 内部设计：`改名方案.md`:L24-28；外部竞品：DeepWiki |
| HC-12 | 不做 PR summary（避免与 What The Diff 同质） | 内部设计：`最终方案.md`:2.2 段；外部竞品：What The Diff |
| HC-13 | 不做 SaaS / 云同步 / 团队 workspace；local-first 核心原则 | 内部设计：`最终方案.md`:产品原则段 |
| HC-14 | Verdict 三档阈值固定：PASS ≥80 / CAUTION 60-79 / FAIL <60；accuracy <14 硬 FAIL gate | 内部设计：`kickoff.md`:L33 |
| HC-15 | `results.tsv` 11 列 TAB 分隔：`timestamp / run_id / head_sha / base_sha / prompt_version / rubric_version / overall / verdict / status / weakest_dim / note` | 内部设计：`kickoff.md`:L33；`SOURCE-CODE-VERIFICATION-REPORT.md`:L222 |

### B.2 软约束（Soft Constraints）— 倾向性

| ID | 约束 | 来源 |
|---|---|---|
| SC-1 | 发行通道兼顾：PyPI `ahadiff` 包 + 发布到 `awesome-claude-skills` 生态作为 skill 入口 | 外部竞品：ComposioHQ/awesome-claude-skills 55K stars |
| SC-2 | 与 graphify 互补（repo map + AhaDiff diff overlay），非竞争关系；保留 `graphify-out/GRAPH_REPORT.md` 作 Context Layer 输入 | 灵感项目：graphify 定位、`改名方案.md`:L74-80 |
| SC-3 | SRS 算法采用 SM-2 或 FSRS，SQLite 存 `.ahadiff/review.db` | 外部竞品：RemNote 使用 SM-2/FSRS |
| SC-4 | `.ahadiffignore` 类比 `.gitignore` 过滤路径 | 内部设计：`设计思路.md` 配置层 |
| SC-5 | `audit.jsonl` 记录每次 LLM 调用（file/token/cost/provider） | 内部设计：`改名方案.md` Settings 段 |
| SC-6 | section helpfulness Δ（score_with_section − score_without_section）反哺棘轮，Δ ≤ ε 的章节压缩或删除（SKILL0 思想，扩展到 section 粒度） | 内部设计：`改名方案.md`:L145-165 |
| SC-7 | 品牌统一「知返 AhaDiff」，CLI 名 `ahadiff`，Logo 方向 `Δ知` 或 `Δ↺` | 内部设计：`改名方案.md`:L1-50 |

### B.3 依赖关系（Dependencies）— 影响实施顺序

| ID | 关系 | 原因 |
|---|---|---|
| DEP-1 | Diff Capture → Context Layer（graphify 可选） | 无 diff 无法构建 context |
| DEP-2 | Lesson Generation → Verification（必经） | 未经 Claim Verifier 的 lesson 不得进入 Ratchet |
| DEP-3 | Verification → Ratchet | `wiki_score` 决定 keep/discard |
| DEP-4 | Ratchet → Learning（只有 PASS/keep 的 lesson 才进 quiz/SRS） | 避免把低质笔记塞给 SRS 污染长期记忆 |
| DEP-5 | Learning → Wiki（section helpfulness 反哺棘轮） | `concepts.jsonl` append-only，`index.md` diff-aware merge |
| DEP-6 | 三文件契约先于任何其他模块落地 | `evaluator.py` 是所有 ratchet 的唯一真相源 |
| DEP-7 | `llm/provider.py` 先于所有 prompt 文件 | HC-8 要求 |

### B.4 风险（Risks）+ 缓解

| ID | 风险 | 概率 | 影响 | 缓解策略 |
|---|---|:---:|:---:|---|
| RISK-1 | **CodeRabbit 加入 SRS/learning 特性** → 直接进入 AhaDiff 领地 | 中 | 高 | 强调 local-first 个人工具定位；SRS+Claim-Evidence 组合是 CodeRabbit 企业 review 基因不会做的事；迅速建立 `awesome-claude-skills` 生态入口 |
| RISK-2 | Anthropic 官方推出「Diff Learning Skill」 | 低 | 极高 | 提前将 AhaDiff 作为 skill 发布，占据 `obra/superpowers` 同级生态位；突出 `evaluator.py` + ratchet 的非平凡实现 |
| RISK-3 | Greptile 「learns your codebase」扩展到人类学习 | 低 | 中 | Claim 五状态机差异化；Greptile 是 rule-adapt 而非人类学习 |
| RISK-4 | LLM 调用成本高（每条 diff 3-5 次 API：generation + verification + judge） | 中 | 中 | 小模型做 judge（Haiku），`offline_only = true` 支持本地模型；`audit.jsonl` 可视化成本 |
| RISK-5 | Claim verification 的 deterministic 规则不足以识别"虚构解释"，LLM judge 可能漂移 | 中 | 高 | risky words 扫描作为第三层；跨模型评估；人工标注 20 份 benchmark 做 judge 稳定性测试 |
| RISK-6 | 用户不愿意在本地跑 Python CLI（希望 IDE 插件） | 中 | 中 | 留 v1.0 做 VS Code 扩展；首版走 `ahadiff install claude/codex/cursor` 让 agent 代用户调用 |
| RISK-7 | 命名冲突遗留：GitHub 已有 `mohi-devhub/antivibe`（已通过改名 AhaDiff 规避），但需确保 `ahadiff` 的 PyPI/npm/GitHub 未被占 | 低 | 中 | 发布前冻结三站命名；`doc/知返ahadiff改名后的后续方案.md` 已记录 |
| RISK-8 | `repo/` 下 autoresearch 原版三文件结构与 CLAUDE.md 描述有偏差[M-1] | 已发生 | 低 | 本研究文件「Part A.2」已识别；需在后续 planning 更新 CLAUDE.md 归因表述 |

---

## Part C：成功判据

| ID | 可验证行为 | 验证方式 |
|---|---|---|
| OK-1 | 10 份 pinned diff 端到端验证，`wiki_score ≥ 0.80`（PASS 档） | `tests/integration/` 跑 `ahadiff learn` 读取 `score.json` |
| OK-2 | Claim 5 状态分类人工标注对齐 ≥ 85%（20 份 benchmark） | 对比 `claims.jsonl.status` 与人工标注 |
| OK-3 | Phase 2.5 真实触发率 ≤ 15%（避免滥用重写） | `results.tsv` 统计 `status=='phase2.5_rewrite'` 占比 |
| OK-4 | 4 个差异化空白（Diff-Learning / Claim-Evidence / Ratchet / Local-first）有可 demo 的最小实现 | 各写 1 段 5 分钟 screencast |
| OK-5 | SRS review 留存率（2 周后主动回忆正确率）≥ 50% | `review.db` 统计 `correct / total` |
| OK-6 | 离线模式（`offline_only=true`）可完整跑通 `learn/verify/improve/quiz/review` 5 个核心命令 | CI 用本地模型端点做 smoke test |
| OK-7 | 发布到 `awesome-claude-skills` 仓库并被列入索引 | PR 合入 `ComposioHQ/awesome-claude-skills` |
| OK-8 | 与 CodeRabbit/Greptile/Qodo 的对比页面明确列出 4 个差异化空白 | `doc/vs-others.md` 落地 |

---

## Part D：开放问题（需用户后续决策，但不 block 本研究）

| ID | 问题 | 建议默认值 | 需决策阶段 |
|---|---|---|---|
| Q-1 | 对 CodeRabbit 的竞争策略：是否在 README / 官网做"反广告"对比页？ | 建议：`doc/vs-others.md` 做客观对比，不贬竞品 | `/ccg:team-plan` |
| Q-2 | 离线模式（`offline_only`）优先级：P0（首版必交付）还是 P1（v0.2）？ | 建议：P0 关键词"support"（即有 code path 但不强制 CI 覆盖），P1 才做完整验证 | `/ccg:team-plan` |
| Q-3 | 发行策略：先 PyPI `ahadiff` 还是先 `awesome-claude-skills` skill 条目？ | 建议：同步 — PyPI 为主，skill 作为安装器 | `/ccg:team-plan` |
| Q-4 | 多模态 diff：图片/UI 改动如何学习？ | 建议：v0.1 仅支持文本 diff，多模态留 v1.0 | `/ccg:team-plan` |
| Q-5 | CLAUDE.md [M-1] 偏差（三文件契约归因）是否需修订描述？ | 建议：修订为「受 autoresearch 三文件思想启发，具体映射 AhaDiff 自研命名」 | 本次研究可直接修订 |
| Q-6 | 是否主动接入 `graphify`（SC-2）作为 Context Layer 依赖？ | 建议：可选依赖（via `ahadiff learn --with-graph`），非强制 | `/ccg:team-plan` |

**标注说明**：以上 Q-1~Q-6 不在本研究阶段消解，按 `/ccg:team-research` 定义，它们是后续 `/ccg:team-plan` 阶段需通过 `AskUserQuestion` 与用户对齐的决策点。本研究已把问题收敛到具体可决策的粒度。

---

## Part E：差异化一句话（给 README / 官网用）

> **DeepWiki 解释整仓，CodeRabbit 评审 PR，What The Diff 总结改动，Execute Program 教预制课程 — 而知返 AhaDiff 把你刚 AI 写完的 diff 变成带代码证据、经质量棘轮校验、能主动回忆的学习笔记，全本地运行。**

---

## Part G：真实代码可借鉴实现点（37 条 file:line 级）

> 关键区分：**Part A/B 讨论的是"抽象概念"**（三文件契约、ratchet、rubric 框架）——已写进 CLAUDE.md；**Part G 挖的是"具体实现手法"**——开发首版时明天就能抄的细节。
> 数据来源：亲自 Read/Grep 了 `repo/` 下 4 个项目 + Qodo PR-Agent 开源仓库（WebFetch raw 文件）。每条附真实 `file:line`。

### G.1 来自 autoresearch（6 条）

| # | 借鉴点 | 真实位置 | 优先级 |
|:--:|---|---|:--:|
| 1 | **`^key:value` stdout 协议**输出评估指标（vs JSON/exit code） | `train.py:L622-L630` · `program.md:L61-L63` | P0 |
| 2 | **5 列 TSV 日志**固定：`commit val_bpb memory_gb status description`（tab 分隔避免 description 中 comma） | `program.md:L67-L88` | P0 |
| 3 | `gc.disable()` + 定期 `gc.collect()`（Python GC 卡 500ms） | `train.py:L592-L598` | P2 |
| 4 | **时间预算制** `TIME_BUDGET=300` + `progress=elapsed/budget` 线性调度 | `train.py:L29-L30, L518-L525` | P1 |
| 5 | `NEVER STOP` 自主循环声明 + 10min 超时 kill 规则 | `program.md:L111-L114` | P1 |
| 6 | **redirect stdout** `uv run ... > run.log 2>&1`（禁用 tee 防输出淹没 agent context） | `program.md:L99` | P0 |

### G.2 来自 darwin-skill（6 条）

| # | 借鉴点 | 真实位置 | 优先级 |
|:--:|---|---|:--:|
| 7 | **8 维加权 Rubric**（结构 60+效果 40）+ 改进必须严格 `>` 而非 `≥` | `SKILL.md:L29-L51` | P0 |
| 8 | `test-prompts.json` 格式化测试用例集 `[{id, prompt, expected}]` | `SKILL.md:L87-L95` | P1 |
| 9 | results.tsv 增 **`eval_mode` 列**（`full_test` / `dry_run` 区分降级） | `SKILL.md:L232-L239` | P0 |
| 10 | 文件体积 >150% 阈值 → 拒绝提交，回退精简 | `SKILL.md:L282` | P1 |
| 11 | **异常处理决策表**（9 场景：不在 git / TSV 损坏 / 分支冲突 / revert 失败…，绝不静默跳过） | `SKILL.md:L270-L286` | P0 |
| 12 | HTML 成果卡片 3 种主题（`#swiss/#terminal/#newspaper` URL hash 切换）+ `screenshot.mjs` | `SKILL.md:L356-L364` | P2 |

### G.3 来自 SkillCompass（10 条）

| # | 借鉴点 | 真实位置 | 优先级 |
|:--:|---|---|:--:|
| 13 | **`eval-result.json` Schema** 强制 `{score, max, details, sub_scores, issues, metadata}` + `verdict` 枚举 `PASS|CAUTION|FAIL` + 自动 `weakest_dimension` | `schemas/eval-result.json:L1-L224` | P0 |
| 14 | **D3 Security Gate**：critical 直接 `score=0, verdict=FAIL`（不论 overall） + 扣分阶梯 critical→0 / high→-4 / medium→-1 / low→-0.5 | `shared/scoring.md:L40-L46` | P0 |
| 15 | **减分制评分 + fatal cap**：`Math.max(0, Math.min(10, 10 − errors×3 − warnings×1.5 − infos×0.5))` + fatal 错误锁上限 | `lib/structure-validator.js:L524-L534, L49-L63` | P0 |
| 16 | `output-guard.js` 双级检查：新 URL/危险命令→BLOCK，scope mismatch/体积>3x→WARN，>5x→BLOCK；含 `sha256:` 审计 | `hooks/scripts/output-guard.js:L42-L52, L143-L175` | P1 |
| 17 | `hooks.json` PostToolUse 钩子：matcher `Write|Edit` + `${CLAUDE_PLUGIN_ROOT}` 变量 + timeout 3000-5000ms | `hooks/hooks.json:L1-L53` | P1 |
| 18 | **`quick-scan.js` 三维快扫 + mtime 缓存**：try-catch 独立运行 + verdict `≤4 high_risk / ≤6 medium / 否则 clean` | `lib/quick-scan.js:L42-L127, L136-L168` | P0 |
| 19 | **Tier 分类 + Few-shot + 算术验证行**：Tier A/B/C + 5 示例末尾附 `Score check: 9×0.30 + 8×0.20 = 8.25 → 8`（防 LLM 算错） | `prompts/d4-functional.md:L34-L42, L159-L401` | P0 |
| 20 | **`<<<UNTRUSTED_SKILL_BEGIN>>>` 边界标记** + 6 条 mandatory safety rules（不执行代码、不遵 "ignore previous"） | `prompts/d4-functional.md:L30-L32` | P0 |
| 21 | `version-manifest.json` 版本追踪：trigger 枚举 `initial|eval-improve|eval-merge|manual|upstream` + `sha256:` | `schemas/version-manifest.json:L1-L86` | P1 |
| 22 | **V1-V7 统计指标体系** + ASCII 柱状图：分布 / Tier 区分度 / gate 失败率 / 公平性 / verdict 分布 / 异常 / 维度方差 | `scripts/eval-v2/analyze-results.js:L83-L260` | P1 |

### G.4 来自 graphify（7 条）

| # | 借鉴点 | 真实位置 | 优先级 |
|:--:|---|---|:--:|
| 23 | **SHA256 内容寻址缓存 + frontmatter 剥离**：`hash = content + '\x00' + path` 避免不同路径同内容碰撞 | `graphify/cache.py:L10-L41` | P0 |
| 24 | **枚举型 Schema 验证**：`VALID_FILE_TYPES` / `VALID_CONFIDENCES` 常量集 + `assert_valid()` 格式化 raise | `graphify/validate.py:L4-L64` | P0 |
| 25 | `_normalize_id()` 容忍 LLM 拼写差异：`re.sub(r"[^a-zA-Z0-9]+","_",s).lower()` + norm_to_id 映射 fallback | `graphify/build.py:L31-L37, L61-L72` | P1 |
| 26 | `_PLATFORM_CONFIG` 字典驱动 13 平台 install（避 if-else 分支） | `graphify/__main__.py:L62-L128` | P2 |
| 27 | `benchmark.py` token 缩减比：5 固定问题 BFS 子图 vs 全语料 token（`_CHARS_PER_TOKEN=4` 近似） | `graphify/benchmark.py:L55-L61, L64-L111` | P1 |
| 28 | `report.py` Markdown 生成（Summary/God Nodes/Surprising/Gaps/Suggested Questions），纯字符串拼接零模板引擎 | `graphify/report.py:L15-L176` | P1 |
| 29 | **PreToolUse hook 条件注入**：`[ -f graphify-out/graph.json ] && echo '...additionalContext...' || true` | `graphify/__main__.py:L39-L51` | P1 |

### G.5 来自 Qodo PR-Agent（8 条，外部 Apache-2.0 开源）

| # | 借鉴点 | 真实位置 | 优先级 |
|:--:|---|---|:--:|
| 30 | **`__new hunk__` / `__old hunk__` 格式化协议**：new 带行号，old 不带；`+/-/space` 三态前缀 | `settings/pr_reviewer_prompts.toml` | P0 |
| 31 | **YAML 输出（非 JSON）+ Pydantic 验证**：prompt 强约束 "valid YAML, and nothing else" + `class Review(BaseModel)` | `settings/pr_reviewer_prompts.toml` | P0 |
| 32 | **`OUTPUT_BUFFER_TOKENS_SOFT=1500 / HARD=1000` 双缓冲区**：`total + SOFT < max` 返回完整，超出触发 `large_patch_policy` | `algo/pr_processing.py` | P0 |
| 33 | **`large_patch_policy: skip|clip`** 降级策略：skip 记 warning，clip 用 `clip_tokens()` 截断到剩余 budget | `algo/pr_processing.py` | P0 |
| 34 | `sort_files_by_main_languages`：检测 PR 主语言后排序，token 预算优先给核心代码 | `algo/pr_processing.py` | P1 |
| 35 | **`key_issues_to_review` 附 `start_line`/`end_line`**：`{relevant_file, issue_header, issue_content, start_line, end_line}` 便 IDE 跳转 | `settings/pr_reviewer_prompts.toml` | P0 |
| 36 | `score: 0-100` + `estimated_effort_to_review: 1-5` 双正交维度（质量 vs 审查难度） | `settings/pr_reviewer_prompts.toml` | P1 |
| 37 | **Jinja2 条件渲染 prompt**：`{%- if require_score %}` 动态裁剪输出字段（`--no-security` 等 flag 可用） | `settings/pr_reviewer_prompts.toml` | P1 |

### G.6 Top 10 必抄清单（按 AhaDiff 开发顺序）

| 排名 | 借鉴编号 | 模块 | 一句话 |
|:---:|:---:|---|---|
| 1 | #30 | diff 预处理 | hunk 格式化输入 — AhaDiff 的 Layer 1 Diff Capture 必须做的第一步 |
| 2 | #20 | Layer 3 Generation | `<<<DIFF_BEGIN>>>` 边界标记隔离，防 prompt injection |
| 3 | #31 + #24 | Layer 3/4 输出格式 | YAML 输出 + 枚举验证双保险 |
| 4 | #13 | Layer 4 Verification | `eval-result.json` Schema 强制结构化 |
| 5 | #14 + #15 | Layer 5 Ratchet | 减分制 + gate 维度 = 评分引擎核心 |
| 6 | #19 | Layer 3 Generation | few-shot + 算术验证行防 LLM 算错加权分 |
| 7 | #32 + #33 | Layer 2 Context | 双缓冲区 token 预算 + skip/clip 大 diff 降级 |
| 8 | #1 + #2 | Layer 5 Ratchet | `^wiki_score:` + TSV 11 列日志 |
| 9 | #23 | 跨层 | SHA256 内容寻址缓存，避免重复 LLM 调用 |
| 10 | #11 | 跨层 | 异常处理决策表，鲁棒性基线 |

### G.7 8 类维度统计

| 维度 | 条数 | 代表实现 |
|------|:---:|---|
| 数据结构 / Schema | 8 | #2 TSV · #9 eval_mode · #13 JSON Schema · #21 manifest · #24 枚举 · #31 YAML · #35 行号 · #36 双分值 |
| Prompt 工程 | 5 | #19 few-shot · #20 边界标记 · #30 hunk · #37 Jinja2 · #31 YAML 约束 |
| CLI / 配置 | 2 | #26 平台字典 · #33 `--large-diff-policy` |
| 评估器实现 | 6 | #7 加权 rubric · #14 gate · #15 减分制 · #18 快扫 · #22 V1-V7 · #34 按语言排序 |
| 测试 / Mock | 2 | #8 test-prompts · #22 analyze-results |
| 错误处理 / 成本 | 7 | #3 GC · #4 时间预算 · #5 NEVER STOP + 超时 kill · #10 150% · #11 异常表 · #16 output-guard · #32 双缓冲区 |
| 文件组织 / Manifest | 5 | #17 hooks · #23 SHA256 · #25 ID 归一化 · #27 benchmark · #28 report |
| UX / 输出 | 4 | #1 stdout 协议 · #6 redirect · #12 HTML 卡片 · #29 PreToolUse |

### G.8 五项目最强借鉴维度（一句话总结）

| 项目 | 最强点 | 何时用 |
|------|--------|--------|
| **autoresearch** | **协议化 IO**：KV stdout + TSV 日志 + redirect | evaluator 层、日志层首选 |
| **darwin-skill** | **鲁棒性工程**：Rubric + 异常决策表 + eval_mode 降级 | Layer 5 + SKILL.md 指令设计 |
| **SkillCompass** | **Schema + 评估引擎**：JSON Schema + 减分制 + gate + few-shot 校准 | Layer 4 Verification 核心 |
| **graphify** | **缓存 + 容错**：SHA256 内容寻址 + ID 归一化 + 枚举验证 | 跨层共享基础设施 |
| **Qodo PR-Agent** | **prompt + token 工程**：hunk 格式 + YAML 输出 + 双缓冲区 + 行号定位 | Layer 1/2/3 全面采用 |

---

## Part F：衍生产出清单

| 文件 | 用途 | 状态 |
|---|---|---|
| `doc/知返设计坐标.md` | 内部设计 10 维坐标（含 file:line 出处） | 已生成 |
| `doc/competitive-analysis-2026-04.md` | 外部 10 款竞品 × 5 象限全量矩阵 | 已生成 |
| `.claude/team-plan/ahadiff-competitors-research.md` | **本文件**：约束集 + 成功判据 | 已生成 |

---

**下一步**：运行 `/clear` 后执行 `/ccg:team-plan ahadiff-competitors-research` 进入规划阶段。规划阶段需用 AskUserQuestion 消解 Q-1 ~ Q-6。
