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

Stage 0 / Task 0 到 Stage 6 主线现在都已经有实际产物，Stage 7 的 i18n signoff 也已通过。当前代码已经能稳定产出 Lesson / Claims / Quiz / Misconception Cards / Cards / Score / Ratchet；review 流的 SRS runtime、serve backend、install targets、GitHub Action 模板、benchmark suite、improve loop core、Task 17 targeted verification、Phase 2.5 runtime、i18n-0 后端以及前端 `viewer/` React SPA 都已落地。

本轮 v1.1 review-fix 跨后端 Python、`viewer/` 前端、测试、benchmark 和文档。后端收口 watch 自触发 learn 的工作区 diff 模式、provider model discovery 的 SSRF 加固且保留本地 provider discovery、URL embedded secret 的 OAuth query/fragment 覆盖、GraphProvenance 强校验，以及 concepts JSONL 导出的 symlink / reparse guard。前端收口 Dashboard LLM Calls / Weak Concepts、ConceptGraph 500+/1000+ 大图提示与 1000+ 二次确认、a11y heading / tab panel / nested-interactive 修复、accent contrast token、GraphifyCard V6 fidelity 和 Skills 焦点恢复；本次收尾又把 Dashboard KPI E2E 契约同步到 5 张卡，给 Diff claim 选中 E2E 加了真实点击重试，并新增前端 CI workflow。

上一轮 v1.1 review-fix 的真实验证：`UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run --frozen --no-sync pytest tests/unit -x -q` = `2055 passed`；`pytest tests/integration -q` = `11 passed`；`pytest tests/eval -q` = `9 passed`；`ruff check src tests`、`ruff format --check src tests`、`pyright` 通过；`uv build --wheel` 通过；`cd viewer && pnpm typecheck`、`pnpm vitest run`（`21 files, 227 tests passed`）和 `pnpm build` 通过；完整跨浏览器 Playwright = `2000 passed, 10 skipped`；`AHADIFF_LIVE_LLM_MODELS=gpt-5.5 pytest tests/live/test_llm_judge_live.py -q` = `1 passed`；Graphify 10k benchmark parse avg `172.399ms`、peak `42.435MiB`、gate OK。coverage 本轮未重跑。

2026-05-09 的 follow-up 把 path-scoped learn 补成真正的端到端能力：`ahadiff learn --changed-path`、watch 自触发 learn、`POST /api/learn` / `POST /api/learn/estimate` 和 Learn Mode Dialog 都会把路径范围传到 capture 层；capture 只允许它用于 staged / unstaged / working tree，并用 literal pathspec 处理 glob 字符。前端同时把任务进度改为 EventSource 优先、polling fallback，Learn Mode Dialog 的高级区补了路径范围、其它来源提示和三个运行选项说明；PWA manifest 也补上同源 `id` / `scope` 以及 192/512 PNG 图标。

本次 follow-up 的目标验证：后端 path-scope 回归 `6 passed`；`cd viewer && pnpm vitest run tests/unit/learn-mode-dialog.test.ts tests/unit/manifest.test.ts src/state/learn-store.test.ts` = `3 files, 87 tests passed`；`cd viewer && pnpm typecheck`、`pnpm build` 通过；`cd viewer && pnpm test:e2e:real-serve` = `1 passed`。完整后端单元、完整 Playwright、live judge 和 coverage 没有在这次 follow-up 里重跑。

同日第二轮集成页 follow-up 把工具集成从展示页补成受保护的 WebUI 写闭环：`GET /api/install/targets` 继续返回安装命令、卸载命令、manifest preview 和 `manifest_hash`；新增 `POST /api/install/{target}/preview`、`POST /api/install/{target}`、`POST /api/install/{target}/uninstall`，写操作只针对当前 serve repo，必须带 `confirmed_manifest_hash` 和 `X-AhaDiff-Token`，并沿用 Origin / Referer 写保护、localhost-only 边界和 repo 写锁。通用 install 写入层也补了 no-follow / regular-file / reparse / symlink parent guard。当前 Settings Integrations 负责预览、安装、卸载、显示 pending/success/error，并在写入后重新 detect；Guide 只展示使用命令和支持的集成目标，并深链到 Settings Integrations。Settings、Concepts、Review 的深链消费也已接通。

第二轮集成页 follow-up 的目标验证：`UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run --frozen --no-sync pytest tests/unit/test_routes_install.py -q` = `19 passed`；`UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run --frozen --no-sync pytest tests/unit/test_install.py -q` = `37 passed`；`ruff check src tests`、`ruff format --check src tests`、`pyright` 通过；`cd viewer && pnpm typecheck` 通过；`cd viewer && pnpm vitest run` = `22 files, 236 tests passed`；`cd viewer && pnpm build` 通过；`cd viewer && pnpm exec playwright test tests/e2e/walkthrough.spec.ts -g "Skills|Settings integrations|Deep links" --reporter=line` = `75 passed`。没有对当前真实 repo 执行 install / uninstall 写入；写入验证只在临时测试 repo 和浏览器 mock 中完成。完整后端单元、live judge 和 coverage 没有在这次集成页 follow-up 里重跑。

同日第三轮 P1 read-only follow-up 把三个浏览型能力补成产品面：Concepts 页新增 Ledger tab，读取 `GET /api/concepts/ledger`，支持 cursor 分页、run 过滤和 `?tab=` / `?run=` / `?focus=` 深链同步；Run Detail 页新增 Score / Judge / Artifacts tab，`GET /api/run/{id}/judge` 会读取 `judge.json`，JudgeReport 兼容字符串和数组 notes；Ratchet 页新增 Improve Preview tab，读取 `GET /api/improve/preflight`，只展示 repo state、可用 anchor/baseline、provider 状态、mutable prompts 和已有 session，不触发 worktree 写入。review-fix 又收口了 preflight 的 finalized marker 校验、session JSON symlink/reparse/hardlink/大文件 guard、untracked prompt dirty 检测、前端 hash 同步、run-filter race、Zod strict schema、窄屏换行和 accent 对比度。

第三轮 P1 follow-up 的真实验证：目标后端 route 测试 `18 passed`；完整后端 unit `2088 passed`；`ruff check src tests`、`ruff format --check src tests`、`pyright` 通过；`cd viewer && pnpm typecheck` 通过；`cd viewer && pnpm vitest run` = `23 files, 245 tests passed`；`cd viewer && pnpm build` 通过；P1 三组 E2E 全项目矩阵 `390 passed`；指定移动项目 `52 passed`；Concepts / Ratchet axe-core 目标审计 `2 passed`。本轮没有重跑 integration / eval / live judge / coverage，也没有执行真实 improve 写入。

2026-05-10 的 review follow-up 补的是本地诊断和浏览面收口：serve 新增受写 token 保护的 `POST /api/graph/refresh` 和 `POST /api/db/check`。前者在 repo 写锁内重新导入 Graphify artifact，并继续校验导入路径；后者用 read-only DB check 读取 schema、`quick_check`、event/card 计数，不会顺手初始化空库。Run Detail 增加 Concepts tab，只有 run 里有 `concepts.jsonl` 时才显示；`?tab=concepts` 打到无 concepts artifact 的 run 会回到 Overview。Concepts 页增加 Graph refresh 按钮，Onboarding 展示 DB check，Provider placeholder i18n、LearnModeDialog / RatchetChart a11y 和几处 container query / 599px 窄屏 CSS 也已同步。

05-10 的前端 review-fix 收口当日那组 viewer / CI 改动：`tokens.css` 补 13 个兼容别名和 `color-scheme: dark`；Ratchet / Diff / Topbar / Skills / ClaimInspector / Onboarding / LearnModeDialog / SearchOverlay / Settings 的暗色、container query fallback、forced-colors 和窄屏样式补齐；Dashboard 增加 stable concepts / last run KPI；Run Detail 增加 metadata 行和本地化 degraded flags；Settings 增加 audit 分页、竞态清理和 per-model usage 表；SearchOverlay 的 table filter chips 接到 `/api/search` 的 `tables` 参数，并补 ArrowLeft / ArrowRight / ArrowUp / ArrowDown / Home / End 键盘切换。前端 CI 也改成 Chromium desktop 全 11 specs，加 Firefox 和 WebKit desktop smoke/a11y。

本次 frontend review-fix 的真实验证：`cd viewer && pnpm typecheck` 通过；`cd viewer && pnpm vitest run` = `23 files, 245 tests passed`；`cd viewer && pnpm build` 通过；`cd viewer && pnpm exec playwright test tests/e2e/ --project=chromium-desktop --reporter=line` = `166 passed`；`cd viewer && pnpm exec playwright test tests/e2e/smoke.spec.ts tests/e2e/a11y.spec.ts --project=webkit-desktop --reporter=line` = `38 passed`；`cd viewer && pnpm exec playwright test tests/e2e/ --project=chromium-mobile --reporter=line` = `166 passed`；`UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run pytest tests/unit` = `2090 passed`；`ruff check src tests`、`ruff format --check src tests`、`pyright src/ahadiff` 通过；i18n parity `EN:969 zh-CN:969 match:True`；`git diff --check` 通过。integration / eval / live judge / coverage / wheel 没有在这次重跑，也没有执行真实 improve 写入。

本次兼容性和 route 覆盖 follow-up 基于当前未提交代码继续收口：Backend PR CI 现在把 `tests/eval` 纳入 PR 跑法；frontend CI 安装 Chromium / Firefox / WebKit，继续跑 Chromium desktop 全 E2E 和 Firefox smoke/a11y，并新增 WebKit smoke/a11y。Viewer 侧把 `formatBytes` / `formatCompactNumber` 收到 `viewer/src/utils/format.ts`，LearnTaskBanner 和 ProviderCard 会按当前 locale 显示 byte / token，旧 Intl runtime 不支持 compact notation 时会回退到 K/M/B；ConceptGraph 会先读取初始 SVG 宽度，再在有 `ResizeObserver` 时订阅 resize；LearnTaskBanner 的 `color-mix()` gradient 前面补了纯色 fallback；Topbar 按平台显示 `⌘K` 或 `Ctrl+K`；Settings 和 Diff 的 clipboard 写入在浏览器 API 不可用时直接跳过。后端 route 测试补到 review、signals、tasks、DB check、search 和 `/api/concepts/weak` 的鉴权、空库、schema、有效 payload 和无效 payload 场景。

本次 compatibility follow-up 的真实验证：`UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run --frozen --no-sync pytest tests/unit -q` = `2130 passed`；`UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run --frozen --no-sync ruff check src tests` 通过；`UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run --frozen --no-sync ruff format --check src tests` = `248 files already formatted`；`UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run --frozen --no-sync pyright src` = `0 errors, 0 warnings, 0 informations`；`cd viewer && pnpm typecheck` 通过；`cd viewer && pnpm vitest run` = `24 files, 250 tests passed`；`cd viewer && pnpm vite build` 通过；i18n parity `969/969`；`cd viewer && pnpm exec playwright test tests/e2e/a11y.spec.ts --project=chromium-desktop --reporter=line` = `17 passed`；`cd viewer && pnpm exec playwright test tests/e2e/smoke.spec.ts --project=chromium-desktop --reporter=line` = `21 passed`；真实浏览器覆盖 Dashboard、Settings Provider/Integrations、Diff anchor、Concepts Graph、Topbar、Learn、Review、Search 和 375px 窄屏，10 个场景通过；`git diff --check` 通过。integration / eval / live judge / coverage / wheel 和 GitHub Actions 远端 workflow 没有在这次重跑。

本轮 error / locale / i18n hardening follow-up 把 API 错误面收成稳定的 27 个 `ErrorCode` 和 `{error_code,error,status,details?}` payload，`AUTH_REQUIRED` 继续对应 401，loopback / write-origin 拒绝继续对应 403；serve 的 run/artifact 读取改用 per-request locale，`PUT /api/locale` 会持久化到 `.ahadiff/config.toml`；claim extraction 和 lesson/quiz 一样会收到解析后的 `output_lang`；git 相关路径统一通过 `shutil.which("git")` 找可执行文件，缺 git 时给清楚错误，hooks 调用有 timeout，并且只裁掉 CR/LF，不再破坏带空格路径；生成的 verify workflow 加入 Windows matrix，Linux-only SQLite 构建有 `runner.os == 'Linux'` guard，Windows 只跑 CLI load smoke；前端通过 `ApiError.errorCode`、`errors.*` 和 `Format.*` 做错误和 byte/token 展示本地化。

本轮 follow-up 的真实验证：目标后端回归 `455 passed`；完整后端 unit `2136 passed`；`ruff check src tests`、`ruff format --check src tests`、`pyright` 通过；`cd viewer && pnpm vitest run` = `253 passed`；`pnpm typecheck`、`pnpm build` 通过；i18n scalar keys `1011/1011`，`errors.*` 覆盖 `27/27` 个 error code，`Format.*` 覆盖 6 个格式化文案；`git diff --check` 通过。integration / eval / live judge / coverage / wheel / Playwright 和 GitHub Actions 远端 workflow 没有在这次重跑，也没有执行真实 improve 写入。

本次 Skills → Guide follow-up 把旧 Skills 页替换成更轻的 Guide 页：`/#/guide` 展示日常学习工作流、核心命令、设置命令、进阶/维护命令和 13 个支持的集成目标；`/#/skills` 现在会 replace 到 `/#/guide`。Guide 不导入 install API，也不执行安装/卸载；实际 preview / install / uninstall 仍在 Settings → Integrations 里完成。Onboarding 的命令块抽成共享 `CommandBlock`，复制按钮有本地化 label、clipboard API 优先和 `execCommand('copy')` fallback，fallback textarea 会在异常路径清理。Onboarding 示例也按平台拆成 POSIX / PowerShell 写法，并只使用占位符 API key。本次真实验证：Guide 目标 Playwright `7 passed`；`cd viewer && pnpm vitest run` = `253 passed`；`pnpm typecheck`、`pnpm build` 通过；Guide keys 全部被使用；旧 Skills 残留只剩 `/skills` redirect 测试；Guide/Onboarding/CommandBlock 未发现真实 key、endpoint 或本机绝对路径示例；`git diff --check` 通过。后端、integration、eval、live judge、coverage、wheel、完整 Playwright 和 GitHub Actions 远端 workflow 没有在本次重跑。

2026-05-11 的 Onboarding / Guide QA follow-up 只改前端学习入口和测试：新增 `DiagnosticRow` 组件，把 doctor / DB check 行的状态图标、`sr-only` 文案和 `aria-live="polite"` 收到一个地方；Onboarding 重排 stepper、doctor、DB check、预览和 CTA，补上 HashRouter 下的锚点滚动、reduced-motion、forced-colors、414px 窄屏和 renderToStaticMarkup 断言；Sidebar 的 SYSTEM 顺序保持 Welcome → Get Started → Guide → Settings；Guide 的维护命令默认展示 `--dry-run`；light mode focus ring 改回可见 token 组合；WebKit 下 Dashboard run link 的 E2E 等待改成点击后断言 URL，避免把 hash SPA 的 load 等待误当成产品失败。

本次 QA follow-up 的真实验证：后端完整 unit `2136 passed`；`ruff format --check src tests`、`ruff check src tests`、`pyright`、`uv build --wheel`、`python -m ahadiff --version` 和 `ahadiff doctor` 通过；`cd viewer && pnpm install --frozen-lockfile`、`pnpm typecheck`、`pnpm lint`、`pnpm vitest run` = `25 files, 268 tests passed`、`pnpm build` 和完整 Playwright = `2630 passed, 10 skipped` 通过；i18n scalar keys `1090/1090`，`errors.*` 覆盖 `27/27` 个 error code，`Format.*` 覆盖 6 个格式化文案；Vite preview 与 `ahadiff serve` 的 `/`、`/healthz` 本机 smoke 没有安全 console error/warning；`git diff --check` 通过。integration / eval / live judge / coverage 和远端 GitHub Actions 没有在本次重跑。

本次 viewer review-fix 只改前端学习面和测试：Learn Mode Dialog 的输出语言默认跟随当前 viewer locale，仍可在高级区改为 auto / en / zh-CN；Review 页面恢复 Again / Hard / Good / Easy 四档评分，键盘 `1`-`4` 同步可用，并补上高风险概念 chip、遗忘曲线说明和 mastery warning / danger 色阶；Quiz 页面补 Prev / Mark wrong / Next 导航、Guided / Recall / Transfer mode chips、progress table 和 mark-wrong idempotency，Quiz 内的 SRSCard 仍保留 Good / Hard / Wrong 与 peek guard。相关 CSS 同步 4 列/移动 2x2、触控目标、hover shadow、reduced-motion、forced-colors 和全局 `sr-only`。当前 `viewer/src` 是 13 页面、47 个生产 TSX、40 个 CSS，i18n scalar keys 为 `1101/1101`。

本次 viewer review-fix 的真实验证：`cd viewer && pnpm typecheck` 通过；`cd viewer && pnpm vitest run` = `25 files, 269 tests passed`；`cd viewer && pnpm build` 通过；`cd viewer && pnpm exec playwright test --reporter=line` = `2630 passed, 10 skipped`；`git diff --check` 通过。Playwright 输出里只有 `NO_COLOR` / `FORCE_COLOR` 环境变量提示，命令退出码为 0。后端、integration、eval、live judge、coverage、wheel 和远端 GitHub Actions 没有在本次重跑。

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

LOOP：编辑 → commit → 评估 → 高分 keep / 低分 reset → 写入 `review.sqlite`（唯一真相源，`results.tsv` 为导出视图）。

## 快速开始

下面命令对应当前 CLI。源码 checkout 中可以用 `uv run ahadiff ...`；安装为 wheel / pipx 后直接用 `ahadiff ...`。

```bash
pipx install ahadiff

# 初始化当前 repo 的 .ahadiff/
ahadiff init
ahadiff doctor
ahadiff config show --resolved

# 学习最近一次 commit
ahadiff learn --last

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
ahadiff serve --watch

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

ahadiff learn --last --provider gpt55 --model gpt-5.5 --privacy-mode explicit_remote
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

WebUI 里的 Settings → Integrations 复用同一组 target，并且只通过受保护的 serve API 写入。浏览器会先预览 manifest 并拿到 hash，安装 / 卸载时必须把这个 hash 作为 `confirmed_manifest_hash` 带回，同时带本地写 token。接口只写启动 `ahadiff serve` 的当前 repo，不接受浏览器传入任意 repo 路径。Guide 页只做使用说明和入口跳转，不直接调用 install API。

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
├─ src/ahadiff/graphify/        # 当前分支 Graphify 后端：models/parser/matcher/linker/slicer/search/freshness + concepts/FTS 接线
├─ src/ahadiff/eval/            # Stage 3 / Task 11-12 evaluator + ratchet + results + 可选 LLM judge
├─ src/ahadiff/serve/           # Task 14.5 + v0.2 本地 serve API（含 search/audit/usage/mastery/learning/tasks）
├─ src/ahadiff/install/         # Task 19/20 install targets + hooks no-follow + GitHub Action 模板
├─ src/ahadiff/i18n/            # i18n-0 locale resolver / prompt language helper
├─ src/ahadiff/review/          # Task 15 + v0.2 review.sqlite schema / FSRS-6 / migration chain
├─ src/ahadiff/prompts/         # wheel 内打包的 prompt 资源（含 eval_judge.md）
├─ prompts/                     # Lesson / claim / quiz / eval judge prompt 模板
├─ src/ahadiff/improve/         # Stage 5 / Task 16/17 improve loop、targeted verify、Phase 2.5
├─ benchmarks/                  # Task 18 本地 benchmark fixtures + manifest + scripts + results
├─ tests/unit/                  # Stage 0–6 与 i18n-0 单元测试
├─ tests/eval/                  # benchmark suite 测试
├─ tests/integration/           # pinned integration fixtures
├─ tests/live/                  # 需要显式环境变量开启的真实 LLM judge smoke
├─ viewer/                      # React 19 + Vite + Zustand + vanilla CSS 前端（13 页面 / 47 个生产 TSX / 40 个 CSS / 1101 i18n scalar keys / v1.1 gate: Vitest 227 passed + 全量 Playwright 2000 passed / 10 skipped；05-09 follow-up: 目标 Vitest 87 passed + real-serve E2E 1 passed；集成页 follow-up: Vitest 236 passed + 目标 Playwright 75 passed；P1 follow-up: Vitest 245 passed + P1 E2E 390 passed；05-10 frontend review-fix: 后端 unit 2090 + Vitest 245 + Chromium desktop E2E 166 + WebKit smoke/a11y 38 + Chromium mobile E2E 166；compatibility follow-up: 后端 unit 2130 + Vitest 250 + Chromium smoke 21 + Chromium a11y 17；error/locale follow-up: 后端 unit 2136 + Vitest 253 + error i18n 27/27；Guide follow-up: 目标 Playwright 7 passed + Vitest 253 + typecheck/build；05-11 Onboarding/Guide QA: Vitest 268 + 完整 Playwright 2630 passed / 10 skipped；05-11 viewer review-fix: Vitest 269 + 完整 Playwright 2630 passed / 10 skipped）
├─ ui/                          # HTML 原型 v1–v6（设计迭代史）
└─ CLAUDE.md                    # 项目 AI 上下文索引
```

## 当前阶段

**Stage 0 / Task 0、Stage 1 的 Task 1/2、Layer 1.5 的 Task 7、Stage 2 / Task 5/6/8、Stage 3 / Task 8.5/9/10/11/12、Stage 4 / Task 15、Stage 5 / Task 16/17、Stage 6 / Task 18/19/20，以及 i18n-0 后端已落地。** 当前代码除了设计文档和 HTML 原型，还已经有：

- `ahadiff learn` 的主链路：支持 git / `--patch` / `--compare` capture，经过 learnability gate 后生成 `claims.raw.jsonl -> claims.jsonl`、`lesson.full|hint|compact.md`、`misconception.md`、`not_proven.md`；工作区输入还支持 repeatable `--changed-path`，只学习指定 repo-relative 路径
- `ahadiff quiz`：对已生成的 `quiz.jsonl` 做最小交互式答题，并回显 source_claims / file:line evidence
- quiz artifact 链路：会写 `quiz.jsonl` 和 `misconception_cards.jsonl`；评分通过的 run 会生成 `cards.jsonl` 并回填 `review_card_id`，没有 `review_card_id` 的 open-answer 行在 viewer 里也仍然可以正常显示；git 输入写 repo 级 `concepts.jsonl`，non-git 输入写 run 级 `concepts_local.jsonl`
- `ahadiff score` / `ahadiff verify` / `ahadiff export-results`：评分、ratchet 判定和 `results.tsv` 导出都已可用
- `ahadiff review` / `ahadiff mark <claim_id> wrong` / `ahadiff db {backup,restore,check,import-results,finalize-targeted}`：`review.sqlite` 的 review / signals / result_events / lossy import / targeted finalize 链路都已可用
- `ahadiff serve`：localhost-only serve backend 已可用，读接口只暴露 finalized runs，写接口需要 token + Origin/Referer 校验；`/api/auth/token` 需要同源浏览器信号，继续兼容 GET，并支持 POST bootstrap。API 错误响应现在统一为 `{error_code,error,status,details?}`；token 缺失或无效返回 `401/AUTH_REQUIRED`，loopback / write-origin 拒绝仍返回 `403/LOOPBACK_DENIED`。当前 route 面是 61 个 concrete `/api/*` route + 1 个 `/api/{rest_of_path:path}` catchall，另有 `/healthz`。`POST /api/learn` 有 in-memory 10 req/min 滑动窗口限流，429 会带 `retry_after` / `Retry-After`；`POST /api/learn` 和 `POST /api/learn/estimate` 都支持 `changed_paths` 工作区路径范围；Concepts Ledger、Run Detail Judge/Concepts、Improve Preflight 已有只读路由；`POST /api/graph/refresh` 会在 repo 写锁内重新导入 Graphify artifact 并校验导入路径；`POST /api/db/check` 会用 read-only DB check 返回 schema/quick_check/event/card 计数，不初始化空库；install targets 现在有 `GET /api/install/targets`、preview、install、uninstall 四类路由，写入必须带 token 和 confirmed manifest hash，且只针对当前 serve repo；`/api/tasks*` 已提升为 stable product API，前端现在优先消费 `/api/tasks/{id}/progress` SSE，失败时回退 polling；`/api/watch/status` 仍为 internal/unstable。`GET/PUT /api/config` 现在包含 `learnability_threshold` 和 `desired_retention`，serve runtime 会按当前 workspace 读取 config。
- `ahadiff install` / `ahadiff uninstall`：13 个 target 已可用（Aider / Claude / Cline / Codex / Continue / Copilot / Cursor / Gemini / GitHub Action / hooks / OpenCode / Roo / Windsurf）；真实写入路径见上方 install target 清单。hooks 是 POSIX shell target，Windows v0.1 会明确拒绝；对已有 hook 文件会做 no-follow regular-file 校验，拒绝 symlink / reparse point；通用写入层也会拒绝 reparse / symlink parent 这类不安全路径；hooks 和 repo git 调用会通过 `shutil.which("git")` 找可执行文件，缺 git 时给出明确错误，hook 辅助调用有 bounded timeout，并保留路径里的合法空格；生成的 verify workflow 覆盖 macOS / Linux / Windows，Linux SQLite 构建只在 Linux runner 上跑，Windows 只跑 `ahadiff --version` CLI load smoke，`verify --ci` 仍只在非 Windows runner 上执行；generate workflow 使用 `AHADIFF_PROVIDER_API_KEY`，并上传 `.ahadiff/` 产物 artifact。WebUI 的 Settings Integrations 复用同一份 install target contract，先预览 manifest，再用 hash + token 确认 install / uninstall，不接受浏览器传入任意 repo 路径；Guide 页只展示命令和集成入口
- `ahadiff benchmark`：本地 benchmark manifest、20 个 eval fixtures、11 个 pinned integration fixtures 与 `ground_truth.md` 一致性校验已可用；第 11 个 fixture 是 graph-present smoke fixture，覆盖 Graphify-style `graph.json` 纳入 suite digest、真实 parser 解析，以及 fixture materialization 产出 `graphify_context.json` / `artifact_set.json`。生产路径的 per-run Graphify context 由 `test_git_capture.py` 覆盖；这里不声称等同真实大型 Graphify export
- 仓库当前还补上了 repo 级 Backend CI / `nightly-eval` / `release` workflows：PR 跑 unit + pinned integration（`ubuntu py311/py312 + macOS py312`），并有独立 Windows runtime guard；当前 PR CI 又把 `tests/eval` 加进同一条 Python gate；release gate 现在还会阻塞 `doctor`、wheel install smoke 和 coverage `>= 85%`。本轮另补 `.github/workflows/frontend-ci.yml`：前端 PR/push 跑 `pnpm typecheck`、`pnpm vitest run`、`pnpm build`，Chromium desktop 跑完整 11 个 E2E specs，并额外跑 Firefox 和 WebKit desktop smoke/a11y。同时 `pyproject.toml` 已带 `watchdog` / `tree-sitter` optional extras 与 `pytest-cov` dev dependency；`ahadiff watch`、`serve --watch` 和 `/api/watch/status` 已落地，其中 `/api/watch/status` 仍为 internal/unstable。`tree-sitter` 也不再只是 optional wiring：runtime consumer 已接到 symbol extraction 层，当前支持 JS/TS/TSX + Go + Java + Rust + PHP + Ruby + C#；Python 仍优先走 AST，其他未接入语言仍回退到 regex / section header，下游 lesson / quiz / claims 逻辑未改
- Phase 0 相关收口已经补到当前分支：contracts 权威口径、`safe_sqlite_connect` SQLite 连接 helper、reparse/hardlink 防护、serve CORS 与 `X-Frame-Options` 安全头、CLI 冷启动和本地 baseline 脚本都有对应实现
- i18n-0：locale resolver 支持 cookie / Accept-Language / `AHADIFF_LANG` / CLI / config / `LANG` fallback；serve 的 run/artifact 读取按 request 解析 locale，`PUT /api/locale` 会同步持久化到 `.ahadiff/config.toml`；claim extraction、lesson 和 quiz prompt payload 都会带输出语言指令
- `ahadiff improve --suite local --rounds N`：目前仅支持 `--suite local`。它从已有 finalized run 中选择 baseline，在 git worktree 里只改白名单 prompt，重放同一 diff 并重新评分；候选必须让目标维度 + `accuracy` + `evidence` + `safety_privacy` 的合计分高于 baseline，且 hard gates 通过，才会尝试 cherry-pick prompt commit 回主分支，并记录 `event_type=improve` / `status=targeted_verify`；未提升则记录 `discard`，cherry-pick 冲突则保留 pending worktree 且不 finalized；同一 session 连续两次 `discard` 会触发一次 Phase 2.5 worktree rewrite
- `src/ahadiff/eval/{rubric,gates,deterministic,evaluator,results,ratchet}.py`：8 维评分、hard gates、结果写入、ratchet 选择和导出视图
- `src/ahadiff/review/{database,scheduler,schemas,signal}.py`：review.sqlite schema / migration、FSRS-6 调度、review queue、learning signal 和 review CLI 后端
- `src/ahadiff/improve/{loop,program,targeted,rewrite}.py`：improve session、immutable improve_program、worktree 隔离、5 个 mutable prompt 白名单、replay-learn、targeted verification、Phase 2.5 触发、cherry-pick 顺序、session 校验与 pending worktree resume guard
- source checkout 与 wheel 安装态的 runtime 资源定位：`eval_bundle_version`、`prompt_version`、lesson prompt 加载都已经接到包内资源
- `keep_final` 仍通过全 8 维 recheck 后的 `ahadiff db finalize-targeted <event_id>` 手动收口，不在 improve loop 内自动升级。前端 `viewer/` React SPA 继续保持 13 页面；当前学习面已收口到更接近实际使用：Review 页面显示 Again / Hard / Good / Easy 四档评分并支持 `1`-`4` 快捷键，Quiz 的 SRSCard 仍保留 Good / Hard / Wrong 与 peek guard，但已有 Prev / Mark wrong / Next 导航、mode chips 和 progress table；Topbar 的 Learn Run 会打开 Learn Mode Dialog，默认输出语言跟随当前 viewer locale，也可选择 10 种 capture mode 并走 preflight 确认，working / unstaged / staged 模式可填写每行一个路径的 Path scope；Dashboard 空态也可以直接打开同一个 Learn Mode Dialog；Lesson 会根据 weak concepts / stability 推荐 compact / hint / full；Settings 是 7-tab（Account / Provider / Capture / Privacy / Audit / Preferences / Integrations），Preferences 合并语言、外观、`learnability_threshold` 和 `desired_retention`，Provider/Capture/Integrations 等 `?tab=` 深链可初始化并切换，Provider tab 的生成/评判 provider 与 model 控件有独立 aria-label，Integrations tab 支持 preview/install/uninstall、复制命令、查看 manifest 写入路径和写后重新 detect；Guide 页替代旧 Skills 页，展示工作流、常用命令、维护命令和支持的集成目标，维护命令默认展示 `--dry-run`，`/#/skills` 会 replace 到 `/#/guide`；Review 会消费 `?card=`，并展示高风险概念、遗忘曲线说明和 mastery 色阶；Concepts 是 Ledger / Graph 双 tab，会消费 `?focus=`、`?run=` 和 `?tab=`，Graph tab 可以刷新 Graphify import；Ratchet 可用 token-header blob 下载 `results.tsv`，也有只读 Improve Preview tab；Run Detail 页展示 Overview / Score / Judge / Concepts / Artifacts 五个 tab，其中 Concepts 只在 run 有 `concepts.jsonl` 时出现；Onboarding 会单独展示 DB check，doctor 和 DB check 互不遮挡，并通过 `DiagnosticRow` 给状态图标、`sr-only` 文案和 `aria-live` 做统一处理；Onboarding 和 Guide 共享 `CommandBlock` 复制组件；ConceptGraph 现在只有 Graph / List 两种视图，大图默认 List 但仍可打开完整图谱，完整图谱支持不设硬边界的拖拽和缩放，节点文件路径展示会剥离本机 home/system 前缀；Dashboard 对 runs / ratchet / stats / heatmap / learning 使用 `Promise.allSettled`，学习效果接口失败不会拖垮主页面；长任务进度现在走 SSE 优先、polling fallback。

本轮又收口了几件容易出错的运行时边界：`prompt_version` 只描述 AhaDiff 自己的 prompt 资源，不再受目标工作区 `prompts/` 影响；lesson JSON 解析会跳过不匹配 schema 的示例块，claims / quiz / misconception cards / LLM judge 也会在 provider envelope、fenced JSON、JSONL、示例块和部分截断 JSON 之间选择能通过 schema 的真实答案；lesson/quiz 目录改成生成后再接到主链，失败时会回滚；如果 lesson 生成阶段失败，会清掉新写出的 `claims.raw.jsonl` / `claims.jsonl`、`quiz/` 和 `concepts_local.jsonl` 半成品；`learn` 成功后会写入 `event_type=learn` 的评分事件和 `score.json`，配置 `judge_provider` 时还会把 LLM judge 的 8 维结果写入 `judge.json`，manual `score` / `verify` 不再污染 learn 的 ratchet baseline；`ReviewCard` 现在会校验 `last_rating` 范围和 `card_state/stale_reason` 组合；伪造 quiz 也不会再误拿 `PASS`。后续又把 pinned integration 里的 `cards.jsonl` fixture 收回真实生成路径：测试先写 `symbols.json`，再用 `generate_cards_for_run()` 生成 cards，并逐行校验 `ReviewCard` schema，避免手写半截 cards 绕过生产契约。Task 15 这轮也已经补齐：旧版 `cards` schema 会显式迁移 `stale_reason`，schema-invalid `cards.jsonl` 会降级成 warning，重复 regenerate 不会把旧 active 卡留在 due queue 里；`regenerate --only quiz` 在 `evaluate_run` 失败时会恢复旧 quiz/cards，在 `FAIL` 时会删掉陈旧 `cards.jsonl` 并把该 run 的 active 卡标成 `stale + staleness_unknown`；lossy TSV import 现在走单连接整批导入，坏行或 duplicate identity 会整批回滚；`rollback_result_event` 也改成同一连接里完成 delete + export rows，普通 DB connect 不会再因为路径 typo 静默建目录。Task 16/17 这轮补上了 `lesson_hint.md` 白名单、session_id 路径校验、30 分钟 replay timeout、双 prompt temp+replace 写入、非冲突 cherry-pick 失败区分、discard/pending conflict 不写 `finalized.json`、pending conflict 不作为下一轮 baseline、volatile staged/unstaged 输入从保存的 `patch.diff` 重放、短 worktree 路径、`--rounds` 上限 20、null byte 拒绝、Ctrl+C 在已完成 round 后不再追加第二条 crash event、targeted verification、Phase 2.5 单次触发，以及 OpenAI-compatible provider endpoint 归一化。这次又把 LLM cache key 的版本边界补齐：同一 `api_family` 下不同 `api_family_version` 会生成不同 cache key，避免兼容网关或 API 版本变化时误复用旧结果。

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

真实 LLM judge smoke 需要显式开启，默认模型顺序是 `gpt-5.3-codex-spark,gpt-5.4-mini`，每个模型都会先试 OpenAI Responses，再试 Chat Completions；如需 GPT-5.5，请像快速开始里那样显式设置 `AHADIFF_LIVE_LLM_MODELS`：

```bash
AHADIFF_LIVE_LLM_JUDGE=1 \
AHADIFF_LIVE_LLM_API_KEY="$AHADIFF_LIVE_LLM_API_KEY" \
AHADIFF_LIVE_LLM_BASE_URL="$AHADIFF_LIVE_LLM_BASE_URL" \
AHADIFF_LIVE_LLM_MODELS="gpt-5.3-codex-spark,gpt-5.4-mini" \
pytest tests/live/test_llm_judge_live.py -q
```

上一轮完整 gate（2026-05-08）：`UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run --frozen --no-sync pytest tests/unit -x -q` = `2055 passed`；`UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run --frozen --no-sync pytest tests/integration -q` = `11 passed`；`UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run --frozen --no-sync pytest tests/eval -q` = `9 passed`；`UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run --frozen --no-sync ruff check src tests` 通过；`UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run --frozen --no-sync ruff format --check src tests` 通过；`UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run --frozen --no-sync pyright` = `0 errors`；`UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv build --wheel` 通过；`cd viewer && pnpm typecheck` 通过；`cd viewer && pnpm vitest run` = `21 files, 227 tests passed`；`cd viewer && pnpm build` 通过；`cd viewer && pnpm exec playwright test --reporter=line` = `2000 passed, 10 skipped`；`AHADIFF_LIVE_LLM_MODELS=gpt-5.5 ... pytest tests/live/test_llm_judge_live.py -q` = `1 passed`；Graphify 10k benchmark gate OK（parse avg `172.399ms`、peak `42.435MiB`）。coverage 本轮未重跑。

本次 follow-up（2026-05-09）只重跑改动面：后端 path-scope 目标回归 `6 passed`；前端 Learn Mode Dialog / manifest / learn-store 目标 Vitest `87 passed`；`pnpm typecheck`、`pnpm build` 通过；real-serve Playwright 合同测试 `1 passed`。第二轮集成页 follow-up 又重跑 `test_routes_install.py = 19 passed`、`test_install.py = 37 passed`、`ruff check src tests`、`ruff format --check src tests`、`pyright`、前端全量 Vitest `236 passed`、`pnpm typecheck`、`pnpm build` 和 Skills / Settings integrations / Deep links 目标 Playwright `75 passed`。第三轮 P1 read-only follow-up 重跑目标后端 route 测试 `18 passed`、完整后端 unit `2088 passed`、ruff/format/pyright、前端全量 Vitest `245 passed`、typecheck/build、P1 三组 E2E 全项目矩阵 `390 passed`、指定移动项目 `52 passed`、Concepts/Ratchet axe-core 目标审计 `2 passed`。2026-05-10 review follow-up 重跑 DB check 目标后端 `2 passed`、完整后端 unit `2090 passed`、ruff/format/pyright、viewer typecheck、前端全量 Vitest `245 passed`、viewer build、Run Detail + media 目标 Playwright `500 passed, 10 skipped`、指定 walkthrough/smoke/a11y/cross-browser/learn-task/media E2E `1760 passed, 10 skipped` 和 `git diff --check`。2026-05-10 frontend review-fix 又重跑 viewer typecheck、前端全量 Vitest `245 passed`、viewer build、Chromium desktop 全 E2E `166 passed`、WebKit desktop smoke/a11y `38 passed`、Chromium mobile 全 E2E `166 passed`、后端 unit `2090 passed`、ruff/format/pyright、i18n parity `969/969` 和 `git diff --check`。compatibility follow-up 重跑后端 unit `2130 passed`、ruff/format/pyright、viewer typecheck、前端 Vitest `250 passed`、viewer build、i18n `969/969`、Chromium desktop smoke `21 passed`、Chromium desktop a11y `17 passed`、10 个真实浏览器场景和 `git diff --check`。本轮 error / locale / i18n hardening follow-up 又重跑目标后端 `455 passed`、完整后端 unit `2136 passed`、ruff/format/pyright、viewer typecheck、前端 Vitest `253 passed`、viewer build、i18n scalar keys `1011/1011`、`errors.* 27/27`、`Format.* 6/6` 和 `git diff --check`。本次 Guide follow-up 重跑 Guide 目标 Playwright `7 passed`、前端 Vitest `253 passed`、viewer typecheck、viewer build、Guide/i18n/secret 静态检查和 `git diff --check`。2026-05-11 Onboarding / Guide QA follow-up 重跑后端 unit `2136 passed`、ruff/format/pyright、wheel、version、doctor、前端 Vitest `268 passed`、typecheck/lint/build、完整 Playwright `2630 passed, 10 skipped`、i18n `1090/1090`、Vite preview 和 `ahadiff serve` 本机 smoke、`git diff --check`。本次 viewer review-fix 重跑 `cd viewer && pnpm typecheck`、`pnpm vitest run = 25 files, 269 tests passed`、`pnpm build`、完整 Playwright `2630 passed, 10 skipped`、i18n `1101/1101` 和 `git diff --check`；后端、integration、eval、live judge、coverage、wheel 和远端 GitHub Actions workflow 未在本轮重跑；没有执行真实 improve 写入。

下一步路线图：

- [ ] `v0.1`（MVP）：CLI + Lesson + Evaluator + Ratchet 全链路 + React 19 WebUI（`ahadiff serve`）+ 8 种 LLM Provider（OpenAI Chat/Responses/Gemini/Anthropic/Azure/NewAPI/LMStudio/Ollama）+ 8 种 diff 捕获（含 --unstaged / git show）+ 13 个 install target + i18n + 阶段门禁
- [ ] `v0.2`：--compare-dir + --patch-url + 7 个 IDE install target + watchdog 增量重生 + section-level helpfulness + Team 功能（已完成：后端 Gate 0-6 + medium APIs + helpfulness / learning transfer + misconception cards + Graphify 后端基础与 concept linking / FTS / provenance / perf gate + watch mode + path-scoped learn + graph refresh API + DB check API + 13 install targets + install target WebUI 安全闭环 + provider/model settings + Learn Mode Dialog + `/api/learn` rate limit + DNS pinning + LLM judge + 当前前端学习面收口：三档 SRS UI、自动 scaffolding、retention 设置、Ratchet TSV、ConceptGraph Graph/List 视图与不设硬边界的完整图谱交互、Concepts Ledger、Run Detail judge artifact browser、Run Detail concepts artifact、Ratchet Improve Preview、Dashboard learning metric 隔离和空态 Learn CTA、Guide 使用指南页、三档侧栏、Diff 大文件渲染预算、Dashboard source filter、container query hardening、Settings/Lesson/Guide/Review heading 与 aria 收口、Settings/Concepts/Review 深链消费、CSP hash / z-index token / favicon / runtime status / queue-state / signals / idempotency fallback 硬化；待做：Team / 真实 large-repo signoff evidence / 更深的 V6 frontend signoff）
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
