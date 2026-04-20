# Team Research: AhaDiff AST/LSP 集成可行性

> 调研日期：2026-04-20
> 研究类型：ccg:team-research（约束集 + 成功判据）
> 数据来源：
> - 本地源码：`repo/graphify/graphify/extract.py`（tree-sitter AST 实现）
> - 远程源码：`qodo-ai/pr-agent`（GitHub 官方仓，Codex 远程核验）
> - 远程源码：`Aider-AI/aider/aider/repomap.py`（GitHub，Claude 核验）
> - 外部文档：CodeRabbit ast-grep docs、Greptile graph-based context docs
> - 本地源码：`repo/SkillCompass`、`repo/autoresearch`（均不涉及 AST）
> 模型协作：Codex（竞品源码深度分析）+ Claude（外部搜索 + 综合）

---

## 增强后的需求

| 维度 | 明确化 |
|------|--------|
| 目标 | 对比竞品在 diff→symbol 链路中的 AST/LSP/tree-sitter 真实实现，输出约束集验证 AhaDiff 三层方案 |
| 竞品范围 | 源码实测：graphify（repo/）、PR-Agent（GitHub远程）、aider（GitHub远程）；文档核验：CodeRabbit、Greptile |
| 对比维度 | symbol 提取方法、跨文件能力、多语言覆盖、CLI 启动开销、依赖链 |
| 验收标准 | 硬/软约束集 + 竞品对照表 + AhaDiff 方案遗漏能力清单 |

---

## Part A：竞品真实代码分析

### A.1 竞品 AST/LSP 使用对照表

| 竞品 | Symbol 提取 | tree-sitter | LSP | 多语言 | 依赖链 | 证据 |
|------|-----------|:-----------:|:---:|--------|--------|------|
| **aider** | tree-sitter AST | **核心依赖** | 否 | 20+ 语言 | `grep-ast`, `tree-sitter`, `py-tree-sitter-languages`/`tree-sitter-language-pack`, `pygments`, `networkx` | `aider/repomap.py:1-30` imports tree_sitter + grep_ast |
| **graphify** | tree-sitter AST + LLM 语义 | **核心依赖** | 否 | 20+ 语言 | `tree-sitter>=0.23.0` + 20 grammar 包 | `repo/graphify/graphify/extract.py:1,654-674` |
| **Qodo PR-Agent** | **纯 regex** | 否 | 否 | 扩展名映射 | `PyGithub`, `Dynaconf` | `pr_agent/algo/language_handler.py:37-83`, `pyproject.toml` 无 tree-sitter |
| **CodeRabbit** | ast-grep (Rust) | 间接（ast-grep 基于 tree-sitter） | 否 | 22+ 语言 | 外部 ast-grep binary | `docs.coderabbit.ai/tools/ast-grep` |
| **Greptile** | 图索引 + 语义嵌入 | 未公开 | 未公开 | SaaS 黑盒 | SaaS 服务 | `greptile.com/docs/how-greptile-works/graph-based-codebase-context` |
| **SkillCompass** | **无** | 否 | 否 | N/A | `js-yaml` | `repo/SkillCompass/lib/*.js` 均为 YAML/frontmatter 解析 |
| **autoresearch** | **无** | 否 | 否 | N/A | `torch`, `numpy` | `repo/autoresearch/prepare.py` 只有 argparse |
| **Codex CLI** | LLM 内建理解 | 否 | 否 | LLM 覆盖 | GPT-5.x | 无 AST 依赖，靠模型能力 |

### A.2 关键发现（基于真实代码）

**发现 1：tree-sitter 是 AI 代码工具的事实标准**
- aider（43K stars）和 graphify 都以 tree-sitter 为**核心依赖**做 symbol 提取
- aider 明确写道："tree-sitter replaces the ctags-based map"，从 ctags→tree-sitter 是技术演进方向
- graphify `extract.py` 第 1 行："Deterministic structural extraction from source code using tree-sitter"
- 两者都不用 LSP

**发现 2：PR-Agent 完全不用 AST，但并不需要 symbol 提取**
- PR-Agent 的核心是 diff→LLM review，不做 symbol 级验证
- 它的"语言"信息来自 git provider API + 扩展名映射（`language_handler.py:42-83`）
- 它的 hunk context 来自 git unified diff header 自带的 `section_header`
- **AhaDiff 与 PR-Agent 的根本差异**：AhaDiff 需要 deterministic verifier 验证"symbol 是否存在"，PR-Agent 不需要

**发现 3：CodeRabbit 用 ast-grep（底层是 tree-sitter）做结构化 lint**
- ast-grep 是 Rust 工具，使用 tree-sitter parser 做 AST 匹配
- CodeRabbit 用它做安全规则和代码模式检查，不是 symbol 提取
- 支持 22 种语言的 AST 规则匹配

**发现 4：没有任何竞品在核心路径使用 LSP**
- 所有 5 个有源码可查的竞品均不使用 LSP
- LSP 的跨文件语义能力虽强，但 CLI 工具的启动/通信开销使其不被采纳

**发现 5：graphify 的 tree-sitter 集成复杂度真实可观**
- `extract.py` 1400+ 行，含 20+ 语言的 `LanguageConfig`
- 每种语言需要定义 `class_types/function_types/import_types/call_types` 等 frozenset
- 需要处理 per-language 的 name resolution、body detection、import handler 差异
- `pyproject.toml` 声明 20+ grammar 包依赖

---

## 约束集

### 硬约束
- [HC-1] **Unified diff 必须是主真相源** — PR-Agent 和 graphify 都证明：AST 增强 symbol/evidence，但不能取代 diff parser。来源：Codex（PR-Agent 源码）
- [HC-2] **repo 级 AST 需要 whole-file 访问** — graphify 的跨文件 import/call resolution 依赖完整文件集合，纯 patch（Level 1）无法使用 AST。来源：Codex（graphify extract.py:929-1077）
- [HC-3] **LSP 不进核心路径** — 所有 5 个可查竞品均未在核心链路使用 LSP。CLI 冷启动 + 进程管理 + workspace 同步成本与 local-first 冲突。来源：Claude+Codex 一致
- [HC-4] **多语言 tree-sitter 不是"加一个库"** — graphify 证明需要 20+ grammar 包 + per-language LanguageConfig。来源：Codex（graphify pyproject.toml:13-37）
- [HC-5] **AST parse 失败不能阻断主链路** — aider 用 pygments fallback；graphify 返回 `{"nodes":[], "edges":[], "error": ...}`。来源：Claude（aider repomap.py）、Codex（graphify extract.py:666-667）
- [HC-6] **v0.1 现有计划冻结在 Python AST + regex fallback** — `.claude/team-plan/ahadiff-v01-kickoff.md:147-151`。来源：Codex

### 软约束
- [SC-1] **先 cheap routing，再 expensive parsing** — PR-Agent 先过滤 bad-extension/lockfile/binary，再做 token 预算，最后才是内容分析。来源：Codex
- [SC-2] **AST 应服务 changed symbols + evidence anchoring，不替代 diff parser** — 来源：Claude+Codex 一致
- [SC-3] **repo graph 是外部 overlay，不是 AhaDiff 自建** — AhaDiff 是 diff-level learning layer，不应滑向 graphify 式 repo mapper。来源：Codex
- [SC-4] **tree-sitter 的引入时机应与多语言需求挂钩** — v0.1 只服务 Python diff 时用 Python `ast` 足够。来源：Claude

### 依赖关系
- [DEP-1] bad-extension 过滤 → token 预算 → symbol 提取：必须先 routing 再 parsing
- [DEP-2] Python `ast` provider → SymbolExtractor 接口 → tree-sitter provider：接口先行
- [DEP-3] Graphify overlay → AhaDiff graph import：graphify 的 tree-sitter 能力通过 overlay 间接可用

### 风险
- [RISK-1] v0.1 只有 Python ast，JS/TS/Go diff 的 symbol 质量弱 — 缓解：regex fallback + 明确标注 `extractor: regex` 降低置信度
- [RISK-2] 过早引入 tree-sitter 全家桶抬高安装体积和 CI 复杂度 — 缓解：v0.2 only + optional extra
- [RISK-3] 没有 PR-Agent 式 token/clip/skip 机制时，大 diff 会先在预算层失败 — 缓解：先实现 #32/#33 借鉴点
- [RISK-4] LSP 无严格降级路径会被语言服务器可用性反向绑架 — 缓解：opt-in only + silent fallback

---

## 成功判据

- [OK-1] 核心 learn 主链在没有 AST/LSP 时也能完整工作；AST/LSP 只增强 metadata，不阻断 diff→lesson→claim→quiz
- [OK-2] v0.1 至少让 Python changed symbols、line_map、hunk_hash 稳定可观测；parse 失败时 regex fallback 不中断主链
- [OK-3] v0.2 tree-sitter 先覆盖 JS/TS/Go/Rust，并证明 symbol recall/precision 比 regex 提升
- [OK-4] 具备 PR-Agent 式大 patch 降级：bad-extension 过滤、学习价值排序、soft/hard token buffer、skip/clip 标记
- [OK-5] v0.2+ LSP 只能 opt-in：server 不存在时静默降级
- [OK-6] Graphify overlay 保持 optional：有 graphify-out 就导入 repo context，没有不影响核心路径

---

## AhaDiff 三层方案评估

### 方案回顾

| 层级 | 技术 | 时间 |
|------|------|------|
| v0.1 core | Python `ast` + regex fallback | 首版 |
| v0.2 optional | tree-sitter 多语言 | 多语言需求后 |
| v0.2+ opt-in | LSP 语义增强 | 用户显式配置 |

### 与竞品对照的评估结论

**方案合理性：高（Codex+Claude 一致）**

1. **v0.1 Python ast** — 合理。PR-Agent 连 AST 都不用，纯 regex + diff 就能做 PR review。AhaDiff 的 deterministic verifier 需要 symbol 验证，Python `ast` 是零依赖最小方案
2. **v0.2 tree-sitter** — 合理且必要。aider 和 graphify 都证明 tree-sitter 是 AI 代码工具的事实标准。但要注意 graphify 的真实复杂度（1400 行 extract.py + 20 LanguageConfig）
3. **v0.2+ LSP opt-in** — 合理。没有竞品在核心路径用 LSP，验证了"LSP 只做 opt-in enrichment"的决策

### 方案遗漏的 4 个能力

| # | 遗漏能力 | 来源竞品 | 是否应纳入 | 建议层级 |
|---|---------|---------|-----------|---------|
| 1 | bad-extension/lockfile/binary 过滤 | PR-Agent | **是** | v0.1（#32/#33 已部分覆盖） |
| 2 | git hunk header section_header 复用 | PR-Agent | **是** | v0.1（免费的 symbol hint） |
| 3 | 跨文件 import/call resolution | graphify | 延后 | v0.2（通过 graphify overlay 间接获得） |
| 4 | AST-only 缓存 + watch 增量 | graphify | 延后 | v0.2 |

### 新增建议

**v0.1 应补充的"免费"能力（零依赖）：**
- 从 git unified diff hunk header 提取 `section_header`（函数名/类名），作为 symbol hint
- 这是 PR-Agent 证明有效的零成本方式：`@@ -15,7 +15,8 @@ def retry_with_backoff(...)` 中的 `def retry_with_backoff(...)` 就是 section header

---

## 审查记录

```text
Codex 分析 (SESSION: 019da8b7-a2a1-7b11-b841-709c59835582)
  - 扫描 repo/ 下 4 个灵感项目源码
  - 远程核验 PR-Agent 官方仓（pyproject.toml + algo/*.py + git_providers/*.py）
  - 发现 graphify 重度使用 tree-sitter（extract.py:654-674）
  - 发现 PR-Agent 完全不用 AST（纯 regex + 扩展名映射）
  - 输出 8 条硬约束 + 5 条软约束

Claude 分析
  - 搜索 aider 官方文档和 GitHub 源码
  - 确认 aider/repomap.py 使用 tree-sitter + grep-ast + pygments
  - 搜索 CodeRabbit 架构文档，确认使用 ast-grep（基于 tree-sitter）
  - 搜索 Greptile 文档，确认使用 graph-based codebase context
  - 网络搜索 tree-sitter Python 集成现状（py-tree-sitter 0.25.2）

交叉一致性
  - "LSP 不进核心路径"：Codex+Claude 100% 一致
  - "tree-sitter 是事实标准"：Codex+Claude 100% 一致
  - "v0.1 Python ast 合理"：Codex+Claude 100% 一致
  - "三层方案整体合理"：Codex+Claude 100% 一致
```
