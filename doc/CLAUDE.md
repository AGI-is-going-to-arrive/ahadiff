[根目录](../CLAUDE.md) > **doc**

# doc -- 设计文档模块

## 模块职责

存放知返 AhaDiff 的产品设计文档，包括完整架构方案、品牌改名决策、前端视觉与交互手册，以及当前生效的 `contract-freeze.md` 契约权威源。这些文档是整个产品从理念到实现的蓝图。

## 入口与启动

本模块为纯文档，无可执行入口。直接阅读 Markdown 文件即可。

## 对外接口

无代码接口。文档内容供产品开发、UI 设计和 Claude Design / Stitch 投喂使用。

## 关键依赖与配置

无外部依赖。Markdown 文件可用任意编辑器或阅读器打开。

前端设计手册（`AhaDiff_frontend_design_v1.1_revised.md`）使用 Pandoc YAML frontmatter，含 XeCJK 中文排版配置，可通过 Pandoc 编译为 PDF。

## 文件详解

### 1. `contract-freeze.md` -- Stage 0 契约冻结（当前权威源）

**核心内容**：收口 Stage 0 / Task 0 已冻结的架构契约，作为当前唯一架构权威源。

- **冻结范围**：`RunStatus` / `ClaimStatus` / `CardState` / `RunSource` / `EvaluationBundle` / `result_events` / `ProviderConfig` / `ProviderCapabilities` / `UsageEvent` / `LearnabilityGate` / `Orchestrator` / `Serve` / SQLite / 锁矩阵 / Graphify 边界
- **代码对应面**：`src/ahadiff/contracts/*.py`
- **当前验收**：`uv run pytest tests/unit/test_contracts.py -q`，本次实际结果 `39 passed`
- **适用边界**：当前只冻结 Stage 0 最小 importable contracts，不提前覆盖 Stage 1 之后的运行时实现

### 2. `ahadiff设计思路.md` -- 早期架构快照（⚠️ ARCHIVED）

**核心内容**：从 3 天 MVP 到 v1.0 的完整演进方案。多处术语和设计决策已过时，权威文档见 `CLAUDE.md` + `.claude/team-plan/`。

- **前端三种形态选型**：A 纯 CLI+HTML（MVP 推荐） / B CLI+Textual TUI（v0.3） / C CLI+Web Dashboard（v1.0）
- **6 个灵感项目真机借鉴**（经源码验证修正）：
  - autoresearch：三文件契约（概念改编，原版 prepare.py + train.py），单指标 `val_bpb`，git ratchet 棘轮，简洁性准则。**无 Phase 2.5 或 stuck 检测**
  - SKILL0：helpfulness-driven retention，三段式学习撤架（budget 阶段跳变 [6,3,0]，非线性递减），<0.5k token compact card。helpfulness 原版 file 级，AhaDiff 扩展到 section 粒度
  - darwin-skill：8 维 rubric（总分 100，结构 60 + 效果 40），Phase 2.5 探索性重写（连续 2 个 skill 在 round 1 就 break 时触发），子 agent 对照评测。**零可执行代码**
  - SkillCompass：PASS/CAUTION/FAIL 三档门限（原版 70/50，AhaDiff 调高为 80/60），D3 Security 硬 gate，weakest-dimension-first。原版 6 维评估 skill 文件质量，AhaDiff 自研 8 维评估学习笔记质量
  - Graphify：repo-level map（AhaDiff 做 commit-level learning overlay），标准 NetworkX node-link-data 格式
  - LLM Wiki (Karpathy Gist)：persistent compounding wiki，AhaDiff 落地为 `index.md` + `concepts.jsonl` 增量积累
- **12 模块分层**：cli / diff.parser / concept.extractor / wiki.generator / graph.renderer / deck.exporter / render.jinja / eval.evaluator / eval.ratchet / llm.provider / persistence.store / config
- **8 维自研 Rubric**（非来自 SkillCompass）：accuracy(20) / evidence(18) / diff_coverage(14) / learnability(14) / quiz_transfer(10) / spec_alignment(10) / conciseness(8) / safety_privacy(6) = 100 分
- **测试策略**：单元(VCR) + 集成(pinned diff E2E) + Eval(benchmark + judge 稳定性) + 覆盖率门禁 + 性能成本
- **风险清单**：15 项，包含命名冲突（极高概率）、litellm 供应链事件、prompt injection 等
- **3 天 MVP 行动清单**：Day 1 核心链路 / Day 2 评估棘轮 / Day 3 可视化+CI

### 3. `知返ahadiff改名后的后续方案.md` -- 改名过渡方案（⚠️ ARCHIVED）

**核心内容**：从 AntiVibe Tutor 改名为 知返 AhaDiff 后的全面产品升级方案。多处设计已演进，当前权威来源见 `.claude/team-plan/`。

- **品牌系统**：中文名"知返"，英文名"AhaDiff"，CLI `ahadiff`，Logo 方向 `Δ知` 或 `Δ↺`
- **6 个灵感项目纳入策略**：每个项目具体落地到 AhaDiff 的方式
- **5 个必须补齐的关键设计**：
  1. 增量更新（不重复生成 95% wiki）
  2. 学习深度参数（beginner / intermediate / senior）
  3. Spec-before-code（计划-实现-学习闭环）
  4. Graphify 兼容（repo map + diff learning overlay）
  5. 不确定性标记（verified / weak / not_proven / contradicted）
- **Claim Verifier 设计**：deterministic verifier + LLM judge 双层验证
- **最终命令体系**：plan / learn / verify / improve / quiz / review / graph / install / card / export
- **前端 PDF 9 处必改**：品牌替换、页面重命名、hero 重写、技术栈版本更新等
- **最终数据结构**：claims.jsonl / score.json / review.sqlite / results.tsv

### 4. `AhaDiff_frontend_design_v1.1_revised.md` -- 前端视觉与交互手册

**核心内容**：3 风格 x 11 页面 = 33 个可生成界面的完整设计规范。

- **品牌**：知返 AhaDiff，"AI 写完，Diff 教回。"
- **五条设计公理**：Evidence first / Learning over summary / Local-first trust / Paper-like seriousness / One accent per style
- **三风格 DNA**：
  - Minimal（瑞士研究报告）：Ink Green `#2F6F4F`，Geist + Source Serif
  - Warm（Anthropic 纸感，默认）：Clay Orange `#D97757`，Inter + Newsreader
  - Editorial（精品出版物）：Terracotta `#C66B3D`，Inter + Fraunces
- **11 页面**：Landing / Runs Dashboard / Lesson Reader / Diff+Evidence Viewer / Ratchet Lab / Socratic Quiz / SRS Review / Settings / Onboarding / Agent Skill Hub / Learning Graph Explorer
- **Design Tokens**：语义层 CSS 变量
- **技术栈**：v0.1 使用 React 19 + Vite + vanilla CSS（见 `CLAUDE.md`）；手册中的 Next.js/Tailwind/shadcn 描述仅适用于 v1.0 参考
- **7 轮 Claude Design 投喂流程**
- **20 条一致性 Checklist**

## 数据模型

无运行时数据模型。文档中规划的核心数据结构：

| 数据文件 | 格式 | 用途 |
|----------|------|------|
| `review.sqlite` | SQLite (WAL) | 唯一真相源：SRS cards / result_events / learning_signals |
| `claims.jsonl` | JSONL | 可验证断言，含 source_hunks / status / confidence |
| `score.json` | JSON | 8 维评分 + verdict + hard_gates |
| `judge.json` | JSON | 可选 LLM judge 8 维评分；仅配置 `judge_provider` 后生成，不替代 `score.json` |
| `results.tsv` | TSV | 人类可读导出视图，11 列（从 review.sqlite 导出） |
| `concepts.jsonl` | JSONL | branch-aware 概念累积（per-repo） |
| `audit.jsonl` | JSONL | LLM 调用审计（schema_version + rotation） |
| `audit.private.jsonl` | JSONL | `strict_local` 下的本机隐私审计（gitignored） |
| `.ahadiff/improve/<session_id>.json` | JSON | Task 16 improve session 状态：suite、anchor_run_id、rounds_completed、worktree_path、phase25_attempted、outcome_statuses、interrupted_round、interrupted_stage |

### 数据范围

CLI 全局安装（`pip install ahadiff`），per-repo 运用。核心原则：**per-repo truth + global derived governance**。

- **Per-repo 真相源**（`<repo>/.ahadiff/`）：review.sqlite / concepts.jsonl / audit.jsonl / audit.private.jsonl / runs/ / graphify/ / prompts/
- **Global 派生层**（`~/.config/ahadiff/` 等）：config.toml / registry.json(v0.2) / usage.sqlite(v0.2)
- **Config 优先级**：ENV → CLI flag → per-repo config.toml → global config.toml → defaults

## 测试与质量

文档通过人工评审和 AI 辅助迭代完成质量保障。前端设计手册包含 20 条自查 Checklist。

当前仓库最近一轮实测（2026-05-07，本 session）：targeted parser / judge / orchestrator / lesson 回归 `230 passed in 11.67s`；后端完整 gate 为 `UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run --frozen --no-sync pytest --tb=short` = `1993 passed, 1 skipped in 178.87s (0:02:58)`；`ruff check src tests`、`ruff format --check src tests`、`pyright` 和 `git diff --check` 通过。真实 WebUI learn run 使用 `gpt-5.5` 生成和 judge，成功生成 lesson，`score.json=94.96/PASS`，`judge.json model_id=gpt-5.5`，浏览器 console 无 error/warn；显式 live judge smoke `AHADIFF_LIVE_LLM_JUDGE=1 ... AHADIFF_LIVE_LLM_MODELS=gpt-5.5 ... pytest tests/live/test_llm_judge_live.py -q` = `1 passed in 4.30s`。coverage gate 上一次同日结果仍为 `87.33%`；本轮未重跑 coverage、前端 build 或全量 Playwright。

## 常见问题 (FAQ)

**Q: 为什么从 AntiVibe 改名？**
A: GitHub 已有功能近乎 1:1 重叠的 `mohi-devhub/antivibe`，"Antivibe" 是至少 3 家公司的注册商标，且 Substack 有同名框架预告。改名为 知返 AhaDiff 避免命名冲突。

**Q: N-文件契约具体指什么？**
A: 概念改编自 Karpathy/autoresearch 三文件契约（原版为 prepare.py + train.py，改 Python 代码）。AhaDiff 版本（N-文件契约）：`program.md` / `improve_program.md`（自然语言状态机，人类写）+ evaluation bundle（不可改的评估尺子）+ 可写 prompt 白名单（当前为 `lesson_generate.md`、`lesson_hint.md`、`lesson_compact.md`、`quiz_generate.md`、`claim_extract.md`，agent 只改这些 Markdown prompt）。`eval_judge.md` 是 packaged prompt resource，用于可选 LLM judge，不属于 improve loop 可写白名单。核心循环由 Python CLI 编排，但可变面仍限制在 prompt，不改用户代码。

**Q: 文档间的阅读顺序？**
A: 当前先读 `contract-freeze.md`，再读根目录 `CLAUDE.md` 和 `.claude/team-plan/`（kickoff + stages-4-9 + implementation plan）。前端视觉见「前端设计手册」。早期三份文档（设计思路/改名方案/最终方案）已归档，仅供历史参考。

## 相关文件清单

| 文件 | 行数 | 说明 |
|------|------|------|
| `contract-freeze.md` | ~800 行 | Stage 0 当前权威契约总表 |
| `ahadiff设计思路.md` | ~630 行 | [ARCHIVED] 早期架构快照 |
| `知返ahadiff改名后的后续方案.md` | ~530 行 | [ARCHIVED] 改名过渡方案 |
| `ahadiff 最终完整方案：*.md` | ~2500 行 | [ARCHIVED] 最终完整方案（31 节 + 9 段开发顺序） |
| `AhaDiff_frontend_design_v1.1_revised.md` | 1500 行 | 前端视觉与交互手册（v0.1=React 19+Vite / v1.0=PWA 增强，可编译 PDF） |
| `知返设计坐标.md` | ~100 行 | 早期设计快照（**已归档**，多处术语过时） |
| `COMPREHENSIVE-EVALUATION-REPORT.md` | ~240 行 | 综合评估报告（方案 9.0/10，UI 8.7/10） |
| `SOURCE-CODE-VERIFICATION-REPORT.md` | ~240 行 | 灵感项目源码验证报告（12 项修订） |
| `trending-ai-projects-research-2026.md` | ~240 行 | 趋势调研（无直接竞品） |
| `task16-deep-review.md` | ~280 行 | Task 16 improve loop 独立深度 review + post-fix addendum |
| `v1-graphify-compatibility-matrix.md` | ~350 行 | Graphify ↔ AhaDiff 当前兼容性矩阵与剩余 gap |
| `v1-serve-api-live-test-report.md` | ~220 行 | serve API 2026-04-27 live 快照 + 当前状态 note |
| `v1.0-backend-architecture-research.md` | ~1200 行 | v1.0 后端研究报告（保留 proposal，顶部 current note 对齐当前代码） |

## 变更记录 (Changelog)

| 时间 | 变更 |
|------|------|
| 2026-04-19 21:26:58 | 初始创建 doc/CLAUDE.md |
| 2026-04-20 | 同步根 CLAUDE.md 修订：修正灵感项目描述（6 项含源码验证结论）、8 维 rubric 归因、三文件契约描述、results.tsv 11 列方案（含 base_sha） |
| 2026-04-20 | 补充新增文档条目：最终完整方案、综合评估报告、源码验证报告、趋势调研 |
| 2026-04-20 | 术语同步：三文件契约→N-文件契约（描述 AhaDiff 自身设计时）、evaluator.py→evaluation bundle、四状态→五状态（含 rejected） |
| 2026-04-21 | 同步 v5 改进：evaluation bundle 统一为 5 文件（含 rubric.py）、note→note_json、前端设计手册标注 v0.1=Jinja2/v1.0=React、知返设计坐标.md 标 archived、i18n 骨架补 rejected 第五态 |
| 2026-04-21 | 同步 v6 三模型交叉审查：设计思路/改名方案/最终方案三文档标 ARCHIVED、文件清单描述更新 |
| 2026-04-21 | 同步第三轮开工就绪审查：新增数据范围架构（per-repo truth + global derived governance）、数据模型补 review.sqlite/concepts.jsonl/audit.jsonl、Config 5 层优先级链 |
| 2026-04-21 | 同步本轮契约收敛：补 `audit.private.jsonl` 本机边界、FSRS 撤架规则统一为 stability 驱动、VCR key 补 `api_family_version`、前端撤架命名统一为 Compact、测试口径补 pinned integration + coverage gate |
| 2026-04-21 | 同步 Warm v6.2 模板细化：safe-area/meta、语义 token、统一 easing/duration、scroll / focus / print / 高对比 / reduced-transparency / 触控目标等前端实现约束补入手册与 Stage 文档 |
| 2026-04-21 | 同步 Warm v6.x `editorial-terminal` overlay：字体 weight ramp、FOLIO / verified 印章 / serif page-head / tabular italic numerals / inkstone CTA，以及 focus / print / forced-colors / reduced-transparency 的增强规则补入前端手册；`CLAUDE.md`、`ui/CLAUDE.md` 与 Task 13 参考口径同步更新 |
| 2026-04-22 | 新增 `contract-freeze.md` 为当前权威源；同步根文档与 README 口径到 Stage 0 已完成；记录当前实测 `python3 -m pytest tests/unit/test_contracts.py` = `19 passed` |
| 2026-04-22 | 同步本轮 Stage 0 contract 收口：`peeked_this_session` 改为不参与持久化 dump、`ClaimRecord` 补 `status/reason_code` 联动约束、`source_hunks` 补最小 entry 结构、`fsrs_state` 补合法 JSON object 约束、`Task 13` 验收改为 build + mock/proxy、不再硬依赖 `ahadiff serve` |
| 2026-04-22 | 同步本轮 Stage 1 / Task 2 文档口径：根 README / README.en / CLAUDE 与 team-plan 当前状态更新为 Task 1 + Task 2 已落地；补入 `src/ahadiff/safety/`、4 份安全层单测、`.ahadiffignore` repo 根位置，以及本次真实实测 `tests/unit = 61 passed`、Task 2 目标测试 `26 passed` |
| 2026-04-22 | 同步本轮 Stage 2 / Task 5 文档口径：根 README / README.en / CLAUDE、`ahadiff-v01-kickoff.md` 与 `ahadiff-v01-implementation-plan.md` 更新为 Task 5 已落地；补入 `src/ahadiff/git/{__init__,repo,capture}.py`、`tests/unit/test_git_capture.py`、当前实测 `tests/unit = 87 passed` / `test_git_capture.py = 26 passed`，以及 non-git `unlock --force` 与 non-`--dry-run` `learn` 的最新 CLI 行为 |
| 2026-04-23 | 同步本轮 Stage 2 / Task 9/11/12 与随后 hardening：README / README.en / 根 CLAUDE / doc/CLAUDE / contract-freeze / stages-4-9 已统一到当前代码口径；补入 `score` / `verify` / `export-results`、lesson 三档生成、8 维 evaluator、`review.sqlite` / `results.tsv` / `finalized.json` 发布链路、`prompt_version` 绑定 AhaDiff 自带 prompt 资源、`learn` 写入 `event_type=learn`、最近祖先 baseline 选择、partial lesson 不再误拿 `PASS`，以及本次真实实测 `tests/unit = 326 passed`、`ruff check` / `ruff format --check` / `pyright` / `uv build --wheel` 全通过和 clean-room wheel smoke 通过。 |
| 2026-04-24 | 同步本轮 Task 15 文档口径：README / README.en / 根 CLAUDE / 本文档 / Task 15 cross-review report 已统一到当前代码口径；补入 `src/ahadiff/review/{__init__,database,scheduler,schemas,signal}.py`、`tests/unit/{test_review,test_review_scheduler_extra}.py`、`ahadiff review` / `ahadiff mark` / `ahadiff db` 当前可用事实，以及本轮真实修复的 review.sqlite 边界（`stale_reason` 迁移、schema-invalid cards warning、regenerate stale 化、card_state/anchor DB 约束、monotonic UUID v7、single-connection lossy import、duplicate lossy identity fail-fast、rollback delete+export rows 单连接、`connect_review_db()` 不再静默建目录）；本次真实实测 `tests/unit = 383 passed`，`ruff check` / `ruff format --check` / `pyright` / `uv build --wheel` 全通过。 |
| 2026-04-24 | 同步本轮 Task 16 文档口径：README / README.en / 根 CLAUDE / AGENTS / contract-freeze / stages-4-9 / Task 16 review 报告已统一到当前代码口径；补入 `src/ahadiff/improve/{__init__,loop,program}.py`、`prompts/improve_program.md`、`src/ahadiff/prompts/improve_program.md`、`tests/unit/test_improve_loop.py`、`ahadiff improve --suite local --rounds N` / `--resume` 当前可用事实，以及本轮真实修复的 improve loop 边界（5 个 mutable prompt 白名单、session_id 校验、30min replay timeout、双 prompt temp+replace 写入、discard/pending conflict 不 finalized、pending conflict 不进 baseline、volatile diff 从 `patch.diff` 重放、短 worktree 路径、`--rounds` 上限 20、null byte 拒绝、Ctrl+C 不再 double append）；本次真实实测 `test_improve_loop.py = 14 passed`、目标回归 `56 passed`、`tests/unit = 397 passed`，`ruff check` / `ruff format --check` / `pyright` / `uv build --wheel` / `python -m ahadiff improve --help` 全通过。 |
| 2026-04-24 | 同步本轮 Stage 6 Task 14.5/18/19/20 + i18n-0 review 修复口径：README / README.en / 根 CLAUDE / AGENTS / stages-4-9 / implementation plan / Stage 6 cross-review report 已统一到当前代码和测试；补入 serve backend、benchmark、6 个 install target、GitHub Action 模板、`AHADIFF_PROVIDER_API_KEY`、locale resolver、prompt output language helper、live judge 默认模型顺序 `gpt-5.3-codex-spark,gpt-5.4-mini`；后续 pinned integration cards fixture 已改为生产 `generate_cards_for_run()` 路径并逐行校验 `ReviewCard` schema；本次真实实测 unit `461 passed`、eval `7 passed`、pinned integration `10 passed`、quiz/review `38 passed`、全量 tests `478 passed, 1 skipped`、live judge `1 passed`，且 `gpt-5.3-codex-spark` 已单独确认可用；`ruff check` / `ruff format --check` / `pyright` / `uv build --wheel` / `python -m ahadiff install github-action --help` 全通过。 |
| 2026-04-25 | 同步本轮 LLM cache key 后端边界口径：README / README.en / 根 CLAUDE / AGENTS / kickoff / stages-4-9 / implementation plan 已统一到当前代码和测试；补入 `api_family_version` 已进入 `CacheKeyInput`、`build_cache_key()` 和 provider dispatch 的事实；本次真实实测 `test_provider.py` 36 passed、全量 tests 479 passed + 1 skipped、ruff check / ruff format --check / pyright / wheel build 全通过。 |
| 2026-04-30 | 同步当前工作树文档口径：根 CLAUDE / 本文档 / contract-freeze / serve / research / RFC 文档统一到当时真值；补入 `ClaimExtractor=tree_sitter`、`capture.symbol_extractor` 与 symbol extraction 顺序、`/api/graph/status` 的 imported graph 路径口径、TaskRunner 默认 600s + env/per-task timeout，以及当时后端实测 `pytest tests = 1479 passed, 1 skipped`、coverage `87.08%`、`pyright = 0 errors`、wheel build 成功。 |
| 2026-04-30 | 同步本轮 backend closure 口径：README / README.en / 根 CLAUDE / 本文档 / AGENTS / v1.0 execution plan 已统一到当前代码和测试；补入 BF-1~BF-5 已闭合、learn Step 10 发布边界、watcher restart/status、concepts DB/JSONL cursor、public search rank/order、auth bootstrap 前端前置合约，以及最新后端实测 `pytest tests = 1514 passed, 1 skipped`、`ruff check` 通过、touched-files format 通过、`pyright = 0 errors`。 |
| 2026-04-30 | 同步 Phase 2 gate follow-up 修复后口径：README / README.en / 根 CLAUDE / AGENTS / team-plan / serve live report / review report 已统一到当前代码和本 session 测试；补入 `/api/graph/concepts`、Settings / ConceptGraph 前置 DTO、SearchOverlay / Quiz peek guard / 1024px drawer / Diff path / API error redaction / CSP / lazy chunk budget，以及后端 `1526 passed, 1 skipped`、前端 `typecheck` / `lint` / unit `16 passed` / build / Playwright `1035 passed`、i18n `283/283`。 |
| 2026-05-01 | 同步最终 review-fix 口径：README / README.en / 根 CLAUDE / AGENTS / team-plan / 本文档已按当前代码和测试更新；补入 DNS pinning no-host/empty-pin/userinfo 边界、Graphify invalid node ID 丢弃、learn-store dismiss stale-submit guard、Topbar busy a11y/reduced-motion、LearnTaskBanner token fallback，以及后端 `1689 passed, 1 skipped`、`ruff check` / `ruff format --check` / `pyright` 通过、前端 unit `78 passed`、build 86,034 / 118,964 bytes。 |
| 2026-05-02 | 同步 viewer learn/graph follow-up：`learn-store` 增加 backoff / timeout / safe retry / cancel/recovery 保护，`graph-store` 作为 GraphifyCard 共享 freshness cache，task schema 对齐后端 status enum；本轮前端 unit `118 passed`、目标 Learn E2E `8 passed`、i18n `458/458`，当前 Playwright 配置 `1440 tests`，完整 Playwright/build 未在 follow-up 后重跑。 |
| 2026-05-02 | 同步 Phase 6B hardening：`POST /api/learn` 增加 10 req/min 写限流，401/403/404 不消耗额度；`TaskInfoResponse.error_code` 收紧为 `TaskErrorCode`，新增稳定 `recovery_hint` 字段；LearnTaskBanner 使用 429 `rate_limited` 双语文案和 `recovery_hint` 控制 Retry。当前实测后端 `1754 passed, 1 skipped`，目标 serve tasks `59 passed`，前端 unit `123 passed`，目标 Learn banner/store unit `42 passed`，i18n `459/459`；coverage/build/全量 Playwright 未在 hardening 后重跑。 |
| 2026-05-06 | 同步 Viewer 侧栏溢出修复 + Lesson UX 优化：Diff/Lesson 右侧栏水平溢出修复（根因为 `.claim-card` button 默认 `inline-block` 不受 flex 父容器宽度约束，改 `display: block` + grid 列 `minmax(0, 320px)` + AppShell `overflow-x: hidden`）；Lesson claim 浮动面板（`createPortal` + fixed 定位 EvidencePanel，Escape/click-outside 关闭）；scaffolding tabs 默认精简模式（compact→hint→full 顺序 + 模式描述文字）。前端 unit `166 passed`（18 files），后端未变仍为 `1848 passed`。 |
| 2026-05-07 | 同步 LLM judge + 鲁棒解析 + 真实 gpt-5.5 WebUI 验证：新增 `eval_judge.md`（源码 + wheel prompt resource）、可选 `judge.json` artifact、learn Step 8 LLM judge 接线、`generate_model`/`judge_model` 角色模型覆盖修复；claims/lesson/quiz/misconception/judge 解析增强 provider envelope、fenced JSON、JSONL、示例块和截断 JSON 容错；真实 WebUI learn run `score.json=94.96/PASS`、`judge.json model_id=gpt-5.5`、console 无 error/warn；targeted `230 passed`，后端全量 `1993 passed, 1 skipped`，live judge `1 passed`，ruff/format/pyright/diff-check 通过。 |
