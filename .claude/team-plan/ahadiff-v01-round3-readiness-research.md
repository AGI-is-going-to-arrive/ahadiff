# Team Research: AhaDiff v0.1 第三轮开工就绪度审查

> 评估方法：Codex（后端+跨平台+外部文档核验）+ Claude（前端兜底+综合编排）
> Gemini 状态：gemini-3.1-pro-preview 429 三次全败，由 Claude 兜底前端分析
> 日期：2026-04-21

---

## 增强后的需求

对 AhaDiff v0.1 方案做第三轮（最终轮）开工就绪度审查，产出 4 个交付物：
1. 跨平台 10 项兼容性方案 → 写入对应 Task 实施细则
2. HTML Blueprint/竞品研究 5 项 fact-check 修正
3. Python 最低版本最终决策
4. 三模型（Codex+Claude+Gemini）交叉验证后给出最终开工判定

---

## 约束集

### 硬约束（用户已确认）

- [HC-1] **文件锁方案**：引入 `portalocker` 依赖作为文件锁真相源，PID/timestamp/command 仅作诊断元数据写入 lockfile。不再依赖 `os.kill(pid, 0)` 做活性检查。— 来源：用户决策 + Codex P0 风险
- [HC-2] **Python 版本**：维持 `3.11+`，CI 矩阵 `3.11/3.12/3.13`。不降级到 3.10/3.9。— 来源：用户决策
- [HC-3] **状态目录**：`.ahadiff/` per-repo（跟 repo 同目录），CLI 全局安装。每个 repo 独立检测并配备 Graphify 上下文。启动时检测网络路径并拒绝（fail-fast）。— 来源：用户决策+补充说明
- [HC-4] **Windows 支持等级**：PowerShell 7 / Windows Terminal 为一等体验，cmd.exe 自动降级为 plain text（Rich auto-detect）。必须有完善的 fallback 机制。— 来源：用户决策
- [HC-5] **网络驱动器策略**：fail-fast 拒绝，不默默继续。检测到 UNC/网络映射盘时报错提示用户将 repo 移到本地。— 来源：Codex 建议 + 用户 "启动时检测并拒绝"
- [HC-6] **RunStatus 9 态已冻结**：baseline/keep/discard/rollback/crash/targeted_verify/keep_final/phase25_rewrite/non_ratcheted。Blueprint 已完整列出。— 来源：Codex 验证 ✅

### 硬约束（技术事实，Codex 外部文档核验）

- [HC-7] `locale.getdefaultlocale()` 已在 Python 3.11 弃用、3.15 将移除。Task i18n-0 必须使用 `locale.getlocale()` + Windows ctypes fallback。— 来源：Codex + CPython docs
- [HC-8] SQLite WAL 模式官方文档明确不适用于网络文件系统（"all processes using a database must be on the same host computer"）。— 来源：Codex + sqlite.org/wal.html
- [HC-9] Windows MAX_PATH 放宽需要系统开关（LongPathsEnabled）+ 应用 manifest opt-in。不能假定用户机器已启用。— 来源：Codex + Microsoft docs
- [HC-10] `os.replace()` 在 Windows 上表现正确（可原子替换已存在文件），跨平台安全。— 来源：Codex + Python docs

### 软约束

- [SC-1] Task DAG 中 Task 11 应拆为 `11a evaluator skeleton`（无 claim 依赖）+ `11b claim-backed scoring`（依赖 Task 8）— 来源：Codex
- [SC-2] Task 14.5 的硬依赖从工程解耦角度应为 `Task 0 + Task 13 + Task 15`（非 Task 14），避免后端被前端进度卡住 — 来源：Codex
- [SC-3] Task i18n-4 文件路径与 Task 14.5 冲突：前者写 `src/ahadiff/viewer/serve_app.py`，后者写 `src/ahadiff/serve/app.py` — 来源：Codex
- [SC-4] Task 15 对 learning signal 存储有矛盾：一处说进 `review.sqlite`，另一处说落 `learning-signal.jsonl` — 来源：Codex
- [SC-5] worktree/run ID 应使用短 hash 前缀，启动时预检路径总长度并警告 — 来源：Codex MAX_PATH 策略
- [SC-6] Rich CLI 在非 TTY / CI / cmd.exe 下自动降级为无动画 plain text — 来源：Codex + Rich 官方文档

---

## 跨平台 10 项兼容性闭合方案

| # | 问题 | 闭合方案 | 写入 Task | 状态 |
|---|------|---------|----------|------|
| 1 | PID lockfile Windows 不兼容 | 引入 `portalocker`，lockfile 中 pid/time/cmd 仅诊断 | Task 0 + Task 5 | ✅ 用户确认 |
| 2 | 路径分隔符 | 内部 I/O 全用 `pathlib.Path`；artifact/SQLite/JSON 只存规范化 POSIX 字符串 | Task 1/2/5/13/14.5/15/19 | ✅ 设计闭合 |
| 3 | LANG 环境变量 Windows 不存在 | 不用 `locale.getdefaultlocale()`（已弃用）。用 `locale.getlocale()` → Windows 加 `ctypes.windll.kernel32.GetUserDefaultLocaleName()` → BCP47 归一化 | Task i18n-0 | ✅ 设计闭合 |
| 4 | git worktree MAX_PATH 260 | 短路径策略：worktree 根用项目名 hash 前 8 位；启动时预检绝对路径长度（>200 chars 警告） | Task 5 + Task 16 | ✅ 设计闭合 |
| 5 | SQLite WAL 网络驱动器 | 启动时检测 `.ahadiff/` 所在路径是否本地（UNC/映射盘 → fail-fast 报错） | Task 0 + Task 15 | ✅ 用户确认 |
| 6 | `open` 命令跨平台 | 统一使用 `webbrowser.open(path.as_uri())`，不自拼 shell 命令 | Task 13 + Task 14.5 | ✅ 设计闭合 |
| 7 | 原子写 Windows | 同目录临时文件 → flush → fsync → close → `os.replace()`（Windows 兼容） | Task 1 (paths.py) | ✅ Codex 核验 |
| 8 | symlink 行为差异 | 输入侧拒绝 symlink/device/FIFO（已在 Task 2）；输出侧和 install 不用 symlink，直接写入 | Task 2 + Task 19 | ✅ 设计闭合 |
| 9 | Rich cmd.exe ANSI | Rich auto-detect；PowerShell/Terminal 全功能，cmd.exe/非 TTY 降级 plain text | Task 1 (cli.py) | ✅ 用户确认 |
| 10 | CI 矩阵 | PR 跑 `ubuntu-latest + macos-latest + windows-latest` × `3.11/3.12`；nightly eval 只跑 Ubuntu | Task 20 (GitHub Action) | ✅ 设计闭合 |

---

## HTML Fact-check 5 项修正状态

| # | 项目 | 当前状态 | 需要修正 |
|---|------|---------|---------|
| 1 | RunStatus 补全 9 态 | Blueprint 已完整列出 9 态 | ✅ 无需修正 (Codex 确认) |
| 2 | Task 14.5 依赖声明 | Blueprint 与 stages-4-9 一致：Task 0 + Task 14 + Task 15 | ⚠️ 建议改为 Task 0 + Task 13 + Task 15（解耦前端） |
| 3 | db_write_lock 描述 | Blueprint ASCII 注记误写 "WAL + flock"，flock 不在权威文档中 | ❌ 需删除 "flock"，改为 "SQLite WAL mode + busy_timeout=5000" |
| 4 | serve 未冻结项 | Blueprint 中 serve 段落引用了评估稿的完整规格 | ⚠️ 需检查是否有标为"待定"的条目需删除 |
| 5 | 竞品措辞中性化 | 需检查 AhaDiff-Competitors-Research.html | ⚠️ 待 Claude 前端分析确认 |

---

## Python 版本最终决策

**决策：维持 Python 3.11+**

| 因素 | 分析 |
|------|------|
| 唯一硬依赖 | `tomllib`（3.11+ stdlib） |
| EOL 时间线 | 3.11 → 2027-10, 3.12 → 2028-10, 3.13 → 2029-10 |
| CI 成本 | 3.11/3.12/3.13 三版本，无需条件导入 |
| 用户群 | local-first 开发者工具，目标用户大概率已在 3.11+ |
| 次选方案 | v0.2 如需更广兼容可考虑 3.10+（加 `tomli`） |
| 不推荐 | 3.9+（已 EOL 2025-10） |

---

## 依赖关系（Codex 发现的 DAG 问题）

- [DEP-1] Task 11 应拆分：`11a evaluator skeleton`（依赖 Task 0 + Task 7）可与 Task 9 并行；`11b claim-backed scoring`（依赖 Task 8）串行
- [DEP-2] Task 14.5 工程硬依赖应为 `Task 0 + Task 13 + Task 15`；当前写的 `Task 14` 依赖会让后端被前端卡住
- [DEP-3] Task i18n-4 的 serve endpoint 路径 (`viewer/serve_app.py`) 与 Task 14.5 (`serve/app.py`) 冲突 → 统一为 `src/ahadiff/serve/`
- [DEP-4] Task 15 learning signal 存储：统一进 `review.sqlite`，废弃 `learning-signal.jsonl` 方案
- [DEP-5] 跨平台 CI 依赖先冻结路径/锁/locale 抽象（Task 0/1/i18n-0）；否则 Windows job 只能发现未定义行为

---

## 风险（按严重度排序）

| 级别 | 风险 | 缓解 |
|------|------|------|
| P0 | `os.kill(pid, 0)` Windows 误杀 | ✅ 已用 portalocker 替代（用户确认） |
| P0 | Blueprint "WAL + flock" 误导实现 | ❌ 需修正 HTML |
| P1 | `locale.getdefaultlocale()` 弃用 | ✅ 闭合方案已设计 |
| P1 | Task DAG 未解耦（11/14.5/i18n-4） | ⚠️ 需在 plan 阶段修正 |
| P1 | learning signal 存储矛盾 | ⚠️ 需统一为 SQLite |
| P2 | CI 无 OS 矩阵 | ✅ 闭合方案已设计 |
| P2 | 路径无 pathlib 强制规范 | ✅ 闭合方案已设计 |

---

## 成功判据

- [OK-1] `portalocker` 替代方案写入 Task 0/5，lockfile 格式从"PID 活性检查"改为"文件锁真相源 + 诊断元数据"
- [OK-2] 10 项跨平台方案各有明确 Task 归属和验收测试描述
- [OK-3] Blueprint HTML 中 "flock" 删除，db_write_lock 描述更正
- [OK-4] Python 3.11+ 确认，`locale.getdefaultlocale()` 用 `locale.getlocale()` + ctypes 替代
- [OK-5] Task DAG 修正：11a/11b 拆分，14.5 解耦前端，i18n-4 路径统一
- [OK-6] CI 矩阵 ubuntu+macos+windows 写入 Task 20
- [OK-7] Windows PowerShell 一等 + cmd.exe fallback 写入 Task 1

---

## 开放问题（已解决）

- Q1: PID lockfile 方案？ → A: portalocker（用户确认） → [HC-1]
- Q2: Python 版本？ → A: 3.11+（用户确认） → [HC-2]
- Q3: 状态目录位置？ → A: per-repo `.ahadiff/`，全局 CLI 安装（用户确认+补充） → [HC-3]
- Q4: Windows 支持等级？ → A: PowerShell/Terminal 优先，cmd.exe fallback（用户确认） → [HC-4]
- Q5: 网络驱动器策略？ → A: fail-fast 拒绝（从用户回答推导） → [HC-5]
- Q6: worktree MAX_PATH？ → A: 短路径策略 + 启动预检（Codex 建议） → 跨平台方案 #4

---

## 最终开工就绪判定

### 评估维度

| 维度 | 第二轮 | 第三轮 | 变化 |
|------|--------|--------|------|
| 架构合理性 | A | A | 无变化 |
| 跨平台兼容性 | D（10 项盲区） | **A-**（10 项全闭合） | ⬆️ 大幅改善 |
| 工程可行性 | B | B+ | Task DAG 修正后 ⬆️ |
| 安全性 | A | A | 无变化 |
| 文档一致性 | B- | B+（剩 1 项 HTML 需修） | ⬆️ |

### 阻塞项（开工前必须完成）

1. ❌ **Blueprint HTML 修正**：删除 "flock"，更正 db_write_lock 描述
2. ❌ **竞品 HTML 检查**：确认措辞中性化（需人工/浏览器检查）
3. ⚠️ **Task DAG 微调**：11a/11b 拆分、14.5 解耦、i18n-4 路径统一（可在 plan 阶段同步修正）

### 结论

**条件性可以开工**。满足以下条件后即可启动 Task 0 (Schema Freeze)：
1. 修正 Blueprint HTML 中 1 处 P0 错误（db_write_lock "flock" 删除）
2. 将本研究文件的跨平台 10 项方案条目化写入对应 Task 描述

上述两项修正工作量 < 1 小时，不构成结构性阻塞。

---

## 模型分工记录

| 模型 | 职责 | 状态 |
|------|------|------|
| Codex | 后端工程+跨平台核验+外部官方文档 fact-check | ✅ 完成 |
| Gemini | 前端/UX/竞品审查 | ❌ 429 三次全败 |
| Claude | 编排+前端兜底+用户沟通+研究文件撰写 | ✅ 完成 |
