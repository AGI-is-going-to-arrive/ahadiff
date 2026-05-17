# AhaDiff 本轮验证审计

日期：2026-05-17

## 结论

本轮已经完成大范围本机审查、修复、真实 CLI/WebUI/LLM 验证和用户指南交付。

不能标记为“发布级全部完成”的原因有两点：

- GitHub Actions 在推送后已触发 Backend CI、Frontend CI 和 Pages runs，但 jobs 立即 failure，steps 为空且日志不存在；这不计为远端代码验证通过。此前 annotation 指向 billing / spending limit。
- “没有任何显性隐性 bug”无法被严格证明；当前只能说明本轮覆盖范围内未发现剩余阻断问题。

## 目标到证据映射

### Completion audit

当前不能调用 goal complete。逐项核对如下：

- 全方位 code review / 实测：已完成本机后端、前端、real-serve、CLI、GPT-5.5 live 和 Linux 目标容器测试；缺远端 CI 覆盖当前未提交 diff。
- corner case / 显性隐性 bug：已修复本轮发现的 API 同源、provider schema、changed-path、Graphify/compare guard、SQLite race 等问题；但“无任何隐性 bug”不可被测试严格证明。
- Windows / macOS / Linux：macOS 本机完整；Linux SQLite 3.51.3 目标容器测试和 `doctor` gate 已通过；Windows 只有静态/模拟 guard 和 workflow 配置，缺真实 Windows runner。
- i18n：已完成 key parity、错误/格式键和浏览器语言路径验证。
- CLI 命令实测：已覆盖 help、临时 repo 行为矩阵、live provider / learn 和破坏性命令的 dry-run 或临时 repo 路径。
- 前后端接线 / feature 状态：已覆盖 real-serve、Settings/Guide/API schemas、task progress、auth/token 和核心页面；完整远端 runner 未闭合。
- GPT-5.5 live：已用已配置 provider 跑 live judge、provider test 和 live learn；不是全仓库无限制 LLM 生成。
- 用户说明文档和媒体：已交付自包含 HTML，包含截图和 CSS 动图 demo；未用 Remotion 生成独立视频，因为当前交付没有 Remotion 项目依赖，且 HTML 内嵌 demo 更直接。
- recorder 文档同步：未执行；需要用户明确确认“使用 recorder agent 更新项目文档”。

### 全方位多维 code review 和实际测试

已覆盖：

- 后端完整 unit：`2530 passed`
- 后端 integration/eval：`20 passed`
- `ruff check src tests`
- `ruff format --check src tests`
- `pyright`
- wheel build
- 前端 `pnpm typecheck`
- 前端 `pnpm lint`
- 前端 Vitest：`365 passed`
- 前端 build
- 完整 Playwright：`2945 passed, 10 skipped`
- real-serve Playwright：`2 passed`

限制：

- 测试覆盖不能数学证明零 bug。
- 远端 CI 没有实际执行 steps，不能作为跨平台绿灯。

### 本轮修改清单

后端与安全：

- `src/ahadiff/cli.py`：校准 Challenge CLI 文案。
- `src/ahadiff/core/sqlite_util.py`：Linux SQLite nofollow fd 绑定、主库路径校验和失败打开路径身份校验。
- `src/ahadiff/git/capture.py`：diff capture 输入边界加固。
- `src/ahadiff/llm/provider.py`：provider schema / model discovery 加固。
- `src/ahadiff/serve/routes_learn.py`：learn route 输入校验和 estimate / submit 接线加固。

前端与接线：

- `viewer/src/api/client.ts`：同源绝对 URL token/API 请求，避免 `<base href>` 干扰。
- `viewer/src/api/providers.ts`、`viewer/src/api/schemas.ts`、`viewer/src/api/tasks.ts`、`viewer/src/api/types.ts`：API schema / task / provider 类型收口。
- `viewer/src/pages/GuidePage.tsx`：Guide provider 命令补齐 `base-url`、model、key env 和 privacy mode。
- `viewer/playwright.real-serve.config.ts`：real-serve E2E 改为 Playwright `webServer.env`。

测试：

- `tests/unit/test_core_utils.py`：SQLite race / symlink / reparse 目标覆盖。
- `tests/unit/test_git_capture.py`、`tests/unit/test_routes_learn.py`、`tests/unit/test_security_hardening.py`：capture、learn route、安全输入边界回归。
- `viewer/src/api/__tests__/providers-schema.test.ts`、`viewer/src/api/__tests__/tasks-schema.test.ts`、`viewer/tests/e2e/auth.spec.ts`、`viewer/tests/unit/client.test.ts`：前端 API schema、task schema、auth/base-href 和 token bootstrap 回归。

文档：

- `docs/USER_GUIDE.zh.html`：自包含中文用户指南、7 张截图、CSS 动图 demo、功能状态和验证口径。
- `docs/VALIDATION_AUDIT.zh.md`：本轮 completion audit、证据矩阵、阻断项和复跑命令。

### corner case / 安全边界

已覆盖：

- changed paths 拒绝 `..`、绝对路径、Windows drive / UNC、控制字符和 `.git` / `.ahadiff` 内部路径。
- compare input / Graphify input 增加 symlink、reparse、hardlink、大小和 TOCTOU guard。
- SQLite 连接层在 Linux 上通过 `/proc/self/fd/<fd>` 绑定预打开的 nofollow fd，并在成功或失败打开路径上校验主库路径与叶子身份，覆盖已有 DB 和新建 DB 的 rename / symlink race。
- provider URL SSRF 判定收紧为 `not addr.is_global`。
- viewer API client 使用绝对同源 URL，避免 `<base href>` 影响 token/API 请求。
- API error redaction、bootstrap timeout、401/403 refresh coalescing 均有测试覆盖。

### Windows / macOS / Linux

本机实际环境：

- macOS 26.5 arm64
- SQLite 3.51.0

已覆盖：

- 本机 macOS 全套测试。
- Docker Linux `python:3.12-slim` smoke：源码可安装，目标跨平台 / reparse / SQLite race 单测 `45 passed, 1 skipped`，`python -m ahadiff --version` 输出 `1.1.0a0`；该轻量镜像 SQLite 为 `3.46.1`，所以只算兼容性 smoke。
- Docker Linux `node:22-bookworm` + 自编译 SQLite `3.51.3` gate：目标跨平台 / reparse / SQLite race 单测 `45 passed, 1 skipped`，`python -m ahadiff doctor --repo-root .` 显示 `SQLite gate: compatible with the frozen contract`。
- Windows guard 单测和跨平台静态测试。
- CI workflow 配置包含 Ubuntu、macOS 和 Windows Runtime Guard。
- real-serve Playwright 配置从 POSIX-only env 前缀改为 Playwright `webServer.env`。

未闭合：

- 原生 aarch64 `python:3.12-slim` 自编译 SQLite `3.51.3` 路径在 `apt-get install build-essential` 阶段曾被 Docker 以 exit `137` 杀掉；已改用已有 `node:22-bookworm` 镜像绕过 apt 安装并完成 SQLite `3.51.3` 目标 gate。
- `colima` / `orbctl` / `podman` / `lima` / `act` 不存在。
- GitHub Actions jobs 立即 failure：Backend CI / Frontend CI / Pages runs 的 jobs 均为 `steps: []`，`gh run view --log-failed` 返回 `log not found`；之前 annotation 显示 billing / spending limit 阻断。
- 远端 run 指向对应推送 commit，但没有实际执行 steps/logs；runner 恢复后仍需重新跑。

### i18n 正确性

已覆盖：

- i18n scalar key parity。
- `errors.*` / `Format.*` 覆盖。
- 浏览器 E2E 覆盖语言切换、cookie 持久化和多页面本地化。

### 所有 CLI 命令实测

已覆盖：

- 29 个 top-level help 均 code 0。
- 21 个 nested help 均 code 0。
- 临时 repo 实测 `init`、`doctor`、`config show`、`install --detect`、`provider test`、`learn`、`verify`、`score`、`claims`、`quiz`、`review`、`db check`、`concepts list/verify`、`graph status`、`export-results`。
- 额外 CLI 行为矩阵实测 `db backup/restore/import-results/finalize-targeted`、`export preview`、`graph import/status/refresh`、`concepts lint/export/sync/rollback`、`challenge build/status`、`install/uninstall codex`、`install github-action --dry-run --layer2`、`mark`、`unlock`、`mcp-server initialize`、`watch --dry-run`、`benchmark`。

限制：

- 破坏性命令只在临时 repo 中运行，未触碰真实项目状态。

### 前后端全面接线

已覆盖：

- 完整 Playwright 覆盖前端页面和 mock API。
- real-serve E2E 启动临时 git repo 和真实 `python -m ahadiff serve`，浏览器实测 token、estimate、learn dry-run、task status 和 progress stream。
- `USER_GUIDE.zh.html` 截图来自当前 Viewer 页面。

限制：

- real-serve 不是逐个 `/api/*` route 的完整真实后端矩阵。

### feature 是否全部打开

当前事实：

- Lesson / Claims / Quiz / Score / WebUI / Dashboard / Diff / Review 是主链能力。
- GPT-5.5 需要 provider 配置。
- Challenge 默认关闭，需要 `[challenge] enabled = true`。
- APKG 需要 `ahadiff[anki]`。
- Watch 依赖 watchdog。
- Graphify refresh 依赖 Graphify CLI 或已有缓存。
- README 当前 roadmap 仍把 Team、stable APKG namespace GUID、真实 large-repo signoff evidence 和更细前端视觉 polish 标为 remaining。
- contract-freeze 明确 APKG GUID 仍是 `genanki.guid_for(card_id)`，stable namespace GUID 未落地，不能写成已完成。

结论：

- 不能说“所有 feature 默认全开”。
- 应说“主链默认可用，部分能力是 opt-in 或依赖 extra/tool”。

### GPT-5.5 live LLM

已覆盖：

- `tests/live/test_llm_judge_live.py` 使用真实 provider，不是 mock。
- 本轮 live judge：`2 passed`。
- 临时 repo 使用已配置 GPT-5.5 跑通 provider test 和 live `learn`。

限制：

- live judge 使用合成 fixture。
- 没有对整个当前大型仓库执行无限制 full live generation。

### 前端模板 / 合并 / 重构

已覆盖：

- 当前生产路由覆盖 Dashboard、Welcome、Run Detail、Lesson、Diff、Quiz、Review、Concepts、Ratchet、Settings、Onboarding、Guide、Challenge、404。
- 本轮确认旧 `/skills` 已 redirect 到 `/guide`。
- Settings 的 AI 工具指引和 Guide 职责已分清。
- README / viewer audit 仍记录 finer frontend visual polish、real large-repo signoff evidence、richer graph provenance/count placement 这类非阻断 polish / signoff gap。

限制：

- 没有单独生成“历史 HTML 模板 parity manifest”。
- 不能说“前端没有任何剩余 polish 或 signoff 工作”；只能说当前核心学习面和生产路由已实现并通过本轮验证。

### 用户说明文档和媒体

已交付：

- `docs/USER_GUIDE.zh.html`
- 单文件自包含中文指南。
- 内嵌 7 张当前 Viewer 截图。
- 内嵌 CSS 工作流动图 demo。
- 当前 `docs/USER_GUIDE.zh.html` SHA-256：`c279503981c7ddf3894702135a860e164ac1c72807c1a9c4127f2aeb8f8f2086`。
- 浏览器打开后 console `0 errors, 0 warnings`。
- 390px 移动视口打开后无水平溢出，console `0 errors, 0 warnings`。
- 静态检查确认没有真实 key 和本机临时路径泄漏。

### 后续一致性修正

- `docs/USER_GUIDE.zh.html` 的 FAQ provider 排障命令已补齐 `--provider-class openai_responses`，与快速配置段一致。
- `viewer/src/pages/GuidePage.tsx` 的 Guide provider 命令已同步补齐 `--provider-class openai_responses`，并把示例 provider 名称统一为 `gpt55`。
- 新增 `viewer/tests/e2e/smoke.spec.ts` 断言，确保 Guide 页面继续展示 `--provider-class openai_responses`。
- 追加验证：`pnpm typecheck`、`pnpm lint`、`pnpm vitest run`（`36 files, 365 tests passed`）、`pnpm build`、`pnpm exec playwright test tests/e2e/smoke.spec.ts -g "hash router guide route renders workflow section and command blocks" --project=chromium-desktop`、`git diff --check HEAD` 均通过。
- 本审计文档的后端复跑命令改为通过 `tempfile.gettempdir()` 派生 `UV_CACHE_DIR`，避免写入硬编码本机临时路径；重新扫描 `USER_GUIDE.zh.html` 和 `VALIDATION_AUDIT.zh.md` 后，没有真实 key、本机路径或 localhost 端口泄漏。
- 更新后的 `USER_GUIDE.zh.html` 已通过本地浏览器复核：2 个 provider block 都含 `--provider-class openai_responses`，内嵌 JPEG 截图仍为 7 张，CSS `@keyframes flow` 存在，390px 视口无页面水平溢出，console 无 error/warning。
- 本轮文档收口又同步了 `README.md`、`README.en.md`、根 `CLAUDE.md`、`AGENTS.md`、`doc/contract-freeze.md`、`doc/FRONTEND_GAP_REPORT.md` 和 `doc/CLAUDE.md`，口径只引用本文件已列出的代码事实和测试结果。
- 本轮验证留下的 `viewer/dist/`、`viewer/test-results/`、`viewer/playwright-report/` 都是 gitignored 产物，不会进入提交；未删除它们，因为删除目录需要明确确认。

## 发布前剩余门禁

1. 恢复 GitHub Actions billing / spending limit。
2. runner 恢复后，重新触发 Backend CI、Frontend CI、Windows Runtime Guard，确保远端 runner 验证的是已提交 diff。
3. 远端 runner 恢复后复核 CI 日志；本地通过不等于远端 CI 已闭合。
4. 若需要更强 Windows 证据，提供真实 Windows runner；Linux SQLite `3.51.3` 目标 gate 已本地闭合，完整 Linux CI 仍可在远端 runner 恢复后补跑。
5. 如果要把文档状态同步到其它项目文档体系，明确确认“使用 recorder agent 更新项目文档”。

当前提交边界：

- 代码、安全、前端测试、用户指南和验证审计已纳入本轮提交。
- 推送后发现的远端 CI no-steps/no-logs 事实，只需要文档 follow-up 同步。
- 不纳入提交：`viewer/dist/`、`viewer/test-results/`、`viewer/playwright-report/`，它们是 gitignored 验证产物。
- 早前已执行 `git add --dry-run` 覆盖当时 23 个提交候选文件；文档收口后最终提交列表以本次提交的 staged diff 为准。

## 复跑命令

本机后端 gate：

```bash
export UV_CACHE_DIR="$(python3 -c 'import pathlib, tempfile; print(pathlib.Path(tempfile.gettempdir()) / "ahadiff-uv-cache")')"
uv run --frozen --no-sync pytest tests/unit -q
uv run --frozen --no-sync pytest tests/integration tests/eval -q
uv run --frozen --no-sync ruff check src tests
uv run --frozen --no-sync ruff format --check src tests
uv run --frozen --no-sync pyright
uv build --wheel
```

本机前端 gate：

```bash
cd viewer
pnpm typecheck
pnpm lint
pnpm vitest run
pnpm build
pnpm exec playwright test
```

Linux SQLite `3.51.3` 目标 gate：使用已有 `node:22-bookworm` 镜像自编译 SQLite，避免 `python:3.12-slim` 安装 build-essential 时的 Docker `137`。

```bash
docker run --rm -v "$PWD":/src:ro node:22-bookworm bash -lc '
set -euo pipefail
export SQLITE_AUTOCONF_VERSION=3510300
build_dir=/sqlite-build
mkdir -p "$build_dir"
curl -fsSLo "$build_dir/sqlite.tar.gz" "https://www.sqlite.org/2026/sqlite-autoconf-${SQLITE_AUTOCONF_VERSION}.tar.gz"
tar -xzf "$build_dir/sqlite.tar.gz" -C "$build_dir"
cd "$build_dir/sqlite-autoconf-${SQLITE_AUTOCONF_VERSION}"
./configure --prefix="$build_dir/sqlite" --disable-static >"$build_dir/sqlite-configure.log"
make -j1 >"$build_dir/sqlite-make.log"
make install >"$build_dir/sqlite-install.log"
export LD_LIBRARY_PATH="$build_dir/sqlite/lib:${LD_LIBRARY_PATH:-}"
curl -LsSf https://astral.sh/uv/install.sh | sh >"$build_dir/uv-install.log"
export PATH="$HOME/.local/bin:$PATH"
cp -a /src /work
cd /work
uv sync --locked --dev --python python3 >"$build_dir/uv-sync.log"
uv run pytest tests/unit/test_cross_platform_static.py tests/unit/test_windows_reparse_guards.py tests/unit/test_core_utils.py::TestSafeSqliteConnect tests/unit/test_stage1_task1.py::test_workspace_identity_key_casefolds_on_windows tests/unit/test_stage1_task1.py::test_repo_write_lock_rejects_windows_reparse_point tests/unit/test_stage1_task1.py::test_unlock_repo_write_lock_rejects_windows_reparse_point -q --tb=short
uv run python -m ahadiff doctor --repo-root .
'
```

远端 CI 恢复后：

```bash
gh run list --limit 5 --json databaseId,workflowName,status,conclusion,headSha,url
gh run view <run-id> --json jobs,conclusion,headSha,url
```
