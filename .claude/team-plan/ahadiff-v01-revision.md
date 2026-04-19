# AhaDiff v0.1 方案修订 — 基于源码实测 + CLI 接入扩展

> 修订时间：2026-04-19
> 基于：SOURCE-CODE-VERIFICATION-REPORT.md 的 12 项修订 + 主流 CLI 工具接入扩展

---

## 一、12 项源码验证修订（已应用）

### P0 修订（必须）

#### R1. Phase 2.5 触发条件
- **旧**：连续 2 轮卡住
- **新**：连续 2 个优化目标在首轮就无法改进（darwin-skill 原文："连续2个skill都在round1就break"）
- **影响范围**：improve_program.md, CLAUDE.md, 设计思路.md
- **实现映射**：AhaDiff 的 Phase 2.5 检测逻辑在 `improve loop` 中实现，检查 `results.tsv` 最近 2 条记录是否都是 `status=discard` 且 `rounds_completed=1`

#### R2. Phase 2.5 来源归因
- **旧**：部分归因于 autoresearch
- **新**：Phase 2.5 **完全**来自 darwin-skill。autoresearch 没有任何 stuck 检测，只有 "think harder"
- **影响范围**：CLAUDE.md 灵感项目段落、设计思路.md

#### R3. SkillCompass 维度归因
- **旧**：暗示 8 维来自 SkillCompass
- **新**：SkillCompass 原版 6 维（Structure/Trigger/Security/Functional/Comparative/Uniqueness），且评估对象是 **skill 文件质量**，不是学习笔记质量。AhaDiff 的 8 维（accuracy/evidence/diff_coverage/learnability/quiz_transfer/spec_alignment/conciseness/safety_privacy）是**完全自研体系**
- **影响范围**：CLAUDE.md, 设计思路.md, 评估系统描述

### P1 修订（应该）

#### R4. results.tsv 格式自行定义
- **旧**：混用 autoresearch 5 列和 darwin-skill 9 列
- **新**：AhaDiff 自定义 10 列

```
timestamp	run_id	head_sha	prompt_version	rubric_version	overall	verdict	status	weakest_dim	note
```

| 列 | 类型 | 说明 |
|----|------|------|
| timestamp | ISO 8601 | 运行时间 |
| run_id | string | `make_run_id()` 生成 |
| head_sha | string(7) | git short hash |
| prompt_version | string | `prompts/` 目录的 tree hash 前 7 位 |
| rubric_version | string | `rubric.yaml` 的 content hash 前 7 位 |
| overall | int 0-100 | 加权总分 |
| verdict | enum | PASS / CAUTION / FAIL |
| status | enum | baseline / keep / discard / rollback / crash / targeted_verify / keep_final |
| weakest_dim | string | 最弱维度的 json_key |
| note | string | 人类或 agent 的简短描述 |

#### R5. 三文件契约描述
- **旧**：暗示直接复刻
- **新**：AhaDiff 的 `evaluator.py` / `generator_prompt.md` 是对 autoresearch `prepare.py` / `train.py` 的**概念改编**
  - autoresearch 改的是 Python 代码（`train.py`），AhaDiff 改的是 Markdown prompt（`prompts/*.md`）
  - autoresearch 的评估指标是单一数值（`val_bpb`），AhaDiff 是 8 维 rubric + verdict

#### R6. SKILL0 budget 递减方式
- **旧**：线性递减
- **新**：**阶段跳变** `[6, 3, 0]`，不是线性
  - AhaDiff 映射：`lesson.full.md`（全解释） → `lesson.hint.md`（关键提示） → `quiz`（纯回忆）

#### R7. SKILL0 helpfulness 粒度
- **旧**：section helpfulness
- **新**：原论文实现是 **skill file 级**（如 `clean.md` 整体保留或移除）。AhaDiff 自行扩展到 section 粒度（每个 section 独立计算 Delta_k）

#### R8. PASS/CAUTION/FAIL 阈值
- **旧**：直接使用 80/60 无归因
- **新**：注明 SkillCompass 原版阈值为 70（PASS）/ 50（FAIL），AhaDiff 调高为 80 / 60，理由是学习笔记质量标准应高于 skill 文件格式检查

### P2 修订（可选，建议纳入）

#### R9. Graphify graph.json Schema
补充到方案中的具体 schema：
- Node: `{id, label, file_type, source_file, source_location, community, norm_label}`
- Edge: `{source, target, relation, confidence, confidence_score, source_file, weight}`
- 格式：标准 NetworkX node-link-data，可用 `nx.readwrite.json_graph.node_link_graph()` 加载
- AhaDiff 新增节点类型：`Claim`, `Concept`, `Lesson`, `Quiz`, `ReviewCard`, `Run`
- AhaDiff 新增边类型：`modifies`, `reviewed_by`, `evidence_for`, `contradicts`, `teaches`

#### R10. 机械化打分（借鉴 SkillCompass D3）
- `evidence` 和 `safety_privacy` 维度采用查表计算，避免 LLM 主观抖动
- evidence: 从 `claims.jsonl` 统计 verified/weak/not_proven/rejected 比例机械化打分
- safety_privacy: 从 `redaction_report.json` 统计 findings 机械化扣分

#### R11. Targeted Verification（借鉴 SkillCompass）
- improve loop 不重跑全 8 维，只验证：**目标维度 + accuracy + evidence + safety_privacy**（4 维）
- 理由：SkillCompass 的 "one dimension per round" + targeted verification 降低 ~50% token 消耗
- Codex 建议比原方案多加 accuracy，因为 accuracy 与 evidence 强耦合

#### R12. 简洁性准则（借鉴 autoresearch）
写入 `improve_program.md`：
> "0.001 分提升 + 20 行 hacky prompt 复杂化 → 不值得。0.001 分提升但简化了 prompt → 保留。"

### LLM Wiki 修订（补充项）

#### R13. Karpathy LLM Wiki Gist — 增量积累模式
- **来源**：Karpathy 2026 年 4 月发布的 GitHub Gist，纯 idea file，无可执行代码
- **当前方案落地**：`index.md` + `concepts.jsonl` + `concepts.md` 增量写入，而非每次重新生成孤立文档
- **原方案路径冲突**：前端设计手册（2.6 节）仍写 `commits/<sha>/lesson.md`，但完整方案已改为 `runs/<run_id>/lesson/lesson.full.md`
- **需修订**：
  1. 统一路径：前端设计手册中的 `commits/<sha>/` 引用应标注为旧版路径，以 `runs/<run_id>/` 为准
  2. 增量机制精确描述：LLM Wiki 的核心思想是"persistent compounding wiki"，AhaDiff 的 `index.md` 每次 learn 后追加新概念条目（而非覆盖），`concepts.jsonl` 是 append-only 的概念累积日志
  3. 与 Graphify 的边界：Graphify 做 repo-level 全局 map，LLM Wiki 模式做 diff-level 增量 learning overlay，两者互补不重叠
- **实现影响**：
  - `index.md` 更新逻辑需要 diff-aware merge（检测已存在概念，只添加新概念或更新引用计数）
  - `concepts.jsonl` 每行格式：`{concept, introduced_by_run, updated_by_runs[], related_claims[], file_refs[]}`
  - 前端 Lesson Reader 和 Learning Graph 页面需展示 backlinks、introduced by commit、updated by commit

---

## 二、CLI 工具接入扩展（第九段更新）

### 2.1 接入架构设计

`ahadiff install <target>` 统一架构：

```python
# src/ahadiff/install/base.py
class InstallTarget(Protocol):
    name: str
    config_paths: list[Path]        # 要写入的文件路径
    template_name: str              # Jinja2 模板名

    def detect(self) -> bool: ...   # 检测工具是否已安装
    def preview(self) -> str: ...   # dry-run 预览
    def write(self) -> list[Path]:  # 实际写入
    def uninstall(self) -> list[Path]: ...  # 清理
```

```
src/ahadiff/install/
  __init__.py
  base.py              # InstallTarget protocol
  registry.py          # 注册所有 target
  claude.py            # Claude Code
  codex.py             # Codex CLI
  gemini.py            # Gemini CLI (新增)
  opencode.py          # OpenCode (新增)
  cursor.py            # Cursor
  copilot.py           # GitHub Copilot
  hooks.py             # Git hooks (新增)
  templates/
    claude_skill.md.j2
    codex_agents.md.j2
    gemini_md.md.j2
    opencode_agents.md.j2
    cursor_rules.mdc.j2
    copilot_instructions.md.j2
    post_commit_hook.sh.j2
    pre_push_hook.sh.j2
```

### 2.2 各工具配置规范

#### Claude Code（已有，保持不变）
```
写入路径：.claude/skills/ahadiff/SKILL.md
         .claude/skills/ahadiff/references/*.md
全局路径：~/.claude/CLAUDE.md (追加)
检测方式：which claude
```

#### Codex CLI（已有，保持不变）
```
写入路径：AGENTS.md (追加 section)
全局路径：~/.codex/AGENTS.md
检测方式：which codex
```

#### Gemini CLI（新增）
```
写入路径：GEMINI.md (项目级，追加 section)
全局路径：~/.gemini/GEMINI.md (追加)
检测方式：which gemini
支持 @import：可拆分为 GEMINI.md + .gemini/ahadiff/*.md
```

写入内容：
```markdown
## AhaDiff learn-back rule

After meaningful AI-written changes, run:

\`\`\`bash
ahadiff learn HEAD~1..HEAD
\`\`\`

Rules:
- Every explanation must be grounded in file:line evidence.
- Unsupported claims must be marked `not_proven`.
- Dangerous misconceptions must be rejected and converted to quiz.
- Do not upload secrets or private files.
- Run `ahadiff verify <run_id>` to check claim accuracy.
```

#### OpenCode（新增）
```
写入路径：AGENTS.md (与 Codex 共享，追加 section)
         .opencode/agents/ahadiff.md (专用 agent 定义)
全局路径：~/.config/opencode/agents/ahadiff.md
检测方式：which opencode
兼容性：OpenCode 同时读取 AGENTS.md 和 CLAUDE.md 作为 fallback
```

写入 `.opencode/agents/ahadiff.md`：
```markdown
---
description: Turn AI-written git diffs into verified learning lessons
tools: ["bash"]
---

# AhaDiff Agent

Use the local `ahadiff` CLI to help users learn from AI-written code.

Primary command:
\`\`\`bash
ahadiff learn HEAD~1..HEAD --open
\`\`\`

Rules:
- Every explanation must be grounded in file:line evidence.
- Unsupported claims must be marked `not_proven`.
- Run `ahadiff quiz <run_id>` for active recall practice.
```

#### Cursor（已有，保持不变）
```
写入路径：.cursor/rules/ahadiff.mdc
检测方式：检查 .cursor/ 目录存在
```

#### GitHub Copilot（已有，保持不变）
```
写入路径：.github/copilot-instructions.md (追加)
         .github/instructions/ahadiff.instructions.md
检测方式：检查 .github/ 目录存在
```

### 2.3 Git Hook 集成（新增）

#### post-commit hook
```bash
ahadiff install hooks
```

写入 `.git/hooks/post-commit`（或通过 `core.hooksPath`）：
```bash
#!/bin/sh
# AhaDiff: auto-suggest learning after AI-written commits
DIFF_STAT=$(git diff HEAD~1..HEAD --stat | tail -1)
if [ -n "$DIFF_STAT" ]; then
  echo ""
  echo "💡 AhaDiff: Run 'ahadiff learn HEAD~1..HEAD' to learn this diff"
  echo "   $DIFF_STAT"
fi
```

特点：
- **非阻塞**：只打印提示，不自动运行（避免干扰 CI/自动化）
- **可选排队模式**：`ahadiff install hooks --queue` 写入 `.ahadiff/queue/<sha>.json`，后台异步处理（Codex 建议）
- **可选同步模式**：`ahadiff install hooks --sync` 则同步运行 `ahadiff learn --dry-run`
- **husky 兼容**：检测到 `.husky/` 时写入 `.husky/post-commit` 而非 `.git/hooks/`

#### pre-push hook（可选）
```bash
ahadiff install hooks --pre-push
```

展示未学习的 diff 摘要：
```bash
#!/bin/sh
UNLEARNED=$(ahadiff status --unlearned --count 2>/dev/null)
if [ "$UNLEARNED" -gt 0 ] 2>/dev/null; then
  echo "⚠️  AhaDiff: $UNLEARNED commits not yet learned"
  echo "   Run 'ahadiff learn --all' to catch up"
fi
```

### 2.4 GitHub Action 集成（新增，Codex 建议）

分两层设计：

**Layer 1: verify-only（默认，无需密钥）**
```yaml
# .github/workflows/ahadiff-verify.yml
name: AhaDiff Verify
on: [pull_request]
jobs:
  verify:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - run: uv sync
      - run: uv run ahadiff verify --ci  # 校验已存在 artifacts
```

**Layer 2: generate-on-CI（显式 opt-in，需模型密钥）**
```yaml
# .github/workflows/ahadiff-generate.yml
name: AhaDiff Generate
on:
  workflow_dispatch:
  push:
    branches: [main]
jobs:
  generate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with: { fetch-depth: 2 }
      - uses: astral-sh/setup-uv@v4
      - run: uv sync
      - run: uv run ahadiff learn HEAD~1..HEAD
        env:
          AHADIFF_API_KEY: ${{ secrets.AHADIFF_API_KEY }}
```

### 2.5 统一 CLI 命令

```bash
# 安装到特定工具
ahadiff install claude          # Claude Code skill
ahadiff install codex           # Codex AGENTS.md
ahadiff install gemini          # Gemini CLI GEMINI.md (新增)
ahadiff install opencode        # OpenCode agent (新增)
ahadiff install cursor          # Cursor rules
ahadiff install copilot         # GitHub Copilot instructions
ahadiff install hooks           # Git post-commit hook (新增)
ahadiff install hooks --queue   # Git hook with queue mode (新增)
ahadiff install hooks --sync    # Git hook with sync mode (新增)
ahadiff install hooks --pre-push # Git pre-push hook (新增)
ahadiff install github-action   # GitHub Action workflow (新增)

# 批量安装（自动检测已安装的工具）
ahadiff install --detect        # 检测并安装所有已安装的工具 (新增)

# 通用选项
ahadiff install <target> --dry-run   # 预览将写入的文件
ahadiff install <target> --force     # 覆盖已有配置
ahadiff uninstall <target>           # 清理配置文件
```

### 2.6 install --detect 自动检测逻辑

```python
def detect_installed_tools() -> list[str]:
    """检测本机已安装的 AI 编码工具"""
    targets = []
    if shutil.which("claude"):
        targets.append("claude")
    if shutil.which("codex"):
        targets.append("codex")
    if shutil.which("gemini"):
        targets.append("gemini")
    if shutil.which("opencode"):
        targets.append("opencode")
    if Path(".cursor").is_dir():
        targets.append("cursor")
    if Path(".github").is_dir():
        targets.append("copilot")
    return targets
```

---

## 三、更新后的开发顺序

### 第九段（agent install）更新

**原版**：install claude / codex / cursor / copilot / dry-run / safe merge / uninstall

**更新后**：

实现：
```
install 统一架构 (InstallTarget protocol)
install claude    (保持)
install codex     (保持)
install gemini    (新增)
install opencode  (新增)
install cursor    (保持)
install copilot   (保持)
install hooks     (新增：post-commit / pre-push)
install --detect  (新增：自动检测)
dry-run preview
safe merge (不覆盖用户配置)
uninstall
Jinja2 模板化配置生成
```

验收：
```bash
ahadiff install claude --dry-run
ahadiff install codex --dry-run
ahadiff install gemini --dry-run      # 新增
ahadiff install opencode --dry-run    # 新增
ahadiff install hooks --dry-run       # 新增
ahadiff install --detect --dry-run    # 新增
```

能展示将写入哪些本地文件，不默认覆盖用户已有配置。

---

## 四、团队计划更新摘要

### Task 3（文档 contract 冻结）需额外处理
- 应用 P0-1~3 + P1-1~5 修订到 CLAUDE.md 和设计思路文档
- 统一 results.tsv 为 10 列方案
- 注明所有灵感项目的精确归因

### Task 9（原第九段，新增）
- **类型**: 后端（Codex 实现）
- **文件范围**:
  - `src/ahadiff/install/base.py`
  - `src/ahadiff/install/registry.py`
  - `src/ahadiff/install/claude.py`
  - `src/ahadiff/install/codex.py`
  - `src/ahadiff/install/gemini.py` (新增)
  - `src/ahadiff/install/opencode.py` (新增)
  - `src/ahadiff/install/cursor.py`
  - `src/ahadiff/install/copilot.py`
  - `src/ahadiff/install/hooks.py` (新增)
  - `src/ahadiff/install/templates/*.j2`
  - `tests/unit/test_install.py`
- **依赖**: Task 1（工程骨架）
- **验收标准**: 6 个 target + hooks 的 dry-run 全部正确输出

---

## 五、Codex 分析摘要

### 12 项修订评估结论
- **全部 12 项直接采纳**，其中 4 项需要补充实现约束：
  - R4 `results.tsv`：`run_id` 作为唯一事件 ID，`prompt_version` 应为内容哈希而非手写标签
  - R6 `[6,3,0]`：只作为"借鉴原则"，不作为产品承诺（除非 v0.1 真做三阶段调度）
  - R7 `section helpfulness`：需定义聚合规则、最低样本量、回退到 file 级的逻辑 → **放 v0.2**
  - R10 机械化打分：不要整维度纯确定性，建议 `safety_privacy` 走确定性 gate+cap，`evidence` 走确定性 base+LLM 补充
- R11 `Targeted Verification` recheck 集合应更保守：**目标维度 + accuracy + evidence + safety_privacy**（比 Claude 方案多 accuracy）

### results.tsv 工程建议
- 定位为 **append-only evaluation event log**，不承担 cache/索引/报表职责
- `status` 必须枚举化：`baseline | keep | discard | rollback | crash | targeted_verify | keep_final`
- `note` 约定"短错误码前缀 + 自由文本"，例如 `EVIDENCE_MISSING_LINE: missing line evidence`
- 查询走 `review.sqlite` 的 `result_events` 表，索引：`(run_id UNIQUE)`, `(head_sha, timestamp DESC)`, `(prompt_version, rubric_version)`, `(verdict, status)`, `(weakest_dimension, timestamp DESC)`

### CLI 接入扩展建议
1. **Gemini CLI**：默认写项目根 `GEMINI.md`（不写 `settings.json`），只有 `--with-settings` 时才写 `.gemini/settings.json`。置信度 High
2. **OpenCode**：优先复用/合并项目根 `AGENTS.md`，richer integration 时补 `.opencode/agents/ahadiff.md`。置信度 High
3. **post-commit hook**：不应阻塞式跑 `ahadiff learn`，默认只排队到 `.ahadiff/queue/<sha>.json`，`--sync` 才同步
4. **pre-push hook**：默认只警告，`--enforce` 才阻断推送
5. **GitHub Action**：分两层 — verify-only（默认，无需密钥）+ generate-on-CI（显式 opt-in，需模型密钥）
6. **统一架构**：建议用 `IntegrationDescriptor` 驱动，5 种 surface（instruction/config/command/hook/workflow） × 2 种 scope（project/user），统一流水线 `detect → render → dry-run diff → safe merge → validate → record manifest → uninstall by manifest`
7. **行为约束**：默认不改用户全局配置，不默认启用阻断式 hook，不默认让 CI 带密钥生成

### 新增机制优先级（Codex 建议排序）
1. Targeted Verification（降低 improve loop 成本）
2. Deterministic gates/subscores（accuracy/evidence/safety_privacy 底座做硬）
3. improve_program 简洁性准则（零成本，抑制 prompt 膨胀）
4. results.tsv + SQLite result_events（稳定日志基础）
5. Graphify node-link-data contract（先定 schema，不急可视化）
6. section-level helpfulness → **放 v0.2**（file-level 先跑通）

### 开发顺序调整建议
Codex 建议保留 9 段，但在**第一段之前**增加「第零步：contract freeze」（只改文档真值，不写功能），并将原来的五六段顺序调整为：
- 第五段：score + verifier hard gates + results.tsv
- 第六段：improve loop + targeted verification + Phase 2.5
- 第七段：review 与 learning signal
- 第八段：viewer + Graphify overlay
- 第九段：agent & automation install（扩展为 6 工具 + hooks + GitHub Action）

---

## 六、参考来源

- [Gemini CLI GEMINI.md 文档](https://github.com/google-gemini/gemini-cli/blob/main/docs/cli/gemini-md.md)
- [Gemini CLI 配置指南](https://github.com/google-gemini/gemini-cli/blob/main/docs/get-started/configuration.md)
- [OpenCode 配置文档](https://opencode.ai/docs/config/)
- [OpenCode Agents 文档](https://opencode.ai/docs/agents/)
- [OpenCode Rules 文档](https://opencode.ai/docs/rules/)
- [OpenCode GitHub](https://github.com/opencode-ai/opencode)
