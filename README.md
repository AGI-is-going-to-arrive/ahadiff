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
- 一条可比较的 **质量评分历史**（Ratchet，`review.sqlite` 为唯一真相源，`results.tsv` 为导出视图）

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

# 棘轮优化
ahadiff improve abc123 --rounds 6

# 安装到 AI 工具（v0.1 支持 4 个核心 CLI）
ahadiff install claude    # Claude Code → .claude/skills/
ahadiff install codex     # Codex CLI → AGENTS.md
ahadiff install gemini    # Gemini CLI → GEMINI.md
ahadiff install opencode  # OpenCode → AGENTS.md + .opencode/agents/
# v0.2 扩展: cursor / copilot / windsurf / cline / amp / jules / aider
```

产出物结构：

```text
.ahadiff/
├─ config.toml           # repo 级配置
├─ review.sqlite         # 唯一真相源（SRS/results/signals）
├─ concepts.jsonl        # 概念图谱（term_key-keyed upsert）
├─ runs/<run_id>/
│  ├─ lesson/
│  │  ├─ lesson.full.md
│  │  ├─ lesson.hint.md
│  │  └─ lesson.compact.md
│  ├─ claims.jsonl       # 可验证断言
│  ├─ quiz/
│  │  └─ quiz.jsonl      # 主动回忆题
│  ├─ cards.jsonl        # SRS 复习卡
│  └─ score.json         # 8 维评分 + verdict
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
├─ src/ahadiff/lesson/          # Learnability gate
├─ src/ahadiff/prompts/         # wheel 内打包的 prompt 资源
├─ prompts/                     # Lesson / claim prompt 模板
├─ tests/unit/                  # Stage 0 + Stage 1 + Layer 1.5 + Stage 2 单元测试
├─ ui/                          # HTML 原型 v1–v6（设计迭代史）
└─ CLAUDE.md                    # 项目 AI 上下文索引
```

## 当前阶段

**Stage 1 的 Task 1/2、Layer 1.5 的 Task 7，以及 Stage 2 / Task 5-8 已落地。** 仓库现在除了设计文档和 HTML 原型，还包含 `contract-freeze.md`、最小 contracts skeleton、`pyproject.toml`、可执行的 CLI scaffold（`ahadiff init` / `ahadiff doctor` / `ahadiff config show --resolved` / `ahadiff provider test` / `ahadiff claims` / `ahadiff maint clean-orphans` / `python -m ahadiff`），`src/ahadiff/safety/` 安全层基础实现、`src/ahadiff/llm/{provider,probe,cache,cost}.py` 与 8 个 provider adapter、`src/ahadiff/git/{__init__,repo,capture,parser,path_tokens,line_map,symbols,hunk_hash}.py`、`src/ahadiff/claims/{schema,extract,runtime,verify,negative_scan,classify}.py`、`src/ahadiff/lesson/learnability.py`、`prompts/claim_extract.md` 与 wheel 内打包的 `src/ahadiff/prompts/claim_extract.md`、`ahadiff learn --dry-run`、非 git 目录下可运行且会读取 workspace `.ahadiff/config.toml` 的 `--patch` / `--compare`、`ahadiff graph status|import|refresh`、`ahadiff unlock --force`、`line_map.json` / `symbols.json` / `artifact_set.json` / `before_text_by_path.json` / `after_text_by_path.json`，以及对应的 Stage 0 + Stage 1 + Layer 1.5 + Stage 2 单元测试。evaluator 和 viewer runtime 仍未实现。

本轮还补齐了几项运行时硬化：`.ahadiffignore` 已真正接入 capture 主链，跨行 secret / prompt injection 会被拦截，`--staged --unstaged` 有了明确的 `git_staged_unstaged` source_kind，git-sourced patch 增加了字节上限，claim verifier 已支持 `claims.raw.jsonl -> claims.jsonl` 的 deterministic verify，`source_hunks[]` 现在带显式 `side`（`old / new / either`）来避免 old/new 同号歧义，`claims --extract` 现在有独立 runtime，并且会在 run metadata 要求 `redacted_remote` 时继续走脱敏 payload；`provider test` 和 `claims --extract` 都会把 Chat / Responses 终点归一化回 API 根地址；extract 成功但 verify 失败时会清理新的 raw 文件；plain unified diff 的 patch file / stdin 现在也会按 `max_files` 正常截断，binary compare 会保留 `selected_files` 路径；learnability gate 已补齐 empty diff、binary diff、all-context、rename-only、structural delete 和高信号大 churn 边界。

当前已落地的最小验证：

```bash
uv run pytest tests/unit
uv run ruff check src tests
uv run ruff format --check src tests
uv run pyright
uv build --wheel
uv run python -m ahadiff --version
uv run ahadiff init
uv run ahadiff doctor
uv run ahadiff config show --resolved
uv run python -m ahadiff claims --help
uv run python -m ahadiff learn --help
```

本次实际结果：`env PYTEST_ADDOPTS='-p no:cacheprovider' uv run pytest tests/unit -q` 为 `286 passed`；`uv run pytest tests/unit/test_claim_extract.py tests/unit/test_claim_verify.py tests/unit/test_git_capture.py tests/unit/test_learnability.py tests/unit/test_probe.py tests/unit/test_provider.py tests/unit/test_diff_parser.py -q` 为 `169 passed`；`uv run ruff check src tests`、`uv run ruff format --check src tests`、`uv run pyright` 与 `uv build --wheel` 全通过；`uv run python -m ahadiff --version`、`uv run python -m ahadiff claims --help`、`uv run python -m ahadiff learn --help` 可正常运行。另做了一次 clean wheel 验证：在临时虚拟环境离线安装新 wheel 后，确认 wheel 内包含 `ahadiff/prompts/claim_extract.md`、`ahadiff/claims/runtime.py`、`ahadiff/lesson/learnability.py`，并成功在 non-git workspace 跑通 `python -m ahadiff learn --patch - --dry-run`；该次产物的 `source_kind=patch_stdin`，metadata 中也带有 `learnability`。

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
