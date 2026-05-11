# 知返 AhaDiff 竞品研究 — 可落地的功能差距清单

> 研究方法：对每个竞品做 web search，提取功能 → 对比 AhaDiff 现状（v1.1，FSRS-6 / 8 维 rubric / claims / 13 install targets / React SPA）→ 标注优先级。本报告聚焦**可实现**的具体特性，不做空泛建议。
>
> 日期：2026-05-10

> 校准说明：本次文档同步只按当前代码校准 AhaDiff 现状。下面的外部来源没有在本轮重新抓取；表里的功能是后续候选，不代表本轮已经实现。

---

## 一、SRS 类（Anki / RemNote / Mochi / SuperMemo / Brainscape）

AhaDiff 已有 FSRS-6 + ABCD 卡片 + review.sqlite。**真正缺的是生态、卡片形态、调度精细度。**

### 1.1 高优先级（High）

| Feature | 来源 | 工作机制 | AhaDiff 实现路径 |
|---|---|---|---|
| **`.apkg` 导出** | Anki | `.apkg` 文件可导入 Anki deck；AnkiConnect 是另一条自动写入路径 | 已落地 WebUI 下载：Ratchet 调 `GET /api/export/apkg` 生成 `ahadiff_review.apkg`，只导出 review.sqlite 中 active review cards，上限 10,000 张，缺 `genanki` 时返回 `501 FEATURE_UNAVAILABLE`。这不是 AnkiConnect，也不是 CLI `export-apkg`。 |
| **Cloze deletion 卡片类型** | Anki / SuperMemo / Migaku | 把句子里 1+ 个 token 用 `{{c1::xxx}}` 隐藏，从一句话生成多张卡 | 在 `quiz_generate.md` prompt 里增加 cloze 模板；扩 `QuizChoice` contract 支持 `mode: "cloze"`；前端 Quiz 页加填空 UI。比 ABCD 更适合记 API 签名、shell flag、SQL 关键字。 |
| **Image Occlusion（图像遮罩）** | SuperMemo 19 / Anki Image Occlusion Enhanced | 在图片上画矩形，遮住部分内容，从一张图生成多张卡 | AhaDiff 的"diff 图"天然适合：把 unified diff 渲染成图，遮掉关键 hunk → "下面这个 patch 的第 3 行应该是？"。需要 `viewer/src/pages/Quiz.tsx` 加 SVG overlay。 |
| **Desired Retention 深调 + Easy Days（轻松日）** | Anki FSRS / RemNote | 用户能选目标记忆率，也能选择一周中某些天减少复习量 | AhaDiff 当前 Settings/config 已有 `desired_retention` 基础入口；后续缺的是更细的调度说明、Easy Days，以及 review queue 按 weekday 调整 `due_date`。 |

### 1.2 中优先级（Medium）

| Feature | 来源 | 落地说明 |
|---|---|---|
| **Exam Scheduler（考前调度）** | RemNote | 对开发者就是"周五前我要弄懂这个 PR 的所有概念" → 倒推每天看哪些卡 | 新增 `ahadiff review --deadline 2026-05-15` flag，调度器按 retrievability 倒排。 |
| **Daily Learning Goal + 热力图** | RemNote / Mochi | 每天目标 N 张卡 + GitHub 风格 heatmap | viewer/Dashboard 已有部分；补 streak 追踪与目标条 widget。 |
| **Daily push 提醒（PWA notification）** | Mochi 2025 | 浏览器/PWA push notification | AhaDiff 已是 PWA → 加 `Notification API` + service worker schedule。 |
| **FSRS optimizer（个人参数训练）** | Anki / RemNote | 用 review history 训练 17-22 个浮点参数（梯度下降），最小化预测误差 | `fsrs` Python package 自带 optimizer。新增 `ahadiff review optimize` 命令，按 user 的 result_events 训练。 |
| **Card templates / 多面卡** | Mochi (`<<word>>` 占位)、Anki note types | 一个 note 自动生成 forward/backward/cloze 多张卡 | 把 quiz JSON schema 扩成 `template_id + fields`，一次 LLM 调用生成多张卡。 |
| **Sibling burying（同源卡互斥）** | Anki | 同一个 note 派生的多张卡，今天看了一张就把其他延后 | 用 `lesson_id` group，在 review query 里按 group 限制每日露出数量。 |

### 1.3 低优先级（Low）

- SM-20 ML 调度（SuperMemo 私有，FSRS-6 已经够用）
- Confidence rating（Brainscape 风格 1-5 滑杆）— FSRS Again/Hard/Good/Easy 已覆盖
- 移动 App 原生版 — PWA 已够，原生版 ROI 低

---

## 二、Diff / 代码理解类（GitButler / GitLens / GitHub Copilot / GitKraken AI）

### 2.1 高优先级（High）

| Feature | 来源 | 工作机制 | AhaDiff 实现路径 |
|---|---|---|---|
| **Hunk-level commit 切分 + 学习** | GitButler `but commit -h <hunk-id>` / `but diff l0` | 把同一文件多个 hunk 拆给不同 logical commit | AhaDiff Learn 当前以 commit/diff 为粒度。可加"同一 diff 多个意图分组" — 让 LLM 把 5 个 hunk 标 3 类意图，每类生成独立 lesson + concepts。改 `core/orchestrator.py` 的 changed_paths 划分。 |
| **AI diff summary（commit/branch 级）** | GitKraken AI Explain / GitButler `but log --ai` / Copilot PR summary | 一句话概括 commit/branch 的 what + why | AhaDiff lesson 已有这个。**缺点是只对单 diff**。补一个 `ahadiff summarize <commit-range>` 输出多 commit 合并摘要 + 文件级 walk-through，复用现有 prompt 链。 |
| **Inline blame + heatmap visualization** | GitLens gutter blame + 滚动条颜色热图 | 行尾显示 author/date/commit，滚动条按代码新旧着色 | AhaDiff Diff 页面只显示当前 diff。可加 sidebar 展示该文件的 ahadiff learn 历史："这一行所属 hunk 学过 3 次，concept=`auth_callback`，最近 freshness=stale"。直接复用 concepts.jsonl + Graphify。 |
| **Code Lens 显示 lesson 链接** | GitLens CodeLens（函数/类上方注释） | 函数声明上方显示 author/last commit | AhaDiff 可在用户编辑器（VSCode/Cursor）里通过 LSP 或 extension 在函数上方显示"Learned in run #abc, 4 claims verified"。利用 install 模块已有的 13 个 agent 接口。 |
| **PR / commit summary as lesson 入口** | Copilot PR summary（含 file-by-file walkthrough） | 在 PR 页面生成 prose + 受影响文件 bullet list | AhaDiff 已有 lesson；缺少 "PR 模式"——一次接收多个 commit 的 unified diff，输出每个 commit 的学习卡 + 总览。新增 `--from-pr <url>` 拉取 PR 全部 diff。 |
| **Commit absorb 风格的"修正型"学习** | GitButler drag-and-drop absorb | 当 fix commit 出现，自动并入原 commit | AhaDiff 学习场景：当用户做了 follow-up fix，自动把新 evidence merge 进原 lesson 的 concept node，触发 freshness 刷新。是 Graphify 7-state 自然延伸。 |

### 2.2 中优先级（Medium）

| Feature | 工作机制 | 落地 |
|---|---|---|
| **Cody-style cross-file context for claims** | Sourcegraph Cody RAG 跨仓库索引 + 找到调用方 | AhaDiff claim verifier 当前只 grep 该文件。可补 "downstream impact"：找出调用本 diff 函数的其他文件，让 LLM 评估"这个改动是否破坏调用方语义"。直接读 `LSP textDocument/references` 或 ctags。 |
| **Interactive Rebase Editor 风格的 lesson 重排** | GitLens Interactive Rebase Editor | 已有 Lesson 页面，可加"reorder/squash claim"UI，让用户合并相似 claim。 |
| **Comment 严重度（Critical / Style）分级** | Copilot code review severity context | AhaDiff claim 5 状态 + 8 维 rubric 已隐含，但前端没把 critical claim 突出。Lesson 页加红/黄/灰条带。 |

### 2.3 低优先级（Low）

- Virtual branches Kanban UI（GitButler 招牌） — AhaDiff 不是 Git 客户端
- 自动重写 commit message（aicommits / OpenCommit） — 越权，不写代码

---

## 三、Code-to-Knowledge（Karpathy LLM Wiki / autoresearch）

### 3.1 高优先级（High）

| Feature | 来源 | 工作机制 | AhaDiff 实现路径 |
|---|---|---|---|
| **N-file 不可变契约（已部分实现）** | autoresearch `prepare.py + train.py + program.md` | prepare.py 不可变（评估），train.py agent 沙盒，program.md 人写规则 | AhaDiff **CLAUDE.md 已说"已采纳"**：N-文件契约 + improve worktree 隔离。但仍可强化：把 `eval_judge.md` 标 read-only、新增 `program.md` 等价物来声明研究方向（如"我想理解 auth flow"）。 |
| **results.tsv 完整审计轨迹** | autoresearch | 每次实验记 commit hash + score + GPU mem + pass/fail + 描述 | AhaDiff `runs/<run_id>/audit.jsonl` 已类似，但没有用户可读的合并 dashboard。新增 viewer/Ratchet 页加"all sessions"视图，按时间序展示每次 improve 的 8 维分数 delta。 |
| **LLM Wiki: "wiki 是 codebase, LLM 是 programmer"** | Karpathy gist | LLM 把原始文档编译成结构化 wiki（不是 RAG，每问一遍重新编译） | AhaDiff `concepts.jsonl` 已是 append-only wiki 雏形。**缺 cross-document synthesis**：当某 concept 在 5 个 run 中被 touch，应自动 summarize 出 evergreen note。新增 `ahadiff concepts compact` 命令，按 concept_id 聚合并调 LLM 生成 wiki page。 |
| **fixed time budget per run** | autoresearch（每次实验 5 分钟） | 让结果可比 | AhaDiff improve 当前没硬时间 budget。可加 `--time-budget 300s`，超时即回滚到 baseline。 |
| **Synthetic training data feedback loop** | Karpathy 提议（wiki → 微调） | 把 wiki 当 fine-tune 数据源 | AhaDiff `concepts.jsonl` + `claims.jsonl` 是天然 supervised dataset。可输出 JSONL 供用户 export 给本地小模型微调（不在本体训练，给 export hook）。 |

### 3.2 中优先级（Medium）

- Bayesian-style 多 baseline 对比（autoresearch 没有，AhaDiff 也不必上）
- Plot generator 自动画 score 曲线 — viewer 已有，扩展即可

---

## 四、知识图谱 / 笔记（Obsidian / Logseq / Notion）

### 4.1 高优先级（High）

| Feature | 来源 | 工作机制 | AhaDiff 实现路径 |
|---|---|---|---|
| **Bidirectional links + auto backlinks** | Obsidian `[[Note]]` / Logseq block ref | 任意 note/block 双链 | AhaDiff `concepts.jsonl` 已有 ancestry，但前端 Concepts 页没显示 backlinks。补 "incoming references" panel。 |
| **Block-level reference (`((block-id))`)** | Logseq | 可引用单个 bullet 而非整页 | AhaDiff claim 已是 atomic unit (file:line:hash)，需暴露为 URL 锚点：`/concepts/<id>?claim=<hash>` 让用户 deep link。 |
| **Local Graph view（当前节点的局部图）** | Obsidian Inline Local Graph plugin | 单 note 周围 1-2 跳邻居 | AhaDiff Concepts 页已有全局 graph。补 per-concept 局部视图（仅显示与当前 concept 直连的 ancestors + descendants），用 vis-network 或现有图引擎。 |
| **PDF / 富媒体附件 + 标注** | Logseq / Obsidian | 高亮 PDF 然后链回 graph | AhaDiff 是 diff 学习，pdf 不是核心；但**对图片/截图标注**值得：让用户在 viewer 给 lesson 截图加注释，作为 evidence 旁注。 |
| **Q&A 跨文档自然语言查询（带 citation）** | Notion 3.0 Q&A / Obsidian InfraNodus | 自然语言问，answer 返回 source citation 链接 | AhaDiff serve 已有 search endpoint，但没"问答"。补 `/api/qa` 端点：input=自然语言问题，output=answer + 引用的 lesson_id/concept_id 列表。复用 FTS5 + LLM。 |

### 4.2 中优先级（Medium）

- Canvas / 白板模式（Obsidian Canvas / Logseq Whiteboards）— AhaDiff 是阅读优先，Canvas ROI 中等
- Daily notes — concepts.jsonl 已按时间序，可派生 daily 视图
- Bases / database view — Concepts 页已是表格

### 4.3 低优先级（Low）

- Notion 3.0 autonomous agents — AhaDiff 已有 improve loop，再加 agent 是过度设计
- 多人协作 — local-first 是 AhaDiff 招牌，主动放弃这块

---

## 五、Diff 学习 / 代码考古专项

### 5.1 高优先级（High）

| Feature | 来源 | 工作机制 | AhaDiff 实现路径 |
|---|---|---|---|
| **CogDebt：commit 触发的"理解衰减"** | CogDebt 2025/2026 | 把 codebase 切块 → 测验 → 追踪理解度；当 commit 改了某块，相关理解自动 decay | **AhaDiff 现有 Graphify 7-state freshness 几乎就是这个**。缺一步：把 freshness 投影到 review queue 优先级——stale concept 的 review card 优先弹出。改 `review/optimizer.py` 加 freshness weight。 |
| **`git absorb` 启发的"自动并入旧 lesson"** | git-absorb 工作流 | uncommitted change 自动找到要 fixup 的 ancestor commit | AhaDiff 当一个 diff 与之前 lesson 重叠，自动 reuse concepts 而不是重新生成。orchestrator 加 dedup 步骤：先比较 changed_paths 与 concept_id index，命中则走 `lesson_hint.md` （已有）。 |
| **"代码考古"模式：仓库历史漫游** | code-archaeologist agent / Sourcegraph Code Graph | 给定不熟仓库，自动产出 architecture report + risk + onboarding plan | AhaDiff 当前以单 diff 为单位。新增 `ahadiff onboard <repo>` 模式：拉最近 N 个 commit + tag，自动生成 onboarding lesson 序列。比单 diff 更适合新成员。 |
| **GitByBit / GitMastery 风格的交互测验** | 交互式 git 学习平台 | 在浏览器跑 git 命令，错了即时反馈 | AhaDiff Quiz 是文本 ABCD。可加"diff sandbox"题型：给一段 broken diff，让用户在浏览器编辑器里改对，前端跑 patch 验证。比 ABCD 更接近真实开发。 |

### 5.2 中优先级（Medium）

- difit / aicommits 风格的 commit message draft — AhaDiff 是学习不是写作
- DORA metrics 仪表盘 — Ratchet 页已有 ratchet 时间线，扩展即可

---

## 六、汇总优先级表（建议下一阶段实施顺序）

| 排序 | Feature | 来源 | 估算工作量 | 依赖 |
|---|---|---|---|---|
| 1 | `.apkg` export | Anki | DONE（2026-05-12 WebUI download） | review.sqlite active cards → note model 映射；AnkiConnect / CLI export 仍未做 |
| 2 | Cloze deletion quiz 类型 | Anki/SuperMemo | M（3-4 天） | quiz_generate.md prompt 扩展 + Quiz.tsx 填空 UI |
| 3 | Desired Retention 深调 + Easy Days | Anki FSRS | S（1 天） | 现有 Settings/config 基础上补调度说明 + weekday shifting |
| 4 | freshness → review priority | CogDebt + Graphify | S（1-2 天） | review/optimizer.py weight |
| 5 | Image Occlusion（diff hunk 遮罩） | SuperMemo | M（4-5 天） | Quiz.tsx SVG overlay |
| 6 | `ahadiff summarize <commit-range>` PR 模式 | Copilot PR summary | M（3-4 天） | 复用 lesson + 多 commit orchestrator |
| 7 | `ahadiff concepts compact` wiki 合成 | Karpathy LLM Wiki | M（4-5 天） | concepts.jsonl 聚合 + 新 prompt |
| 8 | Q&A endpoint with citations | Notion Q&A | M（3-4 天） | FTS5 + 新 prompt + viewer 页 |
| 9 | Local graph view（per-concept） | Obsidian | S（2 天） | Concepts.tsx + 子图 query |
| 10 | FSRS personal optimizer | Anki | M（3 天） | fsrs lib optimizer call |
| 11 | Hunk-level lesson 拆分 | GitButler | L（1 周） | orchestrator changed_paths 重构 |
| 12 | `ahadiff onboard <repo>` 仓库 onboarding | code-archaeologist | L（1-2 周） | 多 commit pipeline |
| 13 | Diff sandbox quiz（交互测验） | GitByBit | L（2 周） | 浏览器 patch runner |

---

## 七、明确"不做"的边界（避免功能膨胀）

- **Virtual branches / Git 客户端功能**（GitButler 强项）— AhaDiff 是学习层，不是 Git 客户端
- **AI commit message 生成 / 自动 commit**（aicommits / OpenCommit / GitKraken）— 跟 AhaDiff "学" 的核心定位冲突
- **多人协作 / 云同步** — local-first 招牌不变（review.sqlite 是 single source of truth）
- **Notion 3.0 autonomous agents** — improve loop 已够，再加 agent 是过度设计
- **原生移动 App** — PWA 已能装到 home screen，原生化 ROI 低

---

## Sources

- [Anki FSRS tutorial - fsrs4anki](https://github.com/open-spaced-repetition/fsrs4anki/blob/main/docs/tutorial.md)
- [Anki Deck Options manual](https://docs.ankiweb.net/deck-options.html)
- [Anki FSRS algorithm explained 2026](https://studycardsai.com/blog/anki-fsrs-algorithm)
- [RemNote spaced repetition](https://www.remnote.com/feature/spaced-repetition)
- [RemNote getting started SRS](https://help.remnote.com/en/articles/6022755-getting-started-with-spaced-repetition)
- [Mochi changelog](https://mochi.cards/changelog/)
- [Mochi cards docs](https://mochi.cards/docs/cards/)
- [GitButler virtual branches](https://docs.gitbutler.com/features/branch-management/virtual-branches)
- [GitButler commit editing absorb](https://docs.gitbutler.com/features/branch-management/commits)
- [GitLens features overview](https://techcommunity.microsoft.com/blog/educatordeveloperblog/12-gitlens-features-that-revolutionized-my-coding-workflow-in-vs-code/4421891)
- [GitHub Copilot pull request summaries](https://docs.github.com/en/copilot/responsible-use/pull-request-summaries)
- [GitHub Copilot code review concepts](https://docs.github.com/en/copilot/concepts/agents/code-review)
- [Karpathy nanochat](https://github.com/karpathy/nanochat)
- [Karpathy LLM Wiki gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)
- [Karpathy autoresearch](https://github.com/karpathy/autoresearch)
- [autoresearch program.md](https://github.com/karpathy/autoresearch/blob/master/program.md)
- [Obsidian must-have plugins 2025](https://www.dsebastien.net/2022-10-19-the-must-have-obsidian-plugins/)
- [Obsidian InfraNodus AI graph](https://infranodus.com/obsidian-plugin)
- [Logseq overview & flashcards](https://pangea.app/glossary/logseq)
- [Logseq SM-5 cards](https://blog.neilhighley.com/2025/02/using-llms-and-logseq-to-create-flashcards/)
- [Notion Q&A introduction](https://www.notion.com/blog/introducing-q-and-a)
- [Notion 3.0 features](https://max-productive.ai/ai-tools/notion-ai/)
- [Sourcegraph Cody review 2026](https://devtoolsreview.com/reviews/cody-review/)
- [Cursor vs Cody comparison](https://www.devtoolsacademy.com/blog/cody-vs-cursor-choosing-the-right-ai-code-assistant-for-your-development-workflow/)
- [git-absorb on GitHub](https://github.com/tummychow/git-absorb)
- [SuperMemo image occlusion](https://help.supermemo.org/wiki/Visual_learning)
- [Migaku spaced repetition 2026](https://migaku.com/blog/language-fun/spaced-repetition-in-2026-how-it-actually-works)
- [Brainscape SRS algorithms](https://www.brainscape.com/academy/comparing-spaced-repetition-algorithms/)
- [GitByBit](https://gitbybit.com/)
- [GitMastery](https://gitmastery.me/)
- [GitKraken AI features](https://help.gitkraken.com/gitkraken-desktop/gkd-gitkraken-ai/)
- [code-archaeology topic on GitHub](https://github.com/topics/code-archaeology)
