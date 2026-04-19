# Team Plan: ahadiff-engineering-kickoff

## 概述

将 AhaDiff 从设计文档仓库转化为可执行 Python CLI 工程，修正文档不准确，修复 UI 响应式，按 9 段顺序启动第一段+第二段后端开发。

## codex 分析摘要

- 可行性 **High**，技术栈克制，护城河可编码
- **4 个 contract 冲突必须先冻结**：
  1. `runs/<run_id>` vs `commits/<sha>` 目录冲突 → 统一为 run 是事实、commit 是索引
  2. 8 维评分 `spec_alignment` vs `local_ux` 不一致 → 用 `spec_alignment` 替换 `local_ux`
  3. Phase 2.5 阈值 2/3 冲突 → 已修正为 2（CLAUDE.md 已更新）
  4. improve loop 可写集合含 viewer 模板 → 后端只允许改 `prompts/*.md`
- 推荐 **Artifact-first CLI monolith** 架构
- 给出了精确到文件和函数的包结构建议（60+ 文件/函数）
- Agent 安装落点已用官方文档复核，Cursor 置信度 Medium

## gemini 分析摘要

- **响应式修复**：引入 icon-only 迷你侧栏（769-1024px）+ 全抽屉（≤768px）
- **Rubric 进度条**：改为基于分数阈值的语义变色（excellent/good/fair/poor），不用 8 种固定色
- **favicon**：inline SVG `Δ知` + #D27050，零外部依赖
- **CSS 变量**：拆 RGB 变量支持 alpha、抽象 shadow/radius tokens
- **打印样式**：保留 evidence rail（`.print-keep`），只隐藏交互块
- **Jinja 模板**：`layouts/base.html` + `components/{sidebar,topbar,claim_inspector,rubric_radar}` + `pages/11页`
- **a11y**：对比度 `--muted-2` 加深至 `#7A7363`，进度条加 `role="progressbar"`

## 技术方案

### 架构决策

| 决策点 | 结论 | 来源 |
|-------|------|------|
| artifact 根目录 | `.ahadiff/runs/<run_id>/` 为主，`.ahadiff/commits/<sha>/latest.json` 为索引 | codex |
| 8 维评分 | accuracy/evidence/diff_coverage/learnability/quiz_transfer/spec_alignment/conciseness/safety_privacy | codex |
| Phase 2.5 阈值 | 默认 2，可通过 `max_stuck_rounds` 配置 | codex + 综合评估 |
| improve loop 可写集 | 仅 `prompts/*.md`，viewer 模板走前端线 | codex |
| 前端技术路线 | Jinja2 静态 HTML，不用 Next.js/React | gemini + 方案文档 |
| 响应式断点 | 769-1024px icon-only sidebar, ≤768px drawer | gemini |
| 模型协作 | Claude 编排+前端实现, Codex 后端实现, Gemini 前端评审 | 用户指定 |

## 子任务列表

### Layer 0: 文档修正与工程契约冻结

#### Task 0.1: 修正方案文档 3 处不准确
- **类型**: 文档
- **文件范围**: 
  - `doc/ahadiff 最终完整方案*.md`
  - `doc/知返ahadiff改名后的后续方案.md`
  - `doc/AhaDiff_frontend_design_v1.1_revised.md`
- **依赖**: 无
- **执行者**: Claude
- **实施步骤**:
  1. Phase 2.5 阈值：全局替换"连续 3 轮"为"连续 2 轮"
  2. SkillCompass：注明"AhaDiff 自研 8 维，SkillCompass 原版 6 维"
  3. SKILL0：注明"helpfulness 原论文为 skill file 级，AhaDiff 扩展到 section 粒度"
  4. 统一 8 维名称：`local_ux` → `spec_alignment`
- **验收标准**: grep 全仓库无残留不一致

#### Task 0.2: 冻结工程契约文档
- **类型**: 文档
- **文件范围**: `doc/ENGINEERING-CONTRACT.md`（新建）
- **依赖**: Task 0.1
- **执行者**: Claude
- **实施步骤**:
  1. 定义 artifact 目录规范（run 为主，commit 为索引）
  2. 定义 8 维 rubric 终版 schema
  3. 定义 improve loop 可写/不可写边界
  4. 定义 Phase 2.5 默认阈值与配置化方案
- **验收标准**: 文件存在且与 CLAUDE.md 无冲突

### Layer 1: 项目骨架（可并行）

#### Task 1.1: Python 包骨架 + CLI 入口
- **类型**: 后端
- **文件范围**:
  - `pyproject.toml`
  - `src/ahadiff/__init__.py`
  - `src/ahadiff/__main__.py`
  - `src/ahadiff/cli.py`
  - `src/ahadiff/core/config.py`
  - `src/ahadiff/core/paths.py`
  - `src/ahadiff/core/ids.py`
  - `src/ahadiff/core/errors.py`
  - `src/ahadiff/core/prompts.py`
- **依赖**: Task 0.2
- **执行者**: Codex 实现, Claude+Codex review
- **实施步骤**:
  1. 创建 `pyproject.toml`（typer/rich/pydantic/jinja2/httpx/pyyaml）
  2. 实现 `cli.py` 的 `app()`、`init_cmd()`、`doctor_cmd()` 骨架
  3. 实现 `config.py` 的 `load_config()`、`write_default_config()`
  4. 实现 `paths.py` 的所有路径计算函数
  5. 实现 `ids.py` 的 run_id/claim_id/hunk_id 生成
  6. 实现 `prompts.py` 的 `load_prompt()`、`render_prompt()`
- **验收标准**: `uv run ahadiff --help` 可执行

#### Task 1.2: 安全层
- **类型**: 后端
- **文件范围**:
  - `src/ahadiff/safety/ignore.py`
  - `src/ahadiff/safety/redact.py`
  - `src/ahadiff/safety/injection.py`
  - `src/ahadiff/safety/gates.py`
  - `tests/unit/test_ignore.py`
  - `tests/unit/test_redact.py`
  - `tests/unit/test_injection.py`
- **依赖**: Task 0.2（paths contract）
- **执行者**: Codex 实现, Claude+Codex review
- **实施步骤**:
  1. 实现 `.ahadiffignore` 加载与路径过滤
  2. 实现 secret 扫描（API keys、JWT、private keys 等）
  3. 实现 prompt injection 检测与转义
  4. 实现 offline_only / explicit_upload 门控
  5. 编写对应单元测试
- **验收标准**: `pytest tests/unit/test_redact.py tests/unit/test_injection.py` 全绿

### Layer 2: Diff 结构化（依赖 Layer 1，内部可并行）

#### Task 2.1: Git Diff 捕获与解析
- **类型**: 后端
- **文件范围**:
  - `src/ahadiff/git/repo.py`
  - `src/ahadiff/git/capture.py`
  - `src/ahadiff/git/parser.py`
  - `src/ahadiff/git/line_map.py`
  - `tests/unit/test_git_capture.py`
  - `tests/unit/test_diff_parser.py`
  - `tests/unit/test_line_map.py`
- **依赖**: Task 1.1
- **执行者**: Codex 实现, Claude+Codex review
- **实施步骤**:
  1. 实现 `repo.py`：open_repo、resolve_ref_range
  2. 实现 `capture.py`：capture_patch、write_input_artifacts
  3. 实现 `parser.py`：parse_unified_diff、iter_hunks
  4. 实现 `line_map.py`：build_line_map
  5. 编写单元测试（含空 diff、纯删除、rename、binary、非 UTF-8）
- **验收标准**: `ahadiff learn HEAD~1..HEAD --dry-run` 生成 `patch.diff` + `metadata.json` + `line_map.json`

#### Task 2.2: Symbol 提取与 Hunk Hash
- **类型**: 后端
- **文件范围**:
  - `src/ahadiff/git/symbols.py`
  - `src/ahadiff/git/hunk_hash.py`
  - `tests/unit/test_symbol_extract.py`
  - `tests/unit/test_hunk_hash.py`
- **依赖**: Task 2.1（parser 输出）
- **执行者**: Codex 实现, Claude+Codex review
- **实施步骤**:
  1. 实现 Python AST symbol extraction + regex fallback
  2. 实现 hunk hash（规范化内容，不含时间戳）
  3. 编写单元测试
- **验收标准**: `ahadiff learn --dry-run --inspect` 输出 changed symbols 列表

### Layer 3: 前端修复（与 Layer 2 并行）

#### Task 3.1: UI 响应式修复
- **类型**: 前端
- **文件范围**:
  - `AhaDiff Warm v5.html`（根目录）
  - `ui/AhaDiff Warm v5.html`
- **依赖**: 无（可与 Layer 1-2 完全并行）
- **执行者**: Claude 实现（基于 Gemini 方案）, Gemini review
- **实施步骤**:
  1. 添加 769-1024px icon-only sidebar 媒体查询
  2. 添加 ≤768px drawer mode + backdrop overlay
  3. 实现 sidebar backdrop click/escape 关闭
  4. 修复 Rubric 进度条语义变色
  5. 添加 inline SVG favicon
  6. 优化 CSS 变量体系（RGB 拆分、shadow tokens）
  7. 修复打印样式（保留 evidence rail）
  8. a11y 改进（对比度、tabindex、progressbar role）
- **验收标准**: Playwright 截图验证 768px/375px/1024px 三个视口无断裂

## 文件冲突检查

✅ **无冲突** — 后端 Task (1.1, 1.2, 2.1, 2.2) 全部在 `src/ahadiff/` 和 `tests/` 下，前端 Task (3.1) 只改 HTML 文件，文档 Task (0.1, 0.2) 只改 `doc/`。

## 并行分组

```
Layer 0 (串行): Task 0.1 → Task 0.2
  ↓
Layer 1 (并行): Task 1.1 ∥ Task 1.2
  ↓
Layer 2 (并行): Task 2.1 ∥ Task 2.2
  
Layer 3 (与 Layer 1-2 完全并行): Task 3.1
```

## 执行模型分配

| Task | 实现 | Review |
|------|------|--------|
| 0.1 文档修正 | Claude | — |
| 0.2 工程契约 | Claude | — |
| 1.1 包骨架 | Codex | Claude + Codex |
| 1.2 安全层 | Codex | Claude + Codex |
| 2.1 Git 解析 | Codex | Claude + Codex |
| 2.2 Symbol/Hash | Codex | Claude + Codex |
| 3.1 UI 修复 | Claude | Gemini(gemini-3.1-pro-review) + Claude |

## 预计 Builder 数量

- Layer 0: 1 个 Claude agent（串行，~10 分钟）
- Layer 1: 2 个 Codex agents 并行（~20 分钟）
- Layer 2: 2 个 Codex agents 并行（~20 分钟）
- Layer 3: 1 个 Claude agent（与 Layer 1-2 并行，~30 分钟）

总计最多 3 个并行 agent。
