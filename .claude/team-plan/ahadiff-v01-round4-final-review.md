# AhaDiff v0.1 第四轮终审报告

> 审查模型：Claude Opus 4.6 (编排+综合) + 3 并行探索代理
> 日期：2026-04-21
> 判定：**GO**（初判 CONDITIONAL GO，经 5 轮 Codex+Claude 交叉审查迭代修复后升级为 GO）

---

## 最终判定：CONDITIONAL GO → GO

**C-1 经复核降级为 Info，C-2 已修复（concepts.jsonl 已归入 Task 10 step 7-8）。0 Critical 阻塞项。**

Task 0 (Schema Freeze) **今日可立即开始**。

---

## Critical（阻塞开工）— 全部已解决

### C-1: ~~macOS 全局配置路径冲突~~ → 降级为 Info（非真实冲突）

- **初判**：`ahadiff-v01-kickoff.md` Task 1 step 2 写 `~/Library/Application Support/ahadiff/`，但 `ahadiff-data-scope-architecture.md` 目录概览写 `~/.config/ahadiff/`
- **复核结论**：**非冲突**。data-scope 文档用 Linux 路径做跨平台抽象示意，kickoff Task 1 step 2 已明确三平台实际路径（Linux `~/.config/`，macOS `~/Library/Application Support/`，Windows `%APPDATA%/`），由 `global_config_dir()` 函数统一处理。CLAUDE.md 也用函数调用表述。
- **行动**：在 data-scope 文档目录结构注释中补充 "(示意路径，实际由 platformdirs 决定)" 即可
- **影响**：不阻塞开工

### C-2: concepts.jsonl 无 Task 归属

- **问题**：changelog 2026-04-20 ~15:00 声明 "concepts.jsonl branch-aware 方案提前到 v0.1"，但 Task 9-20 中无专属 Task，仅有 `src/ahadiff/wiki/concepts.py` 估算（~120-180 行）
- **影响**：实现无人负责，可能在集成时才发现缺失
- **修复方案**：将 concepts.jsonl 实现并入 Task 10 (Quiz/SRS)，作为 step 7-8 追加。理由：concepts 与 learning layer 强相关，且 quiz 生成可引用 concepts
- **状态**：✅ 已修复（Task 10 step 7-8 已添加，含 non-git 输入守卫）

---

## Warning（各 Task 启动前修复）

| ID | 问题 | 阻塞 Task | 修复方案 |
|----|------|-----------|---------|
| W-1 | Task 14.5 依赖需含 Task 15 | Task 14.5 | ✅ 已修复：依赖改为 Task 0 + Task 13 + Task 15（signals 路由需 DB schema）；Stage 归属从 Stage 4 移至 Stage 5 解决跨 Stage 死锁 |
| W-2 | Task 15 仍写 learning-signal.jsonl | Task 15 | ✅ 已修复：stages-4-9.md 改为 review.sqlite |
| W-3 | Task i18n-4 文件路径冲突 | i18n-4 | ✅ 已修复：统一为 `src/ahadiff/serve/app.py` |
| W-9 | Blueprint HTML 仍引用旧 learning-signal.jsonl + 旧 Task 14.5 依赖 | Task 0 前 | 需单独更新 AhaDiff-Blueprint.html（大文件，独立 commit） |
| W-4 | Task 11 应拆分 11a/11b | Layer 4 | 11a=evaluator skeleton(仅依赖 Task 0)，11b=claim-backed scoring(依赖 Task 8) |
| W-5 | OrchestratorCommand/Result 字段未定义 | Task 0 完成 | 在 Task 0 执行过程中补齐 DTO 字段 |
| W-6 | ServeApp response schema 缺失 | Task 0 完成 | Task 0 step 14 补充 API response 结构 |
| W-7 | EvaluationBundle hash 算法未指定 | Task 11 | 建议：SHA-256(sorted concatenation of 5 files, `\n---\n` separator) |
| W-8 | 5 项跨平台验收标准缺失 | 各自 Task | 补充 pathlib/locale/path-length/atomic-write/Rich 的可测标准 |

---

## 新发现的 Corner Cases（本轮新增 CC-GAP）

| ID | 场景 | 风险 | v0.1 处置 |
|----|------|------|-----------|
| CC-GAP-1 | 多终端并发 serve | Medium | 端口冲突直接报错即可 |
| CC-GAP-2 | LLM 调用中途网络断开 | **High** | 标记 `crash` + 记录已消耗 token 到 UsageEvent |
| CC-GAP-3 | SQLite 静默损坏 | Medium | 启动时 `PRAGMA integrity_check`（首次写操作前） |
| CC-GAP-4 | 用户 diff 捕获期间 git 操作 | Medium | diff 一次性捕获到内存，后续不再读 git |
| CC-GAP-5 | >10k 行 diff token 预算分配 | Low | budget.py 按文件重要度截断，已有 degraded_flags |
| CC-GAP-6 | 二进制文件在 diff 中 | Low | 跳过 + warn + 设置 degraded_flag |
| CC-GAP-7 | 单 commit 仓库 | Low | 检测 `git rev-parse HEAD~1` 失败 → 提示用 `--patch` |
| CC-GAP-8 | 子模块 diff | Low | v0.1 跳过子模块指针变更 |
| CC-GAP-9 | Merge commit 多父节点 | Low | 默认 first-parent diff，可 `--parent=N` 覆盖 |
| CC-GAP-10 | 文件路径 Unicode | Medium | pathlib + NFKC 归一化 |
| CC-GAP-11 | Symlink 目标越界 | Low | `.resolve()` 后检查是否在 repo 内 |
| CC-GAP-12 | 空 diff | Low | 早退 + 提示 "no changes to learn from" |
| CC-GAP-13 | .ahadiff 只读 | Low | 创建前检查写权限，报人类可读错误 |

**高优先级**：CC-GAP-2 需要在 Task 7 (Provider) 中显式处理 mid-stream failure。

---

## 过度工程化警告（建议 v0.1 简化）

| CC | 当前方案 | 建议简化为 |
|----|---------|-----------|
| CC-NEW-6 (Archive Bomb) | 完整 `safe_extract()` + ArchivePolicy | 二进制/archive 文件直接 skip（1 行检查） |
| CC-NEW-8 (Static Button) | 5 个 data-* 属性 + JS 检测 + CSS | disabled + tooltip "requires ahadiff serve" |
| CC-NEW-7 (Locale Middleware) | 完整 Starlette middleware | `request.cookies.get("lang") or "en"` |
| CC-NEW-3 (Redaction Anchor) | 三模式条件写入 | v0.1 始终存完整路径（local-only） |

---

## karpathy-skills 可借鉴模式

| 模式 | 应用到 AhaDiff | 具体落地 |
|------|---------------|---------|
| 可追溯性测试 | Claim Verification | 每条 claim 必须 trace 到 file:line（已有，强化） |
| Step → verify: check 结构 | Evaluation Rubric | 8 维评分各配具体验证方法（可补充到 rubric.yaml） |
| Before/After 对比范例 | Benchmark 数据集 | Task 18 的 10 份 diff 增加 "bad explanation" 对照 |
| 简洁性自检门禁 | conciseness 维度 | 加入 token/信息密度比率检查 |
| 多平台分发模式 | CLI 接入扩展 | CLAUDE.md/GEMINI.md/AGENTS.md 同源分发（已有） |
| "Surgical changes" 原则 | diff_coverage 维度 | 标记 drift（无关变更）作为扣分项 |

---

## 工期风险评估

| 风险因素 | 影响 | 缓解 |
|---------|------|------|
| Task 8 (Claim) 复杂度最高 | +1-2 天 | 拆为 8a(结构化提取) + 8b(模糊匹配验证) |
| Gemini 持续 429 | 前端审查质量降 | Claude 兜底已确认有效 |
| i18n "并行" 实为渗透 | +2 天集成 | 延后 i18n 到 Layer 7 完成后串行 |
| Task 16/17 git worktree | +1 天调试 | 优先实现 happy path，edge case 后补 |

**实际估计**：14-16 天（原估 11-12 天偏乐观）

---

## Task 0 今日可执行性

**结论：YES**，无阻塞项，立即可开始。

**前置条件检查**：
- [x] 设计决策冻结（9 条全部 user-confirmed）
- [x] 技术栈确定（Python 3.11+, typer, rich, pydantic, etc.）
- [x] 数据范围架构确定（per-repo truth）
- [x] 跨平台方案确定（portalocker, pathlib, platformdirs）
- [x] 全局路径统一（C-1 复核为非冲突：data-scope 用 `global_config_dir()` 函数表述，kickoff Task 1 列三平台实际路径）
- [x] EvaluationBundle hash 可在 Task 0 过程中决定

**Task 0 产出物**：
1. `src/ahadiff/schema/` 目录 with Pydantic models
2. `doc/contract-freeze.md` 冻结记录
3. 通过 `pytest tests/test_schema.py` 验证 import + 序列化

---

## 阶段门禁要求（新增）

每完成一个 Stage/Phase 后，**必须**执行跨模型交叉审查门禁：

1. **Codex CLI** — 代码正确性 + 边界条件 + 测试覆盖
2. **Claude** — 架构一致性 + 文档同步 + 集成点验证
3. **Gemini CLI** — 前端/UX 评审（429 时 Claude 兜底）

门禁通过标准：0 Critical + 0 High → 进入下一 Stage。
