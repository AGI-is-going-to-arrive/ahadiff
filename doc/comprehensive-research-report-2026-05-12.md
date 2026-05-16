# AhaDiff 知返 综合研究报告

> 日期：2026-05-12 | 状态：调研阶段 + Codex 对抗式审计修订（后续 v1.1 hardening 已改生产代码、测试和文档）
> 方法：6 维并行 Agent Teams 扫描 + Codex 5 路只读 sub-agent 复核 + 主线程抽样验证
>
> [Codex Audit] 2026-05-12：本次修订基于当前仓库真实代码、真实测试输出、静态文件计数；第六章竞品格局已追加 Grok Search 官方/权威来源复核。
> [Current-state note] 2026-05-15：本报告仍是 05-12 研究快照，不是当前实现账本。当前 Diff 已有 Unified / Split、Prev/Next、`+` / `-` 行标记、claim auto-scroll、柔和 claim 选中色带、dot legend 和 selected-lines hint；Welcome/Landing lesson demo 已有 H2 折叠、高度上限和最新 Lesson 链接。最新 frontend-polish 实测为后端 unit `2502 passed`、viewer typecheck、Vitest `353 passed`、viewer build、i18n `1449/1449` 和 diffcheck；integration/eval/ruff/format/pyright/wheel/full Playwright 未在这次 polish 中重跑。
> [Current-state note] 2026-05-16：Diff claim navigation 又补上右侧 ClaimInspector 长 diff 跳转后保持可见、选中详情贴在对应卡片下方，以及右侧栏内部滚动；本轮只重跑 viewer 目标/完整 Vitest、typecheck、build、diffcheck 和 serve/browser cache-bust smoke，未重跑后端、完整 Playwright 或 live judge。
> [Current-state note] 2026-05-17：Diff 选中 claim 的源码块预览已改为卡片内联展示，旧底部 selected-hunk 面板已移除；Welcome/Landing 现在会显示 LearnTaskBanner 反馈，并优先使用刚完成或 latest run 的真实 diff / lesson artifact，真实 run 缺 lesson 时不再混入样例内容。最新 viewer-only 实测为 viewer typecheck、Vitest `362 passed`、viewer build、Diff Chromium E2E `1 passed`、Welcome Chromium E2E `4 passed`、i18n `1490/1490`；后端、完整 Playwright 和 live judge 未在本轮重跑。

---

## 一、执行摘要

| 维度 | 评级 | 关键发现 |
|------|------|----------|
| **计划完成度** | v0.1 100% / v0.2 100% / v1.0 ~95% / v1.1 ~70% | 需继续以 backlog 文档为准；后续 hardening 验证为 2188 后端 unit + 318 前端 Vitest |
| **后端代码质量** | 0 confirmed Critical / actionable code findings 已修复 | C-1、`GIT_*` 环境污染、URL userinfo、JSON size cap、MCP allowlist、零宽字符补测已落地 |
| **前端 V6 还原度** | ~80% 静态估计，Bolder Editorial ~50% | Diff 切换、Settings mode-summary 渲染、Bolder 微装饰仍是主要 gap；Dashboard 5 KPI 已落地 |
| **跨平台兼容** | 后端 良好 / 前端 良好 | `browserslist`、Vite `build.target`、`.gitattributes` 已补；剩余关注 CSS fallback / autoprefixer policy / Windows hooks 文案 |
| **竞品格局** | 无完全对位竞品 | Diffity + DeepWiki 最近；5 项短期可借鉴功能 |
| **工程纪律** | 极强 | 生产面零 TODO/FIXME、2188 后端 unit + 318 前端 Vitest、1187 i18n scalar keys parity |

**总体判定**：项目工程质量很强，核心差异化（claim 证据链 + FSRS-6 + 8 维 rubric）壁垒明确。此前最紧迫的 C-1 纵深防御、Git 环境变量清洗、URL userinfo 拒绝、JSON size cap 和 prompt injection 零宽字符补测已由后续 v1.1 hardening 落地；接下来主要是前端 V6 品牌还原度、CSS fallback policy、Windows hooks 文案和几项高 ROI 功能补充。

---

## 二、版本计划完成度

> [Codex Audit] 本节的测试数量和版本号已用当前仓库验证；历史完成度百分比未重新从所有 planning docs 逐项重算，因此继续作为计划状态摘要，而不是新的审计结论。

### 2.1 各版本完成度总览

| 版本 | 完成度 | 测试里程碑 | 判定 |
|------|--------|------------|------|
| **v0.1** | **100%** | 61→559 tests | 7 Stage / 20 Task / 6 i18n Task 全部 IMPL |
| **v0.2** | **100%** | 576→993 tests | Gate 0-6 + Frontend Phase 1-4 全部完成 |
| **v1.0** | **~95%** | 993→2055 tests | 163/164 非 PLANNED 项 IMPL；剩余 Graphify provenance + API p95 |
| **v1.1** | **~70%** | 2055→2188 后端 unit + 318 前端 Vitest | 5 P0 全闭、12/14 P1 闭、4/5 P2 open |
| **v0.3** | **0%** | — | .ipynb diff + PR URL 集成（设计上延后） |

### 2.2 v1.1 仍 open 项

| 优先级 | 项目 | 位置 |
|--------|------|------|
| P1 | Dashboard 四车道模型（5 KPI 卡已落地，四车道模型仍需按 backlog 单独验收） | `DashboardPage.tsx` |
| P1 | Lesson 三栏 reader 完整落地 | `LessonPage.tsx` |
| P2 | Diff 虚拟列表 | `DiffView.tsx` |
| P2 | Benchmark/judge 报告页 | 新页面 |
| P2 | Landing benchmark/demo API（真实 run artifact 预览已接入） | `LandingPage.tsx` |
| P2 | V6 Newsreader / local font token 取舍 | CSS tokens |
| P2 | 8C artifact pack 完整包 | doc/ |

### 2.3 语义漂移

版本已同步到后端 `1.1.0a0`、前端 `1.1.0-alpha.0`；`pyproject.toml`、`uv.lock`、`src/ahadiff/__init__.py`、`viewer/package.json` 和 Sidebar 展示由版本断言测试一起覆盖。后续再改版本时，仍应按这几处一起更新。

---

## 三、后端代码质量与安全审计

### 3.1 High（1 项 — 必须修复）

**C-1: Git revision option-boundary hardening gap**
- **文件**: `src/ahadiff/git/repo.py:361-366`
- **攻击路径**: `POST /api/learn` → `capture_patch(revision=...)` → `_resolve_commitish` → `run_git("rev-parse", "--verify", f"{revision}^{{commit}}")`
- **问题**: revision 参数在 serve 层只有字符串/长度校验，`_resolve_commitish` 未在用户 revision 前加入 `--end-of-options`。`run_git` 使用 argv、不是 shell，因此当前不是 shell 注入；并且 `f"{revision}^{{commit}}"` 会让部分 `--option` payload 变成非法 option 值。但用户输入仍进入 git revision parser，缺少明确 option boundary。
- **影响**: 参数混淆 / 错误信息泄露 / 纵深防御不足（受 loopback + write token 限制；未复现 RCE）
- **修复方案**:
  1. 对所有接收不可信 revision/pathspec 的 git 调用，在用户参数前加 `--end-of-options`
  2. 添加轻量 denylist/长度限制，拒绝以 `-` 开头的 revision；不要用过窄正则破坏合法 ref 语法
  3. 添加单元测试断言 `revision="--upload-pack=..."` 抛出 `InputError`

> [Codex Audit] 原报告的调用链真实存在，但“git ref-name option-injection”表述过强。主线程探针确认 `HEAD~3` 合法，`v1.0^{tree}` 会被 commit-only 语义拒绝；`main...feature` 当前会被 `resolve_ref_range()` 的 `".."` 分割逻辑错误拆成 `main` 和 `.feature`，不能作为已支持语法写入白名单示例。修复优先级仍高，但首选边界是 `--end-of-options`，不是单靠正则。

### 3.2 Warning（8 项）

| ID | 状态 | 问题 | 文件 | 修复建议 |
|----|------|------|------|----------|
| W-1 | Fixed / scoped | `safe_json_loads` 已有默认 50 MiB cap，调用方仍可传更小上限 | `core/json_util.py` | 保留边界测试 |
| W-2 | Fixed | Git subprocess env 清洗已按大小写不敏感方式移除 `GIT_*`，并设置 `GIT_TERMINAL_PROMPT=0` | `git/repo.py` | 保留 env isolation 测试 |
| W-3 | Partial / split boundary | 本轮已在 `download.py --patch-url` 拒绝 URL userinfo；`llm/provider.py` helper 是另一个 provider URL 边界，未在本轮改写 | `git/download.py`, `llm/provider.py` | 不把下载入口修复扩写成 provider helper 全域修复 |
| W-4 | Partial / stale | 当前 `validate_remote_url()` 会检查所有 resolved IP，但缺 DNS 缓存，且实际 pin 仍取第一个 public IP | `llm/provider.py:784` | 保留全量 IP 校验，补短 TTL DNS cache / pin 一致性测试 |
| W-5 | False positive | 当前 cap 已在 append 前检查；风险仅是 httpx 先把 chunk 交给 Python | `llm/provider.py:500` | 不列为安全 warning；可保留 regression test |
| W-6 | Fixed | MCP `_count_table_rows` 动态表名已走 allowlist | `mcp/server.py` | 保留非白名单表名测试 |
| W-7 | False positive | APKG `_front/_back` 已使用 `html.escape` | `review/apkg_export.py:168` | 从 warning 移除；可补注释说明 HTML escape 边界 |
| W-8 | Fixed | `_load_graph` 异常已有 warning 记录 | `mcp/server.py` | 保留日志测试 |

> [Codex Audit] hardening 后：W-1/W-2/W-6/W-8 已修；W-3 的 `download.py --patch-url` userinfo 已修，但 provider URL helper 仍是独立边界；W-4 仍是 provider DNS/pin 一致性后续项；W-5/W-7 为误报或低价值项。

### 3.3 已验证安全的领域与剩余边界

- SQL 注入：普通 value 查询大量使用参数化；MCP `_count_table_rows` 当前已有 allowlist。这个结论只覆盖本轮审计到的 MCP stats 表名路径，不扩写为所有未来动态 SQL 安全。
- Prompt 注入：NFKC/confusable/combining/role-fence 覆盖存在；本轮已补 soft hyphen、variation selectors 和 TAG chars 等零宽字符输入侧检测。
- 密钥泄露：多条 audit 路径确实做 hash/masking；但“audit 只记录 SHA-256 hash”过窄，provider audit 还记录 mask 后的 URL/metadata。
- 路径穿越：install 层和 changed paths 有 no-symlink/no-reparse/repo-scope guard；不能扩写成所有文件读写路径均已同等验证。
- SSRF / DNS 重绑定：私有 IP 检测、Host header 分离和 IP pin 已实现；`download.py --patch-url` userinfo 已拒绝；provider helper 的 userinfo 防御和 W-4 DNS cache/pin 一致性仍是剩余边界。
- SQLite 迁移安全：`upgrade_review_db()` 有备份、失败恢复和测试覆盖；普通 `_ensure_schema()` 是逐步事务迁移，不是完整备份链。
- Async 正确性：serve 层多处阻塞工作已进 thread pool；但 `TaskRunner` 的 cancel/drain 状态契约仍有细节漂移，不能写成全域已验证。
- 后端 `shell=True`：仓库生产代码未发现 `shell=True`。

---

## 四、前端 V6 设计还原度

### 4.1 设计层还原度矩阵

| 维度 | 还原度 | 详情 |
|------|--------|------|
| Design Tokens | **75-85%** | accent 从 V6 `#D27050/#B04E28` 调深为 `#BE5236/#9B4420`；这是对比度校准，不是单纯漂移。全局 serif token 也从 Newsreader 改为本地字体/Georgia fallback |
| App Shell | **100%** | Sidebar/Topbar/skip-link/mobile drawer/⌘K 全部忠实 |
| 媒体查询体系 | **100%** | reduced-motion/forced-colors/reduced-transparency/pointer:coarse |
| Bolder Editorial | **~50%** | FOLIO 部分、drop-cap ✓、TOC tick ✗、italic 数字 ✗、page-head folio ✗ |
| 页面覆盖 | **12/13 可见页 + 1 个 legacy redirect** | `/skills` redirect 到 `/guide`；这是旧路由兼容，不是缺页 bug |

### 4.2 逐页面差距

| 页面 | 还原度 | 关键缺口 |
|------|--------|----------|
| Landing | 85% | hero `<em>` 荧光笔高亮缺失、FOLIO № 分隔符简化 |
| Dashboard | 90% | 5 KPI 卡已落地；四车道模型和 Bolder 细节仍需按 backlog 验收 |
| Lesson | 80% | TOC tick 已部分存在；highlight 证据高亮仍需浏览器视觉核对 |
| Diff Viewer | **60%** | 缺 Unified/Split 切换、Prev/Next file；hunk marker 不能再写成完全缺失 |
| Quiz | 75% | 缺 `.kbd` 快捷键提示、选项视觉可能偏离 |
| Review | 85% | 缺 flashcard 3D flip 效果、印章 hover 效果 |
| Concept Graph | 90% | Canvas 取代 SVG（性能更好）；V6 架构文档区未呈现 |
| Ratchet | 80% | 缺 `gain-card` with/without gain bar |
| Settings | **70%** | `mode-summary` / `provider-cell` CSS 存在，但渲染路径未接入；AI 工具指引 CRUD 已接入 |
| Onboarding | 80% | 缺 V6 `agent-grid` + `agent-card` 安装卡 |
| **Skills / Guide** | **85%** | `/skills` legacy route replace 到 `/guide`；Guide 静态展示命令，Settings → AI 工具指引提供 13 install target 的 preview/write/remove |

> [Codex Audit] Settings 的安装目标闭环真实存在：后端有 targets / preview / install / uninstall 四组受 token 保护的路由，前端 API client 与 Settings UI 均接入；Guide 不调用写 API，只展示命令和跳转入口，这是合理边界。

### 4.3 Viewer 超越 V6 的领域

- ErrorBoundary 诊断脱敏 + clipboard fallback
- SearchOverlay 双栏（list + preview）+ mobile 返回 + focus trap
- ConceptGraph Canvas renderer + a11y list fallback
- APKG export 按钮
- SSE 进度指数退避 + polling fallback
- 完整 i18n 1187 scalar keys parity（V6 全静态中文）
- lesson `walkthrough_tldr`

### 4.4 V6 模板自身待改进

1. CSS 1379 行单块臃肿，多处重复声明
2. 无 dark mode（`color-scheme: light` 锁死）
3. 半像素字号残留（14.5px 等）
4. `@media print` 出现 4 处互相覆盖
5. 未使用 `@layer` 分层
6. `:has()` / `text-wrap:balance` / `scrollbar-gutter` 跨浏览器兼容需渐进增强
7. `font-variation-settings:"opsz" 72` 对 body 文本是反优化
8. 印章 `transform: rotate(-3deg)` 在 flex 容器内可能布局抖动

---

## 五、跨平台与跨浏览器兼容性

### 5.1 后端跨平台（评级：良好）

| 领域 | 状态 |
|------|------|
| pathlib 全覆盖 | ✓ 无 `os.path.join` 滥用 |
| WSL2/UNC 检测 | 部分成立：`assert_local_repo_path` 检测 UNC / `//` 网络路径；`is_wsl2_mnt` 存在但主要用于 SQLite journal 策略 |
| portalocker 跨平台锁 | ✓ TOCTOU-safe |
| subprocess 无 shell=True | ✓ 全仓库验证 |
| 编码统一 UTF-8 | ✓ `encoding="utf-8", errors="replace"` |
| 信号处理平台分支 | ✓ Windows `CREATE_NEW_PROCESS_GROUP` / POSIX `start_new_session` |
| CI 矩阵 | 部分成立：backend matrix 覆盖 Linux/macOS；另有 Windows runtime guard，不是完整 Windows backend matrix |

### 5.2 前端跨浏览器（评级：良好）

**最低浏览器版本**:
- Chrome/Edge: **111+**（受 `color-mix()` 限制）
- Firefox: **121+**（受 `:has()` 限制）
- Safari: **16.4+**（受 `color-mix()` 限制）

| 严重度 | 当前状态 | 后续建议 |
|--------|----------|----------|
| **已修复** | `viewer/package.json` 已有 `browserslist`，`viewer/vite.config.ts` 已有 `build.target` | 保持和公开支持矩阵同步 |
| Low | `color-mix()` 已有部分静态声明 fallback，但缺系统化 `@supports` fallback | `@supports` 包裹 + 静态色 fallback |
| Low | `:has()` 仅在 Diff CSS 中使用，已有基础变量 fallback，但缺 `@supports selector(:has(...))` | 加 selector supports guard |
| **已修复** | `.gitattributes` 已强制文本 LF，并标记常见二进制资源 | 继续避免提交 CRLF 漂移 |
| Low | Windows hooks install 无明确提示 | 改善 i18n 文案 |

> [Codex Audit] 当前代码已补 `browserslist`、Vite `build.target` 和 `.gitattributes`。`repo.py` 已使用 `-c core.quotePath=false`、`encoding="utf-8", errors="replace"`，`improve/loop.py` 已按 Windows/POSIX 分支创建进程组。剩余兼容工作应聚焦 CSS fallback 覆盖和 Windows hooks 文案，而不是缺失基础配置。

### 5.3 无障碍（评级：优秀）

- `prefers-reduced-motion` / `forced-colors` / `prefers-reduced-transparency` 全覆盖
- 37 个组件含 `aria-*` / `role` 属性
- ConceptGraph 有 a11y list fallback
- skip-to-content + focus trap + Esc 关闭

---

## 六、竞品格局与差异化分析

> [Codex Audit / Grok Search] 2026-05-12：本节已用 Grok Search 重新联网复核，并抓取官方或权威页面。结论边界：DeepWiki / CodeRabbit / Execute Program / Sourcegraph Cody / Karpathy LLM Wiki 的核心描述有官方来源支撑；Diffity 的“学习闭环”描述有 GitHub README 支撑，但 `diffity.com` 当前抓取到的 GitHub README 与搜索结果中的 repo 呈现存在差异，因此标为 Medium confidence。

### 6.1 竞品矩阵

| 竞品 | 品类 | 比知返强 | 知返更强 | Grok 复核状态 |
|------|------|----------|----------|----------------|
| **Diffity** | AI diff/review + 教学循环 | GitHub-style diff viewer、agent inline review、tour；部分 README 还描述 `build → tour → challenge → review → adapt` | SRS 长期记忆、claim 验证、8 维 rubric | **Medium**：`nilbuild/diffity` README 明确支持 `Learn any topic` 与学习闭环；但 `diffity.com` 当前抓取到 `kamranahmedse/diffity` README，未展示完整 learn loop。来源：[Diffity/GitHub, 2026, README](https://github.com/nilbuild/diffity)、[Diffity.com/GitHub, 2026, README](https://diffity.com) |
| **DeepWiki** | Code Wiki | 零摩擦 URL trick、自动文档、架构图 | per-diff 颗粒度、证据链 | **High**：Cognition 官方写明把 `github.com` 替换成 `deepwiki.com` 即可访问 public repo wiki，Devin docs 写明 architecture diagrams / documentation / source links。来源：[Cognition, 2025, DeepWiki launch](https://cognition.ai/blog/deepwiki)、[Devin Docs, 2026, DeepWiki](https://docs.devin.ai/work-with-devin/deepwiki) |
| **CodeRabbit** | PR Review | 商业化、企业工作流、PR quality gate | 学习闭环 | **High**：官方 docs 描述 PR review、one-click fixes、全 repo context；enterprise 页面声明 15,000+ customers、global teams、complex codebase review。来源：[CodeRabbit, 2026, PR Reviews](https://docs.coderabbit.ai/overview/pull-request-review)、[CodeRabbit, 2026, Enterprise](https://coderabbit.ai/enterprise) |
| **Execute Program** | SRS 编程 | daily review 习惯化、自动判题、课程依赖解锁 | 来源于真实 diff 而非预制内容 | **High（单一官方来源）**：官方 spaced repetition 页面详细说明 review items、2/7/21/60 day schedule、自动检查代码答案、lesson dependency unlock。来源：[Execute Program, 2026, Spaced Repetition](https://www.executeprogram.com/spaced-repetition) |
| **Sourcegraph Cody** | 代码理解 | 跨本地/远端 codebase context、Sourcegraph Search API、Enterprise 多 repo context | local-first、验证证据链 | **High**：官方 docs 写明 Cody 用 Sourcegraph Search API 从 local and remote codebases 拉取 APIs/symbols/usage context。来源：[Sourcegraph, 2026, Cody docs](https://sourcegraph.com/docs/cody) |
| **Karpathy LLM Wiki** | 范式 / pattern（非产品） | persistent wiki、lint loop：contradictions / stale claims / orphan pages / missing concept pages | AhaDiff 是可运行产品主链，且面向 diff learning | **High**：Karpathy gist 是 idea file，不是 hosted product；lint loop 词项为原文。来源：[Karpathy, 2026-04-04, LLM Wiki gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) |

> [Codex Audit / Grok Search] 原“无完全对位竞品”仍成立，High confidence。最近的功能邻近者是 Diffity（diff/review/tour/learn loop）和 DeepWiki（repo wiki URL trick + architecture diagrams），但 AhaDiff 的 per-diff verified learning、claim evidence state、FSRS-6 和 8 维 rubric 组合仍未在上述官方来源中看到完整对位。

### 6.2 知返护城河评估

| 能力 | 壁垒强度 | 备注 |
|------|----------|------|
| Claim → file:line 证据链 | **极强** | 代码场景下罕见的端到端实现 |
| 8 维 rubric + git ratchet | **极强** | darwin-skill/autoresearch 派生独有 |
| Per-diff lesson 生成 | **强** | 少数把 git diff 当教学单元的工具 |
| FSRS-6 SRS | **同档** | 差异在于卡片来源是 verified diff |
| MCP server 6 tool | **强** | 当前已有 6 个 read-only tools；`ask_lesson` RFC 会新增第 7 个 |
| Local-first / 8 provider | **同档** | 已覆盖 |
| Concept graph | **中** | 可加 blast-radius 查询 |
| APKG export | **中** | 缺 stable GUID + custom CSS |
| Lesson 自我维护 | **缺 → P0** | Karpathy LLM Wiki 的 lint loop 有官方原文支撑；AhaDiff 当前未实现 `find_contradictions/orphans/missing_concepts` |
| 公开预览 / 零摩擦 | **缺 → P1** | DeepWiki URL trick 有官方来源支撑；AhaDiff 未实现 `ahadiff.dev/<repo>/<sha>` 这类公开 preview |

### 6.3 可执行建议（按 ROI 排序）

#### Tier 0 — 安全 + 核心差异化（立即）

1. **`--end-of-options` 安全修复** — 对应 C-1，已落地；后续保持回归测试
2. **Karpathy 维护循环引入 concepts.jsonl** — `find_contradictions/orphans/missing_concepts`，这是知返 V2 自我修复能力的核心，直接提升 lesson 质量和护城河
3. **公开 lesson preview URL** — `ahadiff.dev/<repo>/<sha>` 零摩擦获客通道，对标 DeepWiki URL trick；但这会改变 local-first 安全边界，必须先做 threat model

> [Codex Audit] `ahadiff serve` 当前默认绑定 `127.0.0.1`，公开 preview 不是小 UI 改动；至少需要 artifact redaction、访问控制、租户隔离、公开/私有 repo 边界和删除策略。

#### Tier 1 — 高 ROI / 当前周期

4. **MCP 扩展 `ask_lesson`** — 对外暴露 evidence-grounded Q&A
5. **CodeTour `.tours/*.json` 双向导出** — 零 LLM 成本，VSCode/JetBrains 生态触达
6. **APKG stable GUID + custom CSS** — 多次导出不重复 + Anki 内可读
7. **Daily Review Loop** — Execute Program 风格每日 5 分钟 ritual

#### Tier 2 — 战略差异化

8. **Diffity-style mini-coding challenge** — lesson + quiz 之后让用户写 diff
9. **Hybrid retrieval claim verifier** — BGE dense + BM25 fuzzy 匹配

#### Tier 3 — 探索/选配

10. Per-user FSRS optimizer
11. Browser extension 注入 GitHub PR 页
12. HMAC-attested verification receipt
13. Cinematic diff replay (Gitlogue 风格)

---

## 七、前端 UI/UX 改进路线图

### 7.1 P0 — 品牌一致性（影响首印象）

| 项 | 工作量 | 影响 |
|----|--------|------|
| 校准 `--accent/--accent-ink/--warning` 至 V6 原色或记录对比度偏离原因 | 0.5h | 全局色感统一，但需避免破坏 contrast gate |
| Settings 顶部 `mode-summary` 概览卡 | 0.5d | CSS 已有，需接入渲染路径 |
| Karpathy 维护循环（concepts 自我修复） | 2-3d+ | 核心差异化能力；需要 contradiction/orphan/missing 基础设施 |
| 公开 lesson preview URL 方案设计 | 1d+ | 需先做 local-first threat model，不应直接实现公网托管 |

### 7.2 P1 — 视觉细节

| 项 | 工作量 |
|----|--------|
| Lesson TOC `.toc a::before` 6→12px 短线 reveal | 2h |
| Diff Viewer Unified/Split 切换 + Prev/Next file | 1d |
| Page-head h1 统一 italic Newsreader + folio eyebrow | 0.5d |
| Tabular italic 数字应用到 Dashboard/Ratchet | 2h |
| Review flashcard 3D flip 效果 | 4h |
| Hero `<em>` 荧光笔高亮 | 2h |

### 7.3 P2 — 工程化改进

| 项 | 工作量 |
|----|--------|
| `browserslist` + `build.target` 已补；autoprefixer policy 另行决策 | 2h |
| `color-mix()` `@supports` 兜底 | 3h |
| CSS `@layer base, tokens, components, bolder` 分层 | 4h |
| `.gitattributes` 强制 LF（已补，后续只维护模式表） | 0.5h |
| `manifest.json` 补 `display_override` + `lang` | 0.5h |
| Diff 大文件虚拟滚动 | 1-2d |
| Landing benchmark/demo API（真实 run artifact 预览已接入） | 1d |

> [Codex Audit] P0/P1/P2 排序已保留，但 Karpathy 维护循环和公开 preview 不是纯前端任务；它们涉及后端数据模型、安全边界和产品发布策略。

### 7.4 P3 — 超越 V6 的新增功能

| 项 | 来源 |
|----|------|
| Daily Review ritual UI（streak + 预算卡） | Execute Program |
| Lesson timeline replay 动画 | Gitlogue |
| Graph blast-radius 查询 | CodeRAG |
| Dark mode token 体系 | 现代 CSS 标准 |

---

## 八、后续行动建议

### Phase 1: 安全修复（立即）
- [x] C-1: Git revision option-boundary 修复（`--end-of-options` + 拒绝 leading dash）+ 单元测试
- [x] W-2: Git env 清洗（大小写不敏感清理 `GIT_*`）
- [x] W-3: URL userinfo 拒绝
- [x] W-8: MCP graph load 异常记录
- [x] Prompt injection: 输入侧零宽字符绕过补防护 + 测试

### Phase 2: 核心差异化功能（高优先级）
- [ ] Karpathy 维护循环（concepts.jsonl 自我修复：contradictions/orphans/missing）
- [ ] 公开 lesson preview URL 方案设计（先 threat model，再决定是否实现）

### Phase 3: 前端品牌对齐（1-2 天）
- [ ] accent 色校准
- [ ] Settings mode-summary
- [ ] Diff Unified/Split 切换

### Phase 4: 工程化补齐（1 天）
- [~] browserslist + build.target 已补；autoprefixer policy 仍是后续决策
- [x] .gitattributes
- [x] 版本号更新（`pyproject.toml` / `uv.lock` / `src/ahadiff/__init__.py` / 前端展示 / 版本断言测试同步）

### Phase 5: 高 ROI 功能（1 周）
- [ ] MCP `ask_lesson` 扩展
- [ ] APKG stable GUID + custom CSS
- [ ] Daily Review Loop
- [ ] CodeTour 导出

### Phase 6: 战略差异化（中期）
- [ ] Mini-coding challenge
- [ ] Hybrid retrieval verifier
- [ ] Browser extension 注入 GitHub PR 页

---

## 九、代码库指标快照

| 指标 | 数值 |
|------|------|
| 后端 Python 文件 | 167 个（18 子包） |
| 后端测试文件 | 84 个 `test_*.py`（或 88 个 `tests/**/*.py`；后续 hardening 回归为 2188 passed） |
| 前端 TSX 文件 | 58 个 |
| 前端 TS 文件 | 42 个 |
| CSS 文件 | 43 个 |
| 前端测试 | 318 passed |
| i18n 键值对 | 1187 scalar keys / 语言（en + zh-CN parity） |
| Playwright E2E | repo 内 14 个主要 spec（15 个若包含 real-serve）；本轮最终只重跑目标 10 passed，完整 Playwright 未重跑 |
| Prompt 模板 | 8 个模板族；15 个 `.md` 文件（含 packaged/root duplicates） |
| API 路由 | 62 个 concrete `/api/*`；64 个 Starlette `Route` total |
| ErrorCode | 28 个稳定 |
| LLM Provider 格式 | 8 种 |
| Install 目标 | 13 个 |
| GitHub Workflows | 5 个 |
| 规划/审查文档 | 原 `~145` 口径不清；当前 `doc/*.md` 为 36，全仓 Markdown 为 449 |

> [Codex Audit] 指标快照已按当前文件系统和实跑测试修正；`TODO/FIXME` 在生产源码、测试和 viewer 源码中未命中，仅报告文档自身含相关词。

---

## 十、关键文件速查

### 安全修复目标
- `src/ahadiff/git/repo.py` — C-1 revision option-boundary hardening
- `src/ahadiff/llm/provider.py` — W-3/W-4
- `src/ahadiff/core/json_util.py` — W-1
- `src/ahadiff/mcp/server.py` — W-6/W-8
- `src/ahadiff/safety/injection.py` — 零宽字符输入绕过

### 前端改进目标
- `viewer/src/styles/tokens.css` — accent 色校准
- `viewer/src/pages/DiffViewerPage.tsx` — Unified/Split 切换
- `viewer/src/pages/SettingsPage.tsx` — mode-summary
- `viewer/src/components/Landing.css` — hero 高亮
- `viewer/src/components/Lesson.css` — TOC tick
- `viewer/vite.config.ts` — build.target（已补；后续只需保持支持矩阵同步）
- `viewer/package.json` — browserslist（已补；后续只需保持支持矩阵同步）

### 评估证据
- `R0-feature-matrix.md` — 172 项特性矩阵
- `doc/FRONTEND_GAP_REPORT.md` — 前端 gap 状态
- `doc/v6-alignment-gap-analysis.md` — V6 设计差距
- `.claude/team-plan/v1.1-todo.md` — v1.1 backlog
- `doc/contract-freeze.md` — 架构权威源

---

## 十一、Codex 对抗式审计结论

### 11.1 逐章 IMPLEMENTED 状态

| 章节 | 状态 | 结论 |
|------|------|------|
| 一、执行摘要 | UPDATED | 已修正 C-1 严重性、warning 计数、i18n key 数和跨平台表述 |
| 二、版本计划完成度 | PARTIAL | 版本号和测试里程碑已验证；历史完成度百分比未逐项重算 |
| 三、后端代码质量与安全 | UPDATED | C-1 调整为 High hardening；W-5/W-7 降为 false positive；补零宽字符 prompt injection 绕过 |
| 四、前端 V6 还原度 | UPDATED | Skills/Guide、Settings install CRUD、Dashboard KPI 和 i18n 数字已修正 |
| 五、跨平台与跨浏览器 | UPDATED | Windows CI、WSL2/UNC、color-mix、`:has()`、`.gitattributes` 状态已修正 |
| 六、竞品格局与差异化 | UPDATED | 已用 Grok Search 复核官方/权威来源；Diffity 标为 Medium confidence，其余核心描述为 High confidence |
| 七、前端 UI/UX 路线图 | UPDATED | 将 Karpathy loop / public preview 标为跨后端与安全边界任务 |
| 八、后续行动建议 | UPDATED | 调整 Phase 1 修复项和版本更新依赖面 |
| 九、代码库指标快照 | IMPLEMENTED | 文件数、测试数、i18n、routes、prompt 模板口径已按当前仓库修正 |
| 十、关键文件速查 | UPDATED | 移除 W-5/W-7 误报目标，加入 prompt injection 修复目标 |

### 11.2 关键修正

- **C-1**：攻击路径真实存在，但 `run_git` 使用 argv 且 `_resolve_commitish` 会追加 `^{commit}`；当前更准确的结论是缺少 git option boundary 的纵深防御，不是已复现的 shell/RCE 漏洞。
- **Warning 复核**：W-2/W-3/W-8 为明确可修项；W-1/W-4/W-6 是 scoped hardening；W-5/W-7 为误报或低价值项。
- **新增遗漏**：`src/ahadiff/safety/injection.py` 输入侧未移除零宽字符，`igno\u200bre previous instructions` 这类 payload 当前未命中。
- **工程指标**：后续 hardening 后当前实测为后端 unit `2188 passed`、前端 Vitest `318 passed`、i18n scalar keys `1187/1187`，不是 1228。
- **版本更新**：后端已同步到 `1.1.0a0`，前端已同步到 `1.1.0-alpha.0`；覆盖面包括 `pyproject.toml`、`uv.lock`、`src/ahadiff/__init__.py`、`viewer/package.json`、前端 Sidebar 展示和版本断言测试。

### 11.3 实跑验证

```bash
UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run --frozen --no-sync pytest tests/unit -x -q
# 2188 passed in 195.87s (0:03:15)
```

```bash
cd viewer && pnpm vitest run
# Test Files 29 passed (29)
# Tests 318 passed (318)
```

```bash
cd viewer && node - <<'NODE'
const en = require('./src/i18n/messages/en.json');
const zh = require('./src/i18n/messages/zh-CN.json');
function countScalars(value) {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    return Object.values(value).reduce((sum, child) => sum + countScalars(child), 0);
  }
  return 1;
}
console.log(countScalars(en), countScalars(zh), countScalars(en) === countScalars(zh));
NODE
# 1187 1187 true
```

```bash
uv run pytest tests/unit/test_injection.py tests/unit/test_task_runner.py tests/unit/test_review.py -q
# 64 passed in 7.36s
```

```text
Grok Search competitor audit:
- planning session: c68f67ef8b06
- web_search sessions: Diffity ee5aaf5d70c5; DeepWiki 6c49a825640c; CodeRabbit 6fd682286b7f; Execute Program fcb7dd8df7ae; Sourcegraph Cody f5e63c243333; Karpathy LLM Wiki ad8a7cdaf0ed
- web_fetch official/authoritative pages: github.com/nilbuild/diffity; diffity.com; cognition.ai/blog/deepwiki; docs.devin.ai/work-with-devin/deepwiki; docs.coderabbit.ai/overview/pull-request-review; coderabbit.ai/enterprise; executeprogram.com/spaced-repetition; sourcegraph.com/docs/cody; gist.github.com/karpathy/442a6bf555914893e9891c11519de94f
```

### 11.4 可行性判断

- **C-1 修复**：已按 `--end-of-options` 和 leading-dash 拒绝落地。过窄 `_VALID_REVISION_RE` 会误伤合法 revision 语法，后续不要把它当补救方案。`main...feature` 当前并非已支持格式，不能作为兼容性承诺。
- **Karpathy 维护循环**：当前缺 contradiction/orphan/missing concept 基础设施；需要先定义 concept/claim/linkage schema、检测器和 review 写回策略。
- **公开 preview URL**：当前 serve 是 loopback local-first；公网 preview 需要 threat model、脱敏策略、访问控制、租户隔离和删除策略，不能作为简单 UI feature。
- **browserslist/autoprefixer**：`browserslist` 和 `viewer/vite.config.ts` build target 已落地；autoprefixer policy 仍需单独决策，并继续配合 CSS fallback 和 `pnpm typecheck && pnpm build && pnpm vitest run` 回归。
- **版本更新**：已同步 Python metadata、lockfile、runtime version、前端展示和测试；后续发版仍不能只改 `pyproject.toml`。

### 11.5 边界

原始 Codex 审计本身没有修改生产代码；后续 v1.1 security / cross-platform follow-up 已按本报告中的真实项修改生产代码和测试。最终实测没有重新运行完整 Playwright、integration/eval/live judge/wheel/GitHub Actions。外部竞品章节已用 Grok Search 做官方/权威来源复核；仍需注意两点边界：Diffity 的官方呈现存在 repo/README 差异，因此学习闭环结论为 Medium confidence；竞品资料只验证公开页面可见能力，不验证未公开内部实现或真实用户规模。
