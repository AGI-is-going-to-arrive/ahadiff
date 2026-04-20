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
  - `AhaDiff Warm v6.html`（根目录）
  - `ui/AhaDiff Warm v6.html`
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

### Layer 1.5 / Layer 2（依赖 Layer 1）— LLM Provider + Git 捕获 + Diff 结构化

> **依赖关系**：Task 7 仅依赖 Task 1，可最早启动（Layer 1.5）。Task 5 依赖 Task 1（Layer 2a）。Task 6 依赖 Task 5 的 `capture_patch()` 输出（patch.diff），必须串行等待 Task 5 完成（Layer 2b）。

#### Task 5: Git diff 捕获
- **类型**: 后端（Codex 实现）
- **文件范围**:
  - `src/ahadiff/git/repo.py`
  - `src/ahadiff/git/capture.py`
  - `tests/unit/test_git_capture.py`
- **依赖**: Task 1
- **实施步骤**:
  1. 实现 `open_repo()`, `resolve_ref_range()`
  2. 实现 `capture_patch()` 生成 `patch.diff`，支持 4 种 Level 3 输入模式：
     - ref range: `HEAD~1..HEAD` 或 `abc123..def456`（核心路径）
     - `--last`: 语法糖，先检查 HEAD 父提交数：0 父用 `git diff-tree --root`，多父用 `--first-parent` 语义
     - `--staged`: 调用 `git diff --cached --no-ext-diff`（暂存区未 commit 的改动）
     - `--since "2h ago"`: 用 `git rev-list --first-parent --since` 获取命中 commit 列表；连续后缀则做端点 diff，非连续则聚合各 commit patch。`--author` 在 Python 层做精确过滤（git 的 `--author` 是正则匹配）
  3. 实现 `write_input_artifacts()` 生成 `metadata.json`，包含 `capability_flags`：`has_repo_context / has_symbol_index / has_cross_file_context / has_head_sha / has_graph`（Level 3 全 true，Level 2/1 按实际降级）
  4. 集成安全层：捕获后自动过滤 + redaction
  5. 实现 `--patch file.patch` / `--patch -`（stdin）Level 1 输入：直接读取 unified diff 文本，跳过 git 操作
- **验收标准**:
  - `ahadiff learn HEAD~1..HEAD --dry-run` 生成 `patch.diff` + `metadata.json`
  - `ahadiff learn --last --dry-run` 等价于上述
  - `ahadiff learn --staged --dry-run` 捕获暂存区 diff
  - `ahadiff learn --since "1h ago" --dry-run` 扫描时间范围内的 commit
  - `ahadiff learn --patch tests/fixtures/sample.patch --dry-run` 读取外部 patch 文件

#### Task 6: Diff 解析 + 结构化
- **类型**: 后端（Codex 实现）
- **文件范围**:
  - `src/ahadiff/git/parser.py`
  - `src/ahadiff/git/line_map.py`
  - `src/ahadiff/git/symbols.py`
  - `src/ahadiff/git/hunk_hash.py`
  - `tests/unit/test_diff_parser.py`
  - `tests/unit/test_line_map.py`
  - `tests/unit/test_symbol_extract.py`
- **依赖**: Task 5
- **实施步骤**:
  1. 实现 unified diff 解析器（iter_hunks, iter_changed_files）
  2. 在 hunk 解析中提取 `section_header`（@@ 行尾的函数/类签名，零依赖零成本）
     - 正则：`r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@[ ]?(.*)"` 第 5 组即为 section_header
     - 来源：PR-Agent `git_patch_processing.py:RE_HUNK_HEADER`，git 自动生成此信息
     - 示例：`@@ -15,7 +15,8 @@ def retry_with_backoff(max_retries=3):` → section_header = `def retry_with_backoff(max_retries=3):`
     - 输出到 `HunkRecord.section_header` 字段，作为免费 symbol hint
  3. 实现 `build_line_map()` 生成 `line_map.json`
  4. 实现 symbol extraction 三层策略：
     - **采集阶段**：三个 extractor 按可用性依次尝试，输出统一 `SymbolRecord`
       a. **section_header**：步骤 2 已从 hunk header 提取，所有语言通用，作为最低成本 hint
       b. **Python `ast` 模块**：仅 `.py` 文件，提取函数/类/方法/导入/测试函数
       c. **regex fallback**：AST 失败或非 Python 文件时，匹配 `def/class/function/const/export` 等模式
     - **合并优先级**（权威性递减）：`python_ast > regex > section_header`
       - 同一 symbol 被多个 extractor 命中时，取最高权威性的 extractor 结果
       - section_header 仅在其他 extractor 均未命中时保留为独立 symbol
     - 定义 `SymbolExtractor` protocol：`extract(path, before_text, after_text, hunks) -> list[SymbolRecord]`
     - `SymbolRecord` 字段：`path, qualified_name, kind, range, selection_range, parent, touched_lines, hunk_ids, hunk_hash, change_kind, extractor, confidence`
       - `path`：文件路径（repo-relative），确保跨文件同名 symbol 可区分
       - `hunk_ids`：关联的 hunk 标识列表，与 `hunk_hash` 契约统一（使用 `compute_hunk_hash()` 的输出）
     - `extractor` 枚举：`section_header | python_ast | regex`
     - `confidence` 对应：`python_ast=high | regex=medium | section_header=low`
     - **降级契约**（每层失败时的统一处理）：
       - AST parse 失败（语法错误/编码问题）→ 降级为 regex，记录 `error` 字段
       - regex 也失败 → 保留 section_header-only 记录（如果有）
       - section_header 为空（如 `@@ -0,0 +1 @@` 新文件）→ 该 hunk 无 symbol hint
       - binary/unsupported 文件 → 返回空 `[]`，不报错
       - 删除的文件 → 仅解析 before_text；新增文件 → 仅解析 after_text
       - 重命名/移动的 symbol → `change_kind=renamed`，新旧 qualified_name 都记录
  5. 实现 `compute_hunk_hash()`（内容规范化，不含时间戳）
- **验收标准**:
  - 解析 examples/retry-backoff/patch.diff 输出正确的 line_map、symbols 和 section_headers
  - Python 文件的 symbols 使用 `python_ast` extractor，JS/TS 等文件降级为 `section_header` + `regex`
  - AST parse 失败时自动降级为 regex，不中断主链路
  - `tests/unit/test_symbol_extract.py` 覆盖：
    - 三层策略的降级路径（AST 成功/AST 失败降级 regex/regex+section_header only）
    - hunk header 边界：`@@ -0,0 +1 @@`（空 section_header）、`@@ -1 +1,2 @@`（无 size）
    - 重复 symbol 去重与 extractor 优先级合并
    - 删除/新增/重命名文件的 symbol 处理
    - AST 语法错误文件的 graceful fallback
    - binary/unsupported 文件返回空列表

### Layer 1.5（依赖 Task 1）— LLM Provider 适配

> Task 7 仅依赖 Task 1，可与 Layer 2a/2b 并行启动。

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
  5. 实现调度层：per-provider QPS 限制（config.toml 配置）、exponential backoff（Retry-After header 解析）、并发预算（默认 max_concurrent=3）、上下文窗口超限检测（请求前估算 token 数）
  6. 实现 audit.jsonl 记录
- **验收标准**:
  - `pytest tests/unit/test_provider.py` 覆盖三种 provider mock
  - 429 响应触发 backoff，不崩溃；并发超限时排队

### Layer 3（依赖 Layer 2b + Layer 1.5）— Claim 闭环

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
  3. 实现 deterministic verifier（按检查顺序，参照 §10.2 设计）：
     a. **file 检查**：claim 引用的 file 是否出现在 patch.diff（不在 patch 中 → rejected）
     b. **line range 检查**：claim.source_hunks[{file, start, end}] 是否落在 hunk 范围内
     c. **hunk_id 匹配**：claim 引用的 hunk 是否与 line_map 中的 hunk 对应
     d. **symbol 存在性检查**（消费 Task 6 `SymbolRecord`）：
        - `claim.symbols[]` 是否命中 `SymbolRecord.qualified_name`（同 path 下匹配）
        - 匹配时使用 fuzzy 对比：先精确匹配，失败后 normalize（strip 空白/大小写/分隔符差异）
        - fuzzy match 额外约束：命中后需确认 `SymbolRecord.parent` scope 一致或 `touched_lines` 与 claim 的 `source_hunks` 有 overlap，否则降为候选信号（confidence=low），不直接计入 verified
        - symbol 命中置信度：`python_ast` 命中 → high；`regex` 命中 → medium；仅 `section_header` → low
     e. **risky generalization 检查**：claim 是否含 risky words（faster/secure/always/never 等）但无对应证据
     f. **deleted/renamed symbol**：claim 引用已删除的 symbol → 标注 `change_kind=deleted`
  4. 实现 negative evidence scan（risky words + 结构缺失检查）：
     - Python 文件：利用 AST 检查 try/except、test_ 函数、assert、import 等结构是否存在
     - 非 Python 文件：回退到 regex + risky words 扫描
     - **非 Python 限制声明**：regex + risky words 扫描仅产生 weak signal，不直接驱动 contradicted 状态。性能/安全/重试类 claim 的否定性结论需至少两项证据（结构缺失 + risky words 共存），单项不足以判定
     - claim 声称有重试/安全/性能但 AST 中无对应结构 → negative evidence
  5. 实现 `classify_claim()` 状态机
  6. 集成：`ahadiff claims <run_id>` 可展示五种状态
- **验收标准**:
  - 对 retry-backoff fixture 生成 claims.jsonl，包含 verified/weak/not_proven/contradicted/rejected
  - file 不在 patch 中的 claim → rejected（reason_code=file_not_in_patch）
  - **Claim 状态枚举冻结为 5 态**：`verified | weak | not_proven | contradicted | rejected`。`rejected` 表示 claim 引用了 patch 外的文件或不存在的证据，与 `contradicted`（证据直接反驳）语义不同。每个 rejected claim 附带 `reason_code` 字段。reason_code 枚举：`file_not_in_patch | line_outside_hunk | symbol_not_found | hunk_id_mismatch | evidence_missing`。
  - 引用不存在 symbol 的 claim → not_proven（非 FAIL，因为可能是 regex 漏匹配或 section_header 未覆盖）
  - `python_ast` 命中的 symbol 验证结果标注 `confidence=high`
  - risky words claim 无结构证据 → weak 或 not_proven
  - `tests/unit/test_claim_verify.py` 覆盖：file-not-in-patch、line-outside-hunk、symbol-not-found、symbol-fuzzy-match、risky-word-without-evidence、deleted-symbol-reference

## 文件冲突检查

✅ 无冲突 — 所有 Task 的文件范围完全隔离：
- Task 1: `core/*`, `cli.py`, `pyproject.toml`
- Task 2: `safety/*`, `tests/unit/test_redact.py`, `tests/unit/test_injection.py`
- Task 3: `CLAUDE.md`, `doc/*`
- Task 4: `*.html`（前端文件）
- Task 5: `git/repo.py`, `git/capture.py`
- Task 6: `git/parser.py`, `git/line_map.py`, `git/symbols.py`, `git/hunk_hash.py`, `tests/unit/test_symbol_extract.py`
- Task 7: `llm/*`
- Task 8: `claims/*`, `prompts/*`

## 并行分组

```
Layer 1 (全并行):  Task 1 + Task 2 + Task 3 + Task 4
   ↓
Layer 1.5 (并行):  Task 7 (仅依赖 Task 1，可最早启动)
Layer 2a (并行):   Task 5 (依赖 Task 1)
Layer 2b (串行):   Task 6 (依赖 Task 5，消费 patch.diff)
   ↓
Layer 3:           Task 8 (依赖 Task 6 + Task 7)
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

总计 ~8 个子任务。

**估时修正**：原始 2-3 天估算偏乐观。Task 8（Claim 6步验证）含 800-1000 LoC + symbol fuzzy match + negative scan，单独需 2-3 天。建议 Layer 1-3 总计 5-7 天。
