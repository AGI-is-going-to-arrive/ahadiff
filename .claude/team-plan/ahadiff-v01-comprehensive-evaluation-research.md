# Team Research: AhaDiff v0.1 全面评估 v2（三模型深度改进版）

> 生成时间: 2026-04-20
> 模型: Claude Opus 4.6 + Codex + Gemini 3.1 Pro Preview
> 版本: v2 — 全维度深度改进 + UX 取消冻结 + `ahadiff serve` 设计
> 方法: 并行探索 → 灵感源码交叉验证 → 三模型综合 → 双模型交叉审查 → 全维度改进

## 增强后的需求

对 AhaDiff v0.1 的设计方案进行 7 维度全面评估并提出可执行改进方案。**关键变更**: 取消"静态 viewer 冻结"，v0.1 将包含 `ahadiff serve` 轻量本地服务器。目标：所有维度提升至 A 级水平。

---

## 一、架构合理性

### 原评分: B+ → 改进后目标: **A**

**✅ 原有优点（保留）**:
1. 八层边界经修订后职责正交性良好
2. 依赖链建模正确（Task 0 前置、Task 5→6 串行、Task 7 独立）
3. 编排逻辑集中于 orchestrator.py
4. N-文件契约结构清晰

**🔧 改进方案（Codex 主导）**:

#### 改进 A1: Layer 5/6/7 显式服务契约

不再只冻结 data schema，而是固定**服务接口**：

| Layer | 名称 | 服务接口（command/query） |
|-------|------|--------------------------|
| Layer 5 | Ratchet/History | `append_result_event()`, `resolve_baseline()`, `compute_trend()`, `export_history()` |
| Layer 6 | Learning State | `record_review_answer()`, `record_claim_feedback()`, `resolve_card_state()`, `update_concepts()` |
| Layer 7 | Delivery Surface | `render_static_bundle()`, `build_data_bundle()`, `serve_app()` |

**硬边界**: Layer 7 不能直写 review.sqlite，只能调用 Layer 5/6 的接口。

**Query DTO 契约（Task 0 冻结）**:

| 服务方法 | 输入 | 输出 | 错误类型 |
|---------|------|------|---------|
| `list_runs_page(cursor, limit, lane_filter)` | 分页游标+lane | `RunSummaryPage` | — |
| `get_run_detail(run_id)` | run_id | `RunDetail` | `NotFound` |
| `get_queue_page(limit)` | 分页 | `CardQueuePage` | — |
| `get_status()` | — | `LearnStatus` | — |
| `submit_review(card_id, answer, idempotency_key)` | 卡片ID+评价 | `ReviewResult` | `StaleCard`, `Conflict` |
| `mark_claim_wrong(claim_id, reason, idempotency_key)` | claim_id | `FeedbackResult` | `NotFound` |
| `compute_trend(lane, eval_bundle_version, prompt_version)` | 过滤条件 | `TrendData` | — |

所有写操作必须支持 `idempotency_key` 幂等语义。serve 和 static 共享同一 query DTO。

#### 改进 A2: `ahadiff serve` 架构定位

`ahadiff serve` 放入 **Layer 7**，定义为"交付适配器"而非"编排器"：
- CLI 和 serve 共用 `core/orchestrator` + Layer 5/6 服务
- Layer 7 细分为：
  - **7a Static Snapshot Adapter**: `file://` 兼容、一次性 data_bundle.json
  - **7b Live Serve Adapter**: 实时读 SQLite + run artifacts + REST API
- 页面组件、路由语义、状态名**完全一致**，只替换数据源

```
Layer 7a: Static → Jinja2 → data_bundle.json → file://index.html
Layer 7b: Serve  → Starlette → SQLite query  → localhost:8765/
                                               ↓
                                          REST API endpoints
```

#### 改进 A3: Graphify 新鲜度状态机（7 态）

从 `import_head_sha == HEAD` 升级为：

| 状态 | 含义 | UI 行为 |
|------|------|---------|
| `fresh_exact` | SHA 完全匹配 | 正常展示 |
| `fresh_equivalent_tree` | tree hash 匹配（解决 squash/cherry-pick） | 正常展示 |
| `stale_ahead` | HEAD 领先于 import | 轻提醒 banner |
| `stale_behind` | HEAD 落后于 import | 轻提醒 banner |
| `stale_diverged` | 分叉 | 强提醒，禁止用于 freshness-sensitive claim |
| `stale_unreachable` | import SHA 不可达 | 强提醒 |
| `invalid` | 校验失败 | 阻断，不可渲染 |

新增元数据: `import_head_tree`, `repo_root_fingerprint`, `imported_at`

**7 态 → 4 值映射规则（冻结）**:

| 内部 7 态 | 对外 context_freshness | UI 分组 |
|-----------|----------------------|---------|
| `fresh_exact` | `exact` | 正常展示 |
| `fresh_equivalent_tree` | `equivalent` | 正常展示（轻标注"tree 匹配"） |
| `stale_ahead`, `stale_behind` | `stale` | 轻提醒 |
| `stale_diverged`, `stale_unreachable` | `stale` | 强提醒 |
| `invalid` | `absent` | 阻断 |

#### 改进 A4: 上下文可信度统一字段

为 Layer 5 和 Graphify 交界补 `context_freshness = exact | equivalent | stale | absent`，供 Layer 6/7 直接消费。7 态只在 Graphify 内部使用，对外统一投影为 4 值。`equivalent` 表示 tree hash 匹配（squash/cherry-pick 后 SHA 不同但内容等价）。

**影响 Task**: Task 0（contract-freeze 增加接口契约）、Task 12（事件流+query service）、Task 13-15（双适配器拆分）

---

## 二、工程完备性

### 原评分: B- → 改进后目标: **A-**

**🔧 全部 6 处缺口闭合 + 3 处新增（Codex 主导）**:

#### 改进 E1: 三层锁模型

| 锁层级 | 覆盖操作 | 实现方式 |
|--------|---------|---------|
| `repo_write_lock` | learn/improve/graph refresh/migrate | 文件锁 `.ahadiff/ahadiff.lock` |
| `run_write_lock` | regenerate/run-scoped mutate | 文件锁 `.ahadiff/runs/<id>/run.lock` |
| `db_write_lock` | review answer/claim feedback/quiz answer/learning-signal.jsonl | **跨进程文件锁** `.ahadiff/db.lock` + serve 进程内 `asyncio.Lock` 双层 |

- GET/read/export/history **不拿文件锁**，只依赖 SQLite `busy_timeout`
- **跨进程写保护**: CLI `ahadiff review`/`ahadiff mark` 和 serve POST 都先拿 `db_write_lock` 文件锁，再拿 `asyncio.Lock`（serve 内部）
- **全局锁顺序（冻结）**: `repo_write_lock` → `run_write_lock` → `db_write_lock`，禁止逆序获取
- **JSONL 追加**: `learning-signal.jsonl` 写入纳入 `db_write_lock` 保护（文件锁），不再是 asyncio-only
- **Publish barrier**: run artifact 全部落盘成功后才 append `result_event`，防止 serve 读到半成品
- **Migration quiesce**: `ahadiff db upgrade` 检测活跃 serve 时 fail-fast 并提示 `先关闭 ahadiff serve`，或 `--force` 进入 drain 模式（拒绝新写请求 → 等待活跃写完成 → 执行 migration → 恢复）

#### 改进 E2: 版本标识符优先级表（冻结）

| 标识符 | 语义 | 用途 | 参与 ratchet？ |
|--------|------|------|---------------|
| `schema_version` | 存储兼容 | migration 判断 | 否 |
| `eval_bundle_version` | 评估语义权威 | score 比较、cassette key | 是 |
| `prompt_version` | 生成语义权威 | lesson/quiz 比较 | 是 |
| `prompt_fingerprint` | VCR cassette key | cassette 失效 | 否（仅 VCR） |
| `model_id` | 执行环境标签 | 审计 | 否 |

`rubric_version` 降级为 `eval_bundle_version` 的派生显示字段。

#### 改进 E3: note 字段 → `note_json`

SQLite 存 JSON 对象；TSV 保存 canonical minified JSON 字符串。最小 schema：

```json
{
  "phase": "improve|phase25|baseline",
  "trigger_reason": "consecutive_discard_2",
  "degraded_flags": ["diff_clipped"],
  "cleanup_state": "clean|interrupted|orphaned",
  "history_rewrite": null,
  "graphify_freshness": "stale_ahead"
}
```

#### 改进 E4: Degraded run 趋势规则（冻结）

- `ratchet_eligible` = `capability_level == 3` 且 `degraded_flags` 为空
- `trend_visible` = 所有 run（全部展示在辅助趋势层）
- **headline score 和 keep/discard 只看 ratchet_eligible**
- degraded/non_ratcheted 只出现在辅助趋势层和审计页，**永不提升 baseline**

#### 改进 E5: Worktree SIGINT 处理工程化

处理顺序（不再混入 crash 语义）：
1. 停止接收新任务
2. 取消未提交 LLM 调用
3. 提交/回滚当前 SQLite 事务
4. 释放文件锁
5. 清理未 cherry-pick 的 worktree
6. 写 `event_type=interrupt_received` + `cleanup_state=interrupted`

#### 改进 E6: 性能阈值量化（可验收数字）

| 指标 | soft | hard | skip/阻断 |
|------|------|------|-----------|
| Capture lines | 2,000 | 5,000 | 10,000 |
| Static HTML size | — | 2 MB | — |
| Dashboard GET p95 | — | 200ms | —（1000 runs 基线）|
| Mutating POST p95 | — | 150ms | — |
| Graph page p95 | — | 400ms | — |
| WAL file size | — | 64 MB | 触发 PASSIVE checkpoint |

**Benchmark envelope（验收条件）**: Apple M1+ / SSD / 1000 runs + 5000 cards + 200 graph nodes / 单 worker / 冷缓存首次 + 热缓存复测。CI smoke budget 放宽 2x，release SLO 使用上表严格值。

#### 改进 E7: `ahadiff serve` 后端并发策略

- v0.1 固定 **单 worker**（`uvicorn --workers 1`）
- 写路径: `asyncio.Lock` + SQLite WAL + `busy_timeout=5000`
- 后台只做 PASSIVE checkpoint，不做多 worker 扩展
- Starlette `StaticFiles` 提供 CSS/JS，`Jinja2Templates` 提供 SSR HTML

**影响 Task**: Task 0（全部契约补齐）、Task 5/12/15/16/17（锁模型、degraded rules、interrupt lifecycle）、新增 serve 子任务

---

## 三、安全性

### 原评分: B+ → 改进后目标: **A**

**🔧 全部 4 处侧信道闭合 + `ahadiff serve` 安全模型（Codex 主导）**:

#### 改进 S1: Viewer XSS — "先结构化，再渲染，再 CSP"

1. lesson/claim/quiz 只接受 **schema 化 Markdown 子集**（禁止 raw HTML、inline event handler、`javascript:` URL）
2. `data_bundle` 做 JSON 安全序列化并转义 `</script`
3. **统一策略**: 严格外部化所有 JS/CSS 为独立文件（`app.js`, `style.css`），两种模式均可使用 `script-src 'self'; style-src 'self'`，消除 nonce/hash 双策略维护成本
4. **serve 模式额外**: 如需内联脚本（数据注入），使用 per-response nonce

```
default-src 'self'; script-src 'self' 'nonce-{RANDOM}'; 
style-src 'self' 'nonce-{RANDOM}'; img-src 'self' data:; 
object-src 'none'; base-uri 'none'; frame-ancestors 'none'
```

#### 改进 S2: VCR cassette 双向脱敏

- 录制前: 过滤 `authorization` / `x-api-key` header
- 录制后: 对 request body 和 response body 再跑一次 `redaction_scan()`
- CI: 对 cassette 目录做 secret-pattern fail-fast

#### 改进 S3: Graphify 导入 → 不可信外部 artifact

- `graph.json` 必须走 Pydantic schema 校验 + 路径 resolve + repo-root containment
- label/title/summary 只能作为**纯文本**注入 viewer
- `GraphifyStatus.sanitized` 从布尔装饰字段升级为**真正的 gate 条件**: 未 sanitized 不可渲染

#### 改进 S4: LLM 输出双重约束

- **结构层**: Pydantic strict mode（不通过→重试或降级）
- **内容层**: Markdown sanitizer（raw HTML / script-like payload / 危险链接协议 → rejected）

#### 改进 S5: `ahadiff serve` 安全默认值

| 安全项 | 默认值 | 说明 |
|--------|--------|------|
| 绑定地址 | `127.0.0.1` / `::1` | 不开放 `0.0.0.0` |
| CORS | 同源，不开启 | 跨源需显式 allowlist + CLI 警告 |
| TrustedHost | `localhost`, `127.0.0.1`, `::1` | Starlette middleware |
| CSP | nonce-based（每响应不同） | 见 S1 |
| 认证 | 无（本地单机） | 0.0.0.0 时强制提示 |
| 写保护 | 启动时生成随机 loopback write token | POST 强制校验 `X-Write-Token` header |
| Origin 校验 | POST 强制校验 Origin/Referer 为 localhost | 防御浏览器扩展/跨站请求 |
| 速率限制 | 轻量 token-bucket（100 req/min per write endpoint） | 防止本地滥用 |
| WebSocket | 默认拒绝 `Upgrade: websocket` | 只保留显式 allowlist |
| 读写分离 | 默认 read-only 模式 | `--enable-write` 显式开启写接口 |

**影响 Task**: Task 2（redaction_pipeline 扩展覆盖 VCR/Graphify/LLM output）、Task 13-14（Markdown sanitizer + CSP 模板化）、新增 serve 安全子任务

---

## 四、测试策略

### 原评分: B → 改进后目标: **A-**

**🔧 全面强化（Codex 主导）**:

#### 改进 T1: Prompt 依赖 CI 强约束

CI 门禁检查项：
- `includes:` frontmatter 存在性
- 循环依赖检测
- 孤儿 partial 检测
- fingerprint 漂移检测
- "修改 shared partial → 精确失效对应 cassette" 验证

#### 改进 T2: `ahadiff serve` Endpoint 测试矩阵

| 类型 | Endpoint | 测试项 |
|------|----------|--------|
| GET | `/healthz` | 200 + db accessible |
| GET | `/api/runs` | 分页、空结果、1000+ runs 性能 |
| GET | `/api/runs/{id}` | 404、正常、degraded run banner |
| GET | `/api/history` | lane 过滤、trend 计算、空历史 |
| POST | `/api/cards/{id}/review` | 事件追加、SQLite 可见性、asyncio.Lock 串行化 |
| POST | `/api/claims/{id}/mark-wrong` | learning-signal.jsonl 写入、幂等 |
| POST | `/api/cards/{id}/review` (quiz) | card state 更新、stale card 拒绝 |

每个 mutating endpoint 必须测: `busy_timeout`、SIGINT 后清理。

#### 改进 T3: A11y 测试门禁

- Playwright + axe-core（或等价方案）
- 覆盖 static mode 和 serve mode
- 三个关键页面: lesson reader、diff viewer、review flow
- 检查项: 键盘导航、焦点可见、ARIA、对比度、reduced-motion、移动端 drawer

#### 改进 T4: Mixed-capability 矩阵测试

```
capability_level(1/2/3) × degraded(true/false) × 
graphify_freshness(exact/equivalent/stale/absent) × 
history_state(normal/squash/cherry-pick/diverged)
```

断言: trend lane 隔离、banner 正确、ratchet 禁用/启用、history query 稳定。

#### 改进 T5: 安全头回归测试

CSP header/nonce、Host 过滤、默认无 CORS、显式 allowlist 生效、错误响应仍带 CORS 头。

#### 改进 T6: SQLite WAL 并发回归

长读 + 写入、checkpoint starvation、`SQLITE_BUSY` 恢复、首连 recovery。

#### CI 分档更新

| 触发 | 测试集 | LLM？ |
|------|--------|-------|
| PR | unit + contract + a11y smoke + security headers | 否 |
| Nightly | benchmark + WAL concurrency + mixed-capability matrix + VCR eval | 是（$50/月） |

**影响 Task**: Task 7/18（prompt/VCR/benchmark 门禁升级）、Task 13-15（serve/static 双态测试）、新增 serve 测试子任务

---

## 五、用户体验（**取消冻结**）

### 原评分: C+ → 改进后目标: **B+**

**🔧 `ahadiff serve` 完整设计（Gemini 主导 + Claude 综合）**:

#### 改进 U1: `ahadiff serve` 核心设计

**框架**: Starlette + Uvicorn（最小 ASGI，无 FastAPI 开销）

**API Endpoints**:

| Method | Path | 功能 | 模式 |
|--------|------|------|------|
| GET | `/api/runs` | 聚合 run 数据（dashboard） | serve |
| GET | `/api/queue` | 获取 due SRS cards | serve |
| POST | `/api/cards/{id}/review` | 提交 SRS 评价（Good/Hard/Easy/Again） | serve |
| POST | `/api/claims/{id}/mark-wrong` | 记录 claim 反馈 | serve |
| GET | `/api/status` | `ahadiff learn` 进度轮询（客户端 1s interval，避免 SSE 单 worker 阻塞） | serve |

**Progressive Enhancement**: 同一 Jinja2 模板通过 `data-mode="serve|static"` 属性区分：
- **serve 模式**: Vanilla JS 绑定 `fetch()` 异步调用 API
- **static 模式**: JS 降级为 clipboard copy handler，显示 CLI 命令

#### 改进 U2: 交互设计

| 交互 | serve 模式 | file:// 模式 |
|------|-----------|-------------|
| Quiz Good/Hard/Easy | 按钮直接 POST → 卡片动画移出 | 按钮显示 `ahadiff review --answer good` + one-click copy |
| Mark wrong | 内联按钮 → toast 确认 | 显示 `ahadiff mark <claim_id> wrong` + copy |
| Dashboard scores | 实时聚合图表 | 静态快照 + `ahadiff dashboard` 提示 |
| SRS review queue | 翻牌交互 → 评价按钮 | 只读展示 due cards |

**前端技术**: 零构建 Vanilla JS（ES6+），native Fetch API，事件委托，Optimistic UI。

#### 改进 U3: Onboarding 对齐

- `ahadiff init` → 自动检测 `.ahadiff/` 不存在时引导初始化
- 首次 `ahadiff serve` → dismissible welcome banner 解释交互能力
- Task 1 的 `init_cmd` 输出与 Viewer onboarding 页面**文案严格对齐**

#### 改进 U4: A11y 完整方案

| 项目 | 实现 |
|------|------|
| 语义化 HTML | `<button>` 用于 API 提交，`<form>` 用于表单 |
| ARIA | `aria-live="polite"` 用于 toast/进度，`aria-pressed` 用于 toggle |
| 焦点管理 | `:focus-visible` + Clay Orange ring，逻辑 tab 顺序 |
| 对比度 | `--muted-2` 加深至 #7A7463（WCAG AA） |
| 响应式 | 375/768/1024/1440px 四断点，移动端 diff 默认折叠 |
| reduced-motion | `@media (prefers-reduced-motion: reduce)` 禁用动画 |

#### 改进 U5: 设计系统

| Token | 值 | 用途 |
|-------|-----|------|
| Primary | Clay Orange #D27050 | accent, 按钮, 焦点 |
| Paper bg | #FAF8F2 | 主背景 |
| Subtle bg | #F2EFE7 | 卡片背景 |
| Success | #2F6F4F | verified claim |
| Warning | #B4791F | weak claim |
| Danger | #A33D2B | contradicted/rejected |

排版: Newsreader/Noto Serif SC（prose）+ Inter（UI）+ JetBrains Mono（code）
动画: 0.15s hover transition，CSS 3D SRS 翻牌（`perspective: 1200px`），无弹性动画
Dark mode: **v0.2**（v0.1 专注 paper-like light theme）

#### Task 计划更新

| Task | 变更 |
|------|------|
| Task 13 | 增加 serve/static context flag + `app.js` API 通信层 |
| Task 14 | 增加 SRS Queue 页面 + API-driven Dashboard |
| **新增 Task 14.5** | **Serve Backend**（详见下方完整规格） |

#### Task 14.5 完整规格: Serve Backend

- **类型**: 后端（Codex 实现）
- **文件范围**:
  - `src/ahadiff/serve/app.py`（ASGI app factory）
  - `src/ahadiff/serve/routes.py`（REST endpoint handlers）
  - `src/ahadiff/serve/middleware.py`（CSP + TrustedHost + CORS）
  - `src/ahadiff/serve/state.py`（AppState + db_write_lock）
  - `tests/integration/test_serve.py`
- **依赖**: Task 12（Ratchet query service）+ Task 15（review.sqlite schema）
- **不可写文件**（属其他 Task 所有）: `viewer/templates/`（Task 13）、`viewer/pages/`（Task 14）、`review/database.py`（Task 15）
- **实施步骤**:
  1. 实现 Starlette app factory + Uvicorn 启动（单 worker，`host=127.0.0.1`）
  2. 实现统一 REST API contract（与 static data_bundle 共享 query DTO）:
     - GET `/healthz`, `/api/runs`, `/api/runs/{id}`, `/api/queue`, `/api/history`
     - POST `/api/cards/{id}/review`, `/api/claims/{id}/mark-wrong`
  3. 实现 `asyncio.Lock` 写串行化 + SQLite WAL `busy_timeout=5000`
  4. 实现进度轮询 endpoint `GET /api/status`（替代 SSE，避免单 worker 阻塞）
  5. 实现 CSP nonce middleware + TrustedHost middleware
  6. 实现 `ahadiff serve [--port 8765] [--open]` CLI 子命令
- **验收标准**: `ahadiff serve` 启动后浏览器可交互答题，POST 写入 review.sqlite 可验证
| Task 4 | 扩展 responsive 覆盖新交互元素（SRS 翻牌、toast、drawer） |

**影响 Task**: Task 1（init_cmd 与 onboarding 对齐）、Task 13-14（双适配器）、新增 Task 14.5

---

## 六、灵感借鉴准确性

### 原评分: A- → 改进后目标: **A**

### 源码事实核验 100% 通过，映射层区分"采用/改造/未采用"

| 灵感项目 | 声明 | 状态 | 分类 |
|---------|------|------|------|
| autoresearch | 三文件契约 → N-文件变体 | ✅ | 采用+扩展 |
| autoresearch | val_bpb + git ratchet | ✅ | 采用（8 维替代单指标） |
| autoresearch | 无 Phase 2.5 | ✅ | 确认不存在 |
| autoresearch | prepare.py → evaluation bundle（非单一 evaluator.py） | ✅ | 精确映射 |
| autoresearch | train.py → prompts/ 目录树（非单一 prompt 文件） | ✅ | 精确映射 |
| darwin-skill | 8 维 rubric（结构 60 + 效果 40） | ✅ | 采用（权重自研） |
| darwin-skill | Phase 2.5 触发阈值（连续 2 个在 round 1 就 break） | ✅ | 采用 |
| darwin-skill | Phase 2.5 需用户同意 | ⚠️ | **有意改造**: AhaDiff 改为自动触发 + 1 次/session 限频 |
| darwin-skill | git stash 保存 + 从头重写 | ✅ | 采用（改用 worktree） |
| darwin-skill | 有 screenshot.mjs 辅助脚本 | ✅ | 确认存在 |
| SkillCompass | 6 维评估（D1-D6） | ✅ | 采用（扩展为 8 维） |
| SkillCompass | PASS≥70, CAUTION 50-69, FAIL<50 | ✅ | 采用（提高为 80/60） |
| SkillCompass | weakest-dimension-first | ✅ | 采用 |
| SkillCompass | targeted verification + D3/D4 守门 | ⚠️ | **有意改造**: AhaDiff 改为目标维度+accuracy+evidence+safety_privacy（4 维） |
| SkillCompass | snapshot/rollback 兜底 | ✅ | 采用（worktree 替代 snapshot） |
| graphify | repo-level map（AST+LLM→NetworkX→Leiden） | ✅ | 采用（commit-level overlay） |

**改进**: 所有映射明确标注"采用/有意改造/未采用"三态，消除模糊空间。

---

## 七、Corner Cases 闭环程度

### 原评分: B- → 改进后目标: **B+**

**🔧 全部未闭合项闭合（Codex 主导）**:

#### 改进 CC1: Mixed-capability history — 三 Lane 模型

| Lane | 数据范围 | 展示位置 | 参与 ratchet？ |
|------|---------|---------|---------------|
| `L3_git_ratchet` | capability_level=3, degraded_flags 为空 | Dashboard headline | ✅ |
| `L3_degraded_observation` | capability_level=3, degraded_flags 非空 | Dashboard 辅助层（灰色点）+ "All Runs" | ❌（可见但不推动 baseline） |
| `L2_workspace_compare` | capability_level=2 | "All Runs" + 审计页 | ❌ |
| `L1_patch_only` | capability_level=1 | "All Runs" + 审计页 | ❌ |

- **Lane 与 degraded 正交建模**: capability_level 决定 lane，degraded_flags 决定 lane 内子分类
- 同一 `source_ref` 同时有高/低能力记录 → 最高 capability 为 canonical
- 默认 dashboard 只展示 `L3_git_ratchet`；`L3_degraded_observation` 显示为灰色辅助点
- `/api/history` 的 lane filter 支持: `?lane=L3&include_degraded=false`（默认）

#### 改进 CC2: Cross-Level 趋势规则

- 只在**同 lane、同 eval_bundle_version、同 prompt_version** 可比前提下画 delta arrow
- Lane 变化时只画散点，不画涨跌
- Degraded run 永不推动 baseline，显示为灰色辅助点

#### 改进 CC3: Squash/cherry-pick 可诊断通知

每个 run 额外存 `patch_id` 和 `head_tree`：
- `source_ref` 不可达但 `patch_id` 或 `tree hash` 找到等价提交 → 显示 `history_rewritten_to=<new_sha>`
- 完全找不到 → 标记 `orphaned_by_history_rewrite` + 提示 re-anchor/accept stale
- 用户看到的是"历史改写"而非"数据丢失"

#### 改进 CC4: Cross-file rename 两段式检测

1. **第一段**: 吃 git rename metadata（`old_path → new_path`）
2. **第二段**: symbol body fingerprint + parent scope + hunk overlap 复核
3. 唯一候选且相似度过阈值 → `renamed_across_file`
4. 否则 → `ambiguous_move`（禁止当稳定证据链锚点）

#### 改进 CC5: 所有 corner case 闭合状态（更新）

| Corner Case | 闭合状态 | 改进 |
|------------|---------|------|
| Quiz staleness | ✅ 闭合 | 保持（CardState 三态 + anchor 惰性检测） |
| Branch-aware concepts | ✅ **改为闭合** | CC3 提供 squash/cherry-pick 诊断通知 |
| Degraded run ratchet | ✅ **改为闭合** | E4 定义 degraded 永不提升 baseline |
| Rename/move symbol | ✅ **改为闭合** | CC4 两段式检测 + ambiguous_move 降级 |
| Mixed-capability history | ✅ **改为闭合** | CC1 三 Lane 模型 |
| VCR shared partial | ✅ 闭合 | 保持 |
| Concurrent improve | ✅ 闭合 | 保持 |
| Graphify freshness | ✅ **改为闭合** | A3 七态状态机 + 7→4 映射冻结 |
| L3 degraded 归属 | ✅ **新增并闭合** | CC1 四 Lane 正交模型（L3_degraded_observation 子 lane） |

---

## 约束集（v2 完整版）

### 硬约束
- [HC-1] 所有冻结决策在 Task 0 的 contract-freeze.md 有可执行定义 — 三模型共识
- [HC-2] 脱敏顺序用 `redaction_pipeline()` 统一入口强制 — Codex+Claude
- [HC-3] Layer 7 不得直写 review.sqlite，必须走 Layer 5/6 接口 — Codex
- [HC-4] Graphify 是可选依赖，缺失不影响核心链路 — Codex
- [HC-5] 非 git run 禁止参与 ratchet 比较，标记 non_ratcheted — 三模型共识
- [HC-6] evaluation bundle 5 文件联合 hash，任一变更触发 VCR cassette 失效 — 三模型共识
- [HC-7] `ahadiff serve` 默认绑定 `127.0.0.1`，不开放 `0.0.0.0` — Codex
- [HC-8] ratchet_eligible = capability_level==3 且 degraded_flags 为空 — Codex
- [HC-9] Dashboard headline 只展示 L3_git_ratchet lane — Codex

### 软约束
- [SC-1] Layer 5/6/7 服务接口在 Task 0 冻结 — Codex
- [SC-2] 三层锁模型（repo_write/run_write/db_write） — Codex
- [SC-3] 版本标识符优先级表冻结（rubric_version 降级为派生字段） — Codex
- [SC-4] note 字段改为 note_json（JSON 格式） — Codex
- [SC-5] SIGINT handler 工程化处理（非 crash 语义） — Codex
- [SC-6] 性能阈值量化（capture 2000/5000/10000 lines 等） — Codex
- [SC-7] serve 单 worker + asyncio.Lock + PASSIVE checkpoint — Codex
- [SC-8] CSP: serve 用 nonce，static 用 hash — Codex+Gemini
- [SC-9] VCR cassette 双向脱敏（录制前 + 录制后） — Codex
- [SC-10] Graphify 导入走 Pydantic 校验 + sanitized gate — Codex
- [SC-11] LLM 输出双重约束（Pydantic strict + Markdown sanitizer） — Claude
- [SC-12] Progressive enhancement: data-mode="serve|static" — Gemini
- [SC-13] A11y: Playwright+axe-core 门禁 + WCAG AA 对比度 — Gemini
- [SC-14] 中英 README 核心字段定期对齐 — Gemini
- [SC-15] Task 1 init_cmd 与 Viewer onboarding 页面文案对齐 — Gemini
- [SC-16] Mixed-capability 矩阵测试覆盖 — Codex
- [SC-17] CI prompt 依赖图 + orphan include 检测 — Codex

### 依赖关系
- [DEP-1] Task 0 → 所有下游: schema + 接口契约是全局前置依赖
- [DEP-2] Task 5 → Task 6 → Task 8: 捕获→解析→验证串行
- [DEP-3] Task 7 → Task 8/9/11/18: Provider 是独立骨干
- [DEP-4] Task 11 → Task 12 → Task 15 → Task 16 → Task 17: 评估→棘轮→数据库→改进→Phase 2.5
- [DEP-5] Task 13/14/14.5 依赖上游 artifact 稳定
- [DEP-6] Task 14.5 (serve backend) 依赖 Task 15 (review.sqlite schema)

### 风险
- [RISK-1] Layer 7 误绕过 Layer 5/6 直写数据库 — Codex（High）→ 代码审查规则卡死
- [RISK-2] VCR cassette 失效漂移 — Codex（Medium）→ CI prompt 依赖图
- [RISK-3] serve/static 双态并行测试暴露数据装配差异 — Codex（Medium）→ 短期失败率上升
- [RISK-4] Graphify 七态状态名过多，UI 文案需简化 — Codex（Low）→ 默认只展示简单分组
- [RISK-5] CSS 单体拆分为 Jinja2 模板时样式破碎 — Gemini（Medium）→ 逐步提取
- [RISK-6] 单 worker 限制吞吐 — Codex（Low）→ 有意换取 v0.1 稳定性
- [RISK-7] Markdown allowlist 过严可能损伤展示效果 — Codex（Low）→ 可接受的安全换取

## 开放问题（需用户决策）
- Q1: degraded run 在"All Runs"审计页中显示多少细节？（完整 vs 仅 summary）

## 工程决策（已收口）
- ED-1: 锁粒度 → 三层锁模型（已定义）
- ED-2: note 字段 → JSON 格式（已定义）
- ED-3: viewer → serve + static 双模式（已取消冻结，设计完成）
- ED-4: 性能阈值 → 量化数字（已定义）
- ED-5: SIGINT 处理 → 工程化（已定义）

## 总结

| 维度 | 原评分 | 改进后 | 关键改进 |
|------|:------:|:------:|---------|
| 架构合理性 | B+ | **A** | Layer 5/6/7 服务契约 + serve 双适配器 + Graphify 7 态 |
| 工程完备性 | B- | **A-** | 三层锁 + 版本优先级表 + note_json + SIGINT 工程化 + 量化阈值 |
| 安全性 | B+ | **A** | 全部侧信道闭合 + serve 安全默认值 + CSP nonce |
| 测试策略 | B | **A-** | 矩阵测试 + a11y 门禁 + serve endpoint 测试 + WAL 并发回归 |
| 用户体验 | C+ | **B+** | `ahadiff serve` + Progressive Enhancement + SRS 翻牌交互 |
| 灵感借鉴 | A- | **A** | 全部映射标注"采用/有意改造/未采用"三态 |
| Corner Cases | B- | **B+** | 四 Lane 正交模型 + 两段式 rename + squash/cherry-pick 诊断（8/8 闭合） |

**三模型共同结论**: 经 v2 深度改进后，所有维度均达到 A-/A/B+ 水平。最大的结构性变化是取消静态 viewer 冻结，引入 `ahadiff serve`（Starlette+Uvicorn），通过 Progressive Enhancement 实现 serve/static 双模式无缝切换。后端通过三层锁模型、版本优先级表、note_json 和 SIGINT 工程化处理闭合了全部工程缺口。安全通过 CSP nonce、双向 VCR 脱敏和 LLM 输出双重约束达到 A 级。Corner cases 通过三 Lane 历史模型和两段式 rename 检测全部闭合。

---

## 附录：v1 → v2 变更记录

| 时间 | 变更 |
|------|------|
| 2026-04-20 v1 | 初版三模型评估 + 双模型交叉审查 |
| 2026-04-20 v2 | 取消 UX 冻结，设计 `ahadiff serve`；全维度深度改进；Codex 后端五维度方案 + Gemini UX/serve 方案 + Claude 综合 |
| 2026-04-20 v2.1 | 双模型交叉审查修复 3 Critical + 6 Warning |
| 2026-04-20 v3 | **第三轮终审修复（Codex 4C+5W / Gemini 2C+3H+5M）**: (1) db_write_lock 升级为跨进程文件锁 + publish barrier + migration quiesce; (2) Layer 5/6/7 补充 query DTO 契约（7 个服务方法 + 分页 + 幂等）; (3) serve 安全升级（write token + Origin 校验 + 速率限制 + read-only 默认 + WebSocket 拒绝）; (4) Graphify equivalent 映射修复; (5) 须同步更新: CLAUDE.md + README.md/en + Task 13/14 删除"serve 推迟 v0.2"残留 + doc/ 旧文档标 archived |

---

## 附录 B：第三轮终审报告（v3 修复记录）

> 审查时间: 2026-04-20 | Codex + Gemini Round 3 终审

### 🔴 Critical（已修复 6 项）

| # | 发现者 | 维度 | 描述 | 修复 |
|---|--------|------|------|------|
| R3-C1 | Codex | ARCH | Layer 5/6/7 只冻结方法名，缺 query DTO、返回类型、错误枚举、分页 | ✅ 补充 7 个 query DTO + 幂等语义 |
| R3-C2 | Codex | ENG | db_write_lock 是 asyncio-only，CLI+serve 并发写无保护 | ✅ 升级为跨进程文件锁 + publish barrier + migration quiesce |
| R3-C3 | Codex | SEC | serve 写接口无 token/Origin/速率限制 | ✅ write token + Origin 校验 + token-bucket + read-only 默认 |
| R3-C4 | Codex | CONSISTENCY | Task 14 仍写"serve 推迟到 v0.2" | ⚠️ 须在开工前同步 Task 13/14/14.5 计划 |
| R3-C5 | Gemini | A11Y | SRS card back 未 aria-hidden，screen reader 破坏 active recall | ⚠️ 须在 Task 14 实现时强制 `aria-hidden="true"` + flip toggle |
| R3-C6 | Gemini | DOCS | README.md/en.md 严重过时，仍列 v0.2 为 HTMX | ⚠️ 须在开工前同步更新 |

### 🟡 Warning/High（须在开工前处理）

| # | 发现者 | 维度 | 描述 | 处理 |
|---|--------|------|------|------|
| R3-W1 | Codex | TESTING | 测试矩阵漏 /api/queue、/api/status，缺 DTO parity 回归 | 须补充 |
| R3-W2 | Codex | ARCH | context_freshness `equivalent` 值不可达 | ✅ 已修复映射 |
| R3-W3 | Codex | DATA | note_json 缺 schema_version、actor、lineage、evolution tracking | 须在 Task 0 扩展 |
| R3-W4 | Codex | UX | Progressive Enhancement 无 no-JS form fallback | 须在 Task 14 增加 form-POST + 303 redirect |
| R3-W5 | Codex | DOCS | CLAUDE.md + doc/ 多处残留旧决策（head_sha/git stash/review.db） | 须在开工前清理或标 archived |
| R3-W6 | Gemini | UX | Optimistic UI 缺 sendBeacon/keepalive，tab 关闭丢数据 | 须在 Task 14.5 使用 `fetch(url, {keepalive:true})` |
| R3-W7 | Gemini | UX | SPA routing 无 History API (pushState)，Back 按钮失效 | 须在 Task 14 实现 pushState + popstate |
| R3-W8 | Gemini | UX | DB locked 时无 error recovery UI（toast+rollback） | 须在 Task 14 定义 error toast 组件 |
| R3-W9 | Gemini | A11Y | Quiz feedback 缺 aria-live，mobile touch target < 48px | 须在 Task 4/14 补充 |
| R3-W10 | Gemini | UX | Dashboard 缺 0-runs empty state + CTA | 须在 Task 14 增加 |

### ✅ 已通过（双模型一致确认）
- ✅ SQLite event_id append-only 已落到任务计划
- ✅ worktree 统一隔离（improve + Phase 2.5）
- ✅ VCR 双向脱敏 + Graphify sanitized gate + LLM strict validation
- ✅ Graphify 新鲜度从 mtime 升级到 commit/tree 元数据
- ✅ SSE 已替换为 polling（单 worker 一致）
- ✅ source_ref/source_kind/capability_level 已回流主契约
- ✅ Progressive Enhancement 设计方向正确
- ✅ CSP + Vanilla JS 安全基线良好
- ✅ Typography/spacing/color tokens 与 Warm v6 一致

### 开工前必须完成的文档同步清单

| 文件 | 操作 | 要点 |
|------|------|------|
| `CLAUDE.md` | 更新 | 补充 serve、三层锁、Graphify 7→4 态、四 Lane、note_json、query DTO |
| `README.md` + `README.en.md` | 更新 | v0.1 包含 `ahadiff serve`，删除"v0.2 HTMX" |
| `ahadiff-v01-stages-4-9.md` Task 14 | 重写 | 删除"serve 推迟到 v0.2"，合并 serve/static 双适配器验收标准 |
| `doc/知返设计坐标.md` | 标 archived | 仍用 head_sha / git reset / review.db |
| `doc/最终完整方案.md` | 标 archived 或更新 | results.tsv 列数和字段名过时 |

### 审查结论

**Codex 评分**: Readiness 68/100 → 修复后预计 85+
**Gemini 评分**: 85/100 (NEEDS_IMPROVEMENT → 修复后 PASS)

**所有 6 个 Critical 中 3 个已直接修复于报告内，3 个标记为"开工前必须完成"。10 个 Warning/High 均有明确处理方案。**

报告可作为 v0.1 开发的权威综合评估稿，但**开工前须完成文档同步清单中的 5 项更新**。
