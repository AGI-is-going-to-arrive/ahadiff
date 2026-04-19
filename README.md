# 知返 AhaDiff

> **AI 写完，Diff 教回。**
>
> 把 Claude / Codex / Cursor 写出的每一个 git diff，变成带证据链、会出题、会复习、会自我迭代的学习课程。

[English](./README.en.md) · [设计文档](./doc/) · [UI 原型](./ui/)

---

## 这是什么

**知返 AhaDiff** 是一个 **local-first 的 AI Coding 学习层**。

它不是 PR 摘要，不是 repo wiki，也不是又一个"代码解释器"。它读取每一次 git diff，把改动转成：

- 一篇带 `file:line` 证据链的 **学习笔记**（Lesson）
- 一份每条结论都可回溯的 **断言清单**（Claims）
- 一张本次 diff 引入概念的 **知识图谱**（Concept Graph）
- 几道用于主动回忆的 **测验题**（Quiz）
- 一组未来复习的 **SRS 卡片**（Spaced Repetition）
- 一条可比较的 **质量评分历史**（Ratchet `results.tsv`）

> Code Wiki 解释仓库，知返解释这次改动 —— 而且每一句话都能回到代码证据。

## 为什么要做

AI 写代码越来越快，开发者却越来越不知道自己有没有真的看懂。"vibe coding" 跑得太远，人需要"知返"：

1. **AI 写完，理解要返还给人** —— 改动不能停留在 commit message
2. **每个解释都要有证据** —— 不允许幻觉函数、虚构因果
3. **知识应该积累** —— 同一个概念被多次修改时，应该有 backlinks 和演化记录
4. **质量应该可比较** —— 用 immutable evaluator + git ratchet 取代"看着差不多就行"

## 核心理念（三层不对称）

继承 Karpathy / autoresearch 的设计哲学：

| 文件 | 谁可以改 | 作用 |
|------|----------|------|
| `program.md` | 人类 | 自然语言状态机，描述 improve loop |
| `evaluator.py` | **不可改** | 评估尺子，输出 `lesson_score` 单标量 |
| `generator_prompt.md` | Agent | 唯一可优化的"创作策略" |

LOOP：编辑 → commit → 评估 → 高分 keep / 低分 reset → 写入 `results.tsv`。

## 快速开始（规划中）

```bash
pipx install ahadiff

# 学习上一次 commit
ahadiff learn HEAD~1..HEAD

# 学习 staged 改动
ahadiff learn --staged

# 对照 spec 学习
ahadiff plan "add OAuth login"
ahadiff learn HEAD~1..HEAD --against .ahadiff/specs/oauth-login/SPEC.md

# 复习
ahadiff quiz abc123
ahadiff review

# 棘轮优化
ahadiff improve abc123 --rounds 6

# 安装到 Agent
ahadiff install claude    # Claude Code Skill
ahadiff install codex     # Codex AGENTS.md
ahadiff install cursor    # Cursor rules
```

产出物结构：

```text
.ahadiff/
├─ index.md
├─ concepts.md
├─ commits/<sha>/
│  ├─ lesson.md          # 带证据链的学习笔记
│  ├─ claims.jsonl       # 可验证断言
│  ├─ quiz.md            # 主动回忆题
│  └─ score.json         # 8 维评分 + verdict
├─ results.tsv           # ratchet 历史（不进 git）
└─ specs/<feature>/      # 计划-实现-学习闭环
```

## 8 维评分 Rubric

| # | 维度 | 权重 | 硬门禁 |
|---|------|------|--------|
| 1 | Accuracy（准确性） | 20 | < 14 → FAIL |
| 2 | Evidence（证据链） | 15 | < 10 → FAIL |
| 3 | Diff Coverage（覆盖度） | 15 | — |
| 4 | Learnability（可学性） | 15 | — |
| 5 | Recall Transfer（迁移） | 10 | — |
| 6 | Spec Alignment | 10 | — |
| 7 | Conciseness（简洁度） | 8 | — |
| 8 | Safety & Privacy | 7 | Critical → FAIL |

三档 verdict：**PASS** ≥ 80 / **CAUTION** 60–80 / **FAIL** < 60。

## 项目结构

```text
ahadiff/
├─ AhaDiff Warm v5.html         # 当前最新 UI 原型
├─ doc/                         # 中文设计文档
│  ├─ ahadiff设计思路.md          # 完整架构方案（MVP → v1.0）
│  ├─ 知返ahadiff改名后的后续方案.md  # 品牌重定义 + 产品升级
│  └─ AhaDiff_frontend_design_v1.1_revised.md  # 前端视觉手册
├─ ui/                          # HTML 原型 v1–v5（设计迭代史）
└─ CLAUDE.md                    # 项目 AI 上下文索引
```

## 当前阶段

**Pre-engineering（设计阶段）**。仓库目前只包含设计文档与 HTML 原型；CLI / 评估器 / Skill 均尚未编码。

下一步路线图：

- [ ] `v0.1`（3 天 MVP）：CLI + Lesson + Evaluator + Ratchet 全链路
- [ ] `v0.2`：HTMX dashboard + watchdog 增量重生
- [ ] `v0.3`：Textual TUI + 章节级 helpfulness
- [ ] `v1.0`：Next.js + React 19 完整前端 + Benchmark Transparency

## 灵感来源

- **karpathy/autoresearch** —— 三文件契约 + git ratchet
- **alchaincyf/darwin-skill** —— 8 维 rubric + Phase 2.5 重写
- **Evol-ai/SkillCompass** —— PASS/CAUTION/FAIL + weakest-dimension-first
- **ZJU-REAL/SkillZero** —— helpfulness-driven retention + compact card
- **safishamsi/graphify** —— repo-level graph overlay
- **karpathy/llm-wiki** gist —— persistent compounding wiki

## 设计公理

1. **Evidence first** —— 每条 claim 必须能回到 `file:line`
2. **Learning over summary** —— 出题 + 复习 > 漂亮总结
3. **Local-first trust** —— 默认离线、显示每一次 LLM 调用
4. **Paper-like seriousness** —— 学术期刊感，拒绝冷紫渐变 SaaS
5. **One accent per style** —— 暖白纸感 + 单一 accent 色

## License

待定（计划 MIT）。

---

> 知返 / AhaDiff —— Δ知 ↺
