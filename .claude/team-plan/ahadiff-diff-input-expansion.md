# AhaDiff Diff 输入扩展设计

> 日期：2026-04-21
> 评估方法：Codex + Claude 交叉分析
> 状态：**已冻结（v0.1 部分），v0.2/v0.3 为设计草案**

---

## 总览：捕获方式全景图

```
v0.1（8 种捕获方式 · 3 Levels）
├── Level 3 · Git（完整功能：证据链 + 棘轮 + 概念图谱）
│   ├── A. --last          最后一次 commit
│   ├── B. --since "2h"    时间范围扫描
│   ├── C. --staged        暂存区（git add 后）
│   ├── D. HEAD~5..HEAD    commit 范围
│   ├── E. --unstaged      工作区未暂存改动（NEW）
│   └── F. abc1234         单 commit（git show 语义）（NEW）
├── Level 1 · Patch（无需 git）
│   └── G. --patch file / -  patch 文件或 stdin
└── Level 2 · File Compare（无需 git）
    └── H. --compare a b   单文件新旧对比

v0.2（新增 3 种）
├── I. --compare-dir old/ new/    目录递归对比（Level 2）
├── J. --patch-url URL            远端 patch 下载（Level 1）
└── RunSource schema 三维拆分 + degraded_flags 扩展

v0.3（新增 2 种）
├── K. .ipynb cell-aware diff     Notebook 感知（Level 2/3）
└── L. --url PR_URL               平台 PR/MR 集成（基于 J 扩展）
```

---

## Capture Pipeline 统一设计（C-4 修复）

**问题**：capture→parse→redact 与 raw→scan→redact→才能 log/cache/model 之间存在顺序矛盾。

**解决方案：raw/redacted 双表示**

```
输入源（git/patch/compare）
    │
    ▼
① capture_raw()        → raw_patch（仅内存，不落盘）
    │
    ▼
② secret_scan(raw)     → redaction_map（哪些位置需要脱敏）
    │
    ▼
③ parse_patch(raw)     → HunkRecord[] + LineMap + SymbolRecord[]
    │                     （在原始文本上解析，保证 AST/行号准确）
    │
    ▼
④ apply_redaction(parsed, map) → redacted artifacts
    │                              （用 map 替换敏感内容，保持行号不变）
    │
    ▼
⑤ persist(redacted)    → patch.diff + metadata.json + line_map.json
    │                     （只持久化 redacted 版本）
    │
    ▼
⑥ learn pipeline       → lesson/claims/quiz（只消费 redacted）
```

**关键约束**：
- raw_patch 永不落盘、永不进日志、永不发送到模型
- parse 在 raw 上执行（保证 AST 准确性）
- redaction_map 记录 `[(start, end, replacement)]`
- apply_redaction 替换后保持行号不变（用等长占位符）
- 所有下游只消费 redacted 版本

---

## v0.1 新增详细设计

### E. `--unstaged`（工作区未暂存改动）

**场景**：用户用 AI 写完代码，还没 `git add`，想先学习理解改了什么。这是 AI coding 后最高频的学习时点。

**实现**：
```python
# capture.py
def capture_unstaged(repo_path: Path) -> str:
    # git diff --no-ext-diff（不含 staged，不含 untracked）
    result = subprocess.run(
        ["git", "diff", "--no-ext-diff"],
        capture_output=True, text=True, cwd=repo_path
    )
    if not result.stdout.strip():
        raise InputError("没有未暂存的改动。用 --staged 或 --last 试试？")
    return result.stdout
```

**source_kind**：`git_unstaged`

**CLI 用法**：
```bash
# 学习当前未暂存的所有改动
ahadiff learn --unstaged

# 学习全部工作区改动（staged + unstaged 统一对比 HEAD）
ahadiff learn --staged --unstaged
# 等价于 git diff HEAD（单一基准状态，不拼接两份 patch）

# 包含 untracked 新文件
ahadiff learn --unstaged --include-untracked
# git diff + git ls-files --others --exclude-standard → 新文件当作全新增 diff

# 默认行为（无参数时）
ahadiff learn
# → 等价于 --last（不自动推断 --unstaged，避免意外）
```

**`--staged --unstaged` 组合语义**（C-1 修复）：
> 不拼接两份 patch。直接执行 `git diff HEAD --no-ext-diff`，产出单一 patch 以 HEAD 为基准，包含 index 和 worktree 的全部改动。source_kind=`git_staged_unstaged`，metadata 记录 `combined_mode=true`。

**Corner Cases**：

| Case | 行为 | 理由 |
|------|------|------|
| staged + unstaged 同时存在 | `--unstaged` 只捕获未暂存部分 | 与 git diff 语义一致 |
| `--staged --unstaged` 组合 | 执行 `git diff HEAD`（单一基准） | 避免 patch 拼接导致 anchor 失真 |
| 有 untracked 新文件 | 默认不含，CLI warn；`--include-untracked` 纳入 | 防止意外纳入 node_modules 等 |
| `--include-untracked` 含大量新文件 | 按 `.ahadiffignore` 过滤 + `file_count_exceeded` 截断 | 复用现有 degraded 策略 |
| 工作区无改动 | InputError + 提示 "用 --staged 或 --last 试试" | 友好错误 |
| binary 文件改动 | 设置 `degraded_flags.binary_only` | 复用现有策略 |
| 子模块 (submodule) 改动 | 跳过 + warn | git diff 默认不展开子模块 |
| git worktree 中运行 | 正常工作（git diff 自动感知 worktree） | — |
| merge 冲突状态 | InputError "请先解决 merge 冲突" | git diff 在冲突时输出非标准格式 |
| bare repo | InputError "bare 仓库没有工作区" | 无工作区可 diff |
| detached HEAD | 正常工作，metadata 记录 `head_detached=true` | git diff 不依赖分支指针 |
| unmerged index (部分冲突已解决) | InputError "请先完成所有冲突解决" | 混合状态不可靠 |
| shallow clone | 正常工作 | git diff 只看工作区，不需要完整历史 |

---

### F. `git show <sha>`（单 commit 学习）

**场景**：用户想学习某个历史 commit 的改动。

**实现**：
```python
# capture.py
def capture_single_commit(repo_path: Path, sha: str) -> str:
    # 验证 sha 存在
    verify = subprocess.run(
        ["git", "cat-file", "-t", sha],
        capture_output=True, text=True, cwd=repo_path
    )
    if verify.returncode != 0:
        raise InputError(f"commit {sha} 不存在")
    # 获取 diff
    result = subprocess.run(
        ["git", "diff-tree", "-p", "--first-parent", sha],
        capture_output=True, text=True, cwd=repo_path
    )
    return result.stdout
```

**source_kind**：复用 `git_ref`（source_ref = sha）

**CLI 用法**：
```bash
# 学习单个 commit
ahadiff learn abc1234

# 与范围模式区分：有 ".." 则为范围，无 ".." 则为单 commit
ahadiff learn abc1234..def5678   # → 范围模式
ahadiff learn abc1234            # → 单 commit 模式
```

**Corner Cases**：

| Case | 行为 | 理由 |
|------|------|------|
| sha 不存在 | InputError | 明确报错 |
| 短 sha 有歧义 | InputError "sha 'abc' 有歧义，匹配 N 个 commit" | git 会返回 ambiguous argument |
| merge commit (多父) | 用 `--first-parent` 只看主分支改动 | 与 --last 行为一致 |
| 初始 commit (无父) | 用 `git diff-tree --root` | 对比空树 |
| tag 名称 | 解析为对应 commit sha | git 自动处理 |
| branch 名称 | 解析为 HEAD commit | git 自动处理 |
| sha 指向 tree/blob | InputError "不是 commit 对象" | 只接受 commit |

---

## v0.2 设计

### I. `--compare-dir old/ new/`（目录递归对比）

**场景**：对比两个目录版本（如下载的库新旧版本、非 git 项目迭代）。

**source_kind**：复用 `file_compare`（`source_detail.compare_scope = "dir"`）

**capability_level**：2（有文件快照，无 git ancestry）

**实现要点**：
```
old/                  new/
├── src/              ├── src/
│   ├── main.py       │   ├── main.py      ← 内容对比
│   └── utils.py      │   ├── utils.py     ← 内容对比
│                     │   └── helper.py    ← 新增文件
├── config.yaml       ├── config.yaml      ← 内容对比
└── data.bin          └── data.bin         ← binary skip
```

1. 递归遍历两个目录，建立文件路径映射
2. 对每对文件生成 unified diff
3. 新增/删除的文件生成完整 add/remove diff
4. 合并为单份 patch，喂给 `parse_patch()`

**新增 degraded_flags**：`symlink_skipped`、`empty_dir_omitted`、`format_unsupported`

**Corner Cases**：

| Case | 行为 | 理由 |
|------|------|------|
| 符号链接 | 跳过 + 记录 `degraded_flags.symlink_skipped` + warn | 安全：防穿越 |
| Windows junction | 同上 | — |
| macOS .DS_Store | 默认忽略（内置 ignore 列表） | 噪音 |
| 空目录 | 记录到 `source_detail.empty_dirs`，不生成 hunk | 无法表达为 unified diff |
| binary 文件 | 跳过 + `degraded_flags.binary_only` | 复用现有策略 |
| 超大目录 (>50 文件变更) | `file_count_exceeded` + top-K 截断 | 复用现有策略 |
| 超大文件 (>1MB) | 跳过 + warn | 避免内存耗尽 |
| 同名不同大小写 (macOS/Win) | case-collision 检查 + warn | 跨平台一致性 |
| 嵌套 .git 目录 | 跳过 | 不递归进入子仓库 |
| 路径含空格/Unicode | pathlib 统一处理 | 跨平台 |
| 一侧目录不存在 | InputError | — |
| 两侧目录相同 | InputError "两个目录内容相同" | 友好错误 |
| 文件编码不一致 | charset 检测 + BOM sniffing，非 UTF-8 标记降级 | — |
| `.ahadiffignore` 规则 | 如果任一目录内有此文件，应用过滤 | 一致性 |

---

### J. `--patch-url URL`（远端 patch 下载）

**场景**：从 URL 获取 patch 文件并学习，覆盖 GitHub PR、GitLab MR、任意 .patch URL。

**source_kind**：新增 `patch_url`

**capability_level**：1（纯 patch，无本地仓库上下文）

**实现要点**：
```
用户输入                           内部处理
─────────────────────────────     ──────────────────────
github.com/.../pull/123      →   GET .../pull/123.patch
gitlab.com/.../merge_requests/5 → GET .../merge_requests/5.patch
any-host.com/fix.patch       →   GET fix.patch（直接下载）
                                      │
                                      ▼
                              redaction_pipeline()
                                      │
                                      ▼
                              parse_patch()（复用现有）
```

**URL 解析规则**：
```python
GITHUB_PR = re.compile(r"https?://([^/]+)/([^/]+)/([^/]+)/pull/(\d+)")
GITLAB_MR = re.compile(r"https?://([^/]+)/(.+?)/-/merge_requests/(\d+)")
# 非匹配 → 当作直接 .patch URL 下载
```

**认证配置**（`config.toml`）：
```toml
[remote]
# GitHub token（用于 private repo）
github_token_env = "GITHUB_TOKEN"   # 读取环境变量名
# GitLab token
gitlab_token_env = "GITLAB_TOKEN"
# 通用 Bearer token（其他平台）
default_token_env = ""
# Host allowlist（空=允许所有 HTTPS）
host_allowlist = []
# 最大下载大小
max_patch_size_mb = 10
```

**Corner Cases**：

| Case | 行为 | 理由 |
|------|------|------|
| private repo 无 token | 403 → InputError "需要 token，设置 GITHUB_TOKEN 环境变量" | 明确指引 |
| GitHub Enterprise (GHE) | URL parser 支持任意 host（`https://ghe.corp.com/org/repo/pull/1`） | 路径结构与 github.com 一致 |
| GitLab Self-hosted | 同上 | 路径结构一致 |
| 超大 PR (>100 文件) | 下载后在 capture 层 clip（复用 file_count_exceeded） | 防内存/token 耗尽 |
| 超大 patch (>10MB) | 下载中途中止 + InputError | max_patch_size_mb 保护 |
| URL 返回 HTML 而非 patch | Content-Type 检查，非 text/* 拒绝 | 防误用 |
| URL 返回 404 | InputError "PR/MR 不存在或无权限" | — |
| URL 返回 301/302 重定向 | httpx 自动跟随（最多 5 次） | — |
| 网络超时 | 30s 超时 + 重试 1 次 | — |
| 非 HTTPS URL | 拒绝 | 安全：不允许 HTTP 明文 |
| SSRF (内网 IP) | 检查解析后 IP 是否为私有地址，拒绝 | 安全 |
| rate limit (GitHub 429) | 解析 Retry-After 头，等待后重试 | 复用 provider 层策略 |
| patch 编码非 UTF-8 | charset 检测 + 转换 | — |
| 恶意 diff 载荷 (prompt injection) | 经 `redaction_pipeline()` 处理 | 复用 UNTRUSTED_DIFF 7 类边界 |
| `strict_local` 模式 | 拒绝所有远端获取 | 隐私一致性 |
| CI 环境 | 正常工作（有网络） | — |

---

### RunSource Schema 扩展（v0.2）

当前 v0.1 schema：
```python
class RunSource(BaseModel):
    source_kind: Literal[...]
    source_ref: str
    capability_level: Literal[1, 2, 3]
    degraded_flags: dict[str, bool]
```

v0.2 扩展（向后兼容）：
```python
class RunSource(BaseModel):
    source_kind: Literal[...]  # 保持，但不再无限扩展
    source_ref: str
    capability_level: Literal[1, 2, 3]
    degraded_flags: dict[str, bool]  # 扩展 keys
    # v0.2 新增
    source_detail: SourceDetail | None = None  # 可选扩展字段

class SourceDetail(BaseModel):
    transport: Literal["local", "remote"] = "local"
    content_format: Literal["unified_diff", "ipynb", "raw_text"] = "unified_diff"
    compare_scope: Literal["file", "dir"] | None = None
    origin_url: str | None = None
    content_hash: str | None = None  # 非 git 输入的内容指纹
    platform: Literal["github", "gitlab", "generic"] | None = None
    auth_method: Literal["token", "none"] | None = None
```

**新增 degraded_flags keys**（v0.2）：
- `symlink_skipped` — 跳过了符号链接
- `empty_dir_omitted` — 忽略了空目录
- `format_unsupported` — 文件格式不支持细粒度解析
- `encoding_fallback` — 文件编码非 UTF-8，使用了 fallback 解码
- `remote_partial_fetch` — 远端 patch 被截断下载

---

## v0.3 设计

### K. Notebook `.ipynb` Cell-Aware Diff

**场景**：数据科学家修改 Jupyter Notebook，标准 JSON 行级 diff 几乎无法阅读。

**前置条件**：需先完成 parser registry + anchor 模型升级（v0.3 前半）。

**核心设计**：
```
.ipynb 文件
    │
    ▼
JSON decode → 提取 cells[]
    │
    ▼
按 cell 对比 source 文本（忽略 output/metadata 噪音）
    │
    ▼
生成 virtual hunks（anchor_kind = notebook_cell）
    │
    ▼
正常进入 claim/evidence/quiz 流程
```

**Anchor 模型升级**：
```python
# 当前：只有 file:line
class EvidenceAnchor(BaseModel):
    file_id: str
    display_path: str
    line_start: int
    line_end: int

# v0.3 扩展：
class EvidenceAnchor(BaseModel):
    file_id: str
    display_path: str
    anchor_kind: Literal["file_line", "notebook_cell"] = "file_line"
    # file_line 模式
    line_start: int | None = None
    line_end: int | None = None
    # notebook_cell 模式
    cell_index: int | None = None
    cell_type: Literal["code", "markdown", "raw"] | None = None
    cell_source_hash: str | None = None  # 用于 staleness 检测
```

**Parser Registry**：
```python
# parser/registry.py
PARSERS: dict[str, DiffParser] = {
    ".py": UnifiedDiffParser,      # 默认
    ".ipynb": NotebookDiffParser,  # v0.3 新增
    # 未来可扩展：.sql, .proto 等
}

def get_parser(file_path: str) -> DiffParser:
    ext = Path(file_path).suffix.lower()
    return PARSERS.get(ext, UnifiedDiffParser)
```

**Corner Cases**：

| Case | 行为 | 理由 |
|------|------|------|
| output cell 含图片/HTML/JS | 忽略 output，只 diff source cell | 安全 + 学习价值低 |
| metadata 差异 (kernel/language) | 忽略或单独摘要（不生成 claim） | 噪音 |
| execution_count 变化 | 忽略 | 每次运行都变，纯噪音 |
| cell 重排序 | 检测移动（content hash 匹配） | 类似 git rename |
| 混合 patch (.py + .ipynb) | parser registry 分派 | 各文件用各自 parser |
| 超大 notebook (>100 cells) | cell_count_exceeded + top-K | 类似 file_count_exceeded |
| 无完整快照（Level 1 patch-only） | 降级为 JSON 行级 diff + `format_unsupported` | 无法建立 cell 锚点 |
| .ipynb 不是合法 JSON | 降级为文本 diff + warn | graceful fallback |
| nbformat v3 vs v4 差异 | 统一转为 v4 后对比 | — |

---

### L. `--url PR_URL`（平台 PR/MR 深度集成）

**基于 J（--patch-url）扩展**：除了下载 patch，还可以获取 PR 元数据。

**v0.3 新增能力**（在 J 基础上）：
- 获取 PR title + description → 写入 lesson 的 "变更背景" 章节
- 获取 review comments → 作为补充学习材料
- 获取 CI status → 写入 score.json 的 context

**不做**：
- 不创建/回复 PR comments（只读）
- 不深度集成 GitHub API v4/GraphQL（只用 REST）
- 不缓存 PR 元数据到本地

---

## 不做的场景（及理由）

| 场景 | 理由 |
|------|------|
| AI 聊天输出 (`--from-chat`) | 没有基准版本，无法定义 diff；无稳定 file:line 证据；用 `--patch -` 或 `--compare` 替代 |
| 远程文件对比 (`--compare url1 url2`) | 用户可先下载到本地再用 `--compare`；引入完整远端信任边界得不偿失 |
| SVN/Mercurial 原生支持 | `svn diff | ahadiff learn --patch -` 已覆盖；维护多 VCS 适配器不值得 |
| 剪贴板自动读取 | 跨平台权限模型不一致（macOS/Win/Linux）；隐私惊喜行为；用 `--patch -` 替代 |

---

## 对 Task DAG 的影响

### v0.1 影响（Task 5 已更新）

| Task | 改动 | 内容 |
|------|------|------|
| Task 0 | 补充 | `source_kind` 枚举新增 `git_staged_unstaged`（共 8 个值） |
| Task 5 | 补充 | 新增 `--unstaged` + `git show <sha>` 两种捕获模式（步骤 2 从 4 种扩展为 6 种），验收标准新增 3 条 |

### v0.2 新增 Task

| Task | 内容 | 依赖 |
|------|------|------|
| Task 5a | `--compare-dir` 目录递归对比 | Task 5（capture 层扩展） |
| Task 5b | `--patch-url` 远端 patch 下载 | Task 5 + Task 7（httpx 复用） |
| Task 0a | `SourceDetail` schema + `degraded_flags` 扩展 | Task 0 |

**⚠️ Ratchet 规则约束（Codex 审查冻结）**：v0.2 新增的 `--compare-dir`（source_kind=`file_compare`）和 `--patch-url`（source_kind=`patch_url`）均无 git ancestry，必须挂到与 v0.1 相同的 `has_git_ancestry == false → non_ratcheted` 规则。禁止通过 capability_level 或 source_ref 推断 ancestry 关系。此规则适用于所有未来新增的非 git 输入模式。

### v0.3 新增 Task

| Task | 内容 | 依赖 |
|------|------|------|
| Task 6a | Parser registry + `.ipynb` cell-aware parser | Task 6（parser 层扩展） |
| Task 8a | `EvidenceAnchor` 扩展 `notebook_cell` 锚点 | Task 8 + Task 6a |
| Task 5c | `--url` 平台 PR/MR 深度集成 | Task 5b（基于 --patch-url） |

---

## 版本路线图

```
v0.1（当前）
├── 8 种捕获方式 · 3 Levels
├── source_kind: 7 个枚举值
├── 统一 pipeline: capture → parse → redact → learn
└── degraded_flags: 4 种

v0.2
├── +2 种捕获（--compare-dir + --patch-url）= 10 种
├── SourceDetail 三维扩展
├── degraded_flags: +5 种 = 9 种
└── outbound fetch policy（host allowlist + SSRF）

v0.3
├── +2 种捕获（.ipynb + --url PR）= 12 种
├── parser registry
├── EvidenceAnchor 扩展（file_line + notebook_cell）
└── 平台 PR 元数据（只读）
```
