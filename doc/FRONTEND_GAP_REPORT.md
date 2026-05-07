# AhaDiff 前端差距报告

> 更新日期：2026-05-08 | 基于当前代码、后端 API、前端源码和本 session 实测结果

## 审计范围

- 后端 `src/ahadiff/serve/app.py` 当前注册：53 个 concrete `/api/*` route + 1 个 `/api/{rest_of_path:path}` catchall，另有 `/healthz`
- 前端 `viewer/src/` 当前统计：12 页面；`components/` + `pages/` 下 36 个生产 TSX；23 个页面/组件 CSS；i18n `731/731`
- 本轮真实验证：ConceptGraph 目标 Vitest `3 passed`；前端 Vitest `198 passed`；typecheck / build 通过；Concepts Playwright chromium `2 passed`；`git diff --check` 通过。后端 unit、完整 Playwright 和真实 LLM judge smoke 本轮未因图谱改动重跑

---

## 已闭合的 P0 / P1

| 项目 | 当前状态 | 代码依据 |
|---|---|---|
| SRS Easy 前端暴露 | v0.1 UI 只显示 Good / Hard / Wrong；Easy 仍保留在后端和类型层，供 CLI / 未来 UI 使用 | `SRSCard.tsx`, `ReviewPage.tsx`, `QuizPage.tsx`, `walkthrough.spec.ts` |
| Lesson scaffolding 自动推荐 | Lesson 会按 weak concepts / stability 自动推荐 full / hint / compact；空数据默认 compact | `LessonPage.tsx`, `LessonPage.test.tsx` |
| FSRS `desired_retention` | Settings 的 Preferences tab 可调 70%-99%；后端 config / serve runtime / review rate / signal review 都读取同一配置 | `SettingsPage.tsx`, `routes_config.py`, `config_runtime.py`, `routes_review.py`, `routes_signals.py` |
| TSV 导出 | Ratchet 页通过 `apiFetchBlob()` 下载 `/api/export/results?format=tsv`，token 走 header，不放 query string | `RatchetPage.tsx`, `api/runs.ts`, `api/client.ts` |
| ConceptGraph 完整图谱和大图降级 | 不再提供 cluster/group-by-kind；大图默认 List 但 Full graph 仍可打开；完整图谱不设硬边界，拖拽用 rAF 更新 SVG transform 并暂停 d3 simulation | `ConceptGraph.tsx`, `ConceptGraph.test.tsx` |
| Warning 颜色 / forced-colors / 触控目标 | warning token 改为可访问 fallback；Topbar / Ratchet tab 等触控目标和 forced-colors 已覆盖 | `tokens.css`, `Topbar.css`, `Ratchet.css`, `media-features.spec.ts` |
| safe-area / 100dvh / z-index | Topbar safe-area、100dvh、popover/backdrop z-index 已按当前实现验证 | `AppShell.css`, `Topbar.css`, `ClaimInspector.css`, `media-features.spec.ts` |

## API 覆盖现状

- 已展示或调用：`/api/export/results`、`/api/stats/learning`、`/api/review/heatmap`、`/api/search`、`/api/graph/status`、`/api/graph/concepts`、provider / config / audit / usage / install targets。
- `GET /api/tasks/{id}/progress` 是 SSE 流；当前前端仍用 polling，这是有意选择。
- `GET /healthz` 不属于 viewer 必须调用的产品 API。
- `GET /api/spec/alignment` 和 `GET /api/watch/status` 仍没有一等页面展示；前者适合后续放到 Dashboard / Ratchet，后者目前仍偏 internal status。

## 仍保留的产品差距

| 优先级 | 差距 | 当前判断 |
|---|---|---|
| P1 | Dashboard 仍不是完整四车道模型 | 当前已经有 runs / ratchet / stats / heatmap / learning 并做了失败隔离，但还不是 L3/L2/L1 lane 视图 |
| P1 | Lesson 仍不是完整三栏 reader | 已有 editorial 排版、claim 浮层和 scaffolding 推荐；TOC / prose / rail 的完整 V6 reader 还没完全落地 |
| P2 | Diff 仍没有虚拟列表 | 当前是文件折叠和 sticky header；超大 diff 虚拟滚动仍待做 |
| P2 | `judge.json` 仍不是独立详情面板 | Ratchet 已有 Judge notes tab 文案和 score 读取链路，但还不是完整 judge artifact browser |
| P2 | Landing 仍以样例内容为主 | 还没有接真实 benchmark / demo API |

## 安全 / 可访问性

- `dangerouslySetInnerHTML`：当前关键渲染路径未使用；markdown 通过 JSX 构建。
- 焦点陷阱、inert、skip-to-content、aria-live、ErrorBoundary：当前实现仍成立。
- forced-colors / reduced-motion / print / mobile media：相关实现未在本轮图谱改动中触碰；上一轮 media-features chromium 回归仍保留为历史验证记录。
- 完整 Playwright 全浏览器全视口本轮未重跑；本轮只重跑了 ConceptGraph 目标单测、前端全量 Vitest、typecheck/build 和 Concepts 页 chromium Playwright。
