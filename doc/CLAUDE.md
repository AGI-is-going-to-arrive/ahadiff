[根目录](../CLAUDE.md) > **doc**

# doc -- 设计文档模块

## 模块职责

存放知返 AhaDiff 的产品设计文档，包括完整架构方案、品牌改名决策和前端视觉与交互手册。这些文档是整个产品从理念到实现的蓝图。

## 入口与启动

本模块为纯文档，无可执行入口。直接阅读 Markdown 文件即可。

## 对外接口

无代码接口。文档内容供产品开发、UI 设计和 Claude Design / Stitch 投喂使用。

## 关键依赖与配置

无外部依赖。Markdown 文件可用任意编辑器或阅读器打开。

前端设计手册（`AhaDiff_frontend_design_v1.1_revised.md`）使用 Pandoc YAML frontmatter，含 XeCJK 中文排版配置，可通过 Pandoc 编译为 PDF。

## 文件详解

### 1. `ahadiff设计思路.md` -- 完整架构方案

**核心内容**：从 3 天 MVP 到 v1.0 的完整演进方案。

- **前端三种形态选型**：A 纯 CLI+HTML（MVP 推荐） / B CLI+Textual TUI（v0.3） / C CLI+Web Dashboard（v1.0）
- **6 个灵感项目真机借鉴**（经源码验证修正）：
  - autoresearch：三文件契约（概念改编，原版 prepare.py + train.py），单指标 `val_bpb`，git ratchet 棘轮，简洁性准则。**无 Phase 2.5 或 stuck 检测**
  - SKILL0：helpfulness-driven retention，三段式学习撤架（budget 阶段跳变 [6,3,0]，非线性递减），<0.5k token compact card。helpfulness 原版 file 级，AhaDiff 扩展到 section 粒度
  - darwin-skill：8 维 rubric（总分 100，结构 60 + 效果 40），Phase 2.5 探索性重写（连续 2 个 skill 在 round 1 就 break 时触发），子 agent 对照评测。**零可执行代码**
  - SkillCompass：PASS/CAUTION/FAIL 三档门限（原版 70/50，AhaDiff 调高为 80/60），D3 Security 硬 gate，weakest-dimension-first。原版 6 维评估 skill 文件质量，AhaDiff 自研 8 维评估学习笔记质量
  - Graphify：repo-level map（AhaDiff 做 commit-level learning overlay），标准 NetworkX node-link-data 格式
  - LLM Wiki (Karpathy Gist)：persistent compounding wiki，AhaDiff 落地为 `index.md` + `concepts.jsonl` 增量积累
- **12 模块分层**：cli / diff.parser / concept.extractor / wiki.generator / graph.renderer / deck.exporter / render.jinja / eval.evaluator / eval.ratchet / llm.provider / persistence.store / config
- **8 维自研 Rubric**（非来自 SkillCompass）：accuracy(20) / evidence(18) / diff_coverage(14) / learnability(14) / quiz_transfer(10) / spec_alignment(10) / conciseness(8) / safety_privacy(6) = 100 分
- **测试策略**：单元(VCR) + 集成(pinned repo) + Eval(benchmark + judge 稳定性) + 性能成本
- **风险清单**：15 项，包含命名冲突（极高概率）、litellm 供应链事件、prompt injection 等
- **3 天 MVP 行动清单**：Day 1 核心链路 / Day 2 评估棘轮 / Day 3 可视化+CI

### 2. `知返ahadiff改名后的后续方案.md` -- 品牌与产品重定义

**核心内容**：从 AntiVibe Tutor 改名为 知返 AhaDiff 后的全面产品升级方案。

- **品牌系统**：中文名"知返"，英文名"AhaDiff"，CLI `ahadiff`，Logo 方向 `Δ知` 或 `Δ↺`
- **6 个灵感项目纳入策略**：每个项目具体落地到 AhaDiff 的方式
- **5 个必须补齐的关键设计**：
  1. 增量更新（不重复生成 95% wiki）
  2. 学习深度参数（beginner / intermediate / senior）
  3. Spec-before-code（计划-实现-学习闭环）
  4. Graphify 兼容（repo map + diff learning overlay）
  5. 不确定性标记（verified / weak / not_proven / contradicted）
- **Claim Verifier 设计**：deterministic verifier + LLM judge 双层验证
- **最终命令体系**：plan / learn / verify / improve / quiz / review / graph / install / card / export
- **前端 PDF 9 处必改**：品牌替换、页面重命名、hero 重写、技术栈版本更新等
- **最终数据结构**：claims.jsonl / score.json / learning-signal.jsonl / results.tsv

### 3. `AhaDiff_frontend_design_v1.1_revised.md` -- 前端视觉与交互手册

**核心内容**：3 风格 x 11 页面 = 33 个可生成界面的完整设计规范。

- **品牌**：知返 AhaDiff，"AI 写完，Diff 教回。"
- **五条设计公理**：Evidence first / Learning over summary / Local-first trust / Paper-like seriousness / One accent per style
- **三风格 DNA**：
  - Minimal（瑞士研究报告）：Ink Green `#2F6F4F`，Geist + Source Serif
  - Warm（Anthropic 纸感，默认）：Clay Orange `#D97757`，Inter + Newsreader
  - Editorial（精品出版物）：Terracotta `#C66B3D`，Inter + Fraunces
- **11 页面**：Landing / Runs Dashboard / Lesson Reader / Diff+Evidence Viewer / Ratchet Lab / Socratic Quiz / SRS Review / Settings / Onboarding / Agent Skill Hub / Learning Graph Explorer
- **Design Tokens**：语义层 CSS 变量，Tailwind v4 CSS-first 配置
- **技术栈**：Next.js 16.2.4 / React 19.2.5 / Tailwind 4.2.2 / Motion 12.38.0 / shadcn/ui
- **7 轮 Claude Design 投喂流程**
- **20 条一致性 Checklist**

## 数据模型

无运行时数据模型。文档中规划的核心数据结构：

| 数据文件 | 格式 | 用途 |
|----------|------|------|
| `claims.jsonl` | JSONL | 可验证断言，含 source_hunks / status / confidence |
| `score.json` | JSON | 8 维评分 + verdict + hard_gates |
| `results.tsv` | TSV | 每轮评估记录，11 列：timestamp / run_id / source_ref / base_ref / prompt_version / rubric_version / overall / verdict / status / weakest_dim / note |
| `learning-signal.jsonl` | JSONL | 用户学习行为信号 |

## 测试与质量

文档通过人工评审和 AI 辅助迭代完成质量保障。前端设计手册包含 20 条自查 Checklist。

## 常见问题 (FAQ)

**Q: 为什么从 AntiVibe 改名？**
A: GitHub 已有功能近乎 1:1 重叠的 `mohi-devhub/antivibe`，"Antivibe" 是至少 3 家公司的注册商标，且 Substack 有同名框架预告。改名为 知返 AhaDiff 避免命名冲突。

**Q: N-文件契约具体指什么？**
A: 概念改编自 Karpathy/autoresearch 三文件契约（原版为 prepare.py + train.py，改 Python 代码）。AhaDiff 版本（N-文件契约）：`program.md`（自然语言状态机，人类写）+ evaluation bundle（不可改的评估尺子）+ `generator_prompt.md`（agent 可以改的 Markdown prompt）。核心循环不存在于 Python 层，由 agent 解释执行。

**Q: 文档间的阅读顺序？**
A: 建议先读「设计思路」理解整体架构，再读「改名方案」了解产品升级，最后读「前端设计手册」了解视觉实现。

## 相关文件清单

| 文件 | 行数 | 说明 |
|------|------|------|
| `ahadiff设计思路.md` | ~630 行 | 完整架构方案，从 MVP 到 v1.0 |
| `知返ahadiff改名后的后续方案.md` | ~530 行 | 品牌重定义 + 产品升级方案 |
| `ahadiff 最终完整方案：*.md` | ~2500 行 | 最终完整方案（31 节 + 9 段开发顺序） |
| `AhaDiff_frontend_design_v1.1_revised.md` | 1500 行 | 前端视觉与交互手册（可编译 PDF） |
| `COMPREHENSIVE-EVALUATION-REPORT.md` | ~240 行 | 综合评估报告（方案 9.0/10，UI 8.7/10） |
| `SOURCE-CODE-VERIFICATION-REPORT.md` | ~240 行 | 灵感项目源码验证报告（12 项修订） |
| `trending-ai-projects-research-2026.md` | ~240 行 | 趋势调研（无直接竞品） |

## 变更记录 (Changelog)

| 时间 | 变更 |
|------|------|
| 2026-04-19 21:26:58 | 初始创建 doc/CLAUDE.md |
| 2026-04-20 | 同步根 CLAUDE.md 修订：修正灵感项目描述（6 项含源码验证结论）、8 维 rubric 归因、三文件契约描述、results.tsv 11 列方案（含 base_sha） |
| 2026-04-20 | 补充新增文档条目：最终完整方案、综合评估报告、源码验证报告、趋势调研 |
| 2026-04-20 | 术语同步：三文件契约→N-文件契约（描述 AhaDiff 自身设计时）、evaluator.py→evaluation bundle、四状态→五状态（含 rejected） |
