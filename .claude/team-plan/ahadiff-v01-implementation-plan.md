# AhaDiff v0.1 Implementation Plan

> 修订日期 2026-04-22
> 权威源（高→低）：① `CLAUDE.md` ② `ahadiff-v01-kickoff.md` ③ `ahadiff-v01-stages-4-9.md` ④ `closure-checklist-29.md` ⑤ `AhaDiff_frontend_design_v1.1_revised.md` ⑥ `AhaDiff Warm v6.html`
> 本文档是执行排程，不是新的架构权威源。与 `doc/contract-freeze.md` 冲突时，Task 0 产出的 `contract-freeze.md` 为准。
> 状态更新（2026-04-22）：`Stage 0 / Task 0` 已完成，已产出 `doc/contract-freeze.md`、`src/ahadiff/contracts/*.py`、`tests/unit/test_contracts.py`；当前实测 `python3 -m pytest tests/unit/test_contracts.py` 为 `18 passed`。

---

## A. 文档充分性判断

**结论：Stage 0 已经收口完成。当前不再缺 `contract-freeze.md`，后续开发应直接以已落地的 freeze 继续推进。**

### 已经足够开工的部分

- **主线阶段和 gate 已冻结**：外层执行阶段以 `CLAUDE.md` 的 `Stage 0–7` 为准，不再自创 `Stage 8/9`
- **任务拆分已足够细**：`kickoff.md` 覆盖 Task 0–8，`stages-4-9.md` 覆盖 Task 8.5–20 和 i18n overlay
- **后端核心决策已冻结**：RunStatus、ClaimStatus、EventLog、ServeApp、三层锁矩阵、SQLite 真相源、评估 bundle、improve 状态机
- **diff 输入面已冻结**：v0.1 明确支持 `--last`、`--since`、`--staged`、`--unstaged`、`HEAD range`、单 commit（`git show <sha>` 语义）、`--patch file|-`、`--compare a b`
- **SRS 方案已冻结**：v0.1 用 FSRS-6，不再回到 SM-2 作为默认路径
- **前端参考已足够**：根级 `AhaDiff Warm v6.html` 是视觉参考模板；前端手册已写清 additive-only、v6.2 polish 和 `editorial-terminal` overlay 的工程化边界
- **专题决策已存在**：data-scope、fsrs、diff-input、graphify 四份专题文档都可直接指导实现

### Task 0 已收口的内容

- `doc/contract-freeze.md` 已落地，作为当前权威承载文件
- 已冻结字面值和契约已集中抄录进 `contract-freeze.md`，包括：
  - `CardState = active | stale | archived | suspended`
  - `eval_bundle_hash` 字节级 SHA-256 伪代码
  - SQLite 版本门禁与统一连接初始化
  - Config 5 层优先级链
  - `Allowlist` / `UsageEvent` / `ProviderCapabilities` / `LearnabilityGate` 的 contract
  - Graphify v0.1 的 CLI / data / sanitization / freshness 约束

### 非阻塞但需要后续校准

- Learnability Gate 权重 `0.4 / 0.3 / 0.3` 是 heuristic defaults，首批 50 份 pinned diff 后再调
- FSRS `desired_retention=0.9` 先按默认走，500–1000 次有效 review 后再做 A/B
- 生产环境跨模型评估切换时点后置到工程落地后，不阻塞 v0.1 开工
- Graphify 的 PageRank / 更深 repo graph 能力继续放到 v0.2

### 当前需要统一的口径

- **阶段命名**：
  - 外层执行与 gate：`Stage 0–7`
  - 内部子段：保留 `Layer 0–3`、`Layer 6a/6b` 这种局部 DAG 术语
  - 不再使用 `Stage 0–9`
- **前端参考口径**：
  - `Warm v6` 是视觉参考，不是“字节级原样复刻”
  - 允许提取 token 和 overlay 语言，但必须保持 additive-only
- **Graphify 口径**：
  - 运行时可选增强，不是 core learn 的前置依赖
  - 但既然还在 v0.1 scope 内，就必须进入主排程和 stage gate，不能只留在专题文档里

---

## B. 执行计划（按 Stage 0–7）

### Stage 0 — Schema Freeze Gate（Task 0）

- **当前状态（2026-04-22）**：
  - `doc/contract-freeze.md` 已落地
  - `src/ahadiff/contracts/{claim_status,run_source,eval_bundle,event_log,error_types,orchestrator,serve_app}.py` 已落地
  - `tests/unit/test_contracts.py` 已落地
  - `python3 -m pytest tests/unit/test_contracts.py` 实测 `18 passed`

- **目标**：
  - 产出 `doc/contract-freeze.md`
  - 把现有权威文档里已经冻结的契约集中成单一权威源
  - 建立最小可 import 的 contracts 骨架与 contract 测试
- **输入文档**：
  - `CLAUDE.md`
  - `.claude/team-plan/ahadiff-v01-kickoff.md` 的 Task 0
  - `.claude/team-plan/closure-checklist-29.md`
  - 四份专题文档中涉及 contract 的条目
- **产出物**：
  - `doc/contract-freeze.md`
  - `src/ahadiff/contracts/{claim_status,run_source,eval_bundle,event_log,error_types,orchestrator,serve_app}.py`
  - `tests/unit/test_contracts.py`
  - `contract-freeze.md` 中明确抄录：
    - RunStatus / ClaimStatus / CardState / privacy_mode / scaffolding 命名
    - Config precedence / data-scope / UsageEvent reserved schema
    - ProviderCapabilities contract
    - SQLite gate / lock matrix / Serve DTO / Learnability defaults
    - Graphify v0.1 的 detect/import/sanitize/freshness contract
- **依赖**：无
- **可并行项**：
  - `Claude` 起草 `contract-freeze.md`
  - `Codex` 用多个 sub-agents 并行抽取字面值、DTO、枚举、测试样例
  - 最终合并和 wording 收口必须串行
- **风险点**：
  - 把已经冻结的决策误写成“待定”
  - 提前发明新文件/新模块名，超出权威文档范围
- **验收标准**：
  - `doc/contract-freeze.md` 存在，且与现有权威文档无冲突
  - `python3 -m pytest tests/unit/test_contracts.py` 通过
  - `from ahadiff.contracts import *` 不报错
- **Gate**：
  - `Codex + Claude`
  - 条件按 `CLAUDE.md` 的 `GO / CONDITIONAL GO / NO GO`

### Stage 1 — Infra + Safety + Docs + Prototype Fix（Task 1–4）

- **当前状态（2026-04-22）**：
  - `Task 1` 已落地并通过当前 gate
  - `Task 2` 的安全层基础实现也已落地，并通过当前后端 gate
  - 当前实测：`uv run pytest tests/unit` 为 `61 passed`
  - 其中安全层目标测试：`uv run pytest tests/unit/test_redact.py tests/unit/test_injection.py tests/unit/test_path_safety.py tests/unit/test_allowlist.py` 为 `26 passed`
  - 当前实测：`uv run ruff check src tests`、`uv run ruff format --check src tests`、`uv run pyright` 与 `uv build --wheel` 全通过
  - 当前仓库 `.venv` 运行时为 Python 3.12.10 / SQLite 3.51.3，`ahadiff doctor` 的 SQLite gate 实测通过；低版本 SQLite runtime 下 `doctor` 已改为非零退出
- **目标**：
  - 建立工程骨架、doctor/config 基础能力
  - 落地安全层
  - 同步文档口径
  - 修正根级 `Warm v6` 与 `ui/` 快照的响应式问题
- **输入文档**：
  - `contract-freeze.md`
  - `kickoff.md` Task 1–4
  - `data-scope` 专题
  - 前端手册 + `AhaDiff Warm v6.html`
- **产出物**：
  - **Task 1**：`pyproject.toml`、`src/ahadiff/{__main__,cli}.py`、`core/{config,paths,ids,errors}.py`
    - 包含 `global_config_dir()`
    - 包含 `doctor_cmd()`
    - 包含 `config show --resolved`
  - **Task 2**：`safety/{ignore,redact,injection,gates,audit}.py`
    - `allowlist_digest`
    - `suppress_rules`
    - `audit.jsonl` / `audit.private.jsonl` schema 与 rotation
  - **Task 3**：`CLAUDE.md`、`doc/CLAUDE.md`、`ui/CLAUDE.md` 口径同步
  - **Task 4**：根级 `AhaDiff Warm v6.html` 和 `ui/` v6 快照的四视口响应式修复
- **依赖**：Stage 0 Gate
- **可并行项**：
  - `Task 1 / 2 / 3 / 4` 可安全并行
  - `Task 7` 可在 `Task 1` 骨架稳定后提前分支启动，不必等 Stage 1 全 gate 才开工
- **风险点**：
  - `Task 1` 和 `Task 2` 对 config / doctor / safety provenance 的边界写窄
  - Task 4 误把原型当最终 UI，超出“原型修复”边界
- **验收标准**：
  - `uv sync && uv run ahadiff init && uv run ahadiff doctor` 可运行
  - `ahadiff config show --resolved` 正确显示来源层级
  - 安全层单测通过
  - `Warm v6` 四视口无明显断裂
- **Gate**：
  - `Task 1/2/3`：`Codex + Claude`
  - `Task 4`：`Claude + Codex + Gemini`

### Stage 2 — Capture + Parse + Provider + Claim（Task 5–8）

- **目标**：
  - 落地 v0.1 完整 diff 输入面
  - 落地 provider 探测与能力矩阵
  - 落地 claim 提取与验证
  - 把 Graphify v0.1 的 backend/CLI 工作流正式纳入主线
- **输入文档**：
  - `kickoff.md` Task 5–8
  - `diff-input` 专题
  - `graphify` 专题
  - `closure-checklist-29.md`
- **产出物**：
  - **Task 5**：`git/{repo,capture}.py`
    - v0.1 输入模式精确为：
      - `--last`
      - `--since`
      - `--staged`
      - `--unstaged`
      - commit range
      - 单 commit（`git show <sha>` 语义）
      - `--patch file|-`
      - `--compare a b`
  - **Task 7**：`llm/{provider,probe,cache,cost}.py`
    - 8 adapter
    - context probe
    - ProviderCapabilities
    - token estimation
    - audit provenance
    - 开发阶段允许用 loopback OpenAI-compatible endpoint 做 adapter / probe smoke；仓库内 committed docs / examples 只写环境变量占位符，不落本地 endpoint / API key
  - **Task 6**：`git/{parser,line_map,symbols,hunk_hash}.py`
  - **Graphify v0.1 workstream**：
    - `graphify-out/graph.json` 自动检测 / 导入 / sanitization / freshness metadata
    - `--use-graphify` / `--no-graphify`
    - `ahadiff graph status`
    - `ahadiff graph refresh`
    - `ahadiff graph import`
    - Graphify 相关单测 / 集成测试
  - **Task 8**：`claims/{schema,extract,verify,negative_scan,classify}.py` + `prompts/claim_extract.md`
- **依赖**：
  - `Task 5` 依赖 `Task 1 + Task 2`
  - `Task 7` 依赖 `Task 1`
  - `Task 6` 依赖 `Task 5`
  - `Task 8` 依赖 `Task 6 + Task 7`
- **可并行项**：
  - `Task 7` 可在 `Task 1` 后立即启动
  - `Task 5` 与 `Task 7` 并行
  - Graphify detect/import/sanitize 与 `Task 5/6` 同步推进
  - `Task 8` 必须串行等 `Task 6 + Task 7`
- **风险点**：
  - 把 `--unstaged` / 单 commit / `--compare` 的冻结语义写错
  - 把 Graphify 留在专题文档、不落主线
  - claim verifier 范围大，最容易拖长工期
- **验收标准**：
  - v0.1 输入模式 dry-run 覆盖通过
  - provider probe / capability / adapter mock 测试通过
  - Graphify 缺失时 graceful degrade，存在时可 detect/import/refresh
  - claim verifier 能产出 5 态状态与 `reason_code`
- **Gate**：
  - `Codex + Claude`

### Stage 3 — Learnability + Lesson + Quiz + Eval + Ratchet（Task 8.5, 9–12）

- **目标**：
  - 建立 learnability 判定
  - 生成 lesson / quiz / cards / concepts
  - 冻结 evaluation bundle
  - 落地 ratchet 和 result_events 写入顺序
- **输入文档**：
  - `stages-4-9.md` Task 8.5–12
  - `fsrs` 专题
  - `data-scope` 专题中 benchmark / audit / result 约束
- **产出物**：
  - **Lane A**：
    - `Task 8.5` Learnability Gate
    - `Task 9` Lesson 三档撤架
    - `Task 10` Quiz + `cards.jsonl` + `concepts.jsonl`
  - **Lane B**：
    - `Task 11` evaluation bundle 5 文件 immutable
    - `Task 12` ratchet / `result_events` / `results.tsv`
- **依赖**：
  - `Task 8.5` 依赖 `Task 6 + Task 8`
  - `Task 9` 依赖 `Task 7 + Task 8 + Task 8.5`
  - `Task 10` 依赖 `Task 8 + Task 9`
  - `Task 11` 依赖 `Task 0 + Task 7 + Task 8`
  - `Task 12` 依赖 `Task 0 + Task 11`
- **可并行项**：
  - `Lane A` 与 `Lane B` 并行
  - `Task 11` 不需要等 `Task 9/10`
  - `Task 12` 不需要等 `Task 10`
- **风险点**：
  - `result_events` / TSV / finalized run 的写入顺序漂移
  - FSRS 字段和 UI 动作映射被写窄
  - learnability 被误当成科学定标而不是 heuristic default
- **验收标准**：
  - `ahadiff learn` 能产出 `lesson/full|hint|compact`
  - `Task 10` 的 `fsrs_state` / `card_state` / `peeked_this_session` 契约一致
  - `score.json` 含 `eval_bundle_version`
  - `result_events` 是唯一真相源，TSV 可重建
- **Gate**：
  - `Codex + Claude`

### Stage 4 — Viewer + Review DB（Task 13, 14, 15）

- **目标**：
  - 建立 React viewer 基础
  - 交付 v0.1 必须的 4 个核心页面
  - 落地 `review.sqlite` schema / migration / FSRS 调度
  - 把 Graphify/ConceptGraph 的前端降级态纳入实现
- **输入文档**：
  - `stages-4-9.md` Task 13–15
  - 前端手册
  - `Warm v6`
  - `graphify` 专题
  - `fsrs` 专题
- **产出物**：
  - **Task 13**：`viewer/` 基础工程
    - React 19 + Vite + TypeScript
    - Warm token 提取与 overlay 工程化
    - i18n store
    - virtual list / dynamic measuring
    - print / forced-colors / reduced-transparency / safe-area / FOUC 处理
  - **Task 14**：Dashboard / LessonReader / DiffViewer / Quiz 四页
    - Bottom Mini-Panel 三段吸附
    - KPI fallback
    - `ConceptGraph` 聚类与 `⋮` 菜单
    - Graphify / learning-only / empty 三态展示
  - **Task 15**：`review.sqlite`
    - `cards`
    - `scheduler_presets`
    - `review_logs`
    - `result_events`
    - `learning_signals`
- **依赖**：
  - `Task 13` 依赖 `Task 0`
  - `Task 14` 依赖 `Task 13`
  - `Task 15` 依赖 `Task 10 + Task 12`
- **可并行项**：
  - `Task 13` 和 `Task 15` 并行
  - `Task 14` 在 `Task 13` 后推进
  - Graphify viewer 状态与 `ConceptGraph` 可随 `Task 14` 并行实现
- **风险点**：
  - 把 `Warm v6` 当像素级复刻，而不是工程化参考
  - 把前端 gate 缩成只剩 FCP / render-count
  - `review.sqlite` schema 与 `Task 10/12` 契约漂移
- **验收标准**：
  - `cd viewer && npm run build` 通过
  - 首载无 FOUC
  - `DiffView` 5000 行 `FCP < 500ms`
  - 语言切换 `render-count ≤ 1`
  - `axe-core` 零 critical
  - iPhone 安全区不裁切，核心交互目标 `≥44px`
  - print / `forced-colors` / `prefers-reduced-transparency` 可读
  - 375px 下 Mini-Panel 弹出后 diff 仍可滚动
  - `ConceptGraph` 50 节点首屏 `<300ms`，展开/折叠 `<100ms`，无 `>50ms` long task
- **Gate**：
  - `Codex + Claude + Gemini`

### Stage 5 — Serve + Improve（Task 14.5, 16, 17）

- **目标**：
  - 落地本地 Serve API
  - 落地 improve loop 与 targeted verify / Phase 2.5
- **输入文档**：
  - `stages-4-9.md` Task 14.5 / 16 / 17
  - `CLAUDE.md` Stage 5 定义
- **产出物**：
  - **Task 14.5**：
    - Starlette + Uvicorn
    - localhost-only bind
    - `X-AhaDiff-Token`
    - Host / Origin 校验
    - finalized runs only
  - **Task 16**：
    - improve loop
    - worktree isolation
    - Ctrl+C two-phase finalization
  - **Task 17**：
    - targeted verify
    - Phase 2.5
    - max once/session
- **依赖**：
  - `Task 14.5` 依赖 `Task 15`；与 `Task 14` 无硬依赖。开发时只需和 `Task 13` 的前端 build / API 接入方式保持一致；具体 DTO 字段命名与 shape 以 `doc/contract-freeze.md` 和对应 contract 文件为准
  - `Task 16` 依赖 `Task 11 + Task 12 + Task 15`
  - `Task 17` 依赖 `Task 16`
- **可并行项**：
  - `Task 14.5` 与 `Task 16` 可在各自依赖满足后并行
  - `Task 17` 必须串行跟在 `Task 16` 后
- **风险点**：
  - serve 读到 half-written run
  - improve 状态机与 ratchet 状态机混用
- **验收标准**：
  - `ahadiff serve` 打开本地 WebUI，写路由 token 生效，外网访问被拒绝
  - improve 6 rounds 跑通，worktree 隔离与清理正常
  - targeted verify / `keep_final` / `phase25_rewrite` 路径正确
- **Gate**：
  - `Codex + Claude`

### Stage 6 — Bench + Install + CI（Task 18–20）

- **目标**：
  - 冻结 benchmark 套件
  - 交付 v0.1 的 install targets
  - 落地 GitHub Action 模板
- **输入文档**：
  - `stages-4-9.md` Task 18–20
  - `data-scope` 专题中的 manifest 约束
- **产出物**：
  - **Task 18**：20 eval + 10 integration + `benchmarks/manifest.json`
    - frozen fixture 负责 pinned integration / eval / benchmark 可复现基线
    - live smoke 基于一个外部参考私有仓库（文档中统一记为 `<REFERENCE_REPO>`）跑真实 diff / provider / 主链路冒烟
    - live smoke 结果不写进 `suite_digest` 可比基线
  - **Task 19**：v0.1 的 4 个 target
  - **Task 20**：verify-only / generate-on-CI action 模板
- **依赖**：
  - `Task 18` 依赖 `Task 11`
  - `Task 19/20` 依赖核心 CLI / review / improve 路径冻结
- **可并行项**：
  - `Task 18` 的 fixture / report 可在 `Task 11` 后提前准备
  - `Task 19` 与 `Task 20` 在 CLI contract 稳定后并行
- **风险点**：
  - benchmark manifest 没写入 suite comparability 条件
  - install target scope 偷偷扩到 v0.2
- **验收标准**：
  - benchmark / integration pinned 跑通
  - live smoke 至少覆盖 1 个真实仓库 diff + 1 次 loopback provider probe
  - `suite_id / suite_digest / visibility` 写入 manifest
  - 4 个 install target `--dry-run` 正常
  - GitHub Action 模板能运行 verify 路径
- **Gate**：
  - `Codex + Claude`

### Stage 7 — i18n Signoff

- **目标**：
  - 只做最终 parity audit 和 signoff
- **输入文档**：
  - `CLAUDE.md` Stage 7
  - `stages-4-9.md` i18n-0~6
- **产出物**：
  - i18n parity report
  - Stage 7 signoff 记录
- **依赖**：
  - i18n-0~6 已在 Stage 3–6 期间落地
- **可并行项**：
  - parity audit 可由多模型并行 review
- **风险点**：
  - 把 Stage 7 误写成独立开发阶段，拖慢主线
- **验收标准**：
  - 双语 CLI / Viewer / prompt / VCR key / locale fallback 一致
- **Gate**：
  - `Codex + Claude + Gemini`

### i18n Overlay（跨 Stage 3–6）

- `i18n-0`：locale schema / resolver / file_id / content_lang
- `i18n-1`：catalog + loader
- `i18n-2`：prompt language directive
- `i18n-3`：React i18n
- `i18n-4`：语言切换 UI
- `i18n-5`：CLI `--lang`
- `i18n-6`：VCR key 含 `output_lang`

---

## C. 立即可执行的第一批（未来 1–2 周）

### Day 1–2

1. `Stage 0` 已完成
2. `doc/contract-freeze.md` 已产出
3. contracts 骨架和 `tests/unit/test_contracts.py` 已落地
4. 同步 `CLAUDE.md` / `doc/CLAUDE.md` / `ui/CLAUDE.md` 术语

### Day 3–5

- `Task 1 / 2 / 3 / 4` 并行
- `Task 1` 一旦把 CLI/config/paths 骨架立住，`Task 7` 可以提前开工，不必傻等 Stage 1 全 gate
- 前端只做 prototype fix，不提前把 Stage 4 viewer 全量 merge 进来

### Day 6–9

- `Task 5` 与 `Task 7` 并行
- `Task 6` 在 `Task 5` 后启动
- Graphify backend/CLI workstream 跟 `Task 5/6` 同步推进
- `Task 7` 开发验证优先用 loopback OpenAI-compatible endpoint 跑通，不把本地 endpoint / key 写进仓库
- `Task 8` 在 `Task 6 + Task 7` 都齐后独占推进

### Day 10–14

- `Stage 3` 两条 lane 并行：
  - Lane A：`Task 8.5 → 9 → 10`
  - Lane B：`Task 11 → 12`
- 如果需要压缩等待时间，`Task 13` 可以在 mock/proxy 条件下提前开 feature 分支，但 Stage 4 gate 仍按主阶段顺序执行

### 这些事不能提前

- `Task 8` 不能跳过 `Task 6 + Task 7`
- `Task 14.5` 不能早于 `Task 15` 的 DB schema gate
- `Task 17` 不能早于 `Task 16`
- `Task 19/20` 不要在核心 CLI / review / improve 路径还在漂的时候提前收尾

---

## D. 阻塞项和待确认项

### 真正阻塞项

- **B-01（已解除）**：`doc/contract-freeze.md` 已落地
  - 影响：Stage 0 的主阻塞项已清掉
  - 当前状态：后续阶段可直接以 freeze 为准推进

### 需要在 Task 0 明确写入，但不是“重新设计”的项

- `CardState` 四态与 `peeked_this_session`
- `eval_bundle_hash` 算法
- SQLite 版本门禁与 backport 白名单
- Config precedence / data-scope / allowlist / UsageEvent reserved schema
- ProviderCapabilities contract
- Graphify v0.1 detect/import/sanitize/CLI contract

### 待确认但不阻塞开工

- **Graphify 独立页面口径**
  - 当前按“先完成 backend/CLI + ConceptGraph / 三态降级 + viewer data contract”处理
  - 如果要把独立 Graph Explorer 页面列入 v0.1 core gate，需要显式补进 Task 14 范围
- **测试仓库策略**
  - 当前不建议另建远端 GitHub `ahadifftest` 仓库
  - 先用 frozen fixture + 外部参考私有仓库的 live smoke 完成验证
  - 只有在后续 CI 共享样本、远端认证或远端工作流成为硬需求时再评估
- **生产跨模型评估切换时点**
  - 开发基线统一 `gpt-5.4-mini`
  - `gpt-5.4` 与 `gpt-5.3-codex-spark` 只作为后续对比模型，不进当前默认 gate
- **FSRS / Learnability 校准**
  - 数据够了再调，不阻塞首版

---

## E. 给工程 Agent 的落地建议

### Owner 分工

| 阶段 | Claude | Codex | Gemini |
|---|---|---|---|
| Stage 0 | `contract-freeze.md`、术语收口 | contracts / tests | — |
| Stage 1 | Task 3、Task 4 | Task 1、Task 2 | Task 4 review |
| Stage 2 | prompt 协作、架构校验 | Task 5–8、Graphify backend/CLI | — |
| Stage 3 | lesson / quiz prompts | Task 8.5–12 | — |
| Stage 4 | Task 13、Task 14 | Task 15 | Stage 4 前端 review |
| Stage 5 | 集成校验 | Task 14.5、16、17 | — |
| Stage 6 | install 文案 / action 模板协同 | Task 18–20 | — |
| Stage 7 | parity 汇总 | parity 校验 | parity review |

### Codex sub-agents / multi-agents 使用策略

- **优先并行的场景**：
  - Stage 0：字面值抽取、DTO 抽取、测试样例抽取、contract 只读核对
  - Stage 1：Task 1 / 2 与 Task 4 完全分离
  - Stage 2：Task 5 / 7 并行；Graphify CLI/检测链可做独立分支
  - Stage 3：Lane A / Lane B 并行
  - Stage 4：Task 13 / 15 并行；前端组件可按无冲突文件切子任务
  - Stage 5：Task 14.5 / 16 在依赖满足后并行
- **必须串行的场景**：
  - `Task 5 → Task 6 → Task 8`
  - `Task 8.5 → Task 9 → Task 10`
  - `Task 11 → Task 12`
  - `Task 15 → Task 14.5 gate`
  - `Task 16 → Task 17`
  - 每个 Stage 的最终 gate

### Agent 切 task 原则

- **backend**
  - capture / parser / provider / claim / review / improve / serve / benchmark / install
- **frontend**
  - viewer foundation / core pages / i18n / responsive / a11y / print / performance
- **docs**
  - contract-freeze / CLAUDE family sync / prompt wording
- **test**
  - contracts / safety / provider / capture / claim / graphify / viewer / benchmark / stage gate checklist

### Stage Gate 执行协议

- 每个 Stage 完成后都要做一次完整 gate
- 含前端的 Stage 必须拉 `Gemini`
- Gate checklist 以 `CLAUDE.md` 为准：
  - 功能正确性
  - corner case 覆盖
  - 文档同步
  - 类型安全
  - 代码规范
  - 安全扫描
  - 跨平台兼容
  - 集成点验证

---

## F. Engineering Backlog（P0 / P1 / P2）

### P0

| ID | 任务 | Owner type | 依赖 | 预计工作量 | 验收 |
|---|---|---|---|---|---|
| `BL-00` | Task 0 `contract-freeze.md` + core contracts + tests（已完成） | docs + backend | — | 1.5–2d | `contract-freeze.md` 已落地；contracts import 正常；`python3 -m pytest tests/unit/test_contracts.py` 实测 `18 passed` |
| `BL-01` | Task 1 scaffold + `pyproject.toml` + `doctor` + `config show --resolved` | backend | `BL-00` | 1d | `uv run ahadiff init/doctor/config show --resolved` 可运行 |
| `BL-02` | Task 2 safety + allowlist + audit provenance（已落地基础实现） | backend | `BL-00` | 1d | `uv run pytest tests/unit/test_redact.py tests/unit/test_injection.py tests/unit/test_path_safety.py tests/unit/test_allowlist.py` 实测 `26 passed`；`uv run pytest tests/unit` 实测 `61 passed` |
| `BL-03` | Task 7 provider + probe + ProviderCapabilities | backend | `BL-01` | 1.5–2d | 8 adapter mock + probe + capability 测试通过；loopback OpenAI-compatible smoke 跑通；示例只用 env 占位符 |
| `BL-04` | Task 5 diff capture v0.1 输入面 | backend | `BL-01` + `BL-02` | 1.5d | `--unstaged`、单 commit、`--compare`、`--patch`、range 全部 dry-run 正常 |
| `BL-05` | Task 6 parser + anchors + line map | backend | `BL-04` | 1.5d | AST / regex / section header 降级与 casefold guard 测试通过 |
| `BL-06` | Graphify v0.1 backend/CLI workstream | backend + test | `BL-04` + `BL-05` | 1.5d | `graph status/refresh/import`、detect/import/sanitize、degrade path 覆盖 |
| `BL-07` | Task 8 claim verifier | backend | `BL-03` + `BL-05` | 4–5d | 5 态 claim + `reason_code` + negative scan 全绿 |

### P1

| ID | 任务 | Owner type | 依赖 | 预计工作量 | 验收 |
|---|---|---|---|---|---|
| `BL-08` | Task 8.5 + 9 + 10 | backend + docs | `BL-07` | 2.5–3d | learnability、lesson 三档、quiz/cards/concepts 跑通 |
| `BL-09` | Task 11 + 12 | backend | `BL-07` | 2–2.5d | `eval_bundle_version`、ratchet、`result_events`、TSV 重建通过 |
| `BL-10` | Task 13 viewer foundation | frontend | `BL-00` | 2d | build / FOUC / a11y / print / FCP / render-count 通过 |
| `BL-11` | Task 14 core 4 pages + Graphify/ConceptGraph tri-state | frontend | `BL-10` | 2–2.5d | 4 视口、Mini-Panel、KPI fallback、cluster 性能与无障碍通过 |
| `BL-12` | Task 15 `review.sqlite` + FSRS-6 | backend | `BL-08` + `BL-09` | 1.5–2d | schema / migration / review flow / optimizer 前置条件正确 |

### P2

| ID | 任务 | Owner type | 依赖 | 预计工作量 | 验收 |
|---|---|---|---|---|---|
| `BL-13` | Task 14.5 serve backend | backend | `BL-10` + `BL-12` | 1–1.5d | localhost only、token、finalized runs only、locale API 正常 |
| `BL-14` | Task 16 + 17 improve / targeted verify / Phase 2.5 | backend | `BL-09` + `BL-12` | 2–2.5d | worktree、Ctrl+C、targeted verify、Phase 2.5 上限正确 |
| `BL-15` | Task 18 benchmark | test | `BL-09` | 1.5–2d | 20 eval + 10 integration + manifest + VCR key 条件齐全；另有 1 条真实仓库 live smoke，不进入 `suite_digest` |
| `BL-16` | Task 19 + 20 install / hooks / GitHub Action | backend | `BL-13` + `BL-14` | 1–1.5d | 4 targets `--dry-run`、CI verify 模板可跑 |
| `BL-17` | i18n-0~6 + Stage 7 signoff | backend + frontend + test | 跨 Stage 3–6 | 3.75d overlay + 0.5d signoff | CLI / Viewer / prompt / VCR parity audit 通过 |

---

## 附：这版计划的执行边界

- 不再把 `pyproject.toml` / `doctor` 误放进 Stage 0
- 不再把 `Task 7` 写成必须等 Stage 1 全 gate
- 不再把 `Task 14.5` 写成依赖 `Task 14`
- 不再把 `Warm v6` 写成“字节级复制”
- 不再把 Graphify 留在专题文档里不进主排程
- 不再把已冻结字面值误判为“尚未冻结”
