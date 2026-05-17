# 知返 AhaDiff

> AI 写完，Diff 教回。 / Ship with AI. Learn it back.

## 项目愿景

知返 AhaDiff 是一个 **local-first 的 verified diff learning layer**。把 AI 写出的 git diff 变成带代码证据链的学习笔记、概念图谱、主动回忆测验、SRS 复习卡和质量棘轮记录。核心差异：Code Wiki 解释仓库，知返解释这次改动；每句话都能回到代码证据。

**当前状态（2026-05-17）**：v1.1 security / cross-platform follow-up 之后，Phase 2 follow-up 已补上本地学习闭环的几块产品面。后端仍是 `1.1.0a0`，前端仍是 `1.1.0-alpha.0`；`review.sqlite` schema 已升到 v10，新增 deterministic concept health lint 和 `concept_status` / `concept_lint_runs`；新增 `ahadiff export preview` 与 `POST /api/export/preview`，只生成本地 strict-local 静态预览和 deterministic zip manifest；read-only MCP server 现在是 7 个工具，新增 `ask_lesson`，只做本地 lesson fragment token search；Challenge loop 默认关闭，需要配置 opt-in，CLI 只有 `build` / `status`，serve/WebUI 提供 build/get/advance/abort/review/feedback，review 是 deterministic diff gap 对比，不执行代码；APKG 已改用 packaged CSS，但 GUID 仍是 `genanki.guid_for(card_id)`，stable namespace GUID 未落地。2026-05-14 spec alignment / Notebook follow-up 已补上 `learn --open`、spec alignment artifact、opt-in semantic review、Notebook cell-aware diff 和 Graphify signoff artifact。本次 review/test follow-up 又收口 review card lazy import、post-learn Graphify update/import、50 MiB graph source import、`/api/graph/refresh` 精确 600s timeout、`git --since` 纯日期归一、Concepts wrapper、Sidebar 真实 config footer 和 Graphify freshness 文案；后续 review 修复又补上低 learnability 跳过 lesson/quiz 时的最小 run 发布（result event + `score.json` + `finalized.json`，发布失败回滚 result event）、`quiz.quiz_question_count`（默认 3，范围 1-10，CLI/prompt/serve config/Settings 已接通）、Review open-answer 未 peek、Diff 文件导航和 `+`/`-` 行标记、Lesson 404/skipped 语义修正。之后补了 Learn Mode 安全/a11y、git filter 注入防护、Diff claim 聚合、Run Detail / Judge / safety findings 展示口径。2026-05-17 viewer follow-up 又把 Diff 选中 claim 的 source hunk 预览移回右侧卡片内，并让 Welcome 在 learn 完成后展示真实 run artifact，而不是把样例 lesson 混进真实 run。最新 completion audit 验证为后端 unit `2530 passed`、integration+eval `20 passed`、ruff/format/pyright/wheel、viewer typecheck、lint、Vitest `365 passed`、viewer build、完整 Playwright `2945 passed, 10 skipped`、real-serve `2 passed`、live judge `2 passed`、临时 repo GPT-5.5 provider test / live learn、Linux SQLite `3.51.3` 目标 gate 和 diffcheck；推送后远端 Backend CI / Frontend CI / Pages runs 已触发，但 jobs 立即 failure，steps 为空且日志不存在，不计为代码验证通过；Windows 仍缺真实 runner 结果。

同日后续 frontend polish 只改 `viewer/`：Diff claim 选中态从 accent ring 改成柔和蓝灰行级色带，Unified / Split 的 add/del 选中底色、claim dot hover/focus、dot legend 和 selected-lines hint 已同步；Welcome lesson demo 改为按 H2 折叠，保留 H2 前导内容，无 H2 时回到普通 prose，并在有 latest finalized run 时链接到对应 Lesson。新增 `renderMarkdownCollapsible` 单测覆盖 H2 分组、preamble、无 H2 fallback 和 H3 留在当前 section。真实验证：viewer typecheck、Vitest `35 files, 353 tests passed`、viewer build、后端 unit `2502 passed`、i18n `1449/1449` 和 `git diff --check HEAD` 通过；integration/eval/ruff/format/pyright/wheel/完整 Playwright/live judge/GitHub Actions 未在这次 frontend polish 中重跑。

随后 Learn Mode / Diff aggregation hardening 同步了当前未提交代码的安全/a11y 真值：capture 与 serve submit/estimate 都会拒绝 `since` / `author` 的 leading dash 和控制字符；`against_spec` 只接受当前 workspace 内本地文件；Learn Mode Dialog 拒绝路径遍历、绝对路径、Windows drive/UNC、控制字符和超过 500 条 path scope，`patch_url` 只允许无内嵌凭证的 http/https，revision 拒绝过长、leading dash 和控制字符；关闭 dialog 会 abort estimate / pending learn，store 里的 pending payload 会去掉 patch body / patch URL；Diff Viewer 将同一行多个 claim 聚合为一个最高严重度圆点和数量角标。真实验证：目标后端 `199 passed`、后端 unit `2513 passed`、integration+eval `20 passed`、ruff/format/pyright/wheel、viewer typecheck、Vitest `35 files, 360 tests passed`、viewer build、i18n `1454/1454` 和 `git diff --check HEAD` 通过；完整 Playwright、live judge 和远端 GitHub Actions 未在本轮重跑。

2026-05-16 Run Detail / Judge / safety findings follow-up 只改当前未提交改动涉及的评估、安全和展示面：capture 会在 redaction / injection findings 存在时写 `safety_findings.json`，只保存 severity、rule、位置和 hash；evaluator 读取 `safety_findings.json` / `.jsonl`，坏 artifact 会按 Critical safety finding 失败关闭，并进入 `critical_safety_findings` hard gate；LLM judge 对 `max_score: 0` 的维度按 N/A 处理，最终 PASS/FAIL 仍由 deterministic score + required gates 一起决定。前端 Run Detail 增加 overview 摘要卡、Score 维度卡片和 failed gates 优先、Judge 维度本地化和分数、Artifacts 四类分组；Lesson score explainer 会说明高分但 hard gate 失败、LLM judge advisory 和 Score/Judge 入口；Run Detail 不进入 sidebar，因为它依赖具体 `run_id`。真实验证：后端安全/评估目标测试 `1 passed, 145 deselected` 和 `53 passed`，目标 ruff/format/pyright 通过；viewer typecheck、完整 Vitest `35 files, 362 tests passed`、viewer build、Run Detail + walkthrough Chromium E2E `57 passed`、i18n parity `1 passed` 且 scalar keys `1485/1485`、`git diff --check HEAD` 通过；后端完整 unit、integration、eval、wheel、完整 Playwright、live judge 和远端 GitHub Actions 未在本轮重跑。

2026-05-17 viewer follow-up 只改 `viewer/` 的 Diff / ClaimInspector 和 Welcome 学习入口：Diff 选中 claim 的 source hunk 预览现在直接显示在右侧选中卡片内，并保留 jump-to-code 按钮，页面底部的 `.diff-page__selected-hunk` 面板已移除；Welcome CTA 提交 learn 后显示 LearnTaskBanner，完成后优先展示刚完成 run 的真实 diff 和第一个可用 lesson（full → hint → compact），lesson 缺失或读取失败时显示 run 级空态并链接 Run Detail，不再混入 sample lesson。真实验证：viewer typecheck 通过；Vitest `35 files, 362 tests passed`；viewer build 通过；Diff walkthrough Chromium E2E `1 passed`；Welcome learn-task Chromium E2E `4 passed`；i18n `1490/1490`。一次并行 Playwright 尝试因两个 Vite webServer 抢 `5173` 失败，随后 Welcome 组用 `AHADIFF_VIEWER_E2E_PORT=5174` 重跑通过；端口冲突不计为产品失败。后端、integration、eval、ruff/format/pyright、wheel、完整 Playwright、live judge 和远端 GitHub Actions 未在本轮重跑。

同日 completion audit / 文档收口覆盖当前所有未提交改动：后端补 Linux SQLite nofollow fd 绑定和主库路径校验，compare / Graphify / JSONL artifact 读取拒绝 hardlink，provider URL 判定收紧为 `not addr.is_global`，serve `changed_paths` 拒绝空值、绝对路径、Windows drive / UNC、`.` / `..`、`.git` / `.ahadiff` 和控制字符；前端补 token bootstrap 与同源 absolute URL、provider models / learn estimate Zod schema、real-serve Playwright env、Guide GPT-5.5 provider 命令，以及 API schema / tasks 回归测试。新增 `docs/USER_GUIDE.zh.html` 和 `docs/VALIDATION_AUDIT.zh.md`。真实验证：后端 unit `2530 passed`、integration+eval `20 passed`、ruff/format/pyright/wheel、viewer typecheck、lint、Vitest `36 files, 365 tests passed`、viewer build、完整 Playwright `2945 passed, 10 skipped`、real-serve `2 passed`、live judge `2 passed`、临时 repo GPT-5.5 provider test / live learn、Linux SQLite `3.51.3` 目标 gate 和 `git diff --check HEAD` 通过；推送后远端 Backend CI / Frontend CI / Pages runs 已触发，但 jobs 立即 failure，steps 为空且日志不存在，不计为代码验证通过；Windows 仍缺真实 runner 结果。

## 架构总览

后端 CLI（learn/improve/verify/serve/install/benchmark/mcp-server）：8-provider LLM + diff capture + `safety_findings.json` + claims + lesson/quiz/concepts + concept health lint + 8 维 eval + 可选 LLM judge + `critical_safety_findings` hard gate + review.sqlite v10/FSRS-6 + serve API（72 concrete `/api/*` routes + catchall，28 个稳定 `ErrorCode`）+ `RunDetail.learnability` + skipped-run 最小发布 + APKG export + local static preview export + opt-in Challenge loop + read-only MCP server / `ask_lesson` + 13 install targets + improve loop。前端 React 19 SPA：14 个生产 page TSX、52 个非测试 TSX、47 个 CSS 文件，当前 i18n scalar key parity 为 `1490/1490`；ConceptGraph 当前是 Canvas renderer + 可访问列表 fallback + forced-colors/focus hardening；Settings 的项目级 AI 工具指引仍沿用 `?tab=integrations` 深链，Preferences 已包含 quiz 数量配置；Learn Mode Dialog 已补 path scope / patch URL / revision 校验、abort 和 print/a11y 收口；Run Detail 有 Overview 摘要卡、Score 维度卡片、Judge advisory 和 Artifacts 分组；Diff claim 使用聚合圆点、count badge、sticky ClaimInspector、柔和行级色带、圆点说明和卡片内 source hunk 预览；Welcome lesson demo 支持 H2 折叠、最新 Lesson 链接、learn 任务反馈和真实 run artifact 预览。

### 技术栈

- **后端**：Python 3.11+, typer, rich, pydantic, httpx, pyyaml, fsrs (FSRS-6)
- **前端**：React 19 + Vite + vanilla CSS + Zustand + HashRouter。`ahadiff serve` 启动 Starlette + Uvicorn
- **评估**：LLM-as-judge + 8 维 rubric（accuracy/evidence/diff_coverage/learnability/quiz_transfer/spec_alignment/conciseness/safety_privacy = 100 分）+ git ratchet
- **LLM Provider**：8 种格式（OpenAI Chat/Responses / Gemini / Anthropic / Azure / New API / LM Studio / Ollama）。BYOK + `thinking_level`（none/low/medium/high）按 provider 映射原生参数。`generate_provider`/`judge_provider` 分别指定
- **不使用**：LiteLLM、LangChain、Jinja2 渲染前端、Next.js

### 八层架构

```
0. Schema & Contract     -- 核心契约冻结（ClaimStatus/RunSource/EvalBundle/EventLog）
1. Diff Capture Layer    -- git diff / patch / --compare / --compare-dir / --patch-url
2. Context Layer         -- 2a Assembly / 2b Safety Gate (redact) / 2c Budget & Degrade
3. Lesson Generation     -- prompts/*.md, claim extraction
4. Verification Layer    -- claims.jsonl, deterministic + LLM judge
5. Ratchet Layer         -- evaluation bundle (immutable), review.sqlite, Graphify freshness
6. Learning Layer        -- quiz, SRS review, section helpfulness, concepts.jsonl
7. Wiki + UI Layer       -- React SPA via `ahadiff serve`
```

编排 contract 冻结在 `src/ahadiff/contracts/orchestrator.py`；运行时 learn 主链在 `src/ahadiff/core/orchestrator.py`。

### 数据范围架构

> 核心原则：**per-repo truth + global derived governance**

```
global_config_dir()                   ← Global（派生/索引/偏好，非真相源）
<repo>/.ahadiff/                      ← Per-repo（唯一真相源）
├── config.toml / review.sqlite / concepts.jsonl / ahadiff.lock
├── runs/<run_id>/  graphify/  audit.jsonl  audit.private.jsonl
```

**Config 优先级**：`ENV(AHADIFF_*) → CLI flag → per-repo config.toml → global config.toml → defaults`

## 模块索引

| 模块 | 路径 | 核心职责 |
|------|------|----------|
| contracts | `src/ahadiff/contracts/` | 枚举、DTO、契约 helper、错误类型、QuizChoice/AnswerMode、`LearnabilityInfo`、28 个稳定 `ErrorCode` + `ERROR_STATUS` |
| core | `src/ahadiff/core/` | CLI 配置、路径、ID、json_util/sqlite_util 安全 helper、task_runner（1800s timeout + 终态单调）、orchestrator（error budget 8 + per-step output caps + changed_paths）、watcher |
| safety | `src/ahadiff/safety/` | ignore / redaction（URL-embedded secret）/ injection / gates / audit |
| llm | `src/ahadiff/llm/` | provider（streaming byte cap + DNS IP pinning + DecodingError 重试）、probe、cache、cost、adapters（thinking.py）、usage |
| git | `src/ahadiff/git/` | diff capture、parser、line map、symbols、hunk hash、`git` 可执行文件检测、repo write lock、`since` / `author` leading dash 与控制字符拒绝、`safety_findings.json` 安全发现 artifact |
| claims | `src/ahadiff/claims/` | claim 解析（容错 + 截断 JSON 恢复）、runtime、negative scan、deterministic verifier、`output_lang` 透传 |
| lesson | `src/ahadiff/lesson/` | learnability gate、三档 lesson（full/hint/compact）、full lesson `walkthrough_tldr`、section helpfulness |
| quiz | `src/ahadiff/quiz/` | quiz/cards/misconception_cards（ABCD 选项 + 容错解析）、review_card_id 回填；`quiz_question_count` 默认 3、范围 1-10，并进入 prompt fingerprint |
| wiki | `src/ahadiff/wiki/` | concepts.jsonl 累积、streaming reader、ancestry cache、DB/JSONL cursor 分页、deterministic health lint |
| challenge | `src/ahadiff/challenge/` | opt-in challenge state machine、manifest、deterministic diff gap review、adapt signal |
| export | `src/ahadiff/export/` | local static preview writer、manifest digest、deterministic zip |
| graphify | `src/ahadiff/graphify/` | parser（50 MiB + 50k edge cap + provenance）/ matcher / linker / freshness（7 态 + 4 值投影）/ optional CLI update bridge |
| eval | `src/ahadiff/eval/` | 8 维评分、hard gates（含 `critical_safety_findings`）、ratchet、可选 LLM judge；`max_score=0` 维度按 N/A 处理 |
| review | `src/ahadiff/review/` | review.sqlite v10 + FTS5 + FSRS-6 + search + optimizer + ABCD 卡片 + concept health tables + run-card lazy import + APKG active-card export / packaged CSS |
| serve | `src/ahadiff/serve/` | 72 concrete `/api/*` routes；auth/CORS/CSP；learn/tasks/graph/config/search/usage/audit/review/install/providers/export/challenge 端点；`RunDetail.learnability` 投影；低 learnability skip run 最小发布；lesson/claims/quiz artifact 缺失返回 404；review/signals 缺 active card 时 lazy import 后重试；`POST /api/learn` / estimate 支持 `changed_paths` / `against_spec` / `spec_semantic_review`，并校验 workspace path、changed_paths repo-relative path scope 和 git filter 注入边界；`POST /api/learn` 额外预检 repo 写锁；`GET/PUT /api/config` 含 `quiz_question_count`；`/api/export/results?format=tsv\|json`；`/api/export/apkg`；`/api/export/preview`；challenge feature flag；audit 最新优先分页；统一 `{error_code,error,status,details?}`；per-request locale；SSE progress；写保护；`/api/graph/refresh` 精确 600s timeout |
| install | `src/ahadiff/install/` | 13 安装目标、项目级 AI 工具指引写入、通用写入层（no-follow/reparse/symlink guard）、hooks git 检测/timeout、verify workflow macOS/Linux/Windows matrix |
| improve | `src/ahadiff/improve/` | improve session、worktree replay、prompt 白名单、Phase 2.5、preflight |
| i18n | `src/ahadiff/i18n/` | locale resolver（cookie → Accept-Language → `AHADIFF_LANG` → CLI → config → `LANG`）和 prompt language helper |
| mcp | `src/ahadiff/mcp/` | read-only stdio MCP server，7 个工具：`list_runs` / `get_run_summary` / `list_due_cards` / `search` / `get_concepts` / `get_stats` / `ask_lesson` |
| benchmarks | `benchmarks/` | 10 fixtures、Graphify 10k gate（parse 750ms + peak 96MiB） |
| viewer | `viewer/` | React 19 SPA；14 个生产 page TSX；SearchOverlay 双栏预览 + graph-node Ledger focus；ErrorBoundary 诊断脱敏和复制 fallback；Learn Mode Dialog 默认跟随 viewer locale，含 path scope / patch URL / revision 校验、AbortController 取消、redacted pending payload、`aria-busy` / live region、print hide；Review 四档 SRS + 高风险概念，open-answer reveal 不再记为 peek；Quiz 导航 / mark-wrong / progress table；Challenge Mode；Export modal；HealthBadge；ConceptLedger graph link/focus highlight；ConceptGraph Canvas renderer + botanical palette + community fill + forced-colors + focus persistence + a11y list fallback；Ratchet TSV/JSON/APKG 导出；Settings 项目级 AI 工具指引 + quiz 数量配置；Dashboard + Lesson + Concepts + Ratchet + RunDetail + Settings + Guide + Diff + Search；RunDetail Overview 摘要卡、Score 维度卡片、Judge 语义评审说明、Artifacts 分组；Lesson score explainer 链接 Score/Judge；Diff 文件 Prev/Next、claim auto-scroll、`+`/`-` 行标记、claim 单点聚合/count badge、sticky ClaimInspector、柔和 claim 选中色带、卡片内 source hunk 预览、dot legend 和 selected hint；Welcome lesson H2 折叠、demo 高度上限、最新 Lesson 链接、LearnTaskBanner 反馈和真实 run artifact 预览；Onboarding DiagnosticRow；错误码本地化；locale-aware byte/token 格式化；motion/elevation CSS；侧栏三档 + 真实 config footer；Concepts content wrapper；container query；PWA |
| tests | `tests/` | unit/integration/eval/live；最新 completion audit 验证为后端 unit `2530 passed`、integration+eval `20 passed`、ruff/format/pyright/wheel、viewer typecheck、lint、Vitest `365 passed`、viewer build、完整 Playwright `2945 passed, 10 skipped`、real-serve `2 passed`、live judge `2 passed`、临时 repo GPT-5.5 provider test / live learn、Linux SQLite `3.51.3` 目标 gate 和 diffcheck；推送后远端 Backend CI / Frontend CI / Pages jobs 立即 failure 且无 steps/logs，不计为代码验证通过；Windows 仍缺真实 runner 结果；CI: PR unit + eval + nightly eval + release coverage ≥85% |
| doc | `doc/` | 产品设计文档 |
| ui | `ui/` | UI 原型 Warm v1-v6 |

## 运行与开发

### 验证命令

```bash
uv run pytest tests/unit
uv run ruff check src tests
uv run ruff format --check src tests
uv run pyright
uv build --wheel
uv run python -m ahadiff --version
uv run ahadiff init / doctor / config show --resolved

cd viewer
pnpm vitest run
pnpm typecheck
pnpm build
```

LLM judge smoke（opt-in）：

```bash
AHADIFF_LIVE_LLM_JUDGE=1 \
AHADIFF_LIVE_LLM_API_KEY="$AHADIFF_LIVE_LLM_API_KEY" \
AHADIFF_LIVE_LLM_BASE_URL="$AHADIFF_LIVE_LLM_BASE_URL" \
AHADIFF_LIVE_LLM_MODELS="gpt-5.3-codex-spark,gpt-5.4-mini" \
pytest tests/live/test_llm_judge_live.py -q
```

### 依赖

`pyproject.toml` + `uv.lock`（后端）；`viewer/package.json` + pnpm（前端）。

## 测试策略

- VCR 双层版本：run 级 `prompt_version` + cassette 级五元组 hash
- CI 分档：PR unit+pinned（ubuntu py311/py312 + macOS py312）+ Windows guard；nightly eval；release 全量 + coverage ≥85%
- Benchmark：Python 主套件（7）+ Non-Python 降级（3），独立 recall/precision

## 编码规范

- 中文为主，技术术语保留英文。品牌「知返 AhaDiff」，CLI `ahadiff`
- Python：ruff + pyright strict + pre-commit；线宽 100，ruff 规则 `F,E,W,I,UP,B,C4,SIM,RET,PTH,TC,FA`
- 所有 LLM 调用走 `llm/provider.py`，禁止直接 import anthropic/openai
- prompt 写独立 `.md`，禁止 f-string 拼长 prompt

## AI 使用指引

### 硬性要求
- **所有文档更新必须基于真实代码 + 真实测试结果**。文档间漂移以代码为准。**严禁虚构。**
- 中英文对照文档修改时必须同步更新。
- committed docs 不得写入真实 API key、本地 endpoint 或带用户名的绝对路径。

### 关键设计决策
1. **N-文件契约**：`program.md` + evaluation bundle（immutable，变更触发版本 + VCR 失效）+ prompt 集合。**可写 prompt 白名单**：`lesson_generate.md`、`lesson_hint.md`、`lesson_compact.md`、`quiz_generate.md`、`claim_extract.md`；`eval_judge.md` 是 packaged resource；`improve_program.md` 是 immutable state machine
2. **Claim Verifier 核心护城河**：每句绑定 file:line 证据，五种状态（verified/weak/not_proven/contradicted/rejected）
3. **棘轮机制**：improve/Phase 2.5 在 git worktree 执行，不碰主分支。连续 2 个目标无增益触发 Phase 2.5（最多 1 次/session）
4. **跨模型评估**：生产要求生成≠评估模型。开发阶段统一 gpt-5.4-mini
5. **SQLite 唯一真相源**：`review.sqlite` result_events 表。TSV 为导出视图。前端只是 viewer
6. **安全脱敏顺序**：raw → secret scan → redact → log/cache/model/render
7. **隐私三档**：`strict_local`（默认）/ `redacted_remote` / `explicit_remote`
8. **i18n 全链路**：cookie → Accept-Language → AHADIFF_LANG → --lang → config.toml → LANG → en。支持 en/zh-CN
9. **UNTRUSTED_DIFF 扩展边界**：diff/文件名/commit msg/branch/Graphify label/模型输出/VCR cassette 均经 `redaction_pipeline()`
10. **SQLite 运行时门禁**：WAL + busy_timeout + trusted_schema=OFF + quick_check
11. **架构权威源**：`contract-freeze.md`
12. **Graphify v0.1 可选增强**：存在则导入 + sanitization，不存在则降级

### 灵感项目
- **autoresearch**（Karpathy）→ N-文件契约 + git ratchet
- **SKILL0**（ZJU-REAL）→ section helpfulness
- **darwin-skill** → 8 维 rubric + Phase 2.5
- **Graphify** → 7 态新鲜度 + 4 值投影
- **LLM Wiki**（Karpathy）→ persistent wiki 思路；当前 `concepts.jsonl` 是 snapshot-style 累积，append-only marker/event-log 仍是 RFC 设计项

## 多模型协作策略

| 模型 | 角色 | 职责 |
|------|------|------|
| **Claude** | 编排 + 前端 | 任务编排、前端实现、文档、集成 |
| **Codex** | 后端 | Python CLI、测试、包发布；通过 `codex-plugin-cc` 调用 |
| **Gemini** | 前端评审 | UI/UX 评审（不写代码）；通过 `codeagent-wrapper` 调用 `gemini-3.1-pro-preview` |

调用规则：
- Codex：实现/修复/调查用 `/codex:rescue`，常规 review 用 `/codex:review --background`，对抗式 review 用 `/codex:adversarial-review --background`，状态/结果用 `/codex:status` / `/codex:result`；使用 plugin 默认模型，不加 `--model` / `--effort`，不要通过 `Skill(codex:review)` 调用。
- Gemini：`$HOME/.claude/bin/codeagent-wrapper --backend gemini --gemini-model gemini-3.1-pro-preview`；429 时 Claude 兜底并记录 `gemini-429-fallback=claude`。

### 文件所有权

| 范围 | 写入 | 审查 |
|-----|------|------|
| `src/ahadiff/**/*.py` / `tests/**` | Codex | Claude + Codex |
| `viewer/src/**/*.tsx` / `*.css` | Claude | Claude + Gemini |
| `prompts/*.md` / `doc/**` / `CLAUDE.md` | Claude | — |

### 阶段门禁

- **GO**：0 Critical + 0 High
- **CONDITIONAL GO**：0 Critical + ≤3 High
- **NO GO**：≥1 Critical 或 >3 High

审查清单：功能正确性、覆盖率、文档同步、pyright/ruff、安全扫描、跨平台、集成点。每个大 Stage/Phase 结束后先做最小相关测试，再触发 Codex 对抗式审查和常规 review；前端 UI/UX 相关改动还需要 Gemini/Claude 视觉与浏览器实测。

## 变更记录 (Changelog)

> 详细实现笔记见 `git log`。设计阶段（04-19~21）10 轮三模型审查完成架构冻结。

| 日期 | 里程碑 | Tests |
|------|--------|-------|
| 04-22~24 | Stage 0-5: contracts → capture → provider → claims → lesson → eval → improve | 61→406 |
| 04-24~25 | Stage 6-7 + Viewer A-E + R1-R5 审查 | 478→559 |
| 04-26~28 | v0.2 Gate 0-6 + Frontend Phase 1-4 + FTS5 | 576→993 |
| 04-29~30 | v1.0 Phase 收口 + 对抗式审查 + auth/FSRS/watcher | 1191→1526 |
| 05-01~02 | Settings + concept linking + FTS graph + tasks API + 安全加固 + gate（coverage 87.33%） | 1526→1754 |
| 05-03~04 | Onboard-UX + Review q/a + 跨浏览器 E2E + token normalize + Provider CRUD + Probe | 1755→1835 |
| 05-05 | thinking_level 全栈 + model discovery + generate/judge provider + pipeline 鲁棒性 | 1834→1840 |
| 05-06 | Learn preflight + pipeline 容错 + Quiz ABCD 全栈 + Lesson V6 | 1848→1913 |
| 05-07 | Timeout 修复 + output caps + 截断 JSON 恢复 + LLM judge + gpt-5.5 real run | 1925→2005 |
| 05-08 | 三档侧栏 + Learn Mode Dialog + CSP/z-index + v1.0 收尾 + v1.1 review-fix | 2005→2055 |
| 05-09 | Path-scoped learn + SSE progress + PWA + install 写闭环 + P1 功能增量 | 2055→2088 |
| 05-10 | Graph refresh + DB check + frontend review-fix + CI coverage + compatibility + error/locale/i18n hardening | 2088→2136 |
| 05-11 | Onboarding / Guide QA follow-up + DiagnosticRow + full Playwright rerun | backend 2136 / frontend 268 / Playwright 2630 |
| 05-11 | Viewer Review / Quiz / Learn polish + full Playwright rerun | frontend 269 / Playwright 2630 / i18n 1101 |
| 05-11 | ConceptGraph Canvas migration + graph confidence hardening | frontend 270 / graph route+parser 117 / target Playwright 62 |
| 05-11 | AI 工具指引命名与交互收口 + Ratchet JSON export + Audit 最新优先 | backend target 116 / frontend 270 / target Playwright 59 / i18n 1176 |
| 05-12 | APKG export + read-only MCP server + lesson walkthrough_tldr + SSE/SearchOverlay/ErrorBoundary/CSS hardening | backend 2150 / frontend 310 / target Playwright 10 / coverage run |
| 05-12 | v1.1 security + cross-platform hardening + Phase 2 challenge/export/concept-health/MCP ask_lesson + adversarial hardening | backend 2409 / integration 11 / eval 9 / frontend 326 / i18n 1262 / ruff+format+pyright+typecheck+build+diffcheck |
| 05-13 | RunDetail learnability + lesson/claims/quiz 404 + SearchOverlay/Ledger/ConceptGraph focus hardening | backend target 199 / frontend 336 / SearchOverlay Playwright 60 / i18n 1271 / diffcheck |
| 05-14 | Warm v6 / Blueprint sync + Diff Unified/Split + Dashboard/Graph/Quiz contract hardening | backend 2434 / integration 11 / eval 9 / frontend 344 / Playwright 2735 / i18n 1392 / wheel+ruff+format+pyright+typecheck+build+diffcheck |
| 05-15 | Review lazy import + Graphify update/import + skipped-run persistence + quiz count + Diff/Review/Lesson polish | backend 2502 / integration 11 / eval 9 / frontend 350 / full Playwright 2855 / i18n 1447 / ruff+format+pyright+wheel+typecheck+build+diffcheck |
| 05-15 | Diff claim highlight + Welcome lesson accordion polish | backend unit 2502 / frontend 353 / i18n 1449 / typecheck+build+diffcheck |
| 05-15 | Learn Mode safety/a11y + Diff claim aggregation hardening | backend unit 2513 / integration+eval 20 / frontend 360 / i18n 1454 / ruff+format+pyright+wheel+typecheck+build+diffcheck |
| 05-16 | Run Detail / Judge / safety findings UX + hard gate wording | backend target 1+53 / frontend 362 / Run Detail+walkthrough E2E 57 / i18n 1485 / target ruff+format+pyright+typecheck+build+diffcheck |
| 05-17 | Diff inline source preview + Welcome real-run preview | frontend 362 / Diff E2E 1 / Welcome E2E 4 / i18n 1490 / typecheck+build |
| 05-17 | Completion audit + docs sync + provider/SQLite/path hardening | backend 2530 / integration+eval 20 / frontend 365 / full Playwright 2945 / real-serve 2 / live judge 2 / Linux SQLite 3.51.3 / ruff+format+pyright+wheel+typecheck+lint+build+diffcheck；remote CI jobs failed before steps/logs |


<!-- AHADIFF:BEGIN target=claude -->
## AhaDiff

When working in this repository, use AhaDiff for learn-back and verification:

- `ahadiff learn HEAD~1..HEAD`
- `ahadiff quiz <run_id>`
- `ahadiff review`
- `ahadiff verify <run_id>`

Treat `.ahadiff/review.sqlite` as the local truth source for scores, review
cards, and learning signals. Do not write API keys or local provider endpoints
into committed documentation.
<!-- AHADIFF:END -->
