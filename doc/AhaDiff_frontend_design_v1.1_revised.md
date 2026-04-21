---
title: "知返 AhaDiff v1.1 前端视觉与交互手册"
subtitle: "3 风格 × 11 页面 = 33 个 Claude Design / Stitch 可生成界面"
author: "Revised design spec based on uploaded frontend design"
date: "2026-04-19"
note: "⚠️ 技术栈分版说明：v0.1 使用 React 19 + Vite + vanilla CSS（viewer/ 目录，无 CSS 框架）；v1.0+ 可升级为 PWA 增强 + Tailwind + shadcn/ui。本文档中涉及 Next.js 的内容仅适用于 v1.0 阶段参考。"
lang: zh-CN
mainfont: DejaVu Serif
monofont: DejaVu Sans Mono
geometry: margin=0.8in
toc: true
toc-depth: 2
numbersections: true
colorlinks: true
linkcolor: ClayOrange
urlcolor: InkBlue
header-includes:
  - \usepackage{xeCJK}
  - \setCJKmainfont[Path=/usr/share/fonts/truetype/arphic-gbsn00lp/]{gbsn00lp.ttf}
  - \setCJKsansfont[Path=/usr/share/fonts/truetype/arphic-gbsn00lp/]{gbsn00lp.ttf}
  - \setCJKmonofont[Path=/usr/share/fonts/truetype/arphic-gbsn00lp/]{gbsn00lp.ttf}
  - \usepackage{xcolor}
  - \definecolor{ClayOrange}{HTML}{D97757}
  - \definecolor{InkGreen}{HTML}{2F6F4F}
  - \definecolor{Terracotta}{HTML}{C66B3D}
  - \definecolor{InkBlue}{HTML}{2E4A6B}
  - \usepackage{titlesec}
  - \titleformat{\section}{\Large\bfseries\color{ClayOrange}}{\thesection}{0.6em}{}
  - \titleformat{\subsection}{\large\bfseries\color{InkBlue}}{\thesubsection}{0.6em}{}
  - \titleformat{\subsubsection}{\normalsize\bfseries\color{InkGreen}}{\thesubsubsection}{0.6em}{}
  - \usepackage{fvextra}
  - \DefineVerbatimEnvironment{Highlighting}{Verbatim}{breaklines,breakanywhere,commandchars=\\\{\}}
  - \RecustomVerbatimEnvironment{verbatim}{Verbatim}{breaklines,breakanywhere}
  - \usepackage{longtable}
  - \usepackage{booktabs}
  - \usepackage{array}
  - \usepackage{caption}
  - \captionsetup{font=small,labelfont=bf}
  - \usepackage{fancyhdr}
  - \pagestyle{fancy}
  - \fancyhead[L]{知返 AhaDiff}
  - \fancyhead[R]{3 styles × 11 pages}
  - \fancyfoot[C]{\thepage}
---

\newpage

# 0. 修改摘要

本文件是对原 **AntiVibe Tutor v1.0 前端视觉与交互手册** 的整体修订版。原文件已经完整规划了 3 风格 × 11 页面 = 33 个界面，并提供了三套视觉 DNA、Design Tokens、i18n、页面规格、7 轮 Claude Design 投喂方式和自查清单。本版保留这个结构，不删减 **3 风格 × 11 页面**，但把产品从「AntiVibe Tutor」重构为 **知返 AhaDiff**，并把 Evidence / Claim / Spec / Graphify / Ratchet / Review 这些核心差异点嵌入到原有 11 个页面里。

> **技术栈说明**：本手册中的 Design Tokens、布局结构、组件语义和 i18n 骨架适用于所有前端实现。
> - **v0.1**：使用 React 19 + Vite + vanilla CSS + Starlette serve（详见 `CLAUDE.md`），组件对应 React 函数组件（`viewer/src/components/`）
> - **v1.0+**：PWA 增强 + Tailwind + shadcn/ui（本手册 §14 投喂 Prompt 适用于此阶段高保真升级）

## 0.1 必改项总览

| 原设计 | 本版修改 |
|---|---|
| AntiVibe Tutor | **知返 AhaDiff** |
| Karpathy's LLM Wiki, applied to the code Claude just wrote for you. | **Every AI-written diff becomes a verified Aha lesson.** |
| 把你 vibe 出来的代码，变成你明天还记得的知识。 | **AI 写完，Diff 教回。** |
| Wiki Reader | **Lesson Reader**，强调证据链、claims、quiz、not-proven |
| Diff Viewer | **Diff + Evidence Viewer**，内置 Claim Inspector |
| Claude Skill Showcase | **Agent Skill Hub**，支持 Claude / Codex / Cursor / Gemini 等 |
| Knowledge Graph Explorer | **Learning Graph Explorer**，支持 Graphify overlay |
| Ratchet Lab | **Ratchet Lab + Benchmark Transparency** |
| Settings | 加入 Privacy / Audit / Offline-only / Provider call log |
| Onboarding | 加入 Spec-before-code：plan → implement → learn |

## 0.2 仍然保持 3 风格 × 11 页面

最终仍然输出 **33 个页面**：

| # | 页面 | 说明 |
|---:|---|---|
| 1 | Landing Page | 产品叙事、before/after demo、开源可信感 |
| 2 | Runs Dashboard | 运行记录、质量分、spec alignment 摘要 |
| 3 | Lesson Reader | 可打印的证据学习笔记 |
| 4 | Diff + Evidence Viewer | diff 行、claim、source hunk 双向联动 |
| 5 | Ratchet Lab | 质量棘轮、benchmark transparency、rubric |
| 6 | Socratic Quiz | 主动回忆、追问、解释 |
| 7 | SRS Review | 复习卡、概念掌握、forgetting risk |
| 8 | Settings | BYOK、provider、privacy、audit、offline-only |
| 9 | Onboarding | repo、key、agent install、first plan/learn |
| 10 | Agent Skill Hub | Claude / Codex / Cursor / Gemini 安装与 SKILL.md |
| 11 | Learning Graph Explorer | Graphify repo graph + AhaDiff learning overlay |

每个页面都要生成 Minimal / Warm / Editorial 三套视觉变体。

\newpage

# 1. 核心叙事与设计公理

## 1.1 品牌命名

正式中文名：**知返**  
正式英文名：**AhaDiff**  
完整写法：**知返 AhaDiff**  
CLI 名称：`ahadiff`  
Logo 方向：`Δ知` 或 `Δ↺`  
中文 slogan：**AI 写完，Diff 教回。**  
英文 slogan：**Ship with AI. Learn it back.**  
Hero 英文：**Every AI-written diff becomes a verified Aha lesson.**

## 1.2 产品定义

知返 AhaDiff 不是 PR summary，不是 repo code wiki，不是普通代码解释器。它是一个 local-first 的 **verified diff learning layer**：

> 把 Claude / Codex / Cursor 写出的 git diff，变成带代码证据链的学习笔记、概念图、自测题、复习卡和质量棘轮记录。

一句话差异：

> Code Wiki explains a repo. AhaDiff teaches you what changed — and verifies every claim against the diff.

中文表达：

> Code Wiki 解释仓库，知返解释这次改动；而且每句话都能回到代码证据。

## 1.3 五条设计公理

1. **Evidence first**：每个解释都要能回到 file:line、diff hunk、claim status。
2. **Learning over summary**：不是“这次改了什么”的摘要，而是“你是否真的学会了”的系统。
3. **Local-first trust**：默认本地优先、BYOK、可审计、不自动上传私有代码。
4. **Paper-like seriousness**：学习材料必须经得起打印、归档、长期阅读。
5. **One accent per style**：每套风格只有一个主 accent 色，功能红绿只用于 diff/状态。

## 1.4 必须出现在 UI 中的核心对象

- Diff：一次 commit / staged changes / PR patch。
- Claim：可验证断言。
- Evidence：file:line、hunk hash、symbol。
- Lesson：学习笔记。
- Concept：概念节点。
- Quiz：主动回忆问题。
- Review Card：SRS 卡片。
- Ratchet Run：生成-评估-保留/丢弃记录。
- Spec Alignment：计划与实现的对齐关系。
- Graphify Overlay：整库图谱上下文上的 diff 学习层。
- Audit Log：LLM 调用、文件、token、cost、provider。

\newpage

# 2. 六个灵感项目如何落进前端

## 2.1 SKILL0 → 学习撤架 UI

SKILL0 的核心启发是 **先给完整 skill context，再逐步撤掉，让能力内化**。在前端中落成三种学习状态：

| 状态 | UI 表现 | 页面 |
|---|---|---|
| Full Lesson | 完整解释、背景、证据、误区、例子 | Lesson Reader |
| Hint Mode | 只显示关键提示和 source hunk，不直接给完整答案 | Lesson Reader / Quiz |
| Compact | 只显示问题，让用户主动回忆 | Quiz / SRS Review |

每个 Lesson 的右栏必须显示：

```text
Scaffolding
[Full] -> [Hint] -> [Compact]
```

并展示每个 section 的 helpfulness：

```text
Helpfulness delta
TL;DR +0.06
Walkthrough +0.19
Background +0.02  (candidate to compress)
```

## 2.2 autoresearch → Ratchet Lab UI

Karpathy/autoresearch 的核心不是 engine，而是自然语言 loop、immutable evaluator、可改文件和 results.tsv。前端中必须出现这些概念：

```text
program.md         natural-language state machine
evaluator.py       immutable judge
generator_prompt.md editable generation strategy
results.tsv        every attempt, keep/discard/crash
```

Ratchet Lab 必须显示：

- score before / after
- `keep | discard | crash`
- weakest dimension
- exact evaluator version
- results.tsv preview
- branch diff / prompt diff

## 2.3 darwin-skill → 8 维 Rubric 与 Phase 2.5

AhaDiff 采用 8 维 lesson rubric：

| 维度 | 权重 | 前端展示 |
|---|---:|---|
| Accuracy | 20 | 是否与 diff 行为一致 |
| Evidence | 15 | claims 是否绑定 source |
| Diff Coverage | 15 | changed symbols 覆盖 |
| Learnability | 15 | 解释是否能教会 |
| Quiz Transfer | 10 | quiz 是否能检验迁移 |
| Spec Alignment | 10 | 是否符合 SPEC |
| Conciseness | 8 | 是否冗长 |
| Safety & Privacy | 7 | 是否泄漏或误导 |

Phase 2.5 在 UI 中显示为：

```text
Stuck for 3 rounds.
AhaDiff is trying a structural rewrite.
Previous best is stashed and recoverable.
```

## 2.4 SkillCompass → PASS / CAUTION / FAIL

每个 Lesson、Run、Claim Set 都要有三档 verdict：

| Verdict | 条件 | UI 颜色 |
|---|---|---|
| PASS | score ≥ 80 且 hard gate 通过 | success |
| CAUTION | 60 ≤ score < 80 或有 weak claim | warning |
| FAIL | score < 60 或 hard gate 失败 | danger |

安全硬门禁：

```text
Accuracy < 14/20 -> FAIL
Evidence < 10/15 -> FAIL
Security/privacy critical -> FAIL
Contradicted claims > 0 -> FAIL
Prompt injection unresolved -> FAIL
```

## 2.5 Graphify → Repo Graph + Diff Learning Overlay

Graphify 负责 repo-level map，AhaDiff 负责 commit-level learning overlay。UI 中必须有过滤器：

```text
All
This Diff
From Graphify
Learning Memory
Weak / Unverified
```

节点语义：

| 节点 | 说明 |
|---|---|
| Repo Context | Graphify 已有架构上下文 |
| File | 被 diff 触发的文件 |
| Symbol | changed function/class/type |
| Concept | 学习概念 |
| Claim | 可验证断言 |
| Weak Claim | 证据不足或不能证明 |

## 2.6 LLM Wiki → 增量积累而不是一次性 RAG

AhaDiff 不是每次重新生成一篇孤立文档，而是写入长期 wiki：

```text
.ahadiff/runs/<run_id>/lesson/lesson.full.md
.ahadiff/runs/<run_id>/claims.jsonl
.ahadiff/runs/<run_id>/quiz/quiz.jsonl
.ahadiff/concepts.jsonl
.ahadiff/review.sqlite
.ahadiff/graphify/graph.json
```

前端中的 Lesson Reader 和 Learning Graph 必须展示 backlinks、introduced by commit、updated by commit。

\newpage

# 3. 三风格 DNA 总览

三套风格保留原方向，但品牌从 AntiVibe 改为 AhaDiff。

| 维度 | A. Minimal / 瑞士研究报告 | B. Warm / Anthropic 纸感 | C. Editorial / 精品出版物 |
|---|---|---|---|
| 一句话 | Linear/Vercel 式克制排版 | Claude 生态同源暖白纸感 | Apple/法式杂志式长读 |
| 适合用户 | DX-first 工程师 | Claude/Cursor/Codex 原住民 | 把 wiki 当出版物读的人 |
| 底色 | `#F7F5F0` | `#FAF9F5` | `#FAF7F0` |
| 暗色 | `#0E0F12` | `#141413` | `#17160F` |
| 主 accent | Ink Green `#2F6F4F` | Clay Orange `#D97757` | Terracotta `#C66B3D` |
| 字体气质 | Geist / Source Serif | Inter / Newsreader | Inter / Fraunces |
| 圆角 | 4-8px | 6-10px | 2-8px |
| 阴影 | 几乎无 | 轻柔 shadow.soft | 几乎无，靠 rule |
| 装饰 | § / FIG / REF 编号 | Clay 小圆点 / 手绘节拍 | drop cap / marginalia |
| CTA | solid + ghost | solid Clay + soft card | underline editorial link |

## 3.1 全局视觉约束

- 亮色默认，暗色是克制版本，不做纯反色。
- 一个风格内只允许一个主 accent 色。
- diff 的 add/delete 使用功能红绿，不算主 accent。
- 学习内容页面必须可打印。
- 所有 graph/canvas 页面必须有等价 list view。
- 所有页面都有 Empty / Loading / Error 三态。
- reduced-motion 下所有 Motion 降级为 opacity-only。

\newpage

# 4. Design Tokens

## 4.1 语义层

```css
color.bg.{paper|subtle|elevated|inverse}
color.text.{primary|secondary|muted|inverse|link}
color.border.{hairline|strong|focus}
color.accent.{default|hover|active|subtle}
color.state.{success|warning|danger|info}
color.diff.{add-bg|add-fg|del-bg|del-fg|neutral}
color.claim.{verified|weak|not-proven|contradicted}
color.graph.{repo|diff|concept|claim|weak}
```

## 4.2 Palette

### Minimal

| Token | Light | Dark |
|---|---|---|
| bg.paper | `#F7F5F0` | `#0E0F12` |
| bg.subtle | `#EFEDE7` | `#16181C` |
| bg.elevated | `#FDFBF6` | `#1C1F24` |
| text.primary | `#1A1B1E` | `#F0EDE6` |
| text.secondary | `#6B6862` | `#8A8780` |
| border.hairline | `#E8E4DB` | `#22252B` |
| accent.default | `#2F6F4F` | `#5FA97E` |
| accent.subtle | `#E4EDE7` | `#1C2A22` |

### Warm

| Token | Light | Dark |
|---|---|---|
| bg.paper | `#FAF9F5` | `#141413` |
| bg.subtle | `#F4F1EA` | `#1C1B18` |
| bg.elevated | `#FFFFFF` | `#24231F` |
| text.primary | `#1F1E1B` | `#FAF9F5` |
| text.secondary | `#6B6559` | `#B0AEA5` |
| border.hairline | `#E8E6DC` | `#2C2A26` |
| accent.default | `#D97757` | `#E28866` |
| accent.subtle | `#F6E8DF` | `#3A2820` |

### Editorial

| Token | Light | Dark |
|---|---|---|
| bg.paper | `#FAF7F0` | `#17160F` |
| bg.subtle | `#F2EDE1` | `#1F1D16` |
| bg.elevated | `#FFFDF8` | `#27241A` |
| text.primary | `#1F1D1A` | `#F2EDE1` |
| text.secondary | `#5A554D` | `#B8B0A2` |
| border.rule | `#D9D1BE` | `#2E2A1F` |
| accent.default | `#C66B3D` | `#E08A5F` |
| accent.ink-blue | `#2E4A6B` | `#6A8BB0` |

## 4.3 Typography

| Role | Minimal | Warm | Editorial |
|---|---|---|---|
| display | Geist Sans 500 | Newsreader 500 | Fraunces Display 400 |
| heading | Geist Sans 520 | Inter 600 | Fraunces 500 |
| body | Source Serif 4 | Newsreader / Source Serif 4 | Fraunces Text |
| ui | Inter 450 | Inter 500 | Inter 500 |
| meta | Geist Mono 500 | JetBrains Mono 500 | JetBrains Mono 500 |
| code | Geist Mono | JetBrains Mono | JetBrains Mono |

实际落地 fallback：

```css
--font-sans: "Inter", "Geist Sans", ui-sans-serif,
  "PingFang SC", "Noto Sans SC", sans-serif;

--font-serif: "Newsreader", "Source Serif 4", "Fraunces",
  ui-serif, Georgia, "Noto Serif SC", serif;

--font-mono: "JetBrains Mono", "Geist Mono",
  ui-monospace, SFMono-Regular, "Sarasa Mono SC", monospace;
```

## 4.4 CSS-first Tailwind v4 片段

```css
@import "tailwindcss";

@theme {
  --font-sans: "Inter", ui-sans-serif, system-ui,
    "PingFang SC", "Noto Sans SC", sans-serif;
  --font-serif: "Newsreader", "Source Serif 4",
    ui-serif, Georgia, "Noto Serif SC", serif;
  --font-mono: "JetBrains Mono", ui-monospace,
    SFMono-Regular, "Sarasa Mono SC", monospace;

  --text-display: 4.5rem;
  --text-h1: 3rem;
  --text-h2: 2rem;
  --text-body: 1.0625rem;
  --text-meta: 0.8125rem;
}

:root,
[data-theme="warm"] {
  --bg-paper: #FAF9F5;
  --text-primary: #1F1E1B;
  --border-hairline: #E8E6DC;
  --accent: #D97757;
}

[data-theme="minimal"] {
  --bg-paper: #F7F5F0;
  --accent: #2F6F4F;
}

[data-theme="editorial"] {
  --bg-paper: #FAF7F0;
  --accent: #C66B3D;
}

:lang(zh-Hans) {
  line-height: 1.75;
}

@media (prefers-reduced-motion: reduce) {
  * {
    animation-duration: 0ms !important;
    transition-duration: 0ms !important;
  }
}
```

\newpage

# 5. 技术栈与依赖

## 5.1 推荐版本

```json
{
  "dependencies": {
    "next": "16.2.4",
    "react": "19.2.5",
    "react-dom": "19.2.5",
    "tailwindcss": "4.2.2",
    "@tailwindcss/postcss": "4.2.2",
    "tailwind-merge": "3.x",
    "class-variance-authority": "0.7.1",
    "clsx": "2.1.1",
    "motion": "12.38.0",
    "lucide-react": "1.x",
    "sonner": "2.x",
    "cmdk": "1.1.x",
    "vaul": "1.1.x",
    "next-intl": "4.x",
    "next-themes": "0.4.x",
    "recharts": "3.8.x",
    "@xyflow/react": "12.10.x",
    "@tanstack/react-table": "8.21.3",
    "mermaid": "11.x",
    "shiki": "4.x",
    "react-hook-form": "7.x",
    "zod": "4.x",
    "@next/mdx": "16.2.4",
    "@mdx-js/react": "3.x"
  }
}
```

## 5.2 组件库

```bash
npx shadcn@latest add button card dialog sheet tabs tooltip popover \
  input textarea label select switch checkbox radio-group separator \
  badge avatar scroll-area accordion alert breadcrumb skeleton \
  sonner command progress dropdown-menu form resizable
```

## 5.3 自建组件

| 组件 | 用途 |
|---|---|
| `BrowserChrome` | Landing 产品截图容器 |
| `DiffView` | unified/split diff |
| `EvidenceLink` | claim → source hunk |
| `ClaimBadge` | verified/weak/not_proven/contradicted |
| `ClaimInspector` | Diff 页面右侧/抽屉 |
| `ScoreRadar` | 8 维 rubric 展示 |
| `ResultsTsvTable` | Ratchet Lab |
| `LessonProse` | 可打印 MDX reader |
| `GraphOverlayLegend` | Graphify / AhaDiff 图层 |
| `AuditLogTable` | Settings |
| `SpecAlignmentMatrix` | Onboarding / Dashboard / Ratchet |

\newpage

# 6. i18n 文案骨架

## 6.1 en.json

```json
{
  "Brand": {
    "name": "AhaDiff",
    "cnName": "知返",
    "tagline": "Ship with AI. Learn it back.",
    "hero": "Every AI-written diff becomes a verified Aha lesson.",
    "subline": "AhaDiff turns Claude, Codex, and Cursor changes into code-linked lessons, concept graphs, active-recall quizzes, and ratcheted quality scores."
  },
  "Nav": {
    "dashboard": "Runs",
    "lessons": "Lessons",
    "ratchet": "Ratchet Lab",
    "quiz": "Quiz",
    "review": "Review",
    "graph": "Graph",
    "skills": "Agent Skills",
    "settings": "Settings"
  },
  "Claim": {
    "verified": "Verified",
    "weak": "Weak",
    "notProven": "Not proven",
    "contradicted": "Contradicted",
    "rejected": "Rejected",
    "openEvidence": "Open evidence",
    "markWrong": "Mark wrong"
  },
  "Verdict": {
    "pass": "PASS",
    "caution": "CAUTION",
    "fail": "FAIL"
  }
}
```

## 6.2 zh-CN.json

```json
{
  "Brand": {
    "name": "知返 AhaDiff",
    "cnName": "知返",
    "tagline": "AI 写完，Diff 教回。",
    "hero": "让每个 AI Diff，讲到你真的懂。",
    "subline": "知返会把 Claude、Codex、Cursor 写出的 git diff 变成带代码证据链的学习笔记、概念图、自测题和质量棘轮记录。"
  },
  "Nav": {
    "dashboard": "运行",
    "lessons": "笔记",
    "ratchet": "棘轮",
    "quiz": "测验",
    "review": "复习",
    "graph": "图谱",
    "skills": "Agent 技能",
    "settings": "设置"
  },
  "Claim": {
    "verified": "已验证",
    "weak": "证据弱",
    "notProven": "无法证明",
    "contradicted": "与代码冲突",
    "rejected": "证据无效",
    "openEvidence": "打开证据",
    "markWrong": "标记错误"
  },
  "Verdict": {
    "pass": "通过",
    "caution": "注意",
    "fail": "失败"
  }
}
```

\newpage

# 7. 页面规格：11 页面 × 3 风格

下述每个页面都要生成 Minimal / Warm / Editorial 三套变体。组件骨架一致，差异仅来自 typography、accent、spacing、装饰语言和动效节奏。

## 7.1 Landing Page

### 共通结构

- Header：logo `Δ知` + wordmark，nav：Docs / Examples / GitHub / Changelog。
- Hero：主标题、subline、两个 CTA、before/after demo。
- Section 2：AhaDiff 工作流：Capture diff → Verify claims → Quiz → Ratchet → Wiki。
- Section 3：Claim evidence demo：点击一句解释，跳到 source hunk。
- Section 4：Ratchet 可视化：score 71 → 86 kept。
- Section 5：Graphify + LLM Wiki：repo map + diff learning memory。
- Section 6：Open-source credibility：benchmark、rubric、privacy。
- Footer。

### 必须展示的 hero 文案

中文：

```text
让每个 AI Diff，讲到你真的懂。
AI 写完，Diff 教回。
```

英文：

```text
Every AI-written diff becomes a verified Aha lesson.
Ship with AI. Learn it back.
```

### Before/After demo

```text
Before: raw git diff
After:
  18 verified claims
  5 concepts
  4 quiz questions
  score 71 -> 86
  2 not-proven warnings
```

### 三风格差异

- Minimal：Swiss 排版、§01 技术编号、hairline、无大阴影。
- Warm：Clay orange 小圆点、暖纸感、手绘 diff 纸条、soft shadow。
- Editorial：封面杂志感、drop cap、右侧博物馆式插图、CTA 用下划线链接。

### 交互

- Hero 入场：标题 opacity/y stagger。
- Before/after：点击切换 `Raw Diff` / `Aha Lesson`。
- Evidence demo：hover claim 时 source hunk 高亮。
- reduced-motion：全部降级为 opacity。

\newpage

## 7.2 Runs Dashboard

### 共通结构

- Sidebar：Runs / Lessons / Ratchet / Quiz / Review / Graph / Skills / Settings。
- Header：repo switch、CmdK、`New Learn Run`。
- Row 1：Score、Claims verified、Review due、Spec alignment。
- Row 2：quality history line chart。
- Row 3：Recent runs table。
- Right panel：Weak concepts、not-proven warnings、audit cost。

### 新增 Spec Alignment 摘要

Dashboard 不能成为普通统计页，必须显示：

```text
Spec Alignment
OAuth login
planned 8
implemented 6
missing 2
verdict CAUTION
```

点击后进入 drawer，而不是新增页面。

### 表格列

```text
commit | lesson | score | verdict | claims | spec | cost | status
```

### 三风格差异

- Minimal：数字大、tabular-nums、无阴影。
- Warm：卡片 soft shadow，Clay accent 只用于主指标。
- Editorial：报纸 ruled grid，eyebrow `FIG 1 · RUN QUALITY`。

### Empty / Loading / Error

- Empty：`Run ahadiff learn HEAD~1..HEAD to create your first lesson.`
- Loading：卡片 skeleton + chart dashed path。
- Error：inline Alert，含日志路径和 retry。

\newpage

## 7.3 Lesson Reader

### 共通结构

三栏：

- 左栏：ToC、related lessons、concept backlinks。
- 中栏：lesson prose。
- 右栏：Claims、Evidence、Quiz、Review、Scaffolding。

### Lesson 固定结构

```markdown
# Commit abc123: Add retry backoff

## TL;DR
## What changed
## Why it matters
## Claims verified against code
## Walkthrough by hunk
## Concepts you just used
## Misconceptions
## Not proven by this diff
## Quiz
## Sources
```

### 右栏信息架构

```text
Claims
18 verified
2 weak
0 contradicted

Evidence
src/client.ts:L82-L104
tests/client.test.ts:L21-L49

Learning
Quiz 4/5
Review due tomorrow

Scaffolding
Full -> Hint -> Compact
```

### 新增 Not Proven 模块

每篇 lesson 必须显示：

```text
Not proven by this diff
- The exact performance improvement is not proven.
- Author intent cannot be inferred from code alone.
- Security impact is plausible but not tested here.
```

### 三风格差异

- Minimal：Geist H1，§/FIG meta，代码块左 2px accent stripe。
- Warm：Newsreader 正文，Clay 左边条，marginalia 用 serif italic。
- Editorial：Fraunces H1，drop cap，图注式 source captions。

### 打印样式

打印时只保留中栏，隐藏 nav/side panels，正文 serif，代码 9pt，source links 以 URL 或 file:line 尾注形式出现。

\newpage

## 7.4 Diff + Evidence Viewer

### 共通结构

- Header：commit hash、file breadcrumb、Unified/Split、Open Lesson。
- 左栏：diff viewer。
- 中栏：selected source hunk / lesson paragraph。
- 右栏：Claim Inspector。
- 底部：Prev/Next file。

### Claim Inspector 内置，不新增第 12 页

Claim Inspector 是本页的核心功能，不单独作为第 12 页，以满足 11 页面限制。

Claim card：

```text
c007
The retry loop now uses exponential backoff with jitter.
Status: verified
Confidence: 0.91
Source: src/client.ts:L82-L104
Concepts: retry, exponential_backoff, jitter
Actions: Accept | Mark wrong | Add to quiz
```

### 核心交互

- 点击 diff 行 → 右侧高亮相关 claim。
- 点击 claim → 左侧滚动到 source hunk。
- 点击 concept → 打开 graph node。
- 点击 not-proven → 显示为什么不能证明。
- hover 行 → `Ask this line`。

### Claim 状态颜色

| 状态 | 说明 |
|---|---|
| verified | 能回到 diff hunk |
| weak | 有线索但因果不完整 |
| not_proven | diff 无法证明 |
| contradicted | 与代码冲突 |

### 三风格差异

- Minimal：纯 mono diff、2px split border、hover bg-subtle。
- Warm：左右栏暖色差异、Clay quote bar。
- Editorial：dotted center rule，commit meta uppercase。

\newpage

## 7.5 Ratchet Lab

### 共通结构

- Header：run selector、rubric button、benchmark tab。
- 左栏：results.tsv table。
- 中栏：quality trajectory line chart。
- 下方：selected iteration diff。
- 右栏 Sheet：Rubric / Benchmark / Judge notes。

### results.tsv 表格

```text
time | commit | version | score | verdict | status | weakest | note
```

### Rubric Radar

展示 8 维：

```text
Accuracy
Evidence
Diff Coverage
Learnability
Quiz Transfer
Spec Alignment
Conciseness
Safety & Privacy
```

### Benchmark Transparency 内嵌

不新增第 12 页，作为 Ratchet Lab 的 tab：

```text
Benchmark suite
50 pinned diffs
8 languages
12 project types
human-labeled ground truth
judge-human agreement
score history
```

### Phase 2.5 UI

```text
Stuck for 3 rounds.
Trying structural rewrite.
Previous best is stashed.
```

### 三风格差异

- Minimal：单线图、kept 行左 2px accent。
- Warm：kept 用细小 Clay check，不使用花哨 confetti。
- Editorial：经济学人式黑白图表，caption `FIG 3.2`。

\newpage

## 7.6 Socratic Quiz

### 共通结构

- 顶部：lesson title、Question n/m、Progress。
- 中央：question card、options、submit、explanation。
- 侧栏：evidence source、related claim、difficulty。
- 完成页：score、wrong concepts、send to SRS。

### SKILL0 撤架模式

Quiz 有三种模式：

```text
Guided: 显示 hint + source
Recall: 只显示问题
Transfer: 给一个新场景，检验概念迁移
```

### 题型

- Multiple choice
- Short answer
- Explain this hunk
- Find the missing risk
- Transfer scenario

### 三风格差异

- Minimal：1px 选项边框，选中变 accent。
- Warm：选中 bg accent.subtle，解释段 serif italic。
- Editorial：`Question II of V` 罗马编号，选项为 `(a)(b)(c)`。

### a11y

- RadioGroup 支持键盘箭头。
- aria-live 播报对/错反馈。
- reduced-motion 禁用 shake，只用红色边框。

\newpage

## 7.7 SRS Review

### 共通结构

- 顶部：cards due today、progress、weak concepts。
- 中央：Review Card，front/back。
- 底部：Again / Hard / Good 主按钮 + Archive / Suspend 次级动作。
- 右栏：calendar heatmap、concept mastery、forgetting risk。

### Review card 来源

每张卡都要能追溯：

```text
Concept: Idempotency
Introduced by: commit abc123
Evidence: src/client.ts:L82-L104
Claim: c007
```

### forgetting risk

```text
Risk high
Reason: wrong twice on idempotency transfer questions
Next review: tomorrow
```

### 三风格差异

- Minimal：卡片无阴影，三主按钮等宽，键盘提示 `(1)(2)(3)`；Archive/Suspend 用次级操作。
- Warm：翻书感，但 reduced-motion 用 fade。
- Editorial：ruled paper 视觉，按钮用 editorial link。

### 卡片状态动作

- `Archive`：永久移出 due 队列，用于确认低质量或不再需要的卡。
- `Suspend`：临时移出 due 队列，等待人工恢复或 regenerate。
- `Archive / Suspend` 不写入 FSRS rating，只更新卡片状态。
- 同一 session 内如果用户主动展开完整答案（peek），`Good` 必须禁用，只允许 `Hard / Wrong`。

\newpage

## 7.8 Settings

### 共通结构

Tabs：

```text
Account
Keys
Models
Privacy
Audit
Language
Appearance
Integrations
```

### Privacy

必须包含：

```text
Offline only
Redact .env / secrets / keys
Never upload private files unless explicitly allowed
Show every LLM call
Delete local cache
```

### Audit

Audit 表格列：

```text
time | provider | model | files sent | tokens | cost | purpose | status
```

每一行可以展开查看：

```text
Prompt template
Files included
Redactions applied
Provider response id
```

### Provider

```text
Generate model
Judge model
Embedding model
Local Ollama
Cost preview
Max tokens per run
```

### 三风格差异

- Minimal：紧凑表单，sticky save。
- Warm：每 section 有小 emoji + Clay 左边条。
- Editorial：§ 标题，双线 rule 分隔。

\newpage

## 7.9 Onboarding

### 共通结构

4 步：

1. Pick a repo
2. Add provider key / local model
3. Install agent integration
4. Run first plan + learn

### Spec-before-code 流程

Onboarding 里必须让用户理解：

```text
ahadiff plan "add OAuth login"
# creates SPEC.md, acceptance_tests.md, concept_primer.md

ahadiff learn HEAD~1..HEAD --against SPEC.md
# creates lesson + spec alignment
```

### Step 4 demo

```text
Plan -> Implement -> Learn
SPEC: 8 requirements
Diff: 6 implemented
Missing: 2
Verdict: CAUTION
```

### 三风格差异

- Minimal：无插图，§01/§02/§03/§04 stepper。
- Warm：小手绘插图，Clay progress。
- Editorial：大号 `ONE / TWO / THREE / FOUR`，封面式留白。

\newpage

## 7.10 Agent Skill Hub

### 共通结构

替换原 Claude Skill Showcase。本页是多 agent 集成中心：

- Claude Code
- Codex
- Cursor
- Gemini CLI
- OpenCode
- Copilot / VS Code
- Aider / Kiro / Antigravity 可选

### 页面模块

```text
1. How AhaDiff skill works
2. Install commands by platform
3. SKILL.md preview
4. AGENTS.md / rules preview
5. Hook / always-on behavior
6. Troubleshooting
```

### Claude Skill 结构

```text
skills/ahadiff/
  SKILL.md
  references/rubric.md
  references/output-contract.md
  scripts/run_ahadiff.py
  examples/retry-backoff.md
```

### SKILL.md 展示

```yaml
---
name: ahadiff
description: >
  Turn git diffs and AI-written code changes into verified learning lessons.
  Use when the user says "explain this diff", "learn this commit",
  "teach me what Claude wrote", "generate a diff wiki", or "quiz me on this PR".
allowed-tools: Read, Grep, Bash
---
```

### 三风格差异

- Minimal：README 单栏，线图。
- Warm：手绘 workflow，Clay section label。
- Editorial：对页 spread，`§I · DIFF CAPTURE` eyebrow。

\newpage

## 7.11 Learning Graph Explorer

### 共通结构

- 主体：@xyflow/react canvas。
- 顶部 bar：search、filters、layout toggle。
- 右栏 Sheet：node detail。
- 底部：minimap、zoom。
- Toggle：Graph / List。
- Cluster 节点右上角提供可见 `⋮` 菜单按钮，统一承载展开 / 隐藏 / 高亮关联 claims；不依赖长按手势。

### Graphify Overlay

过滤器：

```text
All
This Diff
From Graphify
Learning Memory
Weak Claims
```

图例：

```text
Repo context: muted gray
Current diff: accent orange/green/terracotta
Verified concept: success outline
Weak claim: warning
Contradicted: danger
```

### Node Detail

```text
Concept: Exponential Backoff
First introduced: commit abc123
Updated by: commit def456
Evidence: src/client.ts:L82-L104
Related claims: c007, c012
Quiz performance: 80%
```

### 大图降级

- >500 节点：默认只显示 current diff + one-hop。
- Canvas 渲染失败：降级为 tree/list。
- a11y：List view 是完整等价功能，不是装饰。

### 三风格差异

- Minimal：6px 圆点，mono label。
- Warm：选中节点有 Clay 轻光晕。
- Editorial：文字即节点，dashed rule 边，右栏像脚注。

\newpage

# 8. 微交互规则

- Hover：只改 opacity / bg tint，不使用 translateY 上浮。
- Focus：统一 2px outline + 2px offset，颜色使用 `--accent`。
- Loading：skeleton + subtle pulse，不用花哨 spinner。
- Error：inline Alert + Sonner，不用阻断弹窗。
- Success：toast + 轻微 scale，不用 confetti。
- Diff line click：source hunk 与 claim 必须双向高亮。
- Claim click：滚动和高亮要在 400ms 内完成。
- Graph filter：opacity fade 240ms。
- Theme switch：切 CSS variables，不重载页面。
- reduced-motion：所有 Motion 动画降级为 opacity-only 或 0ms。

\newpage

# 9. 关键交互剧本

## 9.1 Landing 剧本

用户从 GitHub / HN / 推特进入。3 秒内必须看懂：

```text
AI wrote code -> AhaDiff verified claims -> Quiz -> Ratchet -> Wiki memory
```

点击 `View a verified lesson` 进入 demo Lesson Reader。点击 `Start from your diff` 若未设置则进入 Onboarding。

## 9.2 Lesson Reader 剧本

用户打开一篇 commit lesson。首先看到标题、TL;DR、claim 统计。点击右栏 `2 weak claims`，中栏自动跳到 not-proven section。点击 source，进入 Diff + Evidence Viewer。

## 9.3 Diff + Evidence Viewer 剧本

用户点击 `src/client.ts:L82`。右侧 Claim Inspector 高亮 c007。用户点击 `Add to quiz`，系统把这个 claim 变成一道 active recall 问题。

## 9.4 Ratchet Lab 剧本

用户看到 score 从 71 到 86，状态 `kept`。hover 折线某点出现 judge notes。切到 Benchmark tab，可看到这次改动在 pinned suite 上没有退化。

## 9.5 Quiz / Review 剧本

用户做错 idempotency 题。系统不是只显示错误，而是链接回 source hunk、相关 claim 和 concept node。次日 SRS Review 把它作为 weak concept 重新出现。

\newpage

# 10. 视觉资产清单

## 10.1 Logo

- Minimal：`Δ知` 单色 wordmark。
- Warm：`知返 AhaDiff` + Clay orange 小圆点。
- Editorial：细圆印章 `Δ / 知`，下方小字 `AhaDiff · 2026`。

## 10.2 Favicon

统一一个 32×32 `Δ知`：

- Minimal：Ink Green。
- Warm：Clay Orange。
- Editorial：Terracotta。

## 10.3 OG Image

三套模板：

- Minimal：纸白底 + 大号 `Δ知` + `Every AI-written diff becomes a verified Aha lesson.`
- Warm：暖白底 + Clay dot + before/after diff 卡片。
- Editorial：象牙底 + Fraunces 大字 + 单线图谱。

## 10.4 Spot Illustration

至少 7 张：

1. Landing hero before/after。
2. Onboarding repo。
3. Onboarding key。
4. Onboarding agent install。
5. Empty dashboard。
6. Empty graph。
7. Benchmark transparency。

\newpage

# 11. 响应式、暗色、打印

## 11.1 响应式降级

1. 三栏 → 二栏：右栏进入 Sheet。
2. 二栏 → 一栏：左侧 sidebar 进入 Sheet。
3. DataTable → Card list。
4. Graph canvas → List view。
5. Tabs → Accordion。
6. Diff split → Unified。

## 11.2 暗色模式

- Minimal dark：`#0E0F12` + `#F0EDE6` + `#5FA97E`。
- Warm dark：`#141413` + `#FAF9F5` + `#E28866`。
- Editorial dark：`#17160F` + `#F2EDE1` + `#E08A5F`。

## 11.3 打印

Lesson Reader 必须支持打印：

```css
@media print {
  aside, nav, .no-print { display: none; }
  article {
    max-width: 100%;
    font-family: var(--font-serif);
    font-size: 11pt;
  }
  pre, code { font-size: 9pt; }
  h2 { page-break-after: avoid; }
}
```

\newpage

# 12. 一致性 Checklist

1. 是否全部替换为 **知返 AhaDiff**，没有 AntiVibe 残留。
2. 是否仍然是 3 风格 × 11 页面 = 33 个界面。
3. 每个页面是否只有一个主 accent。
4. Lesson Reader 是否有 Claims / Evidence / Quiz / Review 右栏。
5. Diff Viewer 是否内置 Claim Inspector。
6. Ratchet Lab 是否内置 Benchmark Transparency。
7. Onboarding 是否包含 Spec-before-code。
8. Graph Explorer 是否有 Graphify overlay。
9. Settings 是否有 Privacy / Audit / Offline-only。
10. 所有页面是否有 Empty / Loading / Error。
11. 所有图谱是否有 List view fallback。
12. reduced-motion 是否可用。
13. 中文行高是否 ≥ 1.72。
14. 代码块是否使用 mono token。
15. DataTable 是否可键盘排序。
16. 打印样式是否隐藏侧栏。
17. Claim 状态是否只有 verified / weak / not_proven / contradicted。
18. PASS / CAUTION / FAIL 是否统一。
19. Audit log 是否展示 files sent / tokens / cost。
20. 交付 Claude Design 前是否先生成 Warm，再做 Minimal / Editorial 差量。

\newpage

# 13. Claude Design / Stitch 投喂操作指南

仍然使用 7 轮，但页面保持 11 个，不新增第 12/13 页。

## Round 1：基础设施

投喂内容：

- §1 核心叙事
- §3 三风格 DNA
- §4 Design Tokens
- §5 技术栈
- §6 i18n
- §12 Checklist

要求输出：

```text
app/globals.css
components/theme-provider.tsx
lib/cn.ts
messages/en.json
messages/zh-CN.json
base layout
```

## Round 2：Warm 风格核心 3 页

页面：

1. Landing
2. Runs Dashboard
3. Lesson Reader

强调 Warm 是默认风格，先把纸感、Clay、长读体验做好。

## Round 3：Warm 风格工作流 4 页

页面：

4. Diff + Evidence Viewer
5. Ratchet Lab
6. Socratic Quiz
7. SRS Review

尤其要保证 Claim Inspector 与 Ratchet Lab 的数据结构清楚。

## Round 4：Warm 风格剩余 4 页

页面：

8. Settings
9. Onboarding
10. Agent Skill Hub
11. Learning Graph Explorer

尤其要保证 Privacy / Audit / Graphify overlay / Agent install 的完整性。

## Round 5：Minimal 差量变体

不要重写骨架，只切：

```text
palette -> Minimal
typography -> Geist / Source Serif
shadow -> hairline
ornament -> § / FIG / REF
motion -> faster 120-160ms
```

输出 11 个 Minimal 页面。

## Round 6：Editorial 差量变体

不要重写骨架，只切：

```text
palette -> Editorial
typography -> Fraunces / serif
ornament -> drop cap / marginalia / ruled line
CTA -> editorial underline
motion -> 240-320ms apple ease
```

输出 11 个 Editorial 页面。

## Round 7：审计与修正

按 §12 的 20 条 checklist 逐项修复。特别检查：

```text
AntiVibe 残留
11 页面数量
Claim Inspector 是否存在
Graph List fallback
Print CSS
reduced-motion
i18n 文案
```

\newpage

# 14. 直接投喂 Claude Design 的总 Prompt

> **注意**：以下 Prompt 使用 Next.js/React + Tailwind + shadcn/ui 技术栈，适用于 **v1.0 PWA 增强阶段**。
> v0.1 使用 React 19 + Vite + vanilla CSS + Starlette serve（见 `CLAUDE.md` 技术栈章节）。
> v0.1 的组件已是 React 函数组件（`viewer/src/components/`），v1.0 升级主要涉及 Tailwind 迁移和 PWA 能力。

```markdown
你是 Claude Design / Stitch。请基于以下规范生成 Next.js 16 + React 19 + Tailwind v4 + shadcn/ui + Motion 的前端。

项目正式名称：
中文：知返
英文：AhaDiff
完整写法：知返 AhaDiff
CLI：ahadiff

中文 slogan：
AI 写完，Diff 教回。

英文 slogan：
Ship with AI. Learn it back.

Hero：
Every AI-written diff becomes a verified Aha lesson.

产品定义：
AhaDiff 是 local-first 的 verified diff learning layer。
它把 Claude / Codex / Cursor 写出的 git diff 变成：
1. 带 file:line 证据链的学习笔记
2. claims.jsonl 断言验证
3. 概念图谱
4. 主动回忆 quiz
5. SRS 复习卡
6. ratchet 质量评分
7. spec alignment 报告

页面必须保持：
3 风格 × 11 页面 = 33 个页面。
不要新增第 12 页。Claim Inspector 嵌入 Diff + Evidence Viewer。
Benchmark Transparency 嵌入 Ratchet Lab。
Spec Alignment 嵌入 Dashboard / Onboarding / Ratchet。
Graphify Overlay 嵌入 Learning Graph Explorer。

11 页面：
1. Landing
2. Runs Dashboard
3. Lesson Reader
4. Diff + Evidence Viewer
5. Ratchet Lab
6. Socratic Quiz
7. SRS Review
8. Settings
9. Onboarding
10. Agent Skill Hub
11. Learning Graph Explorer

三风格：
Minimal / Warm / Editorial。
Warm 是默认。
每套风格一个主 accent，不要彩虹、不要 cold purple、不要 glass morphism。

核心交互：
- 点击 diff 行，高亮相关 claim。
- 点击 claim，跳到 source hunk。
- claim 显示 verified / weak / not_proven / contradicted。
- Lesson Reader 右栏显示 Claims、Evidence、Quiz、Review 状态。
- Ratchet Lab 显示 score before/after、weakest dimension、keep/discard。
- Learning Graph 支持 All / This Diff / From Graphify / Weak Claims 过滤。
- Settings 必须有 Privacy、Audit、Provider、Offline-only。

技术版本：
next 16.2.4
react 19.2.5
react-dom 19.2.5
tailwindcss 4.2.2
@tanstack/react-table 8.21.3
motion 12.38.0
shadcn/ui
next-intl
next-themes
shiki
mermaid
@xyflow/react
recharts
zod

输出顺序：
先生成 Warm 风格 11 页，再基于同一骨架做 Minimal 和 Editorial 差量变体。
```

\newpage

# 15. 参考依据

本手册的修订依据包括：

- 原 `frontend design.pdf` 中的 3 风格 × 11 页面结构、Design Tokens、i18n、页面规格、7 轮 Claude Design 投喂流程。
- 原架构报告中关于命名风险、autoresearch 三文件契约、darwin-skill 8 维 rubric、SkillCompass PASS/CAUTION/FAIL、Graphify 文件即真相源的判断。
- Claude Agent Skills 官方文档：Skill 由 instructions、metadata、resources 组成，并按需加载。
- Graphify README：`GRAPH_REPORT.md`、always-on hook、AGENTS.md / Cursor rules / Gemini settings 等集成方式。
- npm 版本信息：Next、React、Tailwind、Motion、TanStack Table 的当前版本。
- SKILL0、autoresearch、darwin-skill、SkillCompass、Graphify、LLM Wiki 的核心设计思想。
