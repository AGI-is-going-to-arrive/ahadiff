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
- 一条可比较的 **质量评分历史**（Ratchet，`review.sqlite` 为唯一真相源，`results.tsv` 为导出视图）

当前代码已经能稳定产出 Lesson / Claims / Quiz / Cards / Score / Ratchet；review 流的 SRS runtime 和 improve loop core 已落地，Viewer / serve / Task 17 targeted verify 仍在后续阶段。

> Code Wiki 解释仓库，知返解释这次改动 —— 而且每一句话都能回到代码证据。

## 为什么要做

AI 写代码越来越快，开发者却越来越不知道自己有没有真的看懂。"vibe coding" 跑得太远，人需要"知返"：

1. **AI 写完，理解要返还给人** —— 改动不能停留在 commit message
2. **每个解释都要有证据** —— 不允许幻觉函数、虚构因果
3. **知识应该积累** —— 同一个概念被多次修改时，应该有 backlinks 和演化记录
4. **质量应该可比较** —— 用 immutable evaluation bundle + git ratchet 取代"看着差不多就行"

## 核心理念（N-文件契约）

受 Karpathy / autoresearch 三文件启发，扩展为 N-文件变体：

| 文件 | 谁可以改 | 作用 |
|------|----------|------|
| `program.md` | 人类 | 自然语言状态机，描述 improve loop |
| evaluation bundle | **不可改** | `evaluator.py` + `rubric.py` + `rubric.yaml` + `gates.py` + `deterministic.py`（共 5 文件，整体 immutable） |
| `prompts/*.md` | Agent | 唯一可优化的"创作策略"目录（agent 只改 prompt，不改用户代码） |

LOOP：编辑 → commit → 评估 → 高分 keep / 低分 reset → 写入 `review.sqlite`（唯一真相源，`results.tsv` 为导出视图）。

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

# 在浏览器中交互（Quiz/SRS/Dashboard）
ahadiff serve

# 棘轮优化（Task 16 core 已落地；需要已有 finalized run 和 provider 配置）
ahadiff improve --suite local --rounds 6

# 安装到 AI 工具（v0.1 支持 4 个核心 CLI）
ahadiff install claude    # Claude Code → .claude/skills/
ahadiff install codex     # Codex CLI → AGENTS.md
ahadiff install gemini    # Gemini CLI → GEMINI.md
ahadiff install opencode  # OpenCode → AGENTS.md + .opencode/agents/
# v0.2 扩展: cursor / copilot / windsurf / cline / amp / jules / aider
```

当前已落地的主要产出结构：

```text
.ahadiff/
├─ config.toml           # repo 级配置
├─ review.sqlite         # 唯一真相源（SRS/results/signals）
├─ concepts.jsonl        # git 输入的 repo 级概念累积
├─ results.tsv           # 从 review.sqlite 导出的可读视图
├─ runs/<run_id>/
│  ├─ patch.diff
│  ├─ metadata.json
│  ├─ line_map.json
│  ├─ symbols.json
│  ├─ artifact_set.json
│  ├─ before_text_by_path.json
│  ├─ after_text_by_path.json
│  ├─ claims.raw.jsonl   # LLM 原始 claim 候选
│  ├─ claims.jsonl       # 可验证断言
│  ├─ score.json         # 8 维评分 + verdict
│  ├─ finalized.json     # run 发布标记
│  ├─ concepts_local.jsonl   # non-git 输入的 run 级概念累积（按需生成）
│  ├─ lesson/
│     ├─ lesson.full.md
│     ├─ lesson.hint.md
│     ├─ lesson.compact.md
│     ├─ misconception.md
│     └─ not_proven.md
│  └─ quiz/
│     ├─ quiz.jsonl
│     └─ cards.jsonl     # 仅 PASS / CAUTION 生成
├─ improve/
│  ├─ <session_id>.json  # improve session 状态
│  └─ wt/<12hex>-rN/     # pending conflict 时保留的临时 worktree
├─ audit.jsonl           # LLM 调用审计
├─ audit.private.jsonl   # strict_local 本机审计（gitignored）
├─ ahadiff.lock          # portalocker 文件锁
```

.ahadiffignore            # repo 根的路径过滤

## 8 维评分 Rubric

| # | 维度 | 权重 | 硬门禁 |
|---|------|------|--------|
| 1 | Accuracy（准确性） | 20 | < 14 → FAIL |
| 2 | Evidence（证据链） | 18 | < 12 → FAIL |
| 3 | Diff Coverage（覆盖度） | 14 | — |
| 4 | Learnability（可学性） | 14 | — |
| 5 | Quiz Transfer（迁移） | 10 | — |
| 6 | Spec Alignment | 10 | — |
| 7 | Conciseness（简洁度） | 8 | — |
| 8 | Safety & Privacy | 6 | Critical → FAIL |

三档 verdict：**PASS** ≥ 80 / **CAUTION** 60–80 / **FAIL** < 60。

## 项目结构

```text
ahadiff/
├─ AhaDiff Warm v6.html         # 当前最新 UI 参考模板
├─ AhaDiff-Blueprint.html       # 八层架构可视化（含 i18n / VCR / 50+ CC）
├─ AhaDiff-Competitors-Research.html  # 竞品矩阵 + 5 条护城河
├─ doc/                         # 中文设计文档
│  ├─ contract-freeze.md        # Stage 0 架构权威源
│  ├─ ahadiff设计思路.md          # [ARCHIVED] 早期架构快照
│  ├─ 知返ahadiff改名后的后续方案.md  # [ARCHIVED] 改名过渡方案
│  └─ AhaDiff_frontend_design_v1.1_revised.md  # 前端视觉手册（v0.1=React 19+Vite）
├─ src/ahadiff/contracts/       # Stage 0 最小 contracts skeleton
├─ src/ahadiff/core/            # Stage 1 / Task 1 工程骨架
├─ src/ahadiff/safety/          # Stage 1 / Task 2 安全层基础实现
├─ src/ahadiff/llm/             # Layer 1.5 / Task 7 provider + probe
├─ src/ahadiff/git/             # Stage 2 / Task 5-6 diff capture + 结构化
├─ src/ahadiff/claims/          # Stage 2 / Task 8 claim 提取 + 验证 + runtime
├─ src/ahadiff/lesson/          # Stage 3 / Task 8.5 + 9 learnability + lesson 生成
├─ src/ahadiff/quiz/            # Stage 3 / Task 10 quiz + cards
├─ src/ahadiff/wiki/            # Stage 3 / Task 10 concepts ledger
├─ src/ahadiff/eval/            # Stage 3 / Task 11-12 evaluator + ratchet + results
├─ src/ahadiff/prompts/         # wheel 内打包的 prompt 资源
├─ prompts/                     # Lesson / claim prompt 模板
├─ src/ahadiff/improve/         # Stage 5 / Task 16 improve loop core
├─ tests/unit/                  # Stage 0 + Stage 1 + Layer 1.5 + Stage 2 / Stage 3 / Stage 4 / Stage 5 单元测试
├─ ui/                          # HTML 原型 v1–v6（设计迭代史）
└─ CLAUDE.md                    # 项目 AI 上下文索引
```

## 当前阶段

**Stage 1 的 Task 1/2、Layer 1.5 的 Task 7、Stage 2 / Task 5/6/8、Stage 3 / Task 8.5/9/10/11/12、Stage 4 / Task 15，以及 Stage 5 / Task 16 已落地。** 当前代码除了设计文档和 HTML 原型，还已经有：

- `ahadiff learn` 的主链路：支持 git / `--patch` / `--compare` capture，经过 learnability gate 后生成 `claims.raw.jsonl -> claims.jsonl`、`lesson.full|hint|compact.md`、`misconception.md`、`not_proven.md`
- `ahadiff quiz`：对已生成的 `quiz.jsonl` 做最小交互式答题，并回显 source_claims / file:line evidence
- `cards.jsonl` / `concepts.jsonl`：评分通过的 run 会生成 cards；git 输入写 repo 级 `concepts.jsonl`，non-git 输入写 run 级 `concepts_local.jsonl`
- `ahadiff score` / `ahadiff verify` / `ahadiff export-results`：评分、ratchet 判定和 `results.tsv` 导出都已可用
- `ahadiff review` / `ahadiff mark <claim_id> wrong` / `ahadiff db {backup,restore,check,import-results,finalize-targeted}`：`review.sqlite` 的 review / signals / result_events / lossy import / targeted finalize 链路都已可用
- `ahadiff improve --suite local --rounds N`：目前仅支持 `--suite local`。它从已有 finalized run 中选择 baseline，在 git worktree 里只改白名单 prompt，重放同一 diff 并重新评分；候选分数高于 baseline 且 hard gates 通过时，会尝试 cherry-pick prompt commit 回主分支，并记录 `event_type=improve` / `status=targeted_verify`；未提升则记录 `discard`，cherry-pick 冲突则保留 pending worktree 且不 finalized
- `src/ahadiff/eval/{rubric,gates,deterministic,evaluator,results,ratchet}.py`：8 维评分、hard gates、结果写入、ratchet 选择和导出视图
- `src/ahadiff/review/{database,scheduler,schemas,signal}.py`：review.sqlite schema / migration、FSRS-6 调度、review queue、learning signal 和 review CLI 后端
- `src/ahadiff/improve/{loop,program}.py`：improve session、immutable improve_program、worktree 隔离、5 个 mutable prompt 白名单、replay-learn、cherry-pick 顺序、session 校验与 pending worktree resume guard
- source checkout 与 wheel 安装态的 runtime 资源定位：`eval_bundle_version`、`prompt_version`、lesson prompt 加载都已经接到包内资源
- `ahadiff serve` / `ahadiff install` / Task 17 的自动 targeted verification、`keep_final` 决策与 Phase 2.5 rewrite 仍在后续阶段；当前已有的是 Task 16 产生 `targeted_verify` 事件，以及 `db finalize-targeted` 的手动收口入口

本轮又收口了几件容易出错的运行时边界：`prompt_version` 只描述 AhaDiff 自己的 prompt 资源，不再受目标工作区 `prompts/` 影响；lesson JSON 解析会跳过不匹配 schema 的示例块；lesson/quiz 目录改成生成后再接到主链，失败时会回滚；如果 lesson 生成阶段失败，会清掉新写出的 `claims.raw.jsonl` / `claims.jsonl`、`quiz/` 和 `concepts_local.jsonl` 半成品；`learn` 成功后会写入 `event_type=learn` 的评分事件和 `score.json`，manual `score` / `verify` 不再污染 learn 的 ratchet baseline；`ReviewCard` 现在会校验 `last_rating` 范围和 `card_state/stale_reason` 组合；伪造 quiz 也不会再误拿 `PASS`。Task 15 这轮也已经补齐：旧版 `cards` schema 会显式迁移 `stale_reason`，schema-invalid `cards.jsonl` 会降级成 warning，重复 regenerate 不会把旧 active 卡留在 due queue 里；`regenerate --only quiz` 在 `evaluate_run` 失败时会恢复旧 quiz/cards，在 `FAIL` 时会删掉陈旧 `cards.jsonl` 并把该 run 的 active 卡标成 `stale + staleness_unknown`；lossy TSV import 现在走单连接整批导入，坏行或 duplicate identity 会整批回滚；`rollback_result_event` 也改成同一连接里完成 delete + export rows，普通 DB connect 不会再因为路径 typo 静默建目录。Task 16 这轮补上了 `lesson_hint.md` 白名单、session_id 路径校验、30 分钟 replay timeout、双 prompt temp+replace 写入、非冲突 cherry-pick 失败区分、discard/pending conflict 不写 `finalized.json`、pending conflict 不作为下一轮 baseline、volatile staged/unstaged 输入从保存的 `patch.diff` 重放、短 worktree 路径、`--rounds` 上限 20、null byte 拒绝，以及 Ctrl+C 在已完成 round 后不再追加第二条 crash event。

当前已落地的最小验证：

```bash
source .venv/bin/activate && pytest tests/unit -q
source .venv/bin/activate && ruff check src tests
source .venv/bin/activate && ruff format --check src tests
source .venv/bin/activate && pyright
source .venv/bin/activate && uv build --wheel
source .venv/bin/activate && python -m ahadiff quiz --help
source .venv/bin/activate && python -m ahadiff review --help
source .venv/bin/activate && python -m ahadiff improve --help
source .venv/bin/activate && python -m ahadiff db check --help
```

本次实际结果：`source .venv/bin/activate && pytest tests/unit/test_improve_loop.py -q` 为 `14 passed`；`source .venv/bin/activate && pytest tests/unit/test_improve_loop.py tests/unit/test_results.py tests/unit/test_review.py -q` 为 `56 passed`；`source .venv/bin/activate && pytest tests/unit -q` 为 `397 passed`；`source .venv/bin/activate && ruff check src tests`、`source .venv/bin/activate && ruff format --check src tests`、`source .venv/bin/activate && pyright` 与 `source .venv/bin/activate && uv build --wheel` 全通过；`source .venv/bin/activate && python -m ahadiff improve --help` 也已实测可用。另做了一次 clean-room wheel 验证：在临时虚拟环境安装新 wheel 后，确认安装态 `evaluate_run()`、`compute_prompt_version()`、lesson/quiz prompt 加载、lesson JSON 解析和 `compute_term_key()` 都能正常工作，且目标工作区自带的 `prompts/` 不会污染 `prompt_version`。

下一步路线图：

- [ ] `v0.1`（MVP）：CLI + Lesson + Evaluator + Ratchet 全链路 + React 19 WebUI（`ahadiff serve`）+ 8 种 LLM Provider + 8 种 diff 捕获（含 --unstaged / git show）+ 4 个 CLI install target + i18n + 阶段门禁
- [ ] `v0.2`：--compare-dir + --patch-url + 7 个 IDE install target + watchdog 增量重生 + section-level helpfulness + Team 功能
- [ ] `v1.0`：PWA + public benchmark suite

## 灵感来源

- **karpathy/autoresearch** —— N-文件契约（三文件变体） + git ratchet
- **alchaincyf/darwin-skill** —— 8 维 rubric + Phase 2.5 重写
- **Evol-ai/SkillCompass** —— PASS/CAUTION/FAIL + weakest-dimension-first
- **ZJU-REAL/SkillZero** —— helpfulness-driven retention + compact card
- **safishamsi/graphify** —— repo-level graph overlay
- **karpathy/llm-wiki** gist —— persistent compounding wiki

## 设计公理

1. **Evidence first** —— 每条 claim 必须能回到 `file:line`
2. **Learning over summary** —— 出题 + 复习 > 漂亮总结
3. **Local-first trust** —— 隐私三档（`strict_local` / `redacted_remote` / `explicit_remote`），默认 `strict_local`
4. **Paper-like seriousness** —— 学术期刊感，拒绝冷紫渐变 SaaS
5. **One accent per style** —— 暖白纸感 + 单一 accent 色

## License

待定（计划 MIT）。

---

> 知返 / AhaDiff —— Δ知 ↺
