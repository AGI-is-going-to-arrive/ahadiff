# AhaDiff 前端差距报告

> 更新日期：2026-05-09 | 基于当前代码、后端 API、前端源码和本 session 实测结果

## 审计范围

- 后端 `src/ahadiff/serve/app.py` 当前注册：59 个 concrete `/api/*` route + 1 个 `/api/{rest_of_path:path}` catchall，另有 `/healthz`
- 前端 `viewer/src/` 当前统计：13 页面；`components/` + `pages/` 下 42 个生产 TSX；29 个页面/组件 CSS；i18n `924/924`
- 最近已记录完整 gate：后端 unit `2055 passed`；integration `11 passed`；eval `9 passed`；`ruff check`、`ruff format --check`、`pyright`、wheel build 通过；前端 `pnpm typecheck`、`pnpm vitest run`（`227 passed`）和 `pnpm build` 通过；完整跨浏览器 Playwright `2000 passed, 10 skipped`；GPT-5.5 live LLM judge smoke `1 passed`；Graphify 10k benchmark gate OK（parse avg `172.399ms`、peak `42.435MiB`）。2026-05-09 follow-up 只重跑改动面：后端 path-scope `6 passed`，前端目标 Vitest `87 passed`，typecheck/build 通过，real-serve E2E `1 passed`；第二轮 install targets follow-up 又重跑 install route `19 passed`、install 写入层 `37 passed`、ruff/format/pyright、前端全量 Vitest `236 passed`、typecheck/build、Skills / Settings integrations / Deep links 目标 Playwright `75 passed`；第三轮 P1 read-only follow-up 重跑目标后端 route `18 passed`、后端全量 `2088 passed`、ruff/format/pyright、前端全量 Vitest `245 passed`、typecheck/build、P1 E2E 全矩阵 `390 passed`、移动目标 `52 passed`、Concepts/Ratchet axe-core `2 passed`。第三轮没有重跑 integration/eval/live judge/coverage，也没有执行真实 improve 写入

---

## 已闭合的 P0 / P1

| 项目 | 当前状态 | 代码依据 |
|---|---|---|
| SRS Easy 前端暴露 | v0.1 UI 只显示 Good / Hard / Wrong；Easy 仍保留在后端和类型层，供 CLI / 未来 UI 使用 | `SRSCard.tsx`, `ReviewPage.tsx`, `QuizPage.tsx`, `walkthrough.spec.ts` |
| Lesson scaffolding 自动推荐 | Lesson 会按 weak concepts / stability 自动推荐 full / hint / compact；空数据默认 compact | `LessonPage.tsx`, `LessonPage.test.tsx` |
| FSRS `desired_retention` | Settings 的 Preferences tab 可调 70%-99%；后端 config / serve runtime / review rate / signal review 都读取同一配置 | `SettingsPage.tsx`, `routes_config.py`, `config_runtime.py`, `routes_review.py`, `routes_signals.py` |
| TSV 导出 | Ratchet 页通过 `apiFetchBlob()` 下载 `/api/export/results?format=tsv`，token 走 header，不放 query string | `RatchetPage.tsx`, `api/runs.ts`, `api/client.ts` |
| ConceptGraph 完整图谱和大图降级 | 不再提供 cluster/group-by-kind；大图默认 List 但 Full graph 仍可打开；完整图谱不设硬边界，拖拽用 rAF 更新 SVG transform 并暂停 d3 simulation；节点文件路径展示会剥离本机 home/system 前缀 | `ConceptGraph.tsx`, `ConceptGraph.test.tsx` |
| Learn Mode Dialog | Topbar Learn Run 和 Dashboard 空态 CTA 都打开懒加载对话框；支持 10 种 capture mode、`/api/learn/estimate` preflight、force / Graphify / dry-run / lang / privacy 选项、working / unstaged / staged 的 path scope、patch 4096 bytes 前端上限、focus trap、Escape 和 body sibling inert；高级区会解释路径范围、其它来源和三个运行选项；输入高级来源会自动选中对应 mode；Dashboard 本地对话框打开时不会再被 `Ctrl/Cmd+K` 叠加 SearchOverlay | `AppShell.tsx`, `DashboardPage.tsx`, `Topbar.tsx`, `LearnModeDialog.tsx`, `learn-mode-dialog.test.ts`, `learn-task.spec.ts`, `cross-browser.spec.ts` |
| Task progress SSE | Learn task 现在优先订阅 `GET /api/tasks/{id}/progress`，收到终态后关闭 EventSource；SSE 失败或浏览器不支持时回退 polling | `viewer/src/api/tasks.ts`, `viewer/src/state/learn-store.ts`, `learn-store.test.ts`, `real-serve-contract.spec.ts` |
| PWA manifest | manifest 已有同源 `id` / `scope`、standalone display、SVG + 192/512 PNG icons；VitePWA build 继续生成 service worker；当前只声明 manifest/installability 覆盖，不把 offline shell 体验算作已验收 | `viewer/public/manifest.json`, `viewer/public/icons/`, `manifest.test.ts`, `vite.config.ts` |
| Install target WebUI 安全闭环 | Skills 页和 Settings Integrations 读取 `/api/install/targets` 返回的 install/uninstall command、manifest preview 和 `manifest_hash`；安装 / 卸载先 preview，再带 `confirmed_manifest_hash` + `X-AhaDiff-Token` 调受保护 POST；UI 有 pending/success/error，写后重新 detect；Settings 支持 `?tab=integrations` 深链 | `routes_install.py`, `serve_install.py`, `base.py`, `SkillsPage.tsx`, `SettingsPage.tsx`, `test_routes_install.py`, `test_install.py`, `walkthrough.spec.ts` |
| Concepts Ledger | Concepts 页现在是 Ledger / Graph 双 tab；Ledger 读取 `/api/concepts/ledger`，支持 cursor 分页、run chip 过滤、空态、load-more 和 `?tab=` / `?run=` / `?focus=` 同步；大图 Graph 仍保留原有降级策略 | `routes_runs.py`, `serve_concepts.py`, `ConceptsPage.tsx`, `ConceptLedger.tsx`, `concepts-store.ts`, `concepts-ledger.spec.ts` |
| Judge artifact browser | Run Detail 页现在是 Overview / Score / Judge / Artifacts 四 tab；Score 使用 8 维 meter 和 hard gates；Judge 读取 `/api/run/{id}/judge`，区分 404 和 malformed JSON，兼容 notes 字符串/数组，并保留 raw JSON toggle | `routes_runs.py`, `RunDetailPage.tsx`, `ScoreBreakdown.tsx`, `JudgeReport.tsx`, `run-detail.spec.ts` |
| Improve Preflight 只读入口 | Ratchet 第 5 tab 显示 Improve Preview，读取 `/api/improve/preflight`；后端只读检查 repo branch/head、prompt dirty、可用 anchor/baseline、provider 配置和 existing sessions；session JSON 读取拒绝 symlink/reparse/hardlink/过大文件，DB row 还必须有 finalized marker 才能当 anchor | `routes_improve.py`, `preflight.py`, `serve_improve.py`, `ImprovePreview.tsx`, `improve-preview.spec.ts`, `test_routes_improve.py` |
| Settings / Lesson / Skills / Review heading 与 aria | Settings provider/model 控件有角色化 aria-label；Lesson rail heading 降级为 h3；Onboarding/Skills/markdown heading outline 已按页面层级收口；Review 右栏 aside 有可访问 label | `SettingsPage.tsx`, `LessonPage.tsx`, `OnboardingPage.tsx`, `SkillsPage.tsx`, `ReviewPage.tsx`, `markdown.tsx`, `a11y.spec.ts` |
| Warning 颜色 / forced-colors / 触控目标 | warning token 改为可访问 fallback；Topbar / Ratchet tab 等触控目标和 forced-colors 已覆盖 | `tokens.css`, `Topbar.css`, `Ratchet.css`, `media-features.spec.ts` |
| CSP / z-index / print | `index.html` inline script 改 CSP hash；z-index 数字集中成 `--z-*` token；print 下 lesson rail 保持 block 并避免分页切断 | `index.html`, `tokens.css`, `AppShell.css`, `Topbar.css`, `SearchOverlay.css`, `print.css`, `media-features.spec.ts` |
| safe-area / 100dvh | Topbar safe-area、100dvh 已按当前实现验证 | `AppShell.css`, `Topbar.css`, `media-features.spec.ts` |
| 前端 CI | 新增 GitHub Actions workflow，前端 PR/push 跑 typecheck、Vitest、build 和 Chromium desktop smoke/a11y/cross-browser/learn-task Playwright 子集 | `.github/workflows/frontend-ci.yml` |

## API 覆盖现状

- 已展示或调用：`/api/export/results`、`/api/stats/learning`、`/api/review/heatmap`、`/api/search`、`/api/graph/status`、`/api/graph/concepts`、`/api/concepts/ledger`、`/api/run/{id}/judge`、`/api/improve/preflight`、provider / config / audit / usage / install targets（含 install/uninstall command、manifest preview/hash 和受保护 install/uninstall POST）。
- `GET /api/tasks/{id}/progress` 是 SSE 流；`viewer/src/api/tasks.ts` 已有 EventSource client，`learn-store` 使用 SSE 优先、polling fallback。
- `GET /healthz` 不属于 viewer 必须调用的产品 API。
- `GET /api/spec/alignment` 和 `GET /api/watch/status` 仍没有一等页面展示；前者适合后续放到 Dashboard / Ratchet，后者目前仍偏 internal status。
- `GET /api/concepts` 和 `GET /api/run/{run_id}/concepts` 后端仍存在；viewer 当前 Concepts Ledger 使用新的 `/api/concepts/ledger` 聚合视图，没有单独展示 run-local concepts artifact。

## 后端能力前端入口路线图

| 优先级 | 后端能力 | 推荐前端入口 | 边界 |
|---|---|---|---|
| P1 | Improve 写入 / targeted verify / Phase 2.5 | Ratchet 已有只读 Improve Preview；下一步才是“Improve this run”向导和显式确认写入 worktree | 当前 WebUI 只有 `GET /api/improve/preflight` 只读入口；真正改 prompt / worktree 的能力仍在 CLI：`ahadiff improve --suite local --rounds N`、`--resume`、`ahadiff db finalize-targeted <run_id>` |
| P1 | Watch 配置和状态 | Settings / Dashboard 增加 watch 状态、debounce/cooldown/force/dry-run/lang 配置说明，以及“如何启动 `serve --watch`”指引 | CLI 已有 `ahadiff watch` / `ahadiff serve --watch`；`/api/watch/status` 仍偏 internal，不承诺远程控制 |
| P2 | Benchmark / judge stability / CI verify | Ratchet 或 Settings 增加 benchmark status / last-run artifact viewer | 当前是 CLI：`ahadiff benchmark --suite local`；serve 还没有 benchmark report route，不把长 benchmark 直接塞进默认 Dashboard；per-run `judge.json` 已可在 Run Detail 查看 |
| P2 | Run-local concepts artifact | 如有必要，在 Run Detail 或 Concepts Ledger 增加 run-local concepts artifact 入口 | Concepts Ledger 已覆盖 repo-level 概念台账；`GET /api/run/{id}/concepts` 还没有独立页面入口 |
| P2 | Audit / usage / heatmap 查询参数 | Settings / Ratchet 增加分页、时间范围、字段筛选 | 先暴露最小筛选，避免把维护面变成复杂控制台 |

## 仍保留的产品差距

| 优先级 | 差距 | 当前判断 |
|---|---|---|
| P1 | Dashboard 仍不是完整四车道模型 | 当前已经有 runs / ratchet / stats / heatmap / learning 并做了失败隔离，但还不是 L3/L2/L1 lane 视图 |
| P1 | Lesson 仍不是完整三栏 reader | 已有 editorial 排版、claim 浮层和 scaffolding 推荐；TOC / prose / rail 的完整 V6 reader 还没完全落地 |
| P2 | Diff 仍没有虚拟列表 | 当前是文件折叠和 sticky header；超大 diff 虚拟滚动仍待做 |
| P2 | Benchmark / judge stability 仍没有报告页 | 单个 run 的 `judge.json` 已在 Run Detail 可看；benchmark status / judge stability 还没有完整报告页 |
| P2 | Landing 仍以样例内容为主 | 还没有接真实 benchmark / demo API |
| P2 | 搜索深链 claim 细粒度高亮仍有限 | `#/concepts?focus=...` 和 `#/review?card=...` 已消费；Diff / claim 深链仍主要依赖现有 claim lookup，不是完整跨页高亮系统 |

## 安全 / 可访问性

- `dangerouslySetInnerHTML`：当前关键渲染路径未使用；markdown 通过 JSX 构建。
- 焦点陷阱、inert、skip-to-content、aria-live、ErrorBoundary：当前实现仍成立。Learn Mode Dialog 会对 body sibling 设置 inert，并在关闭时恢复原值。
- forced-colors / reduced-motion / print / mobile media：2026-05-08 完整 Playwright 覆盖全浏览器/全视口矩阵；二次全量结果为 `2000 passed, 10 skipped`。先前一次 `firefox-mobile` forced-colors 单点失败未在 targeted rerun 和第二次完整矩阵中复现，未改生产样式。第三轮 P1 follow-up 没有重跑完整 walkthrough/media 矩阵，但重跑了 P1 三组 E2E 全项目矩阵 `390 passed`、指定移动项目 `52 passed`，并对 Concepts/Ratchet 跑了 axe-core 目标审计 `2 passed`。
- Diff claim 选中：walkthrough 仍走真实点击路径；为避免 WebKit 全量并行下偶发漏掉首次 click，测试只在未选中时重试点击，单用例和第二次完整矩阵均通过。
- 本次 follow-up 重跑了 LearnModeDialog / manifest / learn-store 目标 Vitest（`87 passed`）、typecheck/build、real-serve E2E（`1 passed`）和后端 path-scope 目标测试（`6 passed`）。第二轮集成页 follow-up 又重跑 install route `19 passed`、install 写入层 `37 passed`、ruff/format/pyright、前端全量 Vitest `236 passed`、typecheck/build、Skills / Settings integrations / Deep links 目标 Playwright `75 passed`。第三轮 P1 follow-up 重跑目标后端 route `18 passed`、后端全量 `2088 passed`、ruff/format/pyright、前端全量 Vitest `245 passed`、typecheck/build、P1 E2E 全矩阵 `390 passed`、移动目标 `52 passed`、Concepts/Ratchet axe-core `2 passed`。integration/eval/live judge/coverage 没有在第三轮重跑。
