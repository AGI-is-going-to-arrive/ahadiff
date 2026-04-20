# Team Research: AhaDiff FAQ 核心问题

## 增强后的需求

用户提出 7 个核心设计问题，需要用通俗语言 + 可视化方式回答并更新 Blueprint HTML。

## 约束集

### 硬约束
- [HC-1] AhaDiff 当前处于设计阶段，无可执行代码 — 来源：Codex
- [HC-2] Diff 检测基于 git unified diff 文本，不使用 LSP 作为核心 — 来源：Codex
- [HC-3] AST 应作为增强层（step 11 symbol 提取），不替代 unified diff — 来源：Codex
- [HC-4] 三文件契约中 evaluator.py 不可变、prompts/*.md 可变 — 来源：Codex §14.1
- [HC-5] AhaDiff 绝不修改用户代码，只生成 .ahadiff/ 目录 — 来源：Codex
- [HC-6] generate/judge 可以配置为同一模型（config.toml 已支持）— 来源：Codex §17
- [HC-7] Graphify graph.html 已存在于 graphify-out/，可可视化 — 来源：Codex
- [HC-8] LLM Wiki 的 index.md + concepts.jsonl 在 learn step 25 更新 — 来源：Codex §8

### 软约束
- [SC-1] 可视化应使用左右分栏对比图（diff vs AST）— 来源：Gemini
- [SC-2] 三文件契约用锁/笔/齿轮图标区分 — 来源：Gemini
- [SC-3] 灵感项目应直接挂载在七层架构图上 — 来源：Gemini
- [SC-4] 只读保证用"防火墙"分区视图 — 来源：Gemini
- [SC-5] `--diff` 命名冲突已修复为 `--compare` — 来源：前轮 review
- [SC-6] "Skill" 概念需要翻译卡区分 Agent skill vs 用户 concept — 来源：Gemini

### 风险
- [RISK-1] AST 引入增加 tree-sitter grammar 维护成本 — 缓解：v0.2+ 再做，MVP 用纯文本

## 成功判据
- [OK-1] Blueprint HTML 新增 FAQ 页面，7 个问题全部可视化
- [OK-2] 每个回答用通俗语言（非专业术语堆砌）
- [OK-3] 经 Codex + Claude 交叉 review 验证准确性
