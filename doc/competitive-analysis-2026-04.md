## 外部竞品对照

> 调研日期：2026-04-20 | 数据来源：各产品官网 / GitHub / 第三方评测

### 象限 1：AI Code Wiki

#### 1.1 DeepWiki (Cognition)
- URL: https://deepwiki.com / https://github.com/CognitionAI/deepwiki
- 模式: 免费（公开仓库）；私有仓库需 Devin 账号（SaaS）
- 输入/输出: 输入整个 GitHub 仓库，输出结构化交互式文档 Wiki + 可对话问答
- Local-first: No（代码上传至 Cognition 服务器索引，官网："We've already indexed over 50,000 of the top public GitHub repos"）
- Claim 绑证据: No — 生成文档是仓库级概览，无逐句 claim → file:line 证据绑定
- Ratchet: No
- SRS: No
- Overlap: **中**（同为"AI 解释代码"，但解释整仓结构而非单次 diff 改动）

#### 1.2 Greptile
- URL: https://www.greptile.com
- 模式: SaaS，$30/seat/月（含 50 次 review），超出 $1/次
- 输入/输出: 输入 PR diff + 全仓代码图谱，输出 PR 评论（含 bug 检测、置信度评分、序列图）
- Local-first: No（SaaS，构建仓库图索引在云端）
- Claim 绑证据: 部分 — review 评论引用具体文件和代码行，但不是结构化 claim-evidence 格式
- Ratchet: No（有 custom rules 和 learning 机制，但非 git ratchet）
- SRS: No
- Overlap: **中**（聚焦 PR review 而非学习；有代码引用但不做学习闭环）

---

### 象限 2：AI 代码 Review / PR 解释

#### 2.1 CodeRabbit
- URL: https://coderabbit.ai
- 模式: SaaS，Pro $24/user/月（年付），Pro Plus $48/user/月，Enterprise 支持自部署
- 输入/输出: 输入 PR diff，输出逐行 review 评论 + 变更摘要 + 架构图 + 1-click AI 修复
- Local-first: No（Enterprise 有 self-hosting 选项，但标准版为 SaaS）。官网："SOC 2 Type II certified"
- Claim 绑证据: 部分 — 逐行评论自然引用代码位置，但无结构化 claim 状态（verified/contradicted）
- Ratchet: No
- SRS: No
- Overlap: **中高**（最接近的竞品之一：聚焦 diff、生成摘要和 walkthrough；但目标是"review 质量"而非"开发者学习"）

#### 2.2 Qodo PR-Agent (原 CodiumAI)
- URL: https://github.com/qodo-ai/pr-agent（Apache-2.0 开源，11K+ stars）
- 模式: 开源（自部署免费）+ Qodo Merge 商业版（SaaS）
- 输入/输出: 输入 PR diff，输出 `/describe`（自动描述）、`/review`（逐行 review）、`/improve`（改进建议）、`/implement`（将 review 转代码）
- Local-first: 可自部署，代码不必上传第三方
- Claim 绑证据: No — 生成建议指向代码位置，但无结构化 claim-evidence 体系
- Ratchet: No
- SRS: No
- Overlap: **中**（开源可自部署是优势，但同样不做学习/SRS 闭环）

---

### 象限 3：编程学习 SRS / 主动回忆

#### 3.1 Execute Program
- URL: https://www.executeprogram.com
- 模式: SaaS 订阅，$39/月（月付）/ $19/月（年付）。16 节免费试用
- 输入/输出: 输入为预制课程（TypeScript、Python、SQL 等 10 门），输出为交互式代码练习 + SRS 复习
- Local-first: No（纯 Web SaaS）
- Claim 绑证据: No — 课程内容由 Gary Bernhardt 手工编写，非基于用户代码
- Ratchet: No（有课程进度追踪，非 git ratchet）
- SRS: **Yes** — 核心卖点。官网："Later, short reviews reinforce your new skills"，使用间隔重复算法
- Overlap: **低**（SRS 理念相同，但输入完全不同：预制课程 vs. 真实 diff）

#### 3.2 RemNote
- URL: https://www.remnote.com
- 模式: Freemium，Pro $6/月。面向学生市场
- 输入/输出: 输入为用户笔记/PDF，输出为闪卡 + SRS 复习 + 概念图 + 考试调度
- Local-first: 有离线模式（Pro 功能），但核心为云同步
- Claim 绑证据: No — 通用笔记工具，不解析代码
- Ratchet: No
- SRS: **Yes** — 支持 SM-2 和 FSRS 算法。官网："Cards resurface at the optimal time for retention"
- Overlap: **低**（SRS + 概念关联的产品形态可参考，但不面向代码/diff 场景）

---

### 象限 4：Claude Skill / Self-improving Agent 框架

#### 4.1 Anthropic 官方 Agent Skills
- URL: https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview / https://github.com/anthropics/skills
- 模式: 开源（SKILL.md 格式），平台内置 + 社区贡献
- 输入/输出: SKILL.md 文件提供领域指令，Claude 在 VM 中执行。预置 Skills 包括 docx/pptx/pdf/xlsx 处理
- Local-first: Skills 文件本地存储，但执行依赖 Claude 平台（API 或 claude.ai）
- Claim 绑证据: No — Skills 是通用指令框架，不含 claim verification 机制
- Ratchet: No
- SRS: No
- Overlap: **低**（AhaDiff 的 SKILL.md 格式灵感来源，但 Skills 是通用 agent 扩展框架，非学习工具）

#### 4.2 awesome-claude-skills (ComposioHQ)
- URL: https://github.com/ComposioHQ/awesome-claude-skills（55K stars）/ https://github.com/travisvn/awesome-claude-skills（11K stars）
- 模式: 开源社区汇编，MIT
- 输入/输出: 社区 SKILL.md 汇总索引；包括 obra/superpowers（20+ 核心 skills）、TDD、deep-research 等
- Local-first: Yes（文件系统级别的 skill 定义）
- Claim 绑证据: No
- Ratchet: No
- SRS: No
- Overlap: **低**（生态入口而非竞品；AhaDiff 可以作为一个 skill 发布到此生态）

---

### 象限 5：Diff-aware 文档 / 变更日志工具

#### 5.1 What The Diff
- URL: https://whatthediff.ai
- 模式: Freemium SaaS，按 token 计费
- 输入/输出: 输入 PR diff（GitHub/GitLab API），输出纯文本变更描述 + 公共 changelog + 周报
- Local-first: No（官网 FAQ："We don't store your code"，但处理通过第三方 API）
- Claim 绑证据: No — 生成自然语言摘要，无结构化证据链
- Ratchet: No
- SRS: No
- Overlap: **中**（同为"解释 diff"，但输出仅为简短摘要，无学习笔记/quiz/SRS）

#### 5.2 Unblocked
- URL: https://getunblocked.com
- 模式: Free tier + 商业版（SaaS），面向企业 coding agent 上下文增强
- 输入/输出: 输入为 code + PRs + Slack/Teams 对话 + Jira/Linear + Confluence/Notion，输出为 coding agent 的上下文层
- Local-first: No（云端构建知识图谱）。官网："Unblocked connects your code, docs, and the conversations to build a model of your engineering system"
- Claim 绑证据: No — 提供上下文检索而非结构化 claim 验证
- Ratchet: No
- SRS: No
- Overlap: **低中**（解决"理解代码历史决策"的问题，但目标用户是 coding agent 而非人类学习者）

---

### 综合竞品矩阵

| 产品 | 聚焦 Diff | Claim 绑证据 | Local-first | SRS/主动回忆 | Ratchet | 与 AhaDiff 差异化风险 |
|------|:---------:|:-----------:|:-----------:|:-----------:|:-------:|:-------------------:|
| DeepWiki | No（整仓） | No | No | No | No | 低 |
| Greptile | Yes（PR） | 部分 | No | No | No | 中 |
| CodeRabbit | Yes（PR） | 部分 | 仅 Enterprise | No | No | 中高 |
| Qodo PR-Agent | Yes（PR） | No | 可自部署 | No | No | 中 |
| Execute Program | No（预制课程） | No | No | **Yes** | No | 低 |
| RemNote | No（通用笔记） | No | 部分 | **Yes** | No | 低 |
| Anthropic Skills | No | No | 部分 | No | No | 低 |
| awesome-skills | No | No | Yes | No | No | 低 |
| What The Diff | Yes（PR） | No | No | No | No | 中 |
| Unblocked | 部分（PR 历史） | No | No | No | No | 低中 |

---

### 没填满的空白（差异化机会）

- **空白 A — Diff-to-Learning 闭环**：没有任何产品把 git diff 作为输入，同时输出带 SRS 复习的学习笔记。CodeRabbit/Greptile 做 review 但不做学习，Execute Program 做 SRS 但不接真实 diff。
- **空白 B — Claim-Evidence 结构化验证**：所有竞品的代码引用都是"自然语言附带行号"，无一做到 claim 四状态（verified / weak / not_proven / contradicted）+ 结构化 evidence chain。
- **空白 C — 质量棘轮 (Git Ratchet)**：无竞品使用 git commit/reset 机制保证输出质量单调递增。autoresearch 有此机制但用于 ML 训练而非学习笔记。
- **空白 D — Local-first 学习数据**：PR review 工具多为 SaaS；学习笔记数据留在本地是隐私敏感用户的差异化卖点。

### 威胁预警（有高 overlap 的产品）

- **CodeRabbit**：最大重叠 — 已覆盖"PR diff 摘要 + walkthrough + 架构图"。若 CodeRabbit 增加 learning 功能（quiz/SRS），将直接进入 AhaDiff 领地。**知返应强调**：(1) claim-evidence 验证不是"review 评论"而是"可追溯学习笔记"；(2) SRS 复习闭环是 CodeRabbit 产品基因中不会做的事。
- **Greptile**：如果 Greptile 的 "learning" 功能（官网提到 "Greptile learns your codebase over time"）扩展到面向开发者个人学习，可能出现竞争。当前其 learning 仅指 review 规则自适应，非人类学习。
- **Unblocked**：如果 Unblocked 从"给 agent 提供上下文"扩展到"给人类解释变更历史"，可能部分重叠。但其 SaaS 模式和企业定位与 AhaDiff 的 local-first 个人工具定位差异明显。
