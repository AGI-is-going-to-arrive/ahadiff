# 知返 AhaDiff

> AI 写完，Diff 教回。 / Ship with AI. Learn it back.

## 项目愿景

知返 AhaDiff 是一个 **local-first 的 verified diff learning layer**。把 AI 写出的 git diff 变成带代码证据链的学习笔记、概念图谱、主动回忆测验、SRS 复习卡和质量棘轮记录。核心差异：Code Wiki 解释仓库，知返解释这次改动；每句话都能回到代码证据。

**当前状态（2026-05-11）**：本轮 viewer review-fix 只改前端学习面和测试。Learn Mode Dialog 的输出语言默认跟随当前 viewer locale；Review 页面恢复 Again / Hard / Good / Easy 四档评分和 `1`-`4` 快捷键，并补高风险概念 chip、遗忘曲线说明和 mastery warning / danger 色阶；Quiz 页面补 Prev / Mark wrong / Next、mode chips、progress table 和 mark-wrong idempotency，Quiz SRSCard 仍保留 Good / Hard / Wrong 与 peek guard。当前真实验证：`cd viewer && pnpm typecheck` 通过；`pnpm vitest run` = `25 files, 269 tests passed`；`pnpm build` 通过；完整 Playwright `2630 passed, 10 skipped`；i18n scalar keys `1101/1101`；`git diff --check` 通过。Playwright 只有 `NO_COLOR` / `FORCE_COLOR` 环境提示，退出码为 0。后端、integration、eval、live judge、coverage、wheel 和远端 GitHub Actions 未在本轮重跑。

## 架构总览

后端 CLI（learn/improve/verify/serve/install/benchmark）：8-provider LLM + diff capture + claims + lesson/quiz/concepts + 8 维 eval + 可选 LLM judge + review.sqlite FSRS-6 + serve API（61 routes + catchall，稳定 `error_code` payload）+ 13 install targets + improve loop。前端 React 19 SPA：13 页面、47 个生产 TSX + 40 个 CSS 文件，当前 i18n scalar key parity 为 `1101/1101`。

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
| contracts | `src/ahadiff/contracts/` | 枚举、DTO、契约 helper、错误类型、QuizChoice/AnswerMode、27 个稳定 `ErrorCode` + `ERROR_STATUS` |
| core | `src/ahadiff/core/` | CLI 配置、路径、ID、json_util/sqlite_util 安全 helper、task_runner（1800s timeout + 终态单调）、orchestrator（error budget 8 + per-step output caps + changed_paths）、watcher |
| safety | `src/ahadiff/safety/` | ignore / redaction（URL-embedded secret）/ injection / gates / audit |
| llm | `src/ahadiff/llm/` | provider（streaming byte cap + DNS IP pinning + DecodingError 重试）、probe、cache、cost、adapters（thinking.py）、usage |
| git | `src/ahadiff/git/` | diff capture、parser、line map、symbols、hunk hash、`git` 可执行文件检测和 repo write lock |
| claims | `src/ahadiff/claims/` | claim 解析（容错 + 截断 JSON 恢复）、runtime、negative scan、deterministic verifier、`output_lang` 透传 |
| lesson | `src/ahadiff/lesson/` | learnability gate、三档 lesson（full/hint/compact）、section helpfulness |
| quiz | `src/ahadiff/quiz/` | quiz/cards/misconception_cards（ABCD 选项 + 容错解析）、review_card_id 回填 |
| wiki | `src/ahadiff/wiki/` | concepts.jsonl 累积、streaming reader、ancestry cache、DB/JSONL cursor 分页 |
| graphify | `src/ahadiff/graphify/` | parser（50 MiB + 50k edge cap + provenance）/ matcher / linker / freshness（7 态 + 4 值投影） |
| eval | `src/ahadiff/eval/` | 8 维评分、hard gates（contradicted ≤2）、ratchet、可选 LLM judge |
| review | `src/ahadiff/review/` | review.sqlite v9 + FTS5 + FSRS-6 + search + optimizer + ABCD 卡片 |
| serve | `src/ahadiff/serve/` | 61 routes；auth/CORS/CSP；learn/tasks/graph/config/search/usage/audit/review/install/providers 端点；统一 `{error_code,error,status,details?}`；per-request locale；SSE progress；写保护 |
| install | `src/ahadiff/install/` | 13 安装目标、通用写入层（no-follow/reparse/symlink guard）、hooks git 检测/timeout、verify workflow macOS/Linux/Windows matrix |
| improve | `src/ahadiff/improve/` | improve session、worktree replay、prompt 白名单、Phase 2.5、preflight |
| i18n | `src/ahadiff/i18n/` | locale resolver（cookie → Accept-Language → `AHADIFF_LANG` → CLI → config → `LANG`）和 prompt language helper |
| benchmarks | `benchmarks/` | 10 fixtures、Graphify 10k gate（parse 750ms + peak 96MiB） |
| viewer | `viewer/` | React 19 SPA；13 页面；Learn Mode Dialog 默认跟随 viewer locale；Review 四档 SRS + 高风险概念；Quiz 导航 / mark-wrong / progress table；Dashboard + Lesson + Concepts + Ratchet + RunDetail + Settings + Guide + Diff + Search；Onboarding DiagnosticRow；错误码本地化；locale-aware byte/token 格式化；侧栏三档；container query；PWA |
| tests | `tests/` | unit/integration/eval/live；本轮 unit `2136 passed`；CI: PR unit + eval + nightly eval + release coverage ≥85% |
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
- **LLM Wiki**（Karpathy）→ concepts.jsonl append-only

## 多模型协作策略

| 模型 | 角色 | 职责 |
|------|------|------|
| **Claude** | 编排 + 前端 | 任务编排、前端实现、文档、集成 |
| **Codex** | 后端 | Python CLI、测试、包发布 |
| **Gemini** | 前端评审 | UI/UX 评审（不写代码），`gemini-3.1-pro-preview` |

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

审查清单：功能正确性、覆盖率、文档同步、pyright/ruff、安全扫描、跨平台、集成点。

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
