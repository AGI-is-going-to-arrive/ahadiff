# 知返 AhaDiff

> **AI 写完，Diff 教回。**
>
> 把 Claude / Codex / Cursor 写出的每一个 git diff，变成带证据链、会出题、会复习、会自我迭代的学习课程。

[English](./README.en.md) · [使用指南](./docs/USER_GUIDE.zh.html) · [中文视频教程](./docs/video/output/ahadiff-tutorial.zh.burned-subtitles.mp4) · [English tutorial video](./docs/video/output/ahadiff-tutorial.en.burned-subtitles.mp4) · [设计文档](./doc/) · [UI 原型](./ui/)

---

## 这是什么

**知返 AhaDiff** 是一个 **local-first 的 AI Coding 学习层**。

它不是 PR 摘要，不是 repo wiki，也不是又一个"代码解释器"。它读取每一次 git diff，把改动转成：

- 一篇带 `file:line` 证据链的 **学习笔记**（Lesson）
- 一份每条结论都可回溯的 **断言清单**（Claims）
- 一条可比较的 **质量评分历史**（Ratchet，`review.sqlite` 为唯一真相源，`results.tsv` 和 JSON 导出都只是视图）

当前代码已经能稳定产出 Lesson / Claims / Quiz / Cards / Score / Ratchet，包括 SRS 复习、WebUI、13 种 AI 工具安装目标、8 维评分 + LLM judge、中英文 i18n 以及 `improve` 自动迭代。

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
| `prompts/*.md` | Agent | improve loop 只改白名单里的生成 prompt；`eval_judge.md` 是评判 prompt 资源，不在可写白名单 |

LOOP：编辑 → commit → 评估 → 高分 keep / 低分 reset → 写入 `review.sqlite`（唯一真相源，`results.tsv` 和 JSON 导出都只是视图）。

## 快速开始

下面命令对应当前 CLI。AhaDiff 当前还未发布到 PyPI；源码 checkout 中可以用 `uv run ahadiff ...`，也可以用 `uv tool install --editable .` 安装本机 CLI。用本地 editable 或本地 wheel 安装后，再直接用 `ahadiff ...`。

```bash
# 在 AhaDiff 源码 checkout 中安装本机 CLI
uv tool install --editable .

# 或者直接在源码目录运行
uv run ahadiff --version

# 初始化当前 repo 的 .ahadiff/
ahadiff init
ahadiff doctor
ahadiff config show --resolved

# 学习最近一次 commit
ahadiff learn --last

# 学习最近一次 commit，并在环境允许时打开本地 lesson
ahadiff learn --last --open

# 按本地 spec 评分；语义复核需要显式开启并使用 judge provider
ahadiff learn --last --against-spec SPEC.md
ahadiff learn --last --against-spec SPEC.md --spec-semantic-review

# 学习一个 commit range
ahadiff learn HEAD~1..HEAD

# 学习 staged 改动
ahadiff learn --staged

# 学习工作区未暂存改动；需要时可包含 untracked 文件
ahadiff learn --unstaged
ahadiff learn --unstaged --include-untracked

# 只学习当前工作区里的指定路径；可重复传多个路径
ahadiff learn --unstaged --include-untracked --changed-path src/app.py
ahadiff learn --changed-path src/app.py --changed-path viewer/src/App.tsx

# 学习 patch、URL patch、或两个目录的差异
ahadiff learn --patch change.diff
ahadiff learn --patch-url "https://example.com/change.diff"
ahadiff learn --compare old.py new.py
ahadiff learn --compare-dir old/ new/

# 复习和浏览
ahadiff quiz <run_id>
ahadiff review
ahadiff mark <claim_id> wrong
ahadiff serve
ahadiff serve --port 8765 --no-browser
ahadiff serve --watch  # 需要 watchdog extra

# 本地静态预览导出和概念健康检查
ahadiff export preview <run_id> --out .ahadiff/export-preview
ahadiff concepts lint --dry-run

# Challenge loop 默认关闭；开启后先构建，再在 WebUI 里完成 challenge/review/adapt
ahadiff challenge build <run_id>
ahadiff challenge status

# 后台 watch 模式（需要 watchdog extra）
ahadiff watch --debounce 2 --cooldown 30

# 棘轮优化；需要已有 finalized run 和 provider 配置
ahadiff improve --suite local --rounds 6
```

源码 checkout 里可以用等价命令：

```bash
uv sync --locked --dev
uv run python -m ahadiff --version
uv run python -m ahadiff learn --last
```

配置远端或本地 OpenAI-compatible provider 时，不要把真实 key 写入命令、README、manifest 或 git 追踪文件；只写环境变量名。`provider test` 会发送一次小探针请求并写入 `.ahadiff/config.toml`。

```bash
export AHADIFF_PROVIDER_BASE_URL="https://api.example.com/v1"
export AHADIFF_PROVIDER_API_KEY="<provider-api-key>"

ahadiff provider test \
  --name gpt55 \
  --provider-class openai_responses \
  --base-url "$AHADIFF_PROVIDER_BASE_URL" \
  --model gpt-5.5 \
  --api-key-env AHADIFF_PROVIDER_API_KEY \
  --privacy-mode explicit_remote

ahadiff learn --last

# 临时覆盖已配置 provider/model 时才需要显式传参
ahadiff learn --last --provider gpt55 --model gpt-5.5
```

真实 LLM judge smoke 默认不跑。要用 GPT-5.5，显式传环境变量；不要把 key 或真实 endpoint 写死进文档：

```bash
AHADIFF_LIVE_LLM_JUDGE=1 \
AHADIFF_LIVE_LLM_API_KEY="$AHADIFF_LIVE_LLM_API_KEY" \
AHADIFF_LIVE_LLM_BASE_URL="$AHADIFF_LIVE_LLM_BASE_URL" \
AHADIFF_LIVE_LLM_MODELS="gpt-5.5" \
pytest tests/live/test_llm_judge_live.py -q
```

## AI 工具和自动化安装

先用 `--dry-run --manifest` 看清楚会写哪些文件，再执行真实安装：

```bash
ahadiff install --detect
ahadiff install claude --dry-run --manifest

ahadiff install <target>
ahadiff uninstall <target>
```

13 个 target 的真实写入路径如下：

| target | 命令 | 写入路径 |
|---|---|---|
| `aider` | `ahadiff install aider` | `CONVENTIONS.md` 标记段 |
| `claude` | `ahadiff install claude` | `.claude/skills/ahadiff/SKILL.md` + `CLAUDE.md` 标记段 |
| `cline` | `ahadiff install cline` | `.clinerules/ahadiff.md` |
| `codex` | `ahadiff install codex` | `AGENTS.md` 标记段 |
| `continue` | `ahadiff install continue` | `.continue/rules/ahadiff.md` |
| `copilot` | `ahadiff install copilot` | `.github/copilot-instructions.md` 标记段 |
| `cursor` | `ahadiff install cursor` | `.cursor/rules/ahadiff.mdc` |
| `gemini` | `ahadiff install gemini` | `GEMINI.md` 标记段 |
| `github-action` | `ahadiff install github-action` | `.github/workflows/ahadiff-verify.yml`；加 `--layer2` 时额外写 `.github/workflows/ahadiff-generate.yml` |
| `hooks` | `ahadiff install hooks` | git hooks path，通常是 `.git/hooks/post-commit` + `.git/hooks/pre-push`；Windows v0.1 会拒绝 |
| `opencode` | `ahadiff install opencode` | `AGENTS.md` 标记段 + `.opencode/agents/ahadiff.md` |
| `roo` | `ahadiff install roo` | `.roo/rules/ahadiff.md` |
| `windsurf` | `ahadiff install windsurf` | `.windsurf/rules/ahadiff.md` |

这些 target 当前主要生成规则文件、hook 或 GitHub workflow。测试覆盖模板渲染、写入、防覆盖、检测和卸载；没有启动各 IDE/CLI 去验证它们实际加载这些规则。`hooks` 是非阻塞提醒，不会自动执行 `learn`；GitHub Action verify workflow 在没有 `.ahadiff/runs` 时会以“无 artifact 可校验”成功退出。

WebUI 里的 Settings → AI 工具指引（URL 仍是 `?tab=integrations`）复用同一组 target，并且只通过受保护的 serve API 写入。浏览器会先预览 manifest 并拿到 hash，写入 / 移除时必须把这个 hash 作为 `confirmed_manifest_hash` 带回，同时带本地写 token。接口只写启动 `ahadiff serve` 的当前 repo，不接受浏览器传入任意 repo 路径。这里写的是 repo-local AI 工具指引，不是再次安装 AhaDiff CLI；Guide 页只做使用说明和入口跳转，不直接调用 install API。

高级 / 维护命令已经可用，但更适合维护者、CI 或明确知道状态文件含义的用户：

```bash
# improve / targeted finalize
ahadiff improve --suite local --rounds 6
ahadiff improve --resume <session_id>
ahadiff db finalize-targeted <run_id>

# 评分、CI 校验和导出
ahadiff score <run_id>
ahadiff verify <run_id>
ahadiff verify --ci
ahadiff export-results

# 只读 MCP stdio server（给支持 MCP 的本地 agent 使用）
ahadiff mcp-server --repo-root .

# benchmark / DB / Graphify / concepts derived cache
ahadiff benchmark --suite local
ahadiff db check
ahadiff db backup
ahadiff db restore <backup_path>
ahadiff db import-results results.tsv --i-understand-this-is-lossy
ahadiff graph status
ahadiff graph import
ahadiff graph refresh
ahadiff concepts list
ahadiff concepts verify
ahadiff concepts sync
ahadiff concepts export
ahadiff concepts rollback --dry-run
ahadiff maint clean-orphans --dry-run
```

当前已落地的主要产出结构：

```text
.ahadiff/
├─ config.toml           # repo 级配置
├─ review.sqlite         # 唯一真相源（SRS/results/signals）
├─ concepts.jsonl        # git 输入的 repo 级概念累积
├─ results.tsv           # 从 review.sqlite 导出的 TSV 可读视图
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
│  ├─ spec_alignment.json    # 可选：--against-spec 的 deterministic/semantic 对齐结果
│  ├─ graphify_context.json  # 可选：Graphify 上下文摘要
│  ├─ graphify_signoff.json  # 可选：Graphify provenance/signoff 检查
│  ├─ judge.json         # 可选 LLM judge 评分（配置 judge_provider 后生成）
│  ├─ finalized.json     # run 发布标记
│  ├─ concepts_local.jsonl   # non-git 输入的 run 级概念累积（按需生成）
│  ├─ lesson/
│     ├─ lesson.full.md
│     ├─ lesson.hint.md
│     ├─ lesson.compact.md
│     ├─ misconception.md
│     └─ not_proven.md
│  └─ quiz/
│     ├─ quiz.jsonl      # open-answer 题目；无 cards 时允许缺省 review_card_id
│     ├─ misconception_cards.jsonl
│     └─ cards.jsonl     # 仅 PASS / CAUTION 生成，并回填 review_card_id
├─ improve/
│  ├─ <session_id>.json  # improve session 状态，含 phase25_attempted
│  └─ wt/<12hex>-rN/     # pending conflict 或 Phase 2.5 时使用的临时 worktree
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
│  ├─ contract-freeze.md        # 架构契约权威源
│  ├─ ahadiff设计思路.md          # [ARCHIVED] 早期架构快照
│  ├─ 知返ahadiff改名后的后续方案.md  # [ARCHIVED] 改名过渡方案
│  └─ AhaDiff_frontend_design_v1.1_revised.md  # 前端视觉手册
├─ src/ahadiff/contracts/       # 枚举、DTO、错误类型
├─ src/ahadiff/core/            # 配置、路径、ID、JSON/SQLite 安全 helper、task runner
├─ src/ahadiff/safety/          # 脱敏、注入检测、安全门禁
├─ src/ahadiff/llm/             # LLM provider + probe + cache
├─ src/ahadiff/git/             # diff capture + 结构化解析
├─ src/ahadiff/claims/          # claim 提取 + 验证 + runtime
├─ src/ahadiff/lesson/          # learnability gate + 三档 lesson 生成
├─ src/ahadiff/quiz/            # 测验 + 卡片 + misconception cards
├─ src/ahadiff/wiki/            # concepts.jsonl + 健康度 lint
├─ src/ahadiff/challenge/       # opt-in 挑战模式 + diff gap review
├─ src/ahadiff/export/          # 本地静态预览 + deterministic zip
├─ src/ahadiff/graphify/        # 概念图谱后端
├─ src/ahadiff/eval/            # 8 维评分 + spec alignment + ratchet + LLM judge
├─ src/ahadiff/mcp/             # read-only MCP server（7 个工具）
├─ src/ahadiff/serve/           # 本地 WebUI serve API（72 路由）
├─ src/ahadiff/install/         # 13 安装目标 + hooks
├─ src/ahadiff/i18n/            # locale resolver + prompt 语言
├─ src/ahadiff/review/          # review.sqlite / FSRS-6 / APKG 导出
├─ src/ahadiff/prompts/         # wheel 内打包的 prompt 资源（含 eval_judge.md）
├─ prompts/                     # Lesson / claim / quiz / eval judge prompt 模板
├─ src/ahadiff/improve/         # improve loop、targeted verify、Phase 2.5
├─ benchmarks/                  # benchmark fixtures + manifest + scripts
├─ tests/unit/                  # 单元测试
├─ tests/eval/                  # benchmark suite 测试
├─ tests/integration/           # pinned integration fixtures
├─ tests/live/                  # 需要显式环境变量开启的真实 LLM judge smoke
├─ viewer/                      # React 19 + Vite + Zustand + vanilla CSS 前端（14 个生产页面 TSX / 52 个非测试 TSX / 47 个 CSS / 1490 i18n scalar keys；Phase 2: Challenge 页面、Export modal、HealthBadge；最新完整 gate：后端 unit 2530 + viewer Vitest 365 + i18n 1490；完整 Playwright gate 为 2945 passed / 10 skipped）
├─ ui/                          # HTML 原型 v1–v6（设计迭代史）
└─ CLAUDE.md                    # 项目 AI 上下文索引
```

## 功能状态

当前已可用的功能：

- **学习**：`ahadiff learn` 支持 8 种 diff 捕获模式（git commit/range/staged/unstaged/patch/patch-url/compare/compare-dir），含 Notebook cell-aware diff 和路径范围限定
- **断言验证**：每条 lesson 结论都绑定 `file:line` 证据链，五种验证状态（verified/weak/not_proven/contradicted/rejected）
- **测验与复习**：`ahadiff quiz` 交互式答题 + `ahadiff review` SRS 间隔复习（FSRS-6 算法）
- **评分**：8 维 rubric 评分（accuracy/evidence/diff_coverage/learnability/quiz_transfer/spec_alignment/conciseness/safety_privacy），支持可选 LLM judge
- **WebUI**：`ahadiff serve` 启动本地 Web 界面，含 Dashboard / Lesson / Diff / Quiz / Review / Concepts / Run Detail / Settings / Guide 等 14 个页面
- **导出**：TSV / JSON / Anki `.apkg` 导出 + 本地静态预览包
- **概念图谱**：自动提取跨 diff 概念关联，支持 Canvas 可视化和健康度 lint
- **AI 工具集成**：13 个安装目标（Claude / Cursor / Copilot / Codex / Gemini 等），一键写入项目级 AI 工具指引
- **自动迭代**：`ahadiff improve` 在隔离 worktree 中自动优化 prompt，质量只升不降
- **MCP Server**：只读 stdio MCP server，7 个工具，可被 Claude / Cursor 等 AI 工具直接消费
- **隐私**：三档隐私（strict_local / redacted_remote / explicit_remote），默认 strict_local
- **i18n**：中英文全链路支持（CLI + WebUI + prompt 输出语言）
- **跨平台**：macOS / Linux / Windows 均可运行，Python 3.11+
- **安全**：URL 密钥脱敏、DNS pinning、输入校验、prompt 注入检测、`safety_findings.json` hard gate

当前已落地的最小验证：

```bash
uv run pytest tests/unit -q
uv run ruff check src tests
uv run pyright
uv build --wheel
uv run ahadiff quiz --help
uv run ahadiff review --help
uv run ahadiff improve --help
uv run ahadiff db check --help
uv run ahadiff install github-action --help
```

真实 LLM judge smoke 需要显式开启。下面是 GPT-5.5 示例；如果省略 `AHADIFF_LIVE_LLM_MODELS`，测试会使用代码里的默认模型顺序：

```bash
AHADIFF_LIVE_LLM_JUDGE=1 \
AHADIFF_LIVE_LLM_API_KEY="$AHADIFF_LIVE_LLM_API_KEY" \
AHADIFF_LIVE_LLM_BASE_URL="$AHADIFF_LIVE_LLM_BASE_URL" \
AHADIFF_LIVE_LLM_MODELS="gpt-5.5" \
pytest tests/live/test_llm_judge_live.py -q
```

下一步路线图：

- [ ] `v0.1`（MVP）：CLI + Lesson + Evaluator + Ratchet 全链路 + React 19 WebUI（`ahadiff serve`）+ 8 种 LLM Provider（OpenAI Chat/Responses/Gemini/Anthropic/Azure/NewAPI/LMStudio/Ollama）+ 8 种 diff 捕获（含 --unstaged / git show）+ 13 个 install target + i18n + 阶段门禁
- [ ] `v0.2`：--compare-dir + --patch-url + 7 个 IDE install target + watchdog 增量重生 + section-level helpfulness + Team 功能（已完成：后端 Gate 0-6 + medium APIs + helpfulness / learning transfer + misconception cards + full lesson `walkthrough_tldr` + Graphify 后端基础与 concept linking / FTS / provenance / perf gate + Graphify signoff artifact + post-learn Graphify update/import + watch mode + path-scoped learn + `learn --open` + spec alignment deterministic artifact / opt-in semantic review + Notebook cell-aware diff + graph refresh API + DB check API + graph edge confidence DTO + Run Detail learnability + learning artifact 404 contract + APKG 下载 + packaged APKG CSS + read-only MCP server / `ask_lesson` + 13 install targets + install target WebUI 安全闭环 + provider/model settings + Learn Mode Dialog 安全/a11y 加固 + `/api/learn` rate limit / git filter injection guard + DNS pinning + LLM judge + `safety_findings.json` / `critical_safety_findings` gate + concept health lint + local static preview export + opt-in Challenge loop + review card lazy import + 当前前端学习面收口：三档 SRS UI、自动 scaffolding、retention 设置、Ratchet TSV/JSON/APKG 导出、Ratchet inline results / Phase 2.5 / benchmark transparency、Export modal、ConceptGraph Graph/List 视图、Canvas renderer、community fill、forced-colors/focus persistence、可访问列表 fallback、Concepts Ledger/HealthBadge、ConceptLedger graph link/focus highlight、Run Detail score grid / Judge advisory / Artifacts 分组 / spec alignment / Graphify signoff artifact browser、Run Detail concepts artifact、Ratchet Improve Preview、Dashboard learning metric 隔离和空态 Learn CTA、Welcome 真实 run diff/lesson 预览和 LearnTaskBanner 反馈、Challenge 页面、Guide 使用指南页、项目级 AI 工具指引页、三档侧栏与真实 provider/config footer、Diff Unified/Split + 分侧 claim 跳转 + sticky ClaimInspector 导航 + 内联 source hunk 预览 + claim 单点聚合/count badge、Dashboard source filter、container query hardening、Settings/Lesson/Guide/Review heading 与 aria 收口、Settings/Concepts/Review 深链消费、SearchOverlay 双栏预览和 Ledger focus links、ErrorBoundary 诊断脱敏与复制 fallback、CSP hash / z-index token / favicon / runtime status / queue-state / signals / idempotency fallback 硬化；待做：Team / stable APKG namespace GUID / 真实 large-repo signoff evidence / 更细的前端视觉 polish）
- [ ] `v1.0`：PWA offline shell signoff + public benchmark suite（已完成：VitePWA build、manifest `id`/`scope`、SVG + 192/512 PNG icons、manifest unit test；待做：offline shell E2E 与公开 benchmark signoff）

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

[MIT](./LICENSE)

---

> 知返 / AhaDiff —— Δ知 ↺
