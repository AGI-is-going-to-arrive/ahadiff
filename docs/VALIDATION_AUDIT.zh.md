# AhaDiff 本轮验证审计

日期：2026-05-18

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
- 用户说明文档和媒体：已交付自包含 HTML，包含截图和 CSS 动图 demo；本轮 follow-up 已补中文和英文两个独立 Remotion 视频、对应旁白音频、ASR 回听文本、字幕源文件和烧录字幕 MP4。
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

这次提交包含上一轮 completion audit 的未提交代码，也包含本轮 provider / Guide / 视频文档 follow-up。下面只写当前 diff 能支撑的事实。

后端与配置：

- `src/ahadiff/cli.py`、`src/ahadiff/core/orchestrator.py`：`learn` / `improve` 解析 provider 时，会优先使用配置中的角色 provider；只有多个 provider 且没有可用默认时，才要求显式 `--provider`。单个 provider 会自动作为默认 provider，远端 provider 来自配置时也算用户显式配置，可在 `strict_local` 下通过已有安全检查进入远端调用。
- `src/ahadiff/core/config.py`：`providers.<alias>.available_models` 成为可持久化的动态字段，写回 TOML 时按字符串数组渲染。
- `src/ahadiff/serve/routes_providers.py`：保存 provider models 时去重，并以 tuple 写入配置，避免重载后丢失模型列表。
- `src/ahadiff/serve/routes_install.py`：`hooks` target 在 Windows 上明确标为 unsupported，避免把 POSIX hook 指令展示成可用 Windows 安装。

前端与接线：

- `viewer/src/pages/SettingsPage.tsx`：Provider tab 在单 provider 情况下也会展示可选模型；切换 provider 时保留仍有效的当前模型；保存时只提交实际变化的字段，避免单纯改 LLM limits 时误写默认模型。
- `viewer/src/pages/GuidePage.tsx`、`viewer/src/i18n/messages/*.json`：核心学习命令改回简单心智模型，`learn` / `improve` 不再在日常命令里要求 `--provider` / `--privacy-mode`；provider test 仍保留在设置命令里，作为一次性配置入口；PowerShell 环境变量写法和维护命令参数同步到真实 CLI。
- `viewer/src/pages/LandingPage.tsx`、`viewer/src/utils/platform.ts`、相关 E2E：Welcome/Guide 示例改为源码 checkout / `uv run` / `uv tool install --editable .` 口径，不再写成已发布 PyPI 的安装方式。

测试：

- 新增并已运行 provider 默认解析回归：`tests/unit/test_cli.py`、`tests/unit/test_orchestrator.py`、`tests/unit/test_routes_providers.py`。
- 新增并已运行前端 helper 回归：`viewer/src/pages/__tests__/SettingsPage.test.tsx`、`viewer/src/pages/__tests__/GuidePage.test.tsx`。
- 新增并已运行 install route Windows hooks 回归：`tests/unit/test_routes_install.py`。

文档和视频：

- `docs/USER_GUIDE.zh.html`：安装、provider 默认使用、PowerShell 示例、`serve --watch` 依赖和视频入口已同步。
- `docs/video/`：新增独立 Remotion 工程、中文/英文 clean MP4、烧录字幕 MP4、旁白音频、字幕源文件、ASR 输出和复现脚本。
- `docs/VALIDATION_AUDIT.zh.md`、`docs/video/README.md`、README / README.en / 项目文档：同步当前代码、真实测试结果和视频验证结果；ASR 中文一致性校验失败按失败记录，不写成通过。

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
- 视频入口已加入 `docs/USER_GUIDE.zh.html` hero 区域，分别指向中文视频 `docs/video/output/ahadiff-tutorial.zh.burned-subtitles.mp4` 和英文视频 `docs/video/output/ahadiff-tutorial.en.burned-subtitles.mp4`。
- 当前 `docs/USER_GUIDE.zh.html` SHA-256：`c47306ac0985124ee71d04eafcd5f3b2f9f9f8cee32f1936fcd7f5bc47d30407`。
- 上一轮浏览器打开后 console `0 errors, 0 warnings`；本轮更新安装、provider 和视频入口文案，未重跑浏览器视觉检查。
- 上一轮 390px 移动视口打开后无水平溢出，console `0 errors, 0 warnings`；本轮未重跑移动浏览器检查。
- 静态检查确认没有真实 key 和本机临时路径泄漏。

本轮补交 Remotion 视频：

- `docs/video/` 是独立 Remotion 工程，未复用或污染 `viewer/` 生产代码。
- 文案源：`docs/video/content/story.json`，分 `zh` / `en` 两套界面和旁白字段；中文 composition 只显示中文界面和中文字幕，英文 composition 只显示英文界面和英文字幕。
- 用户可看的成片是 `docs/video/output/ahadiff-tutorial.zh.burned-subtitles.mp4` 和 `docs/video/output/ahadiff-tutorial.en.burned-subtitles.mp4`；clean MP4 是无烧录字幕的渲染中间产物。
- `ffprobe` 显示中文最终 MP4 为 H.264 3840x2160 视频 + AAC 48 kHz stereo 音频，大小 `37,002,001` bytes，时长 `403.000000` 秒；英文最终 MP4 为 H.264 3840x2160 视频 + AAC 48 kHz stereo 音频，大小 `38,710,711` bytes，时长 `395.000000` 秒。
- 字幕源文件：`docs/video/output/subtitles/ahadiff-tutorial.zh.srt` / `.vtt` / `.json`，以及 `docs/video/output/subtitles/ahadiff-tutorial.en.srt` / `.vtt` / `.json`。
- `pnpm run typecheck` 通过。
- `pnpm run probe` 通过，确认两个 clean / burned MP4 均只有 H.264 视频轨和 AAC 音频轨，没有独立 subtitle stream；字幕区域像素差中文 `5.74087`、英文 `8.34139`。
- `pnpm run scan` 扫描 39 个文本文件，未发现真实 API key、本机绝对路径、临时路径或 localhost 端口泄漏。
- `node scripts/check-asr-similarity.mjs` 当前失败在中文 ASR：`dice=0.126`、`lengthRatio=0.027`。中文 ASR 输出是拒绝式说明，不是完整转写；英文按同一脚本逻辑单独计算为 `dice=0.923`、`lengthRatio=0.836`。因此本轮不能把 ASR 一致性写成通过，只能把 MP4 轨道、字幕烧录和敏感信息扫描作为视频产物证据。

### 后续一致性修正

- `docs/USER_GUIDE.zh.html` 已改为源码 checkout 安装口径，补 PowerShell provider 示例，并说明配置好的单 provider 或 Settings 选中的生成 provider/model 可直接供 `ahadiff learn` 使用。
- `viewer/src/pages/GuidePage.tsx` 的核心命令不再要求用户每次手写 `--provider gpt55 --privacy-mode explicit_remote`；这些参数仍保留在一次性 `provider test` 命令中。
- `docs/video/README.md` 已按当前 MP4 时长、大小、probe、scan 和 ASR 结果重写；中文 ASR 一致性失败已明确记录。
- 本轮追加验证：后端 provider/config/install 目标 `209 passed`，目标 ruff/format/pyright、wheel build、viewer 目标 Vitest `5 passed`、viewer 全量 Vitest `38 files, 370 tests passed`、viewer typecheck/lint/build、docs/video typecheck/probe/scan、`git diff --check HEAD`。
- 本轮还以 build viewer mode 启动本地 WebUI，并打开 Guide 供人工观察；Chrome/Playwright MCP 因已有 profile 占用未能接管该浏览器会话。
- 文档收口同步了 `README.md`、`README.en.md`、根 `CLAUDE.md`、`AGENTS.md`、`doc/contract-freeze.md`、`doc/FRONTEND_GAP_REPORT.md`、`doc/CLAUDE.md`、`docs/index.html` 和视频文档，口径只引用本文件已列出的代码事实和测试结果。
- 本轮验证留下的 `viewer/dist/`、`viewer/test-results/`、`viewer/playwright-report/` 都是 gitignored 产物，不会进入提交；未删除它们，因为删除目录需要明确确认。

## 发布前剩余门禁

1. 恢复 GitHub Actions billing / spending limit。
2. runner 恢复后，重新触发 Backend CI、Frontend CI、Windows Runtime Guard，确保远端 runner 验证的是已提交 diff。
3. 远端 runner 恢复后复核 CI 日志；本地通过不等于远端 CI 已闭合。
4. 若需要更强 Windows 证据，提供真实 Windows runner；Linux SQLite `3.51.3` 目标 gate 已本地闭合，完整 Linux CI 仍可在远端 runner 恢复后补跑。
5. 如果要把文档状态同步到其它项目文档体系，明确确认“使用 recorder agent 更新项目文档”。

当前提交边界：

- 待提交：provider 默认解析、Settings/Guide/Landing 接线、相关测试、用户指南、验证审计、视频工程和最终 MP4。
- 不纳入提交：`viewer/dist/`、`viewer/test-results/`、`viewer/playwright-report/`、`docs/video/node_modules/`、`.remotion/`、raw/per-scene audio 和 macOS metadata，它们都是 ignored 产物。
- 最终提交列表以本次 `git status --short` 和 staged diff 为准。

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
