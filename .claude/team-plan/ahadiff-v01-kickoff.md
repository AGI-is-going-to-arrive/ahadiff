# Team Plan: AhaDiff v0.1 Kickoff

## 概述

将 AhaDiff 从纯设计文档仓库转化为可执行的 Python CLI + 静态 HTML Viewer 工程，完成第一段至第三段开发（本地 diff 包 → diff 结构化 → claim 闭环），并同步修复 UI 原型的响应式断裂问题。

## codex 分析摘要

- **可行性**：HIGH。技术栈克制，护城河明确，安全约束可编码
- **4 个 P0 contract 冲突必须先冻结**：
  1. `runs/<run_id>` vs `commits/<sha>` 目录并存 → 统一为 run 是事实，commit 是索引
  2. 8 维评分 schema 不一致（`spec_alignment` vs `local_ux`）→ 统一为 spec_alignment
  3. Phase 2.5 阈值文档冲突 → 已修正为 2
  4. improve loop 可写集合含 viewer 模板 → 后端只允许改 `prompts/*.md`
- **推荐架构**：Artifact-first CLI monolith，40+ 个文件的精确函数级设计
- **Agent 安装路径已官方核验**：Codex(AGENTS.md)/Claude(.claude/skills/)/Copilot(.github/) 置信度 High，Cursor(.cursor/rules/) 置信度 Medium

## gemini 分析摘要（gemini-3.1-pro-preview）

- **响应式修复**：769-1024px 引入 icon-only 迷你侧栏（64px），≤768px 彻底抽屉化
- **侧边栏遮罩**：fixed backdrop + blur(3px) + ESC/点击关闭
- **Rubric 色板**：8 维独立语义色（Accuracy=#2F6F4F, Evidence=#D27050, Coverage=#B09060...）
- **Jinja 拆分**：`templates/{base,layouts/,partials/,components/,pages/}` 五层架构
- **打印样式**：隐藏 UI 但保留证据链，代码块/claim 卡片 page-break-inside: avoid
- **A11y**：`--muted-2` 加深至 #7A7463，progressbar ARIA 补全，focus-visible ring
- **Inline SVG favicon**：`Δ` 字符 + #D27050 填色

## 技术方案

### 核心决策（已冻结）

1. **Artifact 根目录**：`.ahadiff/runs/<run_id>/` 为一级存储，`.ahadiff/commits/<sha>/latest.json` 为索引
2. **8 维 Rubric（immutable）**：accuracy(20)/evidence(18)/diff_coverage(14)/learnability(14)/quiz_transfer(10)/spec_alignment(10)/conciseness(8)/safety_privacy(6) = 100
3. **Phase 2.5 阈值**：默认 2 轮
4. **Backend improve 可写集**：仅 `prompts/*.md`，viewer 模板归前端工作流
5. **模型协作**：Claude 编排+前端实现，Codex 后端实现，Gemini 前端评审(gemini-3.1-pro-preview)

### 技术栈

- Python 3.11+, typer, rich, pydantic, jinja2, httpx, pyyaml
- SQLite (SRS review)
- ruff + pyright strict
- 不用 LiteLLM/LangChain/Next.js/React

## 子任务列表

### Layer 1（并行）— 工程骨架 + 文档修正 + UI 响应式修复

#### Task 1: 工程骨架初始化
- **类型**: 后端（Codex 实现）
- **文件范围**:
  - `pyproject.toml`
  - `src/ahadiff/__init__.py`
  - `src/ahadiff/__main__.py`
  - `src/ahadiff/cli.py`（init/doctor 子命令）
  - `src/ahadiff/core/config.py`
  - `src/ahadiff/core/paths.py`
  - `src/ahadiff/core/ids.py`
  - `src/ahadiff/core/errors.py`
- **依赖**: 无
- **实施步骤**:
  1. 创建 `pyproject.toml`（runtime deps + ruff + pyright + pytest 配置）
  2. 实现 `paths.py`：`project_state_dir()`, `run_dir(run_id)`, `review_db_path()`
  3. 实现 `config.py`：`load_config()`, `write_default_config()`, TOML 解析
  4. 实现 `ids.py`：`make_run_id()`, `make_claim_id()`, `make_hunk_id()`
  5. 实现 `cli.py`：`app()`, `init_cmd()`, `doctor_cmd()` 基础框架
  6. 实现 `__main__.py`：`python -m ahadiff` 入口
- **验收标准**: `uv sync && uv run ahadiff init && uv run ahadiff doctor` 可运行

#### Task 2: 安全层
- **类型**: 后端（Codex 实现）
- **文件范围**:
  - `src/ahadiff/safety/ignore.py`
  - `src/ahadiff/safety/redact.py`
  - `src/ahadiff/safety/injection.py`
  - `src/ahadiff/safety/gates.py`
  - `src/ahadiff/safety/audit.py`
  - `tests/unit/test_redact.py`
  - `tests/unit/test_injection.py`
- **依赖**: 无
- **实施步骤**:
  1. 实现 `.ahadiffignore` 加载与路径过滤
  2. 实现 secret scanner（OpenAI/Anthropic/AWS/JWT/DB URL 模式）
  3. 实现 prompt injection 转义（关键词检测 + XML 容器包裹）
  4. 实现安全门禁：`enforce_offline_only()`, `assert_no_unredacted_secret()`
  5. 编写单测覆盖：空 diff、secret in code、injection in comment/markdown/string
- **验收标准**: `pytest tests/unit/test_redact.py tests/unit/test_injection.py` 全绿

#### Task 3: 文档 contract 冻结
- **类型**: 文档（Claude 维护）
- **文件范围**:
  - `CLAUDE.md`（已修正 3 处 + 多模型策略）
  - `doc/CLAUDE.md`
  - `doc/COMPREHENSIVE-EVALUATION-REPORT.md`
- **依赖**: 无
- **实施步骤**:
  1. 统一 artifact 根目录描述为 `runs/<run_id>`
  2. 统一 8 维评分 schema（去掉 local_ux，加 spec_alignment）
  3. 统一 Phase 2.5 阈值为 2
  4. 标注 improve loop 可写边界
- **验收标准**: CLAUDE.md 与完整方案文档无 contract 冲突

#### Task 4: UI 响应式修复
- **类型**: 前端（Gemini 评审 → Claude 实现）
- **文件范围**:
  - `AhaDiff Warm v5.html`（根目录）
  - `ui/AhaDiff Warm v5.html`
- **依赖**: 无
- **实施步骤**:
  1. 添加 769-1024px icon-only 侧栏断点
  2. 添加 ≤768px 抽屉模式 + backdrop overlay
  3. 添加 inline SVG favicon
  4. 改进 Rubric 进度条 8 维语义色
  5. 加深 `--muted-2` 至 #7A7463（A11y 对比度）
  6. 补全打印样式（保留证据链）
  7. 补全 progressbar ARIA 属性
- **验收标准**: Playwright 截图验证 375px/768px/1024px/1440px 四个视口无断裂
- **Review**: Claude 实现后 → Gemini(gemini-3.1-pro-preview) + Codex 交叉 review

### Layer 2（依赖 Layer 1）— Git 捕获 + Diff 结构化

#### Task 5: Git diff 捕获
- **类型**: 后端（Codex 实现）
- **文件范围**:
  - `src/ahadiff/git/repo.py`
  - `src/ahadiff/git/capture.py`
  - `tests/unit/test_git_capture.py`
- **依赖**: Task 1
- **实施步骤**:
  1. 实现 `open_repo()`, `resolve_ref_range()`
  2. 实现 `capture_patch()` 生成 `patch.diff`
  3. 实现 `write_input_artifacts()` 生成 `metadata.json`
  4. 集成安全层：捕获后自动过滤 + redaction
- **验收标准**: `ahadiff learn HEAD~1..HEAD --dry-run` 生成 `patch.diff` + `metadata.json`

#### Task 6: Diff 解析 + 结构化
- **类型**: 后端（Codex 实现）
- **文件范围**:
  - `src/ahadiff/git/parser.py`
  - `src/ahadiff/git/line_map.py`
  - `src/ahadiff/git/symbols.py`
  - `src/ahadiff/git/hunk_hash.py`
  - `tests/unit/test_diff_parser.py`
  - `tests/unit/test_line_map.py`
- **依赖**: Task 5
- **实施步骤**:
  1. 实现 unified diff 解析器（iter_hunks, iter_changed_files）
  2. 实现 `build_line_map()` 生成 `line_map.json`
  3. 实现 symbol extraction（Python AST + regex fallback）
  4. 实现 `compute_hunk_hash()`（内容规范化，不含时间戳）
- **验收标准**: 解析 examples/retry-backoff/patch.diff 输出正确的 line_map 和 symbols

### Layer 3（依赖 Layer 2）— Claim 闭环

#### Task 7: LLM Provider 适配
- **类型**: 后端（Codex 实现）
- **文件范围**:
  - `src/ahadiff/llm/provider.py`
  - `src/ahadiff/llm/local_ollama.py`
  - `src/ahadiff/llm/openai_provider.py`
  - `src/ahadiff/llm/anthropic_provider.py`
  - `src/ahadiff/llm/cache.py`
  - `src/ahadiff/llm/cost.py`
  - `src/ahadiff/llm/schemas.py`
  - `tests/unit/test_provider.py`
- **依赖**: Task 1
- **实施步骤**:
  1. 定义 `Provider` protocol + `ProviderRequest/Response`
  2. 实现 `make_provider()` 工厂
  3. 实现三个 adapter（httpx 直连，不用 SDK）
  4. 统一超时、重试、JSON 解码、token/cost audit
  5. 实现 audit.jsonl 记录
- **验收标准**: `pytest tests/unit/test_provider.py` 覆盖三种 provider mock

#### Task 8: Claim 提取与验证
- **类型**: 后端（Codex 实现）
- **文件范围**:
  - `src/ahadiff/claims/schema.py`
  - `src/ahadiff/claims/extract.py`
  - `src/ahadiff/claims/verify.py`
  - `src/ahadiff/claims/negative_scan.py`
  - `src/ahadiff/claims/classify.py`
  - `prompts/claim_extract.md`
  - `tests/unit/test_claim_verify.py`
  - `tests/unit/test_negative_scan.py`
  - `tests/unit/test_claim_classify.py`
- **依赖**: Task 6 + Task 7
- **实施步骤**:
  1. 定义 Pydantic schema：ClaimCandidate, ClaimRecord, NegativeEvidence
  2. 编写 `claim_extract.md` prompt
  3. 实现 deterministic verifier（file/line/hunk/symbol 检查）
  4. 实现 negative evidence scan（risky words + missing checks）
  5. 实现 `classify_claim()` 状态机
  6. 集成：`ahadiff claims <run_id>` 可展示四种状态
- **验收标准**: 对 retry-backoff fixture 生成 claims.jsonl，包含 verified/weak/not_proven/rejected_contradicted

## 文件冲突检查

✅ 无冲突 — 所有 Task 的文件范围完全隔离：
- Task 1: `core/*`, `cli.py`, `pyproject.toml`
- Task 2: `safety/*`, `tests/unit/test_redact.py`, `tests/unit/test_injection.py`
- Task 3: `CLAUDE.md`, `doc/*`
- Task 4: `*.html`（前端文件）
- Task 5: `git/repo.py`, `git/capture.py`
- Task 6: `git/parser.py`, `git/line_map.py`, `git/symbols.py`, `git/hunk_hash.py`
- Task 7: `llm/*`
- Task 8: `claims/*`, `prompts/*`

## 并行分组

```
Layer 1 (全并行): Task 1 + Task 2 + Task 3 + Task 4
   ↓
Layer 2 (并行):   Task 5 + Task 6 (依赖 Task 1)
                  Task 7 (可与 Layer 2 并行，仅依赖 Task 1)
   ↓
Layer 3:          Task 8 (依赖 Task 6 + Task 7)
```

## 模型分工

| Task | 实现 | Review |
|------|------|--------|
| Task 1 骨架 | Codex | Claude + Codex |
| Task 2 安全 | Codex | Claude + Codex |
| Task 3 文档 | Claude | 无需 review |
| Task 4 UI修复 | Claude | Gemini(gemini-3.1-pro-preview) + Codex |
| Task 5 Git捕获 | Codex | Claude + Codex |
| Task 6 Diff解析 | Codex | Claude + Codex |
| Task 7 Provider | Codex | Claude + Codex |
| Task 8 Claim | Codex | Claude + Codex |

## 预计 Builder 数量

- Layer 1: 4 个并行 Builder（2 Codex + 1 Claude 文档 + 1 Claude 前端）
- Layer 2: 3 个并行 Builder（2 Codex + 1 Codex Provider）
- Layer 3: 1 个 Builder（Codex Claim 闭环）

总计 ~8 个子任务，预计 2-3 天完成 Layer 1-3。
