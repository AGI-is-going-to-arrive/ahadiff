# AI Tool Guidance & Guide Agent Skills - Executable `ccg:team` Plan

## 审查结论

**PASS as executable plan. Implementation verified on 2026-05-25.**

这份计划已按当时真实仓库状态重写，可直接交给 Claude Code 使用
`ccg:team` 执行。2026-05-25 的当前代码已经按本计划落地，本文件继续保留
为执行记录和后续审计依据。

本机 `/ccg:team-exec` 的真实约束是读取 `.claude/team-plan/` 下最新计划文件。
因此本次同步提供了 team-exec 入口文件：
`.claude/team-plan/guidance-overhaul-execution.md`。
注意：本仓库 `.gitignore` 当前忽略 `.claude/`；该入口文件是本机执行交接文件，
版本化方案真值仍以本文件为准。

执行入口：

```text
/ccg:team-exec
```

如果当前 CCG 环境暴露的是等价 `ccg:team` 执行命令而不是
`/ccg:team-exec`，Claude main agent 必须使用真实 CCG team 入口，并以
`.claude/team-plan/guidance-overhaul-execution.md` 作为执行计划。不得用普通
Claude 子代理假扮 Antigravity 或 Codex。

本计划会跨后端、前端、i18n、Playwright 和测试文件，属于多文件变更。
启动 `ccg:team` 执行本文件即视为用户对该计划的实现确认；执行中仍必须按
阶段 gate 停止和汇报 Critical / High finding。

## Implementation Status

2026-05-25 当前代码已按本计划落地并完成审计。真实实现没有新增
provider-backed demo；`/api/demo/learn-preview` 是公开、确定性、无写入的
GET endpoint，不要求 `X-AhaDiff-Token`，也不会调用 provider、创建 run 目录
或写 `.ahadiff/`。Install target response 通过共享 `InstallTargetSummary`
携带 `usage_hint`，覆盖 15 个 target，并在 list / preview / install /
uninstall payload 中保持一致。

前端当前实现把 Settings 的 AI 工具指引按 CLI / IDE / CI 分组，展示
usage panel、copyable command 和 deterministic demo；安装成功后只展开并
聚焦刚安装的 target。Guide 保持 read-only，提供 All / CLI / IDE / CI
筛选、usage hints 和 generated / user-managed manifest preview；实际
write/remove 仍只在 Settings。

本轮真实验证：

```text
UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run pytest
  3237 passed, 7 skipped
UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run ruff check src tests
UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run ruff format --check src tests
UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run pyright
  0 errors
pnpm --dir viewer typecheck
pnpm --dir viewer exec vitest run
  46 files, 460 tests passed
pnpm --dir viewer build
AHADIFF_VIEWER_E2E_PORT=5174 pnpm --dir viewer exec playwright test ...
  targeted Guide / Settings / a11y / media matrix: 110 passed, 10 skipped
git diff --check HEAD
```

本轮没有重跑 wheel、real-serve、live judge、远端 CI、Linux Docker gate、
真实 Windows runner，也没有在目标矩阵之外重跑完整 Playwright。

## Grounded Findings From Adversarial Review

本节是对原方案的修订依据。所有条目来自计划编写时 checkout 的真实文件；
行号用于说明当时的审查依据，不作为 2026-05-25 完成实现后的当前行号。

- **Install target 真值是 15 个**：`src/ahadiff/install/registry.py:48-64`
  注册 `aider`, `antigravity`, `antigravity-cli`, `claude`, `cline`,
  `codex`, `continue`, `copilot`, `cursor`, `gemini`, `github-action`,
  `hooks`, `opencode`, `roo`, `windsurf`。所有分类和测试必须覆盖这 15 个。
- **模板真值是 22 个 `.j2` 文件**：`tests/unit/test_install.py:23-46`
  固定 `_INSTALL_TEMPLATE_NAMES`。不得继续写 “24 templates”。
- **Settings 实现入口明确**：`viewer/src/pages/SettingsPage.tsx:2265-2555`
  是 `IntegrationsTab`；当前卡片 loop 是 `localTargets.map()`，核心渲染在
  `2425-2548`。
- **Guide 实现入口明确**：`viewer/src/pages/GuidePage.tsx:201-217` 是静态
  fallback 15-target 列表；`GuidePage.tsx:566-702` 是 `AgentSkillsSection`；
  `690-698` 仍是 `SKILL_PREVIEW` / `AGENTS_PREVIEW` 静态预览。
- **Install contract 是 strict shared DTO**：
  `src/ahadiff/contracts/serve_install.py:24-68` 中 `InstallTargetSummary`
  同时用于 list / preview / mutation response。新增 `usage_hint` 必须同步
  所有 target-shaped response。
- **Exact-key 测试会拦截字段漂移**：
  `tests/unit/test_routes_install.py:283-307` 精确断言 install target key set。
- **Route 注册不是 FastAPI Router**：`src/ahadiff/serve/app.py:153-263` 使用
  Starlette `Route(...)` 集中列表；新增 `/api/demo/learn-preview` 必须注册在
  `/api/{rest_of_path:path}` catchall 之前。
- **现有 write rate limit 只有 `/api/learn`**：
  `src/ahadiff/serve/middleware.py:291-294` 的 `_RATE_LIMITS` 只有 10/min 的
  `/api/learn`。本计划默认 demo 不调用 provider、不写状态，因此不新增 rate
  limit；provider-backed demo 另立 RFC。
- **真实 provider 调用不是 read-only**：`src/ahadiff/llm/provider.py:426-443`
  会写 cache/usage，`provider.py:741-743` 会写 audit/private audit。因此原
  “live provider demo” 对 onboarding 过重，本计划改为确定性内置 demo。
- **UI locale 路径是真实存在的**：后端请求 locale 使用
  `src/ahadiff/serve/locale.py:13-20` 的 `request_locale(request)`；前端
  `MessageKey` 从英文 catalog 推导，见
  `viewer/src/i18n/useTranslation.ts:24-35`。
- **跨浏览器矩阵是真实配置**：`viewer/playwright.config.ts:3-30` 生成
  Chromium / Firefox / WebKit × phone-narrow / mobile / tablet / laptop /
  desktop 项目，项目名如 `chromium-desktop`、`firefox-desktop`、
  `webkit-desktop`。
- **项目文档存在漂移**：`CLAUDE.md` 和 `AGENTS.md` 的全局协作策略仍以
  Gemini/Claude 前端实现为主；本计划按用户最新要求锁定 Antigravity 负责
  前端 UI/UX/交互/实现/review。不要在本实现中顺手改 `CLAUDE.md` /
  `AGENTS.md`，除非用户后续明确选择“使用 recorder agent 更新项目文档”。

## Problem Statement

Settings > AI Tool Guidance and Guide > Agent Skills currently emphasize
**installation / writing repo-local guidance**. Users can write guidance files,
but the UI gives limited help for:

- what happens after guidance is written;
- how to invoke AhaDiff from each AI tool;
- which commands are the safe daily workflow;
- what output AhaDiff will produce.

Result: users can complete setup but still fail to turn guidance into daily use.

## Execution Contract For `ccg:team`

### Claude Main Agent

Claude main agent is the orchestrator only:

- decompose phases, assign owners, manage dependencies, aggregate evidence;
- keep the main context small by delegating implementation and review;
- maintain the checklist and stage evidence blocks;
- never edit code directly;
- never call Codex through `Skill(codex:review)` or generic codeagent wrappers;
- never treat a Claude subagent named “Codex” or “Antigravity” as the real tool.

### Codex Routing

All backend, CLI, Python contract, security, test, and non-frontend fixes go
through the installed `codex-plugin-cc` with the default model:

```text
implementation / fix / investigation -> /codex:rescue --background "..."
normal review -> /codex:review --background
adversarial review -> /codex:adversarial-review --background "focused review text"
status -> /codex:status
result -> /codex:result
cancel -> /codex:cancel
```

Codex rules:

- do not pass `--model`;
- do not pass `--effort`;
- use `--background` for long tasks unless the gate explicitly needs a
  synchronous result;
- instruct Codex to use sub-agents / multi-agents where safe;
- split write tasks only by disjoint write sets;
- serialize same-file edits, shared fixtures, and dependency chains.

### Antigravity Routing

All frontend UI/UX, React, CSS, front-end Zod schema, front-end i18n, browser
interaction design, Playwright authoring, and visual review go to **real
Antigravity through CCG**.

Antigravity rules:

- owns `viewer/` implementation and frontend review for this plan;
- covers Chromium / Firefox / WebKit, desktop / mobile, forced-colors,
  reduced-motion, English, and zh-CN;
- does not edit backend Python;
- if a backend API gap blocks frontend work, reports a blocker to Claude main,
  and Claude routes it to Codex.

Fallback rule for Antigravity failures:

- after repeated Antigravity 429, timeout, or unavailable errors, Claude main
  records command, exit code, stderr, and retry count;
- fallback implementation may use a dedicated Claude team frontend worker only
  after those failures are recorded;
- Claude main agent still must not edit code directly;
- any Claude fallback frontend diff must receive Antigravity retry review if the
  tool becomes available, plus Codex adversarial review before the next stage.

### Stage Gate Order

Every sprint / phase / gate must complete this sequence before the next one:

1. owner self-test;
2. Codex adversarial review through `/codex:adversarial-review --background`;
3. fix all Critical / High findings through the correct owner;
4. browser实测 for any `viewer/` or user-visible change;
5. Claude + Codex cross-review;
6. concise evidence block with commands, pass counts, skipped checks, and
   known limitations.

Stop immediately on:

- any unresolved Critical finding;
- any unresolved High finding without explicit written acceptance;
- Antigravity unavailable and no approved fallback;
- Codex plugin unavailable;
- tests that fail for unknown reasons;
- accidental provider call or write from the deterministic demo endpoint.

## Verified Current Architecture

- **Settings Tab**: `viewer/src/pages/SettingsPage.tsx:2265-2555`
  `IntegrationsTab` renders backend install targets. Card rendering is
  data-driven from `localTargets.map()`.
- **Guide Section**: `viewer/src/pages/GuidePage.tsx:566-702`
  `AgentSkillsSection` fetches `GET /api/install/targets`, falls back to the
  static 15-target list at `GuidePage.tsx:201-217`, and renders static preview
  blocks.
- **Backend install response**: `GET /api/install/targets` returns status,
  commands, platform support, manifest preview, manifest hash, and error fields
  via `InstallTargetSummary`; it does not include invocation guidance yet.
- **Install targets**: current registry has exactly 15 targets listed above.
- **Templates**: current packaged install templates are 22 static Jinja2 `.j2`
  files rendered by `render_template(name)` without template values.
- **i18n**: frontend messages live in
  `viewer/src/i18n/messages/en.json` and `viewer/src/i18n/messages/zh-CN.json`;
  parity is guarded by `viewer/tests/unit/i18n-parity.test.ts`.
- **Platform detection**: frontend shell hints use
  `viewer/src/utils/platform.ts` and distinguish Windows PowerShell from
  macOS/Linux terminal syntax.

## Locked Product Decisions

1. Use 15 install targets, not 13 and not 24 template count.
2. Add usage guidance to install target responses through shared
   `InstallTargetSummary`; include it consistently in list / preview /
   mutation target payloads.
3. Use backend-localized usage strings via `request_locale(request)` for
   `usage_hint` content. Keep chrome labels and UI control text in the frontend
   EN/ZH catalogs.
4. Default demo is deterministic and built-in. It must not call an LLM provider,
   read the current repo diff, create a run, write cache, write usage, write
   audit, create cards, touch concepts, or emit ratchet events.
5. Provider-backed live demo is explicitly out of scope for this implementation.
   If desired later, it needs a separate security/product plan because provider
   calls write cache/usage/audit.
6. Guide remains read-only. It can preview generated/user-managed file actions,
   but actual write/remove stays in Settings.
7. Hooks remain POSIX-only and visibly unsupported on Windows.
8. EN/ZH i18n keys must be added in the same diff.
9. Browser coverage must include Chromium, Firefox, WebKit, mobile/narrow
   viewport, forced-colors, reduced-motion, and English/zh-CN checks.

## Architecture Changes

### Phase 1: Backend Contracts And Usage Hints

Owner: Codex via `/codex:rescue --background`.

Add strict usage hint data to `src/ahadiff/contracts/serve_install.py`:

```python
class ToolUsageHint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_category: Literal["cli", "ide", "ci"]
    invocation_pattern: str = Field(min_length=1)
    quick_start_steps: list[str] = Field(min_length=1, max_length=5)
    example_prompts: list[str] = Field(default_factory=list, max_length=5)
    expected_behavior: str = Field(min_length=1)
    platform_notes: dict[Literal["windows", "macos", "linux"], str] = Field(default_factory=dict)
```

Required changes:

- add `usage_hint: ToolUsageHint | None = None` to `InstallTargetSummary`;
- add `ToolUsageHint` to `serve_install.py::__all__`;
- export it from `src/ahadiff/contracts/__init__.py` only if existing contract
  export patterns require it;
- create `src/ahadiff/install/usage_hints.py`;
- provide usage hints for all 15 `available_targets()` entries;
- localize content by passing `request_locale(request)` from routes;
- update exact-key tests in `tests/unit/test_routes_install.py`;
- update preview/install/uninstall nested target response tests;
- do not change `InstallPreviewRequest`, `InstallMutationRequest`,
  `_manifest_hash()`, or `confirmed_manifest_hash`.

Target categories:

- CLI: `claude`, `codex`, `antigravity-cli`, `gemini`, `aider`, `opencode`.
- IDE: `antigravity`, `cursor`, `cline`, `continue`, `copilot`, `windsurf`,
  `roo`.
- CI: `github-action`, `hooks`.

### Phase 2: Deterministic Demo API

Owner: Codex via `/codex:rescue --background`.

Add a safe, deterministic endpoint:

```text
GET /api/demo/learn-preview
```

Implementation shape:

- new contract file: `src/ahadiff/contracts/serve_demo.py`;
- new route file: `src/ahadiff/serve/routes_demo.py`;
- optional pure-data helper: `src/ahadiff/demo/learn_preview.py` if route code
  would otherwise become bulky;
- handler shape: `async def get_demo_learn_preview(request: Request) -> JSONResponse`;
- register in `src/ahadiff/serve/app.py` before the API catchall.

Response contract:

```python
class DemoClaimPreview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1)
    status: Literal["verified", "weak", "not_proven"]
    evidence: str = Field(min_length=1)

class DemoQuizPreview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1)
    choices: list[str] = Field(min_length=2, max_length=5)
    answer_index: int = Field(ge=0, le=4)

class DemoLearnPreviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    locale: Literal["en", "zh-CN"]
    sample_diff: str = Field(min_length=1)
    claims: list[DemoClaimPreview] = Field(min_length=1, max_length=3)
    lesson_snippet: str = Field(min_length=1)
    quiz: DemoQuizPreview
```

Hard constraints:

- no provider calls;
- no `X-AhaDiff-Token` requirement;
- no `_RATE_LIMITS` change;
- no repo diff reads;
- no run directory;
- no `.ahadiff/` writes;
- no usage/audit/cache writes;
- no review cards, concepts, graph refresh, or ratchet event.

Tests must assert the endpoint remains deterministic and no provider path is
called. Provider-backed demo belongs to a future RFC, not this plan.

### Phase 3: Settings Tab Redesign

Owner: Antigravity through CCG. Backend blockers go to Codex.

Current state: one responsive grid of backend target cards with status, command
copy, preview, write/remove buttons, and manifest details.

Target state:

```text
AI Tool Guidance
├── Quick Overview
│   ├── guidance written count
│   ├── available count
│   └── unsupported count
├── CLI Tools
│   └── Claude Code / Codex CLI / Antigravity CLI / Gemini CLI / Aider / OpenCode
├── IDE Extensions
│   └── Antigravity IDE / Cursor / Cline / Continue / Copilot / Windsurf / Roo
├── CI
│   └── GitHub Action / Git hooks
└── Built-in Demo
    ├── sample diff
    ├── verified claim preview
    ├── lesson snippet
    └── quiz preview
```

Per-card usage panel:

1. show `usage_hint.quick_start_steps`;
2. show copyable target-specific prompts when present;
3. show `usage_hint.expected_behavior`;
4. show platform notes, especially Windows unsupported hooks and POSIX-only
   shell behavior;
5. auto-expand only the target that just succeeded after “Write guidance”.

Preserve existing install safety flow:

- preview first;
- install/uninstall with `confirmed_manifest_hash`;
- refresh targets after mutation;
- abort pending actions on unmount;
- do not write unsupported targets;
- do not move write/remove into Guide.

Post-install success behavior:

- show a short success status scoped to the current project;
- auto-expand the usage panel;
- move focus to the usage panel without trapping keyboard users;
- apply any highlight with `prefers-reduced-motion` respected.

Demo widget:

- calls `GET /api/demo/learn-preview`;
- caches result in component/session state so tab switching does not refetch;
- loading state is abortable;
- error state handles generic API/network failure only, because provider errors
  are out of scope;
- text fits narrow mobile widths and zh-CN strings.

### Phase 4: Guide Page Redesign

Owner: Antigravity through CCG. Backend blockers go to Codex.

Current state: `AgentSkillsSection` renders flat target cards plus two static
preview blocks.

Target state:

```text
Agent Skills
├── Category filters (All | CLI | IDE | CI)
├── Per-tool cards
│   ├── status + install command
│   ├── usage scenarios
│   └── generated/user-managed file actions
├── Common workflows
│   ├── Daily learning flow
│   ├── Before review / push
│   └── Improve lesson quality
└── Read-only file preview
```

Usage scenario cards show:

- context: when to use this scenario;
- in-tool prompt or command;
- terminal fallback command;
- expected AhaDiff output: verified claims, lesson, quiz, and optional
  concepts/review updates.

Example for Claude Code:

```text
Scenario: Learn your latest commit

In Claude Code:
  Use the ahadiff skill to learn my latest commit.

Terminal fallback:
  ahadiff learn HEAD~1..HEAD

Expected:
  AhaDiff generates a lesson with verified claims and quiz questions.
```

Interactive preview:

- use real `target.manifest` actions when available;
- fallback to static previews only when the API is unavailable;
- annotate generated files versus user-managed marked sections;
- keep Guide read-only.

### Phase 5: i18n, Platform, And Browser Hardening

Owner: Antigravity through CCG for frontend; Codex for backend locale behavior.

Use existing frontend namespaces:

- `Settings_page.integration_usage_*`
- `Settings_page.integration_demo_*`
- `Settings_page.integration_category_*`
- `Guide.agent_scenario_*`
- `Guide.agent_preview_*`
- existing `Guide.workflow_*` only where necessary
- existing `Skills.copy` and `Skills.copied`

Requirements:

- update `en.json` and `zh-CN.json` together;
- keep placeholders aligned;
- do not add a new `Common.*` namespace for this work;
- use `detectPlatform()` for PowerShell vs POSIX command display;
- use backend `platform_supported` for unsupported target actions;
- add Windows/macOS/Linux rendering tests with mocked platform detection;
- keep hooks visibly unsupported on Windows.

## Task Manifest For `ccg:team`

Use this manifest instead of re-planning from scratch.

```text
B1 Backend usage hints
  owner: Codex /codex:rescue --background
  write scope:
    src/ahadiff/contracts/serve_install.py
    src/ahadiff/install/usage_hints.py
    src/ahadiff/serve/routes_install.py
    tests/unit/test_routes_install.py
    tests/unit/test_install.py
  depends on: none
  parallel-safe with: none for same files; can run before frontend

B2 Backend deterministic demo
  owner: Codex /codex:rescue --background
  write scope:
    src/ahadiff/contracts/serve_demo.py
    src/ahadiff/serve/routes_demo.py
    src/ahadiff/serve/app.py
    src/ahadiff/demo/learn_preview.py optional
    tests/unit/test_routes_demo.py
    tests/unit/test_serve_app.py optional route-order assertion
  depends on: none
  forbidden:
    provider calls, token requirement, rate-limit changes, .ahadiff writes

F1 Frontend API/schema/i18n base
  owner: Antigravity through CCG
  write scope:
    viewer/src/api/config.ts
    viewer/src/api/schemas.ts
    viewer/src/api/demo.ts
    viewer/src/i18n/messages/en.json
    viewer/src/i18n/messages/zh-CN.json
    viewer/tests/unit/i18n-parity.test.ts only if needed
  depends on: B1/B2 contract shape

F2 Settings UI
  owner: Antigravity through CCG
  write scope:
    viewer/src/pages/SettingsPage.tsx
    viewer/src/components/UsagePanel.tsx optional
    viewer/src/components/UsagePanel.css optional
    viewer/src/components/DemoWidget.tsx optional
    viewer/src/components/DemoWidget.css optional
    viewer/src/components/Settings.css or existing Settings CSS files
    viewer/src/pages/__tests__/SettingsPage.test.tsx
  depends on: F1

F3 Guide UI
  owner: Antigravity through CCG
  write scope:
    viewer/src/pages/GuidePage.tsx
    viewer/src/pages/GuidePage.css
    viewer/src/components/ScenarioCard.tsx optional
    viewer/src/components/ScenarioCard.css optional
    viewer/src/pages/__tests__/GuidePage.test.tsx
  depends on: F1

V1 Browser/a11y/cross-platform verification
  owner: Antigravity through CCG
  write scope:
    viewer/tests/e2e/walkthrough.spec.ts
    viewer/tests/e2e/i18n.spec.ts
    viewer/tests/e2e/media-features.spec.ts
    viewer/tests/e2e/cross-browser.spec.ts
    viewer/tests/fixtures/serve-mock.ts
  depends on: F2/F3

R1 Review and fixes
  owner: Claude orchestrates; Codex and Antigravity execute fixes
  depends on: each phase
  required:
    /codex:adversarial-review --background
    fix Critical/High
    /codex:review --background
    browser实测 after viewer changes
```

## Sprint Order And Gates

### Sprint 0: Preflight

Owner: Claude main agent.

Read current truth before dispatch:

```bash
test -d llmdoc && sed -n '1,220p' llmdoc/index.md || true
test -d llmdoc/overview && rg --files llmdoc/overview || true
git status --short
rg -n "InstallTargetSummary|InstallTargetsResponse|InstallTargetPreviewResponse|InstallTargetMutationResponse" src/ahadiff/contracts src/ahadiff/serve tests viewer/src/api
rg -n "AgentSkillsSection|SKILL_PREVIEW|AGENTS_PREVIEW|IntegrationsTab|integration_" viewer/src viewer/tests
rg -n "chromium-desktop|firefox-desktop|webkit-desktop|forced-colors|reduced-motion|i18n" viewer/playwright.config.ts viewer/tests
```

Gate:

- no unreported dirty files in planned write scopes;
- `llmdoc/` absence or contents recorded;
- current target count and template count reconfirmed.

### Sprint 1: Backend Usage Hints

Owner: Codex.

Suggested handoff:

```text
/codex:rescue --background "Implement Sprint 1 of docs/plans/guidance-overhaul-plan.md. Use the installed default Codex model. Use Codex sub-agents/multi-agents where safe. Scope is backend usage hints only; do not touch viewer/. Keep InstallTargetSummary strict and update exact-key tests."
```

Validation:

```bash
UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run pytest tests/unit/test_routes_install.py tests/unit/test_install.py -q
UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run ruff check src/ahadiff/contracts/serve_install.py src/ahadiff/install/usage_hints.py src/ahadiff/serve/routes_install.py tests/unit/test_routes_install.py tests/unit/test_install.py
UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run ruff format --check src/ahadiff/contracts/serve_install.py src/ahadiff/install/usage_hints.py src/ahadiff/serve/routes_install.py tests/unit/test_routes_install.py tests/unit/test_install.py
UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run pyright src/ahadiff/contracts/serve_install.py src/ahadiff/install/usage_hints.py src/ahadiff/serve/routes_install.py tests/unit/test_routes_install.py tests/unit/test_install.py
```

Gate:

- all 15 targets have usage hints in en and zh-CN;
- list / preview / mutation target payloads include consistent `usage_hint`;
- exact-key tests updated intentionally;
- no frontend files touched.

### Sprint 2: Deterministic Demo API

Owner: Codex.

Suggested handoff:

```text
/codex:rescue --background "Implement Sprint 2 of docs/plans/guidance-overhaul-plan.md. Add GET /api/demo/learn-preview as deterministic built-in demo only. Do not call providers, do not require X-AhaDiff-Token, do not modify _RATE_LIMITS, and assert no .ahadiff writes."
```

Validation:

```bash
UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run pytest tests/unit/test_routes_demo.py tests/unit/test_serve_app.py -q
UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run ruff check src/ahadiff/contracts/serve_demo.py src/ahadiff/serve/routes_demo.py src/ahadiff/serve/app.py tests/unit/test_routes_demo.py tests/unit/test_serve_app.py
UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run ruff format --check src/ahadiff/contracts/serve_demo.py src/ahadiff/serve/routes_demo.py src/ahadiff/serve/app.py tests/unit/test_routes_demo.py tests/unit/test_serve_app.py
UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run pyright src/ahadiff/contracts/serve_demo.py src/ahadiff/serve/routes_demo.py src/ahadiff/serve/app.py tests/unit/test_routes_demo.py tests/unit/test_serve_app.py
```

Gate:

- endpoint is before catchall;
- endpoint returns localized deterministic data;
- no provider, cache, usage, audit, run, review, concept, graph, or ratchet writes;
- no middleware rate-limit change.

### Sprint 3: Frontend API, Settings, And i18n

Owner: Antigravity through CCG.

Required Antigravity prompt contents:

```text
Implement frontend Sprint 3 from docs/plans/guidance-overhaul-plan.md.
Use real Antigravity via CCG, not a Claude subagent named Antigravity.
Own viewer/ changes only. Cover Settings AI Tool Guidance category grouping,
usage panels, deterministic demo widget, i18n EN/ZH, platform rendering, and
tests. Do not modify backend Python. If backend API is insufficient, return a
blocker for Claude to route to Codex.
```

Validation:

```bash
pnpm --dir viewer typecheck
pnpm --dir viewer exec vitest run viewer/src/pages/__tests__/SettingsPage.test.tsx viewer/tests/unit/i18n-parity.test.ts viewer/tests/unit/client.test.ts
pnpm --dir viewer build
```

Targeted browser checks:

```bash
AHADIFF_VIEWER_E2E_PORT=5174 pnpm --dir viewer exec playwright test --project=chromium-desktop viewer/tests/e2e/walkthrough.spec.ts -g "Settings AI tool guidance"
AHADIFF_VIEWER_E2E_PORT=5174 pnpm --dir viewer exec playwright test --project=firefox-desktop viewer/tests/e2e/walkthrough.spec.ts -g "Settings AI tool guidance"
AHADIFF_VIEWER_E2E_PORT=5174 pnpm --dir viewer exec playwright test --project=webkit-desktop viewer/tests/e2e/walkthrough.spec.ts -g "Settings AI tool guidance"
```

Gate:

- Settings controls fit mobile and zh-CN text;
- demo fetch is abortable and does not call provider routes;
- unsupported hooks remain hidden/disabled on Windows;
- i18n parity passes.

### Sprint 4: Guide Redesign And Preview

Owner: Antigravity through CCG.

Required Antigravity prompt contents:

```text
Implement frontend Sprint 4 from docs/plans/guidance-overhaul-plan.md.
Own GuidePage and frontend tests only unless explicitly blocked. Replace the
flat AgentSkillsSection with category filters, scenarios, workflows, and
read-only target manifest preview. Keep Guide read-only; write/remove remains
in Settings.
```

Validation:

```bash
pnpm --dir viewer typecheck
pnpm --dir viewer exec vitest run viewer/src/pages/__tests__/GuidePage.test.tsx viewer/tests/unit/i18n-parity.test.ts
pnpm --dir viewer build
```

Targeted browser checks:

```bash
AHADIFF_VIEWER_E2E_PORT=5174 pnpm --dir viewer exec playwright test --project=chromium-desktop viewer/tests/e2e/walkthrough.spec.ts -g "Guide"
AHADIFF_VIEWER_E2E_PORT=5174 pnpm --dir viewer exec playwright test --project=firefox-desktop viewer/tests/e2e/walkthrough.spec.ts -g "Guide"
AHADIFF_VIEWER_E2E_PORT=5174 pnpm --dir viewer exec playwright test --project=webkit-desktop viewer/tests/e2e/walkthrough.spec.ts -g "Guide"
```

Gate:

- Guide has no write/remove mutation;
- fallback previews are only used when API data is unavailable;
- category filters work with keyboard and screen readers;
- EN/ZH text and long target names do not overflow.

### Sprint 5: Cross-Browser, Cross-Platform, Review

Owner: Claude orchestrates; Antigravity and Codex execute their scopes.

Full validation before final PASS:

```bash
UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run pytest tests/unit/test_routes_install.py tests/unit/test_install.py tests/unit/test_routes_demo.py tests/unit/test_serve_app.py -q
UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run ruff check src tests
UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run ruff format --check src tests
UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run pyright
pnpm --dir viewer typecheck
pnpm --dir viewer exec vitest run
pnpm --dir viewer build
AHADIFF_VIEWER_E2E_PORT=5174 pnpm --dir viewer exec playwright test
git diff --check HEAD
```

Review sequence:

```text
/codex:adversarial-review --background "Review the guidance overhaul implementation against docs/plans/guidance-overhaul-plan.md. Focus on provider-free demo safety, strict install target contracts, i18n parity, cross-browser behavior, Windows/macOS/Linux platform handling, and whether Claude/Antigravity/Codex ownership boundaries were respected."
/codex:status
/codex:result
/codex:review --background
/codex:status
/codex:result
```

Browser实测 requirements:

- Chromium desktop Settings and Guide;
- Firefox desktop Settings and Guide;
- WebKit desktop Settings and Guide;
- narrow/mobile viewport;
- forced-colors;
- reduced-motion;
- language switch EN -> zh-CN -> EN;
- Windows platform mock for PowerShell and hooks unsupported state;
- macOS/Linux platform mock for POSIX commands.

Final PASS requires:

- no unresolved Critical / High;
- all targeted backend checks pass;
- frontend typecheck, Vitest, build pass;
- Playwright full matrix passes or every non-product flake has a targeted green
  rerun and is documented;
- no provider-backed demo code path;
- no `.ahadiff/` writes from demo tests;
- no unreviewed same-file conflict between agents.

## File Change Map

### Backend

```text
src/ahadiff/contracts/serve_install.py
  Add strict ToolUsageHint and usage_hint field.

src/ahadiff/install/usage_hints.py
  New localized per-target usage hints for all 15 registry targets.

src/ahadiff/serve/routes_install.py
  Attach usage_hint with request_locale(request).

src/ahadiff/contracts/serve_demo.py
  New strict deterministic demo DTOs.

src/ahadiff/serve/routes_demo.py
  New GET /api/demo/learn-preview handler.

src/ahadiff/serve/app.py
  Import/register demo route before /api/{rest_of_path:path}.

src/ahadiff/demo/learn_preview.py
  Optional helper if keeping demo sample data outside route improves clarity.

tests/unit/test_routes_install.py
tests/unit/test_install.py
tests/unit/test_routes_demo.py
tests/unit/test_serve_app.py
  Contract, coverage, route-order, locale, no-write, and no-provider tests.
```

### Frontend

```text
viewer/src/api/config.ts
viewer/src/api/schemas.ts
viewer/src/api/demo.ts
  usage_hint types/schemas and demo API helper.

viewer/src/pages/SettingsPage.tsx
viewer/src/pages/GuidePage.tsx
viewer/src/components/UsagePanel.tsx optional
viewer/src/components/DemoWidget.tsx optional
viewer/src/components/ScenarioCard.tsx optional
viewer/src/**/*.css in existing relevant CSS files
  Settings and Guide UI implementation.

viewer/src/i18n/messages/en.json
viewer/src/i18n/messages/zh-CN.json
  Matching EN/ZH keys.

viewer/src/pages/__tests__/SettingsPage.test.tsx
viewer/src/pages/__tests__/GuidePage.test.tsx
viewer/tests/unit/i18n-parity.test.ts
viewer/tests/e2e/*.spec.ts targeted as needed
viewer/tests/fixtures/serve-mock.ts
  Unit, i18n, browser, and fixture updates.
```

## Risks And Mitigations

- **Provider/cost leakage from demo**: demo is deterministic and provider-free;
  provider-backed demo is out of scope.
- **Strict DTO breakage**: update Pydantic DTOs, exact-key tests, frontend
  TypeScript, and Zod in the same gate.
- **Preview/mutation inconsistency**: include `usage_hint` in every
  `InstallTargetSummary` payload.
- **Frontend diff too large**: split Settings and Guide into separate
  Antigravity tasks; shared components are optional and must stay focused.
- **i18n drift**: add EN/ZH keys together and run parity tests.
- **Windows/macOS/Linux regressions**: mock platform detection and keep hooks
  unsupported on Windows.
- **Cross-browser flake**: rerun failed target once on a clean port and record
  whether it is product failure or infrastructure flake.
- **Agent boundary violation**: Claude main stops the sprint if it or a generic
  Claude subagent starts editing code directly outside the documented fallback.
- **Documentation drift in `CLAUDE.md` / `AGENTS.md`**: do not opportunistically
  edit project docs in this implementation. Offer `使用 recorder agent 更新项目文档`
  after the code implementation is complete and verified.
