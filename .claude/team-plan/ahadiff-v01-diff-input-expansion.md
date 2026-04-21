# AhaDiff v0.1 · Diff 输入扩展方案（v2 · 经 Codex + Claude 交叉 Review）

> 解决两个设计缺口：(1) 会话级自动扫描 (2) 非 git 场景支持
> 
> Review 结论：方向正确，但初版过度低估了 git 语义的耦合深度。本版根据 Codex（48/100 → NEEDS_IMPROVEMENT）和 Claude 的审查意见修订。

---

## 问题分析

### 缺口 1：会话级自动扫描

**现状**：用户必须手动指定 ref range（`HEAD~1..HEAD`）或用 `--last` 只看最后一个 commit。

**痛点**：vibe coding 一次会话可能产生多个 commit（Claude Code 默认每完成一个子任务就 commit），用户不知道这次会话到底改了多少。

### 缺口 2：非 git 场景

**现状**：`ahadiff learn` 步骤 1 就是"检查当前目录是否为 git repo"，不是 git 仓库就直接退出。

**痛点**：很多 IDE（VS Code, JetBrains, Zed 等）内置 Local History，单文件修改也能查看 diff。用户在 playground、scratch file、REPL 等场景也有学习需求。

---

## Review 发现汇总

### Critical（必须修复）

| # | 来源 | 问题 | 修复 |
|---|------|------|------|
| C1 | Codex | "步骤 3-29 不变"不成立。metadata(步骤5)、symbols(步骤11)、verifier(步骤15-16)、evaluator(步骤23)、results.tsv(步骤27) 都深度绑定 git 语义 | 引入 source capability 分级，显式标注哪些步骤需要分支 |
| C2 | Codex | `results.tsv` 第3列 `head_sha` 对非 git 场景无意义，"11 列不变"不成立 | `head_sha` → `source_ref`（git 场景填 SHA，非 git 填 content hash） |
| C3 | Codex | `--patch`/`--diff` 引入不受信输入，缺安全边界定义 | 补充 External Diff Source 安全边界 |
| C4 | Claude | 非 git 场景违反"改进必须可回滚"原则 | 非 git 模式禁用 ratchet，status 标为 `non_ratcheted` |
| C5 | Claude | `--diff old.py new.py` 命名与工具名 AhaDiff 冲突 | 改为 `--compare` |

### Warning（应修复）

| # | 来源 | 问题 | 修复 |
|---|------|------|------|
| W1 | Codex | `--session` 在版本规划中自相矛盾（策略说 v0.2，优先级表说 v0.1） | v0.1 只发布 `--since`，`--session` 推迟 |
| W2 | Codex | DiffSource 接口 `get_file_content(path, version)` 过宽 | 缩薄为 `capture() -> CapturedDiff` |
| W3 | Codex+Claude | v0.1 塞了太多（--session/--since/--patch/--diff/DiffSource），scope creep | v0.1 收缩到 `--since` + `--patch` + 最小抽象 |
| W4 | Codex | `source_detail` 中 `old_path/new_path` 存绝对路径，有隐私泄漏面 | artifact 默认存相对路径，绝对路径只放 audit.private.jsonl |
| W5 | Claude | 非 git 场景下 backlinks/graph/ratchet 面板为空但不提示 | viewer 添加 degraded feature banner |

---

## 修订后方案

### 1. 会话级扫描：`--since`（v0.1）

```bash
# 按时间范围扫描（v0.1 正式 API）
ahadiff learn --since "2 hours ago" --open
ahadiff learn --since "1 hour ago" --author "Claude" --open

# --session 仅作为 --since 4h 的 heuristic alias（v0.1 隐藏，v0.2 转正）
ahadiff learn --session --open   # 等价于 --since "4 hours ago"
```

**实现**：纯 git 操作，`git log --since=... --format=%H | tail -1` 获取最早 commit，然后 `learn <oldest>..HEAD`。

**状态追踪（v0.2）**：`ahadiff learn` 完成后写入 `.ahadiff/last_learned_sha`，`--session` 自动从上次学习点到 HEAD。

### 2. 非 git 输入：Source Capability 分级

#### 2.1 三层验证能力

> **Codex 建议**：不是"步骤 3-29 不变"，而是步骤按 capability 分支。

```text
Level 3 · git-grounded（完整能力）
  ✓ file:line 证据绑定
  ✓ symbol 提取（import tree、call graph）
  ✓ 跨文件上下文（改了 A，影响 B）
  ✓ ratchet 回滚（git revert）
  ✓ source_ref 版本追踪
  ✓ backlinks / graph overlay
  来源：git ref range, --staged, --last, --since

Level 2 · workspace-grounded（有本地文件）
  ✓ file:line 证据绑定
  ✓ symbol 提取（仅 diff 涉及的文件）
  ✗ 跨文件上下文（无 git history）
  ✗ ratchet 回滚
  ✗ source_ref
  ✓ backlinks（限当前 run）
  来源：--compare old.py new.py

Level 1 · patch-grounded（只有 diff 文本）
  ✓ file:line 证据绑定（基于 hunk）
  ✗ symbol 提取（无完整文件）
  ✗ 跨文件上下文
  ✗ ratchet 回滚
  ✗ source_ref
  ✗ backlinks
  来源：--patch file.patch, --patch -（stdin）
```

#### 2.2 受影响的 learn 步骤

| 步骤 | 原方案 | Level 3 (git) | Level 2 (workspace) | Level 1 (patch) |
|------|--------|---------------|---------------------|-----------------|
| 1-2 | 检查 git repo + 解析 ref | 不变 | 选择 FileDiffSource | 选择 PatchDiffSource |
| 5 | 写 metadata.json | source_ref = git SHA | source_ref = patch content hash | 同 Level 2 |
| 11 | 提取 changed symbols | 完整 import tree | 仅 diff 文件的 symbols | 跳过 |
| 15-16 | deterministic verifier | 完整验证 | 降级：跨文件 claim 最高 `weak` | 降级：repo-wide claim `not_proven` |
| 23 | evaluator.py 打分 | 8 维完整 | D3 Diff Coverage 基于 patch 内文件 | D3 基于 hunk 覆盖 |
| 27 | 追加 results.tsv | source_ref 列填 SHA | source_ref 列填 content hash | 同上 |

#### 2.3 Ratchet 处理（修复 C4）

```text
Level 3 (git)：ratchet 完整可用，status 含 baseline/keep/discard/crash/targeted_verify/keep_final/phase25_rewrite（7 态）
Level 2/1：ratchet 禁用，status 固定为 non_ratcheted
viewer 中棘轮面板显示 banner："此 run 来自非 git 输入，棘轮改进不可用"
```

### 3. v0.1 最小实现范围（修复 W3）

```text
v0.1 正式发布：
  --since "2 hours ago"         # 会话时间范围扫描（纯 git）
  --patch file.patch            # patch 文件输入
  --patch -                     # stdin 管道输入
  DiffSource 最小抽象           # capture() -> CapturedDiff

v0.1 隐藏（--help 不显示）：
  --session                     # --since 4h 的 alias

v0.1.1（紧随其后）：
  --compare old.py new.py       # 单文件对比（非 git 核心场景）

v0.2：
  --session 状态追踪            # last_learned_sha
  --compare ./dir1/ ./dir2/     # 目录对比

v0.2+（延后）：
  --ide-history                 # IDE Local History
  --clipboard                   # 剪贴板
  ahadiff watch                 # 文件系统监控
```

### 4. 缩薄后的 DiffSource 接口（修复 W2）

```python
# src/ahadiff/core/diff_source.py

@dataclass
class CapturedDiff:
    patch_text: str                      # unified diff 文本
    source_kind: Literal["git", "patch", "file_compare"]
    source_ref: str                      # git SHA / content hash
    capability_level: Literal[1, 2, 3]   # 验证能力等级
    metadata_extra: dict                 # source-specific 附加信息
    file_snapshots: dict[str, str] | None  # path → file content（Level 2+ 可用）

class DiffSource(Protocol):
    def capture(self) -> CapturedDiff: ...
```

### 5. metadata.json 扩展（修复 C2，兼容原 §9）

```json
{
  "run_id": "20260420-session-retry",
  "repo": "my-project",
  "base_ref": "HEAD~3",
  "head_ref": "HEAD",
  "source_ref": "abc1234",
  "source_kind": "git",
  "source_ref": "abc1234",
  "capability_level": 3,
  "source_detail": {
    "type": "since",
    "since": "2026-04-20T10:00:00",
    "commits": ["abc1234", "def5678", "ghi9012"],
    "commit_count": 3
  },
  "created_at": "2026-04-20T14:32:10+10:00",
  "mode": "learn",
  "level": "intermediate",
  "provider": { "generate": "ollama/qwen3-coder", "judge": "ollama/qwen3-coder" },
  "privacy_mode": "strict_local"
}
```

非 git（Level 1 patch）：

```json
{
  "run_id": "20260420-patch-review",
  "repo": null,
  "base_ref": null,
  "head_ref": null,
  "source_ref": "patch-sha256-xxxx",
  "source_kind": "patch",
  "source_ref": "sha256:a1b2c3...",
  "capability_level": 1,
  "source_detail": {
    "type": "patch_file",
    "filename": "fix.patch",
    "patch_hash": "sha256:a1b2c3..."
  },
  "created_at": "2026-04-20T15:00:00+10:00",
  "mode": "learn",
  "level": "intermediate",
  "provider": { "generate": "ollama/qwen3-coder", "judge": "ollama/qwen3-coder" },
  "privacy_mode": "strict_local"
}
```

**原方案字段全部保留**（additive only），git 场景完全向后兼容。

### 6. results.tsv 列变更（修复 C2）

```text
原方案第3列：head_sha（string(7)）

修订后：
  列名改为 source_ref
  git 场景：填 git short hash（向后兼容）
  patch 场景：填 patch content hash 前 7 位
  file_compare 场景：填文件 content hash 前 7 位
```

其余 9 列完全不变。

### 7. External Diff Source 安全边界（修复 C3）

```text
--patch 安全规则：
  stdin 限流：默认 10MB，可配 config.toml [safety].max_patch_size
  文本模式读取，拒绝二进制
  patch 内容经过 prompt injection 转义（复用原 §18.3）
  patch 中的路径不用于文件系统访问

--compare 安全规则：
  只接受 regular file，拒绝 /dev/、socket、FIFO
  不跟随 symlink（默认），可配 --follow-symlinks
  拒绝绝对路径中的 .. 穿越
  artifact 中默认存相对路径，绝对路径只放 audit.private.jsonl
  diff 输出限流：单文件 > 1MB 时警告并建议 --ignore

viewer/terminal 渲染：
  所有 source 的输出统一经过 HTML entity escape
  路径显示脱敏（不暴露完整本机路径）
```

### 8. Viewer 降级提示（修复 W5）

```text
Level 1 (patch) viewer banner：
  "此 lesson 来自 patch 文件输入，以下功能不可用：
   反向链接 · 概念图谱 · 棘轮改进 · Symbol 索引"

Level 2 (file_compare) viewer banner：
  "此 lesson 来自文件对比，以下功能不可用：
   棘轮改进 · 跨文件上下文 · Git 历史追踪"
```

### 9. 命令体系最终版

```bash
# === v0.1 新增 ===

# 会话时间范围扫描（git 场景）
ahadiff learn --since "2 hours ago" --open
ahadiff learn --since "1 hour ago" --author "Claude" --open

# Patch 文件输入（Level 1）
ahadiff learn --patch fix.patch --open
ahadiff learn --patch - --open               # stdin
curl -L .../pull/42.patch | ahadiff learn --patch - --open

# === v0.1.1 新增 ===

# 文件对比（Level 2）
ahadiff learn --compare old.py new.py --open

# === v0.2 新增 ===
ahadiff learn --session --open               # 状态追踪式会话扫描
ahadiff learn --compare ./before/ ./after/ --open  # 目录对比

# === 原有命令不变 ===
ahadiff learn HEAD~1..HEAD --open
ahadiff learn --staged --open
ahadiff learn --last --open
ahadiff learn abc123 --open
```

### 10. 对原方案的影响（修订版）

| 原方案章节 | 变更类型 | 具体变更 |
|-----------|---------|---------|
| § 3 产品原则 | additive | 新增："diff 来源不限于 git，但 git 是默认主流程。非 git 模式明确标注降级功能" |
| § 7 命令体系 | additive | 新增 --since / --patch / --compare 命令 |
| § 8 learn 全流程 | **分支** | 步骤 1-2 改为 DiffSource 选择；步骤 5/11/15-16/23/27 按 capability level 分支 |
| § 5 目录设计 | additive | metadata.json 新增 source_kind / source_ref / capability_level / source_detail |
| § 6 工程结构 | additive | 新增 core/diff_source.py, patch/capture.py |
| § 9 数据结构 | **修改** | results.tsv 第3列 head_sha → source_ref（git 场景向后兼容） |
| § 16 Ratchet | **分支** | 非 git 场景禁用 ratchet，status = non_ratcheted |
| § 18 安全设计 | additive | 新增 External Diff Source 安全边界 |
| § 19 Viewer | additive | 非 git 场景显示降级 banner |
| § 20 agent install | additive | install 时可配 post-session hook |

### 11. 不变的核心（经验证）

- claims 验证的核心逻辑（claim → file:line evidence）在所有 level 都可用（基于 hunk）
- 8 维 rubric 评分框架不变（D3 按 capability level 调整基准）
- N-文件契约不变（evaluation bundle immutable + prompts/*.md 可变）
- quiz/cards/SRS 生成链路不变
- local-first / SQLite 即唯一真相源 / claim-first 原则不变

---

## Codex Review 原始评分

```text
TOTAL SCORE: 48/100 → NEEDS_IMPROVEMENT
修订后预期：~75/100（C1-C5 全部修复，W1-W5 部分修复，scope 收缩）
```
