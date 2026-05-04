# 知返 AhaDiff

> AI 写完，Diff 教回。 / Ship with AI. Learn it back.

## 项目愿景

知返 AhaDiff 是一个 **local-first 的 verified diff learning layer**。它把 AI 工具写出的 git diff，变成带代码证据链的学习笔记、概念图谱、主动回忆测验、SRS 复习卡和质量棘轮记录。核心差异定位：Code Wiki 解释仓库，知返解释这次改动；而且每句话都能回到代码证据。

**当前阶段**：v0.2 Gate 0-6 底座 + v1.0 后端增量（helpfulness/transfer、misconception cards、Graphify 全栈、learn orchestrator + `POST /api/learn`、watcher core）。Phase 0G 合同边界已收口（2026-04-29）。symbol extraction 顺序 `python_ast -> tree_sitter -> regex -> section_header`。**最新 gate（2026-05-04）**：后端 `1835 passed`；pyright 0 errors；前端 unit `166 passed`、E2E `1920 passed`（含 axe-core a11y 12 页面 12/12）。`/api/tasks*` 已提升为 stable product API。`POST /api/learn` 10 req/min rate limit + `TaskErrorCode` + `recovery_hint`。当前是 51 concrete `/api/*` routes + 1 catchall（含 Provider CRUD 4 端点 + probe 真实接入）；benchmark suite digest `99feae11...ef1f1`、Graphify perf gate `ok`。5E provenance API 已暴露（`GraphProvenance` + `graph_sha256`/`import_time`/`parser_version`，字段收紧为 64-hex/max64），large-repo benchmark gate ok（500/5000-node）。MIT LICENSE 已就位。

## 架构总览

后端 CLI 主链路（learn/improve/verify/serve/install/benchmark）已跑通：8-provider LLM + diff capture + claims + lesson/quiz/concepts + 8 维 eval + review.sqlite FSRS-6 + serve API（51 routes + catchall）+ 13 install targets + improve loop + i18n-0。`POST /api/learn` 已有 in-memory 10 req/min 写限流，`TaskInfoResponse` 稳定暴露 `result_summary`、`TaskErrorCode` 和 `recovery_hint`；`/api/tasks*` 已于 2026-05-02 提升为 stable product API（§9.10）。Provider CRUD API（`POST/PUT/DELETE /api/providers`）+ probe 真实接入（TaskRunner 异步 + TOCTOU core fingerprint 防漂移 + 全局 3 并发配额）已就位。前端 `viewer/` React 19 SPA：12 页面、26 TSX 组件、32 CSS 文件。核心安全 helper 集中在 `core/json_util.py` / `sqlite_util.py`；serve 拒绝 proxy trace headers，token bootstrap 做同源检查。

### 计划技术栈

- **后端 CLI**：Python 3.11+, typer, rich, pydantic, httpx, pyyaml, fsrs (FSRS-6)
- **前端 Viewer**：React 19 + Vite + vanilla CSS（`AhaDiff Warm v6.html` 设计参考）。`ahadiff serve` 启动 Starlette + Uvicorn + Vite dev/build，`--no-browser` 禁用自动打开。不使用 Next.js 等 SSR 框架
- **评估系统**：LLM-as-judge + 8 维 rubric（accuracy/evidence/diff_coverage/learnability/quiz_transfer/spec_alignment/conciseness/safety_privacy = 100 分）+ git ratchet
- **LLM Provider**：8 种 API 格式（OpenAI Chat / Responses / Gemini / Anthropic / Azure OpenAI / New API / CherryIN / Ollama）。BYOK：model_name + base_url + api_key → 自动探测 temperature/TPM/RPM/context_length
- **不使用**：LiteLLM（供应链风险）、LangChain、Jinja2 渲染前端、Next.js

### 八层架构（计划）

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

编排 contract 冻结在 `src/ahadiff/contracts/orchestrator.py`；运行时 learn 主链在 `src/ahadiff/core/orchestrator.py`。results.tsv 降级为 review.sqlite 的导出视图。

### 数据范围架构

> 核心原则：**per-repo truth + global derived governance**

CLI 全局安装（`pip install ahadiff`），per-repo 运用（每个 repo 独立 `.ahadiff/`）。

```
global_config_dir()                   ← Global（派生/索引/偏好，非真相源）
  Linux: ~/.config/ahadiff/  macOS: ~/Library/Application Support/ahadiff/  Windows: %APPDATA%/ahadiff/
├── config.toml / registry.json / usage.sqlite / security/allowlist.yaml

<repo>/.ahadiff/                      ← Per-repo（唯一真相源）
├── config.toml / review.sqlite / concepts.jsonl / ahadiff.lock
├── runs/<run_id>/  graphify/  audit.jsonl  audit.private.jsonl
```

**Config 优先级链**（高到低）：`ENV(AHADIFF_*) → CLI flag → per-repo config.toml → global config.toml → defaults`。凭证类：`env secret → per-repo env_var_name → global env_var_name → none`。

**不可全局化的真相源**：review.sqlite / audit.jsonl / concepts.jsonl / prompts/ / VCR cassettes / Graphify cache。任何 global 数据不参与 ratchet 判定。

## 模块结构图

```mermaid
graph TD
    A["(根) 知返 AhaDiff"] --> B["doc"];
    A --> C["ui"];
    A --> D["AhaDiff Warm v6.html"];

    click B "./doc/CLAUDE.md" "查看 doc 模块文档"
    click C "./ui/CLAUDE.md" "查看 ui 模块文档"
```

## 模块索引

| 模块 | 路径 | 职责 |
|------|------|------|
| contracts | `src/ahadiff/contracts/` | 枚举、DTO、契约 helper、错误类型；公开 ID 拒绝空字符串 |
| core | `src/ahadiff/core/` | CLI 配置、路径（含 WSL2）、ID、json_util/sqlite_util 安全 helper、registry、task_runner（600s timeout + draining + shutdown）、watcher（debounce + dead/hung observer） |
| safety | `src/ahadiff/safety/` | ignore / redaction（含 URL-embedded secret + URL userinfo 检测规则）/ injection / gates / audit |
| llm | `src/ahadiff/llm/` | provider（streaming byte cap + cache + usage.sqlite + DNS IP pinning TOCTOU 闭合）、probe、cache、cost、adapters、usage |
| claims | `src/ahadiff/claims/` | claim 解析、runtime、negative scan、deterministic verifier |
| lesson | `src/ahadiff/lesson/` | learnability gate、三档 lesson 生成、section helpfulness、learning transfer |
| quiz | `src/ahadiff/quiz/` | quiz/cards/misconception_cards JSONL、review_card_id 回填 |
| wiki | `src/ahadiff/wiki/` | concepts.jsonl 累积、streaming reader（FIFO 拒绝）、ancestry cache（v7 derived index）、DB/JSONL cursor 分页、Graphify linking |
| graphify | `src/ahadiff/graphify/` | models/parser/matcher/linker/slicer/search/freshness（7 态 + 4 值投影）；parser：50 MiB 上限 + 50k edge cap + dedup + dangling removal + sanitization + graph_sha256 provenance |
| eval | `src/ahadiff/eval/` | 8 维评分、hard gates、ratchet、result_events、results.tsv 导出 |
| review | `src/ahadiff/review/` | review.sqlite schema v1→v8 migration + FTS5（concepts/result_events/cards/graph_nodes）+ FSRS-6（NaN/Inf 拒绝）+ search + optimizer（cold/warm/hot）+ cards question/answer 字段 |
| serve | `src/ahadiff/serve/` | 51 routes + catchall；auth（token + 同源 bootstrap）/ CORS / CSP / proxy-trace 拒绝；learn/tasks（stable API）/graph/config/search/usage/audit 端点；Provider CRUD（`POST/PUT/DELETE /api/providers` + probe 真实接入：TaskRunner 异步 + TOCTOU fingerprint + 全局 3 并发配额）含 alias 校验 + base_url normalize + SSRF 校验 + stale probe 清理 + audit trail；`POST /api/learn` 10 req/min 写限流；TaskInfoResponse `TaskErrorCode` + `recovery_hint`；`PUT /api/config` 支持 lang/privacy_mode/generate_model/judge_model/serve_port/capture/llm 七组字段持久化到 config.toml；GraphProvenance；读路径 DB 迁移 + 损坏降级；lifespan shutdown hook |
| install | `src/ahadiff/install/` | 13 安装目标、Jinja2 模板、InstallManifest、hook leaf no-follow 校验 |
| improve | `src/ahadiff/improve/` | improve session、worktree replay、prompt 白名单、Phase 2.5、cherry-pick |
| i18n | `src/ahadiff/i18n/` | locale resolver、Accept-Language / cookie / config / LANG fallback |
| benchmarks | `benchmarks/` | 7+3 fixtures（含 500/5000-node + graph-present）、manifest、scripts runner |
| viewer | `viewer/` | React 19 + Vite + Zustand + HashRouter；12 页面 + 26 组件 + 79 design tokens（含 v6 spacing/radius/shadow/duration/easing + font-size 9 级 + line-height 4 级）；全量 design token normalize 完成（848 token 引用覆盖 27 CSS 文件，legacy --radius-*/--shadow-*/--duration-* 转 v6 alias）；Settings 8-tab（Account/Provider/Capture/Privacy/Audit/Language/Appearance/Integrations），Provider tab 完整 CRUD（ProviderCard 组件：展开/编辑/删除/probe polling，Inline Accordion + grid 跨列编辑态 + AbortController 轮询清理）+ 模型选择 + LLM 设置；Capture（capture limits + file_ranking）、Privacy（隐私模式+端口）均可编辑并持久化到 config.toml；Diff 页面文件级折叠（parseDiffFileSections + sticky header + IntersectionObserver）+ ClaimInspector 简化（jump-to-code + gutter dots）+ 长行 soft-wrap；learn task UI（LearnTaskBanner + learn-store，含 `recovery_hint` Retry gate 与 429 rate_limited 文案）；Graphify shared freshness store（graph-store）+ GraphifySourceCard 共享展示组件 + provenance UI；Landing APG tabs（circular wrap + RTL）；StaticSwitch 只读语义修正；InfoHint tooltip 组件（hover/focus/Escape/a11y）；Review q/a 全栈 + 错误状态分级 + 评分刷新 + 证据链接；Ratchet 8 维 InfoHint；axe-core a11y 12/12；E2E 1920 passed；unit 166 |
| tests | `tests/unit/eval/integration/live/` | 1835 passed；含跨平台 static guard + live LLM judge（opt-in） |
| doc | `doc/` | 产品设计文档 |
| ui | `ui/` | UI 原型 Warm v1-v6 |
| team-plan | `.claude/team-plan/` | v0.1 kickoff + 修订方案 |

## 运行与开发

### 验证命令

```bash
uv run pytest tests/unit
uv run ruff check src tests
uv run pyright
uv build --wheel
uv run python -m ahadiff --version
uv run ahadiff init / doctor / config show --resolved
```

LLM judge smoke（opt-in）：

```bash
AHADIFF_LIVE_LLM_JUDGE=1 \
AHADIFF_LIVE_LLM_API_KEY="$AHADIFF_LIVE_LLM_API_KEY" \
AHADIFF_LIVE_LLM_BASE_URL="$AHADIFF_LIVE_LLM_BASE_URL" \
AHADIFF_LIVE_LLM_MODELS="gpt-5.3-codex-spark,gpt-5.4-mini" \
pytest tests/live/test_llm_judge_live.py -q
```

### 依赖状态

`pyproject.toml` + `uv.lock`（后端 Python）；`viewer/package.json` + pnpm（前端 React 19 + Vite + Vitest + Playwright）。

## 测试策略

- 单元/集成/eval 测试覆盖 Stage 0-6 + v0.2 Gate 0-6 + v1.0 增量
- VCR 双层版本：run 级 `prompt_version` + cassette 级 `prompt_fingerprint + model_id + api_family_version + eval_bundle_version + output_lang` 五元组 hash
- CI 分档：PR unit+pinned（`ubuntu py311/py312 + macOS py312`）+ Windows runtime guard；nightly eval；release 全量 + coverage ≥85% + doctor + wheel smoke
- Benchmark：Python 主套件（7份）+ Non-Python 降级套件（3份），独立 recall/precision

## 编码规范

- 中文为主，技术术语保留英文。品牌「知返 AhaDiff」，CLI `ahadiff`
- Python：ruff + pyright strict + pre-commit；线宽 100，ruff 规则 `F,E,W,I,UP,B,C4,SIM,RET,PTH,TC,FA`
- 所有 LLM 调用走 `llm/provider.py`，禁止直接 import anthropic/openai
- prompt 写独立 `.md`，禁止 f-string 拼长 prompt

## AI 使用指引

### 硬性要求
- **所有文档更新必须基于真实代码 + 真实测试结果 + 当前文档状态**。如文档间漂移，以代码和测试为准。**严禁虚构函数、虚构测试结果、虚构库名或编造不存在的设计决策。**
- 中英文对照文档修改时必须同步更新。
- committed docs 不得写入真实 API key、本地 endpoint 或带用户名的绝对路径。

### 关键设计决策（读取文档前必知）
1. **N-文件契约**（受 autoresearch 启发）：`program.md` + **evaluation bundle**（eval/ 下 5 文件，整体 immutable，变更触发 `eval_bundle_version` 更新 + VCR 失效）+ prompt 集合。**可写 prompt 白名单** 仅限 `lesson_generate.md`、`lesson_hint.md`、`lesson_compact.md`、`quiz_generate.md`、`claim_extract.md`；`prompts/improve_program.md` 是 immutable state machine
2. **Claim Verifier 是核心护城河**：每句解释绑定 file:line 证据，claim 五种状态（verified/weak/not_proven/contradicted/rejected），rejected = 引用 patch 外文件或不存在的证据（附 reason_code）
3. **棘轮机制**：improve/Phase 2.5 在 `git worktree` 执行，不碰主分支。连续 2 个优化目标 round1 无增益触发 Phase 2.5（最多 1 次/session）
4. **跨模型评估**：生产要求生成≠评估模型。开发阶段统一 gpt-5.4-mini
5. **SQLite 唯一真相源**：`review.sqlite` result_events 表。TSV 为导出视图（写入失败仅 warn）。前端只是 viewer
6. **安全脱敏顺序**：raw → secret scan → redact → 才能 log/cache/model/render
7. **隐私三档**（统一 snake_case）：`strict_local`（默认）/ `redacted_remote` / `explicit_remote`
8. **i18n 全链路**：cookie `ahadiff_lang` → Accept-Language → AHADIFF_LANG → CLI `--lang` → config.toml → LANG → en。支持 en/zh-CN。SRS 卡片保留创建时语言不重翻译。审计日志始终英文
9. **UNTRUSTED_DIFF 扩展边界**：diff/文件名/commit message/branch 名/Graphify label/模型输出/VCR cassette 均视为 untrusted，统一经 `redaction_pipeline()` 处理
10. **SQLite 运行时版本门禁**：WAL + busy_timeout + trusted_schema=OFF + quick_check
11. **架构权威源**：`contract-freeze.md` 是唯一架构权威源
12. **Graphify v0.1 可选增强**：存在则导入 + sanitization，不存在则降级。7 态内部、4 值对外投影。v0.1 权威路径是 `ahadiff serve` + React Viewer

### 灵感项目
- **autoresearch**（Karpathy）：三文件契约 + git ratchet → N-文件变体
- **SKILL0**（ZJU-REAL）：学习撤架 → section 粒度 helpfulness
- **darwin-skill**：8 维 rubric + Phase 2.5
- **SkillCompass**（Evol-ai）：weakest-dimension-first → 8 维体系阈值 80/60
- **Graphify** → 7 态新鲜度 + 4 值投影
- **LLM Wiki**（Karpathy）→ concepts.jsonl append-only

## 多模型协作策略

| 模型 | 角色 | 职责 |
|------|------|------|
| **Claude** | 编排 + 前端实现 | 任务编排、前端实现、文档、集成 |
| **Codex** | 后端实现 | Python CLI、测试、包发布 |
| **Gemini** | 前端评审 | UI/UX 评审（不写代码），仅用 `gemini-3.1-pro-preview`，429 时 Claude 兜底 |

### 文件所有权

| 范围 | 写入 | 审查 |
|-----|------|------|
| `src/ahadiff/**/*.py` / `tests/**` | Codex | Claude + Codex |
| `viewer/src/**/*.tsx` / `*.css` | Claude | Claude + Gemini |
| `prompts/*.md` / `doc/**` / `CLAUDE.md` | Claude | — |

### 阶段门禁（Stage Gate）

每 Stage 完成后必须跨模型交叉审查（Codex 代码正确性 + Claude 架构/安全 + Gemini 前端 UX）。

- **GO**：0 Critical + 0 High → 进入下一 Stage
- **CONDITIONAL GO**：0 Critical + ≤3 High → 修复后验证
- **NO GO**：≥1 Critical 或 >3 High → 全量重审

审查清单：功能正确性、CC 覆盖、文档同步、`pyright` 零错误、`ruff` 通过、安全扫描、跨平台兼容、集成点验证。

Stage 0-7 对应 Task 0→20 + i18n signoff，详见 `doc/` 设计文档。

## 变更记录 (Changelog)

> 设计阶段（04-19~21）10 轮三模型审查完成架构冻结。详见 `git log`。

| 日期 | 里程碑 | Tests |
|------|--------|-------|
| 04-22~24 | Stage 0-5: contracts → CLI → safety → capture → provider → claims → lesson → quiz → eval → ratchet → review.sqlite → improve | 61→406 |
| 04-24~25 | Stage 6-7 + Viewer A-E + R1-R5 审查（51 findings closed） | 478→559 |
| 04-26~27 | v0.2 Gate 0-5 + Frontend Phase 1-4 | 576→808 |
| 04-28 | Phase 0 follow-up + v0.2 Gate 6（FTS5 + optimizer） | 845→993 |
| 04-29 | v1.0 Phase 0G/1A-D/3A-E/6B 收口 + backend medium slice | 1191→1266 |
| 04-30 | 文档同步 + 对抗式审查（Codex+Claude 8轨）+ auth/FSRS/watcher closure | 1479→1526 |
| 05-01 | Phase 4D Settings + 5B concept linking + 5C FTS graph + 6B tasks API + 7B 安全加固 + learn UI + DNS pinning 闭合 | 1526→1689 |
| 05-02 | Graphify graph-present fixture + 完整 gate 重跑（coverage 87.33%） | 1736 |
| 05-02 | viewer learn/graph follow-up：safe retry/cancel/recovery、Graphify shared cache、task schema 对齐；前端 unit 118，目标 Learn E2E 8 | 1736 |
| 05-02 | Phase 6B hardening：`/api/learn` 10 req/min rate limit、TaskErrorCode/recovery_hint 合约、LearnTaskBanner 429/retry 文案；后端全量 1754，前端 unit 123，i18n 459/459 | 1754 |
| 05-02 | R0 真值重建 + P1-P6：`/api/tasks*` 提升 stable API、Graphify 5E provenance API + large-repo signoff、concepts CLI hardening（verify/export/rollback）、watcher circuit breaker + retry backoff、axe-core a11y 测试、MIT LICENSE；前端 unit 123，i18n 462/462 | 1754 |
| 05-03 | Viewer UI/UX round：Landing APG tabs（circular wrap + RTL + aria-label）、StaticSwitch 只读语义修正（去 role="switch" + sr-only sibling）、GraphifySourceCard 共享展示组件抽取、print demo-boundary 对齐、CopyButton aria-live 反馈；后端 1755，前端 unit 130，i18n 470/470，E2E 1170 | 1755 |
| 05-03~04 | Onboard-UX Phase 1-3：InfoHint tooltip 组件 + 14 单测；Review q/a 全栈（DB v7→v8 + contract + Zod + 渲染）；错误状态分级（network/auth/unknown）+ 评分后刷新；证据链接；ARIA 补全（rating aria-describedby + 翻卡焦点）；InfoHint 扩展（Dashboard/Ratchet 8 维）；跨浏览器 E2E（Chromium+Firefox+WebKit）；读路径 DB 迁移 + 损坏降级；weak concepts partial index；ConceptGraph RAF 优化；Codex 4 轮对抗式审查 + Gemini UX 审查 98/100；后端 1781，前端 unit 152，i18n 552/552，E2E 1920 | 1781 |
| 05-04 | Settings 可编辑化 + capture 优化：capture 默认值调优（max_files 50→30, hard_limit 5000→3000, max_patch_bytes 10MB→5MB）；新增 `capture.file_ranking` 智能文件排序（learning_value/changed_lines/path，按源码>配置>测试>文档>生成优先）；`PUT /api/config` 扩展支持 privacy_mode/generate_model/judge_model/serve_port/capture/llm 七组字段持久化到 config.toml；Settings tab 从 9 合并为 8（Keys+Models→Provider），Provider/Capture/Privacy 三个 tab 均可编辑保存；diff parser 防御性跳过 hunk body 中的 git metadata 行；provider 401/403 错误从 SafetyError 改为 ProviderError（正确映射 config_error）；injection.py protect_untrusted_text 尾换行修复；后端 1781，前端 unit 152 | 1781 |
| 05-04 | 全量 design token normalize：tokens.css 新增 --fs-2xs~3xl（9 级 font-size）+ --lh-tight~relaxed（4 级 line-height）；legacy token（--radius-8/12/pill、--duration-fast/normal）转 v6 alias；27 CSS 文件迁移 848 处 token 引用（--sp-* 474 + --r-* 114 + --dur-* 89 + --ease-* 74 + --fs-* 72 + --sh-* 25）；移除错误 fallback（var(--accent, #6366f1) 等）；Settings --bg-card/--fg→--elevated/--ink；SearchOverlay -webkit-backdrop-filter 补全；Claude UX 审查 91/100 + Codex 交叉审查 PASS；后端 1781，前端 unit 152，E2E 1809 | 1781 |
| 05-04 | Diff 页面 UX 重构 + Provider Settings 全功能改造：Diff 布局修复（`minmax(0,1fr)` 治右侧面板溢出）+ 长行 soft-wrap（`pre-wrap`）+ ClaimInspector filter 回弹 bug 修复；Provider CRUD 后端（`contracts/serve_providers.py` DTO + `routes_providers.py` 4 端点 + config helpers：alias 校验/base_url normalize/stale probe 清理/fingerprint）+ 前端 ProviderCard 组件（Inline Accordion 展开编辑 + probe polling AbortController + 状态 dot + inline 删除确认 + sr-only a11y）+ API 层（`providers.ts` + Zod schema 对齐）；Codex 双轮对抗式审查 + 3 CRITICAL 修复（DTO 字段对齐/响应 schema 补全/probe stub 501）+ 5 WARNING 修复（alias 校验统一/base_url 校验/URL secret mask/polling cleanup/sr-only）；后端 1810，前端 unit 166 | 1810 |
| 05-04 | Probe 真实接入 + URL secret masking 加固：`POST /api/providers/{alias}/probe` 从 501 stub 接入真实 `probe_provider()`（TaskRunner 异步提交 + TOCTOU core fingerprint 防漂移 + 全局 3 并发配额）；`redact.py` 新增 `URL_EMBEDDED_SECRET`（case-insensitive）+ `URL_USERINFO_SECRET` 检测规则；`validate_provider_base_url` 错误消息通过 `_safe_url_repr` 遮盖原始 URL 防泄露；probe task 异常全捕获防信息外泄；Claude+Codex 双路对抗式审查 0 CRITICAL 0 HIGH；后端 1835 | 1835 |

> 每条门禁的详细实现笔记见 `git log` 对应 commit message。
