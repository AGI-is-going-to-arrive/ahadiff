# Graphify 自动集成设计方案

> 补充 §21 (Graphify 集成)，解决原方案缺失的自动检测/安装/复用逻辑和前端降级策略。
>
> **v2 — 2026-04-20**：根据 Codex (60/100) + Claude (78/100) 交叉 review 修复 7 Critical + 6 Warning。

---

## 1. 设计原则

```text
不重复造轮子：AhaDiff 不重建 repo graph，只做 diff-level learning overlay
可选不强制：Graphify 是增强能力，不是核心功能的前置依赖
检测优先于安装：优先复用已有 graphify-out/，而非每次重新生成
静默降级：Graphify 不可用时，功能正常但图谱页面展示为"仅学习节点"模式
零耦合安装：AhaDiff 不在 pyproject.toml 中依赖 Graphify，纯运行时检测
安全同源：导入的 graph.json 必须经过与 diff 相同的 secret scan + sanitization
```

**重要备注**：Graphify 的 PyPI 包名是 `graphifyy`（双 y），CLI 命令名是 `graphify`。
Graphify 支持任意文件夹（不要求 git 仓库），详见 [官方文档](https://graphify.net/)。

---

## 2. Graphify 可用性检测流程

```text
ahadiff learn HEAD~1..HEAD --open
        │
        ▼
┌─────────────────────────┐
│ Step 1: 检测 graphify   │
│ 命令是否存在             │
│ (shutil.which)          │
└──────┬──────────────────┘
       │
  ┌────┴────┐
  │ 存在    │ 不存在
  ▼         ▼
┌──────┐  ┌──────────────────────────┐
│ OK   │  │ 检查 graphify-out/ 是否  │
└──┬───┘  │ 已有历史产物             │
   │      └──────┬───────────────────┘
   │        ┌────┴────┐
   │        │ 有产物  │ 无产物
   │        ▼         ▼
   │      ┌──────┐  ┌──────────────────────┐
   │      │复用   │  │ 纯学习节点模式       │
   │      │历史   │  │ (无 repo 上下文层)    │
   │      └──┬───┘  │ 提示用户可安装        │
   │         │      └──────────────────────┘
   ▼         ▼
┌─────────────────────────┐
│ Step 2: 检查产物新鲜度   │
│ graphify-out/graph.json │
│ 比较 graphify_meta.json │
│ 中记录的 import_head_sha│
│ 与当前 HEAD commit hash │
└──────┬──────────────────┘
       │
  ┌────┴──────┐
  │ 新鲜      │ 过期
  │ (import   │ (HEAD 已前进
  │  head ==  │  或 meta 文件
  │  HEAD)    │  不存在)
  ▼           ▼
┌──────┐    ┌──────────────────────┐
│ 直接 │    │ 提示可更新，不强制    │
│ 复用 │    │ "Graphify 产物较旧    │
└──────┘    │  (15 commits ago)     │
            │  建议 graphify . 更新"│
            └──────────────────────┘

注：新鲜度基于 .ahadiff/graphify_meta.json 中记录的
import_head_sha，不使用 file mtime（mtime 在 git checkout /
stash pop / CI artifact download 后不可靠）。
```

---

## 3. 安装策略：提示但不自动安装

### 3.1 为什么不自动安装

```text
1. 安全边界：AhaDiff 是 local-first 工具，自动 pip install 第三方包
   违反用户信任（参照 §17.2 LiteLLM 供应链风险教训）
2. 环境冲突：用户可能在 virtualenv / conda / system Python 中，
   自动安装可能写入错误环境
3. 版本锁定：Graphify 版本更新可能 breaking change，
   AhaDiff 不应承担版本兼容性维护
4. 权限问题：macOS/Linux 系统 Python 可能需要 sudo，
   自动安装会静默失败或要求提权
```

### 3.2 提示策略

```python
# graph/graphify_detect.py
from pydantic import BaseModel, Field
from pathlib import Path
from enum import Enum

class GraphifyState(str, Enum):
    """四级状态机，逐级严格"""
    NOT_FOUND = "not_found"       # 无命令、无产物
    DETECTED = "detected"         # 命令存在或产物存在，但未校验
    IMPORTABLE = "importable"     # 产物通过 schema + version 校验
    OPTIMAL = "optimal"           # importable + 新鲜（HEAD hash 匹配）

class GraphifyMeta(BaseModel):
    """持久化在 .ahadiff/graphify_meta.json"""
    import_head_sha: str          # 导入时的 git HEAD hash
    imported_at: str              # ISO 8601 时间戳
    graphify_version: str | None  # graphify --version 输出
    source_path: str              # graph.json 的 resolved 绝对路径
    node_count: int
    edge_count: int
    auto_detected: bool           # True=自动检测, False=手动 import
    sanitized: bool = False       # 是否已通过 secret scan

class GraphifyStatus(BaseModel):
    state: GraphifyState
    command_available: bool       # shutil.which("graphify") is not None
    output_exists: bool           # graphify-out/graph.json exists
    output_valid: bool = False    # JSON 可解析且有 nodes/edges
    output_version_ok: bool = False  # meta.version 在 SUPPORTED_VERSIONS 内
    output_fresh: bool = False    # import_head_sha == 当前 HEAD
    output_path: Path | None = None  # resolved（已解析 symlink）路径
    installed_version: str | None = None
    stale_reason: str | None = None
    meta: GraphifyMeta | None = None

    @property
    def usable(self) -> bool:
        """产物存在且通过校验（不要求新鲜）"""
        return self.state in (GraphifyState.IMPORTABLE, GraphifyState.OPTIMAL)

# 错误类型层级
class GraphifyNotFoundError(Exception): ...
class GraphifyImportError(Exception): ...
class GraphifyVersionError(GraphifyImportError): ...
class GraphifySchemaError(GraphifyImportError): ...
class GraphifyStaleWarning(UserWarning): ...
```

**路径处理规则**：所有路径构造必须使用 `pathlib.Path`，禁止字符串拼接。
`output_path` 存储 `Path.resolve()` 后的绝对路径（解析 symlink）。
如果 resolved 路径在 git root 之外，拒绝导入（防路径穿越）。

### 3.3 CLI 提示消息（通过 Rich 输出）

```text
场景 A — 首次使用，无 Graphify
┌──────────────────────────────────────────────────┐
│ 💡 Graphify 可增强学习图谱（repo 上下文层）       │
│                                                  │
│   pip install graphifyy && graphify .            │
│                                                  │
│ 当前以"仅学习节点"模式运行，核心功能不受影响。    │
│ 了解更多：ahadiff graph --help                   │
└──────────────────────────────────────────────────┘

场景 B — Graphify 已安装，但无产物
┌──────────────────────────────────────────────────┐
│ ℹ 检测到 Graphify (v0.3.2) 但未找到产物          │
│                                                  │
│   graphify .                                     │
│                                                  │
│ 运行后 AhaDiff 将自动导入 repo 上下文。           │
└──────────────────────────────────────────────────┘

场景 C — 产物存在但过期
┌──────────────────────────────────────────────────┐
│ ⚠ Graphify 产物较旧 (2026-04-17, 15 commits ago) │
│                                                  │
│   graphify .    # 更新                           │
│                                                  │
│ 当前使用历史产物继续，图谱可能缺少新文件。         │
└──────────────────────────────────────────────────┘

场景 D — 一切就绪
┌──────────────────────────────────────────────────┐
│ ✓ Graphify synced (v0.3.2, 2h ago, 48 nodes)     │
└──────────────────────────────────────────────────┘
```

### 3.4 提示频率控制

```text
首次提示（场景 A）：仅在第一次 ahadiff learn 时显示
后续提示：每 7 天最多显示一次（记录在 .ahadiff/graphify_prompt_ts）
强制静默：config.toml 中 graphify.prompt = false 可永久关闭提示
--quiet 模式：所有提示被抑制
```

---

## 4. 自动导入逻辑（`graphify_import.py`）

### 4.1 导入时机

```text
触发点 1：ahadiff learn ... --use-graphify
         → 显式请求，必须有可用产物，否则报错退出

触发点 2：ahadiff learn ... (无 flag)
         → 自动检测 graphify-out/graph.json
         → 存在则自动导入（opt-in by presence）
         → 不存在则跳过（静默降级）

触发点 3：ahadiff graph import <path>
         → 手动导入指定路径的 graph.json
         → 支持非标准路径（如 CI 产物、远程下载）

触发点 4：ahadiff graph refresh
         → 如果 graphify 命令可用，先运行 graphify .
         → 然后自动导入最新产物
```

### 4.2 导入流程

```text
graphify-out/graph.json
        │
        ▼
┌─────────────────────────┐
│ 0. 路径安全检查          │
│    Path.resolve() 后     │
│    必须在 git root 内    │
│    （防 symlink 穿越）    │
└──────┬──────────────────┘
       │
       ▼
┌─────────────────────────┐
│ 1. 校验 JSON schema     │
│    Pydantic 模型验证     │
│    GraphifyGraph(        │
│      meta: GraphifyMeta, │
│      nodes: list[Node],  │
│      edges: list[Edge])  │
└──────┬──────────────────┘
       │
       ▼
┌─────────────────────────┐
│ 2. 版本兼容性检查        │
│    读取 meta.version     │
│    对比已知兼容范围       │
│    (SUPPORTED_VERSIONS)  │
└──────┬──────────────────┘
       │
       ▼
┌─────────────────────────┐
│ 3. 安全过滤              │
│    复用 AhaDiff 现有     │
│    secret_scan +         │
│    prompt_injection 链   │
│    （与 diff context 同  │
│    一条 sanitization     │
│    pipeline）            │
└──────┬──────────────────┘
       │
       ▼
┌─────────────────────────┐
│ 4. 提取与 diff 相关的    │
│    子图 (graph.slice)    │
│    只保留 changed files  │
│    的 ±2 hop 邻居        │
│    文件名匹配需处理      │
│    rename/delete/路径    │
│    归一化 (见 4.4)       │
└──────┬──────────────────┘
       │
       ▼
┌─────────────────────────┐
│ 5. 写入 .ahadiff/runs/  │
│    <run>/graph/          │
│    graph.slice.json      │
│    graphify.links.json   │
│ 6. 更新 graphify_meta   │
│    记录 HEAD sha +       │
│    provenance 信息       │
└──────────────────────────┘
```

### 4.2.1 Pydantic 数据模型

```python
# graph/models.py

class GraphifyNodeMeta(BaseModel):
    type: str                    # "file", "function", "class", "module", etc.
    path: str | None = None      # 相对于 repo root 的文件路径
    language: str | None = None

class GraphifyNode(BaseModel):
    id: str
    label: str
    meta: GraphifyNodeMeta | None = None

class GraphifyEdge(BaseModel):
    source: str                  # node id
    target: str                  # node id
    relation: str = "related"    # "imports", "calls", "extends", etc.

class GraphifyFileMeta(BaseModel):
    version: str                 # Graphify schema 版本
    generated_at: str | None = None
    graphify_version: str | None = None

class GraphifyGraph(BaseModel):
    meta: GraphifyFileMeta
    nodes: list[GraphifyNode]
    edges: list[GraphifyEdge]

SUPPORTED_VERSIONS: list[str] = ["0.3", "0.4", "1.0"]
```

### 4.3 子图切片策略（graph.slice）

```text
输入：完整 graph.json (可能 500+ nodes)
      changed_files = ["src/client.ts", "src/types.ts"]

切片规则：
  1. 找到 changed_files 对应的节点
  2. 向外扩展 2 hop（可配置 graphify.slice_depth = 2）
  3. 保留扩展到的所有节点和边
  4. 标记节点来源：
     - "graphify_repo"  → 来自 Graphify 的 repo 上下文
     - "ahadiff_diff"   → AhaDiff 当前 diff 新增
     - "ahadiff_memory" → AhaDiff 历史学习节点

输出文件大小上限：graphify.max_slice_kb = 512
超过则按节点 degree（连接数）排序剪枝，保留连接最多的节点
（v0.1 使用 degree-count 而非 PageRank，避免引入 networkx/scipy 依赖）
TODO(v0.2): 升级为 PageRank 排序
```

### 4.4 文件路径匹配与归一化

```text
diff 中的 changed_files 与 graph.json 中的节点路径匹配需处理：

1. 路径归一化：
   - 统一使用 POSIX 分隔符 (/)，Windows 路径 (\) 自动转换
   - 去除前导 ./ 和尾部 /
   - 大小写：macOS/Windows 默认不敏感，Linux 敏感
     → 使用 Path.resolve() 后的实际路径

2. rename 处理：
   - diff 中有 rename (a/old.ts → b/new.ts)
   - 匹配时同时尝试 old_path 和 new_path
   - graph.json 可能只有其中一个（取决于生成时机）

3. delete 处理：
   - 被删除的文件在 graph.json 中可能仍存在
   - 标记为 "deleted_in_diff"，仍保留在切片中
   - 前端用删除线样式展示

4. 路径不匹配时：
   - 不静默丢弃，记录 warning：
     "⚠ graph.json 中未找到 src/foo.ts 对应节点，该文件将仅显示 diff 层"
   - 降级展示：该文件仅有 AhaDiff diff 节点，无 Graphify 上下文
```

---

## 5. 前端展示策略（三态降级）

### 5.1 三种展示模式

```text
模式 A：完整模式（Graphify + AhaDiff 学习节点）
  条件：graph.slice.json 存在且非空
  展示：
    - SVG 图谱：灰色(repo context) + 橙色(diff) + 绿色(concept) + 黄色(weak)
    - Graphify Source Card：显示 synced 状态、版本、导入时间
    - 过滤器：All / This Diff / From Graphify / Learning Memory / Weak Claims
    - 节点点击 → 展开详情面板

模式 B：仅学习节点模式（无 Graphify）
  条件：graph.slice.json 不存在或为空，但有学习数据
  展示：
    - SVG 图谱：仅橙色(diff files/symbols) + 绿色(concepts) 节点
    - Graphify Source Card：显示 "not connected" 状态
      └─ 内嵌提示："pip install graphifyy && graphify . 可解锁 repo 上下文层"
    - 过滤器：All / This Diff / Learning Memory / Weak Claims（隐藏 From Graphify）
    - 图谱仍然有价值：展示 diff → concept → claim 关系

模式 C：空图谱（首次运行，无任何数据）
  条件：无 graph.slice.json，无学习历史
  展示：
    - Empty State 占位图
    - 引导文案："完成第一次 ahadiff learn 后，学习图谱将在这里生长"
    - 可选：展示示例图谱的静态截图作为预览
```

### 5.2 前端数据注入

```text
data_bundle.json 中的 graph 字段：

{
  "graph": {
    "mode": "full" | "learning_only" | "empty",
    "graphify_status": {
      "connected": true,
      "version": "0.3.2",
      "imported_at": "2026-04-19T14:31:00",
      "stale": false,
      "node_count": 48,
      "edge_count": 71
    },
    "nodes": [...],     // graph.slice.json 内容
    "edges": [...],
    "filters": ["all", "this_diff", "from_graphify", "learning_memory", "weak"]
  }
}
```

### 5.3 Warm v6 模板变更

```text
graph 页面 Jinja2 模板需要处理三态：

{% if graph.mode == "full" %}
  {# 完整 SVG 图谱 + Graphify Source Card (synced) #}
{% elif graph.mode == "learning_only" %}
  {# 仅学习节点 SVG + Source Card (not connected) + 安装提示 #}
{% else %}
  {# Empty State 占位图 + 引导文案 #}
{% endif %}
```

---

## 6. config.toml 配置项

```toml
[graphify]
# 是否在 learn 时自动检测并导入 graphify-out/
auto_import = true          # 默认开启，检测到产物自动导入

# 子图切片深度（从 changed files 向外扩展的 hop 数）
slice_depth = 2             # 默认 2 hop

# 切片最大文件大小（KB），超过则按 degree-count 剪枝
max_slice_kb = 512

# 新鲜度判定：基于 .ahadiff/graphify_meta.json 中的
# import_head_sha 与当前 HEAD 比较，不使用 mtime
# （mtime 在 git checkout/stash/CI 后不可靠）

# 是否显示安装/更新提示
prompt = true               # false 则永久静默

# graphify-out 自定义路径（默认 ./graphify-out/）
output_dir = "graphify-out"

# graphify 命令的自定义路径（如果不在 PATH 中）
# command = "/usr/local/bin/graphify"
```

---

## 7. pyproject.toml 变更

```text
不添加 [graph] optional-dependencies。

理由：
1. 供应链安全：参照 §17.2 LiteLLM 教训，AhaDiff 不应将第三方
   工具的 PyPI 可用性和安全性绑定到自己的安装链上
2. 包名差异：Graphify 的 PyPI 包名是 graphifyy（双 y），
   CLI 命令名是 graphify，用户容易混淆
3. 版本耦合：Graphify 版本更新可能 breaking change，
   AhaDiff 不应承担版本兼容性维护

安装方式（文档引导，非自动依赖）：
  pip install ahadiff              → 核心功能
  pip install graphifyy            → 用户自行安装 Graphify（独立操作）
  graphify .                       → 用户自行运行生成产物
  ahadiff learn HEAD~1..HEAD       → 自动检测并导入产物（如果存在）

pyproject.toml 中 §27 无需修改。
```

---

## 8. CLI 命令变更

### 8.1 现有命令增强

```text
ahadiff learn <range> [--use-graphify | --no-graphify]
  --use-graphify   强制使用 Graphify（无产物则报错）
  --no-graphify    强制跳过 Graphify（即使产物存在）
  (默认)           auto_import=true 时自动检测
```

### 8.2 新增命令

```text
ahadiff graph status
  显示 Graphify 检测结果：
  - 命令是否可用、版本
  - 产物路径、最后更新时间、节点/边数量
  - 新鲜度评估
  - AhaDiff 学习节点数量

ahadiff graph refresh
  如果 graphify 命令可用：
    1. 运行 graphify .（子进程，继承 stdout，timeout=300s）
    2. 自动导入最新 graph.json
    3. 更新 graphify_meta.json
    4. 报告更新结果
  如果不可用：
    报错并提示安装方式：pip install graphifyy
  超时处理：
    subprocess.TimeoutExpired → 提示用户手动运行
    可配置：config.toml graphify.refresh_timeout = 300

ahadiff graph import <path>
  (现有命令，无变更)

ahadiff graph export
  (现有命令，无变更)
```

---

## 9. Corner Cases

### 9.1 Graphify 产物损坏

```text
场景：graphify-out/graph.json 存在但内容不是有效 JSON，
     或缺少 nodes/edges 字段

处理：
  1. graphify_import.py 校验失败
  2. 记录 warning 到 Rich 输出：
     "⚠ graphify-out/graph.json 格式异常，跳过图谱导入"
  3. 降级到"仅学习节点"模式
  4. 不删除用户的损坏文件（可能是 Graphify 的 bug，用户需要排查）
```

### 9.2 Graphify 版本不兼容

```text
场景：用户安装了 Graphify 新版本，graph.json schema 发生 breaking change

处理：
  1. graphify_import.py 检查 meta.version 字段
  2. 已知兼容范围：SUPPORTED_VERSIONS = ["0.3.x", "0.4.x"]
  3. 版本不在范围内：
     "⚠ Graphify v0.5.0 的产物格式尚未支持，跳过导入。
      建议：ahadiff 下个版本将适配，或降级 graphify 到 0.4.x"
  4. 降级到"仅学习节点"模式
```

### 9.3 graphify-out/ 在 .gitignore 中

```text
场景：用户将 graphify-out/ 加入 .gitignore，
     团队成员 clone 后没有这个目录

处理：
  1. AhaDiff 不依赖 graphify-out/ 在 git 中
  2. 每个开发者需自行运行 graphify .
  3. ahadiff graph status 会提示 "graphify-out/ 不存在"
  4. CI 环境：可在 CI pipeline 中加 graphify . 步骤
```

### 9.4 多 worktree / monorepo

```text
场景：用户使用 git worktree 或 monorepo，graphify-out/ 可能在不同位置

处理：
  1. 检测顺序：
     a. config.toml 中 graphify.output_dir（最高优先级）
     b. 当前 git 根目录下的 graphify-out/
     c. 当前工作目录下的 graphify-out/
  2. 如果都找不到，降级到"仅学习节点"模式
  3. monorepo 子包：用户可配置 graphify.output_dir = "../../graphify-out"
```

### 9.5 并发运行

```text
场景：用户在一个终端运行 graphify .（耗时较长），
     同时在另一个终端运行 ahadiff learn

处理：
  1. 尝试 json.loads() 读取 graph.json
  2. 如果解析失败 (JSONDecodeError)，说明文件正在被写入：
     a. 等待 2 秒后重试一次
     b. 仍失败则降级到"仅学习节点"模式
     c. 提示："ℹ graph.json 似乎正在更新，使用上一次的缓存继续"
  3. 不使用文件锁（Graphify 本身不创建 .lock 文件）
  4. POSIX 系统可选 fcntl.flock 共享锁（LOCK_SH），
     Windows 系统仅依赖 JSONDecodeError 重试
  5. 下次 learn 时自动获取最新产物
```

### 9.6 超大 graph.json

```text
场景：大型 monorepo 的 graph.json 可能 10MB+，包含 5000+ 节点

处理：
  1. 子图切片 (graph.slice) 限制：
     - max_slice_kb = 512 (默认)
     - 超过则按 degree-count 排序，保留连接最多的节点
  2. 前端 SVG 渲染限制：
     - 超过 200 节点时自动切换到 List View
     - 显示提示 "图谱节点过多，已切换到列表视图"
  3. data_bundle 内嵌策略：
     - graph 数据始终内嵌到 <script type="application/json"> 中
     - 不使用独立 JSON + fetch（遵守 §19 的 file:// viewer 约束：
       首版必须支持 file:// 直接打开，不依赖 HTTP 服务器）
     - 因此 max_slice_kb = 512 是硬上限，切片后超过仍需剪枝
     - TODO(v0.2): 引入 ahadiff serve 后可改为 fetch 加载
```

### 9.7 非 git 项目使用 Graphify

```text
场景：用户通过 --patch 或 --compare 使用 AhaDiff（非 git 项目），
     但仍想使用 Graphify

处理：
  1. Graphify 支持任意文件夹（不要求 git 仓库），
     用户可在非 git 项目中运行 graphify ./your-folder
  2. Source Capability Level 2 (workspace-grounded)：
     - graphify . 正常运行，产出 graphify-out/graph.json
     - ahadiff graph import 正常导入
     - 图谱功能完全可用
     - 但新鲜度检测无法使用 HEAD hash（因为没有 git）
       → 改用 graphify_meta.json 中的 imported_at 时间戳
       → freshness 退化为时间比较（默认 24h 窗口）
  3. Source Capability Level 1 (patch-grounded)：
     - graphify . 仍可运行（如果有文件夹上下文）
     - 但 changed_files 来自 patch，可能无法与 graph 节点匹配
       → 子图切片可能为空，降级到"仅学习节点"模式
     - ahadiff graph import <path> 手动导入仍可用
  4. 无文件夹上下文（纯 stdin patch）：
     - 图谱功能不可用（没有可关联的目录结构）
     - 静默降级到"仅学习节点"模式
```

### 9.8 config.toml 中 auto_import=false 但传了 --use-graphify

```text
场景：用户全局关闭了自动导入，但某次 learn 想用 Graphify

处理：
  1. CLI flag 优先级高于 config.toml
  2. --use-graphify 覆盖 auto_import=false
  3. --no-graphify 覆盖 auto_import=true
  4. 优先级：CLI flag > 环境变量 AHADIFF_GRAPHIFY > config.toml
```

### 9.9 Graphify 命令执行失败

```text
场景：ahadiff graph refresh 时，graphify . 子进程报错退出

处理：
  1. 捕获 subprocess 非零退出码
  2. 展示 Graphify 的 stderr 输出（不吞错误）
  3. 如果有历史产物，回退使用历史产物：
     "⚠ graphify . 执行失败 (exit code 1)，使用历史产物继续"
  4. 如果无历史产物，降级到"仅学习节点"模式
  5. 不重试（用户需要自己排查 Graphify 问题）
```

### 9.10 用户已有 .ahadiff/graph/ 但格式不匹配

```text
场景：用户从旧版 AhaDiff 升级，graph/ 目录结构或文件名变化

处理：
  1. graphify_import.py 只写入当前 run 目录：
     .ahadiff/runs/<run>/graph/
  2. 顶层 .ahadiff/graph.json 由 ahadiff graph export 生成
  3. 旧格式文件不影响新版运行
  4. migration 脚本（如需要）在 ahadiff upgrade 中处理
```

### 9.11 symlink 路径穿越

```text
场景：graphify-out/ 或 graph.json 是 symlink，
     指向 repo 外部的文件（monorepo 或恶意构造）

处理：
  1. Path.resolve() 解析 symlink 到真实路径
  2. 检查 resolved 路径是否在 git root（或 cwd）内
  3. 如果在外部，拒绝导入：
     "⚠ graphify-out/graph.json 指向仓库外部，已跳过导入"
  4. 记录 warning 到日志（安全事件）
```

### 9.12 graph refresh 子进程超时

```text
场景：ahadiff graph refresh 时，graphify . 在超大 repo 上
     运行时间过长（挂起或无限循环）

处理：
  1. subprocess.run(..., timeout=300)（5 分钟上限）
  2. 超时则 TimeoutExpired 异常：
     "⚠ graphify . 执行超时 (>5min)，请手动运行或检查仓库大小"
  3. 如果有历史产物，回退使用历史产物
  4. 用户可通过 config.toml graphify.refresh_timeout = 600 调整
```

### 9.13 graph.json 中的安全敏感内容

```text
场景：Graphify 的 graph.json 包含 semantic extraction / inferred edges，
     可能泄露源码结构甚至嵌入代码片段

处理：
  1. 导入时复用 AhaDiff learn 流程的 sanitization pipeline：
     a. secret_scan：检查节点 label/path 中是否含 API key / token 模式
     b. prompt_injection_escape：graph 数据进入 LLM prompt 前需转义
     c. .ahadiffignore 过滤：匹配的路径节点不导入
  2. graphify_meta.json 记录 sanitized: true/false
  3. 如果 sanitization 发现问题，记录到 audit.private.jsonl
  4. 前端 Source Card 展示 sanitization 状态
```

### 9.14 Graphify 卸载后残留产物

```text
场景：用户曾安装 Graphify 并生成过产物，后来卸载了 Graphify

处理：
  1. graphify-out/ 仍然存在，graph.json 仍可导入
  2. GraphifyStatus.command_available = False
  3. GraphifyStatus.state = IMPORTABLE（不是 OPTIMAL，因为无法 refresh）
  4. 提示："Graphify 未安装但有历史产物，使用历史数据继续"
  5. ahadiff graph refresh 会报错提示安装
  6. 产物会逐渐过期（HEAD hash 不匹配），但不影响使用
```

---

## 10. 安全信任边界

```text
graph.json 是一个新的外部输入通道，必须与 diff/repo files 同等对待：

┌──────────────────────────────────────────────────┐
│               AhaDiff Trust Boundary              │
│                                                  │
│  ┌──────────┐  ┌───────────┐  ┌──────────────┐  │
│  │ git diff  │  │ repo      │  │ graph.json   │  │
│  │ (trusted) │  │ files     │  │ (external)   │  │
│  └────┬─────┘  └─────┬─────┘  └──────┬───────┘  │
│       │              │               │           │
│       ▼              ▼               ▼           │
│  ┌─────────────────────────────────────────────┐ │
│  │         Sanitization Pipeline               │ │
│  │  1. .ahadiffignore filter                   │ │
│  │  2. secret_scan (regex patterns)            │ │
│  │  3. prompt_injection_escape                 │ │
│  │  4. size_limit_check                        │ │
│  └─────────────────────────────────────────────┘ │
│       │              │               │           │
│       ▼              ▼               ▼           │
│  ┌─────────────────────────────────────────────┐ │
│  │         Context Pack → LLM Prompt           │ │
│  └─────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────┘

graph.json 的 provenance 记录在 graphify_meta.json：
  - source_path: 导入时的文件路径
  - auto_detected: true/false
  - sanitized: true/false
  - import_head_sha: 导入时的 git HEAD
  - graphify_version: 生成工具版本
```

---

## 11. 日志策略

```text
结构化日志（Python logging 模块）与 Rich 控制台并存：

| 级别    | 场景                          | 输出方式       |
|---------|-------------------------------|---------------|
| DEBUG   | 检测路径、版本、切片统计       | 仅日志文件     |
| INFO    | 导入成功、状态变更             | 日志 + Rich    |
| WARNING | 产物过期、格式异常、降级       | 日志 + Rich    |
| ERROR   | 子进程失败、schema 不兼容      | 日志 + Rich    |

日志文件：.ahadiff/logs/graphify.log（追加写入）
CI 模式（--ci）：输出 JSON 结构化日志到 stdout
```

---

## 12. 测试策略

```text
单元测试（graphify_detect.py）：
  - test_detect_no_graphify_no_output → state == NOT_FOUND
  - test_detect_command_only → state == DETECTED, usable == False
  - test_detect_output_valid_fresh → state == OPTIMAL
  - test_detect_output_valid_stale → state == IMPORTABLE, stale_reason 非空
  - test_detect_output_invalid_json → state == DETECTED（有产物但不可导入）
  - test_detect_custom_output_dir → 读取 config.toml 路径
  - test_detect_symlink_outside_root → 拒绝导入，记录 warning
  - test_detect_graphify_uninstalled_with_output → state == IMPORTABLE

单元测试（graphify_import.py）：
  - test_import_valid_graph → 生成 graph.slice.json + graphify_meta.json
  - test_import_invalid_json → GraphifySchemaError，降级
  - test_import_unsupported_version → GraphifyVersionError，降级
  - test_import_large_graph_degree_pruning → 超过 max_slice_kb 时按 degree 剪枝
  - test_import_concurrent_write_retry → JSONDecodeError 后重试一次
  - test_import_rename_path_fallback → old/new path 均尝试匹配
  - test_import_delete_file_preserved → 已删除文件标记 deleted_in_diff
  - test_import_sanitization → secret scan + prompt injection escape
  - test_import_symlink_traversal_blocked → 路径穿越拒绝
  - test_import_non_git_folder → 时间戳 freshness fallback

集成测试：
  - test_learn_with_graphify_auto_import → 端到端
  - test_learn_without_graphify_graceful → 降级不影响核心流程
  - test_graph_refresh_success → 子进程 + 导入 + meta 更新
  - test_graph_refresh_failure → 错误处理 + 历史产物回退
  - test_graph_refresh_timeout → 5min 超时处理
  - test_learn_staged_diff_with_graphify → --staged 场景

前端测试（viewer）：
  - test_graph_page_full_mode → 三种节点颜色 + 全部过滤器
  - test_graph_page_learning_only → 无灰色节点 + 安装提示 + 隐藏 From Graphify
  - test_graph_page_empty → Empty State 占位图
  - test_graph_page_large_graph_list_fallback → >200 节点自动切换列表
  - test_graph_data_inline_not_fetch → 数据在 <script> 中而非独立 JSON
```

---

## 13. 与现有方案的对齐

```text
§7 命令表：新增 ahadiff graph status / refresh（需同步回主方案）
§8 learn 流程：step 2 (Context Layer) 增加 Graphify 检测 + sanitization 步骤
§17 LLM provider：无冲突（Graphify 不使用 LLM）
§19 viewer：前端三态模板化，graph 数据始终内嵌（遵守 file:// 约束）
§21 原 Graphify 集成：本方案是其具体实现规格
§27 pyproject.toml：无修改（Graphify 不作为依赖项）
前端设计手册 §2.5：Graph 页面三态降级对齐
CLAUDE.md 灵感项目：Graphify 定位不变（repo-level map）
Warm v6 原型 L1845：原型中 import 命令参数需修正
  （原型写 GRAPH_REPORT.md，实际应为 graph.json）
```

---

## 14. Review 修复记录

```text
Codex Review (60/100) — 2026-04-20
  [C-fix] PyPI 包名 graphify → graphifyy（CLI 名仍为 graphify）
  [C-fix] 删除 graph.data.json + fetch，改为内嵌（遵守 §19 file:// 约束）
  [C-fix] 9.7 修正：Graphify 支持任意文件夹，不要求 git
  [C-fix] 新增安全信任边界 §10（sanitization pipeline + provenance）
  [W-fix] 删除 ahadiff docs graphify（命令不存在），改为 graph --help
  [W-fix] 新鲜度改为 HEAD hash 比较，不用 mtime
  [W-fix] 新增 §4.4 路径归一化（rename/delete/Windows/大小写）
  [W-fix] GraphifyStatus 四级状态机（NOT_FOUND/DETECTED/IMPORTABLE/OPTIMAL）
  [W-fix] PageRank → degree-count（v0.1），defer PageRank to v0.2
  [W-fix] 标注 Warm v6 原型 L1845 import 命令参数需修正

Claude Review (78/100) — 2026-04-20
  [C-fix] 删除 [graph] optional-dep（供应链安全）
  [C-fix] 新增 Pydantic 数据模型（§4.2.1）
  [C-fix] mtime → HEAD hash（graphify_meta.json）
  [W-fix] 新增错误类型层级（5 个异常类）
  [W-fix] 并发检测改为 JSONDecodeError 重试（不依赖 .lock 文件）
  [W-fix] 新增 Windows pathlib.Path 强制规则
  [W-fix] 新增 §9.11 symlink 路径穿越防护
  [W-fix] 新增 §11 日志策略
  [I-note] graph refresh 新增 subprocess timeout=300
  [I-note] 新增 §9.12-9.14 corner cases
```
