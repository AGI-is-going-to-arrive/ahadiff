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

Stage 0 / Task 0 到 Stage 6 主线现在都已经有实际产物，Stage 7 的 i18n signoff 也已通过。当前代码已经能稳定产出 Lesson / Claims / Quiz / Misconception Cards / Cards / Score / Ratchet；review 流的 SRS runtime、serve backend、install targets、GitHub Action 模板、benchmark suite、improve loop core、Task 17 targeted verification、Phase 2.5 runtime、i18n-0 后端以及前端 `viewer/` React SPA 都已落地。前端 v0.1 阶段落地 Dashboard / Lesson / Diff / Quiz / ConceptGraph 五页并经 R1-R5 五轮跨模型对抗审查（51 项 real findings 修复）。v0.2 后端 Gate 0-6 + 前端 Phase 1-4 已全部通过审查；当前分支又补上了 section-level helpfulness / learning transfer、misconception cards、Graphify 后端基础与部分深一层能力（parser / matcher / linker / slicer / search / freshness / `/api/graph/status` / `/api/graph/concepts`，仍是 backend-only partial，不是完整 Graphify provenance / UI integration）、watch mode（`ahadiff watch` / `serve --watch` / `/api/watch/status`）、中层 serve API（`/api/search`、`/api/usage`、`/api/audit`、`/api/review/mastery`、`/api/concepts/weak`、`/api/spec/alignment`、`/api/stats/learning`）、低层 task status surface，以及 repo 级 CI/CD gate（PR unit+pinned + Windows runtime guard + nightly-eval + release coverage gate）。本轮后端 closure 又收口了 learn 发布边界、watcher restart/status、concepts DB/JSONL cursor、public search rank，以及 auth token bootstrap 的前端前置合约；serve token bootstrap、thread-backed learn 取消/退出、DTO 空 ID 拒绝、FSRS 非有限数拒绝、proxy trace header 拒绝这些边界也仍然成立。Phase 2 gate follow-up 又补齐了 Settings / ConceptGraph 前端实施前的后端契约：providers、audit、doctor、install targets、usage、search 和 graph concepts 都有稳定 DTO / viewer schema 对齐；SearchOverlay focus trap、Quiz peek guard、1024px drawer 边界、Diff 路径归一化、API 错误脱敏、CSP 和 lazy chunk budget 也已修复。随后 Phase 4D Settings UI 已按 V6 形态落地：8-tab sidebar、mode summary card、privacy toggles、provider grid、last-20 audit table、API 失败 fallback、tabs keyboard/a11y，以及 forced-colors / reduced-motion / print / responsive 覆盖。前端仍是 12 页面，组件面为 19 个 TSX + 19 个 CSS，i18n 为 354/354 key parity；本 session 前端门禁 `typecheck` / `lint` / unit / build / Playwright 全绿，unit 为 18 passed，Playwright 为 1125 passed。当前 `pnpm run build` 预算脚本测得 initial JS gzip 82,733 bytes，Dashboard first-route JS gzip 112,307 bytes。

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
ahadiff learn HEAD~1..HEAD --against .ahadiff/specs/oauth-login/SPEC.md

# 复习
ahadiff quiz abc123
ahadiff review

# 在浏览器中交互（Quiz/SRS/Dashboard）
ahadiff serve

# 棘轮优化（Task 16/17 后端已落地；需要已有 finalized run 和 provider 配置）
ahadiff improve --suite local --rounds 6

# 安装到 AI 工具 / 自动化入口（13 个 target）
ahadiff install claude    # Claude Code → .claude/skills/
ahadiff install codex     # Codex CLI → AGENTS.md
ahadiff install gemini    # Gemini CLI → GEMINI.md
ahadiff install opencode  # OpenCode → AGENTS.md + .opencode/agents/
ahadiff install hooks     # POSIX shell git hooks（Windows v0.1 会明确拒绝）
ahadiff install github-action          # verify-only workflow
ahadiff install github-action --layer2 # opt-in generate workflow（需要 provider secret）
ahadiff install cursor    # Cursor → .cursor/rules/
ahadiff install windsurf  # Windsurf → .windsurf/rules/
ahadiff install copilot   # GitHub Copilot → .github/copilot-instructions.md
ahadiff install continue  # Continue → .continue/rules/
ahadiff install aider     # Aider → .aider.conf.yml
ahadiff install cline     # Cline → .clinerules
ahadiff install roo       # Roo Code → .roo/rules/
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
│  ├─ contract-freeze.md        # Stage 0 架构权威源
│  ├─ ahadiff设计思路.md          # [ARCHIVED] 早期架构快照
│  ├─ 知返ahadiff改名后的后续方案.md  # [ARCHIVED] 改名过渡方案
│  └─ AhaDiff_frontend_design_v1.1_revised.md  # 前端视觉手册（v0.1=React 19+Vite）
├─ src/ahadiff/contracts/       # Stage 0 最小可 import + 可序列化 contracts 面
├─ src/ahadiff/core/            # Stage 1 / Task 1 工程骨架 + task runner / watcher + Phase 0 JSON/SQLite 安全 helper
├─ src/ahadiff/safety/          # Stage 1 / Task 2 安全层基础实现
├─ src/ahadiff/llm/             # Layer 1.5 / Task 7 provider + probe
├─ src/ahadiff/git/             # Stage 2 / Task 5-6 diff capture + 结构化
├─ src/ahadiff/claims/          # Stage 2 / Task 8 claim 提取 + 验证 + runtime
├─ src/ahadiff/lesson/          # Stage 3 / Task 8.5 + 9 learnability + lesson + helpfulness/transfer
├─ src/ahadiff/quiz/            # Stage 3 / Task 10 open-answer quiz + cards + misconception cards
├─ src/ahadiff/wiki/            # Stage 3 / Task 10 concepts ledger
├─ src/ahadiff/graphify/        # 当前分支 Graphify 后端基础：models/parser/matcher/linker/slicer/search/freshness
├─ src/ahadiff/eval/            # Stage 3 / Task 11-12 evaluator + ratchet + results
├─ src/ahadiff/serve/           # Task 14.5 + v0.2 本地 serve API（含 search/audit/usage/mastery/learning/tasks）
├─ src/ahadiff/install/         # Task 19/20 install targets + hooks no-follow + GitHub Action 模板
├─ src/ahadiff/i18n/            # i18n-0 locale resolver / prompt language helper
├─ src/ahadiff/review/          # Task 15 + v0.2 review.sqlite schema / FSRS-6 / migration chain
├─ src/ahadiff/prompts/         # wheel 内打包的 prompt 资源
├─ prompts/                     # Lesson / claim prompt 模板
├─ src/ahadiff/improve/         # Stage 5 / Task 16/17 improve loop、targeted verify、Phase 2.5
├─ benchmarks/                  # Task 18 本地 benchmark fixtures + manifest + scripts + results
├─ tests/unit/                  # Stage 0–6 与 i18n-0 单元测试
├─ tests/eval/                  # benchmark suite 测试
├─ tests/integration/           # pinned integration fixtures
├─ tests/live/                  # 需要显式环境变量开启的真实 LLM judge smoke
├─ viewer/                      # React 19 + Vite + Zustand + vanilla CSS 前端（12 页面 / 19 TSX + 19 CSS / 354 i18n keys / 1125 Playwright）
├─ ui/                          # HTML 原型 v1–v6（设计迭代史）
└─ CLAUDE.md                    # 项目 AI 上下文索引
```

## 当前阶段

**Stage 0 / Task 0、Stage 1 的 Task 1/2、Layer 1.5 的 Task 7、Stage 2 / Task 5/6/8、Stage 3 / Task 8.5/9/10/11/12、Stage 4 / Task 15、Stage 5 / Task 16/17、Stage 6 / Task 18/19/20，以及 i18n-0 后端已落地。** 当前代码除了设计文档和 HTML 原型，还已经有：

- `ahadiff learn` 的主链路：支持 git / `--patch` / `--compare` capture，经过 learnability gate 后生成 `claims.raw.jsonl -> claims.jsonl`、`lesson.full|hint|compact.md`、`misconception.md`、`not_proven.md`
- `ahadiff quiz`：对已生成的 `quiz.jsonl` 做最小交互式答题，并回显 source_claims / file:line evidence
- quiz artifact 链路：会写 `quiz.jsonl` 和 `misconception_cards.jsonl`；评分通过的 run 会生成 `cards.jsonl` 并回填 `review_card_id`，没有 `review_card_id` 的 open-answer 行在 viewer 里也仍然可以正常显示；git 输入写 repo 级 `concepts.jsonl`，non-git 输入写 run 级 `concepts_local.jsonl`
- `ahadiff score` / `ahadiff verify` / `ahadiff export-results`：评分、ratchet 判定和 `results.tsv` 导出都已可用
- `ahadiff review` / `ahadiff mark <claim_id> wrong` / `ahadiff db {backup,restore,check,import-results,finalize-targeted}`：`review.sqlite` 的 review / signals / result_events / lossy import / targeted finalize 链路都已可用
- `ahadiff serve`：localhost-only serve backend 已可用，读接口只暴露 finalized runs，写接口需要 token + Origin/Referer 校验；`/api/auth/token` 现在需要同源浏览器信号，继续兼容 GET，并已支持 POST bootstrap；当前还补上了 `/api/search`、`/api/usage`、`/api/audit`、`/api/review/mastery`、`/api/concepts/weak`、`/api/spec/alignment`、`/api/stats/learning`、`/api/graph/status`、`/api/graph/concepts`、`POST /api/learn`，以及 `/api/watch/status`；当前 route 面是 43 个 concrete `/api` Route 对象 + 1 个 `/api` catchall（`Route(` 总数 45，另含 `/healthz`）；`/api/tasks*` 和 `/api/watch/status` 继续作为 low-level、internal/unstable 的状态 / 进度接口，不属于稳定公开 API
- `ahadiff install`：Claude / Codex / Gemini / OpenCode / hooks / GitHub Action target 已可用；hooks 是 POSIX shell target，Windows v0.1 会明确拒绝；对已有 hook 文件会做 no-follow regular-file 校验，拒绝 symlink / reparse point；生成的 GitHub workflow 覆盖 macOS + Linux，Windows 暂缓；generate workflow 使用 `AHADIFF_PROVIDER_API_KEY`，并上传 `.ahadiff/` 产物 artifact
- `ahadiff benchmark`：本地 benchmark manifest、20 个 eval fixtures、10 个 pinned integration fixtures 与 `ground_truth.md` 一致性校验已可用
- 仓库当前还补上了 repo 级 Backend CI / `nightly-eval` / `release` workflows：PR 跑 unit + pinned integration（`ubuntu py311/py312 + macOS py312`），并有独立 Windows runtime guard；release gate 现在还会阻塞 `doctor`、wheel install smoke 和 coverage `>= 85%`。同时 `pyproject.toml` 已带 `watchdog` / `tree-sitter` optional extras 与 `pytest-cov` dev dependency；`ahadiff watch`、`serve --watch` 和 `/api/watch/status` 已落地，其中 `/api/watch/status` 仍标记为 internal/unstable。`tree-sitter` 也不再只是 optional wiring：runtime consumer 已接到 symbol extraction 层，当前支持 JS/TS/TSX + Go + Java + Rust + PHP + Ruby + C#；Python 仍优先走 AST，其他未接入语言仍回退到 regex / section header，下游 lesson / quiz / claims 逻辑未改
- Phase 0 相关收口已经补到当前分支：contracts 权威口径、`safe_sqlite_connect` SQLite 连接 helper、reparse/hardlink 防护、serve CORS 与 `X-Frame-Options` 安全头、CLI 冷启动和本地 baseline 脚本都有对应实现
- i18n-0：locale resolver 支持 cookie / Accept-Language / CLI / config / `AHADIFF_LANG` / `LANG` fallback，lesson/quiz prompt payload 会带输出语言指令
- `ahadiff improve --suite local --rounds N`：目前仅支持 `--suite local`。它从已有 finalized run 中选择 baseline，在 git worktree 里只改白名单 prompt，重放同一 diff 并重新评分；候选必须让目标维度 + `accuracy` + `evidence` + `safety_privacy` 的合计分高于 baseline，且 hard gates 通过，才会尝试 cherry-pick prompt commit 回主分支，并记录 `event_type=improve` / `status=targeted_verify`；未提升则记录 `discard`，cherry-pick 冲突则保留 pending worktree 且不 finalized；同一 session 连续两次 `discard` 会触发一次 Phase 2.5 worktree rewrite
- `src/ahadiff/eval/{rubric,gates,deterministic,evaluator,results,ratchet}.py`：8 维评分、hard gates、结果写入、ratchet 选择和导出视图
- `src/ahadiff/review/{database,scheduler,schemas,signal}.py`：review.sqlite schema / migration、FSRS-6 调度、review queue、learning signal 和 review CLI 后端
- `src/ahadiff/improve/{loop,program,targeted,rewrite}.py`：improve session、immutable improve_program、worktree 隔离、5 个 mutable prompt 白名单、replay-learn、targeted verification、Phase 2.5 触发、cherry-pick 顺序、session 校验与 pending worktree resume guard
- source checkout 与 wheel 安装态的 runtime 资源定位：`eval_bundle_version`、`prompt_version`、lesson prompt 加载都已经接到包内资源
- `keep_final` 仍通过全 8 维 recheck 后的 `ahadiff db finalize-targeted <event_id>` 手动收口，不在 improve loop 内自动升级。前端 `viewer/` React SPA Phase A-E 已完成并经 R1-R5 五轮跨模型深度审查；v0.2 前端 Phase 1-4 新增 6 个页面（Review / Ratchet / Landing / Settings / Onboarding / Skills）、66 个 v6 design tokens、Skeleton 加载组件、review-store、per-route ErrorBoundary、共享 utility 提取。本轮 i18n 升至 354/354 parity、Playwright 升至 1125 tests，并补上 1024px drawer 边界、SearchOverlay dynamic focus trap / inert、Quiz peek guard、Diff path normalization、API error redaction、route-closure JS budget，以及 Phase 4D Settings 的 8-tab sidebar / provider grid / audit log / privacy toggles；Quiz 页会同时读取 `misconception_cards.jsonl`，并兼容没有 `review_card_id` 的 open-answer 行，不会把这类旧题误接到 SRS 评分

本轮又收口了几件容易出错的运行时边界：`prompt_version` 只描述 AhaDiff 自己的 prompt 资源，不再受目标工作区 `prompts/` 影响；lesson JSON 解析会跳过不匹配 schema 的示例块；lesson/quiz 目录改成生成后再接到主链，失败时会回滚；如果 lesson 生成阶段失败，会清掉新写出的 `claims.raw.jsonl` / `claims.jsonl`、`quiz/` 和 `concepts_local.jsonl` 半成品；`learn` 成功后会写入 `event_type=learn` 的评分事件和 `score.json`，manual `score` / `verify` 不再污染 learn 的 ratchet baseline；`ReviewCard` 现在会校验 `last_rating` 范围和 `card_state/stale_reason` 组合；伪造 quiz 也不会再误拿 `PASS`。后续又把 pinned integration 里的 `cards.jsonl` fixture 收回真实生成路径：测试先写 `symbols.json`，再用 `generate_cards_for_run()` 生成 cards，并逐行校验 `ReviewCard` schema，避免手写半截 cards 绕过生产契约。Task 15 这轮也已经补齐：旧版 `cards` schema 会显式迁移 `stale_reason`，schema-invalid `cards.jsonl` 会降级成 warning，重复 regenerate 不会把旧 active 卡留在 due queue 里；`regenerate --only quiz` 在 `evaluate_run` 失败时会恢复旧 quiz/cards，在 `FAIL` 时会删掉陈旧 `cards.jsonl` 并把该 run 的 active 卡标成 `stale + staleness_unknown`；lossy TSV import 现在走单连接整批导入，坏行或 duplicate identity 会整批回滚；`rollback_result_event` 也改成同一连接里完成 delete + export rows，普通 DB connect 不会再因为路径 typo 静默建目录。Task 16/17 这轮补上了 `lesson_hint.md` 白名单、session_id 路径校验、30 分钟 replay timeout、双 prompt temp+replace 写入、非冲突 cherry-pick 失败区分、discard/pending conflict 不写 `finalized.json`、pending conflict 不作为下一轮 baseline、volatile staged/unstaged 输入从保存的 `patch.diff` 重放、短 worktree 路径、`--rounds` 上限 20、null byte 拒绝、Ctrl+C 在已完成 round 后不再追加第二条 crash event、targeted verification、Phase 2.5 单次触发，以及 OpenAI-compatible provider endpoint 归一化。这次又把 LLM cache key 的版本边界补齐：同一 `api_family` 下不同 `api_family_version` 会生成不同 cache key，避免兼容网关或 API 版本变化时误复用旧结果。

当前已落地的最小验证：

```bash
source .venv/bin/activate && pytest tests/unit -q
source .venv/bin/activate && ruff check src tests
source .venv/bin/activate && pyright
source .venv/bin/activate && uv build --wheel
source .venv/bin/activate && python -m ahadiff quiz --help
source .venv/bin/activate && python -m ahadiff review --help
source .venv/bin/activate && python -m ahadiff improve --help
source .venv/bin/activate && python -m ahadiff db check --help
source .venv/bin/activate && python -m ahadiff install github-action --help
```

真实 LLM judge smoke 需要显式开启，默认模型顺序是 `gpt-5.3-codex-spark,gpt-5.4-mini`，每个模型都会先试 OpenAI Responses，再试 Chat Completions：

```bash
AHADIFF_LIVE_LLM_JUDGE=1 \
AHADIFF_LIVE_LLM_API_KEY="$AHADIFF_LIVE_LLM_API_KEY" \
AHADIFF_LIVE_LLM_BASE_URL="$AHADIFF_LIVE_LLM_BASE_URL" \
AHADIFF_LIVE_LLM_MODELS="gpt-5.3-codex-spark,gpt-5.4-mini" \
pytest tests/live/test_llm_judge_live.py -q
```

最近一次验证（2026-05-01，本 session）：`UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run --frozen --no-sync pytest tests -q -p no:cacheprovider --tb=short` = `1526 passed, 1 skipped in 73.10s`；`UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run --frozen --no-sync ruff check src tests` 通过；`UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run --frozen --no-sync ruff format --check src tests` = `224 files already formatted`；`UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run --frozen --no-sync pyright` = `0 errors, 0 warnings, 0 informations`。前端 `pnpm run typecheck && pnpm run lint && pnpm run test:unit && pnpm run build && pnpm exec playwright test --reporter=line` 通过，其中 unit 为 `18 passed`，Playwright 为 `1125 passed`；`pnpm run build` 同时验证 initial JS gzip 82,733 bytes、Dashboard first-route JS gzip 112,307 bytes。本轮没有重跑 coverage gate / wheel build / `uv lock --check` / live judge；此前 coverage/wheel/lock/live judge 结果不能冒充本轮新验证。

下一步路线图：

- [ ] `v0.1`（MVP）：CLI + Lesson + Evaluator + Ratchet 全链路 + React 19 WebUI（`ahadiff serve`）+ 8 种 LLM Provider + 8 种 diff 捕获（含 --unstaged / git show）+ 6 个 install target + i18n + 阶段门禁
- [ ] `v0.2`：--compare-dir + --patch-url + 7 个 IDE install target + watchdog 增量重生 + section-level helpfulness + Team 功能（已完成：后端 Gate 0-6 + medium APIs + helpfulness / learning transfer + misconception cards + Graphify 后端基础与部分深一层能力 + watch mode + 前端 Phase 1-4 + Phase 4D Settings UI + 13 install targets + LLM cache + usage.sqlite + Phase 2 gate follow-up；待做：Team / 完整 5D ConceptGraph UI / 更深的 Graphify linking 与其余前端 V6 对齐）
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
